"""One process/loop owns FoxCore ingest and the cooperating Live/Bridge modules."""

import asyncio
import json
import os
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from foxbridge.cli import validate_output
from foxbridge.output import create_output
from foxbridge.persistence import DeliveryRepository
from foxbridge.service import BridgeService
from foxcore.config import SerialConfig
from foxcore.errors import error_message
from foxcore.events import ConnectionEvent
from foxcore.logging import SafeLogger
from foxcore.serial import SerialTransport
from foxcore.timesync import TimeSyncService
from foxlive.web import create_runtime, source

from .settings import Settings

log = SafeLogger(__name__)


class FoxSuiteRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.owner = create_runtime(
            settings.core.database_path, settings.core, settings.live, tolerate_live_failure=True
        )
        self.source_task: asyncio.Task[None] | None = None
        self.bridge_task: asyncio.Task[None] | None = None
        self.bridge: BridgeService | None = None
        self.bridge_error: str | None = None
        self.started_at = datetime.now(UTC).isoformat()
        self.closed = False
        self.testing = False

    async def start(self, identity_confirmation: bool) -> None:
        # Subscribe Bridge before admitting new source events. Recovery above never backfills it.
        try:
            self.start_bridge()
        except Exception as exc:
            self.bridge_error = error_message(exc)
            log.warning("ERROR FoxBridge startup failed: %s", self.bridge_error)
        self.start_source(identity_confirmation)

    def start_source(self, identity_confirmation: bool) -> None:
        if self.closed:
            return
        if self.source_task is not None and not self.source_task.done():
            raise ValueError("FoxIdentServer reader is already running")
        owner = self.owner
        owner.source_config = self.settings.core
        owner.source_enabled = self.settings.completed and not identity_confirmation
        owner.source_connected = False
        owner.source_health["state"] = "paused" if identity_confirmation else "disconnected"
        if owner.source_enabled:
            transport = SerialTransport(self.settings.core.serial)
            self.source_task = asyncio.create_task(
                source(owner, self.settings.core, transport), name="foxsuite-source"
            )

    async def stop_source(self) -> None:
        task, self.source_task = self.source_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.owner.source_enabled = False
        self.owner.source_connected = False

    def start_bridge(self) -> None:
        config = self.settings.bridge
        if self.closed or not config.enabled or not self.settings.completed:
            return
        if self.bridge_task is not None and not self.bridge_task.done():
            return
        validate_output(config, self.settings.core)
        bridge = BridgeService(
            DeliveryRepository(self.owner.store), config, create_output(config.output)
        )
        self.bridge, self.bridge_error = bridge, None
        self.owner.ingest.subscribe(bridge.accept)

        async def worker() -> None:
            try:
                await bridge.run()
            except Exception as exc:
                self.bridge_error = error_message(exc)
                log.warning("ERROR FoxBridge stopped: %s", self.bridge_error)
            finally:
                self.owner.ingest.unsubscribe(bridge.accept)

        self.bridge_task = asyncio.create_task(worker(), name="foxsuite-bridge")

    async def stop_bridge(self) -> None:
        bridge = self.bridge
        if bridge is not None:
            self.owner.ingest.unsubscribe(bridge.accept)
        task, self.bridge_task = self.bridge_task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if bridge is not None:
            # No abandoned in-memory reservations and no automatic history resend on restart.
            while not bridge.queue.empty():
                delivery = bridge.queue.get_nowait()
                try:
                    bridge.repository.finish(
                        delivery, "failed", "Bridge stopped; operator resend required"
                    )
                finally:
                    bridge.queue.task_done()
        self.bridge = None

    async def configure(self, settings: Settings, identity_confirmation: bool) -> None:
        changed_bridge = self.settings.bridge != settings.bridge
        changed_source = (
            self.settings.core != settings.core or self.settings.completed != settings.completed
        )
        if changed_source:
            await self.stop_source()
        if changed_bridge:
            await self.stop_bridge()
        self.settings = settings
        self.owner.ingest.minimum_unix_timestamp = settings.core.minimum_unix_timestamp
        if changed_source:
            self.owner.source_health.update(last_message=None, timesync=None, last_error=None)
        self.start_bridge()
        if changed_source:
            self.start_source(identity_confirmation)

    async def probe(self, port: str, baud_rate: int, delay: float = 0.6) -> dict[str, Any]:
        """Temporarily replace the owned reader; never run two FoxIdentServer readers."""
        if self.settings.bridge.enabled:
            from dataclasses import replace

            validate_output(
                self.settings.bridge, replace(self.settings.core, serial=SerialConfig(port))
            )
        await self.stop_source()
        self.testing = True
        transport = SerialTransport(SerialConfig(port, baud_rate))
        owner = self.owner
        sync = TimeSyncService(
            transport,
            self.settings.core.time_sync,
            lambda event: owner.store.diagnostic("timesync", json.dumps(asdict(event))),
        )
        connected: asyncio.Future[ConnectionEvent] = asyncio.get_running_loop().create_future()
        first = owner.store.db.execute("SELECT COALESCE(MAX(id),0) FROM raw_events").fetchone()[0]

        async def state(event: ConnectionEvent) -> None:
            if not connected.done():
                connected.set_result(event)

        async def line(raw: bytes) -> None:
            owner.ingest.ingest(raw, "serial:" + port)

        task = asyncio.create_task(transport.run(line, state), name="foxsuite-connection-test")
        try:
            connection = await asyncio.wait_for(asyncio.shield(connected), 5)
            if not connection.connected:
                return {"opened": False, "time_sent": False, "detail": "port_unavailable"}
            await asyncio.sleep(delay)
            event = await sync.send_now()
            await asyncio.sleep(delay)
            if task.done():
                task.result()
            observed = [
                row[0]
                for row in owner.store.db.execute(
                    "SELECT DISTINCT event_type FROM raw_events WHERE id>?", (first,)
                )
            ]
            return {"opened": True, "time_sent": event.success, "observed_types": observed}
        except TimeoutError:
            return {"opened": False, "time_sent": False, "detail": "port_unavailable"}
        finally:
            try:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            finally:
                try:
                    await sync.stop()
                finally:
                    await transport.disconnect()
                    self.testing = False

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.stop_source()
        finally:
            try:
                await self.stop_bridge()
            finally:
                self.owner.store.close()

    def status(self) -> dict[str, Any]:
        owner, config = self.owner, self.settings.bridge
        running = self.bridge_task is not None and not self.bridge_task.done()
        output_connected = bool(self.bridge and self.bridge.output.connected)
        error = self.bridge_error
        if running and self.bridge and not output_connected:
            error = self.bridge.output_detail
        configured = config.output.type == "file" or bool(config.output.port)
        bridge_state = (
            "error"
            if error
            else "not_configured"
            if not configured
            else "running"
            if running
            else "stopped"
        )
        try:
            event = owner.live.repo.running()
        except Exception as exc:
            owner.live.failure = exc
            event = None
        last = DeliveryRepository(owner.store).list_deliveries(config.target, 1)
        counts = dict(
            owner.store.db.execute(
                "SELECT status,COUNT(*) FROM bridge_deliveries WHERE target=? GROUP BY status",
                (config.target,),
            )
        )
        try:
            app_version = version("foxsuite")
        except PackageNotFoundError:
            app_version = "0.5.0"
        return {
            "product": "FoxSuite",
            "version": app_version,
            "pid": os.getpid(),
            "process_model": "single_process",
            "started_at": self.started_at,
            "core": {
                "state": "error" if owner.source_health["state"] == "error" else "running",
                "statistics": owner.store.stats(),
            },
            "source": owner.source_health
            | {
                "state": "testing" if self.testing else owner.source_health["state"],
                "port": self.settings.core.serial.port,
                "connected": owner.source_connected,
                "time_sync_enabled": self.settings.core.time_sync.enabled,
                "reader_running": self.source_task is not None and not self.source_task.done(),
            },
            "live": {
                "state": "error" if owner.live.failure else "running",
                "last_error": error_message(owner.live.failure) if owner.live.failure else None,
                "event": event.model_dump(mode="json") if event else None,
                "url": "/live",
            },
            "bridge": {
                "state": bridge_state,
                "running": running,
                "enabled": config.enabled,
                "configured": configured,
                "endpoint": config.output.endpoint,
                "output_connected": output_connected,
                "last_error": error,
                "queue_size": self.bridge.queue.qsize() if self.bridge else 0,
                "status_counts": counts,
                "last_delivery": last[0] if last else None,
            },
        }
