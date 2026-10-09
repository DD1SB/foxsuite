"""ARDF finish beacon domain correction; existing sporting rules remain authoritative."""

import csv
import io
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_live_domain import STAMP, punch, setup, statuses
from test_live_web import receive, request
from test_readout_web import import_capture, prepare
from test_reconciliation import configured, decision, import_tag

from foxcore.persistence import MIGRATIONS, Store
from foxcore.service import IngestService
from foxlive.models import Role, StationData, Timing
from foxlive.persistence import LiveRepository
from foxlive.presentation import translate
from foxlive.readout import station_record
from foxlive.service import LiveService
from foxlive.web import create_app
from foxops.data import validate_database


def add_beacon(live: LiveService, event: int, station: int = 8) -> None:
    live.put_station(event, StationData(station_id=station, display_name="Bake", role=Role.BEACON))


@pytest.mark.parametrize("role", list(Role))
def test_station_role_database_roundtrip(tmp_path: Path, role: Role) -> None:
    path = tmp_path / "roles.db"
    store, live, _, event, _ = setup(path)
    station = live.put_station(
        event, StationData(station_id=8, display_name="Station", role=role, display_order=7)
    )
    assert station.role == role
    store.close()
    store = Store(path)
    assert next(s for s in LiveRepository(store).stations(event) if s.station_id == 8) == station
    store.close()


def test_populated_m5_migration_preserves_stations_sources_and_historical_scores(
    tmp_path: Path,
) -> None:
    path = tmp_path / "m5.db"
    with patch("foxcore.persistence.MIGRATIONS", MIGRATIONS[:5]):
        store, live, ingest, event, _ = setup(path, Timing.PREDEFINED_START)
        punch(ingest, 1, 10)
        punch(ingest, 11, 60, 2)
        # A real pre-correction result payload has no beacon field.
        previous = live.repo.results(event)[0].model_dump(mode="json", exclude={"beacon_punched"})
        with store.db:
            store.db.execute("UPDATE live_entry_results SET payload=?", (json.dumps(previous),))
        stations = [tuple(r) for r in store.db.execute("SELECT * FROM live_event_stations")]
        sources = [tuple(r) for r in store.db.execute("SELECT * FROM punches")]
        store.close()
    validate_database(path)
    store = Store(path)
    assert store.version == 6
    assert [tuple(r) for r in store.db.execute("SELECT * FROM live_event_stations")] == stations
    assert [tuple(r) for r in store.db.execute("SELECT * FROM punches")] == sources
    assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
    validate_database(path)
    live = LiveService(LiveRepository(store))
    assert (
        live.repo.results(event)[0].model_dump(mode="json", exclude={"beacon_punched"}) == previous
    )
    live.recover()
    assert (
        live.repo.results(event)[0].model_dump(mode="json", exclude={"beacon_punched"}) == previous
    )
    add_beacon(live, event)
    add_beacon(live, event, 9)  # No artificial singleton constraint.
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.db.execute("UPDATE live_event_stations SET role='INVALID' WHERE station_id=8")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        store.db.execute(
            "INSERT INTO bridge_station_maps(station_id,control_code,role,active) VALUES (8,31,'BEACON',1)"
        )
    store.close()


@pytest.mark.parametrize("timing", list(Timing))
def test_three_controls_beacon_repeats_retries_and_finish_timing(
    tmp_path: Path, timing: Timing
) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "score.db", timing)
    add_beacon(live, event)
    live.put_station(event, StationData(station_id=3, display_name="Fox 3", role=Role.CONTROL))
    if timing == Timing.PUNCH_START_FINISH:
        punch(ingest, 10, 0)
    for station in (1, 2, 3):
        punch(ingest, station, station * 10, station)
    without_beacon = live.repo.results(event)[0]
    assert without_beacon.controls == 3 and without_beacon.finish is None
    punch(ingest, 8, 40, 4)
    punch(ingest, 8, 45, 5)
    retry = punch(ingest, 8, 45, 5)
    assert store.get_punch(retry).duplicate
    result = live.repo.results(event)[0]
    assert result.controls == 3 and result.beacon_punched
    assert result.start == STAMP and result.finish is None and result.elapsed is None
    assert statuses(live, event)[-3:] == ["VALID_BEACON", "REPEAT_BEACON", "SOURCE_DUPLICATE"]
    punch(ingest, 11, 60, 6)
    result = live.repo.results(event)[0]
    assert result.controls == 3 and result.finish == STAMP + 60 and result.elapsed == 60
    assert result.rank == 1
    add_beacon(live, event, 9)
    punch(ingest, 9, 50, 7)
    assert statuses(live, event)[-1] == "VALID_BEACON"
    punch(ingest, 8, 61, 8)
    assert statuses(live, event)[-1] == "INVALID_FOR_TIMING"
    before = live.snapshot(event)["results"]
    evidence = [r.model_dump() for r in live.evidence.resolutions(event)]
    for _ in range(3):
        live.recalculate(event)
        assert live.snapshot(event)["results"] == before
        assert [r.model_dump() for r in live.evidence.resolutions(event)] == evidence
    store.close()


def test_beacon_does_not_start_or_require_presence_to_rank(tmp_path: Path) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "start.db")
    add_beacon(live, event)
    punch(ingest, 8, 0)
    result = live.repo.results(event)[0]
    assert result.start is None and result.finish is None and not result.beacon_punched
    assert statuses(live, event) == ["INVALID_FOR_TIMING"]
    punch(ingest, 10, 10, 2)
    punch(ingest, 1, 20, 3)
    punch(ingest, 11, 60, 4)
    result = live.repo.results(event)[0]
    assert result.controls == 1 and result.elapsed == 50 and result.rank == 1
    assert not result.beacon_punched and result.status == "FINISHED" and not result.open_reviews
    import_tag(live, event, [])
    assert live.repo.results(event)[0].completeness == "COMPLETE"
    assert live.repo.results(event)[0].rank == 1
    store.close()


@pytest.mark.parametrize(
    "visits,tag_offset,expected",
    [
        ([40], 40, "MATCHED"),
        ([40], None, "LIVE_ONLY"),
        ([], 40, "TAG_ONLY_RECOVERED"),
        ([40, 45], 45, "TAG_CONFIRMED_LIVE"),
        ([40, 40], 40, "TAG_CONFIRMED_LIVE"),
        ([40, 45], 42, "CONFLICT"),
    ],
)
def test_beacon_reconciliation_provenance_and_conservative_conflicts(
    tmp_path: Path, visits: list[int], tag_offset: int | None, expected: str
) -> None:
    store, live, event, participant = configured(tmp_path)
    add_beacon(live, event)
    ingest = IngestService(store)
    ingest.subscribe(live.accept)
    punch(ingest, 1, 10)
    for sequence, offset in enumerate(visits, 2):
        punch(ingest, 8, offset, sequence)
    if visits:
        punch(ingest, 8, visits[-1], len(visits) + 1)  # Exact transport retry.
    punch(ingest, 11, 60, 9)
    sources = [tuple(r) for r in store.db.execute("SELECT * FROM punches")]
    session = import_tag(
        live, event, [] if tag_offset is None else [station_record(8, STAMP + tag_offset, 1825)]
    )
    beacon = next(r for r in live.evidence.resolutions(event) if r.role == Role.BEACON)
    assert beacon.status == expected and beacon.participant_id == participant
    assert len(beacon.accepted) == (len(visits) or 1)
    assert {s["status"] for s in beacon.scored} == (
        {"VALID_BEACON", "REPEAT_BEACON"} if len(visits) > 1 else {"VALID_BEACON"}
    )
    assert len([e for e in beacon.evidence if e.source_type == "LIVE"]) == len(visits) + bool(
        visits
    )
    if tag_offset is not None:
        tag = next(e for e in beacon.evidence if e.source_type == "TAG_READOUT")
        assert tag.session_id == session["id"] and tag.station_timestamp == STAMP + tag_offset
        assert tag.tag_event_id == 1825 and tag.time_synchronized
    result = live.repo.results(event)[0]
    assert result.controls == 1 and result.recovered_controls == 0 and result.beacon_punched
    assert result.start == STAMP and result.finish == STAMP + 60 and result.elapsed == 60
    assert result.rank == 1 and result.open_reviews == (expected == "CONFLICT")
    assert session["summary"]["recovered"] == 0 and session["summary"]["beacon_punched"]
    assert session["summary"]["controls_found"] == 1 and session["summary"]["finish_punched"]
    assert [tuple(r) for r in store.db.execute("SELECT * FROM punches")] == sources
    baseline = live.snapshot(event)["results"]
    for _ in range(2):
        live.recalculate(event)
        assert live.snapshot(event)["results"] == baseline
    store.close()
    store = Store(tmp_path / "evidence.db")
    live = LiveService(LiveRepository(store))
    live.recover()
    assert live.snapshot(event)["results"] == baseline
    assert next(r for r in live.evidence.resolutions(event) if r.role == Role.BEACON) == beacon
    store.close()


def test_tag_beacon_whole_second_tie_precedes_finish(tmp_path: Path) -> None:
    store, live, event, _ = configured(tmp_path, Timing.PUNCH_START_FINISH)
    add_beacon(live, event)
    import_tag(
        live,
        event,
        [station_record(station, STAMP, 1825) for station in (11, 8, 1, 10)],
    )
    result = live.repo.results(event)[0]
    assert result.controls == 1 and result.beacon_punched and result.elapsed == 0
    assert not result.open_reviews
    store.close()


@pytest.mark.parametrize("action", ["MANUAL", "PRESENCE", "SELECT"])
def test_reasoned_beacon_adjudication_and_audit(tmp_path: Path, action: str) -> None:
    store, live, event, participant = configured(tmp_path)
    add_beacon(live, event)
    import_tag(live, event, [station_record(8, STAMP + 40, 1825, action == "SELECT")])
    beacon = next(r for r in live.evidence.resolutions(event) if r.role == Role.BEACON)
    tag = beacon.evidence[0]
    fields = (
        {"timestamp": datetime.fromtimestamp(STAMP + 40, UTC).isoformat()}
        if action == "MANUAL"
        else {"source_type": "TAG_READOUT", "source_id": tag.source_id}
        if action == "SELECT"
        else {}
    )
    with pytest.raises(ValueError, match="requires a reason"):
        decision(live, event, participant, 8, action, **fields, reason="   ")
    ruling = decision(live, event, participant, 8, action, **fields, operator="Beacon marshal")
    result = live.repo.results(event)[0]
    assert result.controls == 0 and result.beacon_punched and result.manual_decision
    assert result.finish is None and result.elapsed is None and not result.open_reviews
    beacon = next(r for r in live.evidence.resolutions(event) if r.role == Role.BEACON)
    if action == "MANUAL":
        assert beacon.accepted[0].source_type == "MANUAL"
    assert beacon.decision_id == ruling["id"]
    assert any(
        a["action"] == "adjudication" and a["operator"] == "Beacon marshal" and a["reason"]
        for a in live.repo.audit(event)
    )
    decision(live, event, participant, 8, "EXCLUDE")
    assert not live.repo.results(event)[0].beacon_punched
    assert store.db.execute("SELECT COUNT(*) FROM tag_readout_records").fetchone()[0] == 1
    assert not store.db.execute("SELECT * FROM punches").fetchall()
    store.close()


@pytest.mark.parametrize("lang,label", [("en", "Beacon"), ("de", "Bake")])
def test_beacon_api_openapi_websockets_exports_and_localized_form(
    tmp_path: Path, lang: str, label: str
) -> None:
    with TestClient(create_app(tmp_path / "api.db"), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        event = int(root.rsplit("/", 1)[1])
        for role in Role:
            station = {"station_id": 8, "display_name": "MO", "role": role.value}
            assert request(client, root + "/stations/8", station, "PUT")["role"] == role.value
        request(client, root + "/stations/8", station | {"role": "BEACON"}, "PUT")
        assert (
            next(
                s
                for s in client.get(f"/api/stations?event_id={event}").json()
                if s["station_id"] == 8
            )["role"]
            == "BEACON"
        )
        schema = client.get("/openapi.json").json()["components"]["schemas"]
        assert set(schema["Role"]["enum"]) == {"CONTROL", "START", "BEACON", "FINISH"}
        assert schema["StationData"]["properties"]["role"]["$ref"].endswith("/Role")
        assert schema["Station"]["properties"]["role"]["$ref"].endswith("/Role")
        assert client.put(root + "/stations/8", json=station | {"role": label}).status_code == 422
        html = client.get("/live").text
        assert '<option value="BEACON" data-i18n="station.BEACON">Beacon</option>' in html
        assert translate("station.BEACON", lang) == label
        assert client.get(f"/static/translations/{lang}.json").json()["station.BEACON"] == label
        receive(client, station=8, seconds=40)
        receive(client, station=11, seconds=60)
        with client.websocket_connect(f"ws://127.0.0.1/ws?event_id={event}") as socket:
            snapshot = socket.receive_json()["payload"]
            assert next(s for s in snapshot["stations"] if s["station_id"] == 8)["role"] == "BEACON"
            assert (
                next(p for p in snapshot["recent"] if p["station_id"] == 8)["status"]
                == "VALID_BEACON"
            )
        with client.websocket_connect(f"ws://127.0.0.1/ws/display?event_id={event}") as socket:
            assert (
                next(p for p in socket.receive_json()["payload"]["recent"] if p["station_id"] == 8)[
                    "role"
                ]
                == "BEACON"
            )
        import_capture(client, root, [station_record(8, STAMP + 40, 1825)])
        detail = client.get(root + f"/participants/{entry}").json()
        assert detail["history"][0]["role"] == "BEACON"
        assert detail["evidence"][0]["role"] == "BEACON"
        assert detail["result"]["controls"] == 0 and detail["result"]["elapsed"] == 60
        exported = client.get(root + "/export/evidence").json()
        assert next(r for r in exported["resolutions"] if r["station_id"] == 8)["role"] == "BEACON"
        rows = list(csv.DictReader(io.StringIO(client.get(root + "/export/results").text)))
        assert rows[0]["beacon_punched"] == "True" and rows[0]["controls"] == "0"
        assert rows[0]["elapsed_time"] == "60"
