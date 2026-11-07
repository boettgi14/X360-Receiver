# X360 Receiver

Decky Loader plugin for the **Xbox 360 Wireless Gaming Receiver** on Bazzite and SteamOS (Gaming Mode). It shows the battery level of the connected controllers, controls their LEDs, finds a controller by vibration and turns controllers off, including on standby, on shutdown and on reboot. Several receivers are supported. The UI is available in **English and German** and follows the Steam language.

Tested on Bazzite (Deck variant) with one receiver (`045E:0719`) and regular gamepads with 2 AA NiMH batteries. What was checked on a device and what is still unverified is listed in [`docs/DESIGN.md`](docs/DESIGN.md#7-verification-status).

## Features

| Area | What the plugin does |
|------|----------------------|
| **General** (all receivers) | *Monitoring:* "Live USB monitoring" (off by default), "Query battery at start", "Warn when battery is low", "Send test notification". *Power:* "Turn off on standby", "Turn off on shutdown", "Turn off all controllers now". *Language:* Automatic (Steam language), English or Deutsch. *Diagnostics:* the result of the last shutdown run. |
| **Receiver** | One section per receiver; the connected controllers are expandable cards. |
| **Controller card** | The header shows the type and the battery as a bar with the level (0 to 3; the protocol knows only four levels). Inside: "Query battery now", "Turn off controller", "Find controller" (vibrates for about 3 seconds, the LED stays as it is), the LED pattern (modes 0 to 15; `xpad0` is controller 1, `xpad1` controller 2 …) and details. |
| **Messages** | The panel shows no progress or success messages, only failures in red. The only notifications are Steam toasts for a low battery (and the sample from "Send test notification"). |

### Battery

The receiver reports a controller's battery only when the controller connects. So:

- A controller that was already connected when the plugin starts is queried once at start ("Query battery at start", on by default). A query makes the controller disappear for about 3 seconds; do not query during a game.
- A controller that connects later shows its battery by itself if **"Live USB monitoring"** is on. With it off, press "Query battery now" on the card.
- A card without any query and without monitoring shows no battery level and no type or headset/chatpad details. It still appears: controllers are detected through the system (sysfs), not through the monitor.

"Live USB monitoring" follows the receivers' USB traffic (usbmon). It sees the whole bus, but the plugin discards everything that does not belong to a receiver and never stores or logs it; input packets are only counted. If you switch the controllers on before the device, the query at start already covers you and you can leave the monitor off.

The low-battery notification appears when a controller reports level 0 or 1. It assumes 0 = empty and 1 = low, which is unverified; it can be switched off.

## Languages

- The UI uses German for `de`, `de-DE` and similar and English for everything else, following `navigator.language` like Decky's own UI. **Language** (General → Language) overrides this.
- All UI text lives in `src/i18n.ts`. The English catalog defines the shape of every message and the German one must match it, so a missing German text fails `npm run typecheck`.
- The Python backend is language-neutral: it returns English technical messages plus, where a user can act on a failure, a stable code from `x360w.error_codes`, which the frontend translates. Technical details such as kernel or libusb messages stay English.
- External programs run with `LANG=C`, and the systemd unit text is English, so nothing depends on the system language.
- **Adding a language:** add an entry to `MESSAGES` in `src/i18n.ts` (the compiler lists every missing text), a branch for it in `detectLanguage` and an option in the language setting, then extend `tools/frontend_render_test.mjs`.

## How it works

The kernel driver `xpad` neither shows the battery nor offers a way to turn a controller off. The plugin uses:

1. **sysfs** (always): receivers, occupied slots, LEDs (`/sys/class/leds/xpadN/brightness`), the standby behavior (`/sys/module/xpad/parameters/auto_poweroff`).
2. **usbmon** (optional, "Live USB monitoring"): decodes connections and battery reports as they happen.
3. **Short access through libusb** (query battery, turn off): `xpad` briefly releases the slot's interface, the plugin sends `00 00 00 40` (battery request, followed by the presence request `08 00 0F C0` to learn the controller type) or `00 00 08 C0` (turn off), and `xpad` binds again.
4. **Force feedback through the controller's evdev node** (only "Find controller"): one rumble effect is played and removed again. The node is opened write-only, so no input is ever read.
5. **A systemd service** (only "Turn off on shutdown").

### Turn off on shutdown

`xpad` has no shutdown hook, and the plugin cannot do the job itself while Decky shuts it down. When the option is switched on, the plugin sets up a small systemd service:

- `/etc/systemd/system/x360-receiver-poweroff.service` (`Type=oneshot`, `RemainAfterExit=yes`, `ExecStop`)
- `/var/lib/x360-receiver/` with a copy of the program and the report `last-run.json`

On shutdown and reboot systemd runs `ExecStop`: the program finds the connected controllers and turns them off, the same way as "Turn off all controllers now". When the option is switched off and when the plugin is removed, both places are deleted again. The design document explains this and how the plugin copes with Decky's way of stopping plugins ([`docs/DESIGN.md`](docs/DESIGN.md#5-shutdown)).

## Requirements

- Bazzite or SteamOS with [Decky Loader](https://decky.xyz/) (Gaming Mode). Other languages than English and German show the English UI.
- An Xbox 360 Wireless Gaming Receiver (`045E:0291`, `045E:0719` or `045E:02A9`) and the kernel driver `xpad` (default).
- The plugin runs with root rights (`"flags": ["root"]` in `plugin.json`) because it needs libusb, sysfs and usbmon.
- `libusb-1.0` and `/usr/bin/python3` (present on Bazzite; Python is used by the systemd service).

## Installing and removing

There is no store entry. Download `X360-Receiver.zip` from the [releases](https://github.com/boettgi14/X360-Receiver/releases), or build it yourself (see below).

**Install** (developer mode once, then only the zip):
1. Put `X360-Receiver.zip` on the device (e.g. into `~/Downloads`).
2. Decky settings → "General": switch on **Developer mode**. The "Developer" tab appears.
3. There, under "Third-Party Plugins", press **Browse** next to **Install Plugin from ZIP File**, choose the zip, confirm the notice.
4. The plugin appears in the Decky menu as "X360 Receiver".

**Update:** install the newer zip the same way. Decky removes the old version first; the saved settings stay.

**Remove:** In the Decky menu choose **Uninstall** for "X360 Receiver". The plugin resets `auto_poweroff` to its original value and removes the systemd service together with `/var/lib/x360-receiver/`. It does **not** delete its settings, data and log folders (`~/homebrew/settings`, `~/homebrew/data` and `~/homebrew/logs`, each with a folder `X360 Receiver`); remove them by hand if you want to:

```bash
sudo rm -rf "$HOME/homebrew/"{settings,data,logs}"/X360 Receiver"
```

Not undone are the loaded kernel module `usbmon` (until reboot) and a set LED mode (until the controller connects the next time). If the plugin folder was deleted behind Decky's back, the service stays behind:

```bash
sudo systemctl disable --now x360-receiver-poweroff.service
sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver
sudo systemctl daemon-reload
```

## Building

The backend is plain Python and needs no build. Only the frontend is built (TypeScript/React with the Decky toolchain). Requirements: Node.js 18 or newer with npm, and Python 3.

```bash
npm ci                                  # dependencies according to package-lock.json
npm run typecheck                       # TypeScript; also checks that the German texts match the English ones
npm run build                           # creates dist/index.js (Rollup)
python3 -I tools/make_zip.py X360-Receiver.zip
```

`make_zip.py` packs `plugin.json`, `package.json`, `main.py`, `dist/index.js` and `py_modules/` into the form Decky expects (`X360 Receiver/…`); the frontend's source, tests and captures are not included. `npm run watch` rebuilds on changes. `pnpm` works as well, but the lock file belongs to npm.

`@rollup/rollup-linux-x64-musl` is deliberately listed under `optionalDependencies` (as in Decky's template, for musl environments); on glibc systems it is skipped.

## Tests

```bash
python3 -I -m unittest discover -s tests          # backend, without hardware and without root
```

The tests run entirely against stand-ins: the parser and state machine, replays of four real usbmon captures (`tests/fixtures/`), the short access with a dummy backend, `main.py` with a reconstructed `decky` module, and the systemd service in temp folders with a reconstructed `systemctl` (never under `/etc` or `/var`). They assume POSIX paths; on Windows run them on Linux or in WSL. The two zip tests are skipped while `dist/index.js` is missing. `docs/DESIGN.md` lists what each test module covers.

The render test checks the built frontend with stand-in Decky components in jsdom, once in English and once in German, including the language detection. It is no test against Steam's real UI:

```bash
mkdir /tmp/render && cd /tmp/render && npm install react react-dom jsdom
node <path-to-repo>/tools/frontend_render_test.mjs <path-to-repo>/dist/index.js
```

## Repository layout

| Path | Content |
|------|---------|
| `plugin.json`, `package.json`, `rollup.config.js`, `tsconfig.json`, `main.py`, `src/index.tsx` | The Decky plugin: metadata, build configuration, backend entry, UI |
| `src/i18n.ts` | All UI texts in English and German, language detection, translation of error codes and diagnostics |
| `py_modules/x360w/` | Backend library: `protocol` (packets), `usbmon` and `usbmon_reader` (parser, reader), `monitor` (state machine), `service` (monitoring service), `discovery` (receivers in sysfs), `view` (controllers per receiver), `takeover` and `actions` (short access, battery query, turn off), `battery_cache`, `shutdown` (turn off several controllers), `controls` (LED, `auto_poweroff`), `rumble`, `low_battery`, `resume`, `loop_guard`, `poweroff_unit` and `poweroff_cli` (shutdown service), `cleanup`, `safe_exec` (fixed program calls), `error_codes` |
| `tests/` | Unit tests and the captures in `tests/fixtures/` |
| `tools/make_zip.py` | Builds the zip for Decky |
| `tools/frontend_render_test.mjs` | Render test of the built frontend |
| `tools/discover.sh` | Read-only system check (receiver, `xpad`, LEDs, usbmon) |
| `tools/capture_usbmon.py` | Records and decodes a receiver's packets (root; only the bus and device from `discover.sh`) |
| `tools/probe_takeover.py` | Sends a presence request, battery request or turn-off to one slot (root; not during a game) |
| `docs/DESIGN.md` | Design, access paths, architecture, shutdown handling, security, verification status, tests |
| `docs/PROTOCOL.md` | The receiver's protocol, every statement with a confidence level |
| `CLAUDE.md` | Project rules for working with Claude Code |

## Security and privacy

- The backend runs as root but writes only to the named sysfs paths. Its external actions are `modprobe usbmon`; `systemctl daemon-reload | enable --now | disable --now` for its one own service; the USB commands of the short access to known receivers and slots 0 to 3 (battery request, presence request, turn off); and, for "Find controller", one force-feedback effect to the `/dev/input/eventN` node of a known controller (write-only, at most 5 seconds). All use fixed arguments without user input; programs run with an absolute path and a sanitized environment.
- The service runs as root. Its folder and files belong to root and are writable only by root (0644/0755, independent of the `umask`); symlinks at these locations are refused.
- usbmon is off by default and loaded only when "Live USB monitoring" is switched on. Packets of other devices are discarded immediately and never stored or logged.
- There is no network access.

## Known limits

- Only four battery levels, no percentages.
- A battery query or turning off makes the controller disappear for about 3 seconds.
- Chatpad and headset are not supported.
- Unverified: the meaning of the battery levels (so the low-battery notification at a real low level), other battery types and charging, several receivers, other controller types, the monitor after a resume from suspend. See [`docs/DESIGN.md`](docs/DESIGN.md#7-verification-status).
- German texts beyond the original ones were not reviewed by a native speaker.

## License

[GNU General Public License, version 2 or (at your option) any later version](LICENSE) (`GPL-2.0-or-later`).

Why this license: The protocol knowledge and the table of LED modes come from the Linux kernel driver `xpad` (`drivers/input/joystick/xpad.c`, `GPL-2.0-or-later`). `package.json` carries the same identifier. The license applies to the source code in this repo; the dependencies (React, Decky libraries and others) keep their own licenses. This is not legal advice.

"Xbox" and "Xbox 360" are trademarks of Microsoft Corporation. X360 Receiver is an independent project and has no connection to Microsoft; the names are only used to name the supported hardware.
