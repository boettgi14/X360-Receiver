# Protokoll des Xbox 360 Wireless Gaming Receivers

Zusammenfassung der Recherche. Jede Aussage trägt einen Vertrauensgrad:

- **[Quelle]** direkt in einer Quelle gelesen (xpad.c, argon.md, xboxdrv PROTOCOL)
- **[Probe]** durch Unit-Tests gegen Beispielpakete der Quellen bestätigt, aber nicht an echter Hardware
- **[Hypothese]** Annahme, die auf Hardware geprüft werden muss (Phase 0)

## 1. Gerät und Schnittstellen

- USB-IDs: 045E:0291 und 045E:0719 [Quelle: argon.md]. xpad kennt zusätzlich 045E:02A9 als „Unofficial“ [Quelle: xpad.c].
- Ein Receiver hat 4 Slots. Je Slot gibt es eine Controller-Schnittstelle (Klasse 0xFF, Subklasse 0x5D, Protokoll 0x81) und eine Audio-Schnittstelle (Protokoll 0x82) [Quelle: argon.md].
- Endpunkte: Controller 1 = IN 0x81 / OUT 0x01, Controller 2 = 0x83 / 0x03, Controller 3 = 0x85 / 0x05, Controller 4 = 0x87 / 0x07. Audio liegt jeweils auf dem geraden Endpunkt dazwischen [Quelle: argon.md].
- „Slot“ bedeutet Verbindungsreihenfolge am Receiver, nicht die Spielernummer (LED) [Quelle: argon.md].
- xpad bindet nur die Controller-Schnittstellen (Protokoll 129), nicht die Audio-Schnittstellen [Quelle: xpad.c, `XPAD_XBOX360_VENDOR_PROTOCOL(vend, 129)`].
- Jedes IN-Paket ist typischerweise 28 oder 29 Bytes lang [Quelle: xboxdrv].

## 2. IN-Pakete (Receiver → Host)

Header (5 Bytes): `[0]` Paket-ID (0x00, bei Verbindung 0x08), `[1]` Typ, `[2]` unbenutzt (0x00), `[3..4]` Header-Daten.

| ID | Typ | Inhalt | Status |
|----|-----|--------|--------|
| 0x08 | Bits 0x80 / 0x40 im Typ-Byte | Verbindung: 0x80 = Controller da, 0x40 = Headset da. Zwei Bytes lang | Quelle, Probe |
| 0x00 | 0x00 | **Status** in Header-Bytes 3–4, nur gültig wenn `byte3 & 0xF0 == 0x10` | Quelle, Probe |
| 0x00 | 0x01 / 0x03 | Eingabedaten (Tasten, Trigger, Sticks) ab Offset 5 | Quelle |
| 0x00 | 0x05 | Fähigkeiten (erstes Datenbyte 0x12) | Quelle |
| 0x00 | 0x0F | **Link-Report**: Geräteinfo beim Verbinden (erstes Datenbyte 0xCC) | Quelle, Probe |
| 0x00 | 0xF8 / 0xF9 | Unbekannt; erscheinen paarweise, auch nach Headset-Wechsel | Quelle (nur beobachtet) |

### Statusfelder (Byte 3 und Byte 4)

```
Byte 3:  bits 0-1 vibrationLevel   bit 2 headset   bit 3 chatpad   bits 4-7 Marker = 0x1
Byte 4:  bit 0 unknown   bits 1-2 batteryType   bit 3 onlyMic   bits 4-5 powerState   bits 6-7 batteryLevel
```

- Bitreihenfolge LSB-zuerst ist eine Annahme aus der C-Struct [Hypothese].
- `batteryLevel` 0..3 entspricht den vier XInput-Stufen (leer, niedrig, mittel, voll) [Hypothese].
- `batteryType` roh 0..3. Aus den Beispielen: 0xE0 = Typ 0 (xboxdrv-Autor vermutet „Charging?“), 0xE2 = Typ 1, 0xE6 = Typ 3. Welche Zahl Alkaline, NiMH-Pack oder „kabelgebunden/Play & Charge“ ist, ist **offen** [Hypothese]. Phase 0 klärt das mit AA-Batterien und Play-&-Charge-Pack.
- `powerState` roh 0..3, Bedeutung unbekannt. In allen Beispielen 2.

### Link-Report (nach dem 5-Byte-Header, 24 Datenbytes)

| Offset | Größe | Feld |
|--------|-------|------|
| 0 | 1 | immer 0xCC |
| 1 | 4 | unbekannt |
| 5 | 4 | deviceID |
| 9 | 1 | type |
| 10 | 1 | revision |
| 11 | 2 | state (gleiches Format wie Statusbytes oben) |
| 13 | 2 | protocol |
| 15 | 2 | unbekannt |
| 17 | 3 | vendorIDData |
| 20 | 1 | subtype |
| 21 | 3 | unbekannt |

- Die Formel für die Hersteller-ID aus der Quelle liefert für das xboxdrv-Beispiel 0x50001, also keinen plausiblen Wert [Probe]. Rohbytes werden deshalb mit angezeigt, die Formel ist ungeprüft.
- Subtypen (Gamepad, Lenkrad, Arcade-Stick, Flight-Stick, Tanzmatte, Gitarre, Gitarre alternativ, Schlagzeug, Bass, Arcade-Pad) stammen aus der XInput-Doku, die in dieser Session nicht geprüft wurde [Hypothese]. Ein Kernel-Patch-Entwurf (2026) benennt zumindest Gamepad, Wheel, Arcade Stick, Flight Stick, Dance Pad, Guitar und Alternate Guitar [Quelle: LKML-Patch, Vorschau].

## 3. OUT-Befehle (Host → Receiver), 12 Bytes, auf dem OUT-Endpunkt des Slots

| Befehl | Bytes | Status |
|--------|-------|--------|
| Status/Presence anfordern | `08 00 0F C0 00…` | Quelle (xpad.c nutzt das beim Start) |
| Akkustatus anfordern | `00 00 00 40 00…` | Quelle (argon.md), nicht in xpad |
| Fähigkeiten anfordern | `00 00 02 80 00…` | Quelle (argon.md) |
| LED setzen | `00 00 08 (0x40 + Modus) 00…`, Modus 0–15 | Quelle (xpad.c, argon.md) |
| **Controller ausschalten** | `00 00 08 C0 00…` | Quelle (xpad.c `xpad360w_poweroff_controller`, argon.md, xboxdrv) |
| Rumble | `00 01 0F C0 00 groß klein 00…` | Quelle (xpad.c) |
| Chatpad aktivieren | `00 00 0C 1B …` plus Keep-alive 0x1E/0x1F im Sekundentakt | Quelle (xboxdrv) |

LED-Modi laut xpad.c: 0 aus, 1 alle blinken, 2–5 Position 1–4 blinkt dann an, 6–9 Position 1–4 an, 10 rotierend, 11 blinkend, 12 langsam blinkend, 13 rotierend mit zwei Lichtern, 14 dauerhaft langsam alle blinkend, 15 einmal blinken.

Power-State: `0xC0 | Zustand`, Zustand 0 schaltet den Controller aus [Quelle: argon.md]. Andere Zustände (1–3) sind unerforscht.

## 4. Was der Linux-Kernel (xpad.c) davon nutzt

- Verbindung/Trennung (Bit 0x08 im ersten Byte, Controller-Bit 0x80 im zweiten) und Eingabedaten (Typ 0x01) werden ausgewertet.
- **Status-, Link- und Fähigkeitenpakete werden nicht ausgewertet.** Es gibt keine `power_supply`-Registrierung für den Akku [Quelle: xpad.c, im Quelltext gesucht].
- Ausschalten passiert nur (a) nach 5 Sekunden Halten der Guide-Taste (`XPAD360W_POWEROFF_TIMEOUT`) und (b) beim System-Suspend, wenn der Modulparameter `auto_poweroff` gesetzt ist (Standard: an, beschreibbar unter `/sys/module/xpad/parameters/auto_poweroff`).
- LEDs erscheinen als `/sys/class/leds/xpadN/brightness`. Geschrieben wird ein Befehl 0–15 (`command %= 16`). Der LED-Eintrag hängt am USB-Gerät, nicht an der Schnittstelle. Die Zuordnung xpadN → Slot ist deshalb nicht direkt ablesbar (siehe PLAN.md, offenes Problem 2).
- Rumble läuft über die normale Force-Feedback-Schnittstelle des Eingabegeräts.

## 5. Offene Quellenlage

- Die Datei xboxdrv/PROTOCOL wurde nur bis etwa zur Hälfte geladen (Rest nicht gesehen).
- Die Hardware-Beispiele stammen größtenteils von Drittanbieter-Controllern bzw. -Receivern. Original-Microsoft-Geräte können abweichen.
- Es wurde kein Host-Befehl für Sync/Pairing, Slot-Zuweisung oder Funkqualität gefunden. Das heißt nicht, dass es keinen gibt.

## 6. Hardware-Bestätigung (Mitschnitt vom 2026-11-04)

Gerät: Receiver 045E:0719, Bazzite-Deck 44.20261026, Kernel 7.2.11-ogc4.1, ein Gamepad. Rohdaten: `tests/fixtures/capture_connect_gamepad_2026-11-04.txt`, geprüft durch `tests/test_fixture_capture.py`. Dauer ca. 38 s.

Bestätigt an echter Hardware:
- usbmon liefert die **vollständigen 29 Bytes** der IN-Pakete.
- Verbindungspaket: `08 00` = nichts verbunden, `08 80` = Controller verbunden.
- Direkt nach dem Verbinden folgt ein Link-Report (Subtyp 0x01 = Gamepad, Protokoll 0x1D20, Revision 0x20; im xboxdrv-Beispiel war die Revision 0x05, sie variiert also), danach ein Statuspaket (Header-Daten `13 A2`: Akku-Stufe 2, Akkutyp roh 1, Power-State roh 2, Vibration 3, kein Headset/Chatpad).
- Eingabepakete (Typ 0x01): Tastenmaske entspricht dem XInput-Layout (A 0x1000, B 0x2000, X 0x4000, Y 0x8000, LB 0x0100, RB 0x0200, L3 0x0040, R3 0x0080, D-Pad 0x0001/0x0002/0x0004/0x0008). Trigger 0–255, Sticks 16 Bit mit Vorzeichen. Auf jedes Eingabepaket folgt ein Leerpaket `00 00 00 F0`.
- `xpad` sendet beim Trennen LED-Befehl 0 (`00 00 08 40 …`) und beim Verbinden LED-Befehl 2 (`00 00 08 42 …`). Beides ist byteidentisch mit `build_led(0)` und `build_led(2)`.
- Schreiben in `/sys/class/leds/xpadN/brightness` ändert die Controller-LEDs (vom Nutzer gemeldet, 2026-11-04). Welcher Modus getestet wurde und auf welchem OUT-Endpunkt der Befehl erschien, ist nicht erfasst. Die LED `xpadN` existiert nur bei verbundenem Controller.

Beobachtet, aber nicht erklärt:
- Nach dem Statuspaket folgen drei Typ-0-Pakete mit den Header-Daten `20 1D`, `30 03`, `40 01` und dann `F0 00`. Dieselben Bytefolgen stehen im Link-Report (Protokoll, unbekanntes Feld, Beginn der vendorIDData). Das spricht für Tag/Wert-Paare, ist aber nur eine Vermutung.
- Pakete `00 F8 01` und `00 F8 02` kamen fünfmal in 38 s (bei 0,0 / 13,5 / 19,8 / 29,0 / 37,6 s), unregelmäßig. Bedeutung unbekannt.
- **Es kam nur ein einziges Statuspaket, beim Verbinden.** Ob der Receiver den Akkustand später von sich aus erneut meldet, ist offen. Wenn nicht, kann ein passiver Monitor den Akku eines schon verbundenen Controllers nicht sehen.

Weiterhin ungeprüft: Zuordnung Stufe 0–3 zu Ladezustand (nur Stufe 2 beobachtet, Batteriezustand unbekannt), Bedeutung der Akkutyp-Werte, Ausschalten per Befehl, Guide/Start/Back.

## 7. Zweiter Mitschnitt (2026-11-05): Leerlauf nach dem Verbinden

Gerät wie in Abschnitt 6, ein Gamepad. Rohdaten: `tests/fixtures/capture_idle_gamepad_2026-11-05.txt`, geprüft durch `tests/test_fixture_idle.py`. 393 s, davon ca. 380 s mit verbundenem Controller. Die Datei ist am Ende abgeschnitten (grep puffert in 4-KiB-Blöcken, bei 12288 Byte war Schluss). Der geplante LED-Test, das Halten der Guide-Taste und die Tastendrücke stehen nicht darin; im Fenster ist nur eine einzelne Eingabe (bei 73,5 s, Tastenmaske 0, vermutlich eine Stick-Berührung).

Bestätigt an echter Hardware (ein Controller, ein Fenster, Leerlauf):
- **Nach dem Verbinden kommt kein weiteres Statuspaket.** Kein Link-Report, kein Typ-0-Zustand, kein Zustand im Header eines Eingabepakets in den folgenden ca. 380 s. Der Receiver meldet den Akku also nicht von sich aus periodisch. Nicht geprüft: Reaktion auf LED-Befehl, Tastendruck, Guide, Ausschalten, langen Betrieb mit sinkendem Akku.
- Die Verbindungsfolge ist reproduzierbar: `08 00` (getrennt), LED-Befehl 0, `08 80` (verbunden), LED-Befehl 2, Link-Report, dann eine Folge von Paketen mit Header-Daten `13 A2` (Zustand), `00 20`, `13 A2` (Zustand), `20 1D`, `30 03`, `40 01`, danach dauerhaft `F0 00`. Der Zustand war beide Male Stufe 2, Typ roh 1, Power-State roh 2. Der Akku-Wert im Link-Report hatte Bit 0 gesetzt (`13 A3`), im Zustandspaket nicht (`13 A2`); Bedeutung des Bits unbekannt.
- **Der Zustand kann im Header eines Eingabepakets (Typ 0x01) stehen**, nicht nur in einem Typ-0-Paket. Im ersten Mitschnitt kamen dieselben Header-Daten als Typ 0; die Reihenfolge und der Pakettyp wechseln also. Der Parser wertet die Header-Daten deshalb auch bei Eingabepaketen aus (`InputReport.state`).
- Pakete `00 F8 01` und `00 F8 02` kommen weiter, **50 Stück in 393 s, strikt abwechselnd** (02, 01, 02, 01, …). Jeder Abstand ist größer als 2,0 s und liegt nahe an einem Vielfachen von ca. 2,1 s (2,1 / 4,2 / 6,3 / 8,4 / 12,5 / …). Das spricht für ein Umschalten, das auf einem festen Takt abgetastet wird. Bedeutung unbekannt; denkbar wäre eine Verbindungsqualität, das ist nur eine Vermutung. Prüfung: Controller bewusst abschirmen oder entfernen und beobachten, ob sich Rate oder Verhältnis ändern.
- Leere Pakete `00 00 00 F0` kommen auch ohne Eingabe vor, einzeln und in Paaren.

Ungeprüft bleibt weiterhin: Stufen-Zuordnung, Akkutyp-Werte, Ausschalten per Befehl, Guide/Start/Back, welcher OUT-Endpunkt zu welchem Slot gehört.

## 8. Dritter Mitschnitt (2026-11-05): LED, Tasten, Neubinden, Ausschalten

Gerät wie zuvor, ein Gamepad. Rohdaten: `tests/fixtures/capture_events_gamepad_2026-11-05.txt` (vollständig, 246,7 s), geprüft durch `tests/test_fixture_events.py`. Zeiten in Sekunden seit Beginn.

Bestätigt an echter Hardware:
- **LED-Befehle** (`00 00 08 4A` = Modus 10 bei 114,3 s, `00 00 08 42` = Modus 2 bei 132,4 s) gehen auf **OUT-Endpunkt 0x01**. Die LED `xpad0` gehört damit zum ersten Slot (nur ein Controller, die Zuordnung für weitere Slots ist ungeprüft). Auf LED-Befehle antwortet der Receiver mit **keinem** Statuspaket.
- **Tasten:** A = 0x1000, B = 0x2000, **Guide = 0x0400** in der Tastenmaske des Eingabepakets. Tastendrücke lösen kein Statuspaket aus.
- **Lösen von `xpad`** (unbind): Der lesende URB endet mit Status −108, `xpad` versucht noch LED 0 zu senden (Fehler −2).
- **Binden von `xpad`** (bind): `xpad` sendet `08 00 0F C0` (byteidentisch mit `build_status_request()`). Der Receiver antwortet binnen 6 ms mit dem Verbindungspaket `08 80` und einem Link-Report. Der Link-Report ist **byteidentisch** zu dem beim echten Verbinden (Zustand darin `13 A3`: Stufe 2). **Kein** Zustandspaket und **keine** Header-Folge (`13 A2`, `20 1D`, …) folgt. Ob der Akkuwert im Link-Report frisch gemessen oder eine Kopie des Receivers ist, ist unbekannt. Auffällig: Im Link-Report ist Bit 0 des Zustands gesetzt (`A3`), in echten Zustandspaketen nie (`A2`). Das spricht eher für eine Kopie oder ein anderes Feld; ein Beleg ist es nicht.
- **Ausschalten:** `xpad` sendet `00 00 08 C0` auf Endpunkt 0x01, **5,056 s nach dem Guide-Druck**, im selben Augenblick wie das nächste Eingabepaket (das Loslassen, Tastenmaske 0). Danach, gemessen ab dem Befehl: **Zustandspaket 27 ms später (Header `13 82`: Stufe 2, Typ 1, Power-State 0)**, Verbindungspaket `08 00` nach 55 ms, LED-Befehl 0 von `xpad` nach 63 ms. Wiedereinschalten von Hand nach 12,3 s erzeugte die übliche Verbindungsfolge. Dass der Controller nach dem Befehl aus war, folgt aus dem Verbindungspaket und der späteren Neuverbindung; ob er auch ohne den Befehl ausgegangen wäre, wurde nicht getrennt geprüft.
- Das ist das **erste Statuspaket mitten in einer Sitzung**. Es kam beim Ausschalten, nicht periodisch. Power-State 2 (normal) wechselte zu 0.
- Nach echtem Verbinden: Link-Report, dann Header-Folge. Reihenfolge der ersten Häppchen wechselt zwischen Sitzungen. Die Werte `00 20`, `13 A2`, `20 1D`, `30 03`, `40 01` entsprechen in dieser Reihenfolge den Bytes im Körper des Link-Reports (`00 20 13 A3 20 1D 30 03 40 01 50 01`). Hypothese: Das sind 2-Byte-Häppchen desselben Datensatzes, im Header folgender Pakete verteilt; am Link-Report fehlt `50 01` und Bit 0 von `13`. Mittleres Vertrauen.

Aus dem Quelltext (`drivers/input/joystick/xpad.c`, aktueller Hauptzweig von Torvalds, **nicht** die Version des Geräts):
- Kommentar „XBOX360W controllers can't be turned off without driver assistance“. Der Treiber merkt sich den Guide-Druck (Sekundenauflösung) und prüft bei **jedem folgenden Eingabepaket**, ob mindestens 5 s vergangen sind. Dann sendet er `00 00 08 C0`. Halten allein erzeugt kein Paket; erst das Loslassen oder eine Stickbewegung löst aus. Passt zum Mitschnitt.
- Beim Start (`xpad360w_start_input`) sendet der Treiber die Anwesenheitsabfrage; der Kommentar sagt, das erzwinge erneute Verbindungspakete. Passt zum Mitschnitt.
- Beim Suspend sendet der Treiber `C0`, wenn `auto_poweroff` an ist und ein Controller anwesend ist.

Folgerungen (keine Messung): Ein Programm, das für wenige Sekunden eine Schnittstelle selbst belegt, könnte `C0` senden. Das Ausschalten eines Controllers kostet keine Eingabe, weil er danach ohnehin aus ist. Ob die Akkuanfrage `00 00 00 40` etwas liefert, ist unbekannt (Phase 0d).

## 9. Vierter Mitschnitt (2026-11-05): kurzer Zugriff mit `tools/probe_takeover.py`

Rohdaten: `tests/fixtures/capture_takeover_gamepad_2026-11-05.txt` (115 s, vollständig), geprüft durch `tests/test_fixture_takeover.py`. Dazu die Terminal-Ausgabe des Werkzeugs (Dekodierung stimmt mit dem Mitschnitt überein). Ein Receiver 045E:0719, ein Gamepad in Slot 1.

Bestätigt an echter Hardware:
- **Übernahme einer Schnittstelle über libusb funktioniert** (`LibusbBackend`: Gerät öffnen, `xpad` automatisch lösen, Schnittstelle belegen, auf OUT 0x01 schreiben, auf IN 0x81 lesen, freigeben). `xpad` bindet danach jedes Mal wieder, etwa 2 s nach dem Zugriff, und sendet dabei selbst Anwesenheitsabfrage und LED-Befehl 2. Beim Lösen sendet `xpad` noch LED 0 (Fehler −2, weil es gerade abgebaut wird).
- **Anwesenheitsabfrage** `08 00 0F C0` (selbst gesendet): Antwort `08 80` plus Link-Report binnen 8 ms.
- **Akkuanfrage `00 00 00 40`:** Antwort ist **ein Statuspaket** `00 00 00 13 A2` (Stufe 2, Typ 1, Power-State 2, Bit 0 = 0) nach **27 ms**, gefolgt von einem leeren Paket. Das ist dasselbe Paketformat wie beim Verbinden. Es ist die erste Möglichkeit, den Akku **bei Bedarf** zu erhalten.
- **Ausschalten `00 00 08 C0`** (selbst gesendet): Nach 31 ms ein Statuspaket mit Power-State 2, nach 39 ms eines mit **Power-State 0** (`13 82`), nach 55 ms `08 00` (getrennt). Der Controller war danach aus. Eine anschließende Anwesenheitsabfrage von `xpad` ergab `08 00`.
- **Manuelles Wiedereinschalten** 18 s später: `08 80`, Link-Report, Header-Folge wie üblich; `xpad` (wieder gebunden) setzte sofort LED 2. Der Controller verband sich also wieder normal.
- Die Lesezeitüberschreitungen des Werkzeugs (alle 100 ms, URB-Status −2) sind Teil des Verfahrens, keine Fehler.

Offen:
- **Frische des Akkuwerts.** Er war bei allen Abfragen Stufe 2. Ob der Receiver den Controller bei der Anfrage frisch befragt oder aus einem Zwischenspeicher antwortet, ist ungeklärt. Der Zustand mit Power-State 0 beim Ausschalten zeigt, dass Zustandspakete den Controller-Zustand widerspiegeln können (der Receiver konnte den Wechsel nicht selbst wissen), ist aber kein Beleg für die Akkuanfrage. Test: Akkuanfrage bei ausgeschaltetem Controller (kommt dann trotzdem ein Statuspaket, ist es ein Zwischenspeicher), später bei sinkendem Akku.
- Wie Steam den kurzen Verlust des Controllers behandelt (Anzeige, Spielerreihenfolge, laufende Spiele).
- Verhalten mit mehreren Controllern am selben Receiver (andere Slots sollten unberührt bleiben, ungeprüft).

## 10. Weitere Terminalmessungen (2026-11-05): Akkuanfrage ohne Mitschnitt

Nur Terminalausgabe von `tools/probe_takeover.py --battery-request`, kein usbmon-Mitschnitt. Zwei Läufe hintereinander, Zustand des Controllers nicht ausdrücklich angegeben; nach der Reihenfolge der Ausgabe ist **angenommen**, dass er im ersten Lauf ausgeschaltet und im zweiten eingeschaltet war.
- Erster Lauf: Anfrage gesendet, **0 Pakete** zurück.
- Zweiter Lauf: Statuspaket `00 00 00 13 A2` nach 0,02 s (Stufe 2, Typ 1, Power-State 2), dann leeres Paket.
- Trifft die Annahme zu, antwortet der Receiver **nicht aus einem Zwischenspeicher**: Bei ausgeschaltetem Controller kommt kein Statuspaket, bei eingeschaltetem eines. Das spricht dafür, dass der Controller bei der Anfrage befragt wird. Es ist trotzdem kein Beleg für einen sich ändernden Wert; der war bei allen Abfragen Stufe 2.
- Batterie laut Nutzer: **2 AA NiMH**. Zugehörig: Akkutyp roh 1. Andere Werte (Pack, Netz) unbeobachtet. Bei NiMH ist die Spannungskurve flach; die Vierstufigkeit des Protokolls ist daher grob.

Systemstruktur, bestätigt: Der Receiver heißt in sysfs `1-3`, `xpad` ist an `1-3:1.0`, `1-3:1.2`, `1-3:1.4`, `1-3:1.6` gebunden (die Schnittstellen 1, 3, 5, 7 sind Audio und ungebunden). Daneben gibt es `1-4` (anderes Gerät) und die Root-Hubs `N-0:1.0`.

