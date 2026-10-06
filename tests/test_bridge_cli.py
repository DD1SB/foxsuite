import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from foxbridge.cli import validate_output
from foxbridge.config import OutputConfig, load_bridge_config
from foxcore.cli import main
from foxcore.config import Config, SerialConfig
from foxcore.persistence import Store
from foxcore.service import IngestService
from foxcore.simulator import messages


def invoke(db: Path, args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["foxsuite", "--db", str(db), "bridge", *args])
    main()


def test_cli_mapping_status_and_expected_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "cli.db"
    invoke(db, ["uid-map", "add", "04:aa", "912345"], monkeypatch)
    assert json.loads(capsys.readouterr().out)["uid"] == "04AA"
    invoke(db, ["uid-map", "list"], monkeypatch)
    assert len(json.loads(capsys.readouterr().out)) == 1
    with pytest.raises(SystemExit):
        invoke(db, ["uid-map", "add", "04BB", "912345"], monkeypatch)
    error = capsys.readouterr().err
    assert "already has" in error and "Traceback" not in error
    invoke(db, ["station-map", "add", "1", "31"], monkeypatch)
    assert json.loads(capsys.readouterr().out)["control_code"] == 31
    with pytest.raises(SystemExit):
        invoke(db, ["station-map", "add", "2", "255"], monkeypatch)
    assert "20..254" in capsys.readouterr().err
    invoke(db, ["status"], monkeypatch)
    status = json.loads(capsys.readouterr().out)
    assert status["delivered"] == 0 and status["target"] == "fjww"
    invoke(db, ["uid-map", "remove", "04AA"], monkeypatch)
    invoke(db, ["uid-map", "list"], monkeypatch)
    assert json.loads(capsys.readouterr().out) == []
    invoke(db, ["test-frame", "912345", "31", "--timestamp", "1770000000"], monkeypatch)
    assert capsys.readouterr().out.startswith("02 D3 0D")


def test_cli_bridge_pipeline_and_replay_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, cfg, capture = tmp_path / "cli.db", tmp_path / "foxsuite.toml", tmp_path / "frames.bin"
    cfg.write_text('[bridge]\nenabled=true\n[bridge.output]\ntype="file"\npath="frames.bin"\n')
    store = Store(db)
    from foxbridge.mapping import MappingRepository, Role

    maps = MappingRepository(store)
    maps.add_uid("04A78319BCDE12", 912345)
    maps.add_station(1, 31, Role.CONTROL)
    # Use present timestamp so the CLI's actual PC receive clock validates it.
    raw = messages(int(datetime.now(UTC).timestamp()))[0]
    store.close()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    monkeypatch.setattr(
        sys, "argv", ["foxsuite", "--db", str(db), "--config", str(cfg), "bridge", "run", "--stdin"]
    )
    main()
    original = capture.read_bytes()
    assert len(original) == 19
    monkeypatch.setattr(
        sys, "argv", ["foxsuite", "--db", str(db), "--config", str(cfg), "bridge", "replay"]
    )
    main()
    assert capture.read_bytes() == original
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "foxsuite",
            "--db",
            str(db),
            "--config",
            str(cfg),
            "bridge",
            "replay",
            "--allow-replay-output",
        ],
    )
    main()
    assert len(capture.read_bytes()) == 38


def test_default_replay_never_opens_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "replay.db"
    store = Store(db)
    IngestService(store).ingest(messages()[0], "test")
    store.close()
    # With no configured output port, unguarded opening would fail.
    invoke(db, ["replay"], monkeypatch)
    store = Store(db)
    assert (
        store.db.execute("SELECT status FROM bridge_deliveries").fetchone()[0] == "replay_blocked"
    )
    assert store.stats()["raw_events"] == 2
    store.close()


def test_config_and_separate_endpoints(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[bridge]\nenabled=true\n[bridge.output]\ntype="file"\npath="capture.bin"\n'
        '[bridge.sportident]\ntimezone="Europe/Berlin"\n'
    )
    config = load_bridge_config(path)
    assert config.output.path == tmp_path / "capture.bin"
    assert config.sportident.timezone == "Europe/Berlin"
    with pytest.raises(ValueError, match="differ"):
        validate_output(
            replace(config, output=OutputConfig(port="com9")), Config(serial=SerialConfig("COM9"))
        )
    with pytest.raises(ValueError, match="differ"):
        validate_output(
            replace(config, output=OutputConfig(port="\\\\.\\COM9")),
            Config(serial=SerialConfig("COM9")),
        )
    validate_output(
        replace(config, output=OutputConfig(port="COM10")), Config(serial=SerialConfig("COM9"))
    )
    path.write_text("[bridge.mapping]\nauto_allocate_si_numbers=true\n")
    with pytest.raises(ValueError, match="explicit"):
        load_bridge_config(path)


def test_missing_bridge_configuration_concise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        invoke(tmp_path / "disabled.db", ["run"], monkeypatch)
    error = capsys.readouterr().err
    assert "FoxBridge is disabled" in error and "Traceback" not in error


def test_bridge_startup_recovers_raw_without_historical_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, db, capture = tmp_path / "config.toml", tmp_path / "recover.db", tmp_path / "capture.bin"
    cfg.write_text('[bridge]\nenabled=true\n[bridge.output]\ntype="file"\npath="capture.bin"\n')
    store = Store(db)
    store.insert_raw(messages()[0], datetime.fromtimestamp(1770000000, UTC), "base")
    store.close()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO()))
    monkeypatch.setattr(
        sys, "argv", ["foxsuite", "--db", str(db), "--config", str(cfg), "bridge", "run", "--stdin"]
    )
    main()
    store = Store(db)
    assert store.stats()["punches"] == 1
    assert store.db.execute("SELECT COUNT(*) FROM bridge_deliveries").fetchone()[0] == 0
    assert not capture.exists() or capture.read_bytes() == b""
    store.close()


def test_resend_invalid_punch_has_concise_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[bridge.output]\ntype="file"\npath="capture.bin"\n')
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "foxsuite",
            "--db",
            str(tmp_path / "missing.db"),
            "--config",
            str(cfg),
            "bridge",
            "resend",
            "999",
        ],
    )
    with pytest.raises(SystemExit):
        main()
    error = capsys.readouterr().err
    assert "Punch 999 does not exist" in error
    assert "Traceback" not in error and "ExceptionGroup" not in error
