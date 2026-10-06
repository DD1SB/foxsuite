"""Operational FoxBridge commands; no competition administration."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from foxcore.config import Config
from foxcore.logging import SafeLogger
from foxcore.persistence import Store
from foxcore.replay import replay
from foxcore.service import IngestService

from .config import BridgeConfig, load_bridge_config
from .mapping import MappingRepository, Role
from .output import create_output
from .persistence import DeliveryRepository
from .service import BridgeService
from .sportident import SportIdentEncoder, SportIdentPunch
from .time import convert_time

log = SafeLogger(__name__)


def register_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser("bridge", help="FoxBridge live SPORTident gateway")
    commands = parser.add_subparsers(dest="bridge_command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--stdin", action="store_true")
    run.add_argument("--show-punches", action="store_true")
    run.add_argument("--allow-replay-output", action="store_true")
    commands.add_parser("status")
    deliveries = commands.add_parser("deliveries")
    deliveries.add_argument("--limit", type=int, default=50)
    for kind in ["uid", "station"]:
        mapping = commands.add_parser(kind + "-map").add_subparsers(
            dest="mapping_action", required=True
        )
        mapping.add_parser("list")
        add = mapping.add_parser("add")
        remove = mapping.add_parser("remove")
        if kind == "uid":
            add.add_argument("uid")
            add.add_argument("card_number", type=int)
            remove.add_argument("uid")
        else:
            add.add_argument("station_id", type=int)
            add.add_argument("control_code", type=int)
            add.add_argument("--role", choices=[r.value for r in Role], default="CONTROL")
            remove.add_argument("station_id", type=int)
        mapping.add_parser("import").add_argument("path", type=Path)
    test = commands.add_parser("test-frame", help="Print one hex frame; does not open output")
    test.add_argument("card_number", type=int)
    test.add_argument("control_code", type=int)
    test.add_argument("--timestamp", type=int, help="Unix UTC seconds; defaults to now")
    test.add_argument("--offset", type=int, default=0)
    resend = commands.add_parser(
        "resend", help="Explicitly resend ONE punch; may duplicate Fjw data"
    )
    resend.add_argument("punch_id", type=int)
    resend.add_argument("--allow-replay-output", action="store_true")
    rp = commands.add_parser("replay")
    rp.add_argument("--speed", type=float, default=0)
    rp.add_argument("--allow-replay-output", action="store_true")


def validate_output(config: BridgeConfig, core: Config) -> None:
    if config.output.type == "serial":
        if not config.output.port:
            raise ValueError("Configure FoxBridge output port in [bridge.output].port")

        # Windows COM names are case-insensitive; accept normal and device-prefixed spellings.
        def normalize_port(port: str) -> str:
            return port.removeprefix("\\\\.\\").casefold()

        if normalize_port(config.output.port) == normalize_port(core.serial.port):
            raise ValueError("FoxBridge output port must differ from the FoxIdentServer input port")


async def _stdin(service: IngestService) -> None:
    while raw := await asyncio.to_thread(sys.stdin.buffer.readline):
        service.ingest(raw, "stdin")


async def _run(
    args: argparse.Namespace,
    core: Config,
    config: BridgeConfig,
    store: Store,
    service: IngestService,
) -> None:
    # Existing raw recovery precedes subscription: restarting never backfills historical punches.
    service.recover()
    command = args.bridge_command
    allow_replay = args.allow_replay_output
    if command == "run" and not config.enabled:
        raise ValueError("FoxBridge is disabled; set [bridge].enabled = true")
    if command != "replay" or allow_replay:
        validate_output(config, core)
    if command == "run" and not args.stdin and not core.serial.port:
        raise ValueError("Configure a FoxIdentServer serial port in [serial].port")
    repo = DeliveryRepository(store)
    bridge = BridgeService(repo, config, create_output(config.output), allow_replay)
    service.subscribe(bridge.accept)
    if command == "run" and args.show_punches:
        service.subscribe(
            lambda p: log.info(
                "Punch id=%s station=%s uid=%s time=%s duplicate=%s",
                p.id,
                p.station_id,
                p.uid,
                p.station_timestamp,
                p.duplicate,
            )
        )
    log.info(
        "FoxBridge target=%s endpoint=%s timezone=%s",
        config.target,
        config.output.endpoint,
        config.sportident.timezone,
    )

    async def source() -> None:
        if command == "resend":
            delivery = bridge.enqueue(store.get_punch(args.punch_id), explicit=True)
            assert delivery is not None
            if delivery.status != "queued":
                raise ValueError(delivery.error or delivery.status)
        elif command == "replay":
            count = await replay(service, args.speed)
            log.info(
                "FoxCore replay processed %s raw records; output enabled=%s", count, allow_replay
            )
        elif args.stdin:
            await _stdin(service)
        else:
            from foxcore.cli import run_serial

            await run_serial(core, store, service)

    async with asyncio.TaskGroup() as group:
        worker = group.create_task(bridge.run(connect_on_start=command != "replay" or allow_replay))
        await group.create_task(source())
        await bridge.drain()
        worker.cancel()
    if command == "resend":
        latest = repo.list_deliveries(config.target, 1)[0]
        if latest["status"] != "sent":
            raise ValueError(f"Resend {latest['status']}: {latest['error']}")


async def execute(
    args: argparse.Namespace, core: Config, store: Store, service: IngestService
) -> None:
    config = load_bridge_config(args.config)
    command = args.bridge_command
    mapping = MappingRepository(store)
    if command in {"uid-map", "station-map"}:
        kind = "uid" if command == "uid-map" else "station"
        action = args.mapping_action
        if action == "list":
            entries = mapping.list_uids() if kind == "uid" else mapping.list_stations()
            print(json.dumps([asdict(entry) for entry in entries], indent=2))
        elif action == "add":
            entry = (
                mapping.add_uid(args.uid, args.card_number)
                if kind == "uid"
                else mapping.add_station(args.station_id, args.control_code, Role(args.role))
            )
            print(json.dumps(asdict(entry)))
        elif action == "remove":
            if kind == "uid":
                mapping.remove_uid(args.uid)
            else:
                mapping.remove_station(args.station_id)
        else:
            print(f"Imported {mapping.import_csv(args.path, kind)} mapping rows")
    elif command == "status":
        print(json.dumps(DeliveryRepository(store).status(config), indent=2))
    elif command == "deliveries":
        if args.limit < 1:
            raise ValueError("Delivery limit must be positive")
        print(
            json.dumps(
                DeliveryRepository(store).list_deliveries(config.target, args.limit), indent=2
            )
        )
    elif command == "test-frame":
        unix = args.timestamp if args.timestamp is not None else int(time.time())
        encoded = SportIdentEncoder().encode_punch(
            SportIdentPunch(
                args.card_number,
                args.control_code,
                convert_time(unix, config.sportident.timezone, config.sportident.week_counter),
                args.offset,
            )
        )
        print(encoded.hex(" ").upper())
    else:
        await _run(args, core, config, store, service)
