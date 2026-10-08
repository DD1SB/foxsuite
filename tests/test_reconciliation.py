import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_live_domain import STAMP, UID, punch, setup

from foxcore.persistence import MIGRATIONS, Store
from foxlive.evidence import DecisionInput
from foxlive.models import EventData, State, Timing
from foxlive.persistence import LiveRepository
from foxlive.readout import capture, station_record
from foxlive.service import LiveService


def configured(
    tmp_path: Path, timing: Timing = Timing.PREDEFINED_START
) -> tuple[Store, LiveService, int, int]:
    store, live, _, event, participant = setup(tmp_path / "evidence.db", timing)
    current = live.repo.event(event)
    data = current.model_dump(include=set(EventData.model_fields))

    live.put_event(EventData.model_validate(data | {"tag_event_id": 1825}), event)
    return store, live, event, participant


def import_tag(
    live: LiveService,
    event: int,
    records: list[dict[str, object]],
    uid: str = UID,
    status: str = "COMPLETE",
) -> dict[str, Any]:
    return live.evidence.import_raw(event, capture(uid, records, status))


def decision(
    live: LiveService, event: int, participant: int, station: int, action: str, **fields: object
) -> dict[str, object]:
    return live.evidence.decide(
        event,
        DecisionInput.model_validate(
            {
                "participant_id": participant,
                "station_id": station,
                "action": action,
                "reason": "confirmed by marshal",
                **fields,
            }
        ),
    )


def test_recover_missing_live_controls_and_explain(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    punch(ingest, 1, 10)
    punch(ingest, 11, 60, 2)
    before = [tuple(r) for r in store.db.execute("SELECT * FROM punches")]
    session = import_tag(
        live, event, [station_record(1, STAMP + 10, 1825), station_record(2, STAMP + 20, 1825)]
    )
    result = live.repo.results(event)[0]
    assert result.controls == 2 and result.elapsed == 60 and result.rank == 1
    assert result.recovered_controls == 1 and result.completeness == "COMPLETE"
    rows = live.evidence.resolutions(event, participant)
    assert [r.status for r in rows] == ["MATCHED", "TAG_ONLY_RECOVERED", "LIVE_ONLY"]
    assert rows[1].accepted[0].source_type == "TAG_READOUT"
    assert session["summary"]["recovered"] == 1
    assert [tuple(r) for r in store.db.execute("SELECT * FROM punches")] == before
    original = live.snapshot(event)["results"]
    live.recalculate(event)
    assert live.snapshot(event)["results"] == original
    store.close()


@pytest.mark.parametrize(
    "tag_offset,expected", [(10, "MATCHED"), (12, "CONFLICT"), (20, "TAG_CONFIRMED_LIVE")]
)
def test_matching_revisit_vs_conflict(tmp_path: Path, tag_offset: int, expected: str) -> None:
    store, live, event, _ = configured(tmp_path)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    punch(ingest, 1, 10)
    if tag_offset == 20:
        punch(ingest, 1, 20, 2)
    import_tag(live, event, [station_record(1, STAMP + tag_offset, 1825)])
    assert live.evidence.resolutions(event)[0].status == expected
    assert live.repo.results(event)[0].controls == 1
    assert bool(live.evidence.reviews(event)) == (expected == "CONFLICT")
    store.close()


@pytest.mark.parametrize(
    "records,expected",
    [
        ([station_record(1, STAMP + 10, 99)], "WRONG_EVENT"),
        ([station_record(1, STAMP + 10, 1825, False)], "UNSYNC_TAG_TIME"),
        ([station_record(1, 3, 1825)], "INVALID_TIMESTAMP"),
        ([{"file_id": 1, "data": "BAD"}], "MALFORMED"),
        ([station_record(99, STAMP + 10, 1825)], "UNKNOWN_STATION"),
    ],
)
def test_invalid_evidence_preserved_not_scored(
    tmp_path: Path, records: list[dict[str, object]], expected: str
) -> None:
    store, live, event, _ = configured(tmp_path)
    import_tag(live, event, records)
    assert live.repo.results(event)[0].controls == 0
    assert any(
        expected in r.issues or r.status == expected for r in live.evidence.resolutions(event)
    )
    assert live.evidence.reviews(event)
    assert store.db.execute("SELECT COUNT(*) FROM tag_readout_records").fetchone()[0] == 1
    store.close()


def test_snapshots_preserved_changed_repeats_idempotent(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path)
    record = station_record(1, STAMP + 10, 1825)
    for _ in range(3):
        import_tag(live, event, [record])
    assert live.repo.results(event)[0].controls == 1
    assert store.db.execute("SELECT COUNT(*) FROM tag_readout_sessions").fetchone()[0] == 3
    import_tag(
        live, event, [station_record(1, STAMP + 20, 1825), station_record(2, STAMP + 30, 1825)]
    )
    assert live.repo.results(event)[0].controls == 2
    assert live.evidence.resolutions(event)[0].accepted[0].station_timestamp == STAMP + 20
    for table in ["tag_readout_sessions", "tag_readout_records"]:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.db.execute(f"DELETE FROM {table}")
    store.close()


@pytest.mark.parametrize("timing", [Timing.PUNCH_START_FINISH, Timing.PREDEFINED_START])
def test_tag_timing_recovery_and_finish_before_start(tmp_path: Path, timing: Timing) -> None:
    store, live, event, _ = configured(tmp_path, timing)
    import_tag(
        live,
        event,
        [
            station_record(10, STAMP, 1825),
            station_record(1, STAMP + 1, 1825),
            station_record(11, STAMP + 60, 1825),
        ],
    )
    result = live.repo.results(event)[0]
    assert result.controls == 1 and result.elapsed == 60
    import_tag(live, event, [station_record(11, STAMP - 1, 1825)])
    assert live.repo.results(event)[0].elapsed is None
    store.close()


def test_timing_conflict_requires_explicit_choice_and_reopens_on_change(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path, Timing.PUNCH_START_FINISH)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    start = punch(ingest, 10, 0)
    punch(ingest, 1, 10, 2)
    punch(ingest, 11, 60, 3)
    import_tag(live, event, [station_record(10, STAMP + 2, 1825)])
    assert live.repo.results(event)[0].elapsed is None
    decision(live, event, participant, 10, "SELECT", source_type="LIVE", source_id=start)
    assert live.repo.results(event)[0].elapsed == 60 and not live.evidence.reviews(event)
    import_tag(live, event, [station_record(10, STAMP + 2, 1825)])
    assert not live.evidence.reviews(event)  # identical snapshot does not invalidate adjudication
    import_tag(live, event, [station_record(10, STAMP + 4, 1825)])
    assert live.evidence.reviews(event) and live.repo.results(event)[0].elapsed is None
    store.close()


def test_manual_punch_override_exclude_supersede_and_audit(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    manual = decision(
        live,
        event,
        participant,
        1,
        "MANUAL",
        timestamp=datetime.fromtimestamp(STAMP + 10, UTC).isoformat(),
        operator="Jury",
    )
    assert live.repo.results(event)[0].controls == 1 and live.repo.results(event)[0].manual_decision
    assert live.evidence.resolutions(event)[0].accepted[0].source_type == "MANUAL"
    decision(live, event, participant, 1, "EXCLUDE")
    assert live.repo.results(event)[0].controls == 0
    decision(live, event, participant, 1, "AUTO")
    assert len(live.evidence.decisions(event)) == 3
    assert any(
        a["reason"] == "confirmed by marshal" and a["action"] == "adjudication"
        for a in live.repo.audit(event)
    )
    assert not store.db.execute("SELECT * FROM punches").fetchall()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.db.execute(
            "UPDATE live_evidence_decisions SET reason='rewrite' WHERE id=?", (manual["id"],)
        )
    store.close()


def test_unsynchronized_control_presence_is_explicit_only(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    import_tag(live, event, [station_record(1, 100, 1825, False)])
    assert live.repo.results(event)[0].controls == 0
    decision(live, event, participant, 1, "PRESENCE")
    assert live.repo.results(event)[0].controls == 1 and not live.evidence.reviews(event)
    with pytest.raises(ValueError, match="controls only"):
        decision(live, event, participant, 11, "PRESENCE")
    store.close()


def test_unknown_readout_uid_assignment_reinterprets_without_duplication(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    unknown = "04AABBCCDDEE11"
    import_tag(live, event, [station_record(1, STAMP + 1, 1825)], unknown)
    assert live.evidence.resolutions(event)[0].status == "UNKNOWN_UID"
    entry = live.repo.entries(event)[0]
    live.put_entry(event, entry.registration().model_copy(update={"uid": unknown}), participant)
    assert live.repo.results(event)[0].controls == 1 and not live.evidence.reviews(event)
    assert store.db.execute("SELECT COUNT(*) FROM tag_readout_records").fetchone()[0] == 1
    assert not store.db.execute("SELECT * FROM punches").fetchall()
    store.close()


def test_restart_review_decisions_and_raw_payload(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    raw = capture(UID, [station_record(1, STAMP + 1, 1825)])
    live.evidence.import_raw(event, raw)
    decision(
        live,
        event,
        participant,
        2,
        "MANUAL",
        timestamp=datetime.fromtimestamp(STAMP + 2, UTC).isoformat(),
    )
    results = live.snapshot(event)["results"]
    store.close()
    store = Store(tmp_path / "evidence.db")
    published: list[str] = []
    live = LiveService(
        LiveRepository(store), publish=lambda kind, event, data: published.append(kind)
    )
    live.recover()
    assert live.snapshot(event)["results"] == results
    assert "tag_readout_completed" not in published
    assert (
        bytes(store.db.execute("SELECT raw_payload FROM tag_readout_sessions").fetchone()[0]) == raw
    )
    store.close()


def test_additive_migration_from_m4(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with patch("foxcore.persistence.MIGRATIONS", MIGRATIONS[:4]):
        store = Store(path)
        store.close()
    store = Store(path)
    assert store.version == 5
    assert store.db.execute("SELECT * FROM tag_readout_sessions").fetchall() == []
    store.close()


def test_close_warns_open_cases_and_archive_blocks_import(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path)
    import_tag(live, event, [station_record(1, STAMP + 1, 99)])
    with pytest.raises(ValueError, match="confirm close"):
        live.transition(event, State.CLOSED)
    live.transition(event, State.CLOSED, confirm_reviews=True)
    live.transition(event, State.ARCHIVED)
    with pytest.raises(ValueError, match="read-only"):
        import_tag(live, event, [])
    store.close()


def test_tag_event_unknown_then_configuration_reinterprets(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "unknown_event.db", Timing.PREDEFINED_START)
    import_tag(live, event, [station_record(1, STAMP + 10, 1825)])
    assert live.repo.results(event)[0].controls == 0
    assert live.evidence.resolutions(event)[0].status == "EVENT_ID_UNKNOWN"
    data = live.repo.event(event).model_dump(include=set(EventData.model_fields))
    live.put_event(EventData.model_validate(data | {"tag_event_id": 1825}), event)
    assert live.repo.results(event)[0].controls == 1 and not live.evidence.reviews(event)
    store.close()


def test_excluded_live_match_requires_review_not_silent_revival(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    source = punch(ingest, 1, 10)
    live.exclude(event, source, "marshal dispute")
    import_tag(live, event, [station_record(1, STAMP + 10, 1825)])
    resolution = live.evidence.resolutions(event)[0]
    assert "EXCLUDED_LIVE_MATCH" in resolution.issues and resolution.needs_review
    assert live.repo.results(event)[0].controls == 0
    tag = next(e for e in resolution.evidence if e.source_type == "TAG_READOUT")
    decision(
        live, event, participant, 1, "SELECT", source_type="TAG_READOUT", source_id=tag.source_id
    )
    assert live.repo.results(event)[0].controls == 1
    assert live.repo.exclusions(event)[source] == "marshal dispute"
    store.close()


def test_source_retry_does_not_invalidate_a_ruling(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    source = punch(ingest, 1, 10)
    import_tag(live, event, [station_record(1, STAMP + 20, 1825)])
    decision(live, event, participant, 1, "SELECT", source_type="LIVE", source_id=source)
    retry = punch(ingest, 1, 10)
    assert store.get_punch(retry).duplicate and live.repo.results(event)[0].controls == 1
    assert not live.evidence.reviews(event)
    store.close()


def test_window_and_disabled_station_do_not_count_tag(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path)
    data = live.repo.event(event).model_dump(include=set(EventData.model_fields))
    live.put_event(
        EventData.model_validate(
            data | {"competition_end_at": datetime.fromtimestamp(STAMP + 10, UTC).isoformat()}
        ),
        event,
    )
    from foxlive.models import Role, StationData

    live.put_station(
        event,
        StationData(station_id=2, display_name="Disabled fox", role=Role.CONTROL, enabled=False),
    )
    import_tag(
        live, event, [station_record(1, STAMP + 11, 1825), station_record(2, STAMP + 5, 1825)]
    )
    assert live.repo.results(event)[0].controls == 0
    assert {r.status for r in live.evidence.resolutions(event)} == {
        "OUTSIDE_EVENT_WINDOW",
        "DISABLED_STATION",
    }
    store.close()


@pytest.mark.parametrize("status", ["PARTIAL", "FAILED", "ABORTED"])
def test_incomplete_read_absence_never_invalidates_live(tmp_path: Path, status: str) -> None:
    store, live, event, _ = configured(tmp_path)
    from foxcore.service import IngestService

    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    punch(ingest, 1, 10)
    import_tag(live, event, [], status=status)
    assert live.repo.results(event)[0].controls == 1
    assert live.repo.results(event)[0].completeness == "REVIEW_REQUIRED"
    assert live.evidence.reviews(event)
    store.close()


def test_tag_whole_second_ties_and_midnight_dst_absolute_times(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path, Timing.PUNCH_START_FINISH)
    import_tag(
        live,
        event,
        [
            station_record(1, STAMP, 1825),
            station_record(10, STAMP, 1825),
            station_record(11, STAMP, 1825),
        ],
    )
    assert live.repo.results(event)[0].controls == 1 and live.repo.results(event)[0].elapsed == 0
    start = int(datetime(2026, 10, 24, 23, 30, tzinfo=UTC).timestamp())
    finish = int(datetime(2026, 10, 25, 2, 30, tzinfo=UTC).timestamp())
    # Europe's fall-back happens inside the race; elapsed is absolute, not wall-clock subtraction.
    live.evidence.import_raw(
        event,
        capture(
            UID,
            [
                station_record(10, start, 1825),
                station_record(1, start + 10, 1825),
                station_record(11, finish, 1825),
            ],
        ),
        received_at=datetime.fromtimestamp(finish + 60, UTC),
    )
    assert live.repo.results(event)[0].elapsed == 10800
    store.close()


def test_raw_first_survives_parser_and_recalculation_failures(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path)
    raw = capture(UID, [station_record(1, STAMP + 10, 1825)])
    with patch("foxlive.evidence.parse_readout", side_effect=RuntimeError("parser failure")):
        with pytest.raises(RuntimeError):
            live.evidence.import_raw(event, raw)
    row = store.db.execute("SELECT * FROM tag_readout_sessions").fetchone()
    assert bytes(row["raw_payload"]) == raw and row["status"] == "PENDING"
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("UPDATE tag_readout_sessions SET raw_payload=?", (b"rewrite",))
    live.recover()
    assert live.repo.results(event)[0].controls == 1
    with patch.object(live, "_calculate", side_effect=RuntimeError("scorer failure")):
        with pytest.raises(RuntimeError):
            import_tag(live, event, [station_record(2, STAMP + 20, 1825)])
    assert store.db.execute("SELECT COUNT(*) FROM tag_readout_records").fetchone()[0] == 2
    live.recalculate(event)
    assert live.repo.results(event)[0].controls == 2
    store.close()


def test_semantically_identical_capture_keeps_tag_ruling(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    item = station_record(1, STAMP + 10, 1825)
    import_tag(live, event, [item])
    tag = live.evidence.resolutions(event)[0].accepted[0]
    decision(
        live, event, participant, 1, "SELECT", source_type="TAG_READOUT", source_id=tag.source_id
    )
    item["data"] = " ".join(str(item["data"]).lower()[i : i + 2] for i in range(0, 16, 2))
    import_tag(live, event, [item])
    assert not live.evidence.reviews(event) and live.repo.results(event)[0].controls == 1
    store.close()


def test_reason_required_future_clock_and_manual_time_ruling(tmp_path: Path) -> None:
    store, live, event, participant = configured(tmp_path)
    with pytest.raises(ValueError, match="requires a reason"):
        live.evidence.decide(
            event,
            DecisionInput(participant_id=participant, station_id=1, action="EXCLUDE", reason="  "),
        )
    future = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())
    live.evidence.import_raw(
        event,
        capture(UID, [station_record(1, future, 1825)]),
        received_at=datetime.fromtimestamp(STAMP, UTC),
    )
    assert live.repo.results(event)[0].controls == 0
    decision(
        live,
        event,
        participant,
        11,
        "MANUAL",
        timestamp=datetime.fromtimestamp(STAMP + 90, UTC).isoformat(),
    )
    assert live.repo.results(event)[0].elapsed == 90
    store.close()


def test_software_acceptance_five_foxes_recovery_ranking_review_restart(tmp_path: Path) -> None:
    from foxcore.service import IngestService
    from foxlive.models import EntryData, Role, RunnerData, StationData

    store, live, event, participant = configured(tmp_path)
    for station in (3, 4, 5):
        live.put_station(
            event, StationData(station_id=station, display_name=f"Fox {station}", role=Role.CONTROL)
        )
    category = live.repo.entries(event)[0].category_id
    runner = live.put_runner(RunnerData(first_name="Anna", last_name="Example", birth_year=1985))
    other_uid = "04AABBCCDDEE11"
    other = live.put_entry(
        event, EntryData(runner_id=runner.id, start_number=18, category_id=category, uid=other_uid)
    )
    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    source_ids = {station: punch(ingest, station, station * 10, station) for station in (1, 3, 5)}
    punch(ingest, 11, 100, 6)
    for station in (1, 2, 3, 4):
        punch(ingest, station, station * 10, station + 10, other_uid)
    punch(ingest, 11, 90, 20, other_uid)
    assert {r.participant_id: r.rank for r in live.repo.results(event)} == {
        participant: 2,
        other.id: 1,
    }
    original = [tuple(r) for r in store.db.execute("SELECT * FROM punches ORDER BY id")]
    readout = import_tag(
        live,
        event,
        [station_record(station, STAMP + station * 10, 1825) for station in range(1, 6)],
    )
    assert readout["summary"]["recovered"] == 2 and readout["summary"]["matches"] == 3
    assert {r.participant_id: r.rank for r in live.repo.results(event)} == {
        participant: 1,
        other.id: 2,
    }
    assert (
        next(r for r in live.repo.results(event) if r.participant_id == participant).controls == 5
    )
    import_tag(live, event, [station_record(3, STAMP + 35, 1825)])
    assert len(live.evidence.reviews(event)) == 1
    decision(live, event, participant, 3, "SELECT", source_type="LIVE", source_id=source_ids[3])
    assert not live.evidence.reviews(event)
    assert any(a["action"] == "adjudication" and a["reason"] for a in live.repo.audit(event))
    final = live.snapshot(event)["results"]
    assert [tuple(r) for r in store.db.execute("SELECT * FROM punches ORDER BY id")] == original
    store.close()
    store = Store(tmp_path / "evidence.db")
    live = LiveService(LiveRepository(store))
    live.recover()
    assert live.snapshot(event)["results"] == final
    store.close()


def test_equal_numeric_unsynchronized_live_and_tag_time_is_not_validated_by_match(
    tmp_path: Path,
) -> None:
    from foxcore.service import IngestService

    store, live, event, _ = configured(tmp_path, Timing.PUNCH_START_FINISH)
    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    start = punch(ingest, 10, 0)
    punch(ingest, 1, 10, 2)
    punch(ingest, 11, 60, 3)
    assert live.repo.results(event)[0].elapsed == 60
    import_tag(live, event, [station_record(10, STAMP, 1825, False)])
    assert live.repo.results(event)[0].elapsed is None
    assert live.evidence.reviews(event)
    assert store.get_punch(start).station_timestamp == STAMP
    live_evidence = live.evidence.resolutions(event)[1].evidence[0]
    assert live_evidence.validity == "UNTRUSTED_LIVE_TIME"
    store.close()


def test_display_metadata_does_not_revoke_jury_ruling(tmp_path: Path) -> None:
    from foxlive.models import EventData, Role, StationData

    store, live, event, participant = configured(tmp_path)
    import_tag(live, event, [station_record(1, STAMP + 10, 99)])
    decision(live, event, participant, 1, "PRESENCE")
    data = live.repo.event(event).model_dump(include=set(EventData.model_fields))
    live.put_event(EventData.model_validate(data | {"name": "Corrected spelling"}), event)
    live.put_station(
        event, StationData(station_id=1, display_name="Renamed fox", role=Role.CONTROL)
    )
    assert live.repo.results(event)[0].controls == 1
    assert not live.evidence.reviews(event)
    store.close()
