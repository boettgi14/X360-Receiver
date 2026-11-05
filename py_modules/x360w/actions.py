"""Aktionen mit kurzem Zugriff auf einen Slot: Akku abfragen, Controller ausschalten.

An Hardware gesehen (2026-11-05, Mitschnitt und Terminal, ein Receiver 045E:0719, ein Gamepad):
  - Akkuanfrage `00 00 00 40` wird binnen ca. 30 ms mit einem Statuspaket beantwortet.
  - `00 00 08 C0` schaltet den Controller aus (Statuspaket mit Power-State 0, dann Trennung).
  - `xpad` bindet die Schnittstelle nach dem Zugriff wieder.
Unbekannt: ob die Akkuanfrage den Controller frisch befragt oder der Receiver aus einem
Zwischenspeicher antwortet (Test: Anfrage bei ausgeschaltetem Controller).

Kosten: Der Controller des Slots verschwindet für einige Sekunden aus dem System (Steam sieht
ihn gehen und wiederkommen). Andere Slots bleiben unberührt.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from .protocol import (
    InputReport,
    StateReport,
    build_battery_request,
    build_poweroff,
)
from .takeover import Backend, LibusbBackend, SlotSession, UsbError

DRAIN_S = 0.3
BATTERY_LISTEN_S = 1.0
POWEROFF_LISTEN_S = 0.6

BUSY_ERROR = "Es läuft bereits ein Zugriff auf den Receiver."

_lock = threading.Lock()


def _state_dict(state: StateReport) -> dict:
    return {
        "battery_level": int(state.battery_level),
        "battery_type_raw": state.battery_type,
        "power_state_raw": state.power_state,
        "vibration_level": state.vibration_level,
        "headset": state.headset,
        "chatpad": state.chatpad,
    }


def _states(packets: List[tuple]) -> List[StateReport]:
    found: List[StateReport] = []
    for _, _, report in packets:
        if isinstance(report, StateReport):
            found.append(report)
        elif isinstance(report, InputReport) and report.state is not None:
            found.append(report.state)
    return found


def _run(bus: int, devnum: int, slot: int, backend_factory: Callable[[], Backend], body) -> dict:
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": BUSY_ERROR}
    try:
        with SlotSession(backend_factory(), bus, devnum, slot) as session:
            return body(session)
    except (UsbError, ValueError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        _lock.release()


def query_battery(bus: int, devnum: int, slot: int,
                  backend_factory: Callable[[], Backend] = LibusbBackend) -> dict:
    """Sendet die Akkuanfrage. `state` ist None, wenn keine Antwort kam (z. B. Controller aus)."""

    def body(session: SlotSession) -> dict:
        session.listen(DRAIN_S)  # liegengebliebene Pakete verwerfen
        session.send(build_battery_request())
        states = _states(session.listen(BATTERY_LISTEN_S))
        return {"ok": True, "state": _state_dict(states[0]) if states else None}

    return _run(bus, devnum, slot, backend_factory, body)


def power_off(bus: int, devnum: int, slot: int,
              backend_factory: Callable[[], Backend] = LibusbBackend) -> dict:
    """Schaltet den Controller des Slots aus. Bestätigt, wenn ein Statuspaket mit Power-State 0 kommt."""

    def body(session: SlotSession) -> dict:
        session.listen(DRAIN_S)
        session.send(build_poweroff())
        states = _states(session.listen(POWEROFF_LISTEN_S))
        confirmed = any(s.power_state == 0 for s in states)
        return {"ok": True, "confirmed": confirmed}

    return _run(bus, devnum, slot, backend_factory, body)
