"""Release-maintainer smoke for installed/frozen launchers; isolated, offline, no USB claims."""

import argparse
import asyncio
import json
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import websockets

from foxcore.config import Config
from foxlive.config import LiveConfig
from foxlive.readout import capture, station_record
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
                "/static/evidence.js",
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
                {
                    "name": "Offline smoke",
                    "date": "2026-10-08",
                    "timezone": "Europe/Berlin",
                    "timing_mode": "PREDEFINED_START",
                    "default_start_at": datetime.fromtimestamp(
                        int(time.time()) - 60, UTC
                    ).isoformat(),
                    "tag_event_id": 1825,
                },
            )
            root = f"/api/events/{event['id']}"
            category = api(
                "/api/master/categories",
                {"code": "OPEN", "display_name_en": "Open", "display_name_de": "Offen"},
            )
            api(root + "/categories", {"category_id": category["id"]})
            runner = api(
                "/api/runners", {"first_name": "Offline", "last_name": "Runner", "birth_year": 1980}
            )
            entry = api(
                root + "/participants",
                {
                    "runner_id": runner["id"],
                    "start_number": 1,
                    "category_id": category["id"],
                    "uid": "046365525C6180",
                },
            )
            # API uses PUT for station setup; this helper otherwise uses POST/GET.
            for station_id, name, role in [(1, "Fox 1", "CONTROL"), (8, "Bake", "BEACON")]:
                request = Request(
                    base + root + f"/stations/{station_id}",
                    method="PUT",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(
                        {"station_id": station_id, "display_name": name, "role": role}
                    ).encode(),
                )
                with urlopen(request, timeout=5) as response:
                    assert response.status == 200
                    assert json.loads(response.read())["role"] == role
            session = api(
                root + "/readouts/import",
                {
                    "payload": capture(
                        "046365525C6180",
                        [station_record(station, int(time.time()), 1825) for station in (1, 8)],
                    ).decode()
                },
            )
            assert session["summary"]["recovered"] == 1
            assert session["summary"]["beacon_punched"]
            result = api(root + f"/participants/{entry['id']}")["result"]
            assert result["controls"] == 1 and result["provenance"] == "RECOVERED"
            assert result["beacon_punched"] and result["finish"] is None
            assert result["elapsed"] is None

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
            assert api(root + f"/participants/{entry['id']}")["result"] == result
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
            assert api(root + f"/participants/{entry['id']}")["result"] == result
            api("/api/ops/shutdown", {})
            assert process.wait(timeout=20) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
    print(
        "Desktop setup, offline assets, HTTP/WebSockets, M5 recovery, backup/restore, copy, restart and shutdown: PASS"
    )


if __name__ == "__main__":
    main()
