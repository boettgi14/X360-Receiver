# X360 Receiver

Decky-Loader-Plugin für den **Xbox 360 Wireless Gaming Receiver** auf Bazzite und SteamOS (Gaming Mode). Es zeigt den Akkustand aller verbundenen Controller, steuert ihre LEDs und schaltet sie aus – auch beim Standby und beim Herunterfahren. Mehrere Receiver werden unterstützt. Die Oberfläche ist deutsch.

> **Stand:** Das Plugin läuft auf einem Bazzite-Gerät mit einem Receiver (USB-ID `045E:0719`) und einem Gamepad (2 AA-Akkus, kein Ladekabel). Akkuabfrage, LED-Zuordnung, Ausschalten und das Layout sind dort geprüft. Auch „Beim Herunterfahren ausschalten“ (über einen systemd-Dienst, siehe [Hinweis](#beim-herunterfahren-ausschalten)) funktioniert dort. Was gesichert ist und was nur aus Quelltexten oder Unit-Tests stammt, steht in [`PLAN.md`](PLAN.md) und [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

## Funktionen

| Bereich | Was das Plugin tut |
|---------|--------------------|
| **Allgemein** (gilt für alle Receiver) | *Überwachung:* Akku-Status mitlesen (USB-Monitor, standardmäßig aus). *Energie:* „Beim Standby ausschalten“, „Beim Herunterfahren ausschalten“, „Alle Controller jetzt ausschalten“. *Diagnose:* Ergebnis des letzten Laufs beim Herunterfahren. |
| **Receiver** | Je Receiver ein Abschnitt mit den verbundenen Controllern als ausklappbare Karten. |
| **Controller-Karte** | Akku als Balken mit Stufe (0 bis 3, das Protokoll kennt nur vier Stufen), „Akku jetzt abfragen“, „Controller ausschalten“, LED-Muster (Modi 0 bis 15; `xpad0` ist Controller 1, `xpad1` Controller 2 …), Details. |
| **Akku nach dem Start** | Der Receiver meldet den Akku nur beim Verbinden. Deshalb fragt das Plugin direkt nach dem Start einmal alle schon verbundenen Controller ab und merkt sich den Wert. |

## Wie es funktioniert

Der Kernel-Treiber `xpad` zeigt weder Akku noch Ausschalten an. Das Plugin nutzt vier Wege (Einzelheiten und Vertrauensgrade in `PLAN.md`):

1. **sysfs** (immer): Receiver erkennen, belegte Slots, LEDs unter `/sys/class/leds/xpadN/brightness`, Standby-Verhalten über `/sys/module/xpad/parameters/auto_poweroff`.
2. **USB-Monitor `usbmon`** (optional, Schalter „Akku-Status mitlesen“): liest die Pakete des Receivers mit und dekodiert Verbindung und Akkustufe. Er sieht den ganzen Bus, das Plugin filtert sofort nach Bus und Gerät, verwirft alles andere und zählt Eingabepakete nur.
3. **Kurzer Zugriff über libusb** (Akku abfragen, Ausschalten): `xpad` gibt die Schnittstelle des Slots kurz frei, das Plugin sendet `00 00 00 40` (Akkuanfrage) oder `00 00 08 C0` (Ausschalten), danach bindet `xpad` wieder. Der betroffene Controller verschwindet dabei etwa 3 Sekunden.
4. **systemd-Dienst** (nur für „Beim Herunterfahren ausschalten“).

### Beim Herunterfahren ausschalten

`xpad` hat keinen Hook fürs Herunterfahren, und Decky beendet das Plugin dabei nicht zuverlässig: Am Gerät bekam es das Stoppsignal, rief aber `_unload` nie auf und wurde nach 5 Sekunden mit SIGKILL beendet (zwei fremde Plugins ebenso, siehe `PLAN.md`, Risiko 18). Deshalb richtet das Plugin beim Einschalten der Option einen kleinen systemd-Dienst ein:

- `/etc/systemd/system/x360-receiver-poweroff.service` (`Type=oneshot`, `RemainAfterExit=yes`, `ExecStop`)
- `/var/lib/x360-receiver/` mit einer Kopie des Programms (`poweroff.py`, `x360w/`) und dem Bericht `last-run.json`

Beim Herunterfahren und Neustart führt systemd `ExecStop` aus: Das Programm ermittelt die verbundenen Controller wie der Knopf „Alle Controller jetzt ausschalten“ und schaltet sie aus. Beim Ausschalten der Option und beim Entfernen des Plugins werden beide Orte wieder gelöscht. Auf dem Testgerät gehen die Controller damit beim Herunterfahren aus; Neustart und mehrere gleichzeitig verbundene Controller sind nicht gezielt geprüft.

## Voraussetzungen

- Bazzite oder SteamOS mit [Decky Loader](https://decky.xyz/) (Gaming Mode)
- Xbox 360 Wireless Gaming Receiver (`045E:0291`, `045E:0719` oder `045E:02A9`) und der Kernel-Treiber `xpad` (Standard)
- Das Plugin läuft mit Root-Rechten (`"flags": ["root"]` in `plugin.json`), weil es libusb, sysfs und usbmon braucht
- `libusb-1.0` und `/usr/bin/python3` auf dem Gerät (nur für den systemd-Dienst; auf Bazzite vorhanden, der Dienst läuft dort)

## Installieren und Entfernen

Das Plugin ist privat: Es gibt keinen Store-Eintrag, du baust die Zip selbst (siehe unten).

**Installieren** (einmalig Entwicklermodus, danach nur die Zip):
1. `X360-Receiver.zip` auf das Gerät legen (z. B. nach `~/Downloads`).
2. Decky-Einstellungen → „Allgemein“: **Developer mode** einschalten. Es erscheint der Reiter „Entwickler“.
3. Dort unter „Third-Party Plugins“ bei **Install Plugin from ZIP File** auf **Browse** drücken, die Zip wählen, den Hinweis bestätigen.
4. Das Plugin erscheint im Decky-Menü als „X360 Receiver“.

**Entfernen:** Im Decky-Menü bei „X360 Receiver“ **Uninstall** wählen. Das Plugin stellt `auto_poweroff` auf den Ausgangswert zurück, entfernt den systemd-Dienst samt `/var/lib/x360-receiver/` und löscht seine Einstellungs-, Daten- und Log-Ordner. Nicht zurückgenommen werden das geladene Kernelmodul `usbmon` (bis zum Neustart) und ein gesetzter LED-Modus (bis zum nächsten Verbinden). Wurde der Plugin-Ordner an Decky vorbei gelöscht, bleibt der Dienst liegen:

```bash
sudo systemctl disable --now x360-receiver-poweroff.service
sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver
sudo systemctl daemon-reload
```

**Aktualisieren:** dieselbe Zip noch einmal installieren. Decky entfernt dabei zuerst die alte Fassung (inklusive Aufräumen); gespeicherte Einstellungen gehen verloren, die Optionen sind danach aus.

## Bauen

Das Backend ist reines Python und braucht keinen Build. Gebaut wird nur das Frontend (TypeScript/React mit der Decky-Toolchain).

**Voraussetzungen:** Node.js ab 18 mit npm, Python 3.

```bash
npm ci                                  # Abhängigkeiten laut package-lock.json
npm run typecheck                       # TypeScript prüfen
npm run build                           # erzeugt dist/index.js (Rollup)
python3 -I tools/make_zip.py X360-Receiver.zip
```

`make_zip.py` packt `plugin.json`, `package.json`, `main.py`, `dist/index.js` und `py_modules/` in die Form, die Decky erwartet (`X360 Receiver/…`). Quelltext des Frontends, Tests und Mitschnitte kommen nicht hinein. `npm run watch` baut bei Änderungen neu. `pnpm` funktioniert ebenfalls (die Vorlage von Decky nutzt es), die mitgelieferte Lockdatei gehört aber zu npm.

Hinweis: `@rollup/rollup-linux-x64-musl` steht bewusst unter `optionalDependencies` (Vorlage der Decky-Entwickler für musl-Umgebungen); auf glibc-Systemen wird es übersprungen.

## Tests

```bash
python3 -I -m unittest discover -s tests          # Backend, ohne Hardware und ohne root
```

Die zwei Zip-Tests (`test_packaging.py`) werden übersprungen, solange `dist/index.js` fehlt; nach `npm run build` laufen sie mit.

Die Tests laufen vollständig mit Attrappen: Parser und Zustandsautomat, Wiedergabe von vier echten usbmon-Mitschnitten (`tests/fixtures/`), der kurze Zugriff mit Attrappen-Backend, `main.py` mit einem nachgebauten `decky`-Modul. Der systemd-Dienst wird nur in Temp-Ordnern mit einem nachgebauten `systemctl` getestet, nie unter `/etc` oder `/var`.

Rendertest für das gebaute Frontend (gestellte Decky-Bausteine in jsdom; kein Test gegen Steams echte Oberfläche):

```bash
mkdir /tmp/render && cd /tmp/render && npm install react react-dom jsdom
node <Pfad-zum-Repo>/tools/frontend_render_test.mjs <Pfad-zum-Repo>/dist/index.js
```

## Aufbau des Repos

| Pfad | Inhalt |
|------|--------|
| `plugin.json`, `package.json`, `rollup.config.js`, `tsconfig.json`, `main.py`, `src/index.tsx` | Decky-Plugin (Metadaten, Backend-Einstieg, Oberfläche), mit der offiziellen Vorlage abgeglichen |
| `py_modules/x360w/` | Backend-Bibliothek: Protokoll (`protocol`), usbmon-Parser und -Leser, Zustandsautomat (`monitor`), Überwachungsdienst (`service`), LED und `auto_poweroff` (`controls`), Receiver-Erkennung (`discovery`), Ansicht je Receiver (`view`), kurzer Zugriff und Aktionen (`takeover`, `actions`), Akku-Zwischenspeicher (`battery_cache`), Ausschalten mehrerer Controller (`shutdown`), systemd-Dienst (`poweroff_unit`, `poweroff_cli`), Aufräumen beim Entfernen (`cleanup`), feste Programmaufrufe (`safe_exec`) |
| `tests/` | Unit-Tests und Mitschnitte (`tests/fixtures/`) |
| `tools/make_zip.py` | baut die Zip für Decky |
| `tools/frontend_render_test.mjs` | Rendertest des gebauten Frontends |
| `tools/discover.sh` | nur lesende Systemprüfung (Receiver, `xpad`, LEDs, usbmon) |
| `tools/capture_usbmon.py` | zeichnet die Pakete eines Receivers auf und dekodiert sie (root, nur Bus und Gerät aus `discover.sh`) |
| `tools/probe_takeover.py` | sendet Akkuanfrage oder Ausschalten an einen Slot (root; nicht während eines Spiels) |
| `docs/PROTOCOL.md` | Protokoll des Receivers, jede Aussage mit Vertrauensgrad |
| `PLAN.md` | Plan, Zugriffswege, Messungen, offene Risiken, Prüfschritte nach der Installation |
| `CLAUDE.md` | Projektregeln für die Arbeit mit Claude Code |

## Sicherheit und Datenschutz

- Das Backend läuft als root, schreibt aber nur auf die benannten sysfs-Pfade und kennt genau diese fremden Aufrufe: `modprobe usbmon`, `systemctl daemon-reload | enable --now | disable --now` für den einen eigenen Dienst (alle mit absolutem Pfad und bereinigter Umgebung, ohne Nutzereingabe) und die beiden USB-Befehle des kurzen Zugriffs an bekannte Receiver und Slots 0 bis 3.
- Der Dienst läuft als root. Sein Ordner und seine Dateien gehören root und sind nur für root schreibbar (0644/0755, unabhängig von der `umask`); Symlinks an diesen Orten werden abgelehnt.
- usbmon ist standardmäßig aus und wird nur mit dem Schalter „Akku-Status mitlesen“ geladen. Mitschnitte anderer Geräte werden sofort verworfen und nie gespeichert oder geloggt; Eingabepakete werden nur gezählt.
- Es gibt keine Netzwerkzugriffe.

## Bekannte Grenzen

- Nur 4 Akkustufen, keine Prozentwerte (so meldet es das Protokoll).
- Akkuabfrage und Ausschalten lassen den betroffenen Controller etwa 3 Sekunden verschwinden. Wie Steam darauf reagiert, ist nicht gezielt geprüft; nicht während eines Spiels abfragen.
- Mehrere Receiver: Die Zuordnung LED ↔ Controller ist dann nicht gesichert (die Receiver teilen sich die LED-Nummern). Auf dem Testgerät gab es nur einen Receiver.
- Chatpad und Headset werden nicht unterstützt.
- „Beim Herunterfahren ausschalten“ ist nur mit einem Receiver und einem Controller geprüft, und nur beim Herunterfahren (nicht gezielt beim Neustart).
- Fokus-Navigation mit dem Controller in der Plugin-Oberfläche ist nicht gezielt geprüft.

## Lizenz

[GNU General Public License, Version 2 oder (nach Wahl) jede spätere Version](LICENSE) (`GPL-2.0-or-later`).

Warum diese Lizenz: Das Protokollwissen und die Tabelle der LED-Modi stammen aus dem Linux-Kernel-Treiber `xpad` (`drivers/input/joystick/xpad.c`, `GPL-2.0-or-later`). `package.json` trägt dieselbe Kennung. Die Lizenz gilt für den Quelltext in diesem Repo; die Abhängigkeiten (React, Decky-Bibliotheken u. a.) behalten ihre eigenen Lizenzen. Das ist keine Rechtsberatung.

„Xbox“ und „Xbox 360“ sind Marken der Microsoft Corporation. X360 Receiver ist ein unabhängiges Projekt und steht in keiner Verbindung zu Microsoft; die Namen werden nur genannt, um die unterstützte Hardware zu bezeichnen.
