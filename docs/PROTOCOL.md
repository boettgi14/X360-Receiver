# Protocol of the Xbox 360 Wireless Gaming Receiver

Summary of the research. Every statement carries a confidence level:

- **[Source]** read directly in a source (xpad.c, argon.md, xboxdrv PROTOCOL)
- **[Unit-tested]** confirmed by unit tests against sample packets from the sources, but not on real hardware
- **[Hypothesis]** assumption that has to be checked on hardware (phase 0)

## 1. Device and interfaces

- USB IDs: 045E:0291 and 045E:0719 [Source: argon.md]. xpad additionally knows 045E:02A9 as "Unofficial" [Source: xpad.c].
- A receiver has 4 slots. Each slot has one controller interface (class 0xFF, subclass 0x5D, protocol 0x81) and one audio interface (protocol 0x82) [Source: argon.md].
- Endpoints: controller 1 = IN 0x81 / OUT 0x01, controller 2 = 0x83 / 0x03, controller 3 = 0x85 / 0x05, controller 4 = 0x87 / 0x07. Audio sits on the even endpoint in between [Source: argon.md].
- "Slot" means order of connection at the receiver, not the player number (LED) [Source: argon.md].
- xpad binds only the controller interfaces (protocol 129), not the audio interfaces [Source: xpad.c, `XPAD_XBOX360_VENDOR_PROTOCOL(vend, 129)`].
- Each IN packet is typically 28 or 29 bytes long [Source: xboxdrv].

## 2. IN packets (receiver → host)

Header (5 bytes): `[0]` packet ID (0x00, 0x08 on connection), `[1]` type, `[2]` unused (0x00), `[3..4]` header data.

| ID | Type | Content | Status |
|----|------|---------|--------|
| 0x08 | Bits 0x80 / 0x40 in the type byte | Connection: 0x80 = controller present, 0x40 = headset present. Two bytes long | Source, unit-tested |
| 0x00 | 0x00 | **State** in header bytes 3–4, valid only if `byte3 & 0xF0 == 0x10` | Source, unit-tested |
| 0x00 | 0x01 / 0x03 | Input data (buttons, triggers, sticks) from offset 5 | Source |
| 0x00 | 0x05 | Capabilities (first data byte 0x12) | Source |
| 0x00 | 0x0F | **Link report**: device info on connecting (first data byte 0xCC) | Source, unit-tested |
| 0x00 | 0xF8 / 0xF9 | Unknown; appear in pairs, also after a headset change | Source (observed only) |

### State fields (byte 3 and byte 4)

```
Byte 3:  bits 0-1 vibrationLevel   bit 2 headset   bit 3 chatpad   bits 4-7 marker = 0x1
Byte 4:  bit 0 unknown   bits 1-2 batteryType   bit 3 onlyMic   bits 4-5 powerState   bits 6-7 batteryLevel
```

- The LSB-first bit order is an assumption from the C struct [Hypothesis].
- `batteryLevel` 0..3 corresponds to the four XInput levels (empty, low, medium, full) [Hypothesis].
- `batteryType` raw 0..3. From the examples: 0xE0 = type 0 (the xboxdrv author suspects "Charging?"), 0xE2 = type 1, 0xE6 = type 3. Which number is alkaline, NiMH pack or "wired/Play & Charge" is **open** [Hypothesis]. Phase 0 clears this up with AA batteries and a Play & Charge pack.
- `powerState` raw 0..3, meaning unknown. 2 in all examples.

### Link report (after the 5-byte header, 24 data bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0 | 1 | always 0xCC |
| 1 | 4 | unknown |
| 5 | 4 | deviceID |
| 9 | 1 | type |
| 10 | 1 | revision |
| 11 | 2 | state (same format as the state bytes above) |
| 13 | 2 | protocol |
| 15 | 2 | unknown |
| 17 | 3 | vendorIDData |
| 20 | 1 | subtype |
| 21 | 3 | unknown |

- The formula for the vendor ID from the source gives 0x50001 for the xboxdrv example, which is not a plausible value [Unit-tested]. The raw bytes are therefore shown as well; the formula is unchecked.
- Subtypes (gamepad, wheel, arcade stick, flight stick, dance pad, guitar, alternate guitar, drum kit, bass, arcade pad) come from the XInput documentation, which was not checked in this session [Hypothesis]. A kernel patch draft (2026) names at least gamepad, wheel, arcade stick, flight stick, dance pad, guitar and alternate guitar [Source: LKML patch, preview].
- The English names are in `x360w.protocol.SUBTYPE_NAMES`; the plugin UI shows translated names keyed by the subtype number (`src/i18n.ts`). The German names are translations of these English names, not taken from a source.

## 3. OUT commands (host → receiver), 12 bytes, on the slot's OUT endpoint

| Command | Bytes | Status |
|---------|-------|--------|
| Request status/presence | `08 00 0F C0 00…` | Source (xpad.c uses it on start) |
| Request battery status | `00 00 00 40 00…` | Source (argon.md), not in xpad |
| Request capabilities | `00 00 02 80 00…` | Source (argon.md) |
| Set LED | `00 00 08 (0x40 + mode) 00…`, mode 0–15 | Source (xpad.c, argon.md) |
| **Turn the controller off** | `00 00 08 C0 00…` | Source (xpad.c `xpad360w_poweroff_controller`, argon.md, xboxdrv) |
| Rumble | `00 01 0F C0 00 large small 00…` | Source (xpad.c) |
| Enable chatpad | `00 00 0C 1B …` plus keep-alive 0x1E/0x1F every second | Source (xboxdrv) |

LED modes according to xpad.c: 0 off, 1 all blink, 2–5 position 1–4 blinks then on, 6–9 position 1–4 on, 10 rotating, 11 blinking, 12 slow blinking, 13 rotating with two lights, 14 permanently slow all blinking, 15 blink once.

Power state: `0xC0 | state`, state 0 turns the controller off [Source: argon.md]. Other states (1–3) are unexplored.

## 4. What the Linux kernel (xpad.c) uses of this

- Connection/disconnection (bit 0x08 in the first byte, controller bit 0x80 in the second) and input data (type 0x01) are evaluated.
- **State, link and capabilities packets are not evaluated.** There is no `power_supply` registration for the battery [Source: xpad.c, searched in the source].
- Turning off happens only (a) after holding the Guide button for 5 seconds (`XPAD360W_POWEROFF_TIMEOUT`) and (b) on system suspend if the module parameter `auto_poweroff` is set (default: on, writable under `/sys/module/xpad/parameters/auto_poweroff`).
- LEDs appear as `/sys/class/leds/xpadN/brightness`. A command 0–15 is written (`command %= 16`). The LED entry hangs on the USB device, not on the interface. The assignment xpadN → slot can therefore not be read directly (see PLAN.md, open problem 2).
- Rumble goes through the input device's normal force-feedback interface.

## 5. Open source situation

- The file xboxdrv/PROTOCOL was only loaded up to about the halfway point (rest not seen).
- The hardware examples mostly come from third-party controllers or receivers. Original Microsoft devices can differ.
- No host command was found for sync/pairing, slot assignment or radio quality. That does not mean there is none.

## 6. Hardware confirmation (capture of 2026-11-04)

Device: receiver 045E:0719, Bazzite-Deck 44.20261026, kernel 7.2.11-ogc4.1, one gamepad. Raw data: `tests/fixtures/capture_connect_gamepad_2026-11-04.txt`, checked by `tests/test_fixture_capture.py`. Duration about 38 s.

Confirmed on real hardware:
- usbmon delivers the **complete 29 bytes** of the IN packets.
- Connection packet: `08 00` = nothing connected, `08 80` = controller connected.
- Right after connecting, a link report follows (subtype 0x01 = gamepad, protocol 0x1D20, revision 0x20; in the xboxdrv example the revision was 0x05, so it varies), then a state packet (header data `13 A2`: battery level 2, battery type raw 1, power state raw 2, vibration 3, no headset/chatpad).
- Input packets (type 0x01): the button mask matches the XInput layout (A 0x1000, B 0x2000, X 0x4000, Y 0x8000, LB 0x0100, RB 0x0200, L3 0x0040, R3 0x0080, D-pad 0x0001/0x0002/0x0004/0x0008). Triggers 0–255, sticks 16-bit signed. Every input packet is followed by an empty packet `00 00 00 F0`.
- `xpad` sends LED command 0 (`00 00 08 40 …`) on disconnect and LED command 2 (`00 00 08 42 …`) on connect. Both are byte-identical to `build_led(0)` and `build_led(2)`.
- Writing to `/sys/class/leds/xpadN/brightness` changes the controller's LEDs (reported by the user, 2026-11-04). Which mode was tested and on which OUT endpoint the command appeared was not recorded. The LED `xpadN` only exists while a controller is connected.

Observed but not explained:
- After the state packet come three type-0 packets with header data `20 1D`, `30 03`, `40 01` and then `F0 00`. The same byte sequences are in the link report (protocol, unknown field, start of the vendorIDData). That suggests tag/value pairs, but it is only a guess.
- Packets `00 F8 01` and `00 F8 02` came five times in 38 s (at 0.0 / 13.5 / 19.8 / 29.0 / 37.6 s), irregularly. Meaning unknown.
- **Only a single state packet came, on connecting.** Whether the receiver reports the battery level again on its own later is open. If not, a passive monitor cannot see the battery of an already connected controller.

Still unchecked: mapping of level 0–3 to charge state (only level 2 observed, battery condition unknown), meaning of the battery type values, turning off by command, Guide/Start/Back.

## 7. Second capture (2026-11-05): idle after connecting

Device as in section 6, one gamepad. Raw data: `tests/fixtures/capture_idle_gamepad_2026-11-05.txt`, checked by `tests/test_fixture_idle.py`. 393 s, of which about 380 s with a connected controller. The file is cut off at the end (grep buffers in 4 KiB blocks, it stopped at 12288 bytes). The planned LED test, holding the Guide button and the button presses are not in it; in the window there is only a single input (at 73.5 s, button mask 0, presumably a touch of the stick).

Confirmed on real hardware (one controller, one window, idle):
- **After connecting, no further state packet comes.** No link report, no type-0 state, no state in the header of an input packet in the following about 380 s. So the receiver does not report the battery periodically on its own. Not checked: reaction to an LED command, button press, Guide, turning off, long operation with a draining battery.
- The connection sequence is reproducible: `08 00` (disconnected), LED command 0, `08 80` (connected), LED command 2, link report, then a series of packets with header data `13 A2` (state), `00 20`, `13 A2` (state), `20 1D`, `30 03`, `40 01`, then permanently `F0 00`. The state was level 2, type raw 1, power state raw 2 both times. The battery value in the link report had bit 0 set (`13 A3`), in the state packet it did not (`13 A2`); meaning of the bit unknown.
- **The state can be in the header of an input packet (type 0x01)**, not only in a type-0 packet. In the first capture the same header data came as type 0; so the order and the packet type change. The parser therefore also evaluates the header data of input packets (`InputReport.state`).
- Packets `00 F8 01` and `00 F8 02` keep coming, **50 of them in 393 s, strictly alternating** (02, 01, 02, 01, …). Every gap is larger than 2.0 s and close to a multiple of about 2.1 s (2.1 / 4.2 / 6.3 / 8.4 / 12.5 / …). That suggests a toggle that is sampled on a fixed clock. Meaning unknown; a connection quality would be conceivable, that is only a guess. Check: deliberately shield or remove the controller and observe whether rate or ratio change.
- Empty packets `00 00 00 F0` also occur without input, singly and in pairs.

Still unchecked: level mapping, battery type values, turning off by command, Guide/Start/Back, which OUT endpoint belongs to which slot.

## 8. Third capture (2026-11-05): LED, buttons, re-binding, turning off

Device as before, one gamepad. Raw data: `tests/fixtures/capture_events_gamepad_2026-11-05.txt` (complete, 246.7 s), checked by `tests/test_fixture_events.py`. Times in seconds since the start.

Confirmed on real hardware:
- **LED commands** (`00 00 08 4A` = mode 10 at 114.3 s, `00 00 08 42` = mode 2 at 132.4 s) go to **OUT endpoint 0x01**. The LED `xpad0` thus belongs to the first slot (only one controller, the assignment for further slots is unchecked). The receiver answers LED commands with **no** state packet.
- **Buttons:** A = 0x1000, B = 0x2000, **Guide = 0x0400** in the input packet's button mask. Button presses trigger no state packet.
- **Unbinding `xpad`:** the reading URB ends with status −108, `xpad` still tries to send LED 0 (error −2).
- **Binding `xpad`:** `xpad` sends `08 00 0F C0` (byte-identical to `build_status_request()`). Within 6 ms the receiver answers with the connection packet `08 80` and a link report. The link report is **byte-identical** to the one on a real connect (state in it `13 A3`: level 2). **No** state packet and **no** header sequence (`13 A2`, `20 1D`, …) follows. Whether the battery value in the link report is freshly measured or a copy held by the receiver is unknown. Notable: in the link report bit 0 of the state is set (`A3`), in real state packets never (`A2`). That points more to a copy or a different field; it is not proof.
- **Turning off:** `xpad` sends `00 00 08 C0` on endpoint 0x01, **5.056 s after the Guide press**, at the same moment as the next input packet (the release, button mask 0). After that, measured from the command: **state packet 27 ms later (header `13 82`: level 2, type 1, power state 0)**, connection packet `08 00` after 55 ms, LED command 0 from `xpad` after 63 ms. Switching back on by hand after 12.3 s produced the usual connection sequence. That the controller was off after the command follows from the connection packet and the later reconnection; whether it would have turned off without the command was not checked separately.
- This is the **first state packet in the middle of a session**. It came on turning off, not periodically. Power state 2 (normal) changed to 0.
- After a real connect: link report, then the header sequence. The order of the first pieces changes between sessions. The values `00 20`, `13 A2`, `20 1D`, `30 03`, `40 01` correspond in this order to the bytes in the body of the link report (`00 20 13 A3 20 1D 30 03 40 01 50 01`). Hypothesis: these are 2-byte pieces of the same record, spread over the headers of following packets; `50 01` and bit 0 of `13` are missing from the link report. Medium confidence.

From the source code (`drivers/input/joystick/xpad.c`, current Torvalds main branch, **not** the version on the device):
- Comment "XBOX360W controllers can't be turned off without driver assistance". The driver remembers the Guide press (one-second resolution) and checks at **every following input packet** whether at least 5 s have passed. Then it sends `00 00 08 C0`. Holding alone produces no packet; only the release or a stick movement triggers it. Matches the capture.
- On start (`xpad360w_start_input`) the driver sends the presence request; the comment says this forces new connection packets. Matches the capture.
- On suspend the driver sends `C0` if `auto_poweroff` is on and a controller is present.

Conclusions (not a measurement): A program that claims an interface itself for a few seconds could send `C0`. Turning a controller off costs no input, because it is off afterwards anyway. Whether the battery request `00 00 00 40` returns anything is unknown (phase 0d).

## 9. Fourth capture (2026-11-05): short access with `tools/probe_takeover.py`

Raw data: `tests/fixtures/capture_takeover_gamepad_2026-11-05.txt` (115 s, complete), checked by `tests/test_fixture_takeover.py`. Plus the tool's terminal output (the decoding matches the capture). One receiver 045E:0719, one gamepad in slot 1.

Confirmed on real hardware:
- **Taking over an interface through libusb works** (`LibusbBackend`: open the device, detach `xpad` automatically, claim the interface, write to OUT 0x01, read from IN 0x81, release). `xpad` binds again afterwards every time, about 2 s after the access, and itself sends the presence request and LED command 2 in the process. When detaching, `xpad` still sends LED 0 (error −2, because it is just being torn down).
- **Presence request** `08 00 0F C0` (sent by ourselves): answer `08 80` plus link report within 8 ms.
- **Battery request `00 00 00 40`:** the answer is **a state packet** `00 00 00 13 A2` (level 2, type 1, power state 2, bit 0 = 0) after **27 ms**, followed by an empty packet. That is the same packet format as on connecting. It is the first way to get the battery **on demand**.
- **Turn off `00 00 08 C0`** (sent by ourselves): after 31 ms a state packet with power state 2, after 39 ms one with **power state 0** (`13 82`), after 55 ms `08 00` (disconnected). The controller was off afterwards. A subsequent presence request from `xpad` gave `08 00`.
- **Manual switching back on** 18 s later: `08 80`, link report, header sequence as usual; `xpad` (bound again) immediately set LED 2. So the controller connected normally again.
- The tool's read timeouts (every 100 ms, URB status −2) are part of the procedure, not errors.

Open:
- **Freshness of the battery value.** It was level 2 for all queries. Whether the receiver polls the controller afresh on the request or answers from a cache is unresolved. The state with power state 0 on turning off shows that state packets can reflect the controller's state (the receiver could not know the change itself), but it is no proof for the battery request. Test: battery request with the controller off (if a state packet still comes, it is a cache), later with a draining battery.
- How Steam treats the controller's brief loss (display, player order, running games).
- Behavior with several controllers on the same receiver (other slots should stay untouched, unchecked).

## 10. Further terminal measurements (2026-11-05): battery request without a capture

Only terminal output of `tools/probe_takeover.py --battery-request`, no usbmon capture. Two runs in a row, the controller's state not stated explicitly; from the order of the output it is **assumed** that it was off in the first run and on in the second.
- First run: request sent, **0 packets** back.
- Second run: state packet `00 00 00 13 A2` after 0.02 s (level 2, type 1, power state 2), then an empty packet.
- If the assumption holds, the receiver does **not answer from a cache**: with the controller off no state packet comes, with it on one does. That suggests the controller is polled on the request. It is still no proof of a changing value; that was level 2 for all queries.
- Battery according to the user: **2 AA NiMH**. Belonging to it: battery type raw 1. Other values (pack, mains) unobserved. With NiMH the voltage curve is flat; the protocol's four levels are therefore coarse.

System structure, confirmed: The receiver is called `1-3` in sysfs, `xpad` is bound to `1-3:1.0`, `1-3:1.2`, `1-3:1.4`, `1-3:1.6` (interfaces 1, 3, 5, 7 are audio and unbound). Besides that there is `1-4` (another device) and the root hubs `N-0:1.0`.
