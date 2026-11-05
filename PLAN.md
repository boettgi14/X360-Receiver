# Umsetzungsplan: Decky-Plugin für den Xbox 360 Wireless Receiver

Stand: 2026-11-05. Zielsystem: Bazzite (Deck-Variante, Gaming-Modus) mit Xbox-360-Wireless-Receiver.

Dieser Plan trennt strikt zwischen **an Hardware bestätigt**, **nur aus Quellen oder Unit-Tests belegt**, **Annahme** und **offen**. Das Protokoll steht in `docs/PROTOCOL.md`.

## 0. Stand in Kürze

| Bereich | Stand |
|---------|-------|
| usbmon als Lesezugang | **an Hardware bestätigt**: debugfs als root lesbar, volle 29-Byte-Pakete, Filter auf Bus/Gerät greift |
| Verbindung, Link-Report, Statuspaket, Eingabepakete | **an Hardware bestätigt** (ein Gamepad, Mitschnitt 38 s) |
| LED-Steuerung über `/sys/class/leds/xpadN/brightness` | **bestätigt**: Du hast gemeldet, dass die LEDs reagieren. Welcher Modus getestet wurde, ist nicht festgehalten; die Zuordnung LED ↔ Slot ist ungeprüft (nur ein Controller) |
| Akku periodisch oder nur beim Verbinden gemeldet | **an Hardware bestätigt: nur beim Verbinden.** Kein weiteres Statuspaket in ca. 380 s Leerlauf, nach LED-Befehlen, nach A/B/Guide und nach dem Neubinden von `xpad` (dort nur ein Link-Report mit Akkustufe, Frische unklar). Einzige Meldung mitten in einer Sitzung: beim Ausschalten (Power-State 0). Ungeprüft: Akkuanfrage `00 00 00 40`, langer Betrieb mit sinkendem Akku, Laden |
| Ausschalten per Befehl | **an Hardware bestätigt** (von `xpad` gesendet, 5 s Guide; Controller danach getrennt). Selbst senden: an Hardware bestätigt (kurzer Zugriff, Knopf im Plugin, Dienst beim Herunterfahren) |
| Akkuanfrage per Befehl (`00 00 00 40`) | **an Hardware bestätigt**: Antwort ist ein Statuspaket nach 27 ms. Bei ausgeschaltetem Controller kam **keine** Antwort (angenommen, Reihenfolge der Läufe), also vermutlich kein Zwischenspeicher. Ob sich der Wert bei sinkendem Akku ändert, ist ungeprüft |
| Kurzer Zugriff auf einen Slot (libusb) | **an Hardware bestätigt** mit `tools/probe_takeover.py`: Anwesenheitsabfrage, Akkuanfrage und Ausschalten, `xpad` bindet danach wieder. Im Plugin verdrahtet (Schaltflächen), als Plugin nie auf dem Gerät gelaufen |
| Backend (Monitor, Dienst, Steuerung) | **200 Tests grün** (darunter Wiedergabe vierer echter Mitschnitte). Läuft als Decky-Plugin auf dem Gerät des Nutzers: Akkuabfrage (auch direkt nach dem Start), LED-Zuordnung und Knöpfe vom Nutzer als korrekt bestätigt; der systemd-Dienst für das Herunterfahren funktioniert laut Nutzer (Risiko 18) |
| Frontend | baut mit der offiziellen Toolchain, ist in Decky geladen und vom Nutzer gesehen (Layout, Karten, Balken); Rendertest mit gestellten Decky-Bausteinen; Fokus-Navigation mit dem Controller nicht gezielt geprüft |
| Secure Boot / Lockdown | aus / `none`: ein selbstgebautes `xpad`-Modul ist auf dem Gerät prinzipiell möglich (Kernel-Header ungeprüft) |

## 1. Anforderungen

1. Möglichst alle Controller-Arten unterstützen, die der Receiver anbindet (Gamepad, Lenkrad, Arcade-Stick, Gitarre, Schlagzeug, Tanzmatte u. a.).
2. Mehrere Receiver gleichzeitig am System.
3. Alle auslesbaren Statusinformationen anzeigen.
4. Controller steuern, vor allem Power-Management.

## 2. Das zentrale Hindernis

Der Kernel-Treiber `xpad` besitzt auf jedem Receiver die vier Controller-Schnittstellen (belegt: `XPAD_XBOX360_VENDOR_PROTOCOL(vend, 129)`). Er wertet nur Verbindungs- und Eingabepakete aus. Die Statuspakete mit dem Akkustand verwirft er, und er bietet keinen Schalter, um einen Controller gezielt auszuschalten. Ein Userspace-Programm darf eine belegte USB-Schnittstelle nicht gleichzeitig nutzen, ohne `xpad` abzukoppeln, und dann fiele die Controller-Eingabe weg.

Daraus folgen vier mögliche Zugriffswege:

| Weg | Lesen | Senden | Eingriff | Bewertung |
|-----|-------|--------|----------|-----------|
| **A. usbmon (passiv)** | Ja, alles was über den Bus geht | Nein | Keiner, `xpad` läuft normal weiter | Heute machbar. Sieht den ganzen USB-Bus, also Datenschutzthema (siehe 7) |
| **B. Kernel-Patch in `xpad`** | Ja, sauber als `power_supply` | Ja, z. B. Ausschalten per sysfs | Neuer Kernel bzw. Modul nötig | Sauberste Lösung. Auf unveränderlichem Bazzite erst nutzbar, wenn der Patch im verwendeten Kernel steckt |
| **C. Userspace-Übernahme** | Ja | Ja | `xpad` abkoppeln, eigene libusb-Logik, virtuelle Controller per uinput | Mächtig, aber riskant: Steam Input, Rumble, Suspend und Latenz müssen neu gebaut werden |
| **D. eBPF auf `xpad`-Funktionen** | Ja, nur `xpad`-Daten | Nein | BPF-Werkzeuge nötig | Datenschutzfreundlicher als A. Ob BPF-Tooling im Decky-Python praktikabel ist, ist offen |

### Empfehlung

Dreigleisig, mit automatischer Erkennung der Fähigkeiten zur Laufzeit:

- **Spur A liefert v1** (nur lesen + das, was Kernel-Schnittstellen schon hergeben).
- **Spur B läuft parallel als Upstream-Patch.** Sobald `/sys/class/power_supply` einen Controller-Akku und ein Ausschalten anbietet, bevorzugt das Plugin diese Schnittstelle und braucht usbmon nicht mehr.
- **Spur C nur, wenn A und B nicht reichen**, als abschaltbarer Experten-Modus. Entscheidung nach Phase 1.

Rückenwind für B: Auf der Kernel-Liste (linux-input) läuft 2026 bereits ein Patch-Stapel „xpad: Overhaul device data for wireless devices“ (v7 vom August 2026). Ob er angenommen wurde, ist nicht geprüft. Er zeigt, dass Änderungen am Wireless-Teil von `xpad` aktiv begutachtet werden.

## 3. Funktionsumfang und Machbarkeit

Stufen: **jetzt** = mit Linux-Bordmitteln, **A** = braucht usbmon, **B** = braucht Kernel-Patch oder Übernahme, **offen** = Quellenlage unklar.

### Statusinformationen

| Information | Quelle | Stufe |
|-------------|--------|-------|
| Receiver: USB-IDs, Hersteller-/Produktstring, Seriennummer, Firmware-Version (`bcdDevice`), Bus/Port, Original oder Klon (PID-Hinweis) | sysfs | jetzt |
| Welche Schnittstelle an welchen Treiber gebunden ist | sysfs | jetzt |
| Slot belegt (Controller verbunden) | Eingabegeräte in sysfs, deren Elternteil die Schnittstelle 0/2/4/6 ist | jetzt |
| Verbunden/getrennt in Echtzeit, Headset angeschlossen | Verbindungspaket | A |
| **Akkustufe (4 Stufen), Akkutyp, Power-State** | Statuspaket | A |
| Chatpad und Headset angeschlossen, Rumble-Level | Statuspaket | A |
| Controller-Art (Subtyp), Geräte-ID, Protokollversion, Hersteller | Link-Report (nur beim Verbinden) | A, mit Einschränkung (8, Problem 3) |
| Fähigkeiten (Motoren, Tasten) | Fähigkeitenpaket (muss angefordert werden) | B |
| Signalqualität, Funkkanal | keine Quelle gefunden | offen |
| Prozentgenauer Akku | gibt das Protokoll nach heutigem Stand nicht her (nur 4 Stufen) | nicht verfügbar |

### Steuerung

| Funktion | Weg | Stufe |
|----------|-----|-------|
| Spieler-LED und Blinkmuster (Modi 0–15) | `/sys/class/leds/xpadN/brightness` | jetzt, **bestätigt** (Slot-Zuordnung: Problem 2; LED existiert nur bei verbundenem Controller) |
| Rumble-Test („Controller finden“) | Force-Feedback am Eingabegerät | jetzt |
| **Option „Beim Standby ausschalten“** | `/sys/module/xpad/parameters/auto_poweroff` (beschreibbar). Laut `xpad.c` schaltet `xpad_suspend` damit alle verbundenen Controller aus; Kernel-Standard ist an. Globaler Parameter, nicht je Controller. Das Plugin speichert die Wahl und setzt sie beim Start erneut (der Parameter ist nach einem Neustart zurückgesetzt) | jetzt (Quelle, am Gerät nicht geprüft) |
| **Option „Beim Herunterfahren ausschalten“** | `xpad` hat keinen Shutdown-Hook, und Decky stoppt das Plugin beim Herunterfahren nicht zuverlässig (am Gerät beobachtet, siehe Risiko 18). Deshalb richtet das Plugin beim Einschalten der Option einen kleinen **systemd-Dienst** ein (`x360-receiver-poweroff.service`, `Type=oneshot`, `RemainAfterExit`, `ExecStop`), der unabhängig von Decky beim Herunterfahren und Neustart das Programm `/var/lib/x360-receiver/poweroff.py` ausführt: Ziele wie beim Knopf ermitteln (sysfs und LEDs, ohne usbmon) und `00 00 08 C0` mit derselben Befehlsfolge senden (am Gerät bewährt, Zeitlimit 8 s, `TimeoutStopSec=12`). Beim Ausschalten der Option und beim Entfernen des Plugins werden Dienst und Programm gelöscht. Das Ergebnis des letzten Laufs steht unter „Diagnose“ | jetzt (**früherer Weg über das Plugin selbst scheiterte dreimal am Gerät; der Dienst funktioniert laut Nutzer**, Risiko 18) |
| Hinweis: Guide-Taste 5 s halten schaltet den Controller aus | eingebaut in `xpad` | jetzt |
| **Controller auf Knopfdruck ausschalten** (**bestätigt über den kurzen Zugriff**) | OUT-Befehl `00 00 08 C0…`. Von `xpad` bei 5 s Guide bestätigt. Selbst senden über den kurzen Zugriff, an Hardware bestätigt; Spur B nicht nötig | jetzt (Plugin-Schaltfläche) |
| Akkustatus aktiv anfordern | OUT-Befehl `00 00 00 40…` über den kurzen Zugriff, an Hardware bestätigt. Kostet: Slot verschwindet ca. 3 s | jetzt (Plugin-Schaltfläche). **Automatisch einmal nach dem Start des Plugins** für alle schon verbundenen Controller (der Receiver meldet den Akku sonst nur beim Verbinden); das Ergebnis wird im Backend gemerkt (`battery_cache.py`) und auch ohne Monitor angezeigt. Quelle „query“, Alter wie bei Monitorwerten; der jeweils neuere Wert gewinnt (Monitor oder Abfrage) |
| Andere Power-States (1–3) | unerforscht | offen |
| Sync/Pairing, Slot-Zuweisung | kein Host-Befehl gefunden | offen |
| Chatpad und Headset | Chatpad über Controller-Endpunkt, Headset-Audio auf eigenen, von `xpad` nicht gebundenen Schnittstellen | später (v2) |

Das Ausschalten auf Knopfdruck ist wegen des Zugriffsproblems die schwierigste Anforderung. Mit Spur A allein ist sie **nicht** erfüllbar.

## 4. Mehrere Receiver

- Jeder Receiver ist ein eigenes USB-Gerät. Das Plugin enumeriert alle Geräte mit den bekannten IDs (045E:0291, 045E:0719, 045E:02A9) und bildet pro Receiver vier Slots.
- Datenmodell: `Receiver (usb_path, bus, devnum, ids, firmware) → Slot 0..3 (Zustand, Subtyp, Akku, Headset, Chatpad, evdev-Pfad, LED-Pfad)`.
- usbmon filtert nach `(Bus, Geräteadresse)`. Mehrere Receiver am selben Bus werden über die Geräteadresse getrennt.
- Hot-Plug: Änderungen über udev-Ereignisse oder Polling von `/sys/bus/usb/devices` alle paar Sekunden. Ein neu eingestecktes Gerät bekommt eine neue Geräteadresse.
- Der Plan geht von beliebig vielen Receivern aus. Praktische Obergrenzen (Steam, Kernel) sind nicht geprüft.

## 5. Architektur

```
Decky-Frontend (React, @decky/ui)        Decky-Backend (Python, root)
 QAM-Panel: Allgemein, Receiver,  <----->  Plugin-Klasse (main.py)
  ausklappbare Controller                  ├─ View       (Receiver → Controller, LED-Zuordnung)
 Toasts bei niedrigem Akku                 ├─ Discovery  (sysfs, Hot-Plug)
 Einstellungen                             ├─ Monitor    (usbmon-Leser, Filter nach Gerät)   [Spur A]
                                           ├─ PowerSupply-Leser (sysfs)                      [Spur B]
                                           ├─ Controls   (LED, Rumble, auto_poweroff, Poweroff)
                                           └─ x360w.protocol (reiner Parser, getestet)
```

- Backend läuft als root (`"flags": ["root"]` in `plugin.json`. Decky prüft im Quelltext genau `"root" in flags`. `"_root"` aus der Vorlage bedeutet "ausgeschaltet": Das Plugin liefe ohne Root-Rechte und libusb, sysfs und usbmon würden scheitern. Ein früherer Stand dieses Plans behauptete das Gegenteil; das war falsch), weil usbmon und sysfs-Schreibzugriff es verlangen. Das ist begründungspflichtig für den Decky-Store.
- Das Backend hält pro Slot einen Zustandsautomaten, der Pakete zusammenführt (Verbindung → Link-Report → Statusupdates) und veraltete Daten mit Zeitstempel markiert („zuletzt gesehen vor 40 s“).
- **Oberfläche** (`src/index.tsx`), von oben nach unten:
  1. *Allgemein* (gilt für alle Receiver), Gruppen *Überwachung* („Akku-Status mitlesen“) und *Energie* („Beim Standby ausschalten“, „Beim Herunterfahren ausschalten“, „Alle Controller jetzt ausschalten“).
  2. Je Receiver ein Abschnitt „Receiver N“ mit Kopfzeile (Name, USB-Pfad, belegte Slots) und der Gruppe *Controller*.
  3. Jeder verbundene Controller ist eine ausklappbare Karte (zugeklappt: Name, Typ, **Akkubalken mit „Stufe n/3“**). Aufgeklappt, mit Überschrift und Linie links je Gruppe: *Akku* (Alter der Meldung, „Akku jetzt abfragen“; Balken und Stufe stehen nur in der Kopfzeile der Karte), *Energie* („Controller ausschalten“), *LED* (nur wenn eindeutig zugeordnet), *Details*.
  4. LEDs, die sich keinem einzelnen Controller zuordnen lassen, stehen als Gruppe beim Receiver.
  Der Akkubalken hat drei Segmente für die Stufen 1–3 (0 = leer, rot); die Zuordnung zu Prozent ist unbelegt und wird nicht angezeigt.
  Die Optionen Standby und Herunterfahren stehen unter *Allgemein*, nicht je Controller: `auto_poweroff` ist ein globaler Kernelparameter, und beide Ereignisse betreffen das ganze Gerät.
- **Welche Controller sind verbunden?** Aus dem Monitor (bestätigt) und aus dem von `xpad` angelegten Eingabegerät unter `<Schnittstelle>/input/` (nur aus dem Quelltext abgeleitet). Dadurch sieht man Controller auch bei ausgeschaltetem Monitor, dann ohne Akkustand. Gibt es mehr LEDs als erkannte Controller (LED existiert nur bei verbundenem Controller, bestätigt), steht „n weiterer Controller verbunden“ und die Slots sind unbekannt.
- **LED-Zuordnung:** Die LED hängt am Receiver (`led_classdev_register(&xpad->udev->dev …)`), nicht am Slot; sie wird über den aufgelösten sysfs-Pfad dem Receiver zugeordnet. Innerhalb eines Receivers gilt die am Gerät beobachtete Regel „xpad0 = Controller 1, xpad1 = Controller 2 …“: LEDs nach Nummer sortiert, Controller nach Slot sortiert, paarweise, sofern die Anzahlen übereinstimmen (sonst stehen die LEDs als Gruppe beim Receiver). Das bleibt bei **einem** Receiver im Gleichschritt, weil xpad die LED-Nummer und der Receiver den Slot jeweils als „kleinste freie“ vergeben. Bei mehreren Receivern teilen sie sich die LED-Nummern; die Reihenfolge kann abweichen (Beispiel: Receiver 2 belegt xpad0, danach verbindet sich ein Controller an Slot 1 von Receiver 1 und bekommt xpad1 statt xpad0). Gesichert ist die Zuordnung dann nicht.
- Das Frontend fragt den Zustand alle 2–5 s per `callable` ab. Niedrigen Akku meldet das Backend per Ereignis, das Frontend zeigt dann einen Toast.
- Abhängigkeiten: keine außer der Python-Standardbibliothek in Spur A. Der Parser `py_modules/x360w/` ist rein und wurde bereits getestet.

## 6. Phasen mit Abnahmekriterien

**Phase 0: Realitätscheck an echter Hardware. Abgeschlossen.**
- Erledigt: Systemdaten, usbmon, volle Pakete, Verbindungsfolge (dreimal), LED-Pfad und -Bytes, Leerlauf, LED-Befehle, Tasten, Neubinden von `xpad`, Ausschalten (`docs/PROTOCOL.md`, Abschnitte 6 bis 8).
- **Ergebnis: Der Receiver meldet den Akku nur beim Verbinden.** Weder Zeit, LED-Befehle, Tasten noch das Neubinden von `xpad` lösen ein frisches Statuspaket aus. Das Neubinden liefert nur einen Link-Report mit Akkustufe; ob der Wert frisch ist, ist offen. Startet das Plugin nach dem Controller, zeigt es zunächst „noch nicht gemeldet“.
- **Ergebnis: Ausschalten funktioniert per Befehl `00 00 08 C0`** (von `xpad` gesendet, danach Zustandspaket mit Power-State 0 und Trennung).
- Stufenleiter für den Akku, von harmlos zu aufwendig:
  1. Letzten Wert mit Alter anzeigen (gebaut: `state_age_s`, plus `state_source` „report“ oder „link“; die Oberfläche kennzeichnet Link-Werte).
  2. Den beim Verbinden oder Aufwecken gemeldeten Wert nutzen (kostenlos).
  3. **Kurzer Zugriff auf den Slot** (`x360w/takeover.py`, `x360w/actions.py`, libusb): `xpad` gibt die Schnittstelle für Sekunden frei, wir senden `00 00 00 40`, lesen die Antwort, `xpad` bindet wieder. **An Hardware bestätigt (Phase 0d).** Kostet: Der Controller dieses Slots verschwindet für etwa 3 s aus dem System. Im Plugin als Schaltfläche „Akku abfragen“, bewusst ohne automatische Wiederholung.
  4. Spur B: Akkuanfrage und `power_supply` aus einem gepatchten `xpad`. Nahtlos und ohne Controller-Aussetzer, braucht aber Modul oder Kernel. Das Protokoll dafür ist nun bekannt (Anfrage `00 00 00 40`, Antwort Typ 0 mit Header `13 xx`). Wird wichtig, wenn Steam den kurzen Verlust schlecht verträgt.
- **Ausschalten per Knopf im Plugin** braucht keinen Kernelpatch: Der kurze Zugriff sendet `C0`, und weil der Controller danach ohnehin aus ist, geht keine Eingabe verloren. An Hardware bestätigt (Phase 0d), mit Rückfrage im Plugin.
- Unklar: die `F8 01/02`-Pakete (50 in 393 s, strikt abwechselnd) sind der einzige laufende Datenstrom im Leerlauf. Vermutung Verbindungsqualität, ohne Beleg.

**Phase 0d: Prüfung des kurzen Zugriffs. Bestanden** (`docs/PROTOCOL.md`, Abschnitt 9). Übernahme, Anwesenheitsabfrage, Akkuanfrage und Ausschalten funktionieren; `xpad` bindet danach jedes Mal wieder.

**Phase 0e: teilweise erledigt.** Akkuanfrage bei ausgeschaltetem Controller: keine Antwort (Reihenfolge der Läufe, nicht ausdrücklich bestätigt). Offen: Verhalten von Steam beim kurzen Verlust des Controllers; wird mit dem installierten Plugin beobachtet (Abschnitt 10).

**Phase 1: Plugin-MVP. Code geschrieben, Gerätetest als Plugin offen.**
- Vorhanden: Receiver-Erkennung, usbmon-Leser (je Bus ein Thread, Vorfilter nach Adressmarke), Zustandsautomat je Slot, Dienst mit Hot-Plug-Aktualisierung, QAM-Panel (Aufbau siehe Abschnitt 5) mit Status, LED-Auswahl, den Optionen Standby und Herunterfahren sowie je Controller „Akku abfragen“ und „Ausschalten“ (mit Rückfrage). Das Backend nimmt nur bekannte Receiver und Slots 0 bis 3 an.
- Gerätetest-Abnahme: Plugin laden; Akkustufe des verbundenen Controllers erscheint nach dem Einschalten binnen 10 s; Monitor aus bedeutet: kein usbmon-Zugriff (am Logging und an `status.readers` prüfbar). Zwei Receiver nur als Wiedergabe testbar, solange kein zweiter vorhanden ist.
- Ungeprüfte Annahmen, die der Gerätetest klären muss: `select()` auf der usbmon-Datei verhält sich wie erwartet; die echte sysfs-Struktur passt zur Erkennung (`discovery.py` ist nur gegen einen nachgebauten Baum getestet); Decky lädt Backend und Frontend.
- Toast bei niedrigem Akku: noch nicht gebaut, bewusst zurückgestellt, bis die Stufenzuordnung (0–3 gegen Ladezustand) belegt ist.

**Phase 2: Lokale Steuerung. Teilweise gebaut.**
- Gebaut: LED-Modus je `xpadN` setzen und zurücksetzen (Standard `(N mod 4)+2`), `auto_poweroff` umschalten. LED-Befehle sind an Hardware bestätigt.
- LED ↔ Slot: für den ersten Slot bestätigt (`xpad0` schreibt auf Endpunkt 0x01). Für weitere Slots ungeprüft; der Monitor merkt sich den letzten LED-Befehl je Slot und kann das ablesen, sobald ein zweiter Controller da ist.
- Offen: Rumble-Test.
- Abnahme: Ein Slot lässt sich gezielt identifizieren (LED + Rumble), ohne dass ein anderer reagiert.

**Phase 3: Kernel-Spur.**
- Vorbedingung: Kernel-Header oder Build-Umgebung für 7.2.11-ogc4.1 prüfen (`ls /lib/modules/$(uname -r)/build`, sonst Bazzite-Build-Container oder Quellpaket des Kernels). Secure Boot ist aus, ein unsigniertes Modul lädt also.
- Patch für `xpad.c`: Statuspaket auswerten, `power_supply` (Kapazitätsstufe, Status) je Controller registrieren, Ausschalten über ein sysfs-Attribut, optional Akkuanfrage. Zuerst als Out-of-tree-Modul auf dem Gerät testen, dann an linux-input senden. Parallel Bazzite fragen, ob der Patch im Kernel mitgeführt werden kann.
- Plugin erkennt die neue Schnittstelle und bevorzugt sie.
- Abnahme: Mit gepatchtem Modul zeigt `upower -d` den Akku, und „Ausschalten“ im Plugin funktioniert.

**Phase 4: Veröffentlichung**
- Einstellungen, Deutsch/Englisch, Lizenz, Store-Einreichung, Sicherheits- und Datenschutztexte.

**Phase 5 (optional): Übernahme-Modus, Chatpad, Headset**

## 7. Sicherheit und Datenschutz

- usbmon zeigt den **gesamten** Bus, auch Tastatur und Maus am selben Bus. Das Backend muss jede Zeile sofort nach `(Bus, Gerät)` filtern, fremde Zeilen verwerfen, nichts davon speichern oder loggen und Eingabepakete des Controllers nur zählen, nicht aufzeichnen. Das ist in `tools/capture_usbmon.py` so umgesetzt und wird im Plugin übernommen.
- Das Plugin zeigt in den Einstellungen offen an, dass es USB-Verkehr des Receivers liest. Der Monitor ist Opt-in.
- Spur B und D vermeiden die Busbreite von usbmon und sind aus Datenschutzsicht besser.
- Fremde Aufrufe des Root-Backends, alle ohne Nutzereingabe und mit absolutem Pfad und bereinigter Umgebung (`safe_exec.py`): das feste `modprobe usbmon`; `systemctl daemon-reload`, `systemctl enable --now x360-receiver-poweroff.service` und `systemctl disable --now x360-receiver-poweroff.service` (nur für den einen eigenen Dienst, nur beim Ein- und Ausschalten der Option, beim Start-Abgleich und beim Entfernen); und die USB-Befehle des kurzen Zugriffs. Dateien außerhalb von Decky: `/etc/systemd/system/x360-receiver-poweroff.service` und `/var/lib/x360-receiver/`, nur bei eingeschalteter Option, root-eigen (Dateien 0644, Ordner 0755, unabhängig von der umask), Symlinks an diesen Orten werden abgelehnt, Löschen nur für genau diesen Ordnernamen. Der Dienst läuft als Root; sein Programm ist eine Kopie aus dem Plugin und wird bei jedem Plugin-Start aktualisiert, solange die Option an ist.
- Root-Rechte: Schreibzugriffe nur auf die benannten sysfs-Pfade (`leds/xpadN`, `module/xpad/parameters/auto_poweroff`), keine freien Shell-Aufrufe.
- Kurzer Zugriff: Das Backend akzeptiert nur Receiver, die es selbst erkannt hat (Bus und Geräteadresse), und Slots 0 bis 3. Gesendet werden nur die Befehle `00 00 00 40` und `00 00 08 C0` an den Endpunkt des gewählten Slots. Es gibt keine automatische Wiederholung; jede Aktion löst der Nutzer aus, das Ausschalten mit Rückfrage.

## 8. Offene Probleme und Risiken

1. **Zugriffsweg** (Abschnitt 2). Entscheidet über Umfang von v1.
2. **LED ↔ Slot zuordnen.** Der LED-Eintrag `xpadN` hängt am USB-Gerät, nicht an der Schnittstelle (belegt: `led_classdev_register(&xpad->udev->dev, …)`). Die Nummer N kommt aus einem globalen Zähler in Verbindungsreihenfolge. Lösung: LED beschreiben und im usbmon beobachten, auf welchem OUT-Endpunkt (0x01, 0x03, 0x05, 0x07) der Befehl erscheint. Ohne usbmon bleibt nur eine unsichere Heuristik. Die Zuordnung der Eingabegeräte (Rumble) ist dagegen eindeutig, weil deren Elternteil die Schnittstelle ist.
3. **Link-Report kommt nur beim Verbinden.** Ein Controller, der vor dem Start des Plugins verbunden war, liefert zunächst keinen Subtyp. Auswege: Plugin früh starten; auf Wunsch die `xpad`-Schnittstelle kurz lösen und neu binden (löst eine erneute Anfrage aus, trennt aber den Controller für Sekunden und darf nicht während eines Spiels passieren).
4. **Akkutyp- und Stufen-Bedeutung** unbekannt. Beobachtet wurde Stufe 2, Typ roh 1, Power-State roh 2; welche Batterie im Controller steckte und wie voll sie war, ist nicht bekannt. Die Anzeige sagt deshalb „Stufe 2 von 3“ und behauptet keinen Prozentwert.
5. **Klone und Drittanbieter-Receiver** können vom Protokoll abweichen. Die vorhandenen Beispielpakete stammen größtenteils von solchen Geräten.
6. **Bitfeld-Reihenfolge und Stufenzuordnung** sind aus einer C-Struct abgeleitet. Die Unit-Tests prüfen nur Konsistenz mit den Beispielpaketen, nicht die Hardware.
7. **Decky-Rahmen:** Plugin-Manifest und Build-Konfiguration müssen mit der aktuellen offiziellen Vorlage (`decky-plugin-template`) abgeglichen werden. Abgeglichen am 2026-11-04: `package.json`, `tsconfig.json`, `rollup.config.js`, Root-Flag (`root`, nach Prüfung im Decky-Quelltext; die Vorlage enthält nur den ausgeschalteten Platzhalter `_root`). Der Build mit `@decky/rollup` läuft in einer Testkopie durch, geladen wurde das Plugin in Decky noch nie. `@rollup/rollup-linux-x64-musl` steht wie in der Vorlage in `package.json` und lässt sich auf glibc-Rechnern nicht installieren; für lokale Builds in einer Kopie entfernen. Der Typcheck meldet einen Fehler in den Typen von `@decky/api` (fehlendes `react-router`), nicht in diesem Code.
8. **Suspend/Resume:** `xpad` schaltet Controller beim Suspend aus (wenn `auto_poweroff` an ist). Der Monitor muss offene usbmon-Handles nach dem Aufwachen neu aufbauen.
9. **Wechselwirkung mit Steam Input:** LED- und Rumble-Tests können laufende Spiele stören. Das Panel warnt davor.
10. **Immutables Bazzite:** Ein eigener Kernel oder ein Modul auf dem Zielgerät ist nur mit Aufwand möglich (Secure Boot, Signatur). Für Entwicklung deshalb auf einem Testsystem arbeiten.
11. **Lizenz:** Wenn Code aus `xpad.c` in den Patch eingeht, ist der Patch GPL-2.0. Das Plugin selbst: GPL-2.0-or-later vorschlagen, damit beides zusammenpasst. Zu entscheiden.
12. **Akku nur beim Verbinden gemeldet** (an Hardware bestätigt, Abschnitt 6). Die Akkuanzeige funktioniert nur für Controller, deren Verbinden das Plugin miterlebt hat, bis Stufe 3 oder 4 der Leiter steht.
13. **Mitschnitte abgeschnitten:** `grep` puffert in Blöcken, bei Abbruch geht der Rest verloren (zweiter Mitschnitt endete bei 12288 Byte). Künftig `grep --line-buffered`.
14. **Thread-Namenskollision:** `threading.Thread` nutzt intern `_handle`; mein Leser hatte eine gleichnamige Methode und scheiterte im Test. Behoben (`_process_line`). Als Hinweis für künftige Thread-Unterklassen.
15. **Kurzer Zugriff (takeover):** An Hardware funktioniert, `xpad` bindet danach wieder. Offen: Bleibt die Schnittstelle nach einem Fehler ungebunden, ist der Slot tot, bis `xpad` neu bindet (Controller aus/an oder von Hand); `SlotSession` gibt im Fehlerfall frei, das ist nur gegen eine Attrappe getestet. Das Decky-Backend braucht libusb auf dem Zielsystem (auf Bazzite vorhanden, im Decky-Prozess ungeprüft). Steam sieht den Controller kurz verschwinden (Wirkung ungeprüft, Phase 0e). Keine automatische Wiederholung.
16. **Akku-Frische teilweise geklärt.** Bei ausgeschaltetem Controller kam keine Antwort (nach der Reihenfolge der Läufe angenommen), also kein Zwischenspeicher. Der Wert war aber immer Stufe 2 (2 AA NiMH); ob er bei sinkendem Akku wirklich wechselt, ist ungeprüft, und NiMH hat eine flache Spannungskurve.
17. **Einrichtung auf dem Gerät teilweise bestätigt:** Installation per Zip, Laden in Decky, libusb im Decky-Prozess (Akkuabfrage, Ausschalten-Knöpfe) und der systemd-Dienst funktionieren laut Nutzer. Nicht ausdrücklich bestätigt: `modprobe usbmon` aus dem Plugin (Monitor-Schalter) und `_uninstall` (Entfernen per Decky) unter echtem Decky. Decky ruft `_uninstall` auch beim Neuinstallieren derselben Zip auf; Einstellungen gehen dann verloren.
18. **Ausschalten beim Herunterfahren aus dem Plugin heraus ist nicht zuverlässig möglich; ersetzt durch einen systemd-Dienst (vom Nutzer am Gerät bestätigt: „Das Herunterfahren funktioniert jetzt“, 2026-11-05).** Drei Versuche im Plugin schlugen am Gerät fehl (clean env für `systemctl`; Überwachung vor dem Stoppsignal; eigener Thread mit feiner Spur). **Belege:** (a) Spur: `systemctl` antwortet im Plugin (`systemctl_selftest` 0,01 s). (b) Deckys Journal beim Herunterfahren (`journalctl -b -1 -u plugin_loader`): um 321,307 s sagt Decky allen sechs Plugins „Shutting down“; SteamGridDB, ProtonDB Badges und CSS Loader antworten sofort („Calling Loader unload function“), **„X360 Receiver“, NonSteamLaunchers und Decky LSFG-VK nicht**; alle drei werden nach 5 s mit SIGKILL beendet (326,33 s), Decky endet 326,47 s. Die Spur hat für diesen Lauf kein `unload_entered`. Warum diese drei Plugins nicht reagieren, ist ungeklärt (zwei fremde sind betroffen, also kein Fehler allein im eigenen Code). (c) Systemd meldete `stopping` erst im Moment des Stoppsignals (Steam schloss bei 318 bis 319 s), eine Überwachung hätte keinen Vorsprung. (d) Zwischen Beginn des Herunterfahrens und Ende von Decky liegen mehr als 5 s; USB war vermutlich noch da (abgeleitet, nicht geprüft). **Lösung (bestätigt):** systemd-Dienst, siehe Zeile „Beim Herunterfahren ausschalten“ in Abschnitt 3. Damit ist am Gerät gezeigt, dass `ExecStop` rechtzeitig läuft, bevor USB verschwindet, und dass `/usr/bin/python3`, libusb und SELinux auf Bazzite den Dienst zulassen. **Offen:** Ob auch ein Neustart (nicht nur Herunterfahren) und mehrere Controller gleichzeitig zuverlässig ausgehen, ist nicht gezielt geprüft; die Dauer bis zum Abschalten wurde nicht gemessen. Der Bericht `last-run.json` zeigt nach dem Neustart in der Diagnose, ob und was der Dienst getan hat. Wird das Plugin per Decky-„Uninstall“ entfernt, räumt `_uninstall` den Dienst weg; wird der Plugin-Ordner anders gelöscht, bleibt der Dienst bis zum manuellen Entfernen (`sudo systemctl disable --now x360-receiver-poweroff.service; sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver; sudo systemctl daemon-reload`).
19. **Anwesenheit über sysfs und LED-Zuordnung nur aus dem Quelltext:** Ob unter `<Schnittstelle>/input/` bei verbundenem Controller ein Eintrag erscheint und die LED unter `<usb_path>/leds/` liegt, ist am Gerät nicht geprüft (Prüfbefehle in Abschnitt 10). Stimmt das nicht, zeigt die Oberfläche ohne Monitor keine Controller, mit „n weiterer Controller verbunden“.
20. **Oberfläche nie in Steams echtem Aussehen gesehen.** Geprüft sind Typen, Build, Aufbau und Klicks gegen gestellte Bausteine (`tools/frontend_render_test.mjs`). Ungeprüft: Optik, Umbrüche, Fokus-Navigation mit dem Controller, ob Decky `Field` mit `focusable` wie erwartet behandelt.
21. **Akkuabfrage nach dem Start kostet ein kurzes Verschwinden je Controller.** Sie läuft bei jedem Laden des Plugins (Gerätestart, Decky-Neustart, Plugin-Aktualisierung, Neuinstallieren). Wird Decky mitten im Spiel neu geladen, verschwinden die verbundenen Controller nacheinander für je ca. 3 s. Es gibt dafür keinen Schalter. Wie Steam reagiert (Spielernummer, „getrennt/verbunden“), ist ungeprüft (Phase 0e). Beim Gerätestart ist normalerweise noch kein Controller verbunden, dann passiert nichts. Ohne Monitor wird ein später verbundener Controller nicht automatisch abgefragt (der Receiver meldet den Akku beim Verbinden, aber nur der Monitor liest das mit).

## 9. Tests

- 200 Tests, alle bestanden: `python3 -I -m unittest discover -s tests`.
  - `test_protocol.py`: Parser, Befehlsbau, usbmon-Zeilen.
  - `test_discovery.py`: Receiver-Erkennung gegen einen **nachgebauten** sysfs-Baum (echte Struktur ungeprüft).
  - `test_fixture_capture.py`: 6 Tests gegen den echten Mitschnitt vom 2026-11-04.
  - `test_fixture_idle.py`: 7 Tests gegen den echten Mitschnitt vom 2026-11-05 (Verbindungsfolge, kein weiterer Zustand im Leerlauf, Zustand im Eingabepaket-Header, nur zwei xpad-LED-Befehle, `F8`-Umschalter, Monitor mit Alter des Werts).
  - `test_fixture_events.py`: 8 Tests gegen den vollständigen dritten Mitschnitt (LED-Befehle und Endpunkt, Tasten inkl. Guide 0x0400, Neubinden ohne Zustandsfolge, byteidentischer Link-Report, Poweroff 5,056 s nach Guide, Zustand mit Power-State 0 danach, Monitor-Quellenkennzeichnung).
  - `test_fixture_takeover.py`: 7 Tests gegen den vierten Mitschnitt (Lösen von `xpad`, Antwort auf Anwesenheits- und Akkuanfrage, Ausschalten mit Power-State 0, Neubinden von `xpad`, manuelles Wiedereinschalten, Monitor über die ganze Sitzung).
  - `test_actions.py`: 5 Tests (Akkuanfrage, Ausschalten, Fehlerrückgabe, Sperre bei gleichzeitigem Zugriff).
  - `test_packaging.py`: 2 Tests (Aufbau der Decky-Zip, Root-Flag).
  - `test_takeover.py`: 8 Tests mit Attrappen-Backend (Endpunkte je Slot, Freigabe auch bei Fehlern, Befehlslänge) und ein Aufruf von libusb ohne Gerät.
  - `test_monitor.py`: Zustandsautomat, Slot-Zuordnung über Endpunkte, fremde Geräte, Wiederverbinden, Begrenzung unbekannter Pakete, kein Eingabeinhalt im Zustand, Leser auf Testdatei, Dienst ein/aus, LED- und `auto_poweroff`-Logik mit Eingabeprüfung.
  - `test_cleanup.py`: 10 Tests (Löschen nur der eigenen Decky-Ordner: Symlinks, `..`, falsche Ordnerart, Bazzite-Symlink für `DECKY_HOME`; Wiederherstellen von `auto_poweroff`).
  - `test_backend.py`: `main.py` mit Attrappen-`decky` und Attrappe für `poweroff_unit` (nie echte Dateien unter /etc oder /var): Lebenszyklus, Statusform, Standby-Option gespeichert und nach Neustart erneut gesetzt, Herunterfahren-Option richtet den Dienst ein/entfernt ihn (Fehler: Option bleibt aus, Fehlertext), Abgleich beim Start (Option an: einrichten/aktualisieren; aus: Rest entfernen; Umschalten direkt nach dem Start wird nicht rückgängig gemacht), `_unload` schaltet nichts aus und lässt den Dienst in Ruhe, „Alle ausschalten“, `_uninstall` (Wert wiederhergestellt, Dienst entfernt auch bei Fehler, fremdes Plugin unberührt, fehlende Ordner).
  - `test_battery_cache.py`: 6 Tests (abgefragte Akkustände mit Alter; Eintrag verfällt erst, wenn der Slot länger als 15 s fehlt, weil der Controller während der Abfrage selbst kurz verschwindet).
  - `test_backend.py` prüft zusätzlich die Abfrage nach dem Start: jeder verbundene Controller genau einmal und nacheinander, kein Controller keine Abfrage, keine Antwort/Fehler/Ausnahme stoppt nichts, „Besetzt“ wird wiederholt, `_unload` bricht eine noch wartende Abfrage ab, manuelle Abfrage wird ebenfalls gemerkt.
  - `test_view.py`: Receiver-Ansicht (Zusammenführung Monitor/sysfs, LED nur bei eindeutiger Zuordnung, nicht zugeordnete Controller, Ziele für das Ausschalten), LED-Zuordnung über sysfs-Pfad, Anwesenheit über `input/`, alles gegen nachgebaute Bäume.
  - `test_shutdown.py`: Ausschalten mehrerer Ziele mit Wiederholung bei Besetzt, Zeitlimit, Fehler in einem Slot.
  - `test_poweroff_unit.py`: Dienst-Text (`ExecStop=-…`, `RemainAfterExit`, Zeitlimit größer als das des Programms; `systemd-analyze verify` einmalig von Hand ohne Meldung), Einrichten (Dateien und Rechte unabhängig von umask, feste `systemctl`-Aufrufe mit bereinigter Umgebung, idempotent, Update ohne Neuladen, Fehler räumt auf, Symlinks abgelehnt), Entfernen (Programm zuerst gelöscht, dann Dienst gestoppt; nie Symlink-Ziel oder falsch benannter Ordner), Kopie läuft allein mit System-Python im Isolationsmodus und lädt nur die Module der Liste, Einstieg endet mit 0 und schreibt den Bericht, Urteile der Diagnose.
  - `test_poweroff_cli.py`: Ablauf des Programms (Ziele, Bericht, Fehler werden berichtet statt geworfen, nichts zu senden), `main` endet immer mit 0 und schreibt `last-run.json` atomar.
  - `tools/frontend_render_test.mjs` (nicht Teil von `unittest`): Rendertest des gebauten Frontends mit jsdom und gestellten Decky-Bausteinen.
- Diese Tests sagen nichts über echtes Verhalten aus, außer dort, wo ein Mitschnitt die Eingabe ist.
- Wiedergabe: `tools/capture_usbmon.py --file <aufzeichnung>`.
- Hardware-Matrix für Abnahme: ein Gamepad mit AA und mit Akkupack; falls vorhanden Headset, Chatpad, Gitarre/Schlagzeug; zwei Receiver.

## 10. Einrichtung und nächste Prüfung

### Installieren und Entfernen (Deckys eigener Weg)

Ziel: so installieren und entfernen wie jedes Drittanbieter-Plugin, ohne Skript. Grundlage ist der Decky-Quelltext (`browser.py`, `sandboxed.py`, Übersetzungstexte), geprüft am 2026-11-05; am Gerät nicht erprobt.

- **Installieren:** Decky-Einstellungen → „Allgemein“ → **Developer mode** an → Reiter „Entwickler“ → „Third-Party Plugins“ → **Install Plugin from ZIP File** → **Browse** → `X360-Receiver.zip` wählen → Hinweis bestätigen. Alternativ **Install Plugin from URL**. Die Zip ist fertig gebaut (Frontend enthalten, kein Node nötig) und hat die Form `X360 Receiver/plugin.json`, `main.py`, `dist/index.js`, `py_modules/…`. Decky liest den Ordnernamen aus `plugin.json` (`name`).
- **Root:** `"flags": ["root"]` (genau diese Zeichenfolge). Ohne das Flag liefe das Plugin als normaler Nutzer und scheiterte an libusb, sysfs und usbmon. Ob Decky beim Installieren zusätzlich nachfragt, ist ungeprüft.
- **Entfernen:** Plugin-Aktionen im Decky-Menü → **Uninstall**. Ablauf in Decky: `_unload` → `_uninstall` → Plugin-Ordner löschen. Decky löscht selbst nur den Plugin-Ordner; Einstellungen, Daten und Logs unter `DECKY_HOME/settings|data|logs/<Ordner>` räumt `Plugin._uninstall` weg (`x360w/cleanup.py`).
  - `_uninstall` stellt `auto_poweroff` auf den Wert zurück, den es vor der ersten Änderung durch das Plugin hatte (der Wert wird beim ersten Ändern in den Einstellungen gemerkt).
  - Gelöscht wird nur genau `<DECKY_HOME>/<settings|data|logs>/<Name>`; keine Symlinks, nichts außerhalb, `..` wird abgewiesen. Das ist wichtig, weil das Backend als root läuft. `/home` ist auf Bazzite ein Symlink nach `/var/home`, `DECKY_HOME` selbst darf deshalb über einen Symlink erreichbar sein.
  - Nicht zurückgenommen: das geladene Modul `usbmon` (bis zum Neustart) und ein gesetzter LED-Modus (bis zum nächsten Verbinden). Der systemd-Dienst samt `/var/lib/x360-receiver/` wird dagegen entfernt (`_uninstall` ruft `poweroff_unit.uninstall`, auch wenn die Option aus ist). Sonst legt das Plugin nichts außerhalb dieser Ordner an.
- **Update:** Dieselbe Zip noch einmal. Decky deinstalliert die alte Fassung zuerst (`uninstall_plugin`) und ruft dabei `_uninstall` auf. Folge: Einstellungen (Monitor an/aus) gehen verloren, der Monitor ist danach aus. Das ist gewollt einfach gehalten.
- **Prüfen am Gerät:** Nach „Uninstall“ dürfen weder `~/homebrew/plugins/X360 Receiver` noch `~/homebrew/settings/X360 Receiver`, `~/homebrew/data/X360 Receiver` und `~/homebrew/logs/X360 Receiver` existieren, und `cat /sys/module/xpad/parameters/auto_poweroff` zeigt den Ausgangswert.

Der Monitor („Akku-Status mitlesen“) ist aus und lädt `usbmon` selbst, sobald du ihn einschaltest. Ohne Monitor funktionieren „Akku abfragen“, „Ausschalten“, LEDs und der `auto_poweroff`-Schalter.

### Was beim ersten Start zu prüfen ist

1. Erscheint der Receiver im Plugin (Bus 1, Gerät 2)? Wenn nicht: `sudo journalctl -u plugin_loader -n 50` und den Anfang der Meldung schicken.
2. „Akku abfragen“ für Slot 1: Zeigt es „Akku Stufe 2 von 3“? Fehlertexte wie „libusb nicht ladbar“ zeigen, dass libusb im Decky-Prozess fehlt.
3. Steam beim kurzen Verlust beobachten: Erscheint „Controller getrennt/verbunden“? Ändert sich die Spielernummer? Geht die Steuerung danach sofort?
4. „Akku-Status mitlesen“ einschalten, Controller ausschalten und wieder einschalten: Erscheint der Akku nach dem Verbinden von selbst?
5. Neue Oberfläche: Erscheint unter dem Receiver der verbundene Controller als Karte? Ohne Monitor: Kommt er trotzdem (ohne Akku)? Wenn nicht, bitte (Controller an) `ls /sys/bus/usb/devices/1-3:1.0/` und `readlink -f /sys/class/leds/xpad0` schicken.
6. „Beim Standby ausschalten“: Gerät in den Standby schicken und wecken. Ist der Controller aus? (Kernel-Standard ist an.)
7. Akku nach dem Start: Controller einschalten, dann das Plugin neu starten (Decky neu laden oder Gerät neu starten, Controller vorher verbunden lassen). Erscheint der Akkustand ohne Zutun? Jeder Controller verschwindet dabei nacheinander ca. 3 s; wie Steam darauf reagiert (Spielernummer, Meldungen), ist ungeprüft.
8. „Beim Herunterfahren ausschalten“: Option einschalten (das Plugin richtet den Dienst ein; schlägt das fehl, bleibt die Option aus und es erscheint ein Fehlertext, bitte abschreiben). Unter „Allgemein → Diagnose → Dienst beim Herunterfahren“ steht danach „eingerichtet, noch nicht gelaufen“. Dann Controller verbinden, Gerät herunterfahren, neu starten. Ist der Controller aus gewesen? Danach steht in der Diagnose das Urteil des Dienstes (Zeit, Dauer, Ziele, Ergebnis); bitte abschreiben. Zusätzlich: `systemctl status x360-receiver-poweroff.service`, `sudo journalctl -b -1 -o short-monotonic | grep -i "x360"` (der Dienst schreibt eine Zeile „x360w-poweroff {…}“) und `cat /var/lib/x360-receiver/last-run.json`. Option wieder ausschalten und prüfen, dass Dienst und Ordner weg sind (`ls /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver`).

### Fragen

1. War dein erster Lauf von `--battery-request` bei ausgeschaltetem Controller und der zweite bei eingeschaltetem? Davon hängt die Aussage „kein Zwischenspeicher“ ab.
2. Wie viele Receiver und welche Controller-Arten besitzt du?
3. Startest du zuerst den Controller oder zuerst den Rechner?

## 11. Gemessen am 2026-11-04

- System: Bazzite-Deck 44.20261026, Kernel 7.2.11-ogc4.1.fc44, **Secure Boot aus**, Lockdown `none`, `xpad` als Modul, `auto_poweroff` = Y.
- Receiver 045E:0719 an Bus 1, Gerät 2. Schnittstellen 0/2/4/6 gehören `xpad`, 1/3/5/7 (Audio) haben keinen Treiber.
- `upower` zeigt keinen Controller-Akku.
- usbmon funktioniert über debugfs als root und liefert volle Pakete. Fremde Geräte am selben Bus tauchten im gefilterten Mitschnitt nicht auf.
- Die LED `xpad0` existiert nur, solange ein Controller verbunden ist. Der erste Schreibversuch scheiterte deshalb mit „Datei nicht gefunden“, weil der Controller aus war. Mein erster Test (`echo 6`) war zudem schlecht gewählt: Modus 6 sah aus wie der Endzustand von xpad selbst. Später: LEDs reagieren (Modus nicht festgehalten).
- Statuspaket (Stufe 2, Typ roh 1, Power-State roh 2) kam einmal, beim Verbinden. Mitschnitt wurde nach ca. 38 s abgebrochen: keine Aussage zu periodischen Updates, Guide-Halten oder Ausschalten.

## 12. Gemessen am 2026-11-05

- Zweiter Mitschnitt, 393 s, ein Gamepad (`docs/PROTOCOL.md`, Abschnitt 7). Die Datei war am Ende abgeschnitten.
- Der Controller wurde aus- und wieder eingeschaltet (6,4 s / 13,1 s). Die Verbindungsfolge war dieselbe wie am Vortag, Akku wieder Stufe 2.
- **Kein weiteres Statuspaket in den folgenden ca. 380 s** (eine einzelne Eingabe bei 73,5 s löste auch keins aus).
- Der Zustand stand diesmal einmal im Header eines Eingabepakets. Parser und Monitor werten das jetzt aus.
- 50 `F8 01/02`-Pakete, strikt abwechselnd, Abstände ≥ 2,1 s.
- Nicht enthalten, obwohl geplant: LED-Test mit Modus 10, Guide-Halten, Tastendrücke. Wahrscheinlich im abgeschnittenen Teil oder nach dem Ende des Fensters.

## 13. Gemessen am 2026-11-05, dritter Mitschnitt

- 246,7 s, vollständig. Details und Zeiten: `docs/PROTOCOL.md`, Abschnitt 8.
- LED-Befehle gehen auf Endpunkt 0x01 (erster Slot). Weder LED-Befehle noch Tasten lösen ein Statuspaket aus. Guide hat die Tastenmaske 0x0400.
- Neubinden von `xpad`: Der Receiver antwortet auf `08 00 0F C0` mit Verbindungspaket und Link-Report (byteidentisch zu früheren), sonst nichts.
- Ausschalten: `xpad` sendet `C0` 5,056 s nach dem Guide-Druck beim nächsten Paket; danach Zustandspaket mit Power-State 0, Trennung, LED 0.

## 14. Gemessen am 2026-11-05, vierter Mitschnitt (Phase 0d)

- Kurzer Zugriff mit `tools/probe_takeover.py`: Anwesenheitsabfrage, Akkuanfrage und Ausschalten funktionieren, `xpad` bindet jedes Mal wieder (`docs/PROTOCOL.md`, Abschnitt 9).
- Akkuanfrage `00 00 00 40` wird nach 27 ms mit einem Statuspaket beantwortet (Stufe 2, Power-State 2). Frische ungeklärt.
- Ausschalten per Befehl bestätigt (Statuspaket mit Power-State 0, danach `08 00`).
- Nach manuellem Einschalten verbindet sich der Controller normal und `xpad` setzt die LED.

## 15. Gemessen am 2026-11-05, Terminalläufe

- Akkuanfrage ohne Antwort (erster Lauf) und mit Antwort (zweiter Lauf); Batterie: 2 AA NiMH; kein Ladekabel vorhanden. `docs/PROTOCOL.md`, Abschnitt 10.
- sysfs: Receiver `1-3`, `xpad` an `1-3:1.0/1.2/1.4/1.6`. Passt zur Erkennung in `discovery.py`.
- Das Plugin bleibt privat; Ziel ist eine Einrichtung mit einem Befehl.

