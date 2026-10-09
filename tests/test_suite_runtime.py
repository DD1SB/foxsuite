"""M4.1 shared ownership, module isolation and operator lifecycle regressions."""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foxbridge.config import BridgeConfig, OutputConfig
from foxbridge.output import FakeOutput
from foxcore.config import Config, SerialConfig, TimeSyncConfig
from foxcore.serial import FakeTransport
from foxlive.service import LiveService
from foxops import ports
from foxops.runtime import FoxSuiteRuntime
from foxops.settings import Locations, Settings, encode, load, save
from foxops.web import ConnectionTestInput, Controller, create_app

UID = "046365525C6180"


class Sources:
    def __init__(self) -> None:
        self.instances: list[FakeTransport] = []
        self.active = 0
        self.maximum = 0

    def create(self, config: SerialConfig) -> FakeTransport:
        owner = self

        class Tracked(FakeTransport):
            async def connect(self) -> None:
                await super().connect()
                owner.active += 1
                owner.maximum = max(owner.maximum, owner.active)

            async def disconnect(self) -> None:
                if self.connected:
                    owner.active -= 1
                await super().disconnect()

        result = Tracked()
        self.instances.append(result)
        return result


@pytest.fixture
def suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Controller, Sources, list[FakeOutput]]]:
    locations = Locations(tmp_path / "user")
    locations.create()
    settings = Settings(
        Config(SerialConfig("COM3"), locations.database, TimeSyncConfig(interval_seconds=0.05)),
        completed=True,
        bridge=BridgeConfig(enabled=True, output=OutputConfig(port="COM10")),
    )
    save(locations, settings)
    sources, outputs = Sources(), []
    monkeypatch.setattr("foxops.runtime.SerialTransport", sources.create)
    monkeypatch.setattr(ports, "enumerate_ports", lambda: [])

    def output(config: OutputConfig) -> FakeOutput:
        result = FakeOutput()
        outputs.append(result)
        return result

    monkeypatch.setattr("foxops.runtime.create_output", output)
    controller = Controller(locations, settings, lambda: None)
    app = create_app(controller)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.portal is not None
        client.portal.call(asyncio.sleep, 0.01)
        yield client, controller, sources, outputs
        supervisor: FoxSuiteRuntime = app.state.supervisor
    assert supervisor.closed and supervisor.source_task is None and supervisor.bridge_task is None
    assert sources.active == 0 and sources.maximum == 1
    assert all(not output.connected for output in outputs)
    with pytest.raises(sqlite3.ProgrammingError):
        supervisor.owner.store.db.execute("SELECT 1")


def post(client: TestClient, path: str, value: dict[str, Any]) -> Any:
    response = client.post(path, json=value)
    assert response.status_code == 200, response.text
    return response.json()


def receive(client: TestClient, sources: Sources, sequence: int) -> None:
    async def check() -> None:
        runtime: FoxSuiteRuntime = cast(FastAPI, client.app).state.supervisor
        before = runtime.owner.store.stats()["raw_events"]
        await sources.instances[-1].input.put(
            json.dumps(
                {
                    "type": "tag",
                    "station": 1,
                    "timestamp": int(datetime.now(UTC).timestamp()),
                    "sequence": sequence,
                    "uid": UID,
                }
            ).encode()
        )
        async with asyncio.timeout(2):
            while runtime.owner.store.stats()["raw_events"] == before:
                await asyncio.sleep(0.001)
            if runtime.bridge is not None:
                await runtime.bridge.drain()

    assert client.portal is not None
    client.portal.call(check)


def mappings(client: TestClient) -> None:
    post(client, "/api/ops/bridge/mappings/uid", {"uid": UID, "card_number": 912345})
    post(client, "/api/ops/bridge/mappings/station", {"station_id": 1, "control_code": 31})


def test_one_ingest_fans_out_to_live_and_bridge(suite: tuple[Any, ...]) -> None:
    client, controller, sources, outputs = suite
    mappings(client)
    event = post(client, "/api/events", {"name": "Shared receiver", "date": "2026-10-09"})
    post(client, f"/api/events/{event['id']}/state", {"state": "RUNNING"})
    receive(client, sources, 1)
    status = client.get("/api/ops/status").json()
    assert status["product"] == "FoxSuite" and status["process_model"] == "single_process"
    assert status["core"]["statistics"]["raw_events"] == 1
    assert status["core"]["statistics"]["punches"] == 1
    assert status["source"]["state"] == "connected" and status["source"]["last_message"]
    assert status["source"]["timesync"]["success"]
    assert status["live"]["event"]["id"] == event["id"]
    assert len(client.get("/api/punches", params={"event_id": event["id"]}).json()) == 1
    assert len(outputs[0].frames) == 1 and status["bridge"]["status_counts"] == {"sent": 1}
    assert len(sources.instances) == 1
    assert "Control Center" in client.get("/").text
    assert "script-src 'self'" in client.get("/").headers["content-security-policy"]
    assert "<h1>FoxLive</h1>" in client.get("/live").text


def test_bridge_stop_start_preserves_reader_and_never_backfills(suite: tuple[Any, ...]) -> None:
    client, controller, sources, outputs = suite
    mappings(client)
    receive(client, sources, 1)
    post(client, "/api/ops/bridge/state", {"running": False})
    assert not load(controller.locations).bridge.enabled and not outputs[0].connected
    assert client.get("/api/ops/status").json()["bridge"]["state"] == "stopped"
    receive(client, sources, 2)
    for _ in range(3):
        post(client, "/api/ops/bridge/state", {"running": True})
        post(client, "/api/ops/bridge/state", {"running": False})
    post(client, "/api/ops/bridge/state", {"running": True})
    receive(client, sources, 3)
    assert len(sources.instances) == 1 and sources.maximum == 1
    assert sum(len(output.frames) for output in outputs) == 2
    assert len(client.get("/api/ops/bridge/deliveries").json()) == 2
    assert load(controller.locations).bridge.enabled
    assert client.portal is not None
    assert client.portal.call(lambda: len(controller.runtime().ingest.subscribers)) == 2


def test_probe_and_reconnect_never_overlap_source_readers(suite: tuple[Any, ...]) -> None:
    client, controller, sources, _ = suite
    assert client.portal is not None
    result = client.portal.call(controller.test, ConnectionTestInput(port="COM3"), 0.01)
    assert result["opened"] and result["time_sent"]
    post(client, "/api/ops/reconnect", {})
    client.portal.call(asyncio.sleep, 0.01)
    assert sources.maximum == 1 and sources.active == 1 and len(sources.instances) == 4
    assert client.get("/api/ops/status").json()["source"]["reader_running"]


@pytest.mark.parametrize("port", ["COM3", "com3", r"\\.\COM3"])
def test_bridge_cannot_open_input_port(suite: tuple[Any, ...], port: str) -> None:
    client, controller, sources, outputs = suite
    before = controller.locations.settings.read_bytes()
    response = client.post("/api/ops/bridge", json={"enabled": True, "port": port})
    assert response.status_code == 422 and "differ" in response.json()["detail"]
    assert controller.locations.settings.read_bytes() == before
    assert len(sources.instances) == 1 and len(outputs) == 1


def test_bridge_failure_does_not_stop_core_or_live(suite: tuple[Any, ...]) -> None:
    client, controller, sources, outputs = suite
    mappings(client)
    outputs[0].fail_write = True
    receive(client, sources, 1)
    status = client.get("/api/ops/status").json()
    assert status["bridge"]["state"] == "error" and status["bridge"]["running"]
    assert status["bridge"]["last_delivery"]["status"] == "uncertain"
    assert status["source"]["state"] == "connected" and status["live"]["state"] == "running"
    receive(client, sources, 2)
    assert client.get("/api/ops/status").json()["core"]["statistics"]["raw_events"] == 2


def test_source_failure_is_visible_and_reconnect_is_owned(suite: tuple[Any, ...]) -> None:
    client, controller, sources, _ = suite

    async def fail() -> None:
        controller.runtime().store.db.execute(
            "CREATE TRIGGER full BEFORE INSERT ON raw_events BEGIN SELECT RAISE(ABORT,'disk full'); END"
        )
        await sources.instances[-1].input.put(b"message\n")
        async with asyncio.timeout(2):
            while controller.runtime().source_health["state"] != "error":
                await asyncio.sleep(0.001)

    assert client.portal is not None
    client.portal.call(fail)
    status = client.get("/api/ops/status").json()
    assert status["core"]["state"] == "error" and "disk full" in status["source"]["last_error"]
    assert status["live"]["state"] == "running" and not status["source"]["reader_running"]
    client.portal.call(lambda: controller.runtime().store.db.execute("DROP TRIGGER full"))
    post(client, "/api/ops/reconnect", {})
    receive(client, sources, 1)
    assert client.get("/api/ops/status").json()["source"]["state"] == "connected"


def test_bridge_settings_roundtrip_and_apply_without_source_restart(
    suite: tuple[Any, ...], tmp_path: Path
) -> None:
    client, controller, sources, _ = suite
    path = tmp_path / "capture with spaces.bin"
    post(
        client,
        "/api/ops/bridge",
        {
            "enabled": True,
            "output_type": "file",
            "path": str(path),
            "timezone": "Europe/Berlin",
            "week_counter": 2,
        },
    )
    assert load(controller.locations) == controller.settings
    assert len(sources.instances) == 1
    assert controller.settings.bridge.sportident.timezone == "Europe/Berlin"
    assert controller.settings.bridge.sportident.week_counter == 2
    assert b"[bridge.output]" in encode(controller.settings)
    assert (
        client.post(
            "/api/ops/bridge",
            json={"output_type": "file", "path": str(controller.locations.database)},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/ops/bridge", json={"output_type": "file", "path": "relative.bin"}
        ).status_code
        == 422
    )


def test_runtime_restart_exit_and_cross_origin_controls(suite: tuple[Any, ...]) -> None:
    client, controller, _, _ = suite
    assert (
        client.post(
            "/api/ops/reconnect", json={}, headers={"origin": "https://foreign.test"}
        ).status_code
        == 403
    )
    before = controller.locations.settings.read_bytes()
    post(client, "/api/ops/restart", {})
    assert controller.pending is not None and controller.restarting
    assert not getattr(client.app.state, "exit_requested", False)
    assert client.post("/api/ops/bridge/state", json={"running": False}).status_code == 503
    assert controller.locations.settings.read_bytes() == before


def test_override_keeps_settings_read_only_but_allows_module_stop(suite: tuple[Any, ...]) -> None:
    client, controller, _, outputs = suite
    controller.settings = replace(controller.settings, override=True)
    before = controller.locations.settings.read_bytes()
    assert client.post("/api/ops/bridge", json={"port": "COM11"}).status_code == 422
    post(client, "/api/ops/bridge/state", {"running": False})
    assert not outputs[0].connected and controller.locations.settings.read_bytes() == before
    post(client, "/api/ops/shutdown", {})
    assert client.app.state.exit_requested


def test_bridge_stop_records_interrupted_and_pending_deliveries(
    suite: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, controller, sources, outputs = suite
    mappings(client)
    writing = asyncio.Event()

    async def block(data: bytes) -> None:
        writing.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(outputs[0], "write", block)

    async def queue() -> None:
        for sequence in (1, 2):
            await sources.instances[-1].input.put(
                json.dumps(
                    {
                        "type": "tag",
                        "station": 1,
                        "timestamp": int(datetime.now(UTC).timestamp()),
                        "sequence": sequence,
                        "uid": UID,
                    }
                ).encode()
            )
        async with asyncio.timeout(2):
            await writing.wait()
            while controller.runtime().store.stats()["raw_events"] != 2:
                await asyncio.sleep(0.001)

    assert client.portal is not None
    client.portal.call(queue)
    post(client, "/api/ops/bridge/state", {"running": False})
    deliveries = client.get("/api/ops/bridge/deliveries").json()
    assert {item["status"] for item in deliveries} == {"failed", "uncertain"}
    assert not outputs[0].connected and sources.active == 1


def test_live_recovery_failure_keeps_suite_core_and_bridge_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations = Locations(tmp_path / "user")
    locations.create()
    settings = Settings(
        Config(SerialConfig("COM3"), locations.database),
        completed=True,
        bridge=BridgeConfig(enabled=True, output=OutputConfig(port="COM10")),
    )
    sources, output = Sources(), FakeOutput()
    monkeypatch.setattr("foxops.runtime.SerialTransport", sources.create)
    monkeypatch.setattr("foxops.runtime.create_output", lambda config: output)

    def fail(service: LiveService) -> None:
        raise ValueError("Derived recovery unavailable")

    monkeypatch.setattr(LiveService, "recover", fail)
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        status = client.get("/api/ops/status").json()
        assert status["live"]["state"] == "error"
        assert "Derived recovery unavailable" in status["live"]["last_error"]
        assert status["core"]["state"] == "running"
        mappings(client)
        receive(client, sources, 1)
        status = client.get("/api/ops/status").json()
        assert status["core"]["statistics"]["raw_events"] == 1
        assert status["core"]["statistics"]["punches"] == 1
        assert status["bridge"]["status_counts"] == {"sent": 1}
        assert len(output.frames) == 1 and sources.maximum == 1
        assert client.get("/").status_code == 200
    assert sources.active == 0 and not output.connected
