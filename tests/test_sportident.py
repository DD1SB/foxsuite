import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foxbridge.sportident import (
    PunchTime,
    SportIdentEncoder,
    SportIdentPunch,
    card_bytes,
    control_bytes,
    crc,
    validate_frame,
)
from foxbridge.time import convert_time


def test_published_autosend_vector() -> None:
    vector = json.loads((Path(__file__).parent / "fixtures/sportident_vectors.json").read_text())
    assert crc(bytes.fromhex(vector["body"])) == int(vector["crc"], 16)
    punch = SportIdentPunch(
        vector["card_number"],
        vector["control_code"],
        PunchTime(vector["day_pm"], vector["half_day_seconds"], vector["subsecond"]),
        vector["backup_offset"],
    )
    assert SportIdentEncoder().encode_punch(punch) == bytes.fromhex(vector["frame"])
    validate_frame(bytes.fromhex(vector["frame"]))


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"", 0),
        (b"\xe0", 0),
        (b"\xe0\x00", 0xE000),
        (bytes.fromhex("D30D002C000BDF77270E8D27000B70"), 0xBE71),
    ],
)
def test_crc_vectors(raw: bytes, expected: int) -> None:
    assert crc(raw) == expected


@pytest.mark.parametrize(
    "card,raw",
    [
        (1, "00000001"),
        (65000, "0000FDE8"),
        (200001, "00020001"),
        (265000, "0002FDE8"),
        (300001, "00030001"),
        (400001, "00040001"),
        (500000, "0007A120"),
        (912345, "000DEBD9"),
        (8000000, "007A1200"),
        (0xFFFFFF, "00FFFFFF"),
    ],
)
def test_card_encoding(card: int, raw: str) -> None:
    assert card_bytes(card) == bytes.fromhex(raw)


@pytest.mark.parametrize("card", [0, -1, 65001, 100001, 199999, 299999, 499999, 0x1000000])
def test_invalid_cards(card: int) -> None:
    with pytest.raises(ValueError):
        card_bytes(card)


@pytest.mark.parametrize(
    "control,raw", [(1, b"\x00\x01"), (20, b"\x00\x14"), (254, b"\x00\xfe"), (1023, b"\x03\xff")]
)
def test_control_boundaries(control: int, raw: bytes) -> None:
    assert control_bytes(control) == raw


@pytest.mark.parametrize("control", [0, -1, 1024])
def test_invalid_controls(control: int) -> None:
    with pytest.raises(ValueError):
        control_bytes(control)


@pytest.mark.parametrize(
    "hour,ptd,seconds", [(0, 2, 0), (11, 2, 39600), (12, 3, 0), (23, 3, 39600)]
)
def test_am_pm(hour: int, ptd: int, seconds: int) -> None:
    stamp = int(datetime(2026, 10, 5, hour, tzinfo=UTC).timestamp())  # Monday
    assert convert_time(stamp, "UTC") == PunchTime(ptd, seconds)


def test_midnight_timezone_and_dst() -> None:
    first = int(datetime(2026, 10, 5, 21, 59, 59, tzinfo=UTC).timestamp())
    assert convert_time(first, "Europe/Berlin") == PunchTime(3, 43199)
    assert convert_time(first + 1, "Europe/Berlin") == PunchTime(4, 0)
    for hour in [0, 1]:  # Both 02:30 occurrences during fall-back.
        stamp = int(datetime(2026, 10, 25, hour, 30, tzinfo=UTC).timestamp())
        with pytest.raises(ValueError, match="ambiguous"):
            convert_time(stamp, "Europe/Berlin")
    before = int(datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC).timestamp())
    assert convert_time(before, "Europe/Berlin").half_day_seconds == 7199
    assert convert_time(before + 1, "Europe/Berlin").half_day_seconds == 10800


def test_frame_validation_and_determinism() -> None:
    encoder = SportIdentEncoder()
    punch = SportIdentPunch(912345, 31, PunchTime(2, 100))
    frame = encoder.encode_punch(punch)
    assert frame == encoder.encode_punch(punch)
    validate_frame(frame)
    for bad in [frame[:-1], b"\xff" + frame, frame[:-3] + b"\x00\x00\x03"]:
        with pytest.raises(ValueError):
            validate_frame(bad)
    for t in [PunchTime(14, 0), PunchTime(2, 43200), PunchTime(2, -1), PunchTime(2, 0, 256)]:
        with pytest.raises(ValueError):
            encoder.encode_punch(SportIdentPunch(912345, 31, t))
