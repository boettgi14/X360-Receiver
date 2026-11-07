# X360 Receiver

Decky Loader plugin for the **Xbox 360 Wireless Gaming Receiver** on Bazzite and SteamOS (Gaming Mode). It shows the battery level of all connected controllers, controls their LEDs and turns them off, including on standby and on shutdown. Several receivers are supported. The UI is available in **English and German** and follows the Steam language (see [Languages](#languages)).

> **Status:** The plugin runs on a Bazzite device with one receiver (USB ID `045E:0719`) and one gamepad (2 AA batteries, no charging cable). Battery query, LED assignment, turning off and the layout have been checked there. "Turn off on shutdown" (through a systemd service, see [note](#turn-off-on-shutdown)) works there too. What is confirmed and what only comes from source code or unit tests is listed in [`PLAN.md`](PLAN.md) and [`docs/PROTOCOL.md`](docs/PROTOCOL.md). The English and German UI works on the device according to the user (2026-11-07). The rumble test ("Find controller"), the low-battery notification and the wake-up handling were added afterwards and are only unit-tested; they have not been tried on a device yet.

## Features

UI texts are quoted in English below; the German UI shows the translations from `src/i18n.ts`.

| Area | What the plugin does |
|------|----------------------|
| **General** (applies to all receivers) | *Monitoring:* "Live USB monitoring" (USB monitor, off by default), "Query battery at start", "Warn when battery is low". *Power:* "Turn off on standby" (turns the controllers off when the device goes to sleep), "Turn off on shutdown", "Turn off all controllers now". *Language:* Automatic (Steam language), English or Deutsch. *Diagnostics:* result of the last run on shutdown. |
| **Receiver** | One section per receiver, with the connected controllers as expandable cards. |
| **Controller card** | Battery as a bar with a level (0 to 3, the protocol only knows four levels), "Query battery now", "Turn off controller", "Find controller" (vibrates the controller for about 3 seconds, the LED stays as it is), LED pattern (modes 0 to 15; `xpad0` is controller 1, `xpad1` controller 2 …), details. |
| **Battery after start** | The receiver reports the battery only when a controller connects. That is why the plugin queries all already connected controllers once right after it starts and remembers the value (switchable with "Query battery at start"). |
| **Low-battery notification** | A toast appears when a controller reports battery level 0 or 1 of 3, also while the plugin panel is closed. It assumes 0 = empty and 1 = low (unverified) and appears when a controller connects or is queried, because that is when the receiver reports the level. |

### What "Live USB monitoring" brings

The switch only decides whether the plugin follows the receivers' USB traffic live (usbmon). With it **off**, which is the default, the plugin still lists the connected controllers (it finds them through the system, in sysfs) and shows a battery level whenever one is known: from the query at plugin start ("Query battery at start") or from "Query battery now". With it **on**, connections and battery reports are also picked up the moment they happen, for example when a controller connects. To see no battery levels at all, switch off "Query battery at start" as well and do not query by hand.

In practice the monitor matters for one thing: **a controller that connects after the plugin has started shows its battery level by itself** (confirmed on the device), without the 3-second drop-out of a query. It also shows live details (headset, chatpad, the last LED command). If you always switch the controllers on first and then the device, it brings little; the query at start covers that. The controller type is also learned by every battery query (the query asks the receiver for the link report afterwards), so it no longer needs the monitor.

## Languages

The plugin UI is available in **English** and **German**. It follows the language of the Steam client, so it behaves the same on SteamOS and on Bazzite, and the language of the operating system does not matter:

- The frontend reads `navigator.language` (and `navigator.languages`) and uses German for `de`, `de-DE` and similar; every other language falls back to English. Decky Loader detects its own UI language the same way (`i18next` with `lng: navigator.language`, read in the Decky source on 2026-11-06). The user confirmed on 2026-11-07 that the UI follows the Steam language in German and in English.
- The setting **Language** (General → Language) overrides the detection: "Automatic (Steam language)", "English" or "Deutsch". The choice is stored in the plugin's settings.
- All UI text lives in `src/i18n.ts`. The English catalog defines the shape of every message and the German catalog must match it, so a missing or mistyped German text fails `npm run typecheck`.
- The Python backend is language-neutral: it never produces text in the user's language. Failed actions return an English technical message plus, where a user can act on the failure, a stable code from `x360w.error_codes` (and the diagnostics verdict as a code with parameters). The frontend translates those. Technical details such as kernel or libusb messages are shown as they are (English).
- External programs run with `LANG=C` and `LC_ALL=C` (`safe_exec.py`), `tools/discover.sh` does the same, and the systemd unit text is English, so nothing depends on the system language.
- **Adding a language:** add an entry to `MESSAGES` in `src/i18n.ts` (the compiler lists every missing text) and a branch for it in `detectLanguage`, then extend `tools/frontend_render_test.mjs`.

## How it works

The kernel driver `xpad` does not show the battery and offers no way to turn a controller off. The plugin uses five ways (details and confidence levels in `PLAN.md`):

1. **sysfs** (always): detect receivers, occupied slots, LEDs under `/sys/class/leds/xpadN/brightness`, standby behavior through `/sys/module/xpad/parameters/auto_poweroff`.
2. **USB monitor `usbmon`** (optional, switch "Live USB monitoring"): reads the receiver's packets and decodes connection and battery level. It sees the whole bus; the plugin filters immediately by bus and device, discards everything else and only counts input packets.
3. **Short access through libusb** (query battery, turn off): `xpad` briefly releases the slot's interface, the plugin sends `00 00 00 40` (battery request) or `00 00 08 C0` (turn off), then `xpad` binds again. The affected controller disappears for about 3 seconds.
4. **systemd service** (only for "Turn off on shutdown").
5. **Force feedback through the controller's evdev node** (only for "Find controller"): one short rumble effect is uploaded, played and removed again. The node is opened write-only, so no input is ever read, and no USB takeover is involved.

### Turn off on shutdown

`xpad` has no hook for shutdown, and Decky does not reliably stop the plugin on shutdown: on the device it received the stop signal, never called `_unload` and was killed with SIGKILL after 5 seconds (two foreign plugins as well, see `PLAN.md`, risk 18). That is why the plugin sets up a small systemd service when the option is switched on:

- `/etc/systemd/system/x360-receiver-poweroff.service` (`Type=oneshot`, `RemainAfterExit=yes`, `ExecStop`)
- `/var/lib/x360-receiver/` with a copy of the program (`poweroff.py`, `x360w/`) and the report `last-run.json`

On shutdown and reboot systemd runs `ExecStop`: the program finds the connected controllers the same way as the "Turn off all controllers now" button and turns them off. When the option is switched off and when the plugin is removed, both places are deleted again. On the test device the controllers turn off on shutdown this way; reboot and several controllers connected at once have not been tested specifically.

## Requirements

- Bazzite or SteamOS with [Decky Loader](https://decky.xyz/) (Gaming Mode), with the Steam UI in English or German (other languages show the English UI)
- Xbox 360 Wireless Gaming Receiver (`045E:0291`, `045E:0719` or `045E:02A9`) and the kernel driver `xpad` (default)
- The plugin runs with root rights (`"flags": ["root"]` in `plugin.json`) because it needs libusb, sysfs and usbmon
- `libusb-1.0` and `/usr/bin/python3` on the device (only for the systemd service; present on Bazzite, the service runs there)

## Installing and removing

The plugin is private: there is no store entry, you build the zip yourself (see below).

**Install** (developer mode once, then only the zip):
1. Put `X360-Receiver.zip` on the device (e.g. into `~/Downloads`).
2. Decky settings → "General": switch on **Developer mode**. The "Developer" tab appears.
3. There, under "Third-Party Plugins", press **Browse** next to **Install Plugin from ZIP File**, choose the zip, confirm the notice.
4. The plugin appears in the Decky menu as "X360 Receiver".

**Remove:** In the Decky menu choose **Uninstall** for "X360 Receiver". The plugin resets `auto_poweroff` to its original value, and removes the systemd service together with `/var/lib/x360-receiver/`. It does **not** delete its settings, data and log folders (`~/homebrew/settings`, `~/homebrew/data` and `~/homebrew/logs`, each with a folder `X360 Receiver`); they stay behind and can be removed by hand: `sudo rm -rf "$HOME/homebrew/"{settings,data,logs}"/X360 Receiver"`. Not undone are the loaded kernel module `usbmon` (until reboot) and a set LED mode (until the next connect). If the plugin folder was deleted behind Decky's back, the service stays behind:

```bash
sudo systemctl disable --now x360-receiver-poweroff.service
sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver
sudo systemctl daemon-reload
```

**Update:** install the same zip again. Decky first removes the old version; saved settings stay, so the options keep their values.

## Building

The backend is plain Python and needs no build. Only the frontend is built (TypeScript/React with the Decky toolchain).

**Requirements:** Node.js 18 or newer with npm, Python 3.

```bash
npm ci                                  # dependencies according to package-lock.json
npm run typecheck                       # check TypeScript (also checks that the German texts match the English ones)
npm run build                           # creates dist/index.js (Rollup)
python3 -I tools/make_zip.py X360-Receiver.zip
```

`make_zip.py` packs `plugin.json`, `package.json`, `main.py`, `dist/index.js` and `py_modules/` into the form Decky expects (`X360 Receiver/…`). The frontend's source code, tests and captures are not included. `npm run watch` rebuilds on changes. `pnpm` works as well (Decky's template uses it), but the lock file that comes with the repo belongs to npm.

Note: `@rollup/rollup-linux-x64-musl` is deliberately listed under `optionalDependencies` (the Decky developers' template does this for musl environments); on glibc systems it is skipped.

## Tests

```bash
python3 -I -m unittest discover -s tests          # backend, without hardware and without root
```

The two zip tests (`test_packaging.py`) are skipped as long as `dist/index.js` is missing; after `npm run build` they run too.

The tests run entirely with stand-ins: parser and state machine, replay of four real usbmon captures (`tests/fixtures/`), the short access with a dummy backend, `main.py` with a reconstructed `decky` module. The systemd service is only tested in temp folders with a reconstructed `systemctl`, never under `/etc` or `/var`. `tests/test_i18n_contract.py` checks that the backend's error codes, diagnostics codes, LED modes and controller types all have a translation in `src/i18n.ts`.

The tests assume POSIX paths (for example `/var/lib/...` in the service text); on Windows many of them fail for that reason, so run them on Linux or in WSL.

Render test for the built frontend (stand-in Decky components in jsdom; no test against Steam's real UI). It runs the whole check twice, once with the UI in English and once in German, and also checks the language detection:

```bash
mkdir /tmp/render && cd /tmp/render && npm install react react-dom jsdom
node <path-to-repo>/tools/frontend_render_test.mjs <path-to-repo>/dist/index.js
```

## Repository layout

| Path | Content |
|------|---------|
| `plugin.json`, `package.json`, `rollup.config.js`, `tsconfig.json`, `main.py`, `src/index.tsx` | Decky plugin (metadata, backend entry, UI), compared with the official template |
| `src/i18n.ts` | All UI texts in English and German, language detection, translation of error codes and diagnostics |
| `py_modules/x360w/` | Backend library: protocol (`protocol`), usbmon parser and reader, state machine (`monitor`), monitoring service (`service`), LED and `auto_poweroff` (`controls`), receiver discovery (`discovery`), view per receiver (`view`), short access and actions (`takeover`, `actions`), battery cache (`battery_cache`), turning off several controllers (`shutdown`), rumble test (`rumble`), low-battery watcher (`low_battery`), resume-from-suspend detection (`resume`), systemd service (`poweroff_unit`, `poweroff_cli`), cleanup on removal (`cleanup`), fixed program calls (`safe_exec`), error codes for the frontend (`error_codes`) |
| `tests/` | Unit tests and captures (`tests/fixtures/`) |
| `tools/make_zip.py` | builds the zip for Decky |
| `tools/frontend_render_test.mjs` | render test of the built frontend (both languages) |
| `tools/decky_stop_sim.py` | simulates how Decky stops a plugin (SIGTERM, 5 s, SIGKILL) around `main.py`; shows the exit watchdog at work (Linux) |
| `tools/discover.sh` | read-only system check (receiver, `xpad`, LEDs, usbmon) |
| `tools/capture_usbmon.py` | records and decodes a receiver's packets (root, only bus and device from `discover.sh`) |
| `tools/probe_takeover.py` | sends a battery request or turn-off to one slot (root; not during a game) |
| `docs/PROTOCOL.md` | protocol of the receiver, each statement with a confidence level |
| `PLAN.md` | plan, access paths, measurements, open risks, checks after installation |
| `CLAUDE.md` | project rules for working with Claude Code |

## Security and privacy

- The backend runs as root but writes only to the named sysfs paths and knows exactly these external calls: `modprobe usbmon`, `systemctl daemon-reload | enable --now | disable --now` for its one own service (all with an absolute path and a sanitized environment, without user input) and the USB commands of the short access to known receivers and slots 0 to 3 (battery request, presence request, turn off). For "Find controller" it additionally writes one force-feedback effect to the `/dev/input/eventN` node that sysfs shows under a known receiver's slot interface (write-only, fixed strength, at most 3 seconds).
- The service runs as root. Its folder and files belong to root and are writable only by root (0644/0755, independent of the `umask`); symlinks at these locations are rejected.
- usbmon is off by default and is only loaded with the "Live USB monitoring" switch. Captures of other devices are discarded immediately and never stored or logged; input packets are only counted.
- There is no network access.

## Known limits

- Only 4 battery levels, no percentages (that is what the protocol reports).
- Battery query and turning off make the affected controller disappear for about 3 seconds. How Steam reacts is not specifically checked; do not query during a game.
- Several receivers: the assignment LED ↔ controller is then not guaranteed (the receivers share the LED numbers). There was only one receiver on the test device.
- Chatpad and headset are not supported.
- "Turn off on shutdown" has only been tested with one receiver and one controller, and only on shutdown (not specifically on reboot).
- Focus navigation with the controller in the plugin UI has not been specifically tested.
- Languages: only English and German. Most German texts are the plugin's original ones; those added later (error messages, controller type names, the newer settings) were written by the assistant and not reviewed by a native speaker. Technical error details from the backend are shown untranslated (English).
- "Find controller" works on the device according to the user (the controller vibrates). The low-battery notification and the wake-up handling are only unit-tested and have not been tried there; "Send test notification" (General → Monitoring) shows a sample notice so the display can be checked. The notification depends on the unverified assumption that level 0 means empty and 1 means low.
- Without a battery query and without live USB monitoring a card shows no battery level and no controller type or headset/chatpad details: the receiver only reports them on connecting and on a query. The LED pattern shows the mode xpad sets on connecting (`(N mod 4) + 2`) until you change it.
- Everything that needs other hardware has not been tested: a battery that drains, other battery types or charging, a second receiver, other controller types (guitar, wheel, drums), headset and chatpad.

## License

[GNU General Public License, version 2 or (at your option) any later version](LICENSE) (`GPL-2.0-or-later`).

Why this license: The protocol knowledge and the table of LED modes come from the Linux kernel driver `xpad` (`drivers/input/joystick/xpad.c`, `GPL-2.0-or-later`). `package.json` carries the same identifier. The license applies to the source code in this repo; the dependencies (React, Decky libraries and others) keep their own licenses. This is not legal advice.

"Xbox" and "Xbox 360" are trademarks of Microsoft Corporation. X360 Receiver is an independent project and has no connection to Microsoft; the names are only used to name the supported hardware.
