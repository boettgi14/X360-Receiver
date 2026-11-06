# Implementation plan: Decky plugin for the Xbox 360 Wireless Receiver

Status: 2026-11-06. Target system: Bazzite (Deck variant, Gaming Mode) with an Xbox 360 Wireless Receiver. The hardware results below date from 2026-11-04/05; the English/German UI was added on 2026-11-06 (see sections 0, 5 and risk 22).

This plan strictly separates **confirmed on hardware**, **only backed by sources or unit tests**, **assumption** and **open**. The protocol is in `docs/PROTOCOL.md`.

## 0. Status in brief

| Area | Status |
|------|--------|
| usbmon as a read path | **confirmed on hardware**: debugfs readable as root, full 29-byte packets, filter by bus/device works |
| Connection, link report, state packet, input packets | **confirmed on hardware** (one gamepad, 38 s capture) |
| LED control through `/sys/class/leds/xpadN/brightness` | **confirmed**: you reported that the LEDs react. Which mode was tested is not recorded; the assignment LED ↔ slot is unchecked (only one controller) |
| Battery reported periodically or only on connecting | **confirmed on hardware: only on connecting.** No further state packet in about 380 s idle, after LED commands, after A/B/Guide and after re-binding `xpad` (there only a link report with a battery level, freshness unclear). The only report in the middle of a session: on turning off (power state 0). Unchecked: battery request `00 00 00 40` with a draining battery, long operation, charging |
| Turning off by command | **confirmed on hardware** (sent by `xpad`, 5 s Guide; controller disconnected afterwards). Sending it ourselves: confirmed on hardware (short access, button in the plugin, service on shutdown) |
| Battery request by command (`00 00 00 40`) | **confirmed on hardware**: the answer is a state packet after 27 ms. With the controller off **no** answer came (assumed, from the order of the runs), so probably no cache. Whether the value changes with a draining battery is unchecked |
| Short access to a slot (libusb) | **confirmed on hardware** with `tools/probe_takeover.py`: presence request, battery request and turning off, `xpad` binds again afterwards. Wired into the plugin (buttons) and since confirmed by the user to work as a plugin (see next row) |
| Backend (monitor, service, control) | **220 tests**, including replay of four real captures. Linux run (WSL) of 2026-11-06: 219 pass, 1 fails, and it fails on the original commit too (`test_toggle_right_after_start_is_not_undone_by_the_start_sync`, risk 23). Runs as a Decky plugin on the user's device: battery query (also right after start), LED assignment and buttons confirmed correct by the user; the systemd service for shutdown works according to the user (risk 18) |
| Frontend | builds with the official toolchain, loaded in Decky and seen by the user (layout, cards, bars); render test with stand-in Decky components; focus navigation with the controller not specifically checked |
| UI languages (English/German) | **implemented 2026-11-06**, follows the Steam language through `navigator.language` (the way Decky's own UI does; read in the Decky source). Checked: type check (the German catalog must match the English one), render test in both languages including language detection, contract test between backend and catalog. **Not checked on a device:** which `navigator.language` Steam really reports with a German or English UI (risk 22) |
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
| Rumble test ("find controller") | force feedback on the input device | now |
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
  1. *General* (applies to all receivers), groups *Monitoring* ("Read battery status") and *Power* ("Turn off on standby", "Turn off on shutdown", "Turn off all controllers now").
  2. One section "Receiver N" per receiver with a header line (name, USB path, occupied slots) and the group *Controllers*.
  3. Every connected controller is an expandable card (collapsed: name, type, **battery bar with "Level n/3"**). Expanded, with a heading and a line on the left for each group: *Battery* (age of the report, "Query battery now"; bar and level only appear in the card's header row), *Power* ("Turn off controller"), *LED* (only if clearly assigned), *Details*.
  4. LEDs that cannot be assigned to a single controller appear as a group at the receiver.
  The battery bar has three segments for levels 1–3 (0 = empty, red); the mapping to percent is unproven and is not shown.
  The options standby and shutdown are under *General*, not per controller: `auto_poweroff` is a global kernel parameter, and both events concern the whole device.
- **Languages.** All UI text is in `src/i18n.ts`, in English and German; the UI follows the Steam language, detected through `navigator.language` (and `navigator.languages`) the way Decky Loader's own UI does it (source: Decky frontend `start.tsx`, i18next with `lng: navigator.language`, read 2026-11-06). German for `de…`, English for everything else. The English catalog defines the shape, the German one must match it (type check). The Python backend is language-neutral:
  - Failed actions return `{"ok": false, "error": <English text>}` plus, where a user can act on the failure, a `code` from `x360w.error_codes` and an optional `detail`; the frontend translates the code (`errors` in `i18n.ts`), appends the detail and falls back to the English text for an unknown code. Technical details (kernel, libusb, `systemctl` messages) stay English.
  - The diagnostics verdict is a code with parameters (`poweroff_unit.VERDICT_CODES`), its detail lines are `{key, value}` pairs (`LINE_KEYS`); the frontend writes the sentences.
  - LED mode names and controller type names are translated in the frontend by their number; the backend's English text is only the fallback (`tests/test_i18n_contract.py` checks that both agree). The receiver label stays language-neutral; an `unofficial` flag lets the frontend add the translated note.
  - External programs run with `LANG=C`/`LC_ALL=C`, `tools/discover.sh` does the same, and the systemd unit text is English; nothing depends on the system language.
- **Which controllers are connected?** From the monitor (confirmed) and from the input device `xpad` creates under `<interface>/input/` (derived from the source code only). That way controllers are visible even with the monitor off, then without a battery level. If there are more LEDs than detected controllers (the LED exists only while a controller is connected, confirmed), it says "n more controllers connected" and the slots are unknown.
- **LED assignment:** The LED hangs on the receiver (`led_classdev_register(&xpad->udev->dev …)`), not on the slot; it is assigned to the receiver through the resolved sysfs path. Within a receiver, the rule observed on the device applies: "xpad0 = controller 1, xpad1 = controller 2 …": LEDs sorted by number, controllers sorted by slot, pairwise, provided the counts match (otherwise the LEDs appear as a group at the receiver). With **one** receiver this stays in step, because xpad hands out the LED number and the receiver the slot, each as "smallest free". With several receivers they share the LED numbers; the order can differ (example: receiver 2 takes xpad0, then a controller connects to slot 1 of receiver 1 and gets xpad1 instead of xpad0). The assignment is then not guaranteed.
- The frontend polls the state every 2–5 s through a `callable`. The backend reports low battery as an event, and the frontend then shows a toast.
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

**Phase 0e: partly done.** Battery request with the controller off: no answer (order of the runs, not explicitly confirmed). Open: Steam's behavior on the brief loss of the controller; will be observed with the installed plugin (section 10).

**Phase 1: plugin MVP. Code written, device test as a plugin open.**
- Present: receiver discovery, usbmon reader (one thread per bus, pre-filter by address marker), state machine per slot, service with hot-plug refresh, QAM panel (layout see section 5) with status, LED selection, the options standby and shutdown, and per controller "Query battery now" and "Turn off" (with a confirmation). The backend only accepts known receivers and slots 0 to 3.
- Device test acceptance: load the plugin; the battery level of the connected controller appears within 10 s after switching on; monitor off means: no usbmon access (checkable in the logging and in `status.readers`). Two receivers can only be tested by replay as long as there is no second one.
- Unchecked assumptions the device test has to clear up: `select()` on the usbmon file behaves as expected; the real sysfs structure matches the discovery (`discovery.py` is only tested against a reconstructed tree); Decky loads backend and frontend.
- Toast on low battery: not built yet, deliberately postponed until the level mapping (0–3 against charge state) is proven.

**Phase 2: local control. Partly built.**
- Built: set and reset the LED mode per `xpadN` (default `(N mod 4)+2`), toggle `auto_poweroff`. LED commands are confirmed on hardware.
- LED ↔ slot: confirmed for the first slot (`xpad0` writes to endpoint 0x01). Unchecked for further slots; the monitor remembers the last LED command per slot and can read this off as soon as a second controller is there.
- Open: rumble test.
- Acceptance: A slot can be identified specifically (LED + rumble) without another one reacting.

**Phase 3: kernel track.**
- Precondition: check kernel headers or a build environment for 7.2.11-ogc4.1 (`ls /lib/modules/$(uname -r)/build`, otherwise the Bazzite build container or the kernel's source package). Secure Boot is off, so an unsigned module loads.
- Patch for `xpad.c`: evaluate the state packet, register `power_supply` (capacity level, status) per controller, turn off through a sysfs attribute, optionally the battery request. First test as an out-of-tree module on the device, then send to linux-input. In parallel ask Bazzite whether the patch can be carried in the kernel.
- The plugin detects the new interface and prefers it.
- Acceptance: With the patched module `upower -d` shows the battery, and "Turn off" in the plugin works.

**Phase 4: publication**
- Settings, license, store submission, security and privacy texts. (The German/English UI is done, see section 5; more languages would be added in `src/i18n.ts`.)

**Phase 5 (optional): takeover mode, chatpad, headset**

## 7. Security and privacy

- usbmon shows the **entire** bus, including keyboard and mouse on the same bus. The backend has to filter every line immediately by `(bus, device)`, discard foreign lines, store or log nothing of them and only count the controller's input packets, not record them. This is implemented that way in `tools/capture_usbmon.py` and carried over into the plugin.
- The plugin openly states in its settings that it reads the receiver's USB traffic. The monitor is opt-in.
- Tracks B and D avoid usbmon's bus-wide view and are better from a privacy point of view.
- Foreign calls of the root backend, all without user input and with an absolute path and a sanitized environment (`safe_exec.py`): the fixed `modprobe usbmon`; `systemctl daemon-reload`, `systemctl enable --now x360-receiver-poweroff.service` and `systemctl disable --now x360-receiver-poweroff.service` (only for the one own service, only when the option is switched on and off, on the start reconciliation and on removal); and the USB commands of the short access. Files outside Decky: `/etc/systemd/system/x360-receiver-poweroff.service` and `/var/lib/x360-receiver/`, only while the option is on, owned by root (files 0644, folders 0755, independent of the umask), symlinks at these places are rejected, deletion only for exactly this folder name. The service runs as root; its program is a copy from the plugin and is refreshed at every plugin start as long as the option is on.
- Root rights: writes only to the named sysfs paths (`leds/xpadN`, `module/xpad/parameters/auto_poweroff`), no free shell calls.
- Short access: The backend only accepts receivers it detected itself (bus and device address), and slots 0 to 3. Only the commands `00 00 00 40` and `00 00 08 C0` are sent, to the chosen slot's endpoint. There is no automatic repetition; the user triggers every action, turning off with a confirmation.
- Languages: the frontend only reads `navigator.language`/`navigator.languages`; the language is neither stored nor sent anywhere.

## 8. Open problems and risks

1. **Access path** (section 2). Decides the scope of v1.
2. **Assigning LED ↔ slot.** The LED entry `xpadN` hangs on the USB device, not on the interface (proven: `led_classdev_register(&xpad->udev->dev, …)`). The number N comes from a global counter in connection order. Solution: write the LED and watch in usbmon on which OUT endpoint (0x01, 0x03, 0x05, 0x07) the command appears. Without usbmon only an unsafe heuristic remains. The assignment of the input devices (rumble) is unambiguous, however, because their parent is the interface.
3. **The link report only comes on connecting.** A controller that was connected before the plugin started first delivers no subtype. Ways out: start the plugin early; on request, briefly release the `xpad` interface and bind it again (triggers a new request, but disconnects the controller for seconds and must not happen during a game).
4. **Meaning of battery type and levels** unknown. Level 2, type raw 1, power state raw 2 were observed; which battery was in the controller and how full it was is not known. The display therefore says "Level 2 of 3" and claims no percentage.
5. **Clones and third-party receivers** can deviate from the protocol. The available sample packets mostly come from such devices.
6. **Bit-field order and level mapping** are derived from a C struct. The unit tests only check consistency with the sample packets, not the hardware.
7. **Decky framework:** Plugin manifest and build configuration have to be compared with the current official template (`decky-plugin-template`). Compared on 2026-11-04: `package.json`, `tsconfig.json`, `rollup.config.js`, root flag (`root`, after checking the Decky source; the template only contains the switched-off placeholder `_root`). The build with `@decky/rollup` runs through in a test copy; at that time the plugin had never been loaded in Decky (it has since, see section 0). `@rollup/rollup-linux-x64-musl` is in `package.json` like in the template and cannot be installed on glibc machines; remove it for local builds in a copy. The type check reported an error in the types of `@decky/api` (missing `react-router`), not in this code. On 2026-11-06 the type check on Windows ran through without that error.
8. **Suspend/resume:** `xpad` turns controllers off on suspend (if `auto_poweroff` is on). The monitor has to rebuild open usbmon handles after waking.
9. **Interaction with Steam Input:** LED and rumble tests can disturb running games. The panel warns about this.
10. **Immutable Bazzite:** A custom kernel or a module on the target device is only possible with effort (Secure Boot, signature). So work on a test system for development.
11. **License:** If code from `xpad.c` goes into the patch, the patch is GPL-2.0. The plugin itself: propose GPL-2.0-or-later so that both fit together. To be decided.
12. **Battery reported only on connecting** (confirmed on hardware, section 6). The battery display only works for controllers whose connecting the plugin witnessed, until step 3 or 4 of the ladder is in place.
13. **Captures cut off:** `grep` buffers in blocks; on abort the rest is lost (the second capture ended at 12288 bytes). In future use `grep --line-buffered`.
14. **Thread name collision:** `threading.Thread` uses `_handle` internally; my reader had a method of the same name and failed in the test. Fixed (`_process_line`). As a note for future thread subclasses.
15. **Short access (takeover):** It works on hardware, `xpad` binds again afterwards. Open: If the interface stays unbound after an error, the slot is dead until `xpad` binds again (controller off/on or by hand); `SlotSession` releases on failure, but that is only tested against a dummy. The Decky backend needs libusb on the target system (present on Bazzite; since confirmed to work inside the Decky process, see risk 17). Steam sees the controller disappear briefly (effect unchecked, phase 0e). No automatic repetition.
16. **Battery freshness partly clarified.** With the controller off no answer came (assumed from the order of the runs), so no cache. The value was always level 2 (2 AA NiMH), though; whether it really changes with a draining battery is unchecked, and NiMH has a flat voltage curve.
17. **Setup on the device partly confirmed:** installation by zip, loading in Decky, libusb in the Decky process (battery query, turn-off buttons) and the systemd service work according to the user. Not explicitly confirmed: `modprobe usbmon` from the plugin (monitor switch) and `_uninstall` (removal through Decky) under real Decky. Decky also calls `_uninstall` when the same zip is installed again; settings are then lost.
18. **Turning off on shutdown from inside the plugin is not reliably possible; replaced by a systemd service (confirmed on the device by the user: "Shutting down works now", 2026-11-05).** Three attempts inside the plugin failed on the device (clean env for `systemctl`; monitoring before the stop signal; own thread with a fine track). **Evidence:** (a) Track: `systemctl` answers inside the plugin (`systemctl_selftest` 0.01 s). (b) Decky's journal on shutdown (`journalctl -b -1 -u plugin_loader`): at 321.307 s Decky tells all six plugins "Shutting down"; SteamGridDB, ProtonDB Badges and CSS Loader answer immediately ("Calling Loader unload function"), **"X360 Receiver", NonSteamLaunchers and Decky LSFG-VK do not**; all three are killed with SIGKILL after 5 s (326.33 s), Decky ends at 326.47 s. The track has no `unload_entered` for this run. Why these three plugins do not react is unexplained (two foreign ones are affected, so not a fault in our own code alone). (c) Systemd reported `stopping` only at the moment of the stop signal (Steam closed at 318 to 319 s), so monitoring would have had no head start. (d) Between the start of shutdown and the end of Decky there are more than 5 s; USB was presumably still there (derived, not checked). **Solution (confirmed):** systemd service, see the row "Turn off on shutdown" in section 3. That shows on the device that `ExecStop` runs in time before USB disappears, and that `/usr/bin/python3`, libusb and SELinux on Bazzite allow the service. **Open:** Whether a reboot (not only shutdown) and several controllers at once also turn off reliably is not specifically checked; the time until turning off was not measured. The report `last-run.json` shows in the diagnostics after the reboot whether and what the service did. If the plugin is removed through Decky's "Uninstall", `_uninstall` clears the service away; if the plugin folder is deleted another way, the service stays until it is removed by hand (`sudo systemctl disable --now x360-receiver-poweroff.service; sudo rm -rf /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver; sudo systemctl daemon-reload`).
19. **Presence through sysfs and LED assignment only from the source code:** Whether an entry appears under `<interface>/input/` when a controller is connected and the LED sits under `<usb_path>/leds/` is not checked on the device (check commands in section 10). If that is wrong, the UI without the monitor shows no controllers, with "n more controllers connected".
20. **UI never seen in Steam's real look.** Checked are types, build, layout and clicks against stand-in components (`tools/frontend_render_test.mjs`). Unchecked: looks, line breaks, focus navigation with the controller, whether Decky treats `Field` with `focusable` as expected.
21. **The battery query after start costs a brief disappearance per controller.** It runs every time the plugin loads (device start, Decky restart, plugin update, reinstall). If Decky is reloaded in the middle of a game, the connected controllers disappear one after the other for about 3 s each. There is no switch for it. How Steam reacts (player number, "disconnected/connected") is unchecked (phase 0e). On device start normally no controller is connected yet, then nothing happens. Without the monitor, a controller connected later is not queried automatically (the receiver reports the battery on connecting, but only the monitor reads that).
22. **Language detection not verified on a device.** The frontend takes the UI language from `navigator.language`/`navigator.languages`, because Decky Loader's own UI does (Decky frontend `start.tsx`: i18next with `lng: navigator.language`, read on 2026-11-06 through a summarizing fetch of the source, not the full file). That this value really follows the Steam language on SteamOS and on Bazzite is **not** confirmed; if it does not, the UI shows English on a German system (a harmless failure). The render test sets `navigator` itself, so it cannot reveal this. Most German texts are the plugin's original ones; those added with the language change (error messages, a few labels, the controller type names) were written by the assistant and not reviewed by a native speaker. Technical error details stay English. A manual language switch in the settings is a possible follow-up if detection turns out unreliable. Check: section 10, step 9.
23. **A test fails on the original commit too:** `test_backend.PoweroffServiceTests.test_toggle_right_after_start_is_not_undone_by_the_start_sync` (reproduced in WSL/Ubuntu before and after the language changes; not touched). Cause (confirmed with a trace in a scratch copy on 2026-11-06, with the test's stand-in service): the start reconciliation `_sync_unit` reads the saved option while a toggle's `install` is still running in a thread, sees "off" while the service is already installed, and removes the service the toggle just installed (trace order: toggle install starts → sync sees option off + service installed → toggle install done, option not saved yet → sync removes the service); the toggle only saves the option after `install`. With the real service the install takes longer, so the window is real, but it needs a toggle within the first moments after the plugin loads. Not fixed. Also: the other test that failed in WSL on the original commit (`test_runs_fixed_modprobe_when_missing_and_reports_errors`, it compared with the bare name `modprobe` although `run_fixed` resolves the absolute path) was fixed together with the language changes.

## 9. Tests

- 220 tests (Linux run in WSL on 2026-11-06: 219 pass, 1 known failure, risk 23): `python3 -I -m unittest discover -s tests`. The tests assume POSIX paths; on Windows many fail for that reason.
  - `test_protocol.py` (17): parser, command building, usbmon lines, English fallback name of an unknown subtype.
  - `test_discovery.py` (3): receiver discovery against a **reconstructed** sysfs tree (real structure unchecked); language-neutral labels and the `unofficial` flag of ID 02A9.
  - `test_fixture_capture.py`: 6 tests against the real capture of 2026-11-04.
  - `test_fixture_idle.py`: 7 tests against the real capture of 2026-11-05 (connection sequence, no further state when idle, state in the input packet header, only two xpad LED commands, `F8` toggle, monitor with age of the value).
  - `test_fixture_events.py`: 8 tests against the complete third capture (LED commands and endpoint, buttons incl. Guide 0x0400, re-binding without a state sequence, byte-identical link report, power-off 5.056 s after Guide, state with power state 0 afterwards, monitor source marking).
  - `test_fixture_takeover.py`: 7 tests against the fourth capture (detaching `xpad`, answer to presence and battery request, turn-off with power state 0, re-binding `xpad`, manual switching back on, monitor over the whole session).
  - `test_actions.py` (6): battery request, turn-off, returned errors (with and without code/detail), lock on simultaneous access (answer carries the code `busy`).
  - `test_packaging.py` (3): layout of the Decky zip, root flag, all service helper modules in the zip.
  - `test_takeover.py` (10): dummy backend (endpoints per slot, release even on errors, command length), `UsbError` with code/detail, missing libusb reports `libusb_unavailable`, and one libusb call without a device.
  - `test_monitor.py` (20): state machine, slot assignment through endpoints, foreign devices, reconnecting, bounding unknown packets, no input content in the state, reader on a test file, service on/off, LED and `auto_poweroff` logic with input validation, completeness of the LED mode descriptions, `ensure_usbmon` error texts.
  - `test_cleanup.py` (10): deleting only the own Decky folders: symlinks, `..`, wrong kind of folder, Bazzite symlink for `DECKY_HOME`; restoring `auto_poweroff`.
  - `test_backend.py` (37): `main.py` with a stand-in `decky` and a stand-in for `poweroff_unit` (never real files under /etc or /var): lifecycle, status shape, standby option saved and set again after a restart, shutdown option sets up/removes the service (error: option stays off, error code and detail), reconciliation on start (option on: set up/update; off: remove a remnant; toggling right after the start is not undone, see risk 23), `_unload` turns nothing off and leaves the service alone, "Turn off all", `_uninstall` (value restored, service removed even on error, foreign plugin untouched, missing folders), error codes of the slot actions and of a missing LED, language-neutral texts in the status.
  - `test_backend.py` also checks the query after start: every connected controller exactly once and one after the other, no controller no query, no answer/error/exception stops nothing, "busy" is retried, `_unload` cancels a still waiting query, a manual query is remembered too.
  - `test_battery_cache.py`: 6 tests (queried battery levels with age; an entry only expires when the slot has been missing for longer than 15 s, because the controller itself briefly disappears during the query).
  - `test_view.py` (23): receiver view (merging monitor/sysfs, LED only on an unambiguous assignment, unassigned controllers, targets for turning off), LED assignment through the sysfs path, presence through `input/`, all against reconstructed trees.
  - `test_shutdown.py` (6): turning off several targets with a retry on busy, deadline, error in one slot (English, language-neutral error texts).
  - `test_poweroff_unit.py` (36): service text (`ExecStop=-…`, `RemainAfterExit`, timeout larger than the program's; English and ASCII; `systemd-analyze verify` once by hand without a message), setup (files and modes independent of the umask, fixed `systemctl` calls with a sanitized environment incl. `LANG=C`, idempotent, update without reload, an error cleans up, symlinks rejected), removal (program deleted first, then service stopped; never a symlink target or a wrongly named folder), the copy runs on its own with the system Python in isolated mode and loads only the modules in the list, entry point ends with 0 and writes the report, the diagnostics verdicts as codes with parameters and detail lines as key/value pairs (only documented codes and keys are emitted).
  - `test_poweroff_cli.py` (6): flow of the program (targets, report, errors are reported instead of raised, nothing to send), `main` always ends with 0 and writes `last-run.json` atomically.
  - `test_i18n_contract.py` (9): contract between the backend and `src/i18n.ts`: both catalogs define the same messages and tables; every error code (`x360w.error_codes`), diagnostics verdict code and detail-line key has a translation; LED modes and controller subtypes are all covered and the English texts equal the backend fallback; every field the frontend's `Controller` and `Receiver` types declare is really sent.
  - `tools/frontend_render_test.mjs` (not part of `unittest`): render test of the built frontend with jsdom and stand-in Decky components. Runs the whole check once in English and once in German (layout, order of the groups, collapsing, switches, backend calls, translated error codes, verdicts, LED mode and controller type names, hours with the language's decimal separator), plus language detection (`de`, `de-AT`, `en-GB`, unsupported language → English, first supported entry wins, empty list, no `navigator`).
  - `npm run typecheck` additionally guarantees that the German catalog has exactly the English one's shape.
- These tests say nothing about real behavior, except where a capture is the input.
- Replay: `tools/capture_usbmon.py --file <recording>`.
- Hardware matrix for acceptance: a gamepad with AA and with a battery pack; if available headset, chatpad, guitar/drums; two receivers.

## 10. Setup and next check

### Installing and removing (Decky's own way)

Goal: install and remove like any third-party plugin, without a script. Basis is the Decky source (`browser.py`, `sandboxed.py`, translation texts), checked on 2026-11-05; not tried on the device.

- **Install:** Decky settings → "General" → **Developer mode** on → tab "Developer" → "Third-Party Plugins" → **Install Plugin from ZIP File** → **Browse** → choose `X360-Receiver.zip` → confirm the notice. Alternatively **Install Plugin from URL**. The zip is fully built (frontend included, no Node needed) and has the form `X360 Receiver/plugin.json`, `main.py`, `dist/index.js`, `py_modules/…`. Decky reads the folder name from `plugin.json` (`name`).
- **Root:** `"flags": ["root"]` (exactly this string). Without the flag the plugin would run as a normal user and fail at libusb, sysfs and usbmon. Whether Decky asks additionally on installing is unchecked.
- **Remove:** Plugin actions in the Decky menu → **Uninstall**. Flow in Decky: `_unload` → `_uninstall` → delete the plugin folder. Decky itself only deletes the plugin folder; settings, data and logs under `DECKY_HOME/settings|data|logs/<folder>` are cleared away by `Plugin._uninstall` (`x360w/cleanup.py`).
  - `_uninstall` resets `auto_poweroff` to the value it had before the plugin's first change (the value is remembered in the settings on the first change).
  - Only exactly `<DECKY_HOME>/<settings|data|logs>/<name>` is deleted; no symlinks, nothing outside, `..` is rejected. That matters because the backend runs as root. `/home` is a symlink to `/var/home` on Bazzite, so `DECKY_HOME` itself may be reachable through a symlink.
  - Not undone: the loaded module `usbmon` (until reboot) and a set LED mode (until the next connect). The systemd service together with `/var/lib/x360-receiver/` is removed, however (`_uninstall` calls `poweroff_unit.uninstall`, even if the option is off). Otherwise the plugin creates nothing outside these folders.
- **Update:** The same zip once more. Decky uninstalls the old version first (`uninstall_plugin`) and calls `_uninstall` in the process. Consequence: settings (monitor on/off) are lost, the monitor is off afterwards. This is deliberately kept simple.
- **Check on the device:** After "Uninstall" neither `~/homebrew/plugins/X360 Receiver` nor `~/homebrew/settings/X360 Receiver`, `~/homebrew/data/X360 Receiver` and `~/homebrew/logs/X360 Receiver` may exist, and `cat /sys/module/xpad/parameters/auto_poweroff` shows the initial value.

The monitor ("Read battery status") is off and loads `usbmon` itself as soon as you switch it on. Without the monitor, "Query battery now", "Turn off", the LEDs and the `auto_poweroff` switch work.

### What to check on first start

1. Does the receiver appear in the plugin (bus 1, device 2)? If not: `sudo journalctl -u plugin_loader -n 50` and send the start of the message.
2. "Query battery now" for slot 1: does the message say "battery level 2/3" and the card show "Level 2/3" (German UI: "Akku Stufe 2/3" and "Stufe 2/3")? Error texts like "libusb could not be loaded" show that libusb is missing in the Decky process.
3. Watch Steam during the brief loss: does "controller disconnected/connected" appear? Does the player number change? Does control work again immediately afterwards?
4. Switch "Read battery status" on, turn the controller off and on again: does the battery appear on its own after connecting?
5. New UI: does the connected controller appear as a card under the receiver? Without the monitor: does it come anyway (without battery)? If not, please send (controller on) `ls /sys/bus/usb/devices/1-3:1.0/` and `readlink -f /sys/class/leds/xpad0`.
6. "Turn off on standby": send the device to standby and wake it. Is the controller off? (Kernel default is on.)
7. Battery after start: switch the controller on, then restart the plugin (reload Decky or restart the device, leaving the controller connected beforehand). Does the battery level appear without doing anything? Each controller disappears for about 3 s in turn; how Steam reacts to that (player number, messages) is unchecked.
8. "Turn off on shutdown": switch the option on (the plugin sets up the service; if that fails, the option stays off and an error text appears, please copy it down). Under "General → Diagnostics → Shutdown service" it then says "The service is set up and has not run yet". Then connect a controller, shut the device down, start it again. Was the controller off? Afterwards the diagnostics show the service's verdict (time, duration, targets, result); please copy it down. In addition: `systemctl status x360-receiver-poweroff.service`, `sudo journalctl -b -1 -o short-monotonic | grep -i "x360"` (the service writes one line "x360w-poweroff {…}") and `cat /var/lib/x360-receiver/last-run.json`. Switch the option off again and check that service and folder are gone (`ls /etc/systemd/system/x360-receiver-poweroff.service /var/lib/x360-receiver`).
9. Languages: set the Steam language to German (Steam → Settings → Interface) and open the plugin: are the texts German ("Allgemein", "Akku jetzt abfragen")? Then set English: "General", "Query battery now"? Also try one other language (it should show English). If the wrong language appears, please report which language Steam is set to and what `navigator.language` returns (for example in Decky's developer tools). Note: an old service installed before 2026-11-06 is refreshed on the next plugin start (its program files changed because the code comments are English now); that is expected and does not need a reboot.

### Questions

1. Was your first run of `--battery-request` with the controller off and the second with it on? The statement "no cache" depends on that.
2. How many receivers and which controller types do you own?
3. Do you start the controller first or the computer first?

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
