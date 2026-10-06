import json
import socket
import sys
from pathlib import Path

import pytest

from foxcore.cli import main
from foxlive.cli import bind
from foxlive.config import LiveConfig


def test_live_cli_concise_errors_status_and_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prefix = ["foxsuite", "--db", str(tmp_path / "live.db"), "live"]
    monkeypatch.setattr(sys, "argv", prefix + ["run", "--no-browser"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    message = capsys.readouterr().err
    assert (
        "serial port" in message and "Traceback" not in message and "ExceptionGroup" not in message
    )
    monkeypatch.setattr(sys, "argv", prefix + ["recalculate"])
    with pytest.raises(SystemExit):
        main()
    assert "No active event" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", prefix + ["status"])
    main()
    assert json.loads(capsys.readouterr().out)["active_event_id"] is None
    from foxcore.persistence import Store
    from foxlive.models import EventData
    from foxlive.persistence import LiveRepository
    from foxlive.service import LiveService

    store = Store(tmp_path / "live.db")
    event = LiveService(LiveRepository(store)).put_event(EventData(name="Desk", date="2026-10-06"))
    store.close()
    for kind in ["participants", "results"]:
        monkeypatch.setattr(sys, "argv", prefix + ["export-" + kind, str(event.id)])
        main()
        assert "start_number" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", prefix + ["recalculate", str(event.id)])
    main()
    assert json.loads(capsys.readouterr().out)["source_punches"] == 0


def test_http_endpoint_collision_is_concise() -> None:
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        with pytest.raises(ValueError, match="HTTP endpoint .* unavailable"):
            bind(LiveConfig(port=endpoint.getsockname()[1]))
