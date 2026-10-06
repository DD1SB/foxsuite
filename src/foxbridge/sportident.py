"""Minimal extended D3 AUTOSEND encoder; no transport or competition semantics."""

from dataclasses import dataclass


def bounded_integer(value: int, minimum: int, maximum: int, name: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")


def crc(data: bytes) -> int:
    """SPORTident's polynomial remainder, including its special seed/padding convention.

    Independent polynomial-division implementation; see docs/SPORTIDENT.md for evidence.
    """
    if len(data) < 2:
        return 0
    if len(data) == 2:
        return int.from_bytes(data, "big")
    remainder = int.from_bytes(data + bytes(2 - len(data) % 2), "big")
    while remainder.bit_length() > 16:
        remainder ^= 0x18005 << (remainder.bit_length() - 17)
    return remainder


def card_bytes(number: int) -> bytes:
    bounded_integer(number, 1, 0xFFFFFF, "SI card number")
    if number >= 500000:
        return number.to_bytes(4, "big")
    if number <= 65000:
        return number.to_bytes(4, "big")
    series, short = divmod(number, 100000)
    if series not in {2, 3, 4} or not 1 <= short <= 65000:
        raise ValueError(f"Unsupported SI5 card number {number}")
    return bytes([0, series]) + short.to_bytes(2, "big")


def control_bytes(code: int) -> bytes:
    bounded_integer(code, 1, 1023, "SPORTident control code")
    return code.to_bytes(2, "big")


@dataclass(frozen=True)
class PunchTime:
    day_pm: int
    half_day_seconds: int
    subsecond: int = 0

    def to_bytes(self) -> bytes:
        bounded_integer(self.day_pm, 0, 63, "PTD")
        if ((self.day_pm >> 1) & 7) == 7:
            raise ValueError("PTD weekday must be Sunday..Saturday")
        bounded_integer(self.half_day_seconds, 0, 43199, "Half-day seconds")
        bounded_integer(self.subsecond, 0, 255, "Subsecond")
        return (
            bytes([self.day_pm])
            + self.half_day_seconds.to_bytes(2, "big")
            + bytes([self.subsecond])
        )


@dataclass(frozen=True)
class SportIdentPunch:
    card_number: int
    control_code: int
    time: PunchTime
    backup_offset: int = 0


def frame(command: int, payload: bytes) -> bytes:
    bounded_integer(command, 0x80, 0xFF, "Extended command")
    bounded_integer(len(payload), 0, 255, "Payload length")
    body = bytes([command, len(payload)]) + payload
    return b"\x02" + body + crc(body).to_bytes(2, "big") + b"\x03"


class SportIdentEncoder:
    def encode_punch(self, punch: SportIdentPunch) -> bytes:
        bounded_integer(punch.backup_offset, 0, 0xFFFFFF, "Backup offset")
        payload = (
            control_bytes(punch.control_code)
            + card_bytes(punch.card_number)
            + punch.time.to_bytes()
            + punch.backup_offset.to_bytes(3, "big")
        )
        return frame(0xD3, payload)


def validate_frame(data: bytes) -> None:
    """Validate a captured D3 frame for diagnostics, not a general SI decoder."""
    if len(data) != 19 or data[:3] != b"\x02\xd3\x0d" or data[-1] != 3:
        raise ValueError("Expected one 19-byte extended D3 AUTOSEND frame")
    if crc(data[1:-3]) != int.from_bytes(data[-3:-1], "big"):
        raise ValueError("SPORTident CRC mismatch")
