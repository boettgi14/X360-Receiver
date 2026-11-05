# Projektregeln für Claude Code

- Ziel und Plan: `PLAN.md`. Protokollwissen: `docs/PROTOCOL.md`. Erst dort nachlesen, dann ändern.
- Jede Protokollaussage trägt einen Vertrauensgrad (Quelle, Probe, Hypothese). Neue Erkenntnisse aus echter Hardware ersetzen Hypothesen und werden in `docs/PROTOCOL.md` nachgezogen.
- Keine Aussage als bestätigt darstellen, die nur aus Unit-Tests oder Quellen stammt.
- Tests: `python3 -I -m unittest discover -s tests` vor jedem Commit.
- Datenschutz: usbmon sieht den ganzen Bus. Fremde Geräte sofort verwerfen, nichts speichern oder loggen. Eingabepakete nur zählen.
- Backend (root) schreibt nur auf die benannten sysfs-Pfade und kennt genau diese fremden Aufrufe: das feste `modprobe usbmon`, `systemctl daemon-reload | enable --now | disable --now` ausschließlich für den eigenen Dienst `x360-receiver-poweroff.service` (alle über `safe_exec.run_fixed` mit bereinigter Umgebung, ohne Nutzereingabe) und die USB-Befehle des kurzen Zugriffs (`00 00 00 40`, `00 00 08 C0`) an bekannte Receiver und Slots 0 bis 3. Außerhalb von Decky legt das Plugin nur `/etc/systemd/system/x360-receiver-poweroff.service` und `/var/lib/x360-receiver/` an, nur bei eingeschalteter Option „Beim Herunterfahren ausschalten“, root-eigen (0644/0755), und löscht beides beim Ausschalten der Option und beim Entfernen. Keine freien Shell-Aufrufe, keine Nutzereingabe in Befehlen.
- Decky-Dateien (`plugin.json`, `package.json`, `main.py`, `src/`) sind mit der offiziellen `decky-plugin-template` abgeglichen und das Frontend baut, das Plugin läuft inzwischen auf dem Gerät des Nutzers, der systemd-Dienst für das Herunterfahren funktioniert laut Nutzer (Stand: siehe `PLAN.md`). Das Root-Flag heißt `root` (Decky prüft genau diese Zeichenfolge; `_root` ist der ausgeschaltete Platzhalter der Vorlage). `dist/index.js` ist Build-Ausgabe und wird mit `npm run build` neu erzeugt.
- Sprache der Doku: Deutsch. Code-Bezeichner: Englisch.
