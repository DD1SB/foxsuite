"""Current FoxIdent eight-byte DESFire captures; no reader or competition policy."""

import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from foxcore.protocol import normalize_uid


@dataclass(frozen=True)
class TagStationRecord:
    file_id: int | None
    raw_value: str
    raw_bytes: bytes | None
    station_timestamp: int | None
    event_id: int | None
    time_synchronized: bool | None
    parse_status: str
    error: str = ""


@dataclass(frozen=True)
class TagReadout:
    uid: str | None
    received_at: datetime
    provider: str
    reader: str | None
    raw_payload: bytes
    status: str
    records: tuple[TagStationRecord, ...]
    errors: tuple[str, ...]


def record(value: Any) -> TagStationRecord:
    raw_value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    file_id: int | None = None
    raw: bytes | None = None
    try:
        if not isinstance(value, dict):
            raise ValueError("Record must be an object")
        number = value.get("file_id")
        if type(number) is not int or not 0 <= number <= 255:
            raise ValueError("File ID must be an integer 0..255")
        file_id = number
        if value.get("error") or value.get("data") is None:
            raise ValueError(str(value.get("error") or "File read failed"))
        data = value["data"]
        if not isinstance(data, str):
            raise ValueError("File data must be hexadecimal")
        raw = bytes.fromhex(data)
        if len(raw) != 8:
            raise ValueError("Station file must contain exactly eight bytes")
        stamp, event, reserved, sync = struct.unpack("<IHBB", raw)
        status = "EMPTY" if raw == bytes(8) else "VALID"
        if reserved or sync not in (0, 1):
            status = "UNSUPPORTED_RECORD"
        return TagStationRecord(
            file_id, raw_value, raw, stamp, event, bool(sync) if sync in (0, 1) else None, status
        )
    except (ValueError, TypeError) as exc:
        return TagStationRecord(file_id, raw_value, raw, None, None, None, "MALFORMED", str(exc))


def parse_readout(
    raw: bytes, provider: str = "import", received_at: datetime | None = None
) -> TagReadout:
    received = received_at or datetime.now(UTC)
    if received.tzinfo is None:
        raise ValueError("PC readout time must be timezone-aware")
    uid: str | None = None
    reader: str | None = None
    records: tuple[TagStationRecord, ...] = ()
    try:
        if len(raw) > 1_048_576:
            raise ValueError("Readout exceeds 1 MiB")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Readout must be an object")
        if (
            data.get("type") != "tag_readout"
            or type(data.get("version")) is not int
            or data["version"] != 1
        ):
            raise ValueError("Unsupported readout contract version")
        if data.get("format") != "foxident-desfire-8":
            raise ValueError("Unsupported tag format")
        uid = normalize_uid(data["uid"])
        reader = str(data["reader"])[:200] if data.get("reader") else None
        items = data.get("records")
        if not isinstance(items, list) or len(items) > 256:
            raise ValueError("Readout requires at most 256 records")
        records = tuple(record(v) for v in items)
        status = data.get("status")
        if status not in {"COMPLETE", "PARTIAL", "FAILED", "ABORTED"}:
            raise ValueError("Invalid readout completion status")
        errors = data.get("errors", [])
        if not isinstance(errors, list) or not all(isinstance(e, str) for e in errors):
            raise ValueError("Readout errors must be strings")
        files = [r.file_id for r in records if r.file_id is not None]
        if len(files) != len(set(files)):
            raise ValueError("Repeated file ID in one snapshot")
        if status == "COMPLETE" and any(r.parse_status == "MALFORMED" for r in records):
            status = "PARTIAL"
        return TagReadout(
            uid, received.astimezone(UTC), provider, reader, raw, status, records, tuple(errors)
        )
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        return TagReadout(
            uid, received.astimezone(UTC), provider, reader, raw, "FAILED", records, (str(exc),)
        )


class TagReadoutProvider(Protocol):
    async def read(self) -> TagReadout: ...


class FileReadoutProvider:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def read(self) -> TagReadout:
        with self.path.open("rb") as stream:
            raw = stream.read(1_048_577)
        return parse_readout(raw, "file-import")


def capture(uid: str, records: list[dict[str, Any]], status: str = "COMPLETE") -> bytes:
    return json.dumps(
        {
            "type": "tag_readout",
            "version": 1,
            "format": "foxident-desfire-8",
            "uid": uid,
            "reader": "simulator",
            "status": status,
            "records": records,
            "errors": [],
        }
    ).encode()


def station_record(
    station: int, stamp: int, event_id: int, synchronized: bool = True
) -> dict[str, Any]:
    return {
        "file_id": station,
        "data": struct.pack("<IHBB", stamp, event_id, 0, int(synchronized)).hex().upper(),
    }


class SimulatorReadoutProvider:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    async def read(self) -> TagReadout:
        return parse_readout(self.raw, "simulator")
