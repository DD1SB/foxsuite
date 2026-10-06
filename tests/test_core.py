import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from foxcore.config import load_config
from foxcore.dedupe import duplicate_key
from foxcore.events import DiagnosticEvent, MalformedLineEvent, Message, TagEvent, UnknownJsonEvent
from foxcore.participants import ParticipantRepository
from foxcore.persistence import Store
from foxcore.protocol import format_uid, normalize, normalize_uid, parse_line
from foxcore.service import IngestService
from foxcore.simulator import messages
from foxcore.stations import Station, StationRepository

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "uid,expected",
    [
        ("04:a7:83:19:bc:de:12", "04A78319BCDE12"),
        ("04 a7", "04A7"),
        ("00-01", "0001"),
        ("010203040506070809", "010203040506070809"),
    ],
)
def test_uid(uid: str, expected: str) -> None:
    assert normalize_uid(uid) == expected
    assert normalize_uid(format_uid(uid)) == expected


@pytest.mark.parametrize("uid", ["", "0", "GG", "0x04", "04/AA"])
def test_invalid_uid(uid: str) -> None:
    with pytest.raises(ValueError):
        normalize_uid(uid)


def test_current_protocol() -> None:
    event = parse_line(messages()[0])
    assert isinstance(event, TagEvent)
    p = normalize(event, 1, NOW, "serial:COM4", False, "live")
    assert p is not None and p.uid == "04A78319BCDE12"
    assert p.station_timestamp == 1770000000 and p.sequence == 2
    assert p.received_at_pc is NOW
    event.payload.pop("callsign")
    event.payload.pop("rssi")
    event.payload["future"] = 123
    p = normalize(event, 1, NOW, "test", False, "live")
    assert p is not None and p.callsign is None and p.rssi is None


@pytest.mark.parametrize("raw", [b"{broken", b"\xff\n", b'{"type":"tag",broken\n'])
def test_malformed(raw: bytes) -> None:
    assert isinstance(parse_line(raw), MalformedLineEvent)


def test_diagnostic_unknown_text() -> None:
    for raw in messages()[4:]:
        assert isinstance(parse_line(raw), DiagnosticEvent)
    assert isinstance(parse_line(b'{"type":"future","foo":1}'), UnknownJsonEvent)
    assert isinstance(parse_line(b"[]"), UnknownJsonEvent)
    assert parse_line(b"[BASE] LoRa ready\r\n").status == "text"


def test_persistence_dedupe_restart_migrations(tmp_path: Path) -> None:
    path = tmp_path / "core.db"
    store = Store(path)
    service = IngestService(store)
    first = service.ingest(messages()[0], "base", NOW)
    second = service.ingest(messages()[1], "base", NOW + timedelta(seconds=1))
    assert first and second and not first.duplicate and second.duplicate
    assert second.duplicate_of == first.id
    assert duplicate_key(first) == duplicate_key(second)
    later = parse_line(messages()[0])
    later.payload["sequence"] = 3
    import json

    third = service.ingest(json.dumps(later.payload).encode(), "base", NOW)
    assert third and not third.duplicate
    later.payload["sequence"] = 2
    later.payload["timestamp"] += 30
    fourth = service.ingest(json.dumps(later.payload).encode(), "base", NOW)
    assert fourth and not fourth.duplicate
    assert duplicate_key(first) != duplicate_key(replace(first, sequence=0))
    assert duplicate_key(first) != duplicate_key(replace(first, station_timestamp=1))
    store.close()
    store = Store(path)
    assert store.version == 1
    assert store.stats()["raw_events"] == 4
    assert store.stats()["duplicates"] == 1
    assert IngestService(store).ingest(messages()[0], "base", NOW).duplicate  # type: ignore[union-attr]
    assert len(store.db.execute("SELECT * FROM schema_migrations").fetchall()) == 1
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_raw_first_failure_and_recovery(tmp_path: Path) -> None:
    store = Store(tmp_path / "core.db")

    def broken(raw: bytes) -> Message:
        raise RuntimeError("parser bug")

    IngestService(store, broken).ingest(b"\xff\n", "test", NOW)
    assert store.raw_events()[0].raw_bytes == b"\xff\n"
    assert store.db.execute("SELECT parse_status FROM raw_events").fetchone()[0] == "failed"
    store.insert_raw(messages()[0], NOW, "test")
    IngestService(store).recover()
    assert store.stats()["punches"] == 1
    assert store.stats()["pending"] == 0
    store.close()


def test_subscriber_failure_invalid_uid_and_unknown_retained(tmp_path: Path) -> None:
    store = Store(tmp_path / "core.db")
    service = IngestService(store)
    seen: list[int] = []

    def bad(_: object) -> None:
        raise RuntimeError("subscriber bug")

    service.subscribe(bad)
    service.subscribe(lambda p: seen.append(p.raw_event_id))
    for raw in messages():
        service.ingest(raw, "test", NOW)
    service.ingest(messages()[0].replace(b"04A78319BCDE12", b"ZZ"), "test", NOW)
    assert len(seen) == 2
    assert store.stats()["raw_events"] == 8
    assert store.stats()["punches"] == 2
    store.close()


def test_finish_failure_preserves_pending_raw(tmp_path: Path) -> None:
    store = Store(tmp_path / "core.db")
    store.db.execute(
        "CREATE TRIGGER fail_punch BEFORE INSERT ON punches "
        "BEGIN SELECT RAISE(ABORT,'injected disk failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        IngestService(store).ingest(messages()[0], "test", NOW)
    assert store.stats()["raw_events"] == 1
    assert store.stats()["pending"] == 1
    store.db.execute("DROP TRIGGER fail_punch")
    IngestService(store).recover()
    assert store.stats()["punches"] == 1
    store.close()


def test_mappings(tmp_path: Path) -> None:
    store = Store(tmp_path / "core.db")
    people = ParticipantRepository(store)
    person = people.add("Runner")
    people.assign_uid("04:aa", person.id)
    assert people.find_by_uid("04AA") == person
    assert people.find_by_uid("00") is None
    stations = StationRepository(store)
    stations.put(Station(1, "Start", "DD1SB"))
    assert stations.get(1) == Station(1, "Start", "DD1SB")
    assert stations.get(2) is None
    store.close()


def test_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[serial]\nport="COM9"\n[database]\npath="local.db"\n')
    cfg = load_config(path)
    assert cfg.serial.port == "COM9" and cfg.serial.baud_rate == 115200
    assert cfg.database_path == tmp_path / "local.db"
    path.write_text("[serial]\nreconnect_interval_seconds=0\n")
    with pytest.raises(ValueError):
        load_config(path)
