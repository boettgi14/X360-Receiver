"""Controller ausschalten: nacheinander an alle Ziele, mit Zeitlimit.

Wird vom Knopf „Alle Controller jetzt ausschalten“ (Plugin) und vom Dienst beim Herunterfahren
(`poweroff_cli`, siehe `poweroff_unit`) benutzt. Ob das System herunterfährt, wird hier nicht
geprüft: Das Plugin selbst wird von Decky beim Herunterfahren nicht zuverlässig gestoppt
(am Gerät beobachtet), deshalb übernimmt ein eigener systemd-Dienst diese Aufgabe.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import actions

# Jeder Slot braucht mit der am Gerät bewährten Abfolge (Verwerfen 0,3 s, Senden, Mitlesen 0,6 s) etwa 1 s.
# Der Dienst darf nach `TimeoutStopSec` (poweroff_unit) beendet werden; das Limit liegt darunter.
DEADLINE_S = 8.0
RETRY_S = 0.2

Target = Tuple[int, int, int]


def power_off_targets(
    targets: Iterable[Target],
    power_off: Optional[Callable[..., dict]] = None,
    deadline_s: float = DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, object]:
    """Sendet den Ausschaltbefehl nacheinander an alle Ziele, höchstens `deadline_s` Sekunden lang.

    Läuft gerade ein anderer Zugriff, wird bis zur Frist wiederholt. Gibt Zähler und Fehlertexte zurück.
    """
    power_off = power_off or actions.power_off  # zur Laufzeit gebunden, damit Tests ersetzen können
    start = clock()
    sent = confirmed = skipped = 0
    errors: List[str] = []
    pending = list(targets)
    for index, (bus, devnum, slot) in enumerate(pending):
        while True:
            result = power_off(bus, devnum, slot)
            if result.get("error") != actions.BUSY_ERROR or clock() - start >= deadline_s:
                break
            sleep(RETRY_S)
        if result.get("ok"):
            sent += 1
            confirmed += 1 if result.get("confirmed") else 0
        else:
            errors.append(f"Bus {bus} Gerät {devnum} Slot {slot + 1}: {result.get('error', 'Fehler')}")
        if clock() - start >= deadline_s:
            skipped = len(pending) - index - 1
            break
    if skipped:
        errors.append(f"{skipped} Slot(s) nicht mehr erreicht (Zeitlimit)")
    return {"ok": not errors, "sent": sent, "confirmed": confirmed, "errors": errors}
