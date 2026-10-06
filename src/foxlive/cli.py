"""FoxLive operations; ordinary operation depends only on FoxCore and FoxLive."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import webbrowser
from contextlib import closing, suppress
from pathlib import Path

import uvicorn

from foxcore.config import Config
from foxcore.logging import SafeLogger
from foxcore.persistence import Store

from . import csvio
from .config import LiveConfig, load_live_config
from .persistence import LiveRepository
from .service import LiveService
from .web import create_app

log = SafeLogger(__name__)


def register_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    commands = sub.add_parser("live", help="FoxLive standalone local event desk").add_subparsers(
        dest="live_command", required=True
    )
    run = commands.add_parser("run")
    run.add_argument("--no-serial", action="store_true", help="Offline administration/testing")
    run.add_argument("--no-browser", action="store_true")
    commands.add_parser("status").add_argument("--event", type=int)
    recalculate = commands.add_parser("recalculate")
    recalculate.add_argument("event_id", type=int, nargs="?", help="Defaults to running event")
    for name in ("participants", "results"):
        commands.add_parser("export-" + name).add_argument("event_id", type=int)
    associate = commands.add_parser("associate", help="Explicit historical source association")
    associate.add_argument("event_id", type=int)
    associate.add_argument("punch_ids", type=int, nargs="+")


def bind(config: LiveConfig) -> socket.socket:
    try:
        addresses = socket.getaddrinfo(config.host, config.port, type=socket.SOCK_STREAM)
        family, kind, protocol, _, address = addresses[0]
        endpoint = socket.socket(family, kind, protocol)
        try:
            if sys.platform == "win32":
                endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            endpoint.bind(address)
            endpoint.listen(128)
            endpoint.setblocking(False)
        except BaseException:
            endpoint.close()
            raise
        return endpoint
    except OSError as exc:
        raise ValueError(
            f"FoxLive HTTP endpoint {config.host}:{config.port} unavailable: {exc}"
        ) from exc


async def serve(path: Path, core: Config, config: LiveConfig, serial_enabled: bool) -> None:
    if serial_enabled and not core.serial.port:
        raise ValueError("Configure a FoxIdentServer serial port or use live run --no-serial")
    # Open/migrate before Uvicorn lifespan so expected DB failures use the common concise CLI UX.
    with closing(Store(path)):
        pass
    app = create_app(path, core, config, serial_enabled)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level=core.logging_level.lower(), access_log=False)
    )
    endpoint = bind(config)
    host = f"[{config.host}]" if ":" in config.host else config.host
    url = f"http://{host}:{config.port}/"

    async def browser() -> None:
        while not server.started:
            await asyncio.sleep(0.1)
        log.info("FoxLive desk %s", url)
        if config.open_browser:
            try:
                await asyncio.to_thread(webbrowser.open, url)
            except Exception as exc:
                log.warning("Browser could not open; navigate to %s: %s", url, exc)

    task = asyncio.create_task(browser())
    try:
        await server.serve(sockets=[endpoint])
        if not server.started:
            raise ValueError("FoxLive could not start; inspect the startup log")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        endpoint.close()


def execute(args: argparse.Namespace, core: Config) -> None:
    config = load_live_config(args.config)
    path = args.db or core.database_path
    if args.live_command == "run":
        if args.no_browser:
            from dataclasses import replace

            config = replace(config, open_browser=False)
        asyncio.run(serve(path, core, config, not args.no_serial))
        return
    with closing(Store(path)) as store:
        live = LiveService(LiveRepository(store), config.operator)
        if args.live_command == "status":
            print(json.dumps(live.snapshot(args.event), indent=2, ensure_ascii=False))
        elif args.live_command.startswith("export-"):
            print(csvio.export(live, args.event_id, args.live_command == "export-results"), end="")
        elif args.live_command == "associate":
            print(json.dumps(live.associate(args.event_id, args.punch_ids), indent=2))
        else:
            event_id = args.event_id
            if event_id is None:
                running = live.repo.running()
                if running is None:
                    raise ValueError("No active event")
                event_id = running.id
            print(json.dumps(live.recalculate(event_id), indent=2))
