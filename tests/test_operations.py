"""M4 composes accepted services; no Windows device is required for these tests."""

import asyncio
import json
import sys
import zipfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from serial.tools.list_ports_common import ListPortInfo

from foxcore.config import Config, SerialConfig
from foxcore.persistence import Store
from foxcore.serial import FakeTransport
from foxcore.service import IngestService
from foxlive.config import LiveConfig
from foxops import data, i18n, native, ports
from foxops.launcher import instance
from foxops.settings import Device, Locations, Settings, encode, load, save, user_root
from foxops.web import ConnectionTestInput, Controller, create_app

TAG = b'{"type":"tag","station":1,"sequence":1,"timestamp":1791280800,"uid":"046365525C6180"}\n'


def fixture(tmp_path: Path, completed: bool = False) -> tuple[Locations, Settings]:
    locations = Locations(tmp_path / "user")
    locations.create()
    settings = Settings(
        Config(database_path=locations.database, serial=SerialConfig("FAKE" if completed else "")),
        LiveConfig(open_browser=False),
        completed,
    )
    return locations, settings


def test_paths_and_normal_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("foxops.settings.sys.platform", "win32")
    assert user_root() == tmp_path / "FoxSuite"
    locations, settings = fixture(tmp_path)
    assert not load(locations).completed
    assert load(locations).core.database_path.is_absolute()
    settings = replace(
        settings,
        language="de",
        completed=True,
        core=replace(settings.core, serial=SerialConfig("COM7")),
    )
    save(locations, settings)
    assert load(locations) == settings
    advanced = tmp_path / "advanced.toml"
    advanced.write_text(
        '[serial]\nport="COM8"\n[database]\npath="advanced.db"\n[live]\nport=8777\n',
        encoding="utf-8",
    )
    overridden = load(locations, advanced)
    assert overridden.override and overridden.core.serial.port == "COM8"
    assert overridden.core.database_path == tmp_path / "advanced.db"
    assert overridden.live.port == 8777
    with pytest.raises(ValueError, match="read-only"):
        save(locations, overridden)
    assert load(locations).core.serial.port == "COM7"


def test_settings_absolute_roundtrip_unicode_and_invalid(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    path = tmp_path / 'Müller "race"' / "foxsuite.db"
    settings = replace(
        settings,
        core=replace(settings.core, database_path=path),
        device=Device(123, 456, "XYZ", "USB", "Vendor", "Fox"),
    )
    save(locations, settings)
    assert load(locations) == settings
    assert not list(locations.settings.parent.glob(".foxsuite-*"))
    with pytest.raises(ValueError, match="absolute"):
        Locations(Path("relative"))
    with pytest.raises(ValueError, match="absolute"):
        Settings(Config())
    with pytest.raises(ValueError, match="localhost"):
        replace(settings, live=LiveConfig(host="0.0.0.0"))
    with pytest.raises(ValueError, match="Select"):
        replace(settings, completed=True)


def test_port_enumeration_and_confirmed_identity_only(monkeypatch: pytest.MonkeyPatch) -> None:
    info = ListPortInfo("COM5")
    info.description = "USB Serial Device"
    info.vid, info.pid, info.serial_number, info.manufacturer, info.product = (
        12,
        34,
        "XYZ",
        "Vendor",
        "Base",
    )
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [info])
    choice = ports.enumerate_ports()[0]
    assert choice.label == "COM5 — USB Serial Device"
    assert choice.device.product == "Base"
    assert ports.relocated(choice.device, "COM3", [choice]) == choice
    assert ports.relocated(choice.device, "COM5", [choice]) is None
    assert ports.relocated(Device(12, 34), "COM3", [choice]) is None
    assert ports.relocated(Device(), "COM3", [choice]) is None
    assert ports.relocated(choice.device, "COM3", [choice, choice]) is None


def test_online_backup_includes_wal_and_restore_all_source_facts(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        ingest = IngestService(store)
        ingest.ingest(TAG, "serial:COM3")
        ingest.ingest(TAG, "serial:COM3")
        ingest.ingest(b"malformed\xff\n", "serial:COM3")
        expected = [tuple(row) for row in store.db.execute("SELECT * FROM raw_events")]
        archive = data.backup(store, locations, settings)
        ingest.ingest(b"later", "serial:COM3")
        assert archive.exists() and len(list(locations.backups.glob("*.foxbackup"))) == 1
    data.restore(locations, settings, archive)
    with closing(Store(locations.database)) as restored:
        assert [tuple(row) for row in restored.db.execute("SELECT * FROM raw_events")] == expected
        assert (
            restored.db.execute("SELECT COUNT(*) FROM punches WHERE duplicate=1").fetchone()[0] == 1
        )
    assert len(list(locations.backups.glob("*.foxbackup"))) == 2


@pytest.mark.parametrize("mode", ["copy", "move", "existing"])
def test_explicit_data_change(tmp_path: Path, mode: str) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
    destination = tmp_path / "other"
    if mode == "existing":
        with closing(Store(destination / "foxsuite.db")) as store:
            IngestService(store).ingest(b"existing data", "file")
    updated = data.change_location(locations, settings, destination, cast(Any, mode))
    assert (
        load(locations).core.database_path
        == updated.core.database_path
        == destination / "foxsuite.db"
    )
    with closing(Store(updated.core.database_path)) as store:
        assert store.db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1
    assert len(list(locations.backups.glob("*.foxbackup"))) == 1
    if mode == "move":
        assert not locations.database.exists()
        assert len(list(locations.database.parent.glob("foxsuite-moved-*.db"))) == 1
    else:
        assert locations.database.exists()


def test_data_change_never_silently_creates_or_overwrites(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    save(locations, settings)
    with closing(Store(locations.database)):
        pass
    destination = tmp_path / "other"
    with pytest.raises(ValueError, match="existing"):
        data.change_location(locations, settings, destination, "existing")
    assert not destination.exists() and load(locations) == settings
    with closing(Store(destination / "foxsuite.db")):
        pass
    with pytest.raises(ValueError, match="already exists"):
        data.change_location(locations, settings, destination, "copy")
    for directory in [Path("relative"), Path("/"), locations.database.parent]:
        with pytest.raises(ValueError):
            data.change_location(locations, settings, directory, "copy")
    assert load(locations) == settings


def test_invalid_restore_preserves_current_and_rejects_traversal(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
    archive = locations.backups / "bad.foxbackup"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("../escape", "bad")
    with pytest.raises(ValueError, match="members"):
        data.restore(locations, settings, archive)
    with closing(Store(locations.database)) as store:
        assert store.db.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 1
    assert not (locations.root / "escape").exists()


def test_future_schema_and_corrupt_archive_rejected(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        good = data.backup(store, locations, settings)
        store.db.execute("INSERT INTO schema_migrations(version) VALUES(1000000000)")
        store.db.commit()
    with pytest.raises(ValueError, match="schema"):
        data.validate_database(locations.database)
    with (
        zipfile.ZipFile(good) as source,
        zipfile.ZipFile(tmp_path / "corrupt.foxbackup", "w") as target,
    ):
        for name in source.namelist():
            target.writestr(name, b"wrong" if name == "settings.toml" else source.read(name))
    with pytest.raises(ValueError, match="checksum"):
        data.unpack(tmp_path / "corrupt.foxbackup", tmp_path / "test.db")


def test_first_run_routes_settings_language_and_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    monkeypatch.setattr(ports, "enumerate_ports", lambda: [])
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        assert client.get("/", follow_redirects=False).headers["location"] == "/setup"
        assert client.get("/setup").status_code == 200
        assert client.get("/ops/static/settings.js").status_code == 200
        assert client.get("/api/ops/settings").json()["language"] == "en"
        response = client.post(
            "/api/ops/restore",
            json={"name": "missing.foxbackup"},
            headers={"Accept-Language": "de"},
        )
        assert response.status_code == 422 and "bestätigen" in response.json()["detail"]
        assert "Traceback" not in response.text
        assert (
            client.post(
                "/api/ops/settings", json={"port": "COM3"}, headers={"Origin": "http://evil"}
            ).status_code
            == 403
        )
        assert client.get("/api/ops/settings", headers={"Host": "evil"}).status_code == 400
        assert not client.get("/api/status").json()["application"]["serial_enabled"]


def test_connection_probe_uses_raw_first_ingest_and_real_time_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    transport = FakeTransport()
    monkeypatch.setattr("foxops.web.SerialTransport", lambda config: transport)
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        assert client.portal is not None
        client.portal.call(transport.input.put, TAG)
        client.portal.call(transport.input.put, b"broken\xff\n")
        result = client.portal.call(controller.test, ConnectionTestInput(port="COM3"), 0.01)
        assert result["opened"] and result["time_sent"]
        assert "tag" in result["observed_types"]
        assert transport.commands[0].startswith(b"TIME ") and transport.commands[0].endswith(b"\n")
        raw = client.portal.call(
            lambda: [
                tuple(row)
                for row in controller.runtime().store.db.execute("SELECT raw_bytes FROM raw_events")
            ]
        )
        assert raw == [(TAG,), (b"broken\xff\n",)]
        assert not transport.connected


@pytest.mark.parametrize("failure", ["open", "write"])
def test_probe_errors_are_concise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    locations, settings = fixture(tmp_path)
    transport = FakeTransport()
    transport.fail_send = failure == "write"
    if failure == "open":

        async def failed(line: Any, state: Any) -> None:
            from foxcore.events import ConnectionEvent

            await state(ConnectionEvent(False, "busy"))
            await asyncio.Event().wait()

        monkeypatch.setattr(transport, "run", failed)
    monkeypatch.setattr("foxops.web.SerialTransport", lambda config: transport)
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        assert client.portal is not None
        result = client.portal.call(controller.test, ConnectionTestInput(port="COM3"), 0.01)
        assert not result["time_sent"] and result["opened"] == (failure == "write")
        assert not transport.connected


def test_settings_completion_restart_and_no_historical_reemission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    monkeypatch.setattr(
        ports, "enumerate_ports", lambda: [ports.Port("COM3", Device(1, 2, "SER", "USB"))]
    )
    monkeypatch.setattr("foxlive.web.SerialTransport", lambda config: FakeTransport())
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        result = client.post("/api/ops/settings", json={"port": "COM3", "language": "de"})
        assert result.status_code == 200
        assert load(locations).completed and load(locations).language == "de"
        assert load(locations).device.serial_number == "SER"
        assert client.get("/", follow_redirects=False).status_code == 200
        assert client.get("/api/status").json()["application"]["serial_enabled"]
        assert "/settings" in client.get("/system/settings").text
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
    restored = Controller(locations, load(locations), lambda: None)
    with TestClient(create_app(restored), base_url="http://127.0.0.1") as client:
        assert client.get("/api/ops/settings").json()["completed"]
        assert len(client.get("/api/source-punches").json()) == 1


def test_backup_import_download_and_deferred_restore(tmp_path: Path) -> None:
    locations, settings = fixture(tmp_path)
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        name = client.post("/api/ops/backup", json={}).json()["name"]
        archive = client.get("/api/ops/backups/" + name).content
        imported = client.post(
            "/api/ops/import", content=archive, headers={"Content-Type": "application/octet-stream"}
        )
        assert imported.status_code == 200
        assert len(client.get("/api/ops/backups").json()) == 2
        assert (
            client.post(
                "/api/ops/import",
                content=b"bad",
                headers={"Content-Type": "application/octet-stream"},
            ).status_code
            == 422
        )
        response = client.post(
            "/api/ops/restore", json={"name": imported.json()["name"], "confirmed": True}
        )
        assert response.status_code == 200 and controller.pending is not None
        assert client.post("/api/ops/backup", json={}).status_code == 503
        assert client.post("/api/events", json={"name": "Late"}).status_code == 503
    controller.pending()
    data.validate_database(locations.database)


def test_instance_lock_releases_and_native_picker_boundary(tmp_path: Path) -> None:
    locations, _ = fixture(tmp_path)
    with instance(locations):
        with pytest.raises(ValueError, match="already running"):
            with instance(locations):
                pass
    with instance(locations):
        pass
    if sys.platform != "win32":
        with pytest.raises(ValueError, match="Windows"):
            native.browse_folder()


def test_catalogs_complete_and_static_keys_exist(tmp_path: Path) -> None:
    import re

    assets = Path(__file__).parents[1] / "src/foxops/static"
    en, de = i18n.catalog("en"), i18n.catalog("de")
    assert en.keys() == de.keys() and all(en.values()) and all(de.values())
    assert set(i18n.ERRORS.values()) <= en.keys()
    keys = set(re.findall(r'data-t="([\w.]+)"', (assets / "settings.html").read_text()))
    keys |= set(re.findall(r"\bt\('([\w.]+)'", (assets / "settings.js").read_text()))
    assert keys <= en.keys()
    assert i18n.error_text("Backup is invalid", "de") == "Die Sicherung ist ungültig"
    assert (
        json.loads(
            encode(Settings(Config(database_path=tmp_path / "foxsuite.db")))
            .decode()
            .split("language = ")[1]
            .splitlines()[0]
        )
        == "en"
    )


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_failed_settings_save_retains_original_location_and_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    locations, settings = fixture(tmp_path)
    save(locations, settings)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")

    def fail(locations: Locations, settings: Settings) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("foxops.data.save", fail)
    with pytest.raises(OSError, match="disk full"):
        data.change_location(locations, settings, tmp_path / "other", cast(Any, mode))
    assert load(locations) == settings and locations.database.exists()
    with closing(Store(locations.database)) as store:
        assert store.db.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 1


def test_reidentified_usb_pauses_source_instead_of_opening_wrong_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path, True)
    settings = replace(
        settings,
        core=replace(settings.core, serial=SerialConfig("COM3")),
        device=Device(12, 34, "BASE"),
    )
    calls: list[str] = []

    def transport(config: SerialConfig) -> FakeTransport:
        calls.append(config.port)
        return FakeTransport()

    monkeypatch.setattr("foxlive.web.SerialTransport", transport)
    monkeypatch.setattr(
        ports,
        "enumerate_ports",
        lambda: [
            ports.Port("COM3", Device(50, 60, "OTHER")),
            ports.Port("COM5", Device(12, 34, "BASE")),
        ],
    )
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        status = client.get("/api/ops/settings").json()
        assert status["suggestion"]["port"] == "COM5" and status["identity_confirmation"]
        assert not calls and not client.get("/api/status").json()["application"]["serial_enabled"]
        assert client.post("/api/ops/settings", json={"port": "COM5"}).status_code == 200
        assert client.portal is not None
        client.portal.call(asyncio.sleep, 0.01)
        assert calls == ["COM5"]


def test_move_recovery_rename_failure_does_not_diverge_from_saved_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)):
        pass
    original_replace = Path.replace

    def rename(path: Path, target: Path) -> Path:
        if path == locations.database:
            raise PermissionError("recovery copy in use")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", rename)
    updated = data.change_location(locations, settings, tmp_path / "other", "move")
    assert updated == load(locations) and locations.database.exists()
    assert updated.core.database_path.exists()


def test_second_desktop_launch_reopens_existing_browser_without_another_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxops import launcher

    locations, _ = fixture(tmp_path)
    (locations.root / "running.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 8765, "path": "/setup"})
    )
    monkeypatch.setattr(sys, "argv", ["foxsuite-desktop", "--user-directory", str(locations.root)])
    opened: list[str] = []
    monkeypatch.setattr("foxops.launcher.webbrowser.open", lambda url: opened.append(url))
    with instance(locations):
        launcher.main()
    assert opened == ["http://127.0.0.1:8765/setup"]
