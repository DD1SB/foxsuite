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
