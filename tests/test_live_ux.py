"""Presentation regressions; source facts/scoring remain owned by accepted M3 services."""

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter

import pytest
from fastapi.testclient import TestClient
from test_live_web import STAMP, UID, configure, receive, request, runtime

from foxlive import presentation
from foxlive.models import CompetitionStatus, InterpretationStatus, Role, State, Timing, instant
from foxlive.web import create_app

ASSETS = Path(__file__).resolve().parents[1] / "src" / "foxlive"


def test_catalogs_complete_valid_and_same_placeholders() -> None:
    en, de = presentation.catalog("en"), presentation.catalog("de")
    assert set(en) == set(de)
    for key in en:
        assert en[key].strip() and de[key].strip()
        assert {field for _, field, _, _ in Formatter().parse(en[key]) if field} == {
            field for _, field, _, _ in Formatter().parse(de[key]) if field
        }, key
    for prefix, enum in [
        ("event", State),
        ("timing", Timing),
        ("station", Role),
        ("participant", CompetitionStatus),
        ("punch", InterpretationStatus),
    ]:
        assert all(f"{prefix}.{item}" in en for item in enum)
    # Literal keys used by the templates/script must exist, not leak to the desk.
    source = "".join(path.read_text() for path in (ASSETS / "templates").glob("*.html")) + "".join(
        path.read_text() for path in (ASSETS / "static").glob("*.js")
    )
    for key in re.findall(r'["\']([a-z]+\.[a-zA-Z_-]+)["\']', source):
        if key.startswith("foxlive.") or key.endswith((".css", ".js")):
            continue
        assert key in en, key
    for code in ("en", "de"):
        pairs = json.loads(
            (ASSETS / "static" / "translations" / f"{code}.json").read_text(),
            object_pairs_hook=list,
        )
        assert len(pairs) == len(dict(pairs)), "Duplicate catalog keys"


def test_english_default_and_translation_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    en = presentation.catalog("en")
    assert presentation.language("") == "en"
    assert presentation.language("fr-FR") == "en"
    assert presentation.language("de-DE,de;q=0.9") == "de"
    monkeypatch.setattr(presentation, "catalog", lambda lang: en if lang == "en" else {})
    assert presentation.translate("participant.start_number", "de") == "Start number"
    assert presentation.translate("unimplemented.key", "de") == "Unavailable"


@pytest.mark.parametrize(
    "key,word",
    [
        ("participant.RUNNING", "Unterwegs"),
        ("participant.FINISHED", "Im Ziel"),
        ("station.FINISH", "Ziel"),
        ("punch.UNKNOWN_UID", "Unbekannter"),
        ("participant.start_number", "Startnummer"),
        ("event.label", "Veranstaltung"),
    ],
)
def test_localized_domain_labels(key: str, word: str) -> None:
    assert word in presentation.translate(key, "de")


def test_form_ids_generated_categories_and_native_controls(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "labels.db"), base_url="http://127.0.0.1") as client:
        html = client.get("/", headers={"Accept-Language": "de"}).text
        assert '<html lang="en">' in html  # The browser preference, not OS locale, decides.
        assert 'id="language"' in html and "English" in html and "Deutsch" in html
        assert "Start number" in html and ">Bib<" not in html
        assert 'name="id"' not in html and "Category ID" not in html
        assert 'name="punch_ids"' not in html
        assert html.count('type="datetime-local"') == 5  # M5 adds explicit manual evidence time.
        assert 'type="date"' in html and "Local ISO time" not in html
        event, category, _ = configure(client)
        other = request(
            client,
            "/api/master/categories",
            {"code": "M40", "display_name_en": "Men 40", "display_name_de": "Männer 40"},
        )
        assert category != other["id"] and other["id"] > 0
        assert (
            client.post(
                f"/api/events/{event}/categories", json={"id": 9, "code": "X", "display_name": "X"}
            ).status_code
            == 422
        )
        for file in ("en.json", "de.json"):
            response = client.get("/static/translations/" + file)
            assert response.status_code == 200
            assert "participant.start_number" in response.json()
        assert client.get("/static/presentation.js").status_code == 200


def test_capture_next_live_uid_confirm_history_collision_and_no_source_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "capture.db"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        event, category, entry = configure(client)
        root = f"/api/events/{event}"
        old = receive(client, uid="04BB")
        endpoint = root + "/rfid-candidates"
        baseline = client.get(endpoint).json()
        assert baseline["cursor"] == old
        data = {
            "start_number": 17,
            "runner_id": client.get(f"{root}/participants/{entry}").json()["participant"][
                "runner_id"
            ],
            "category_id": category,
        }
        assert client.get(root + f"/participants/{entry}").json()["participant"]["uid"] is None
        # Only the new live unassigned tag is observed, not the older registration punch.
        seen = receive(client, seconds=2)
        retry = receive(client, seconds=2)
        receive(client, seconds=3, uid="04CC")
        batch = client.get(endpoint + "?after_id=" + str(baseline["cursor"])).json()
        assert batch["items"][0]["id"] == seen and batch["items"][0]["uid"] == UID
        assert retry not in [v["id"] for v in batch["items"]]
        assert batch["items"][0]["station_name"] == "Fox 1"
        before = client.get("/api/source-punches").json()
        # Capture is read-only: no implicit assignment until the existing PUT is confirmed.
        assert client.get(root + f"/participants/{entry}").json()["result"]["controls"] == 0
        request(client, root + f"/participants/{entry}", data | {"uid": UID}, "PUT")
        history = client.get(root + f"/participants/{entry}").json()
        assert history["result"]["controls"] == 1
        assert {p["status"] for p in history["history"]} == {"VALID_CONTROL", "SOURCE_DUPLICATE"}
        assert all(v["uid"] != UID for v in client.get(endpoint).json()["items"])
        response = client.post(
            root + "/participants",
            json=data | {"start_number": 18, "uid": UID},
            headers={"Accept-Language": "de"},
        )
        assert response.status_code == 422
        assert "Startnummer 17" in response.json()["detail"]
        assert "046365525C6180" in response.json()["detail"]
        assert client.get("/api/source-punches").json() == before
        audit = client.get(f"/api/audit?event_id={event}").json()
        assert any(r["after"].get("uid") == UID for r in audit if isinstance(r["after"], dict))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 4


def test_read_tags_during_draft_and_invalid_time_without_scoring(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "draft.db"), base_url="http://127.0.0.1") as client:
        event = request(
            client,
            "/api/events",
            {"name": "Registration", "date": "2026-10-06", "timezone": "Europe/Berlin"},
        )["id"]
        source_id = receive(client)
        candidates = client.get(f"/api/events/{event}/rfid-candidates").json()
        assert candidates["items"][0]["id"] == source_id
        assert client.get(f"/api/punches?event_id={event}").json() == []

        def presync() -> None:
            runtime(client).ingest.ingest(
                b'{"type":"tag","station":1,"timestamp":5,"uid":"04DD","sequence":9}',
                "serial:FAKE",
                datetime.fromtimestamp(STAMP, UTC),
            )

        assert client.portal is not None
        client.portal.call(presync)
        candidates = client.get(f"/api/events/{event}/rfid-candidates").json()
        assert not candidates["items"][0]["station_time_valid"]
        assert (
            candidates["items"][0]["uid"] == "04DD"
        )  # Identity read is not a race-time correction.


def test_candidate_scope_recent_uniqueness_inactive_and_replay(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "scope.db"), base_url="http://127.0.0.1") as client:
        event, category, entry = configure(client)
        root = f"/api/events/{event}"
        receive(client)
        newest = receive(client, seconds=2)
        assert [v["id"] for v in client.get(root + "/rfid-candidates").json()["items"]] == [newest]
        data = {
            "start_number": 17,
            "runner_id": client.get(f"{root}/participants/{entry}").json()["participant"][
                "runner_id"
            ],
            "category_id": category,
            "uid": UID,
            "active": False,
        }
        request(client, root + f"/participants/{entry}", data, "PUT")
        assert client.get(root + "/rfid-candidates").json()[
            "items"
        ]  # Inactive entries don't own a tag.

        def replay() -> None:
            runtime(client).ingest.ingest(
                b'{"type":"tag","station":1,"timestamp":1791280803,"uid":"04EE","sequence":3}',
                "replay",
                datetime.fromtimestamp(STAMP + 3, UTC),
                replayed=True,
                scope="replay:test",
            )

        assert client.portal is not None
        client.portal.call(replay)
        assert all(
            v["uid"] != "04EE" for v in client.get(root + "/rfid-candidates").json()["items"]
        )
        assert client.get(root + "/rfid-candidates?after_id=-1").status_code == 422
        assert client.get(root + "/rfid-candidates?limit=101").status_code == 422
        request(client, root + f"/participants/{entry}", data | {"active": True}, "PUT")
        other = request(client, "/api/events", {"name": "Next", "date": "2026-10-07"})["id"]
        assert client.get(f"/api/events/{other}/rfid-candidates").json()[
            "items"
        ]  # Event-scoped ownership.


@pytest.mark.parametrize(
    "value,timezone,expected",
    [
        ("2026-10-06T14:30", "Europe/Berlin", "2026-10-06T12:30:00+00:00"),
        ("2026-10-06T14:30", "UTC", "2026-10-06T14:30:00+00:00"),
        ("2026-10-07T00:30", "Europe/Berlin", "2026-10-06T22:30:00+00:00"),
    ],
)
def test_native_local_time_normal_and_midnight(value: str, timezone: str, expected: str) -> None:
    options = presentation.local_time_options(value, timezone)
    assert len(options) == 1 and options[0]["instant"] == expected
    assert instant(options[0]["instant"], timezone) == expected


def test_native_local_time_dst_choices_gaps_and_localized_errors(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "times.db"), base_url="http://127.0.0.1") as client:
        data = {"value": "2026-10-25T02:30", "timezone": "Europe/Berlin"}
        options = request(client, "/api/ui/local-time", data)["options"]
        assert [o["instant"] for o in options] == [
            "2026-10-25T00:30:00+00:00",
            "2026-10-25T01:30:00+00:00",
        ]
        assert [o["offset"] for o in options] == ["+02:00", "+01:00"]
        for value in (
            "0001-01-01T00:00",
            "2026-03-29T02:30",
            "not a date",
            "2026-10-06T14:30Z",
            "2026-10-06T14:30:00.5",
        ):
            response = client.post(
                "/api/ui/local-time",
                json=data | {"value": value},
                headers={"Accept-Language": "de"},
            )
            assert response.status_code == 422
            assert "Traceback" not in response.text
        gap = client.post(
            "/api/ui/local-time",
            json=data | {"value": "2026-03-29T02:30"},
            headers={"Accept-Language": "de"},
        )
        assert "existiert" in gap.json()["detail"]
        assert runtime_no_writes(client) == 0


def runtime_no_writes(client: TestClient) -> int:
    assert client.portal is not None
    return int(client.portal.call(lambda: runtime(client).store.stats()["raw_events"]))


def test_localized_validation_messages_and_csv(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "validation.db"), base_url="http://127.0.0.1") as client:
        headers = {"Accept-Language": "de"}
        response = client.post(
            "/api/events",
            json={"name": "Race", "date": "2026-10-06", "timezone": "Bad/Zone"},
            headers=headers,
        )
        assert "zeitzone" in response.json()["detail"].lower()
        event, category, _ = configure(client)
        response = client.post(
            f"/api/events/{event}/participants",
            json={"start_number": 0, "first_name": "A", "last_name": "B", "category_id": category},
            headers=headers,
        )
        assert response.status_code == 422 and "Mindestwert" in response.json()["detail"][0]["msg"]
        assert "Minimum" in response.json()["ui_detail"]["en"][0]["msg"]
        response = client.post(
            f"/api/events/{event}/import",
            json={"text": "start_number,first_name,last_name,category\n19,A,B,MISSING\n"},
            headers=headers,
        )
        assert not response.json()["valid"]
        assert "Kategorie" in response.json()["errors"][0]["error"]
        assert "Category" in response.json()["errors"][0]["ui_error"]["en"]


@pytest.mark.parametrize("case", ["language", "fallback", "labels", "dates", "capture"])
def test_browser_presentation_helpers(case: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Optional Node.js runner for dependency-free browser helper tests")
    subprocess.run(
        [node, str(Path(__file__).parent / "fixtures" / "live_presentation.js"), str(ASSETS), case],
        check=True,
        capture_output=True,
        text=True,
    )
