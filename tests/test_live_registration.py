"""Corrected master/registration model; accepted scoring and immutable facts preserved."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_live_domain import STAMP, UID, add_category, punch, setup, statuses
from test_live_web import configure, receive, request

from foxcore.persistence import MIGRATIONS, Store
from foxcore.service import IngestService
from foxlive import csvio
from foxlive.models import (
    CategoryData,
    ClubData,
    EntryData,
    EventCategoryData,
    EventData,
    RegistrationData,
    Role,
    RunnerData,
    State,
    StationData,
    Timing,
)
from foxlive.persistence import LiveRepository
from foxlive.service import LiveService
from foxlive.web import create_app


def test_runner_reused_with_independent_historical_assignments(tmp_path: Path) -> None:
    store, live, ingest, event, entry_id = setup(tmp_path / "history.db", Timing.PREDEFINED_START)
    first = live.repo.entries(event)[0]
    punch(ingest, 1, 1)
    punch(ingest, 11, 10)
    original = first.model_dump()
    original_result = live.repo.results(event)[0].model_dump()
    live.transition(event, State.CLOSED)
    for number, code, uid in [(42, "OPEN", "04BB"), (5, "M40", "04CC"), (3, "OPEN", UID)]:
        other = live.put_event(
            EventData(
                name=f"Event {number}",
                date="2026-10-07",
                timing_mode=Timing.PREDEFINED_START,
                default_start_at=datetime.fromtimestamp(STAMP, UTC).isoformat(),
            )
        )
        category = add_category(live, other.id, code, code)
        registered = live.put_entry(
            other.id,
            EntryData(
                runner_id=first.runner_id,
                start_number=number,
                category_id=category.id,
                uid=uid,
                start_time=datetime.fromtimestamp(STAMP + 1, UTC).isoformat(),
            ),
        )
        assert registered.runner_id == first.runner_id and registered.id != entry_id
        assert registered.start_number == number and registered.uid == uid
        live.put_station(other.id, StationData(station_id=1, display_name="Fox", role=Role.CONTROL))
        live.put_station(
            other.id, StationData(station_id=11, display_name="Finish", role=Role.FINISH)
        )
        live.transition(other.id, State.RUNNING)
        punch(ingest, 1, 2, sequence=number, uid=uid)
        punch(ingest, 11, 20, sequence=number, uid=uid)
        result = live.repo.results(other.id)[0]
        assert result.controls == 1 and result.elapsed == 19 and result.rank == 1
        live.transition(other.id, State.CLOSED)
    assert live.repo.entries(event)[0].model_dump() == original
    assert live.repo.results(event)[0].model_dump() == original_result
    assert len(live.repo.runners()) == 1 and len(live.repo.master_categories()) == 2
    store.close()


def test_master_edits_never_rewrite_registered_snapshots(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "snapshot.db")
    entry = live.repo.entries(event)[0]
    category = live.repo.categories(event)[0]
    club = live.put_club(ClubData(code="P01", display_name="Club A"))
    runner = live.repo.runner(entry.runner_id)
    live.put_runner(
        RunnerData(
            first_name="Changed", last_name=runner.last_name, birth_year=1980, club_id=club.id
        ),
        runner.id,
    )
    live.put_master_category(
        CategoryData(code="NEW", display_name_en="New", display_name_de="Neu"), category.id
    )
    live.put_entry(event, entry.registration().model_copy(update={"checked_in": True}), entry.id)
    assert live.repo.entries(event)[0].first_name == "Max"
    assert live.repo.entries(event)[0].club == ""
    assert live.repo.categories(event)[0].code == "OPEN"
    assert live.repo.master_audit()
    later = live.put_event(EventData(name="Next", date="2026-10-07"))
    live.put_category(later.id, EventCategoryData(category_id=category.id))
    future = live.put_entry(later.id, entry.registration())
    assert future.first_name == "Changed" and future.club == "Club A"
    assert live.repo.categories(later.id)[0].code == "NEW"
    store.close()


def test_same_event_uniqueness_and_inactive_registration(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "unique.db")
    entry = live.repo.entries(event)[0]
    with pytest.raises(ValueError, match="already registered"):
        live.put_entry(
            event, entry.registration().model_copy(update={"start_number": 2, "uid": "04BB"})
        )
    other = live.put_runner(RunnerData(first_name="Anna", last_name="Meyer", birth_year=1980))
    with pytest.raises(ValueError, match="already assigned"):
        live.put_entry(
            event,
            entry.registration().model_copy(update={"runner_id": other.id, "start_number": 2}),
        )
    with pytest.raises(ValueError, match="Start number"):
        live.put_entry(
            event, entry.registration().model_copy(update={"runner_id": other.id, "uid": None})
        )
    live.put_entry(event, entry.registration().model_copy(update={"active": False}), entry.id)
    second = live.put_entry(event, entry.registration().model_copy(update={"start_number": 2}))
    assert second.uid == UID and second.runner_id == entry.runner_id
    with pytest.raises(sqlite3.IntegrityError):
        with store.db:
            store.db.execute("UPDATE live_entries SET active=1 WHERE id=?", (entry.id,))
    store.close()


def test_club_reuse_runner_search_and_birth_date(tmp_path: Path) -> None:
    store, live, _, _, _ = setup(tmp_path / "search.db")
    club = live.put_club(ClubData(code="P01", display_name="Ortsverband Test"))
    for year in (1970, 1980):
        live.put_runner(
            RunnerData(first_name="Max", last_name="Müller", birth_year=year, club_id=club.id)
        )
    found = live.repo.runners("mÜLLER 1970 p01")
    assert len(found) == 1 and found[0].birth_year == 1970
    assert found[0].club == club.display_name
    assert len(live.repo.runners("Ortsverband")) == 2
    born = live.put_runner(
        RunnerData(first_name="Anna", last_name="Meyer", birth_date="1981-04-03")
    )
    assert born.birth_year == 1981 and born.birth_date == "1981-04-03"
    with pytest.raises(ValueError, match="already exists"):
        live.put_club(ClubData(code="P01", display_name="Other"))
    assert len(live.repo.clubs()) == 1
    store.close()


@pytest.mark.parametrize(
    "birth_year,birth_date,error",
    [
        (None, None, "required"),
        (1980, "1981-01-01", "match"),
        (1980, "bad", "Invalid"),
        (9999, None, "future"),
        (None, "9999-01-01", "future"),
    ],
)
def test_birth_validation(
    tmp_path: Path, birth_year: int | None, birth_date: str | None, error: str
) -> None:
    store, live, _, _, _ = setup(tmp_path / "birth.db")
    with pytest.raises(ValueError, match=error):
        live.put_runner(
            RunnerData(first_name="A", last_name="B", birth_year=birth_year, birth_date=birth_date)
        )
    assert len(live.repo.runners()) == 1
    store.close()


def test_event_category_enable_disable_and_reuse(tmp_path: Path) -> None:
    store, live, ingest, event, entry_id = setup(tmp_path / "enabled.db", Timing.PREDEFINED_START)
    category = live.repo.categories(event)[0]
    punch(ingest, 1, 1)
    punch(ingest, 11, 10)
    assert live.repo.results(event)[0].rank == 1
    live.put_category(event, EventCategoryData(category_id=category.id, enabled=False), category.id)
    assert live.repo.results(event)[0].rank is None
    # Existing corrections remain possible; new registrations cannot select disabled categories.
    entry = live.repo.entries(event)[0]
    live.put_entry(event, entry.registration().model_copy(update={"checked_in": True}), entry_id)
    runner = live.put_runner(RunnerData(first_name="A", last_name="B", birth_year=1980))
    with pytest.raises(ValueError, match="not enabled"):
        live.put_entry(
            event, EntryData(runner_id=runner.id, start_number=2, category_id=category.id)
        )
    live.put_category(event, EventCategoryData(category_id=category.id, enabled=True), category.id)
    assert live.repo.results(event)[0].rank == 1
    assert len(live.repo.punches(event)) == 2 and len(live.repo.master_categories()) == 1
    store.close()


def test_inline_registration_atomic_and_unknown_history(tmp_path: Path) -> None:
    store, live, ingest, event, _ = setup(tmp_path / "inline.db", Timing.PREDEFINED_START)
    unknown = punch(ingest, 1, 1, uid="04BB")
    before = [tuple(r) for r in store.db.execute("SELECT * FROM punches")]
    person = RunnerData(first_name="Anna", last_name="Meyer", birth_year=1980)
    data = RegistrationData(
        start_number=2, category_id=live.repo.categories(event)[0].id, uid="04:BB", checked_in=True
    )
    registered = live.register_new_runner(event, person, data)
    assert registered.uid == "04BB" and registered.checked_in
    assert statuses(live, event) == ["VALID_CONTROL"]
    assert (
        next(r for r in live.repo.results(event) if r.participant_id == registered.id).controls == 1
    )
    assert live.repo.recent(event)[0]["id"] == unknown
    assert [tuple(r) for r in store.db.execute("SELECT * FROM punches")] == before
    audits = live.repo.master_audit()
    with pytest.raises(ValueError, match="already assigned"):
        live.register_new_runner(
            event,
            person.model_copy(update={"first_name": "Other"}),
            data.model_copy(update={"start_number": 3}),
        )
    assert len(live.repo.runners()) == 2 and live.repo.master_audit() == audits
    store.close()


def test_csv_master_reuse_atomic_and_ambiguous_people(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "csv-master.db")
    club = live.put_club(ClubData(code="P01", display_name="Test"))
    person = RunnerData(first_name="Anna", last_name="Meyer", birth_year=1980, club_id=club.id)
    runner = live.put_runner(person)
    text = "start_number,first_name,last_name,category,birth_year,club,club_code,uid\n2,Anna,Meyer,OPEN,1980,Test,P01,04BB\n"
    assert csvio.preview(live, event, text)["valid"] and len(live.repo.entries(event)) == 1
    assert csvio.import_participants(live, event, text)["valid"]
    assert live.repo.entries(event)[1].runner_id == runner.id
    assert len(live.repo.runners()) == 2 and len(live.repo.clubs()) == 1
    later = live.put_event(EventData(name="Next", date="2026-10-07"))
    add_category(live, later.id, "OPEN", "Open")
    assert csvio.import_participants(live, later.id, text)["valid"]
    assert live.repo.entries(later.id)[0].runner_id == runner.id
    other = live.put_event(EventData(name="Ambiguous", date="2026-10-07"))
    add_category(live, other.id, "OPEN", "Open")
    live.put_runner(person)  # Identical name/date/club is allowed; identity must not be guessed.
    assert not csvio.preview(live, other.id, text)["valid"]
    assert "ambiguous" in csvio.preview(live, other.id, text)["errors"][0]["error"]
    store.close()


def test_registration_api_search_unknown_assignment_and_localized_errors(tmp_path: Path) -> None:
    with TestClient(
        create_app(tmp_path / "registration-api.db"), base_url="http://127.0.0.1"
    ) as client:
        event, category, _ = configure(client)
        club = request(client, "/api/clubs", {"code": "P01", "display_name": "Test"})
        person = {
            "first_name": "Anna",
            "last_name": "Meyer",
            "birth_date": "1980-05-06",
            "club_id": club["id"],
        }
        receive(client, uid="04BB")
        entry = request(
            client,
            f"/api/events/{event}/register-new-runner",
            {
                "runner": person,
                "entry": {
                    "start_number": 18,
                    "category_id": category,
                    "uid": "04BB",
                    "checked_in": True,
                },
            },
        )
        runners = client.get("/api/runners?search=meyer%201980%20p01").json()
        assert len(runners) == 1 and runners[0]["id"] == entry["runner_id"]
        assert (
            client.get(f"/api/events/{event}/participants/{entry['id']}").json()["result"][
                "controls"
            ]
            == 1
        )
        response = client.post(
            f"/api/events/{event}/participants",
            json={"runner_id": entry["runner_id"], "start_number": 19, "category_id": category},
            headers={"Accept-Language": "de"},
        )
        assert response.status_code == 422 and "bereits" in response.json()["detail"]
        assert len(client.get("/api/source-punches").json()) == 1
        assert client.get("/api/master/audit").json()
        request(
            client, "/api/clubs/" + str(club["id"]), {"code": "P01", "display_name": "New"}, "PUT"
        )
        assert (
            client.get(f"/api/events/{event}/participants/{entry['id']}").json()["participant"][
                "club"
            ]
            == "Test"
        )


def test_migration_three_retains_legacy_and_rebuilds_identically(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    now = datetime.fromtimestamp(STAMP, UTC).isoformat()
    with patch("foxcore.persistence.MIGRATIONS", MIGRATIONS[:3]):
        store = Store(path)
        ingest = IngestService(store)
        punch_id = punch(ingest, 1, 1)
        with store.db:
            for event_id in (1, 2):
                store.db.execute(
                    "INSERT INTO live_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        f"Old {event_id}",
                        "2026-10-06",
                        "Europe/Berlin",
                        "",
                        "RUNNING" if event_id == 1 else "CLOSED",
                        "PREDEFINED_START",
                        None,
                        None,
                        now,
                        1577836800,
                        86400,
                        punch_id,
                        now,
                        now,
                    ),
                )
                store.db.execute(
                    "INSERT INTO live_categories VALUES (?,?,?,?,?,?)",
                    (event_id, event_id, "OPEN", "Open", 1, 0),
                )
                store.db.execute(
                    "INSERT INTO live_participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        event_id,
                        17,
                        "Max",
                        "Müller",
                        event_id,
                        UID,
                        "Club A",
                        None,
                        None,
                        1,
                        now,
                        now,
                    ),
                )
            store.db.execute("INSERT INTO live_event_stations VALUES (1,1,'Fox','CONTROL',1,0)")
            store.db.execute(
                "INSERT INTO live_event_punches VALUES (1,?,?,?,'live')", (punch_id, UID, now)
            )
            store.db.execute(
                "INSERT INTO live_punch_interpretations VALUES (1,?,1,'VALID_CONTROL','CONTROL','')",
                (punch_id,),
            )
            payload = {
                "participant_id": 1,
                "category_id": 1,
                "start_number": 17,
                "status": "RUNNING",
                "controls": 1,
                "start": STAMP,
                "finish": None,
                "elapsed": None,
                "rank": None,
                "eligible": True,
            }
            store.db.execute("INSERT INTO live_results VALUES (1,1,?)", (json.dumps(payload),))
            store.db.execute(
                "INSERT INTO live_audit_events VALUES (1,1,?,'operator','lifecycle','1','null','null','')",
                (now,),
            )
        tables = [
            "live_categories",
            "live_participants",
            "live_punch_interpretations",
            "live_results",
            "punches",
            "raw_events",
            "bridge_deliveries",
        ]
        # Existing M2 deliveries are not interpreted or rewritten by this migration.
        original = {
            table: [tuple(r) for r in store.db.execute(f"SELECT * FROM {table}")]
            for table in tables
        }
        store.close()
    store = Store(path)
    assert store.version == 4
    live = LiveService(LiveRepository(store))
    assert len(live.repo.runners()) == 2 and all(r.birth_year is None for r in live.repo.runners())
    assert len(live.repo.clubs()) == 1
    assert all(c.needs_review for c in live.repo.master_categories())
    assert [c.code for c in live.repo.master_categories()] == ["OPEN", "OPEN"]
    assert live.repo.entries(1)[0].id == 1 and live.repo.entries(2)[0].runner_id == 2
    assert live.repo.results(1)[0].controls == 1
    published: list[str] = []
    live.publish = lambda kind, _event, _payload: published.append(kind)
    live.recover()
    assert not published and statuses(live, 1) == ["VALID_CONTROL"]
    assert live.repo.results(1)[0].controls == 1
    assert len(live.repo.audit(1)) == 1
    for table in tables:
        assert [tuple(r) for r in store.db.execute(f"SELECT * FROM {table}")] == original[table]
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(ValueError, match="already exists"):
        live.put_master_category(
            CategoryData(code="OPEN", display_name_en="Open", display_name_de="Offen")
        )
    store.close()


def test_import_storage_failure_rolls_back_new_people_clubs_and_audits(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "rollback.db")
    before = live.repo.master_audit()
    store.db.execute(
        "CREATE TRIGGER fail_registration BEFORE INSERT ON live_entries WHEN NEW.start_number=3 BEGIN SELECT RAISE(ABORT,'disk unavailable'); END"
    )
    text = "start_number,first_name,last_name,category,birth_year,club,club_code\n2,Anna,Meyer,OPEN,1980,Test,P01\n3,Peter,Test,OPEN,1970,Test,P01\n"
    assert csvio.preview(live, event, text)["valid"]
    assert live.repo.clubs() == [] and len(live.repo.runners()) == 1
    with pytest.raises(sqlite3.IntegrityError):
        csvio.import_participants(live, event, text)
    assert live.repo.clubs() == [] and len(live.repo.runners()) == 1
    assert live.repo.master_audit() == before and len(live.repo.entries(event)) == 1
    store.close()


def test_reusable_master_restart_and_no_historical_notifications(tmp_path: Path) -> None:
    path = tmp_path / "restart-master.db"
    store, live, ingest, event, _ = setup(path, Timing.PREDEFINED_START)
    punch(ingest, 1, 1)
    before = live.snapshot(event)
    audit = live.repo.master_audit()
    store.close()
    store = Store(path)
    published: list[str] = []
    live = LiveService(
        LiveRepository(store), publish=lambda kind, _event, _payload: published.append(kind)
    )
    live.recover()
    assert live.snapshot(event)["participants"] == before["participants"]
    assert live.snapshot(event)["results"] == before["results"]
    assert not published and live.repo.master_audit() == audit
    assert len(live.repo.runners()) == 1 and len(live.repo.master_categories()) == 1
    store.close()
