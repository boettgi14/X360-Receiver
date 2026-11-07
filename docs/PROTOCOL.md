# Protocol of the Xbox 360 Wireless Gaming Receiver

What is known about the receiver's USB protocol, with a confidence level for every statement:

- **[Source]** read in a source (Linux `xpad.c`, `argon.md` from x360-research, xboxdrv `PROTOCOL`), not checked on hardware
- **[Unit-tested]** matches sample packets from the sources in the unit tests, not checked on hardware
- **[Hardware]** observed on real hardware: a receiver `045E:0719`, one gamepad with 2 AA NiMH batteries, Bazzite with kernel 7.2. The raw captures are in `tests/fixtures/` and are replayed by the tests
- **[Hypothesis]** assumption, not confirmed

New findings from hardware replace hypotheses here. A statement that only comes from sources or unit tests is never presented as confirmed.

## 1. Device and interfaces

- USB IDs `045E:0291` and `045E:0719` [Source: argon.md]; xpad also knows `045E:02A9` as "Unofficial" [Source: xpad.c].
- A receiver has 4 slots. Each slot has one controller interface (class 0xFF, subclass 0x5D, protocol 0x81) and one audio interface (protocol 0x82) [Source: argon.md]. In sysfs the receiver was `1-3`, `xpad` was bound to `1-3:1.0`, `1.2`, `1.4`, `1.6`, and the audio interfaces 1, 3, 5, 7 had no driver [Hardware].
- Endpoints: controller 1 = IN 0x81 / OUT 0x01, controller 2 = 0x83 / 0x03, controller 3 = 0x85 / 0x05, controller 4 = 0x87 / 0x07. Audio sits on the even endpoint in between [Source: argon.md]. Controller 1 used 0x01/0x81 [Hardware].
- "Slot" is the order of connection at the receiver, not the player number (LED) [Source: argon.md].
- xpad binds only the controller interfaces (`XPAD_XBOX360_VENDOR_PROTOCOL(vend, 129)`) [Source: xpad.c].
- An IN packet is 28 or 29 bytes long [Source: xboxdrv]; usbmon delivers all 29 bytes [Hardware].

## 2. IN packets (receiver → host)

Header (5 bytes): `[0]` packet ID (0x00, 0x08 for a connection packet), `[1]` type, `[2]` unused (0x00), `[3..4]` header data.

| ID | Type | Content | Confidence |
|----|------|---------|------------|
| 0x08 | bits 0x80 / 0x40 of the type byte | Connection: 0x80 = controller present, 0x40 = headset present; two bytes long. `08 00` = nothing connected, `08 80` = controller connected | Source, Hardware |
| 0x00 | 0x00 | **State** in header bytes 3–4, valid only if `byte3 & 0xF0 == 0x10` | Source, Hardware |
| 0x00 | 0x01 / 0x03 | Input data (buttons, triggers, sticks) from offset 5. The state can also sit in the header bytes of an input packet | Source, Hardware |
| 0x00 | 0x05 | Capabilities (first data byte 0x12) | Source |
| 0x00 | 0x0F | **Link report**: device info on connecting (first data byte 0xCC) | Source, Hardware |
| 0x00 | 0xF8 | Unknown; see section 5 | Hardware (observed only) |

### State fields (byte 3 and byte 4)

```
Byte 3:  bits 0-1 vibrationLevel   bit 2 headset   bit 3 chatpad   bits 4-7 marker = 0x1
Byte 4:  bit 0 unknown   bits 1-2 batteryType   bit 3 onlyMic   bits 4-5 powerState   bits 6-7 batteryLevel
```

- The LSB-first bit order is an assumption from the C struct of the source; the decoded sample (`13 A2`: level 2, type 1, power state 2, vibration 3) is consistent with it [Hypothesis, consistent with Hardware].
- `batteryLevel` 0..3 corresponds to the four XInput levels (empty, low, medium, full). Only level 2 has been observed, so the mapping to the charge state is unverified [Hypothesis].
- `batteryType` raw 0..3. Observed: raw 1 with 2 AA NiMH batteries [Hardware]. The sources' examples: 0xE0 = type 0 (xboxdrv's author suspects "charging?"), 0xE2 = type 1, 0xE6 = type 3. Which value means which battery pack or wired power is unknown [Hypothesis].
- `powerState` raw 0..3. 2 while the controller is on, 0 after it has been turned off [Hardware]. 1 and 3 are unexplored.
- Bit 0 of byte 4 (unknown): set in the link report (`13 A3`), never in a state packet (`13 A2`) [Hardware]. Meaning unknown.

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

- Observed: subtype 0x01 (gamepad), protocol 0x1D20, revision 0x20 (the xboxdrv example has 0x05, so it varies) [Hardware].
- The source's formula for the vendor ID gives 0x50001 for the xboxdrv example, which is not plausible [Unit-tested]. The raw bytes are therefore kept and the formula is not used.
- Subtype names (gamepad, wheel, arcade stick, flight stick, dance pad, guitar, alternate guitar, drum kit, bass guitar, arcade pad) come from the XInput documentation and were not checked against it; only "gamepad" was observed [Hypothesis]. The English names are in `x360w.protocol.SUBTYPE_NAMES`; the UI shows translated names keyed by the subtype number (`src/i18n.ts`).

## 3. OUT commands (host → receiver), 12 bytes, on the slot's OUT endpoint

| Command | Bytes | Confidence |
|---------|-------|------------|
| Request status/presence | `08 00 0F C0 00…` | Source (xpad.c sends it when it binds); answered with a connection packet and a link report within 6–8 ms [Hardware] |
| Request battery status | `00 00 00 40 00…` | Source (argon.md); answered with a state packet after about 27 ms [Hardware] |
| Request capabilities | `00 00 02 80 00…` | Source (argon.md) |
| Set LED | `00 00 08 (0x40 + mode) 00…`, mode 0–15 | Source (xpad.c, argon.md); mode 10 and 2 observed [Hardware] |
| **Turn the controller off** | `00 00 08 C0 00…` | Source (xpad.c `xpad360w_poweroff_controller`, argon.md, xboxdrv); works [Hardware] |
| Rumble | `00 01 0F C0 00 large small 00…` | Source (xpad.c). The plugin vibrates through the kernel's force-feedback interface instead, which works [Hardware] |
| Enable chatpad | `00 00 0C 1B …` plus a keep-alive 0x1E/0x1F every second | Source (xboxdrv) |

LED modes according to xpad.c: 0 off, 1 all blink, 2–5 position 1–4 blinks then on, 6–9 position 1–4 on, 10 rotating, 11 blinking, 12 slow blinking, 13 rotating with two lights, 14 permanently slow all blinking, 15 blink once.

Power state: `0xC0 | state`, state 0 turns the controller off [Source: argon.md].

## 4. What the Linux kernel (xpad.c) uses of this

- Connection and disconnection (bit 0x08 in the first byte, controller bit 0x80 in the second) and input data (type 0x01) are evaluated.
- **State, link and capabilities packets are not evaluated.** There is no `power_supply` registration for the battery [Source: xpad.c].
- A controller is turned off only (a) after the Guide button has been held for 5 seconds (`XPAD360W_POWEROFF_TIMEOUT`) and (b) on system suspend if the module parameter `auto_poweroff` is set (default on, writable under `/sys/module/xpad/parameters/auto_poweroff`) [Source]. (a) and the effect of (b) were observed [Hardware].
- LEDs appear as `/sys/class/leds/xpadN/brightness`. A command 0–15 is written (`command %= 16`). The LED entry hangs on the USB device, not on the interface, so xpadN → slot cannot be read directly [Source]. With one receiver `xpad0` is controller 1, `xpad1` controller 2, and so on [Hardware]; the LED exists only while the controller is connected [Hardware].
- Rumble goes through the input device's normal force-feedback interface [Source]; the input device appears as `<interface>/input/inputN/eventM` while the controller is connected [Hardware].

## 5. Observations on hardware

### Connecting

- The sequence is reproducible: `08 00` (disconnected), LED command 0, `08 80` (connected), LED command 2, link report, then packets with header data `13 A2` (state), `00 20`, `13 A2`, `20 1D`, `30 03`, `40 01`, then permanently `F0 00`. The order of the first pieces varies between sessions, and the state sometimes arrives as the header of an input packet [Hardware].
- The pieces `00 20`, `13 A2`, `20 1D`, `30 03`, `40 01` match, in this order, the bytes in the body of the link report (`00 20 13 A3 20 1D 30 03 40 01 50 01`); they may be 2-byte pieces of the same record spread over the headers of following packets [Hypothesis, medium confidence].
- `xpad` sends LED command 0 when a controller disconnects and LED command 2 when it connects [Hardware].
- Input packets (type 0x01): button mask in the XInput layout (A 0x1000, B 0x2000, X 0x4000, Y 0x8000, LB 0x0100, RB 0x0200, L3 0x0040, R3 0x0080, D-pad 0x0001/0x0002/0x0004/0x0008, **Guide 0x0400**), triggers 0–255, sticks 16-bit signed. Every input packet is followed by an empty packet `00 00 00 F0` [Hardware]. Empty packets also occur without input.

### The battery is reported only on connecting

- After connecting, **no further state packet comes**: none in about 380 s of idle, none after LED commands, button presses (A, B, Guide) or re-binding `xpad` [Hardware]. So the receiver does not report the battery periodically.
- Re-binding `xpad` (presence request) yields the connection packet and a link report that is byte-identical to the one on a real connect, with a battery value in its state. Whether that value is fresh or a copy held by the receiver is unknown [Hardware, open].
- The only state packet in the middle of a session comes when the controller is turned off (power state 2 → 0) [Hardware].
- Consequence: a passive monitor cannot see the battery of a controller that was already connected. The plugin asks for it with the battery request (section 6).

### Turning off by xpad

`xpad` sends `00 00 08 C0` 5.056 s after the Guide press, at the next input packet (holding alone produces no packet; the release triggers it) [Hardware, matches xpad.c]. Then, measured from the command: a state packet with power state 0 (`13 82`) after 27 ms, `08 00` after 55 ms, LED command 0 from `xpad` after 63 ms. Switching the controller back on by hand gives the usual connection sequence [Hardware].

### Binding and unbinding `xpad`

Unbinding ends the reading URB with status −108; `xpad` still tries to send LED 0 (error −2). Binding sends the presence request `08 00 0F C0`; the receiver answers within 6 ms with `08 80` and a link report, and no state packet follows [Hardware].

### Packets `00 F8 01` / `00 F8 02`

They keep coming while a controller is connected: 50 of them in 393 s, strictly alternating (02, 01, 02, 01 …), every gap larger than 2.0 s and close to a multiple of about 2.1 s. Meaning unknown; a connection quality would be conceivable [Hardware, observed only; meaning is a guess].

## 6. Short access through libusb

The plugin claims one slot's interface for a few seconds, sends commands and releases it [Hardware, confirmed with `tools/probe_takeover.py` and from inside the plugin]:

- libusb detaches `xpad` automatically; `xpad` binds again about 2 s after the access and sends its own presence request and LED command 2. The slot delivers no input in that time; Steam copes with it.
- **Presence request** `08 00 0F C0`: answered with `08 80` and a link report within 8 ms. The link report carries the controller type.
- **Battery request** `00 00 00 40`: the answer is a state packet `00 00 00 13 A2` (level 2, type 1, power state 2) after 27 ms, followed by an empty packet. It is the way to get the battery on demand.
- **With the controller off the battery request gets no answer**, so the receiver does not answer from a cache. Whether the value changes as a battery drains is unknown: it was level 2 every time, and NiMH has a flat voltage curve [Hardware, open].
- **Turn off** `00 00 08 C0`: a state packet with power state 2 after 31 ms, one with power state 0 after 39 ms, `08 00` after 55 ms; the controller stays off until switched on by hand [Hardware].
- Read timeouts every 100 ms (URB status −2) are part of the procedure, not errors.

## 7. Open questions

- Mapping of the levels 0–3 to the charge state, and the battery type values for other packs (alkaline, rechargeable pack, wired).
- Power states 1 and 3; the unknown bit 0; the meaning of the `F8` packets and of the pieces in the headers.
- Whether a state packet in answer to the battery request is measured afresh as a battery drains.
- Behavior of other controller types (wheel, guitar, drums, dance pad), of a headset and of a chatpad; the hardware examples in the sources mostly come from third-party devices, and original Microsoft devices can differ.
- A host command for sync/pairing, slot assignment or radio quality: none was found, which does not mean there is none.
- Behavior with several controllers on one receiver (other slots should stay untouched while one is taken over) and with several receivers.
