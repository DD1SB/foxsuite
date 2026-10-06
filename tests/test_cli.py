import json
import subprocess
import sys
from pathlib import Path

import pytest

from foxcore.cli import main
from foxcore.errors import error_message


def test_missing_port_is_concise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["foxsuite", "--db", str(tmp_path / "core.db"), "run"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "Configure a FoxIdentServer serial port" in output
    assert "Traceback" not in output and "ExceptionGroup" not in output


def test_group_error_unwrap() -> None:
    error = ExceptionGroup(
        "tasks", [ValueError("port missing"), ExceptionGroup("nested", [OSError("disk full")])]
    )
    assert error_message(error) == "port missing; disk full"


def test_simulator_explicit_timestamp() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "foxcore.cli", "simulate", "--timestamp", "1770000001"],
        check=True,
        capture_output=True,
    )
    lines = result.stdout.splitlines()
    assert len(lines) == 7 and lines[0] == lines[1]
    assert json.loads(lines[0])["timestamp"] == 1770000001
    assert json.loads(lines[5])["timestamp"] == 1770000001
    assert json.loads(lines[6])["timestamp"] == 1770000001
