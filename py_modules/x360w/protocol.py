"""Decoder and encoder for the protocol of the Xbox 360 Wireless Gaming Receiver.

Sources (see docs/PROTOCOL.md for details and confidence levels):
  - x360-research (InvoxiPlayGames): hardware/usb-protocols/argon.md
  - xboxdrv: PROTOCOL
  - Linux kernel: drivers/input/joystick/xpad.c

Everything in this module works on raw bytes. There is no USB access.
The bit-field order (LSB first) is an assumption from the source's C struct
and is only partly confirmed on hardware (see docs/PROTOCOL.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Union


class BatteryLevel(IntEnum):
    """Four levels like XInput (BATTERY_LEVEL_*). The mapping of 0..3 is assumed."""

    EMPTY = 0
    LOW = 1
    MEDIUM = 2
    FULL = 3


# XInput subtypes according to the Microsoft documentation (XINPUT_CAPABILITIES.SubType).
# Unverified: taken from the XInput documentation without a check (see docs/PROTOCOL.md).
# The names are English; the frontend shows translated names keyed by subtype number.
SUBTYPE_NAMES = {
    0x01: "Gamepad",
    0x02: "Wheel",
    0x03: "Arcade Stick",
    0x04: "Flight Stick",
    0x05: "Dance Pad",
    0x06: "Guitar",
    0x07: "Guitar (alternate)",
    0x08: "Drum Kit",
    0x0B: "Guitar (bass)",
    0x13: "Arcade Pad",
}

HEADER_LEN = 5


@dataclass(frozen=True)
class ConnectionEvent:
    """Packet ID 0x08: connection status of the slot."""

    controller: bool
    headset: bool


@dataclass(frozen=True)
class StateReport:
    """Type 0x00 with marker 0x1 in the upper nibble of byte 3: state of the controller."""

    vibration_level: int  # 0..3
    headset: bool
    chatpad: bool
    battery_type: int  # raw 0..3, meaning still to be clarified
    only_mic: bool
    power_state: int  # raw 0..3
    battery_level: BatteryLevel
    unknown_bit: int = 0


@dataclass(frozen=True)
class InputReport:
    """Type 0x01 or 0x03: input data (buttons, sticks)."""

    buttons: int
    left_trigger: int
    right_trigger: int
    left_stick_x: int
    left_stick_y: int
    right_stick_x: int
    right_stick_y: int
    # The two header data bytes can also carry a state in input packets
    # (seen on hardware: first packet after connecting, header 13 A2).
    state: Optional["StateReport"] = None


@dataclass(frozen=True)
class CapabilitiesReport:
    """Type 0x05: capabilities (XInput capabilities structure)."""

    buttons: int
    left_motor: int
    right_motor: int
    raw: bytes = b""


@dataclass(frozen=True)
class LinkReport:
    """Type 0x0F: device information on connecting."""

    device_id: int
    device_type: int
    revision: int
    state: Optional[StateReport]
    protocol: int
    vendor_id_data: bytes
    vendor_id_guess: int  # formula from the source, unchecked
    subtype: int
    raw: bytes = b""

    @property
    def subtype_name(self) -> str:
        return SUBTYPE_NAMES.get(self.subtype, f"Unknown (0x{self.subtype:02X})")


@dataclass(frozen=True)
class UnknownReport:
    packet_id: int
    packet_type: int
    raw: bytes = field(default=b"", repr=False)


Report = Union[
    ConnectionEvent,
    StateReport,
    InputReport,
    CapabilitiesReport,
    LinkReport,
    UnknownReport,
]


def _s16(lo: int, hi: int) -> int:
    value = lo | (hi << 8)
    return value - 0x10000 if value & 0x8000 else value


def _decode_state_bytes(b0: int, b1: int) -> Optional[StateReport]:
    """Decodes the two state bytes. Valid only if the upper nibble of b0 == 0x1."""
    if (b0 & 0xF0) != 0x10:
        return None
    return StateReport(
        vibration_level=b0 & 0x03,
        headset=bool(b0 & 0x04),
        chatpad=bool(b0 & 0x08),
        unknown_bit=b1 & 0x01,
        battery_type=(b1 >> 1) & 0x03,
        only_mic=bool((b1 >> 3) & 0x01),
        power_state=(b1 >> 4) & 0x03,
        battery_level=BatteryLevel((b1 >> 6) & 0x03),
    )


def decode_in_packet(data: bytes) -> Optional[Report]:
    """Decodes an IN packet from the receiver. Returns None if it is too short."""
    if len(data) < 2:
        return None

    packet_id, packet_type = data[0], data[1]

    # Connection packet: ID 0x08, data in the "type" byte
    if packet_id == 0x08:
        return ConnectionEvent(
            controller=bool(packet_type & 0x80),
            headset=bool(packet_type & 0x40),
        )

    if len(data) < HEADER_LEN:
        return UnknownReport(packet_id, packet_type, bytes(data))

    if packet_id == 0x00:
        if packet_type == 0x00:
            state = _decode_state_bytes(data[3], data[4])
            if state is not None:
                return state
            return UnknownReport(packet_id, packet_type, bytes(data))

        if packet_type in (0x01, 0x03):
            body = data[HEADER_LEN:]
            if len(body) >= 13:
                return InputReport(
                    buttons=body[1] | (body[2] << 8),
                    left_trigger=body[3],
                    right_trigger=body[4],
                    left_stick_x=_s16(body[5], body[6]),
                    left_stick_y=_s16(body[7], body[8]),
                    right_stick_x=_s16(body[9], body[10]),
                    right_stick_y=_s16(body[11], body[12]),
                    state=_decode_state_bytes(data[3], data[4]),
                )

        if packet_type == 0x05:
            body = data[HEADER_LEN:]
            if len(body) >= 15 and body[0] == 0x12:
                return CapabilitiesReport(
                    buttons=body[1] | (body[2] << 8),
                    left_motor=body[13],
                    right_motor=body[14],
                    raw=bytes(body),
                )

        if packet_type == 0x0F:
            body = data[HEADER_LEN:]
            if len(body) >= 24 and body[0] == 0xCC:
                vendor_data = bytes(body[17:20])
                vendor_guess = (
                    (((vendor_data[0] & 0x0F) | (vendor_data[2] << 4)) << 8)
                    | vendor_data[1]
                )
                return LinkReport(
                    device_id=int.from_bytes(body[5:9], "little"),
                    device_type=body[9],
                    revision=body[10],
                    state=_decode_state_bytes(body[11], body[12]),
                    protocol=body[13] | (body[14] << 8),
                    vendor_id_data=vendor_data,
                    vendor_id_guess=vendor_guess,
                    subtype=body[20],
                    raw=bytes(body),
                )

    return UnknownReport(packet_id, packet_type, bytes(data))


# ---------------------------------------------------------------------------
# Output commands (OUT endpoint of the respective slot), 12 bytes each.
# Sending requires exclusive USB access, see docs/DESIGN.md.
# ---------------------------------------------------------------------------


def _out(b2: int, b3: int, b1: int = 0x00, b0: int = 0x00) -> bytes:
    return bytes([b0, b1, b2, b3]) + bytes(8)


def build_status_request() -> bytes:
    """Requests the connection status (triggers new connection/link packets)."""
    return bytes([0x08, 0x00, 0x0F, 0xC0]) + bytes(8)


def build_battery_request() -> bytes:
    return _out(0x00, 0x40)


def build_capabilities_request() -> bytes:
    return _out(0x02, 0x80)


def build_led(mode: int) -> bytes:
    """LED mode 0..15 (0 off, 2..5 player 1..4 blinking, 6..9 steady)."""
    if not 0 <= mode <= 15:
        raise ValueError("LED mode must be between 0 and 15")
    return _out(0x08, 0x40 + mode)


def build_poweroff() -> bytes:
    """Turns the controller off (power state 0)."""
    return _out(0x08, 0xC0)


def build_rumble(left: int, right: int) -> bytes:
    """Rumble: left = large mass (strong), right = small mass (weak), each 0..255."""
    if not (0 <= left <= 255 and 0 <= right <= 255):
        raise ValueError("Rumble values must be between 0 and 255")
    return bytes([0x00, 0x01, 0x0F, 0xC0, 0x00, left, right]) + bytes(5)
