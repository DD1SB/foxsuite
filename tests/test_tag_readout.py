import asyncio
import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foxlive.readout import (
    FileReadoutProvider,
    SimulatorReadoutProvider,
    capture,
    parse_readout,
    record,
    station_record,
)

UID = "046365525C6180"


def test_record_verified_layout_and_endianness() -> None:
    # Independently derived from RFIDManager::writeTimestampFile's shift operations.
    parsed = record({"file_id": 7, "data": "7856341221070001"})
    assert parsed.file_id == 7 and parsed.station_timestamp == 0x12345678
    assert parsed.event_id == 0x0721 and parsed.time_synchronized
    assert parsed.raw_bytes == bytes.fromhex("7856341221070001") and parsed.parse_status == "VALID"


@pytest.mark.parametrize(
    "data,status",
    [
        ("0000000000000000", "EMPTY"),
        ("0100000001000000", "VALID"),
        ("0100000001000101", "UNSUPPORTED_RECORD"),
        ("0100000001000002", "UNSUPPORTED_RECORD"),
        ("0102", "MALFORMED"),
        ("XYZ", "MALFORMED"),
    ],
)
def test_empty_malformed_reserved_sync(data: str, status: str) -> None:
    assert record({"file_id": 255, "data": data}).parse_status == status


@pytest.mark.parametrize("number", [-1, 256, "1", True, None])
def test_invalid_file_id_preserved(number: object) -> None:
    parsed = record({"file_id": number, "data": "00"})
    assert parsed.parse_status == "MALFORMED" and json.loads(parsed.raw_value)["file_id"] == number


@pytest.mark.parametrize("status", ["COMPLETE", "PARTIAL", "FAILED", "ABORTED"])
def test_completion_semantics(status: str) -> None:
    raw = capture(UID, [station_record(1, 1791280800, 1825)], status)
    readout = parse_readout(raw)
    assert readout.status == status and readout.raw_payload == raw
    assert readout.received_at.tzinfo == UTC


def test_partial_file_errors_do_not_discard_good_record() -> None:
    raw = capture(
        UID, [station_record(1, 1791280800, 1), {"file_id": 99, "data": None, "error": "removed"}]
    )
    readout = parse_readout(raw)
    assert readout.status == "PARTIAL" and len(readout.records) == 2
    assert readout.records[0].parse_status == "VALID" and readout.records[1].error == "removed"


@pytest.mark.parametrize(
    "raw",
    [
        b"garbage",
        b"\xff",
        b"[]",
        b'{"type":"tag_readout","version":2}',
        capture("bad!", []),
        capture(UID, [station_record(1, 1, 1)] * 2),
    ],
)
def test_bad_envelopes_retained(raw: bytes) -> None:
    result = parse_readout(raw)
    assert result.status == "FAILED" and result.raw_payload == raw and result.errors


def test_future_fields_empty_tag_and_providers(tmp_path: Path) -> None:
    raw = capture(UID, [])
    document = json.loads(raw) | {"future": "retained"}
    raw = json.dumps(document).encode()
    path = tmp_path / "tag.json"
    # test fixture files also use apply_patch-independent pytest-generated storage.
    path.write_bytes(raw)
    for provider in (FileReadoutProvider(path), SimulatorReadoutProvider(raw)):
        readout = asyncio.run(provider.read())
        assert readout.uid == UID and not readout.records and readout.status == "COMPLETE"
        assert b"future" in readout.raw_payload


def test_original_unsynchronized_timestamp_not_pc_time() -> None:
    raw = capture(UID, [{"file_id": 1, "data": struct.pack("<IHBB", 123456, 1825, 0, 0).hex()}])
    stamp = datetime(2026, 10, 6, tzinfo=UTC)
    result = parse_readout(raw, received_at=stamp)
    assert result.records[0].station_timestamp == 123456 and not result.records[0].time_synchronized


def test_naive_pc_time_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_readout(capture(UID, []), received_at=datetime(2026, 10, 6))
