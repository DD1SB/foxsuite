"""Operational M1 CLI. No product UI or competition logic."""

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from .config import Config, load_config
from .events import ConnectionEvent, TimeSyncEvent
from .logging import SafeLogger
from .persistence import Store
from .replay import replay
from .serial import SerialTransport
from .service import IngestService
from .simulator import emit
from .timesync import TimeSyncService

log = SafeLogger(__name__)


async def run_serial(config: Config, store: Store, service: IngestService) -> None:
    transport = SerialTransport(config.serial)

    def record(event: TimeSyncEvent) -> None:
        store.diagnostic("timesync", json.dumps(asdict(event)))

    sync = TimeSyncService(transport, config.time_sync, record)

    async def state(event: ConnectionEvent) -> None:
        store.diagnostic("connection", json.dumps(asdict(event)))
        await sync.connection_changed(event)

    async def line(raw: bytes) -> None:
        service.ingest(raw, "serial:" + config.serial.port)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(transport.run(line, state))
            group.create_task(sync.wait_failure())
    finally:
        await sync.stop()
        await transport.disconnect()


async def manual_time(config: Config, store: Store) -> bool:
    transport = SerialTransport(config.serial)
    try:
        await transport.connect()
        # Firmware setup has a 500ms startup delay; USB open may reset the board.
        await asyncio.sleep(0.6)
        sync = TimeSyncService(
            transport,
            config.time_sync,
            lambda e: store.diagnostic("timesync", json.dumps(asdict(e))),
        )
        return (await sync.send_now()).success
    finally:
        await transport.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="FoxSuite M1 infrastructure")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--db", type=Path, help="Override database path")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--stdin", action="store_true", help="Ingest newline bytes from stdin")
    sub.add_parser("status")
    sub.add_parser("db-info")
    sub.add_parser("send-time")
    rp = sub.add_parser("replay")
    rp.add_argument("--speed", type=float, default=0, help="0 immediate, 10 ten times faster")
    sim = sub.add_parser("simulate")
    sim.add_argument("--count", type=int, default=1)
    sim.add_argument("--interval", type=float, default=0)
    args = parser.parse_args()
    try:
        if args.command == "simulate":
            emit(args.count, args.interval)
            return
        config = load_config(args.config) if args.config else Config()
        logging.basicConfig(
            level=config.logging_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        log.info("FoxSuite M1 startup")
        store = Store(args.db or config.database_path)
        try:
            log.info("Database path=%s version=%s", args.db or config.database_path, store.version)
            service = IngestService(store, minimum_unix_timestamp=config.minimum_unix_timestamp)
            if args.command in {"db-info", "status"}:
                stats = store.stats()
                if args.command == "status":
                    stats["connectivity_note"] = "last recorded state; not a live device probe"
                print(json.dumps(stats, indent=2))
            elif args.command == "replay":
                service.recover()
                print(f"Replayed {asyncio.run(replay(service, args.speed))} raw records")
            elif args.command == "send-time":
                if not asyncio.run(manual_time(config, store)):
                    raise RuntimeError("TimeSync write failed")
            else:
                service.recover()
                if args.stdin:
                    for raw in sys.stdin.buffer:
                        service.ingest(raw, "stdin")
                else:
                    asyncio.run(run_serial(config, store, service))
        finally:
            store.close()
            log.info("FoxSuite shutdown")
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("FoxSuite operation failed (persistence errors are fatal)")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
