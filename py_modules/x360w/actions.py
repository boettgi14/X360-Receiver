"""Actions with short access to one slot: query the battery, turn the controller off.

Confirmed on hardware (one receiver 045E:0719, one gamepad):
  - The battery request `00 00 00 40` is answered with a state packet within about 30 ms.
  - `00 00 08 C0` turns the controller off (state packet with power state 0, then disconnect).
  - `xpad` re-binds the interface after the access.
  - With the controller off the battery request gets no answer, so the receiver does not answer from a
    cache. Whether the value changes as a battery drains is unverified.

Cost: The slot's controller disappears from the system for a few seconds (Steam sees it leave
and come back). Other slots are untouched.

Results are plain dicts. On failure: {"ok": False, "error": <English text>} plus an optional
"code" (and "detail") that the frontend translates.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from . import error_codes
from .protocol import (
    InputReport,
    LinkReport,
    StateReport,
    build_battery_request,
    build_poweroff,
    build_status_request,
)
from .takeover import Backend, LibusbBackend, SlotSession, UsbError

DRAIN_S = 0.3
BATTERY_LISTEN_S = 1.0
POWEROFF_LISTEN_S = 0.6
PRESENCE_LISTEN_S = 0.5

BUSY_ERROR = "Another access to the receiver is already running."
BUSY_CODE = error_codes.BUSY

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


def _failure(exc: Exception) -> dict:
    result = {"ok": False, "error": str(exc)}
    code: Optional[str] = getattr(exc, "code", None)
    if code:
        result["code"] = code
        detail = getattr(exc, "detail", None)
        if detail:
            result["detail"] = detail
    return result


def _run(bus: int, devnum: int, slot: int, backend_factory: Callable[[], Backend], body) -> dict:
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": BUSY_ERROR, "code": BUSY_CODE}
    try:
        with SlotSession(backend_factory(), bus, devnum, slot) as session:
            return body(session)
    except (UsbError, ValueError, OSError) as exc:
        return _failure(exc)
    finally:
        _lock.release()


def query_battery(bus: int, devnum: int, slot: int,
                  backend_factory: Callable[[], Backend] = LibusbBackend) -> dict:
    """Sends the battery request. `state` is None if no answer came (e.g. controller off).

    If the controller answered, a presence request follows (`08 00 0F C0`, the one xpad sends itself when it
    binds; confirmed on hardware with tools/probe_takeover.py). The receiver answers it with the link report,
    which carries the controller type, so `subtype` is known even without the usbmon monitor (None if no link
    report came). The result then reads {"ok", "state", "subtype"}.
    """

    def body(session: SlotSession) -> dict:
        session.listen(DRAIN_S)  # discard leftover packets
        session.send(build_battery_request())
        states = _states(session.listen(BATTERY_LISTEN_S))
        if not states:
            return {"ok": True, "state": None}
        session.send(build_status_request())
        links = [r for _, _, r in session.listen(PRESENCE_LISTEN_S) if isinstance(r, LinkReport)]
        return {"ok": True, "state": _state_dict(states[0]), "subtype": links[0].subtype if links else None}

    return _run(bus, devnum, slot, backend_factory, body)


def power_off(bus: int, devnum: int, slot: int,
              backend_factory: Callable[[], Backend] = LibusbBackend) -> dict:
    """Turns off the slot's controller. Confirmed when a state packet with power state 0 arrives."""

    def body(session: SlotSession) -> dict:
        session.listen(DRAIN_S)
        session.send(build_poweroff())
        states = _states(session.listen(POWEROFF_LISTEN_S))
        confirmed = any(s.power_state == 0 for s in states)
        return {"ok": True, "confirmed": confirmed}

    return _run(bus, devnum, slot, backend_factory, body)
