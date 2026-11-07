# Implementation plan: Decky plugin for the Xbox 360 Wireless Receiver

Status: 2026-11-07. Target system: Bazzite (Deck variant, Gaming Mode) with an Xbox 360 Wireless Receiver. The hardware results below date from 2026-11-04/05; the English/German UI was added on 2026-11-06; on 2026-11-07 the user confirmed several device checks and made decisions on the remaining scope (section 16), and the rumble test, low-battery notification, switch for the start query, wake-up handling and language choice were added.

This plan strictly separates **confirmed on hardware**, **only backed by sources or unit tests**, **assumption** and **open**. The protocol is in `docs/PROTOCOL.md`.

## 0. Status in brief

| Area | Status |
|------|--------|
| usbmon as a read path | **confirmed on hardware**: debugfs readable as root, full 29-byte packets, filter by bus/device works |
| Connection, link report, state packet, input packets | **confirmed on hardware** (one gamepad, 38 s capture) |
| LED control through `/sys/class/leds/xpadN/brightness` | **confirmed**: you reported that the LEDs react. Which mode was tested is not recorded; the assignment LED ↔ slot is unchecked (only one controller) |
| Battery reported periodically or only on connecting | **confirmed on hardware: only on connecting.** No further state packet in about 380 s idle, after LED commands, after A/B/Guide and after re-binding `xpad` (there only a link report with a battery level, freshness unclear). The only report in the middle of a session: on turning off (power state 0). Unchecked: battery request `00 00 00 40` with a draining battery, long operation, charging |
| Turning off by command | **confirmed on hardware** (sent by `xpad`, 5 s Guide; controller disconnected afterwards). Sending it ourselves: confirmed on hardware (short access, button in the plugin, service on shutdown) |
| Battery request by command (`00 00 00 40`) | **confirmed on hardware**: the answer is a state packet after 27 ms. With the controller off **no** answer comes (in the first runs this was assumed from the order of the runs; the user states on 2026-11-07 that the query does not work with the controller off), so probably no cache. Whether the value changes with a draining battery is unchecked and cannot be tested with the available hardware (section 16) |
| Short access to a slot (libusb) | **confirmed on hardware** with `tools/probe_takeover.py`: presence request, battery request and turning off, `xpad` binds again afterwards. Wired into the plugin (buttons) and since confirmed by the user to work as a plugin (see next row) |
| Backend (monitor, service, control) | **263 tests**, including replay of four real captures; Linux run (WSL) of 2026-11-07: all pass (the start-reconciliation race of risk 23 is fixed). Runs as a Decky plugin on the user's device: battery query (also right after start), LED assignment, buttons, the brief loss of a controller and both UI languages confirmed by the user; the systemd service turns several controllers off on shutdown **and on reboot** according to the user (risk 18) |
| Frontend | builds with the official toolchain, loaded in Decky and seen by the user (layout, cards, bars); render test with stand-in Decky components in both languages; focus navigation with the controller not specifically checked |
| UI languages (English/German) | **confirmed by the user on 2026-11-07: works** with the Steam language set to German and to English. Follows the Steam language through `navigator.language` (the way Decky's own UI does), with a manual choice in the settings as an override. Type check, render test in both languages and a contract test back it up |
| Added 2026-11-07: rumble test ("Find controller"), low-battery notification, switch for the battery query at start, wake-up detection for the monitor, language choice, test button for the notification | implemented and unit-tested (263 backend tests, render test with stand-ins). **Tried on the device (user, after the v1.2.0 release):** rumble works (the first version also changed the LED, which was removed), the switch for the start query and the language choice work, the battery appears by itself after a controller connects with the monitor on. **Not tried on a device:** the notification (now with a test button) and the wake-up handling (risks 8, 25) |
| Secure Boot / lockdown | off / `none`: a self-built `xpad` module is possible on the device in principle (kernel headers unchecked) |

## 1. Requirements

1. Support as many controller types as possible that the receiver connects (gamepad, wheel, arcade stick, guitar, drums, dance pad and others).
2. Several receivers at the same time on the system.
3. Show all readable status information.
4. Control controllers, above all power management.
5. Usable on an English and on a German SteamOS or Bazzite: the UI follows the Steam language (English and German), nothing depends on the system language.

## 2. The central obstacle

The kernel driver `xpad` owns the four controller interfaces on every receiver (proven: `XPAD_XBOX360_VENDOR_PROTOCOL(vend, 129)`). It only evaluates connection and input packets. It discards the state packets with the battery level, and it offers no switch to turn a controller off on demand. A userspace program may not use an occupied USB interface at the same time without detaching `xpad`, and then the controller input would be lost.

Four possible access paths follow from this:

| Path | Read | Send | Intervention | Assessment |
|------|------|------|--------------|------------|
| **A. usbmon (passive)** | Yes, everything that goes over the bus | No | None, `xpad` keeps running normally | Feasible today. Sees the whole USB bus, hence a privacy topic (see 7) |
| **B. Kernel patch in `xpad`** | Yes, cleanly as `power_supply` | Yes, e.g. turning off through sysfs | New kernel or module needed | Cleanest solution. On immutable Bazzite only usable once the patch is in the kernel in use |
| **C. Userspace takeover** | Yes | Yes | Detach `xpad`, own libusb logic, virtual controllers through uinput | Powerful but risky: Steam Input, rumble, suspend and latency have to be rebuilt |
| **D. eBPF on `xpad` functions** | Yes, only `xpad` data | No | BPF tools needed | More privacy-friendly than A. Whether BPF tooling is practical in Decky's Python is open |

### Recommendation

Three tracks, with automatic detection of the capabilities at run time:

- **Track A delivers v1** (read only + what kernel interfaces already provide).
- **Track B runs in parallel as an upstream patch.** As soon as `/sys/class/power_supply` offers a controller battery and turning off, the plugin prefers that interface and no longer needs usbmon.
- **Track C only if A and B are not enough**, as a switchable expert mode. Decision after phase 1.
- **Decision of 2026-11-07:** tracks B and C are dropped (phases 3 and 5): the short access of track A is enough because Steam copes well with the controller's brief loss.

Tailwind for B: A patch series "xpad: Overhaul device data for wireless devices" (v7 of August 2026) is already running on the kernel list (linux-input) in 2026. Whether it was accepted is not checked. It shows that changes to the wireless part of `xpad` are actively reviewed.

## 3. Features and feasibility

Levels: **now** = with Linux built-ins, **A** = needs usbmon, **B** = needs a kernel patch or takeover, **open** = unclear source situation.

### Status information

| Information | Source | Level |
|-------------|--------|-------|
| Receiver: USB IDs, manufacturer/product string, serial number, firmware version (`bcdDevice`), bus/port, original or clone (PID hint) | sysfs | now |
| Which interface is bound to which driver | sysfs | now |
| Slot occupied (controller connected) | input devices in sysfs whose parent is interface 0/2/4/6 | now |
| Connected/disconnected in real time, headset attached | connection packet | A |
| **Battery level (4 levels), battery type, power state** | state packet | A |
| Chatpad and headset attached, rumble level | state packet | A |
| Controller type (subtype), device ID, protocol version, vendor | link report (only on connecting) | A, with a restriction (8, problem 3) |
| Capabilities (motors, buttons) | capabilities packet (has to be requested) | B |
| Signal quality, radio channel | no source found | open |
| Battery in exact percent | the protocol does not provide it as things stand (only 4 levels) | not available |

### Control

| Function | Path | Level |
|----------|------|-------|
| Player LED and blink pattern (modes 0–15) | `/sys/class/leds/xpadN/brightness` | now, **confirmed** (slot assignment: problem 2; the LED only exists while a controller is connected) |
| Rumble test ("find controller") | force feedback on the input device (`x360w.rumble`: one effect of 3 s through the controller's evdev node, write-only; no USB takeover, the controller stays connected, the LED is left alone) | now, **works on the device (user report after the v1.2.0 release)**; the first version also blinked the LED, which the user did not want and which was removed |
| **Option "Turn off on standby"** | `/sys/module/xpad/parameters/auto_poweroff` (writable). According to `xpad.c`, `xpad_suspend` uses it to turn off all connected controllers; kernel default is on. Global parameter, not per controller. The plugin saves the choice and sets it again on start (the parameter is reset after a reboot) | now (source, not checked on the device) |
| **Option "Turn off on shutdown"** | `xpad` has no shutdown hook, and Decky does not reliably stop the plugin on shutdown (observed on the device, see risk 18). So when the option is switched on, the plugin sets up a small **systemd service** (`x360-receiver-poweroff.service`, `Type=oneshot`, `RemainAfterExit`, `ExecStop`) that, independent of Decky, runs the program `/var/lib/x360-receiver/poweroff.py` on shutdown and reboot: find the targets like the button does (sysfs and LEDs, without usbmon) and send `00 00 08 C0` with the same command sequence (proven on the device, deadline 8 s, `TimeoutStopSec=12`). When the option is switched off and when the plugin is removed, service and program are deleted. The result of the last run is under "Diagnostics" | now (**the earlier way through the plugin itself failed three times on the device; the service works according to the user**, risk 18) |
| Note: holding the Guide button for 5 s turns the controller off | built into `xpad` | now |
| **Turn a controller off on a button press** (**confirmed through the short access**) | OUT command `00 00 08 C0…`. Confirmed with `xpad` on a 5 s Guide hold. Sending it ourselves through the short access, confirmed on hardware; track B not needed | now (plugin button) |
| Request the battery status actively | OUT command `00 00 00 40…` through the short access, confirmed on hardware. Costs: the slot disappears for about 3 s | now (plugin button). **Automatically once after the plugin starts** for all already connected controllers (the receiver otherwise reports the battery only on connecting); the result is remembered in the backend (`battery_cache.py`) and shown even without the monitor. Source "query", age like monitor values; the newer value wins (monitor or query) |
| Other power states (1–3) | unexplored | open |
| Sync/pairing, slot assignment | no host command found | open |
| Chatpad and headset | chatpad through the controller endpoint, headset audio on its own interfaces not bound by `xpad` | later (v2) |

Turning off on a button press is the hardest requirement because of the access problem. With track A alone it is **not** achievable.

## 4. Several receivers

- Every receiver is its own USB device. The plugin enumerates all devices with the known IDs (045E:0291, 045E:0719, 045E:02A9) and forms four slots per receiver.
- Data model: `Receiver (usb_path, bus, devnum, ids, firmware) → slot 0..3 (state, subtype, battery, headset, chatpad, evdev path, LED path)`.
- usbmon filters by `(bus, device address)`. Several receivers on the same bus are told apart by the device address.
- Hot-plug: changes through udev events or polling `/sys/bus/usb/devices` every few seconds. A newly plugged-in device gets a new device address.
- The plan assumes any number of receivers. Practical upper limits (Steam, kernel) are not checked.

## 5. Architecture

```
Decky frontend (React, @decky/ui)        Decky backend (Python, root)
 QAM panel: General, receivers,  <----->  Plugin class (main.py)
  expandable controllers                  ├─ View       (receiver → controllers, LED assignment)
 i18n.ts: English/German texts            ├─ Discovery  (sysfs, hot-plug)
 Toasts on low battery                    ├─ Monitor    (usbmon reader, filter by device)   [track A]
 Settings                                 ├─ PowerSupply reader (sysfs)                     [track B]
                                          ├─ Controls   (LED, rumble, auto_poweroff, power off)
                                          └─ x360w.protocol (pure parser, tested)
```

- The backend runs as root (`"flags": ["root"]` in `plugin.json`. Decky checks for exactly `"root" in flags` in its source. `"_root"` from the template means "switched off": the plugin would run without root rights and libusb, sysfs and usbmon would fail. An earlier version of this plan claimed the opposite; that was wrong), because usbmon and sysfs write access require it. This has to be justified for the Decky store.
- The backend keeps a state machine per slot that merges packets (connection → link report → state updates) and marks stale data with a timestamp ("last seen 40 s ago").
- **UI** (`src/index.tsx`), from top to bottom:
  1. *General* (applies to all receivers), groups *Monitoring* ("Live USB monitoring", "Query battery at start", "Warn when battery is low"), *Power* ("Turn off on standby", "Turn off on shutdown", "Turn off all controllers now"), *Language* (Automatic / English / Deutsch) and, when there is something to show, *Diagnostics*.
  2. One section "Receiver N" per receiver with a header line (name, USB path, occupied slots) and the group *Controllers*.
  3. Every connected controller is an expandable card (collapsed: name, type, **battery bar with "Level n/3"**). Expanded, with a heading and a line on the left for each group: *Battery* (age of the report, "Query battery now"; bar and level only appear in the card's header row), *Power* ("Turn off controller"), *Identify* ("Find controller": rumble for about 3 seconds, nothing else), *LED* (only if clearly assigned), *Details*.
  4. LEDs that cannot be assigned to a single controller appear as a group at the receiver.
  The battery bar has three segments for levels 1–3 (0 = empty, red); the mapping to percent is unproven and is not shown.
  The options standby and shutdown are under *General*, not per controller: `auto_poweroff` is a global kernel parameter, and both events concern the whole device.
- **Languages.** All UI text is in `src/i18n.ts`, in English and German; the UI follows the Steam language, detected through `navigator.language` (and `navigator.languages`) the way Decky Loader's own UI does it (source: Decky frontend `start.tsx`, i18next with `lng: navigator.language`, read 2026-11-06). German for `de…`, English for everything else. The English catalog defines the shape, the German one must match it (type check). The Python backend is language-neutral:
  - Failed actions return `{"ok": false, "error": <English text>}` plus, where a user can act on the failure, a `code` from `x360w.error_codes` and an optional `detail`; the frontend translates the code (`errors` in `i18n.ts`), appends the detail and falls back to the English text for an unknown code. Technical details (kernel, libusb, `systemctl` messages) stay English.
  - The diagnostics verdict is a code with parameters (`poweroff_unit.VERDICT_CODES`), its detail lines are `{key, value}` pairs (`LINE_KEYS`); the frontend writes the sentences.
  - LED mode names and controller type names are translated in the frontend by their number; the backend's English text is only the fallback (`tests/test_i18n_contract.py` checks that both agree). The receiver label stays language-neutral; an `unofficial` flag lets the frontend add the translated note.
  - External programs run with `LANG=C`/`LC_ALL=C`, `tools/discover.sh` does the same, and the systemd unit text is English; nothing depends on the system language.
  - The Language setting in the UI ("Automatic", English, Deutsch) is stored in the backend (`language` in `x360w.json`) and overrides the detected language; an unsupported or invalid stored value means automatic.
- **Which controllers are connected?** From the monitor (confirmed) and from the input device `xpad` creates under `<interface>/input/` (derived from the source code only). That way controllers are visible even with the monitor off, then with the battery level of the last query (at plugin start or by hand) if there is one. The user pointed out on 2026-11-07 that controllers and battery levels are shown with the monitor off; that is by design, and the switch was renamed from "Read battery status" to "Live USB monitoring" with an explanatory hint, because the old name suggested it controlled the battery display. If there are more LEDs than detected controllers (the LED exists only while a controller is connected, confirmed), it says "n more controllers connected" and the slots are unknown.
- **LED assignment:** The LED hangs on the receiver (`led_classdev_register(&xpad->udev->dev …)`), not on the slot; it is assigned to the receiver through the resolved sysfs path. Within a receiver, the rule observed on the device applies: "xpad0 = controller 1, xpad1 = controller 2 …": LEDs sorted by number, controllers sorted by slot, pairwise, provided the counts match (otherwise the LEDs appear as a group at the receiver). With **one** receiver this stays in step, because xpad hands out the LED number and the receiver the slot, each as "smallest free". With several receivers they share the LED numbers; the order can differ (example: receiver 2 takes xpad0, then a controller connects to slot 1 of receiver 1 and gets xpad1 instead of xpad0). The assignment is then not guaranteed.
- The frontend polls the state every 2 s through a `callable`.
- **Low-battery notice.** The backend's refresh loop (every 5 s) feeds `x360w.low_battery.LowBatteryWatcher`; a controller whose level becomes 0 or 1 is queued once. The frontend pulls the queue (`take_low_battery_notices`, every 10 s, from the moment the plugin loads, also while the panel is closed) and shows a toast in the user's language. Pulling instead of pushing means nothing is lost if the UI is not loaded yet when a notice arises. It assumes level 0 = empty and 1 = low (risk 25); the receiver only reports the level on connecting or on a query, so a notice appears at those moments. Switchable in the UI.
- **Wake-up handling.** `x360w.resume.ResumeDetector` notices a resume from suspend (the wall clock advanced more than the monotonic clock) and the refresh loop then restarts the usbmon readers (`MonitorService.restart_readers`). An assumption, not verified on a device (risk 8).
- **Rumble.** `x360w.rumble` uploads one short rumble effect to the slot's evdev node (`discovery.input_event_nodes` finds it under `<interface>/input/inputN/eventM`) with the standard force-feedback ioctls, plays it and removes it again. The node is opened write-only; nothing is ever read from it.
- **Start query switch.** "Query battery at start" (setting `startup_battery_query`, default on) decides whether already connected controllers are queried once when the plugin loads (risk 21).
- Dependencies: none beyond the Python standard library in track A. The parser `py_modules/x360w/` is pure and has already been tested.

## 6. Phases with acceptance criteria

**Phase 0: reality check on real hardware. Completed.**
- Done: system data, usbmon, full packets, connection sequence (three times), LED path and bytes, idle, LED commands, buttons, re-binding `xpad`, turning off (`docs/PROTOCOL.md`, sections 6 to 8).
- **Result: The receiver reports the battery only on connecting.** Neither time, LED commands, buttons nor re-binding `xpad` trigger a fresh state packet. Re-binding only delivers a link report with a battery level; whether the value is fresh is open. If the plugin starts after the controller, it first shows "not reported yet".
- **Result: Turning off works by the command `00 00 08 C0`** (sent by `xpad`, then a state packet with power state 0 and a disconnect).
- Ladder for the battery, from harmless to costly:
  1. Show the last value with its age (built: `state_age_s`, plus `state_source` "report" or "link"; the UI marks link values).
  2. Use the value reported on connecting or waking (free).
  3. **Short access to the slot** (`x360w/takeover.py`, `x360w/actions.py`, libusb): `xpad` releases the interface for seconds, we send `00 00 00 40`, read the answer, `xpad` binds again. **Confirmed on hardware (phase 0d).** Costs: the controller of this slot disappears from the system for about 3 s. In the plugin as the button "Query battery now", deliberately without automatic repetition.
  4. Track B: battery request and `power_supply` from a patched `xpad`. Seamless and without controller drop-outs, but needs a module or kernel. The protocol for it is now known (request `00 00 00 40`, answer type 0 with header `13 xx`). Becomes important if Steam tolerates the brief loss badly.
- **Turning off by button in the plugin** needs no kernel patch: the short access sends `C0`, and because the controller is off afterwards anyway, no input is lost. Confirmed on hardware (phase 0d), with a confirmation dialog in the plugin.
- Unclear: the `F8 01/02` packets (50 in 393 s, strictly alternating) are the only running data stream when idle. Presumption: connection quality, without proof.

**Phase 0d: test of the short access. Passed** (`docs/PROTOCOL.md`, section 9). Takeover, presence request, battery request and turning off work; `xpad` binds again afterwards every time.

**Phase 0e: passed.** Battery request with the controller off: no answer (the user confirms on 2026-11-07 that the query does not work with the controller off). Steam's behavior on the brief loss of the controller: the user reports on 2026-11-07 that it copes well (what exactly Steam displays was not recorded).

**Phase 1: plugin MVP. Done.**
- Present: receiver discovery, usbmon reader (one thread per bus, pre-filter by address marker), state machine per slot, service with hot-plug refresh, QAM panel (layout see section 5) with status, LED selection, the options standby and shutdown, and per controller "Query battery now" and "Turn off" (with a confirmation). The backend only accepts known receivers and slots 0 to 3.
- Device test, as reported by the user: loading in Decky, battery query (also right after start), LED assignment, buttons, layout, the shutdown service (on shutdown and on reboot, several controllers) and both UI languages work. The monitor was not reported on explicitly, except that switching it on does not read the battery of controllers that were already connected (expected: the receiver reports the level only on connecting). Two receivers can only be tested by replay; only one receiver is available.
- Of the assumptions the device test had to clear up, Decky loading backend and frontend, libusb in the Decky process and the receiver discovery are confirmed. Unchecked remain `select()` on the usbmon file and the presence of controllers through `<interface>/input/` (risk 19).
- Toast on low battery: built on 2026-11-07, resting on the unverified level mapping (risk 25).

**Phase 2: local control. Built.**
- Built: set and reset the LED mode per `xpadN` (default `(N mod 4)+2`), toggle `auto_poweroff`, and (2026-11-07) the **rumble test** ("Find controller": rumble for 3 s through the evdev node; works on the device). LED commands are confirmed on hardware.
- LED ↔ slot: confirmed for the first slot (`xpad0` writes to endpoint 0x01). Unchecked for further slots; the monitor remembers the last LED command per slot and can read this off as soon as a second controller is there.
- Rumble on a real controller works (risk 24).
- Acceptance: A slot can be identified specifically (LED + rumble) without another one reacting.

**Phase 3: kernel track. Dropped (decision of the user, 2026-11-07).** Steam copes well with the controller's brief loss, so the seamless battery path of a patched `xpad` is not needed. (Background, if it is ever picked up again: check kernel headers or a build environment for 7.2.11-ogc4.1 (`ls /lib/modules/$(uname -r)/build`), patch `xpad.c` to evaluate the state packet and register `power_supply`, test as an out-of-tree module, then send to linux-input. Secure Boot is off, so an unsigned module loads.)

**Phase 4: publication. Dropped (decision of the user, 2026-11-07).** The plugin stays private (section 15): no store submission, so no store texts, no author or image in `plugin.json` (the author is still `TODO`) and no Root justification for the store. The license stays GPL-2.0-or-later (risk 11). German/English is done (section 5).

**Phase 5: takeover mode, chatpad, headset. Dropped (2026-11-07).** Only regular controllers are available, and the brief loss is tolerated, so there is no need for a takeover mode.

## 7. Security and privacy

- usbmon shows the **entire** bus, including keyboard and mouse on the same bus. The backend has to filter every line immediately by `(bus, device)`, discard foreign lines, store or log nothing of them and only count the controller's input packets, not record them. This is implemented that way in `tools/capture_usbmon.py` and carried over into the plugin.
- The plugin openly states in its settings that it reads the receiver's USB traffic. The monitor is opt-in.
- Tracks B and D avoid usbmon's bus-wide view and are better from a privacy point of view.
- Foreign calls of the root backend, all without user input and with an absolute path and a sanitized environment (`safe_exec.py`): the fixed `modprobe usbmon`; `systemctl daemon-reload`, `systemctl enable --now x360-receiver-poweroff.service` and `systemctl disable --now x360-receiver-poweroff.service` (only for the one own service, only when the option is switched on and off, on the start reconciliation and on removal); and the USB commands of the short access (battery request `00 00 00 40`; after a successful one the presence request `08 00 0F C0`, which xpad itself sends when it binds, to learn the controller type; turn off `00 00 08 C0`). The plugin deletes nothing under `DECKY_HOME`. Files outside Decky: `/etc/systemd/system/x360-receiver-poweroff.service` and `/var/lib/x360-receiver/`, only while the option is on, owned by root (files 0644, folders 0755, independent of the umask), symlinks at these places are rejected, deletion only for exactly this folder name. The service runs as root; its program is a copy from the plugin and is refreshed at every plugin start as long as the option is on.
- Root rights: writes only to the named sysfs paths (`leds/xpadN`, `module/xpad/parameters/auto_poweroff`) and, for the rumble test, one force-feedback effect to the `/dev/input/eventN` node that sysfs shows under a known receiver's slot interface (opened write-only, so no input can ever be read; the node name is checked against `event<number>`; fixed strength, duration capped at 3 s; the effect is always removed again). No free shell calls.
- Short access: The backend only accepts receivers it detected itself (bus and device address), and slots 0 to 3. Only the commands `00 00 00 40` and `00 00 08 C0` are sent, to the chosen slot's endpoint. There is no automatic repetition; the user triggers every action, turning off with a confirmation.
- Languages: the frontend only reads `navigator.language`/`navigator.languages`; the language is neither stored nor sent anywhere.
- Low-battery notices carry only the slot number, the level and the language choice; nothing else leaves the backend.

## 8. Open problems and risks

1. **Access path** (section 2). Decides the scope of v1.
2. **Assigning LED ↔ slot.** The LED entry `xpadN` hangs on the USB device, not on the interface (proven: `led_classdev_register(&xpad->udev->dev, …)`). The number N comes from a global counter in connection order. Solution: write the LED and watch in usbmon on which OUT endpoint (0x01, 0x03, 0x05, 0x07) the command appears. Without usbmon only an unsafe heuristic remains. The assignment of the input devices (rumble) is unambiguous, however, because their parent is the interface.
3. **The link report only comes on connecting.** A controller that was connected before the plugin started first delivers no subtype. Ways out: start the plugin early; on request, briefly release the `xpad` interface and bind it again (triggers a new request, but disconnects the controller for seconds and must not happen during a game).
4. **Meaning of battery type and levels** unknown. Level 2, type raw 1, power state raw 2 were observed; which battery was in the controller and how full it was is not known. The display therefore says "Level 2 of 3" and claims no percentage.
5. **Clones and third-party receivers** can deviate from the protocol. The available sample packets mostly come from such devices.
6. **Bit-field order and level mapping** are derived from a C struct. The unit tests only check consistency with the sample packets, not the hardware.
7. **Decky framework:** Plugin manifest and build configuration have to be compared with the current official template (`decky-plugin-template`). Compared on 2026-11-04: `package.json`, `tsconfig.json`, `rollup.config.js`, root flag (`root`, after checking the Decky source; the template only contains the switched-off placeholder `_root`). The build with `@decky/rollup` runs through in a test copy; at that time the plugin had never been loaded in Decky (it has since, see section 0). `@rollup/rollup-linux-x64-musl` is in `package.json` like in the template and cannot be installed on glibc machines; remove it for local builds in a copy. The type check reported an error in the types of `@decky/api` (missing `react-router`), not in this code. On 2026-11-06 the type check on Windows ran through without that error.
8. **Suspend/resume:** `xpad` turns controllers off on suspend (if `auto_poweroff` is on). Whether the open usbmon handles stay usable after waking is unknown. Built on 2026-11-07 as a precaution: the refresh loop detects a resume (`x360w.resume`) and restarts the readers. Both the problem and the fix are assumptions; nothing was observed on the device. (A reader that dies with an error is also restarted after 30 s, as before.)
9. **Interaction with Steam Input:** LED and rumble tests can disturb running games. The panel warns about this.
10. **Immutable Bazzite:** A custom kernel or a module on the target device is only possible with effort (Secure Boot, signature). So work on a test system for development.
11. **License: decided (2026-11-07): GPL-2.0-or-later,** as in the README and `package.json`. If code from `xpad.c` goes into a patch, that patch is GPL-2.0 and fits.
12. **Battery reported only on connecting** (confirmed on hardware, section 6). The battery display only works for controllers whose connecting the plugin witnessed, until step 3 or 4 of the ladder is in place.
13. **Captures cut off:** `grep` buffers in blocks; on abort the rest is lost (the second capture ended at 12288 bytes). In future use `grep --line-buffered`.
14. **Thread name collision:** `threading.Thread` uses `_handle` internally; my reader had a method of the same name and failed in the test. Fixed (`_process_line`). As a note for future thread subclasses.
15. **Short access (takeover):** It works on hardware, `xpad` binds again afterwards. Open: If the interface stays unbound after an error, the slot is dead until `xpad` binds again (controller off/on or by hand); `SlotSession` releases on failure, but that is only tested against a dummy. The Decky backend needs libusb on the target system (present on Bazzite; since confirmed to work inside the Decky process, see risk 17). Steam sees the controller disappear briefly (effect unchecked, phase 0e). No automatic repetition.
16. **Battery freshness partly clarified.** With the controller off no answer came (assumed from the order of the runs), so no cache. The value was always level 2 (2 AA NiMH), though; whether it really changes with a draining battery is unchecked, and NiMH has a flat voltage curve.
17. **Stopping the plugin takes longer than Decky waits: open, with an emergency exit.** Installation by zip, loading in Decky, libusb in the Decky process (battery query, turn-off buttons) and the systemd service work according to the user. But on every stop of the plugin (a plain reload as well as an uninstall, and also with v0.0.1) the journal of the user's device (`journalctl -u plugin_loader`, 2026-11-07) reads `Attempting to unload with plugin X360 Receiver's "_unload" function`, then nothing: no `x360w unloaded` (our own last line), no `Unloaded`, no `Calling Loader uninstall function`, and 5 s later `Plugin … still alive 5 seconds after stop request! Sending SIGKILL!`. Decky's source (read 2026-11-07): SIGTERM → `shutdown()` → `_unload()` → (only on uninstall) `_uninstall()` → `sys.exit(0)`; no timeout of its own; SIGKILL after 5 s. So `_uninstall` was never reached, which is why the cleanup of the folders never worked, and the earlier remark that the service was gone after uninstalling is unexplained (most likely the option was off and no service existed). **The cause is not known.** A copy of Decky's stop sequence (`tools/decky_stop_sim.py`, run in WSL against the old and the new code) does not reproduce it: `_unload` finishes in 0.05 s there. It does show one way a stop ends in SIGKILL although `_unload` returned (a non-daemon thread or a busy executor thread keeps the interpreter from exiting after the loop is closed). Changed, in three steps: (1) 2026-11-07, v1.2.1: `_unload` and `_uninstall` no longer use `asyncio.to_thread`, every slow step runs in a plain daemon thread with a 2 s deadline and is logged. The user reports that SIGKILL still happens (journal not sent). (2) After v1.2.1: `_unload` arms `faulthandler.dump_traceback_later(4.3 s, exit=True)` first, a C-level watchdog that writes the stack of every thread to the log and ends the process before Decky's 5 s, whatever keeps it alive (the simulation shows the process ending after 4.3 s instead of being killed). (3) The plugin no longer deletes its settings, data and log folders at all (user's decision); they stay and can be removed by hand. Not yet checked on the device. If `x360w unloading` is missing from the next journal, the event loop is blocked before our code runs; if `Timeout (0:00:04.3…)!` appears, the stacks that follow show what hangs. Decky also calls `_uninstall` when the same zip is installed again.
18. **Turning off on shutdown from inside the plugin is not reliably possible; replaced by a systemd service (confirmed on the device by the user: "Shutting down works now", 2026-11-05; on a reboot too, 2026-11-07).** Three attempts inside the plugin failed on the device (clean env for `systemctl`; monitoring before the stop signal; own thread with a fine track). **Evidence:** (a) Track: `systemctl` answers inside the plugin (`systemctl_selftest` 0.01 s). (b) Decky's journal on shutdown (`journalctl -b -1 -u plugin_loader`): at 321.307 s Decky tells all six plugins "Shutting down"; SteamGridDB, ProtonDB Badges and CSS Loader answer immediately ("Calling Loader unload function"), **"X360 Receiver", NonSteamLaunchers and Decky LSFG-VK do not**; all three are killed with SIGKILL after 5 s (326.33 s), Decky ends at 326.47 s. The track has no `unload_entered` for this run. Why these three plugins do not react is unexplained (two foreign ones are affected, so not a fault in our own code alone). (c) Systemd reported `stopping` only at the moment of the stop signal (Steam closed at 318 to 319 s), so monitoring would have had no head start. (d) Between the start of shutdown and the end of Decky there are more than 5 s; USB was presumably still there (derived, not checked). **Solution (confirmed):** systemd service, see the row "Turn off on shutdown" in section 3. That shows on the device that `ExecStop` runs in time before USB disappears, and that `/usr/bin/python3`, libusb and SELinux on Bazzite allow the service. **Update 2026-11-07 (user):** several controllers turn off on shutdown **and on reboot**; they are off a few seconds after pressing the button and shortly before the computer is fully off. The exact time was not measured. **Open:** nothing specific. The report `last-run.json` shows in the diagnostics after the reboot whether and what the service did. If the plugin is removed through Decky's "Uninstall", `_uninstall` clears the service away; if the plugin folder is deleted another way, the service stays until it is removed by hand (`sudo systemctl disable --now x360-receiver-poweroff.service; sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver; sudo systemctl daemon-reload`).
19. **Presence through sysfs and LED assignment only from the source code (indirect evidence):** The battery query right after the plugin starts finds the connected controllers (user report), and it takes its targets from sysfs presence when the monitor is off (the default); whether the monitor was off in that test was not recorded. The LED assignment was confirmed by the user. Not explicitly checked: that a card appears for a connected controller with the monitor off (check in section 10).
20. **UI never seen in Steam's real look.** Checked are types, build, layout and clicks against stand-in components (`tools/frontend_render_test.mjs`). Unchecked: looks, line breaks, focus navigation with the controller, whether Decky treats `Field` with `focusable` as expected.
21. **The battery query after start costs a brief disappearance per controller.** It runs every time the plugin loads (device start, Decky restart, plugin update, reinstall). Each controller disappears for about 3 s, one after the other. The user reports that Steam copes with this well (2026-11-07). Since 2026-11-07 there is a switch ("Query battery at start", default on). Without the monitor, a controller connected later is not queried automatically (the receiver reports the battery on connecting, but only the monitor reads that). The user mostly starts the computer first and the controllers afterwards, which is exactly this case.
22. **Language detection: works (user, 2026-11-07).** The UI follows the Steam language in German and in English. The frontend takes the language from `navigator.language`/`navigator.languages` because Decky Loader's own UI does (Decky frontend `start.tsx`, read on 2026-11-06 through a summarizing fetch of the source). Since 2026-11-07 there is also a manual choice in the settings ("Automatic" / English / Deutsch). Most German texts are the plugin's original ones; those added with the language change (error messages, a few labels, the controller type names, the texts of the 2026-11-07 additions) were written by the assistant and not reviewed by a native speaker. Technical error details stay English.
23. **Start-reconciliation race: fixed (2026-11-07).** The test `test_toggle_right_after_start_is_not_undone_by_the_start_sync` failed on the original commit; a trace showed the cause: the start reconciliation `_sync_unit` read the saved option while a toggle's `install` was still running, saw "off" with the service already installed and removed it. Both now run under one lock (`_unit_lock`), so the toggle has saved its option before the reconciliation reads it. The other test that failed in WSL on the original commit (`test_runs_fixed_modprobe_when_missing_and_reports_errors`, which compared with the bare name `modprobe` although `run_fixed` resolves the absolute path) was fixed on 2026-11-06.
24. **Rumble test: works on the device (user, after the v1.2.0 release).** The controller vibrates. The first version also set the LED to "blink once"; the user did not want that, so the button now only rumbles (3 s instead of 1 s, capped at 5 s). Still unknown: whether Steam Input being active changes anything, and whether the right node is found when several controllers are connected (only one controller was tried). Failure shows a translated message ("cannot vibrate right now"), it does not harm anything else.
25. **Low-battery notice rests on the level mapping.** Level 0 = empty and 1 = low is the XInput convention and an assumption here (only level 2 has ever been seen, and 2 AA NiMH have a flat voltage curve). The notice appears only when a level is reported (connecting or a query), not while a battery drains. It can be switched off.

## 9. Tests

- 263 tests (Linux run in WSL on 2026-11-07: all pass): `python3 -I -m unittest discover -s tests`. The tests assume POSIX paths; on Windows many fail for that reason.
  - `test_protocol.py` (17): parser, command building, usbmon lines, English fallback name of an unknown subtype.
  - `test_discovery.py` (4): receiver discovery against a **reconstructed** sysfs tree (real structure unchecked); language-neutral labels and the `unofficial` flag of ID 02A9; the evdev nodes of a slot.
  - `test_fixture_capture.py`: 6 tests against the real capture of 2026-11-04.
  - `test_fixture_idle.py`: 7 tests against the real capture of 2026-11-05 (connection sequence, no further state when idle, state in the input packet header, only two xpad LED commands, `F8` toggle, monitor with age of the value).
  - `test_fixture_events.py`: 8 tests against the complete third capture (LED commands and endpoint, buttons incl. Guide 0x0400, re-binding without a state sequence, byte-identical link report, power-off 5.056 s after Guide, state with power state 0 afterwards, monitor source marking).
  - `test_fixture_takeover.py`: 7 tests against the fourth capture (detaching `xpad`, answer to presence and battery request, turn-off with power state 0, re-binding `xpad`, manual switching back on, monitor over the whole session).
  - `test_actions.py` (8): battery request (followed by the presence request that yields the controller type; none when the controller does not answer), turn-off, returned errors (with and without code/detail), lock on simultaneous access (answer carries the code `busy`).
  - `test_packaging.py` (3): layout of the Decky zip, root flag, all service helper modules in the zip.
  - `test_takeover.py` (10): dummy backend (endpoints per slot, release even on errors, command length), `UsbError` with code/detail, missing libusb reports `libusb_unavailable`, and one libusb call without a device.
  - `test_monitor.py` (22): state machine, slot assignment through endpoints, foreign devices, reconnecting, bounding unknown packets, no input content in the state, reader on a test file, service on/off, restarting the readers (stopped and joined, fresh ones started, state kept, nothing when off), LED and `auto_poweroff` logic with input validation, completeness of the LED mode descriptions, `ensure_usbmon` error texts.
  - `test_cleanup.py` (3): restoring `auto_poweroff`; a guard that the plugin has no code that deletes folders as root.
  - `test_backend.py` (51): `main.py` with a stand-in `decky` and a stand-in for `poweroff_unit` (never real files under /etc or /var): lifecycle, status shape, standby option saved and set again after a restart, shutdown option sets up/removes the service (error: option stays off, error code and detail), reconciliation on start (option on: set up/update; off: remove a remnant; a toggle right after the start is not undone, see risk 23), `_unload` turns nothing off and leaves the service alone, "Turn off all", `_uninstall` (value restored, service removed even on error, the folders are left alone, a slow service removal is not waited for forever, unloading and uninstalling work even if `asyncio.to_thread` is unusable, a hanging or failing monitor stop cannot keep `_unload` from finishing, the exit watchdog is armed first with a limit below Decky's 5 s and falls back to another output stream), error codes of the slot actions and of a missing LED, language-neutral texts in the status. New on 2026-11-07: start-query switch (saved, shown, respected), language setting (validated, saved, corrupt value falls back to automatic), low-battery notice flow (once, again after recovery, switched off, bounded queue, language attached), "Find controller" (rumble only, never an LED command; translated errors; bad arguments never reach the input device), the LED mode that is shown without the monitor (xpad's default, a mode set through the plugin, forgotten when the LED goes away), restart of the readers after a detected resume.
  - `test_backend.py` also checks the query after start: every connected controller exactly once and one after the other, no controller no query, no answer/error/exception stops nothing, "busy" is retried, `_unload` cancels a still waiting query, a manual query is remembered too.
  - `test_rumble.py` (11): structure sizes, field offsets and ioctl numbers against the known x86-64 values; the call sequence against a stand-in kernel (open write-only, upload, start, wait, stop, remove, close), duration cap, every failure path still removes the effect and closes the descriptor, busy lock, only `event<number>` node names are accepted.
  - `test_low_battery.py` (8): levels 0 and 1 are low, notified once, again after recovery or a real power cycle, not again after the brief absence of a query, controllers told apart by receiver and slot.
  - `test_resume.py` (4): detecting a suspend with two clocks (normal ticks, a long suspend, a delayed tick, small clock corrections).
  - `test_battery_cache.py` (7): queried battery levels with age and controller type; an entry only expires when the slot has been missing for longer than 15 s, because the controller itself briefly disappears during the query.
  - `test_view.py` (30): receiver view (merging monitor/sysfs, the LED mode shown without the monitor, the controller type from a query, LED only on an unambiguous assignment, unassigned controllers, targets for turning off), LED assignment through the sysfs path, presence through `input/`, all against reconstructed trees.
  - `test_shutdown.py` (6): turning off several targets with a retry on busy, deadline, error in one slot (English, language-neutral error texts).
  - `test_poweroff_unit.py` (36): service text (`ExecStop=-…`, `RemainAfterExit`, timeout larger than the program's; English and ASCII; `systemd-analyze verify` run by hand on 2026-11-06 without a message), setup (files and modes independent of the umask, fixed `systemctl` calls with a sanitized environment incl. `LANG=C`, idempotent, update without reload, an error cleans up, symlinks rejected), removal (program deleted first, then service stopped; never a symlink target or a wrongly named folder), the copy runs on its own with the system Python in isolated mode and loads only the modules in the list, entry point ends with 0 and writes the report, the diagnostics verdicts as codes with parameters and detail lines as key/value pairs (only documented codes and keys are emitted).
  - `test_poweroff_cli.py` (6): flow of the program (targets, report, errors are reported instead of raised, nothing to send), `main` always ends with 0 and writes `last-run.json` atomically.
  - `test_i18n_contract.py` (9): contract between the backend and `src/i18n.ts`: both catalogs define the same messages and tables; every error code (`x360w.error_codes`), diagnostics verdict code and detail-line key has a translation; LED modes and controller subtypes are all covered and the English texts equal the backend fallback; every field the frontend's `Controller` and `Receiver` types declare is really sent.
  - `tools/frontend_render_test.mjs` (not part of `unittest`): render test of the built frontend with jsdom and stand-in Decky components. Runs the whole check once in English and once in German (layout, order of the groups, collapsing, switches, backend calls, translated error codes, verdicts, LED mode and controller type names, hours with the language's decimal separator, "Find controller", the new switches, the language choice and its override of Steam's language, low-battery notices becoming toasts in the right language and only once), plus language detection (`de`, `de-AT`, `en-GB`, unsupported language → English, first supported entry wins, empty list, no `navigator`).
  - `npm run typecheck` additionally guarantees that the German catalog has exactly the English one's shape.
- These tests say nothing about real behavior, except where a capture is the input.
- Replay: `tools/capture_usbmon.py --file <recording>`.
- Hardware matrix for acceptance: originally a gamepad with AA and with a battery pack; if available headset, chatpad, guitar/drums; two receivers. Decision of 2026-11-07: only one receiver and regular controllers with 2 AA NiMH are available, so the rest of the matrix is out of scope (section 16).

## 10. Setup and next check

### Installing and removing (Decky's own way)

Goal: install and remove like any third-party plugin, without a script. Basis is the Decky source (`browser.py`, `sandboxed.py`, translation texts), checked on 2026-11-05; not tried on the device.

- **Install:** Decky settings → "General" → **Developer mode** on → tab "Developer" → "Third-Party Plugins" → **Install Plugin from ZIP File** → **Browse** → choose `X360-Receiver.zip` → confirm the notice. Alternatively **Install Plugin from URL**. The zip is fully built (frontend included, no Node needed) and has the form `X360 Receiver/plugin.json`, `main.py`, `dist/index.js`, `py_modules/…`. Decky reads the folder name from `plugin.json` (`name`).
- **Root:** `"flags": ["root"]` (exactly this string). Without the flag the plugin would run as a normal user and fail at libusb, sysfs and usbmon. Whether Decky asks additionally on installing is unchecked.
- **Remove:** Plugin actions in the Decky menu → **Uninstall**. Flow in Decky: SIGTERM to the plugin → `_unload` → `_uninstall` → delete the plugin folder, all within 5 s (then SIGKILL). `_uninstall` restores `auto_poweroff` and removes the systemd service. The settings, data and log folders under `DECKY_HOME/settings|data|logs/<folder>` are **not** deleted (decision of the user, 2026-11-07, after the cleanup could not be made to work, see risk 17); remove them by hand with `sudo rm -rf "$HOME/homebrew/"{settings,data,logs}"/X360 Receiver"` (they belong to root).
  - `_uninstall` resets `auto_poweroff` to the value it had before the plugin's first change (the value is remembered in the settings on the first change).
  - Only exactly `<DECKY_HOME>/<settings|data|logs>/<name>` is deleted; no symlinks, nothing outside, `..` is rejected. That matters because the backend runs as root. `/home` is a symlink to `/var/home` on Bazzite, so `DECKY_HOME` itself may be reachable through a symlink.
  - Not undone: the loaded module `usbmon` (until reboot) and a set LED mode (until the next connect). The systemd service together with `/var/lib/x360-receiver/` is removed, however (`_uninstall` calls `poweroff_unit.uninstall`, even if the option is off). Otherwise the plugin creates nothing outside Decky's folders.
- **Update:** The same zip once more. Decky uninstalls the old version first and calls `_uninstall`, which no longer deletes the settings, so they stay and the options keep their values. (Until 2026-11-07 the settings were meant to be deleted, but the cleanup never ran, so in practice they stayed too.)
- **Check on the device:** After "Uninstall" `~/homebrew/plugins/X360 Receiver` must be gone and `cat /sys/module/xpad/parameters/auto_poweroff` shows the initial value; the other three folders stay (see above).

The monitor ("Live USB monitoring") is off and loads `usbmon` itself as soon as you switch it on. Without the monitor, "Query battery now", "Turn off", the LEDs and the `auto_poweroff` switch work.

### What to check on the device

The original steps are done as far as the user reported them (section 16): receiver appears, battery query, Steam during the brief loss, shutdown and reboot service, battery after start, languages. What remains can only be checked on the device:

1. **Standby ("Turn off on standby").** The switch sets the kernel parameter `xpad.auto_poweroff`. When the device goes to sleep, `xpad` then turns all connected controllers off, so they do not drain their batteries while the device sleeps (kernel default: on). Check: switch it on, put the device to sleep, wake it. The controllers should be off and need a press of Guide to connect again. Not tried yet.
2. **Monitor ("Live USB monitoring").** Switch it on, then turn a controller off and on again: does the battery level appear by itself after connecting? (The receiver reports the level only on connecting, so controllers that were already connected show nothing until queried.)
3. **Stopping the plugin (risk 17).** Reload the plugin once, then uninstall it, and run `sudo journalctl -u plugin_loader --since "-15min" | grep -iE "x360|uninstall|Timeout|Thread"`. Wanted: `x360w unloading`, `x360w unloaded`, `Unloaded X360 Receiver` and no `still alive 5 seconds after stop request! Sending SIGKILL!`. If the watchdog fired, the journal contains `Timeout (0:00:04.3…)!` and the stack of every thread: please send it. Also `cat /sys/module/xpad/parameters/auto_poweroff` shows the initial value afterwards, and the service is gone (`ls /etc/systemd/system/x360-receiver-poweroff.service`).
4. **Cards without the monitor (risk 19).** With "Live USB monitoring" off (the default), connect a controller: does its card appear? In a terminal, `ls /sys/bus/usb/devices/1-3:1.0/input/` shows an `inputN` entry while the controller is connected (use your receiver's path from `ls /sys/bus/usb/devices/`).
5. **Added on 2026-11-07:** "Find controller" and the language choice are checked (works). Not yet tried on a device: "Send test notification" (General → Monitoring: does a toast appear?); the low-battery notice (hard to provoke with full batteries; it appears when a controller connects or is queried at level 0 or 1); "Query battery at start" switched off (no query after restarting the plugin); the language choice; after waking from sleep with the monitor on, does a controller that you turn on still show its battery level?

## 11. Measured on 2026-11-04

- System: Bazzite-Deck 44.20261026, kernel 7.2.11-ogc4.1.fc44, **Secure Boot off**, lockdown `none`, `xpad` as a module, `auto_poweroff` = Y.
- Receiver 045E:0719 on bus 1, device 2. Interfaces 0/2/4/6 belong to `xpad`, 1/3/5/7 (audio) have no driver.
- `upower` shows no controller battery.
- usbmon works through debugfs as root and delivers full packets. Foreign devices on the same bus did not appear in the filtered capture.
- The LED `xpad0` only exists while a controller is connected. The first write attempt therefore failed with "file not found" because the controller was off. My first test (`echo 6`) was also badly chosen: mode 6 looked like xpad's own end state. Later: LEDs react (mode not recorded).
- State packet (level 2, type raw 1, power state raw 2) came once, on connecting. The capture was aborted after about 38 s: no statement on periodic updates, holding Guide or turning off.

## 12. Measured on 2026-11-05

- Second capture, 393 s, one gamepad (`docs/PROTOCOL.md`, section 7). The file was cut off at the end.
- The controller was switched off and on again (6.4 s / 13.1 s). The connection sequence was the same as the day before, battery level 2 again.
- **No further state packet in the following about 380 s** (a single input at 73.5 s did not trigger one either).
- This time the state was once in the header of an input packet. Parser and monitor evaluate that now.
- 50 `F8 01/02` packets, strictly alternating, gaps ≥ 2.1 s.
- Not contained, although planned: LED test with mode 10, Guide hold, button presses. Probably in the cut-off part or after the end of the window.

## 13. Measured on 2026-11-05, third capture

- 246.7 s, complete. Details and times: `docs/PROTOCOL.md`, section 8.
- LED commands go to endpoint 0x01 (first slot). Neither LED commands nor buttons trigger a state packet. Guide has the button mask 0x0400.
- Re-binding `xpad`: the receiver answers `08 00 0F C0` with a connection packet and a link report (byte-identical to earlier ones), nothing else.
- Turning off: `xpad` sends `C0` 5.056 s after the Guide press on the next packet; afterwards a state packet with power state 0, disconnect, LED 0.

## 14. Measured on 2026-11-05, fourth capture (phase 0d)

- Short access with `tools/probe_takeover.py`: presence request, battery request and turning off work, `xpad` binds again every time (`docs/PROTOCOL.md`, section 9).
- The battery request `00 00 00 40` is answered after 27 ms with a state packet (level 2, power state 2). Freshness unresolved.
- Turning off by command confirmed (state packet with power state 0, then `08 00`).
- After switching back on manually the controller connects normally and `xpad` sets the LED.

## 15. Measured on 2026-11-05, terminal runs

- Battery request without an answer (first run) and with an answer (second run); battery: 2 AA NiMH; no charging cable available. `docs/PROTOCOL.md`, section 10.
- sysfs: receiver `1-3`, `xpad` at `1-3:1.0/1.2/1.4/1.6`. Matches the discovery in `discovery.py`.
- The plugin stays private; the goal is a setup with one command.

## 16. Reported by the user on 2026-11-07

Device checks (the user's own words, summarized; details of what exactly was seen were not recorded):
- **Languages:** works with the Steam language set to German and to English.
- **Brief loss of a controller (query battery, query at start):** works, Steam copes with it.
- **Shutdown and reboot:** several controllers turn off on shutdown and on reboot. They are off a few seconds after pressing the power button, shortly before the computer is completely off.
- **Monitor:** after switching the monitor on (then called "Read battery status"), the battery of controllers that were already connected is not read automatically. That is expected (risk 12); the open check is whether it appears after a controller connects (section 10, step 2).
- **Uninstall:** the service is gone afterwards. The folders were not checked (the user asked where they are: section 10, step 3).
- **Battery request with the controller off:** does not work (no answer).

Hardware and habits: one receiver, only regular controllers; the user sometimes starts the controllers first and sometimes the computer first, mostly the computer first (relevant for risk 21: the start query only reaches controllers that are already connected).

Decisions: the plugin stays private (phase 4 dropped); Steam copes well with the brief loss, so the kernel track (phase 3) and the takeover mode (phase 5) are dropped; the license stays GPL-2.0-or-later. Everything that needs other hardware (a draining battery, other battery types or charging, a second receiver, other controller types, headset, chatpad) cannot be tested by the user and stays open as a known limit. Built on request: the rumble test, the switch for the start query, the wake-up handling, the language choice and the low-battery notification (all unit-tested, none tried on a device yet).

Reported afterwards on 2026-11-07:
- **Standby:** "Turn off on standby" works as intended (the controllers are off after the device wakes up).
- **Uninstall:** the folders `X360 Receiver` under `settings`, `data` and `logs` were still there after uninstalling (risk 17; changed the same day).
- **Display with the monitor off:** controllers and battery levels are shown although the monitor switch is off. That is by design (sysfs presence plus the query at start); the switch was renamed to "Live USB monitoring" and its hint now says what it does (section 5, README).

Reported after the v1.2.0 release (user's own words, summarized):
- **Uninstall:** all folders are still there (risk 17). The journal the user sent showed that `_unload` never finishes (on every stop, also on a reload) and Decky kills the plugin after 5 s, so `_uninstall` is never reached. Reworked, see risk 17; open until the next uninstall is checked.
- **Find controller:** vibrates, but also changed the LED. Wanted: rumble only, and if possible a bit longer. Done: no LED command any more, 3 s instead of 1 s.
- **Query at start switched off:** the card appears, but without battery level, LED status and details. The battery level and the type/headset/chatpad details are not available without a query or live monitoring (the receiver only reports them on connecting and on a query), so that part is expected. The LED status was missing because it was only known from the monitor; now the LED pattern shows xpad's default mode or the mode set through the plugin.
- **Monitor on:** the battery level appears by itself after a controller connects.
- **Language choice:** works without problems.
- **Scrolling:** it was no longer possible to scroll down to the controller details. Probable cause (a hypothesis, not confirmed): rows that are not focusable are skipped by controller navigation, so the last reachable element ended above the details. The detail rows and the diagnostic lines are now focusable. Not yet checked on the device.
- **Texts:** the descriptions of the functions should be shorter. Done, all descriptions are now one short sentence.
- **Notification:** a test button was requested. Done: "Send test notification" in General → Monitoring shows a sample toast at once, in the UI language, without involving the backend (it tests the display, not the battery detection).

Reported after the v1.2.1 release (user's own words, summarized):
- **Stopping and uninstalling:** the folders are still there and SIGKILL is still sent. The user asked to drop the deletion of the folders and to concentrate on stopping the plugin. Done (risk 17).
- **Diagnostic lines:** reachable now, but not indented. Done: they sit in an indented block like the card's groups.
- **Find controller, LED mode without monitor, test notification, short descriptions:** work. The notification appears correctly.
- **Shutdown and reboot with the option on:** works.
- **Controller type:** shown only after the battery has been queried (with the monitor on, because the type comes from the link report the monitor sees when xpad binds again). Done: the query now also sends the presence request and reads the link report, so the type shows without the monitor. Not yet checked on the device.
- **Question: does the live USB monitoring bring anything?** Answered in the README ("What Live USB monitoring brings"): its main use is the battery of a controller that connects after the plugin has started.
