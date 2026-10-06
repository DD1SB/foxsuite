import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from foxcore.config import Config, SerialConfig, TimeSyncConfig
from foxcore.events import ConnectionEvent
from foxlive.config import LiveConfig
from foxlive.web import Hub, Runtime, create_app

STAMP = 1791280800
UID = "046365525C6180"


def runtime(client: TestClient) -> Runtime:
    return cast(Runtime, cast(FastAPI, client.app).state.runtime)


def request(client: TestClient, url: str, data: dict[str, Any], method: str = "POST") -> Any:
    response = client.request(method, url, json=data)
    assert response.status_code == 200, response.text
    return response.json()


def configure(client: TestClient) -> tuple[int, int, int]:
    event = request(
        client,
        "/api/events",
        {
            "name": "<script>desk</script>",
            "date": "2026-10-06",
            "timezone": "Europe/Berlin",
            "timing_mode": "PREDEFINED_START",
            "default_start_at": datetime.fromtimestamp(STAMP, UTC).isoformat(),
        },
    )["id"]
    root = f"/api/events/{event}"
    category = request(client, root + "/categories", {"code": "OPEN", "display_name": "Open"})["id"]
    entry = request(
        client,
        root + "/participants",
        {"start_number": 17, "first_name": "Max", "last_name": "Müller", "category_id": category},
    )["id"]
    for station, role in [(1, "CONTROL"), (11, "FINISH")]:
        request(
            client,
            root + f"/stations/{station}",
            {"station_id": station, "display_name": "Fox " + str(station), "role": role},
            "PUT",
        )
    request(client, root + "/state", {"state": "RUNNING"})
    return event, category, entry


def receive(client: TestClient, station: int = 1, seconds: int = 1, uid: str = UID) -> int:
    def on_owner() -> int:
        owner = runtime(client)
        raw = json.dumps(
            {
                "type": "tag",
                "station": station,
                "sequence": seconds,
                "timestamp": STAMP + seconds,
                "uid": uid,
                "rssi": -70,
                "callsign": "DD1SB",
            }
        ).encode()
        result = owner.ingest.ingest(
            raw, "serial:FAKE", datetime.fromtimestamp(STAMP + seconds, UTC)
        )
        assert result is not None and result.id is not None
        return result.id

    assert client.portal is not None
    return client.portal.call(on_owner)


def test_dashboard_crud_unknown_exclusion_and_source_immutable(tmp_path: Path) -> None:
    path = tmp_path / "web.db"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        assert client.get("/").status_code == 200
        event, category, entry = configure(client)
        root = f"/api/events/{event}"
        html = client.get("/")
        assert "&lt;script&gt;desk&lt;/script&gt;" in html.text
        assert "<script>desk</script>" not in html.text
        assert "script-src 'self'" in html.headers["content-security-policy"]
        assert client.get("/static/desk.js").status_code == 200
        assert client.get("/static/desk.css").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 200
        source_id = receive(client)
        assert client.get("/api/status").json()["unknown"][0]["id"] == source_id
        data = {
            "start_number": 17,
            "first_name": "Max",
            "last_name": "Müller",
            "category_id": category,
            "uid": UID,
        }
        request(client, root + f"/participants/{entry}", data, "PUT")
        assert client.get("/api/status").json()["unknown"] == []
        assert client.get(f"/api/rankings?event_id={event}").json()[0]["controls"] == 1
        receive(client, seconds=2)
        receive(client, station=11, seconds=3)
        result = client.get(f"/api/rankings?event_id={event}").json()[0]
        assert result["rank"] == 1 and result["elapsed"] == 3 and result["controls"] == 1
        detail = client.get(root + f"/participants/{entry}").json()
        assert [p["status"] for p in detail["history"]] == [
            "VALID_CONTROL",
            "REPEAT_CONTROL",
            "VALID_FINISH",
        ]
        request(client, root + f"/punches/{source_id}/exclude", {"reason": "Wrong competitor"})
        assert (
            client.get(f"/api/punches?event_id={event}").json()[-1]["status"] == "MANUALLY_EXCLUDED"
        )
        assert request(client, root + "/recalculate", {})["MANUALLY_EXCLUDED"] == 1
        category_data = {"code": "OPEN", "display_name": "Open renamed", "active": False}
        request(client, root + f"/categories/{category}", category_data, "PUT")
        assert client.get(f"/api/rankings?event_id={event}").json()[0]["rank"] is None
        request(client, root + f"/participants/{entry}", data | {"active": False}, "PUT")
        assert not client.get(f"/api/participants?event_id={event}").json()[0]["active"]
        assert not client.get(f"/api/categories?event_id={event}").json()[0]["active"]
        station = client.get(f"/api/stations?event_id={event}").json()[0]
        assert (
            station["punch_count"] == 2
            and station["callsign"] == "DD1SB"
            and station["rssi"] == -70
        )
        assert client.get(root + "/export/results").headers["content-type"].startswith("text/csv")
        audit = client.get(f"/api/audit?event_id={event}").json()
        assert any(a["action"] == "manual_exclusion" and a["reason"] for a in audit)
        assert client.get("/api/source-punches").json()[0]["station_timestamp"] == STAMP + 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 3
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_websocket_publication_reconnect_and_broken_client(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "ws.db"), base_url="http://127.0.0.1") as client:
        event, _, _ = configure(client)
        with client.websocket_connect("ws://127.0.0.1/ws") as socket:
            assert socket.receive_json()["type"] == "snapshot"
            receive(client)
            messages = [socket.receive_json() for _ in range(5)]
            assert {m["type"] for m in messages} == {
                "punch_received",
                "ranking_changed",
                "station_updated",
                "participant_updated",
                "unknown_uid",
            }
            assert all(m["version"] == 1 and m["event_id"] == event for m in messages)
        receive(client, seconds=2)  # A disconnected subscriber cannot stop processing.
        with client.websocket_connect("ws://127.0.0.1/ws") as socket:
            assert len(socket.receive_json()["payload"]["recent"]) == 2
            request(client, f"/api/events/{event}/state", {"state": "CLOSED"})
            assert socket.receive_json()["type"] == "event_state_changed"
            assert socket.receive_json()["type"] == "ranking_changed"
        receive(client, seconds=3)
        assert len(client.get(f"/api/punches?event_id={event}").json()) == 2


def test_http_validation_origin_csv_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart-web.db"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        event, category, entry = configure(client)
        root = f"/api/events/{event}"
        invalid = client.post(
            "/api/events", json={"name": "Bad", "date": "2026-10-06", "timezone": "Not/AZone"}
        )
        assert invalid.status_code == 422 and "Unknown IANA" in invalid.json()["detail"]
        assert client.post(root + "/state", json={"state": "ARCHIVED"}).status_code == 422
        second = request(client, "/api/events", {"name": "Next", "date": "2026-10-07"})["id"]
        assert (
            "another event"
            in client.post(f"/api/events/{second}/state", json={"state": "RUNNING"}).text
        )
        response = client.post(
            "/api/events",
            json={"name": "Bad", "date": "2026-10-06"},
            headers={"Origin": "https://elsewhere.invalid"},
        )
        assert response.status_code == 403
        assert client.post("/api/events", content="name=bad").status_code == 415
        assert client.get("/", headers={"Host": "elsewhere.invalid"}).status_code == 400
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1/ws", headers={"Origin": "https://elsewhere.invalid"}
            ):
                pass
        data = {
            "start_number": 17,
            "first_name": "Max",
            "last_name": "Müller",
            "category_id": category,
            "uid": UID,
        }
        request(client, root + f"/participants/{entry}", data, "PUT")
        assert client.post(root + "/participants", json=data).status_code == 422
        assert (
            client.put(
                root + "/stations/7",
                json={"station_id": 1, "role": "CONTROL", "display_name": "Bad"},
            ).status_code
            == 422
        )
        text = "start_number,first_name,last_name,category,uid\n18,Anna,Meyer,OPEN,04AA\n"
        assert request(client, root + "/import", {"text": text})["count"] == 1
        assert len(client.get(f"/api/participants?event_id={event}").json()) == 1
        assert request(client, root + "/import", {"text": text, "commit": True})["valid"]
        assert not request(client, root + "/import", {"text": text, "commit": True})["valid"]
        assert "Müller" in client.get(root + "/export/participants").text
        receive(client)
        receive(client, 11, 5)
        before = client.get(f"/api/rankings?event_id={event}").json()
    with TestClient(create_app(path), base_url="http://127.0.0.1") as restarted:
        assert restarted.get("/api/status").json()["active_event_id"] == event
        assert restarted.get(f"/api/rankings?event_id={event}").json() == before
        with restarted.websocket_connect("ws://127.0.0.1/ws") as socket:
            initial = socket.receive_json()
            assert initial["type"] == "snapshot" and len(initial["payload"]["recent"]) == 2
        assert request(restarted, root + "/recalculate", {})["source_punches"] == 2
        request(restarted, root + "/state", {"state": "CLOSED"})
        request(restarted, root + "/state", {"state": "ARCHIVED"})
        assert restarted.put(root + f"/participants/{entry}", json=data).status_code == 422
        assert len(restarted.get("/api/events").json()) == 2


def test_hub_slow_client_resync() -> None:
    hub = Hub(capacity=1)
    slow, fast = hub.subscribe(), hub.subscribe()
    hub.publish("punch_received", 1, {"punch_id": 1})
    assert fast.get_nowait()["payload"]["punch_id"] == 1
    hub.publish("punch_received", 1, {"punch_id": 2})
    assert slow.get_nowait()["type"] == "resync"
    assert fast.get_nowait()["type"] == "punch_received"


def test_accepted_serial_and_timesync_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxcore.serial import FakeTransport

    class Transport(FakeTransport):
        async def run(self, line: Any, state: Any) -> None:
            import asyncio

            await self.connect()
            await state(ConnectionEvent(True, "fake"))
            await line(b"malformed debug line\n")
            await asyncio.Event().wait()

    transport = Transport()
    monkeypatch.setattr("foxlive.web.SerialTransport", lambda config: transport)
    core = Config(serial=SerialConfig("FAKE"), time_sync=TimeSyncConfig(interval_seconds=60))
    with TestClient(
        create_app(tmp_path / "source.db", core, serial_enabled=True), base_url="http://127.0.0.1"
    ) as client:
        # The TestClient lifespan/task startup is asynchronous; use its loop to await progress.
        async def ready() -> None:
            import asyncio

            async with asyncio.timeout(2):
                while not transport.commands or not runtime(client).store.stats()["raw_events"]:
                    await asyncio.sleep(0.001)

        assert client.portal is not None
        client.portal.call(ready)
        diagnostics = client.get("/api/status").json()["diagnostics"]
        assert diagnostics["connection"]["connected"] and diagnostics["timesync"]["success"]
        assert transport.commands[0].startswith(b"TIME ") and transport.commands[0].endswith(b"\n")
    assert not transport.connected


def test_live_configuration_and_missing_source(tmp_path: Path) -> None:
    from foxlive.config import load_live_config

    assert load_live_config(None) == LiveConfig()
    with pytest.raises(ValueError):
        LiveConfig(port=0)
    with pytest.raises(ValueError, match="serial port"):
        with TestClient(create_app(tmp_path / "missing.db", serial_enabled=True)):
            pass
