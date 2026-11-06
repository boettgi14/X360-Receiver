"""State per receiver and slot, fed from usbmon records.

Pure logic: no input/output, no threads. The caller supplies the time (`now`).

Privacy:
  - Records of foreign devices are discarded immediately (only watched (bus, device) pairs).
  - The controller's input packets are only counted. Buttons, sticks and triggers are never
    stored. For unknown packets only the first 5 header bytes are counted, never the payload
    (with a chatpad, keystrokes appear in the payload).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .protocol import (
    SUBTYPE_NAMES,
    ConnectionEvent,
    InputReport,
    LinkReport,
    StateReport,
    UnknownReport,
    decode_in_packet,
)
from .usbmon import UsbmonRecord

SLOT_COUNT = 4
MAX_UNKNOWN_KINDS = 32
# Controller interfaces use the odd endpoints 1, 3, 5, 7 (even = audio)
CONTROLLER_ENDPOINTS = (1, 3, 5, 7)

DeviceKey = Tuple[int, int]  # (bus, device address)


@dataclass
class SlotState:
    slot: int
    connected: bool = False
    connected_inferred: bool = False  # True if concluded from traffic only
    connected_at: Optional[float] = None
    headset: bool = False
    chatpad: bool = False
    subtype: Optional[int] = None
    protocol: Optional[int] = None
    revision: Optional[int] = None
    link_at: Optional[float] = None
    battery_level: Optional[int] = None  # raw 0..3, mapping to percent unchecked
    battery_type_raw: Optional[int] = None
    power_state_raw: Optional[int] = None
    vibration_level: Optional[int] = None
    state_at: Optional[float] = None
    # "report": state packet (also in the header of an input packet); "link": from the link report only.
    # When xpad re-binds, the link report is byte-identical to earlier ones; freshness unclear.
    state_source: Optional[str] = None
    input_count: int = 0
    last_input_at: Optional[float] = None
    last_led_mode: Optional[int] = None
    last_led_at: Optional[float] = None
    last_poweroff_at: Optional[float] = None
    unknown: Dict[str, int] = field(default_factory=dict)

    def reset_session(self) -> None:
        """New connection: discard the previous session's data. LED/turn-off history stays."""
        self.connected_inferred = False
        self.headset = False
        self.chatpad = False
        self.subtype = self.protocol = self.revision = self.link_at = None
        self.battery_level = self.battery_type_raw = None
        self.power_state_raw = self.vibration_level = self.state_at = None
        self.state_source = None
        self.input_count = 0
        self.last_input_at = None
        self.unknown = {}


def _age(now: float, stamp: Optional[float]) -> Optional[float]:
    return None if stamp is None else max(0.0, now - stamp)


def blank_slot_dict(slot: int) -> dict:
    """Empty slot in the same format as `ReceiverMonitor.snapshot` (for slots without monitor data)."""
    return ReceiverMonitor._slot_dict(SlotState(slot), 0.0)


class ReceiverMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watched: Set[DeviceKey] = set()
        self._slots: Dict[DeviceKey, List[SlotState]] = {}

    # -- Configuration ------------------------------------------------------

    def set_watched(self, devices: Iterable[DeviceKey]) -> None:
        new = set(devices)
        with self._lock:
            self._watched = new
            for key in list(self._slots):
                if key not in new:
                    del self._slots[key]

    # -- Input --------------------------------------------------------------

    def feed(self, record: UsbmonRecord, now: float) -> None:
        if record.xfer_type != "I" or not record.data:
            return
        if record.endpoint not in CONTROLLER_ENDPOINTS:
            return
        key = (record.bus, record.device)
        with self._lock:
            if key not in self._watched:
                return
            slots = self._slots.setdefault(key, [SlotState(i) for i in range(SLOT_COUNT)])
            slot = slots[(record.endpoint - 1) // 2]
            if record.direction == "i" and record.event == "C":
                self._on_in(slot, record.data, now)
            elif record.direction == "o" and record.event == "S":
                self._on_out(slot, record.data, now)

    def _mark_present(self, slot: SlotState) -> None:
        if not slot.connected:
            slot.connected = True
            slot.connected_inferred = True
            slot.connected_at = None

    @staticmethod
    def _apply_state(slot: SlotState, state: StateReport, now: float, source: str = "report") -> None:
        slot.battery_level = int(state.battery_level)
        slot.battery_type_raw = state.battery_type
        slot.power_state_raw = state.power_state
        slot.vibration_level = state.vibration_level
        slot.headset = state.headset
        slot.chatpad = state.chatpad
        slot.state_at = now
        slot.state_source = source

    def _on_in(self, slot: SlotState, data: bytes, now: float) -> None:
        report = decode_in_packet(data)
        if report is None:
            return

        if isinstance(report, ConnectionEvent):
            if report.controller:
                if not slot.connected:
                    slot.reset_session()
                    slot.connected = True
                    slot.connected_inferred = False
                    slot.connected_at = now
                elif slot.connected_inferred:
                    slot.connected_inferred = False
                    slot.connected_at = now
                slot.headset = report.headset
            else:
                slot.connected = False
                slot.connected_inferred = False
                slot.connected_at = None
                slot.headset = False
                slot.chatpad = False
            return

        if isinstance(report, InputReport):
            self._mark_present(slot)
            slot.input_count += 1
            slot.last_input_at = now
            if report.state is not None:
                self._apply_state(slot, report.state, now)
            return

        if isinstance(report, LinkReport):
            self._mark_present(slot)
            slot.subtype = report.subtype
            slot.protocol = report.protocol
            slot.revision = report.revision
            slot.link_at = now
            if report.state is not None:
                self._apply_state(slot, report.state, now, "link")
            return

        if isinstance(report, StateReport):
            self._mark_present(slot)
            self._apply_state(slot, report, now)
            return

        if isinstance(report, UnknownReport):
            kind = report.raw[:5].hex()
            if kind in slot.unknown or len(slot.unknown) < MAX_UNKNOWN_KINDS:
                slot.unknown[kind] = slot.unknown.get(kind, 0) + 1

    @staticmethod
    def _on_out(slot: SlotState, data: bytes, now: float) -> None:
        if len(data) != 12 or data[0] != 0x00 or data[1] != 0x00 or data[2] != 0x08:
            return
        command = data[3]
        if 0x40 <= command <= 0x4F:
            slot.last_led_mode = command - 0x40
            slot.last_led_at = now
        elif command == 0xC0:
            slot.last_poweroff_at = now

    # -- Output -------------------------------------------------------------

    def snapshot(self, now: float) -> List[dict]:
        with self._lock:
            result = []
            for key in sorted(self._watched):
                slots = self._slots.get(key) or [SlotState(i) for i in range(SLOT_COUNT)]
                result.append(
                    {
                        "bus": key[0],
                        "devnum": key[1],
                        "slots": [self._slot_dict(s, now) for s in slots],
                    }
                )
            return result

    @staticmethod
    def _slot_dict(s: SlotState, now: float) -> dict:
        return {
            "slot": s.slot,
            "connected": s.connected,
            "connected_inferred": s.connected_inferred,
            "connected_age_s": _age(now, s.connected_at),
            "headset": s.headset,
            "chatpad": s.chatpad,
            "subtype": s.subtype,
            "subtype_name": None
            if s.subtype is None
            else SUBTYPE_NAMES.get(s.subtype, f"Unknown (0x{s.subtype:02X})"),
            "protocol": s.protocol,
            "revision": s.revision,
            "link_age_s": _age(now, s.link_at),
            "battery_level": s.battery_level,
            "battery_type_raw": s.battery_type_raw,
            "power_state_raw": s.power_state_raw,
            "vibration_level": s.vibration_level,
            "state_age_s": _age(now, s.state_at),
            "state_source": s.state_source,
            "input_count": s.input_count,
            "last_input_age_s": _age(now, s.last_input_at),
            "last_led_mode": s.last_led_mode,
            "last_led_age_s": _age(now, s.last_led_at),
            "last_poweroff_age_s": _age(now, s.last_poweroff_at),
            "unknown": dict(s.unknown),
        }
