"""Release-maintainer smoke for installed/frozen launchers; isolated, offline, no USB claims."""

import argparse
import asyncio
import json
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import websockets

from foxcore.config import Config
from foxlive.config import LiveConfig
from foxops.settings import Locations, Settings, load, save


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", required=True, type=Path)
    parser.add_argument("--cli", required=True, type=Path)
    args = parser.parse_args()
    desktop, cli = str(args.desktop.resolve()), str(args.cli.resolve())
    subprocess.run([desktop, "--help"], check=True, capture_output=True)
    subprocess.run([cli, "--help"], check=True, capture_output=True)
    with tempfile.TemporaryDirectory(prefix="foxsuite-release-smoke-") as folder:
        locations = Locations(Path(folder) / "user")
        locations.create()
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            port = endpoint.getsockname()[1]
        save(locations, Settings(Config(database_path=locations.database), LiveConfig(port=port)))
        base = f"http://127.0.0.1:{port}"

        def api(path: str, payload: dict[str, object] | None = None) -> Any:
            request = Request(
                base + path,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload).encode() if payload is not None else None,
            )
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        def wait(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    if predicate():
                        return
                except (URLError, TimeoutError, ConnectionError, OSError):
                    pass
                time.sleep(0.1)
            raise AssertionError("Desktop did not reach the expected state")

        process = subprocess.Popen(
            [desktop, "--user-directory", str(locations.root), "--no-browser"],
            cwd=folder,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait(lambda: api("/api/ops/settings")["completed"] is False)
            for asset in (
                "/setup",
                "/ops/static/settings.js",
                "/ops/static/en.json",
                "/ops/static/de.json",
                "/static/desk.js",
                "/live/display",
            ):
                with urlopen(base + asset, timeout=5) as response:
                    assert response.status == 200 and response.read()
            api(
                "/api/ops/settings",
                {"port": "SIMULATED-NO-HARDWARE", "http_port": port, "language": "de"},
            )
            assert load(locations).completed and load(locations).language == "de"
            event = api(
                "/api/events",
                {"name": "Offline smoke", "date": "2026-10-08", "timezone": "Europe/Berlin"},
            )

            async def sockets() -> None:
                async with (
                    websockets.connect(base.replace("http", "ws") + "/ws") as operator,
                    websockets.connect(base.replace("http", "ws") + "/ws/display") as display,
                ):
                    await asyncio.wait_for(operator.recv(), 5)
                    await asyncio.wait_for(display.recv(), 5)
                    api(f"/api/events/{event['id']}/state", {"state": "RUNNING"})
                    assert json.loads(await asyncio.wait_for(operator.recv(), 5))["version"] == 1
                    assert json.loads(await asyncio.wait_for(display.recv(), 5))["version"] == 1

            asyncio.run(sockets())
            archive = api("/api/ops/backup", {})["name"]
            api("/api/events", {"name": "Later event", "date": "2026-10-09"})
            api("/api/ops/restore", {"name": archive, "confirmed": True})
            wait(lambda: len(api("/api/events")) == 1)
            destination = Path(folder) / "copied"
            api(
                "/api/ops/location",
                {"directory": str(destination), "mode": "copy", "confirmed": True},
            )
            wait(lambda: api("/api/ops/settings")["data_directory"] == str(destination))
            assert locations.database.exists() and (destination / "foxsuite.db").exists()
            assert load(locations).core.database_path == destination / "foxsuite.db"
            api("/api/ops/shutdown", {})
            assert process.wait(timeout=20) == 0
            # Same settings, data and active event recover without a new live punch.
            process = subprocess.Popen(
                [desktop, "--user-directory", str(locations.root), "--no-browser"],
                cwd=folder,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait(lambda: api("/api/ops/settings")["completed"] is True)
            assert len(api("/api/events")) == 1 and api("/api/source-punches") == []
            api("/api/ops/shutdown", {})
            assert process.wait(timeout=20) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
    print(
        "Desktop setup, offline assets, HTTP/WebSockets, backup/restore, copy, restart and shutdown: PASS"
    )


if __name__ == "__main__":
    main()
