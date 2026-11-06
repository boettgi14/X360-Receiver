"""View for the frontend: per receiver, the connected controllers plus extra data.

Pure logic without input/output. A controller's presence comes from two sources:
  - "monitor": usbmon capture (confirmed on the device), only while the monitor is on;
  - "sysfs": the input device xpad creates (derived from the source code, unchecked on the device).
In addition: A LED `xpadN` exists only while a controller is connected (confirmed on the device).
If there are more LEDs than detected controllers, the rest goes into `unlocated_count`.

LED assignment (as observed on the user's device: xpad0 = controller 1, xpad1 = controller 2 …):
A receiver's LEDs are sorted by number and assigned to the controllers in slot order, provided
their counts match. xpad and the receiver both hand out LED number and slot as "smallest free", so
with one receiver they stay in step. With several receivers they share the LED numbers; then the
order can differ, and the assignment is not guaranteed.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

from .discovery import ReceiverInfo
from .monitor import SLOT_COUNT, blank_slot_dict


def build_receiver_views(
    receivers: Iterable[ReceiverInfo],
    monitor_snapshot: List[dict],
    led_owners: Dict[str, List[str]],
    sysfs_slots: Dict[str, Set[int]],
    cached_batteries: Optional[Dict[Tuple[int, int, int], dict]] = None,
) -> List[dict]:
    by_key: Dict[Tuple[int, int], List[dict]] = {
        (entry["bus"], entry["devnum"]): entry["slots"] for entry in monitor_snapshot
    }
    views: List[dict] = []
    for receiver in receivers:
        monitor_slots = by_key.get((receiver.bus, receiver.devnum)) if receiver.bus is not None else None
        from_sysfs = sysfs_slots.get(receiver.usb_path, set())
        controllers: List[dict] = []
        for index in range(SLOT_COUNT):
            data = dict(monitor_slots[index]) if monitor_slots else blank_slot_dict(index)
            sources = []
            if data["connected"]:
                sources.append("monitor")
            if index in from_sysfs:
                sources.append("sysfs")
            if not sources:
                continue
            data["connected"] = True
            data["detected_by"] = sources
            data["led"] = None
            _apply_cached_battery(data, (receiver.bus, receiver.devnum, index), cached_batteries)
            controllers.append(data)

        leds = sorted(led_owners.get(receiver.usb_path, []), key=lambda name: int(name[4:]))
        unassigned: List[str] = leds
        if controllers and len(controllers) == len(leds):
            for controller, name in zip(controllers, leds):  # controllers are sorted by slot
                controller["led"] = name
            unassigned = []

        view = receiver.to_dict()
        view.update(
            {
                "controllers": controllers,
                "unassigned_leds": unassigned,
                "unlocated_count": max(0, len(leds) - len(controllers)),
                "slot_count": SLOT_COUNT,
            }
        )
        views.append(view)
    return views


def _apply_cached_battery(data: dict, key: Tuple, cached: Optional[Dict[Tuple[int, int, int], dict]]) -> None:
    """Uses the actively queried battery level if it is newer than the monitor's (or the monitor has none)."""
    entry = (cached or {}).get(key)
    if entry is None:
        return
    monitor_age = data.get("state_age_s")
    if data.get("battery_level") is not None and monitor_age is not None and monitor_age <= entry["age_s"]:
        return  # the monitor has a newer value
    data["battery_level"] = entry["battery_level"]
    data["battery_type_raw"] = entry["battery_type_raw"]
    data["power_state_raw"] = entry["power_state_raw"]
    data["state_age_s"] = entry["age_s"]
    data["state_source"] = "query"


def connected_targets(views: Iterable[dict]) -> List[Tuple[int, int, int]]:
    """(bus, device, slot) of all controllers whose slot is known. Unlike `plan_targets`, without guessing."""
    return [
        (view["bus"], view["devnum"], controller["slot"])
        for view in views
        if view.get("bus") is not None and view.get("devnum") is not None
        for controller in view["controllers"]
    ]


def plan_targets(views: Iterable[dict]) -> List[Tuple[int, int, int]]:
    """(bus, device, slot) of all controllers that should be turned off.

    If it is known which slots are occupied, only those. If it is only known that a controller is
    connected somewhere (LED present, slot unknown), all four slots of that receiver.
    """
    targets: List[Tuple[int, int, int]] = []
    for view in views:
        bus, devnum = view.get("bus"), view.get("devnum")
        if bus is None or devnum is None:
            continue
        if view["controllers"]:
            slots = [c["slot"] for c in view["controllers"]]
            if view["unlocated_count"] > 0:
                slots = list(range(view["slot_count"]))
        elif view["unlocated_count"] > 0:
            slots = list(range(view["slot_count"]))
        else:
            slots = []
        targets.extend((bus, devnum, slot) for slot in slots)
    return targets
