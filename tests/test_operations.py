"""M4 composes accepted services; no Windows device is required for these tests."""

import asyncio
import json
import os
import stat
import sys
import zipfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from serial.tools.list_ports_common import ListPortInfo

from foxbridge.output import FileOutput
from foxcore.config import Config, SerialConfig
from foxcore.persistence import Store
from foxcore.serial import FakeTransport
from foxcore.service import IngestService
from foxlive.config import LiveConfig
from foxops import data, i18n, native, ports
from foxops.files import sync_file
from foxops.launcher import instance
from foxops.settings import Device, Locations, Settings, encode, load, save, user_root
from foxops.web import ConnectionTestInput, Controller, create_app

TAG = b'{"type":"tag","station":1,"sequence":1,"timestamp":1791280800,"uid":"046365525C6180"}\n'


@pytest.fixture(autouse=True)
def writable_fsync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enforce Windows' writable-file requirement even on permissive POSIX hosts.

    A zero-byte write checks descriptor access without changing file contents. Every
    accepted call still performs the real fsync; directory handles are not accepted.
    """
    real_fsync = os.fsync

    def checked(descriptor: int) -> None:
        assert stat.S_ISREG(os.fstat(descriptor).st_mode)
        os.write(descriptor, b"")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", checked)


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


def test_completed_file_flush_preserves_bytes_and_closes_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runs the real fsync/_commit on every platform, including native Windows."""
    path = tmp_path / "completed.bin"
    content = b"completed archive\x00\xff"
    path.write_bytes(content)
    descriptors: list[int] = []
    real_fsync = os.fsync

    def flushed(descriptor: int) -> None:
        real_fsync(descriptor)
        descriptors.append(descriptor)

    monkeypatch.setattr(os, "fsync", flushed)
    sync_file(path)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    target = tmp_path / "published.bin"
    path.replace(target)  # A still-open flush handle would interfere on Windows.
    assert target.read_bytes() == content
    missing = tmp_path / "missing.bin"
    with pytest.raises(FileNotFoundError):
        sync_file(missing)
    assert not missing.exists()


def test_completed_file_flush_failure_propagates_and_closes_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "completed.bin"
    path.write_bytes(b"unchanged")
    descriptors: list[int] = []

    def failed(descriptor: int) -> None:
        descriptors.append(descriptor)
        raise OSError("flush failed")

    monkeypatch.setattr(os, "fsync", failed)
    with pytest.raises(OSError, match="flush failed"):
        sync_file(path)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert path.read_bytes() == b"unchanged"


def test_settings_flush_failure_preserves_saved_preferences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    save(locations, settings)
    before = locations.settings.read_bytes()

    def failed(descriptor: int) -> None:
        raise OSError("settings flush failed")

    monkeypatch.setattr(os, "fsync", failed)
    with pytest.raises(OSError, match="settings flush failed"):
        save(locations, replace(settings, language="de"))
    assert locations.settings.read_bytes() == before and load(locations) == settings
    assert not list(locations.settings.parent.glob(".foxsuite-*"))


def test_backup_archive_flush_failure_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    real_sync = sync_file

    def failed(path: Path) -> None:
        if path.name == "archive":
            raise OSError("archive flush failed")
        real_sync(path)

    monkeypatch.setattr(data, "sync_file", failed)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
        with pytest.raises(OSError, match="archive flush failed"):
            data.backup(store, locations, settings)
        assert store.stats()["raw_events"] == 1
    assert not list(locations.backups.iterdir())


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_location_snapshot_flush_failure_preserves_original_and_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    locations, settings = fixture(tmp_path)
    save(locations, settings)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
    destination = tmp_path / "other"
    real_sync = sync_file

    def failed(path: Path) -> None:
        if path.is_relative_to(destination):
            raise OSError("snapshot flush failed")
        real_sync(path)

    monkeypatch.setattr(data, "sync_file", failed)
    with pytest.raises(OSError, match="snapshot flush failed"):
        data.change_location(locations, settings, destination, cast(Any, mode))
    assert load(locations) == settings and not (destination / "foxsuite.db").exists()
    assert len(list(locations.backups.glob("*.foxbackup"))) == 1
    assert not list(destination.glob(".foxsuite-*"))
    with closing(Store(locations.database)) as store:
        assert store.stats()["raw_events"] == 1


@pytest.mark.parametrize("stage", ["restored_database", "safety_backup"])
def test_restore_flush_failure_preserves_current_source_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        archive = data.backup(store, locations, settings)
        IngestService(store).ingest(TAG, "serial:COM3")
        IngestService(store).ingest(b"not in backup\xff\n", "serial:COM3")
        before = [tuple(row) for row in store.db.execute("SELECT * FROM raw_events")]
    real_sync = sync_file

    def failed(path: Path) -> None:
        if (stage == "restored_database" and path.parent.name.startswith(".restore-")) or (
            stage == "safety_backup" and path.name == "archive"
        ):
            raise OSError("restore flush failed")
        real_sync(path)

    monkeypatch.setattr(data, "sync_file", failed)
    with pytest.raises(OSError, match="restore flush failed"):
        data.restore(locations, settings, archive)
    with closing(Store(locations.database)) as store:
        assert [tuple(row) for row in store.db.execute("SELECT * FROM raw_events")] == before
    assert list(locations.backups.glob("*.foxbackup")) == [archive]
    assert not list(locations.database.parent.glob(".restore-*"))


@pytest.mark.parametrize("operation", ["backup", "copy", "restore"])
def test_staging_files_are_synced_before_atomic_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        IngestService(store).ingest(TAG, "serial:COM3")
        archive = data.backup(store, locations, settings)
    flushed: set[Path] = set()
    published: list[Path] = []
    real_sync, real_replace = sync_file, Path.replace

    def synced(path: Path) -> None:
        real_sync(path)
        flushed.add(path)

    def publish(path: Path, target: Path) -> Path:
        if target.suffix in {".foxbackup", ".db"}:
            assert path in flushed
            published.append(target)
        return real_replace(path, target)

    monkeypatch.setattr(data, "sync_file", synced)
    monkeypatch.setattr(Path, "replace", publish)
    if operation == "backup":
        with closing(Store(locations.database)) as store:
            data.backup(store, locations, settings)
    elif operation == "copy":
        data.change_location(locations, settings, tmp_path / "other", "copy")
    else:
        data.restore(locations, settings, archive)
    assert len(published) == (1 if operation == "backup" else 2)


def test_import_flush_failure_does_not_publish_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    locations, settings = fixture(tmp_path)
    with closing(Store(locations.database)) as store:
        archive = data.backup(store, locations, settings)

    def failed(path: Path) -> None:
        assert path.name == "upload"
        raise OSError("import flush failed")

    monkeypatch.setattr("foxops.web.sync_file", failed)
    controller = Controller(locations, settings, lambda: None)
    with TestClient(create_app(controller), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/ops/import",
            content=archive.read_bytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 503 and "Traceback" not in response.text
    assert list(locations.backups.iterdir()) == [archive]


def test_bridge_capture_uses_writable_fsync(tmp_path: Path) -> None:
    """The accepted append-only bridge path also exercises the writable-fd guard."""
    path = tmp_path / "capture.bin"
    path.write_bytes(b"previous")

    async def capture() -> None:
        output = FileOutput(path)
        await output.connect()
        try:
            await output.write(b"new frame")
        finally:
            await output.close()

    asyncio.run(capture())
    assert path.read_bytes() == b"previousnew frame"
