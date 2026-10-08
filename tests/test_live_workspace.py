"""Event-desk IA, explicit quick-create and read-only display regressions."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_live_web import STAMP, UID, configure, receive, request, runtime

from foxlive.web import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path / "workspace.db"), base_url="http://127.0.0.1") as test:
        yield test


@pytest.mark.parametrize(
    "path",
    [
        "/live",
        "/master/runners",
        "/master/clubs",
        "/master/categories",
        "/system/diagnostics",
        "/system/base",
        "/system/settings",
    ],
)
def test_workspace_routes_and_hidden_internal_keys(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert 'id="top-nav"' in response.text and 'id="sub-nav"' in response.text
    assert 'role="combobox"' in response.text and 'role="listbox"' in response.text
    assert 'name="id"' not in response.text
    assert 'type="hidden" name="runner_id"' in response.text
    assert 'type="hidden" name="category_id"' in response.text


def test_event_deep_links_and_display_read_only_template(client: TestClient) -> None:
    event, _, _ = configure(client)
    for section in ("overview", "participants", "categories", "stations", "live", "rankings"):
        response = client.get(f"/events/{event}/{section}")
        assert response.status_code == 200 and "&lt;script&gt;desk&lt;/script&gt;" in response.text
    html = client.get("/live/display").text
    assert "fullscreen" in html and "display.js" in html and 'id="language"' in html
    assert "participant-form" not in html and "COM" not in html and "data-edit" not in html
    assert "<form" not in html and "<input" not in html
    for asset in ("combobox.js", "workspace.js", "display.js", "display.css"):
        assert client.get("/static/" + asset).status_code == 200


def test_explicit_club_review_normalization_duplicates_and_no_merging(client: TestClient) -> None:
    data = {"code": " S01 ", "display_name": " DARC  OV Schwerin "}
    club = request(client, "/api/ui/quick-club", {"club": data})
    assert club["code"] == "S01" and club["display_name"] == "DARC OV Schwerin"
    exact = request(client, "/api/ui/club-matches", {"code": "s01", "display_name": "Other"})
    assert exact["exact"][0]["id"] == club["id"]
    for duplicate in (
        {"code": "s01", "display_name": "Other"},
        {"code": "S99", "display_name": "darc ov schwerin"},
    ):
        result = client.post(
            "/api/ui/quick-club",
            json={"club": duplicate, "allow_similar": True},
            headers={"Accept-Language": "de"},
        )
        assert result.status_code == 422 and "vorhanden" in result.json()["detail"]
    other = {"code": "S10", "display_name": "OV Schwerin"}
    candidates = request(client, "/api/ui/club-matches", other)
    assert not candidates["exact"] and candidates["similar"][0]["id"] == club["id"]
    response = client.post("/api/ui/quick-club", json={"club": other})
    assert response.status_code == 422
    assert len(client.get("/api/clubs").json()) == 1
    created = request(client, "/api/ui/quick-club", {"club": other, "allow_similar": True})
    assert created["id"] != club["id"] and len(client.get("/api/clubs").json()) == 2


def test_staged_club_runner_registration_is_atomic_and_preserves_source(client: TestClient) -> None:
    event, category, _ = configure(client)
    receive(client)
    before = client.get("/api/source-punches").json()
    root = f"/api/events/{event}"
    payload: dict[str, Any] = {
        "runner": {"first_name": "Anna", "last_name": "Example", "birth_year": 1990},
        "club": {"code": "X23", "display_name": "Independent DX Group"},
        "entry": {"start_number": 17, "category_id": category, "uid": UID},
    }
    # A rejected registration must not leave staged club/person/audit debris.
    audits = client.get("/api/master/audit").json()
    assert client.post(root + "/register-new-runner", json=payload).status_code == 422
    assert client.get("/api/clubs").json() == []
    assert len(client.get("/api/runners").json()) == 1
    assert client.get("/api/master/audit").json() == audits
    payload["entry"]["start_number"] = 18
    entry = request(client, root + "/register-new-runner", payload)
    club = client.get("/api/clubs").json()[0]
    person = next(r for r in client.get("/api/runners").json() if r["id"] == entry["runner_id"])
    assert person["club_id"] == club["id"] and "uid" not in person
    assert entry["club_code"] == "X23" and entry["uid"] == UID
    assert client.get(root + f"/participants/{entry['id']}").json()["result"]["controls"] == 1
    assert client.get("/api/source-punches").json() == before


def test_category_quick_create_enable_and_duplicate_rollback(client: TestClient) -> None:
    event, _, _ = configure(client)
    endpoint = f"/api/events/{event}/quick-category"
    data = {"code": "M40", "display_name_en": "Men 40", "display_name_de": "Männer 40"}
    selection = request(client, endpoint, data)
    master = next(
        c for c in client.get("/api/master/categories").json() if c["id"] == selection["id"]
    )
    assert selection["enabled"] and master["display_name_de"] == "Männer 40"
    assert client.post(endpoint, json=data | {"code": " m40 "}).status_code == 422
    assert len(client.get("/api/master/categories").json()) == 2
    request(client, f"/api/events/{event}/state", {"state": "CLOSED"})
    request(client, f"/api/events/{event}/state", {"state": "ARCHIVED"})
    assert client.post(endpoint, json=data | {"code": "M50"}).status_code == 422
    assert len(client.get("/api/master/categories").json()) == 2


def test_runner_review_history_summary_and_snapshot_preservation(client: TestClient) -> None:
    event, category, entry = configure(client)
    matches = request(
        client,
        "/api/ui/runner-matches",
        {"first_name": " max ", "last_name": "müller", "birth_year": 1980},
    )
    assert len(matches) == 1
    runner = matches[0]
    history = client.get(f"/api/runners/{runner['id']}/history").json()
    assert history[0]["id"] == entry and history[0]["category_id"] == category
    request(
        client,
        f"/api/runners/{runner['id']}",
        {"first_name": "Corrected", "last_name": "Müller", "birth_year": 1980},
        "PUT",
    )
    assert client.get(f"/api/runners/{runner['id']}/history").json()[0]["first_name"] == "Max"
    summary = client.get("/api/ui/master-summary").json()
    assert summary["runners"] == [{"id": runner["id"], "count": 1, "last_date": "2026-10-06"}]
    assert summary["categories"] == [{"id": category, "count": 1}]
    assert client.get(f"/events/{event}/participants").status_code == 200


def test_public_http_and_websocket_do_not_leak_tag_or_diagnostics(client: TestClient) -> None:
    event, category, entry = configure(client)
    root = f"/api/events/{event}"
    participant = client.get(root + f"/participants/{entry}").json()["participant"]
    request(
        client,
        root + f"/participants/{entry}",
        {
            "start_number": 17,
            "runner_id": participant["runner_id"],
            "category_id": category,
            "uid": UID,
        },
        "PUT",
    )
    with (
        client.websocket_connect(f"ws://127.0.0.1/ws/display?event_id={event}") as first,
        client.websocket_connect(f"ws://127.0.0.1/ws/display?event_id={event}") as second,
    ):
        assert first.receive_json()["type"] == second.receive_json()["type"] == "snapshot"
        receive(client)
        for ws in (first, second):
            message = ws.receive_json()
            assert message["type"] == "punch_received" and message["payload"] == {}
            assert ws.receive_json()["type"] == "ranking_changed"
    receive(client, uid="04AB", seconds=2)
    state = client.get(f"/api/display?event_id={event}").json()
    assert state["results"][0]["controls"] == 1 and state["recent"][0]["participant_id"] is None
    text = json.dumps(state)
    for key in (
        UID,
        "04AB",
        "rssi",
        "callsign",
        "source",
        "diagnostics",
        "audit",
        "raw_event",
        "uid",
        "source_port",
    ):
        assert key not in text
    # Reconnection retrieves current state, not a historical punch stream.
    with client.websocket_connect(f"ws://127.0.0.1/ws/display?event_id={event}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert {k: v for k, v in snapshot["payload"].items() if k != "now"} == {
            k: v for k, v in state.items() if k != "now"
        }
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1/ws/display?event_id=999999"):
            pass


def test_realistic_bulk_data_projection_uses_bounded_query_count(client: TestClient) -> None:
    event, category, _ = configure(client)
    root = f"/api/events/{event}"
    request(client, root + "/state", {"state": "CLOSED"})
    for index in range(200):
        request(
            client,
            "/api/clubs",
            {"code": f"C{index:03}", "display_name": f"Association {index:03}"},
        )
    for index in range(49):
        request(
            client,
            root + "/quick-category",
            {
                "code": f"CAT{index:02}",
                "display_name_en": f"Class {index}",
                "display_name_de": f"Klasse {index}",
            },
        )
    csv = "start_number,first_name,last_name,birth_year,category,uid,club_code,club\n" + "\n".join(
        f"{i + 100},Runner,Person{i:03},1980,OPEN,{i:08X},C{i % 200:03},Association {i % 200:03}"
        for i in range(499)
    )
    result = request(client, root + "/import", {"text": csv, "commit": True})
    assert result["valid"] and result["count"] == 499
    ids: list[int] = []
    queries: list[str] = []

    def seed_and_project() -> dict[str, Any]:
        owner = runtime(client)
        for index in range(3000):
            raw = json.dumps(
                {
                    "type": "tag",
                    "station": 1,
                    "sequence": index,
                    "timestamp": STAMP + index,
                    "uid": f"{index % 499:08X}",
                }
            ).encode()
            fact = owner.ingest.ingest(
                raw, "serial:FAKE", datetime.fromtimestamp(STAMP + index, UTC)
            )
            assert fact is not None and fact.id is not None
            ids.append(fact.id)
        owner.live.associate(event, ids)
        owner.live.repo.db.set_trace_callback(queries.append)
        try:
            return owner.live.snapshot(event)
        finally:
            owner.live.repo.db.set_trace_callback(None)

    assert client.portal is not None
    state = client.portal.call(seed_and_project)
    assert len(state["participants"]) == 500 and len(state["categories"]) == 50
    assert len(client.get("/api/clubs").json()) == 200
    assert len(client.get("/api/runners?limit=10000").json()) == 500
    assert len(ids) == 3000
    assert sum(r["controls"] for r in state["results"]) == 499
    assert len(queries) < 25  # Bulk projection must not do a query per registration.
    assert len(client.get(f"/api/display?event_id={event}").json()["recent"]) == 12
