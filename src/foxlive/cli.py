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
from .evidence import DecisionInput
from .persistence import LiveRepository
from .readout import FileReadoutProvider, capture, station_record
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
    commands.add_parser("reconcile").add_argument("event_id", type=int)
    readout = commands.add_parser("readout").add_subparsers(dest="readout_command", required=True)
    importer = readout.add_parser("import")
    importer.add_argument("event_id", type=int)
    importer.add_argument("path", type=Path)
    simulator = readout.add_parser("simulate")
    simulator.add_argument("event_id", type=int)
    simulator.add_argument("uid")
    simulator.add_argument("--record", action="append", default=[], help="station:unix-seconds")
    simulator.add_argument(
        "--status", choices=["COMPLETE", "PARTIAL", "FAILED", "ABORTED"], default="COMPLETE"
    )
    simulator.add_argument("--unsynchronized", action="store_true")
    review = commands.add_parser("review").add_subparsers(dest="review_command", required=True)
    listing = review.add_parser("list")
    listing.add_argument("event_id", type=int)
    resolving = review.add_parser("resolve")
    resolving.add_argument("event_id", type=int)
    resolving.add_argument("participant_id", type=int)
    resolving.add_argument("station_id", type=int)
    resolving.add_argument("action", choices=["SELECT", "EXCLUDE", "PRESENCE", "MANUAL", "AUTO"])
    resolving.add_argument("--source-type", choices=["LIVE", "TAG_READOUT"])
    resolving.add_argument("--source-id", type=int)
    resolving.add_argument("--timestamp")
    resolving.add_argument("--reason", required=True)


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
        if args.live_command == "readout":
            if args.readout_command == "import":
                result = live.evidence.import_readout(
                    args.event_id, asyncio.run(FileReadoutProvider(args.path).read())
                )
            else:
                event = live.repo.event(args.event_id)
                if event.tag_event_id is None:
                    raise ValueError("Configure the event tag ID before simulating a readout")
                records = []
                for value in args.record:
                    try:
                        station, stamp = map(int, value.split(":"))
                        records.append(
                            station_record(
                                station, stamp, event.tag_event_id, not args.unsynchronized
                            )
                        )
                    except (ValueError, OverflowError) as exc:
                        raise ValueError("Readout record must be station:unix-seconds") from exc
                result = live.evidence.import_raw(
                    args.event_id, capture(args.uid, records, args.status), "simulator"
                )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        if args.live_command == "review":
            if args.review_command == "list":
                print(json.dumps(live.evidence.reviews(args.event_id), indent=2))
            else:
                print(
                    json.dumps(
                        live.evidence.decide(
                            args.event_id,
                            DecisionInput(
                                participant_id=args.participant_id,
                                station_id=args.station_id,
                                action=args.action,
                                source_type=args.source_type,
                                source_id=args.source_id,
                                timestamp=args.timestamp,
                                reason=args.reason,
                            ),
                        ),
                        indent=2,
                    )
                )
            return
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
