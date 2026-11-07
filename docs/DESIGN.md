# Design and status

How the Decky plugin for the Xbox 360 Wireless Receiver works, why it is built this way, and what is and is not confirmed. The receiver's protocol is in [`PROTOCOL.md`](PROTOCOL.md); installation and usage are in the [README](../README.md).

Target system: Bazzite (Deck variant, Gaming Mode) or SteamOS with Decky Loader and one or more Xbox 360 Wireless Gaming Receivers.

Statements are marked **confirmed** when they were checked on a device (one receiver `045E:0719`, regular gamepads with 2 AA NiMH batteries, Bazzite) and **unverified** when they come only from sources, assumptions or unit tests. Unit tests alone never make something confirmed.

## 1. Requirements

1. Show the battery level and the other readable status of every connected controller.
2. Control the controllers: LED, find a controller by vibration, turn off on demand, on standby and on shutdown.
3. Work with several receivers at once.
4. Be usable on an English and on a German SteamOS or Bazzite; nothing may depend on the system language.
5. No kernel patch and no change to how Steam sees the controllers beyond a short interruption of one slot when asked for.

## 2. The central obstacle and the access paths

The kernel driver `xpad` owns the four controller interfaces of every receiver. It evaluates only connection and input packets, discards the state packets with the battery level, and offers no way to turn a controller off on demand. A userspace program may not use an occupied interface without detaching `xpad`, and then the controller's input is lost for that time.

| Path | Read | Send | Used |
|------|------|------|------|
| sysfs | receivers, occupied slots, LEDs | LED mode, `auto_poweroff` | yes, always |
| usbmon (passive) | everything the receiver sends, nothing else is changed | no | yes, optional ("Live USB monitoring") |
| **Short access through libusb** | yes | yes | yes, for queries and turning off |
| force feedback through the evdev node | no | rumble effect | yes, for "Find controller" |
| systemd service | no | turn-off command | yes, for "Turn off on shutdown" |
| Kernel patch for `xpad` (`power_supply`, turn-off attribute) | yes | yes | not pursued: the short access is enough |
| Full userspace takeover with virtual controllers (uinput) | yes | yes | not pursued: Steam copes with the short interruption |
| eBPF on `xpad` functions | partly | no | not pursued |

The **short access** claims one slot's interface for a few seconds, sends a command, reads the answer and releases it; libusb detaches and re-attaches `xpad` itself. That slot's controller disappears from the system for about 3 seconds. Other slots stay untouched. Steam copes with this: confirmed on the device.

## 3. What the plugin does

| Function | Way | Status |
|----------|-----|--------|
| Detect receivers (IDs, bus, device, firmware, original or clone) | sysfs | confirmed |
| Detect connected controllers | monitor, or the input device xpad creates under `<interface>/input/` | confirmed, also without the monitor |
| Battery level (4 levels), battery type, power state | state packet: from the monitor when a controller connects, from a battery query otherwise | confirmed (level 2 only) |
| Controller type (gamepad, wheel …) | link report: from the monitor, and from the presence request that follows every successful battery query | confirmed for gamepads |
| **Battery query** | `00 00 00 40` through the short access. No answer when the controller is off | confirmed |
| Battery query once at plugin start for every connected controller | same, switchable ("Query battery at start") | confirmed |
| Low-battery notification | toast when a level is 0 or 1 (assumes 0 = empty, 1 = low); switchable; "Send test notification" shows a sample | display confirmed; detection unverified (see section 9) |
| LED pattern (modes 0–15), reset to default | `/sys/class/leds/xpadN/brightness`; shows the mode the monitor saw, the one set through the plugin, or xpad's own default `(N mod 4) + 2` | confirmed |
| Find controller | rumble effect (3 s) through the controller's evdev node, write-only; LED untouched | confirmed |
| Turn off one controller | `00 00 08 C0` through the short access, with a confirmation dialog | confirmed |
| Turn off all controllers now | same for every connected controller | confirmed |
| Turn off on standby | kernel parameter `xpad.auto_poweroff`, saved and set again at every start | confirmed |
| Turn off on shutdown and reboot | systemd service (section 5) | confirmed, also with several controllers |
| Language choice | Automatic (Steam language), English or Deutsch | confirmed |
| Several receivers | one section per receiver | unverified: only one receiver was available |
| Chatpad, headset | not supported | – |
| Battery in percent | not available: the protocol knows four levels | – |
| Signal quality, radio channel | no source found | – |

Holding the Guide button for 5 seconds turns a controller off by itself (built into `xpad`).

## 4. Architecture

```
Decky frontend (React, @decky/ui)          Decky backend (Python, root)
 src/index.tsx   panel                <---> main.py   Plugin class
 src/i18n.ts     English/German texts        ├─ service       receiver discovery + usbmon readers
 toasts for low battery                      ├─ monitor       state machine per receiver and slot
                                             ├─ view          receivers → controllers, LED assignment
                                             ├─ actions       battery query, turn off (short access, takeover)
                                             ├─ rumble        force feedback
                                             ├─ controls      LED, auto_poweroff
                                             ├─ battery_cache queried levels with age and type
                                             ├─ low_battery, resume, loop_guard
                                             └─ poweroff_unit, poweroff_cli, shutdown   shutdown service
```

- **Backend.** Runs as root (`"flags": ["root"]` in `plugin.json`; Decky checks for exactly this string, the template's `_root` is the switched-off placeholder) because libusb, sysfs and usbmon need it. Settings are kept in `x360w.json`: `monitor_enabled`, `auto_poweroff`, `poweroff_on_shutdown`, `original_auto_poweroff`, `startup_battery_query`, `low_battery_toast`, `language`.
- **Frontend.** Polls `get_status` every 2 s and the notification queue every 10 s. The panel shows no progress or success messages, only failures in red; the new battery level simply appears in the card.
- **Data model.** Receiver (USB path, bus, device, IDs, firmware) → slots 0–3 (state, type, battery, headset, chatpad, LED). usbmon is filtered by (bus, device address), so several receivers on one bus are told apart. A new device address after replugging is picked up by the regular refresh (every 5 s).
- **UI.** *General* (Monitoring, Power, Language, Diagnostics), then one section per receiver with the connected controllers as expandable cards. A card has the groups Battery, Power, Identify, LED and Details; its header row shows name, type and the battery bar with the level "n/3". Rows are focusable so that controller navigation can scroll to them. Diagnostics shows the verdict of the last shutdown run and its detail lines.
- **Which controllers are connected.** From the monitor and from the input device xpad creates; a controller therefore shows up without the monitor, then with the battery level of the last query if there is one. If there are more LEDs than detected controllers, the UI says "n more controllers connected" and the slots are unknown.
- **LED assignment.** The LED belongs to the receiver (it is registered on the USB device), not to a slot. Within a receiver, LEDs sorted by number are paired with the controllers sorted by slot, if the counts match (xpad0 = controller 1, xpad1 = controller 2 …). xpad and the receiver both hand out the LED number and the slot as "smallest free", so this holds for one receiver. Several receivers share the LED numbers, so the pairing is then not guaranteed (unverified).
- **Battery after start.** The receiver reports the battery only when a controller connects (section 5 of `PROTOCOL.md`). A controller that was connected before the plugin started is therefore queried once, one after the other, and the value is kept in `battery_cache` with its age; the newer of monitor and query wins. The monitor shows the battery of a controller that connects later by itself; without it, "Query battery now" is needed for such a controller.
- **Wake-up.** `resume.ResumeDetector` notices a resume from suspend (the wall clock advanced more than the monotonic clock) and the refresh loop restarts the usbmon readers. Unverified: that the readers need it, and that it works.
- **Low-battery notices.** The refresh loop feeds `low_battery.LowBatteryWatcher`; a controller whose level becomes 0 or 1 is queued once, and again only after its level went back up or after a real power cycle. The frontend pulls the queue, so nothing is lost if the UI is not loaded yet.

## 5. Shutdown

### Turning controllers off on shutdown and reboot

`xpad` has no shutdown hook, and the plugin cannot do the job itself while Decky is shutting it down. When the option is switched on, the plugin sets up a small systemd service and removes it again when the option is switched off and when the plugin is removed:

- `/etc/systemd/system/x360-receiver-poweroff.service`: `Type=oneshot`, `RemainAfterExit=yes`, `ExecStop=-/usr/bin/python3 -I /var/lib/x360-receiver/poweroff.py`, `TimeoutStopSec=12`.
- `/var/lib/x360-receiver/`: a copy of the needed backend modules, `poweroff.py`, and `last-run.json`, the report of the last run that the plugin shows under Diagnostics.

On shutdown and reboot systemd runs `ExecStop`: the program finds the targets (sysfs and LEDs, without usbmon), sends `00 00 08 C0` to each with the same command sequence as the button, within a deadline of 8 s, and always exits with 0. The copy is refreshed at every plugin start while the option is on. The unit text is English on every system.

### How Decky stops the plugin, and the guards against its bug

Decky stops a plugin with SIGTERM and kills it with SIGKILL if it is still alive 5 seconds later. Inside the plugin process, Decky's socket reader (`_listen_for_method_call`) has a bug: when Decky closes its end of the socket while stopping the plugin, every read returns empty, the loop does not stop, creates a task per iteration and never lets the event loop run again. Seen on the device as: the main thread stuck in `asyncio.create_task`; on a plain reload SIGTERM never handled; `_unload` stopping at its first real `await`. Plugins whose `_unload` has no suspension point finish in time. Three layers keep this plugin from being killed:

1. `_unload` and `_uninstall` never suspend: no real `await`, no thread, no `asyncio.to_thread`. Their steps run in one go and are logged with their time. A test keeps it that way.
2. `loop_guard.LoopGuard`: a heartbeat on the event loop and a watching daemon thread. If the heartbeat is older than 1.5 s and has not moved 1.0 s later, the thread ends the process, so a plain reload ends after about 2.5 s. `_unload` disarms it first.
3. An exit watchdog (`faulthandler.dump_traceback_later(4.3 s, exit=True)`) is armed first in `_unload`. It ends the process before the 5 s and writes the stack of every thread to the log. Confirmed on the device.

Layers 2 and 3 may become unnecessary if Decky fixes its reader; they do no harm.

### Uninstalling

`_uninstall` restores `auto_poweroff` to the value it had before the plugin first changed it and removes the systemd service. It does not delete the plugin's settings, data and log folders under `DECKY_HOME`; they can be removed by hand (README). The settings therefore survive a reinstall of the zip.

## 6. Security and privacy

- usbmon shows the **entire** bus, including other devices. The reader checks every line only as bytes for the address marker of the watched receivers and discards everything else before decoding; nothing of it is stored or logged. A controller's input packets are only counted, never decoded into the state, never recorded. usbmon is off by default and loaded (`modprobe usbmon`) only when the user switches the monitor on. There is no network access.
- The root backend writes only to `/sys/class/leds/xpadN/brightness` and `/sys/module/xpad/parameters/auto_poweroff`, and knows exactly these external actions, all without user input in a command line, with an absolute path and a sanitized environment (`safe_exec.run_fixed`, `LANG=C`):
  - `modprobe usbmon`;
  - `systemctl daemon-reload`, `systemctl enable --now` and `systemctl disable --now` for its one own service;
  - the USB commands of the short access, only to receivers it found itself (bus and device address) and slots 0–3: battery request `00 00 00 40`, presence request `08 00 0F C0` (after a successful battery request, to learn the controller type), turn off `00 00 08 C0`; there is no automatic repetition, and turning off asks for confirmation;
  - one force-feedback effect, write-only, fixed strength, at most 5 s (3 s in use), to the `/dev/input/eventN` node that sysfs shows under a known receiver's slot interface; the node name is checked against `event<number>`, the effect is always removed again, and nothing is ever read from the node.
- Outside Decky the plugin creates only the service file and `/var/lib/x360-receiver/`, only while the shutdown option is on. Both are owned by root (files 0644, folders 0755, independent of the umask), symlinks at these places are refused, and deletion is limited to that exact folder name.
- The plugin deletes nothing under `DECKY_HOME`.

## 7. Verification status

### Confirmed on a device

Loading and running in Decky (including libusb in the Decky process and the root flag); the receiver, controllers and cards (also without the monitor); the battery query, also right after the plugin starts, and its being silent when the controller is off; the battery appearing by itself with the monitor on; Steam coping with the short interruption; LED assignment, LED patterns and their reset; "Find controller" (rumble, LED unchanged); turning off one or all controllers; standby; the shutdown service on shutdown and on reboot with several controllers; English and German UI and the language choice; the test notification; scrolling to the details with the controller; the plugin stopping and uninstalling without being killed; the service being removed on uninstall.

### Unverified

- The meaning of the battery levels 0–3 (only level 2 was ever seen), and therefore the low-battery notification at a real low level. The notification can be switched off.
- Whether the battery query measures freshly as a battery drains.
- Other battery types (alkaline, packs, charging) and power states 1 and 3.
- Several receivers (LED assignment), several controllers on one receiver beyond the shutdown case, and other controller types (wheel, guitar, drums), headset and chatpad.
- The resume-from-suspend handling of the monitor.
- Whether Steam Input being active changes the rumble.
- The German texts that are not the original ones (error messages, type names, newer settings) were not reviewed by a native speaker.

### Known limits

- Only four battery levels, no percentages.
- A battery query or turning off makes the controller disappear for about 3 seconds; do not use it during a game.
- Without a battery query and without live monitoring, a card shows no battery level and no type or headset/chatpad details: the receiver reports them only on connecting and on a query. The LED pattern then shows xpad's default mode until it is changed.
- The plugin leaves its settings, data and log folders behind when uninstalled.

## 8. Tests

`python3 -I -m unittest discover -s tests` runs without hardware and without root, entirely against stand-ins. The tests assume POSIX paths; on Windows run them in WSL or on Linux.

| Test module | What it covers |
|-------------|----------------|
| `test_protocol` | packet decoding, command building, usbmon lines |
| `test_fixture_capture`, `_idle`, `_events`, `_takeover` | replay of four real usbmon captures (`tests/fixtures/`): connection sequence, no further state when idle, LED commands, buttons, re-binding, turn-off timing, the short access |
| `test_monitor` | state machine, slot mapping, foreign devices, reader on a test file, service on/off and restart of the readers, LED and `auto_poweroff` logic |
| `test_discovery`, `test_view`, `test_battery_cache` | receivers from a reconstructed sysfs tree, evdev nodes, merging monitor and sysfs, LED pairing and modes, queried battery and type |
| `test_takeover`, `test_actions`, `test_shutdown` | the short access with a dummy backend, battery query with the presence request, turning off several targets with a deadline |
| `test_rumble` | structure sizes and ioctl numbers against known x86-64 values, call sequence against a stand-in kernel, failure paths |
| `test_poweroff_unit`, `test_poweroff_cli` | service text and files in temp folders (never under `/etc` or `/var`), modes independent of the umask, symlinks refused, the copy running on its own, the report, the diagnostics verdicts |
| `test_low_battery`, `test_resume`, `test_loop_guard` | notification logic, suspend detection, starved-loop guard |
| `test_backend` | `main.py` with a stand-in `decky` module: lifecycle, settings, actions and their error codes, start reconciliation, shutdown path (never suspends, no thread, watchdogs), `_uninstall` |
| `test_cleanup` | restoring `auto_poweroff`; a guard that the plugin has no code that deletes folders |
| `test_i18n_contract` | backend codes, diagnostics verdicts, LED modes and controller types all have a translation in `src/i18n.ts` |
| `test_packaging` | layout of the Decky zip, root flag |

`npm run typecheck` additionally guarantees that the German catalog has exactly the English one's shape. `tools/frontend_render_test.mjs` renders the built frontend with stand-in Decky components in jsdom, once in English and once in German, and checks layout, switches, backend calls, error translation, notifications and language detection. It is no test against Steam's real UI.

## 9. Checks after installing on a new device

1. The receiver and the connected controllers appear. If a card is missing with the monitor off, `ls /sys/bus/usb/devices/<receiver>:1.0/input/` shows an `inputN` entry while the controller is connected.
2. "Query battery now" shows the level and, under Details, the type. With the controller off it shows nothing.
3. "Find controller" vibrates the controller for about 3 seconds and leaves the LED alone.
4. With "Turn off on shutdown" on, `systemctl status x360-receiver-poweroff.service` is active; after a shutdown, Diagnostics shows the result and `cat /var/lib/x360-receiver/last-run.json` the report.
5. Reload the plugin and uninstall it: `sudo journalctl -u plugin_loader --since "-15min" --no-pager | grep -iE "x360|SIGKILL|Timeout"` shows `x360w unloaded` and no `Sending SIGKILL`. If the exit watchdog fired, `Timeout (0:00:04.3…)` and the stacks of all threads follow.
6. After uninstalling, `cat /sys/module/xpad/parameters/auto_poweroff` shows the initial value, and the service file is gone.
