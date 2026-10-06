import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from foxcore.persistence import MIGRATIONS, Store
from foxcore.service import IngestService
from foxlive import csvio
from foxlive.models import (
    CategoryData,
    EntryData,
    EventData,
    Role,
    State,
    StationData,
    Timing,
    instant,
)
from foxlive.models import CompetitionStatus as CS
from foxlive.persistence import LiveRepository
from foxlive.service import LiveService

STAMP = 1791280800
UID = "046365525C6180"


def setup(
    path: Path, timing: Timing = Timing.PUNCH_START_FINISH
) -> tuple[Store, LiveService, IngestService, int, int]:
    store = Store(path)
    live = LiveService(LiveRepository(store))
    event = live.put_event(
        EventData(
            name="Herbstlauf",
            date="2026-10-06",
            timezone="Europe/Berlin",
            timing_mode=timing,
            default_start_at=datetime.fromtimestamp(STAMP, UTC).isoformat()
            if timing == Timing.PREDEFINED_START
            else None,
        )
    )
    category = live.put_category(event.id, CategoryData(code="OPEN", display_name="Open"))
    entry = live.put_entry(
        event.id,
        EntryData(
            start_number=1, first_name="Max", last_name="Müller", category_id=category.id, uid=UID
        ),
    )
    for station, role in [
        (1, Role.CONTROL),
        (2, Role.CONTROL),
        (10, Role.START),
        (11, Role.FINISH),
    ]:
        live.put_station(
            event.id, StationData(station_id=station, display_name=str(station), role=role)
        )
    live.transition(event.id, State.RUNNING)
    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    return store, live, ingest, event.id, entry.id


def punch(
    ingest: IngestService, station: int, offset: int, sequence: int = 1, uid: str = UID
) -> int:
    raw = json.dumps(
        {
            "type": "tag",
            "station": station,
            "timestamp": STAMP + offset,
            "sequence": sequence,
            "uid": uid,
            "callsign": "DD1SB",
            "rssi": -70,
        }
    ).encode()
    event = ingest.ingest(raw, "serial:FAKE", datetime.fromtimestamp(STAMP + offset, UTC))
    assert event is not None and event.id is not None
    return event.id


def statuses(live: LiveService, event: int) -> list[str]:
    return [
        r[0]
        for r in live.repo.db.execute(
            "SELECT status FROM live_punch_interpretations WHERE event_id=? ORDER BY punch_id",
            (event,),
        )
    ]


def test_timing_controls_repeats_and_source_immutability(tmp_path: Path) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "timing.db")
    for station, seconds, sequence in [
        (1, -1, 1),
        (11, -1, 2),
        (10, 0, 3),
        (10, 1, 4),
        (1, 2, 5),
        (1, 3, 6),
        (2, 4, 7),
        (11, 5, 8),
        (11, 6, 9),
        (2, 7, 10),
    ]:
        punch(ingest, station, seconds, sequence)
    punch(ingest, 1, 2, 5)  # Exact transport retry, not a revisit.
    assert statuses(live, event) == [
        "INVALID_FOR_TIMING",
        "INVALID_FOR_TIMING",
        "VALID_START",
        "REPEAT_START",
        "VALID_CONTROL",
        "REPEAT_CONTROL",
        "VALID_CONTROL",
        "VALID_FINISH",
        "REPEAT_FINISH",
        "INVALID_FOR_TIMING",
        "SOURCE_DUPLICATE",
    ]
    result = live.repo.results(event)[0]
    assert (
        result.controls == 2
        and result.elapsed == 5
        and result.rank == 1
        and result.status == CS.FINISHED
    )
    source = [tuple(r) for r in store.db.execute("SELECT * FROM punches ORDER BY id")]
    raw = store.raw_events()
    before = live.snapshot(event)["results"]
    assert live.recalculate(event) == live.recalculate(event)
    assert before == live.snapshot(event)["results"]
    assert source == [tuple(r) for r in store.db.execute("SELECT * FROM punches ORDER BY id")]
    assert raw == store.raw_events()
    store.close()


def test_unknown_uid_assignment_and_category_change(tmp_path: Path) -> None:
    store, live, ingest, event, entry_id = setup(tmp_path / "unknown.db", Timing.PREDEFINED_START)
    source_id = punch(ingest, 1, 1, uid="04AA")
    assert statuses(live, event) == ["UNKNOWN_UID"]
    assert live.snapshot(event)["unknown"][0]["id"] == source_id
    entry = live.repo.entries(event)[0]
    data = EntryData.model_validate(
        entry.model_dump(exclude={"id", "event_id", "created_at", "updated_at"})
    )
    live.put_entry(event, data.model_copy(update={"uid": "04AA"}), entry_id)
    assert statuses(live, event) == ["VALID_CONTROL"]
    assert live.repo.results(event)[0].controls == 1 and live.snapshot(event)["unknown"] == []
    second = live.put_category(event, CategoryData(code="M40", display_name="M40"))
    live.put_entry(
        event, data.model_copy(update={"uid": "04AA", "category_id": second.id}), entry_id
    )
    assert live.repo.results(event)[0].category_id == second.id
    assert store.stats()["punches"] == 1 and store.stats()["raw_events"] == 1
    assert any("participant_uid_category_status" in a["action"] for a in live.repo.audit(event))
    store.close()


def test_lifecycle_uniqueness_close_archive_and_window(tmp_path: Path) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "lifecycle.db", Timing.PREDEFINED_START)
    other = live.put_event(EventData(name="Next", date="2026-10-07"))
    with pytest.raises(ValueError, match="another event"):
        live.transition(other.id, State.RUNNING)
    current = live.repo.event(event)
    data = EventData.model_validate(
        current.model_dump(exclude={"id", "state", "cursor", "created_at", "updated_at"})
    )
    live.put_event(
        data.model_copy(
            update={"competition_end_at": datetime.fromtimestamp(STAMP + 5, UTC).isoformat()}
        ),
        event,
    )
    punch(ingest, 1, 6)
    assert statuses(live, event) == ["OUTSIDE_EVENT_WINDOW"]
    live.transition(event, State.CLOSED)
    punch(ingest, 1, 2, 2)
    assert len(statuses(live, event)) == 1
    live.recalculate(event)
    assert live.repo.audit(event)[0]["action"] == "after_close:recalculate"
    live.transition(event, State.ARCHIVED)
    with pytest.raises(ValueError, match="read-only"):
        live.put_event(data, event)
    with pytest.raises(ValueError, match="read-only"):
        live.recalculate(event)
    assert live.repo.event(event).state == State.ARCHIVED
    store.close()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unknown", "UNKNOWN_STATION"),
        ("disabled", "DISABLED_STATION"),
        ("invalid", "INVALID_TIMESTAMP"),
    ],
)
def test_bad_station_and_timestamp(tmp_path: Path, case: str, expected: str) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "bad.db", Timing.PREDEFINED_START)
    if case == "disabled":
        live.put_station(
            event,
            StationData(station_id=7, display_name="Disabled", role=Role.CONTROL, enabled=False),
        )
    punch(ingest, 7, -STAMP if case == "invalid" else 1)
    assert statuses(live, event) == [expected]
    punch(ingest, 1, 2)
    assert live.repo.results(event)[0].controls == 1
    store.close()


def test_exclusion_and_manual_status(tmp_path: Path) -> None:
    store, live, ingest, event, entry_id = setup(tmp_path / "exclude.db", Timing.PREDEFINED_START)
    source_id = punch(ingest, 1, 1)
    with pytest.raises(ValueError, match="reason"):
        live.exclude(event, source_id, " ")
    live.exclude(event, source_id, "Wrong tag handed to runner")
    assert statuses(live, event) == ["MANUALLY_EXCLUDED"]
    assert live.repo.results(event)[0].controls == 0
    assert store.get_punch(source_id).station_timestamp == STAMP + 1
    data = EntryData.model_validate(
        live.repo.entries(event)[0].model_dump(
            exclude={"id", "event_id", "created_at", "updated_at"}
        )
    )
    live.put_entry(event, data.model_copy(update={"manual_status": CS.DSQ}), entry_id)
    assert live.repo.results(event)[0].status == CS.DSQ
    assert live.repo.results(event)[0].rank is None
    store.close()


def test_predefined_specific_default_missing_and_midnight(tmp_path: Path) -> None:
    store, live, ingest, event, entry_id = setup(
        tmp_path / "predefined.db", Timing.PREDEFINED_START
    )
    data = EntryData.model_validate(
        live.repo.entries(event)[0].model_dump(
            exclude={"id", "event_id", "created_at", "updated_at"}
        )
    )
    live.put_entry(
        event,
        data.model_copy(
            update={"start_time": datetime.fromtimestamp(STAMP - 86400, UTC).isoformat()}
        ),
        entry_id,
    )
    punch(ingest, 11, 10)
    assert live.repo.results(event)[0].elapsed == 86410
    live.put_entry(event, data, entry_id)
    assert live.repo.results(event)[0].elapsed == 10
    config = EventData.model_validate(
        live.repo.event(event).model_dump(
            exclude={"id", "state", "cursor", "created_at", "updated_at"}
        )
    )
    live.put_event(config.model_copy(update={"default_start_at": None}), event)
    assert statuses(live, event) == ["INVALID_FOR_TIMING"]
    assert live.repo.results(event)[0].elapsed is None
    store.close()


def test_csv_atomic_unique_entries_and_export(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "csv.db")
    bad = "start_number,first_name,last_name,category,uid\n2,Anna,Meyer,OPEN,04AA\n3,John,Smith,OPEN,04AA\n"
    summary = csvio.preview(live, event, bad)
    assert not summary["valid"] and summary["errors"][0]["row"] == 3
    assert not csvio.import_participants(live, event, bad)["valid"]
    assert len(live.repo.entries(event)) == 1
    good = bad.replace("3,John,Smith,OPEN,04AA", "3,John,Smith,OPEN,04BB")
    assert csvio.import_participants(live, event, good)["count"] == 2
    assert "Müller" in csvio.export(live, event)
    assert "rank,start_number" in csvio.export(live, event, True)
    with pytest.raises(ValueError, match="already assigned"):
        live.put_entry(
            event,
            EntryData(
                start_number=4,
                first_name="B",
                last_name="C",
                category_id=live.repo.categories(event)[0].id,
                uid="04AA",
            ),
        )
    store.close()


def test_restart_cursor_recovery_and_explicit_history(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    store, live, ingest, event, _ = setup(path, Timing.PREDEFINED_START)
    punch(ingest, 1, 1)
    original = live.repo.results(event)[0]
    core_only = IngestService(store)
    missed = punch(core_only, 2, 2)
    store.close()
    store = Store(path)
    messages: list[str] = []
    live = LiveService(
        LiveRepository(store), publish=lambda kind, _id, _payload: messages.append(kind)
    )
    live.recover()
    assert messages == [] and live.repo.running() is not None
    assert live.repo.results(event)[0].controls == 2
    assert store.stats()["punches"] == 2
    live.associate(event, [missed, missed])
    assert len(live.repo.punches(event)) == 2
    assert original.controls == 1
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_v2_migration_preserves_m1_m2(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    with patch("foxcore.persistence.MIGRATIONS", MIGRATIONS[:2]):
        store = Store(path)
        source_id = punch(IngestService(store), 1, 1)
        raw = store.raw_events()
        source = store.get_punch(source_id)
        assert store.version == 2
        store.close()
    store = Store(path)
    assert store.version == 3 and store.raw_events() == raw and store.get_punch(source_id) == source
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_dst_local_configuration() -> None:
    assert instant("2026-10-06T13:00:00", "Europe/Berlin") == "2026-10-06T11:00:00+00:00"
    for local in ["2026-10-25T02:30:00", "2026-03-29T02:30:00"]:
        with pytest.raises(ValueError, match="ambiguous or nonexistent"):
            instant(local, "Europe/Berlin")
    assert instant("2026-10-25T02:30:00+02:00", "Europe/Berlin") != instant(
        "2026-10-25T02:30:00+01:00", "Europe/Berlin"
    )


def test_earliest_times_not_arrival_order_and_predefined_start_marker(tmp_path: Path) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "earliest.db")
    punch(ingest, 11, 10)
    punch(ingest, 10, 1)
    punch(ingest, 10, 0, 2)
    assert live.repo.results(event)[0].elapsed == 10
    assert statuses(live, event) == ["VALID_FINISH", "REPEAT_START", "VALID_START"]
    store.close()


def test_sporting_ties_and_statuses() -> None:
    from foxlive.models import Result
    from foxlive.scoring import DistinctControlsThenTime

    results = [
        Result(
            participant_id=i,
            category_id=1,
            start_number=10 - i,
            controls=c,
            elapsed=t,
            start=100,
            finish=100 + t,
            status=CS.FINISHED,
        )
        for i, c, t in [(1, 8, 100), (2, 7, 90), (3, 7, 90), (4, 6, 20)]
    ]
    ranked = DistinctControlsThenTime().calculate(results)
    assert [r.rank for r in ranked] == [1, 2, 2, 4]
    assert [r.participant_id for r in ranked] == [1, 3, 2, 4]
    assert all(r.rank is None for r in results)  # Pure strategy, input unchanged.
    for status in (CS.RUNNING, CS.DNS, CS.DNF, CS.DSQ, CS.REGISTERED):
        unranked = DistinctControlsThenTime().calculate(
            [results[0].model_copy(update={"status": status})]
        )
        assert unranked[0].rank is None
    other = results[3].model_copy(update={"category_id": 2})
    assert (
        next(
            r
            for r in DistinctControlsThenTime().calculate(results[:3] + [other])
            if r.category_id == 2
        ).rank
        == 1
    )
