"""Ansicht für das Frontend: je Receiver die verbundenen Controller samt Zusatzdaten.

Reine Logik ohne Ein-/Ausgabe. Die Anwesenheit eines Controllers kommt aus zwei Quellen:
  - "monitor": usbmon-Mitschnitt (am Gerät bestätigt), nur bei eingeschaltetem Monitor;
  - "sysfs": von xpad angelegtes Eingabegerät (aus dem Quelltext abgeleitet, am Gerät ungeprüft).
Zusätzlich gilt: Eine LED `xpadN` existiert nur bei verbundenem Controller (am Gerät bestätigt).
Gibt es mehr LEDs als erkannte Controller, steht der Rest in `unlocated_count`.

LED-Zuordnung (Vorgabe des Nutzers, an seinem Gerät beobachtet: xpad0 = Controller 1, xpad1 =
Controller 2 …): Die LEDs eines Receivers werden nach Nummer sortiert und den Controllern nach
Slot-Reihenfolge zugeordnet, sofern ihre Anzahl übereinstimmt. xpad und der Receiver vergeben
LED-Nummer und Slot beide nach „kleinste freie“, bei einem Receiver bleiben sie dadurch im Gleichschritt.
Bei mehreren Receivern teilen sie sich die LED-Nummern; dann kann die Reihenfolge abweichen, und die
Zuordnung ist nicht gesichert.
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
            for controller, name in zip(controllers, leds):  # controllers sind nach Slot sortiert
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
    """Setzt den aktiv abgefragten Akkustand ein, wenn er neuer ist als der des Monitors (oder dieser fehlt)."""
    entry = (cached or {}).get(key)
    if entry is None:
        return
    monitor_age = data.get("state_age_s")
    if data.get("battery_level") is not None and monitor_age is not None and monitor_age <= entry["age_s"]:
        return  # der Monitor hat einen neueren Wert
    data["battery_level"] = entry["battery_level"]
    data["battery_type_raw"] = entry["battery_type_raw"]
    data["power_state_raw"] = entry["power_state_raw"]
    data["state_age_s"] = entry["age_s"]
    data["state_source"] = "query"


def connected_targets(views: Iterable[dict]) -> List[Tuple[int, int, int]]:
    """(Bus, Gerät, Slot) aller Controller, deren Slot bekannt ist. Anders als `plan_targets` ohne Raten."""
    return [
        (view["bus"], view["devnum"], controller["slot"])
        for view in views
        if view.get("bus") is not None and view.get("devnum") is not None
        for controller in view["controllers"]
    ]


def plan_targets(views: Iterable[dict]) -> List[Tuple[int, int, int]]:
    """(Bus, Gerät, Slot) aller Controller, die ausgeschaltet werden sollen.

    Ist bekannt, welche Slots belegt sind, nur diese. Ist nur bekannt, dass irgendwo ein Controller
    verbunden ist (LED vorhanden, Slot unbekannt), alle vier Slots dieses Receivers.
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
