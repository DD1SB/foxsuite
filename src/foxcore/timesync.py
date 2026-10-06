"""Independent clock policy. A successful write is not a firmware/hardware ACK."""

import asyncio
import time
from collections.abc import Callable

from .config import TimeSyncConfig
from .events import ConnectionEvent, TimeSyncEvent
from .logging import SafeLogger
from .serial import Transport

log = SafeLogger(__name__)


class TimeSyncService:
    def __init__(
        self,
        transport: Transport,
        config: TimeSyncConfig,
        record: Callable[[TimeSyncEvent], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.transport = transport
        self.config = config
        self.record = record
        self.clock = clock
        self._task: asyncio.Task[None] | None = None

    async def send_now(self) -> TimeSyncEvent:
        unix = int(self.clock())
        if not 0 < unix <= 4294967295:
            raise ValueError("Firmware time must be positive uint32 Unix seconds")
        try:
            await self.transport.send(
                self.config.command_template.format(unix=unix).encode("ascii")
            )
            event = TimeSyncEvent(unix, True, "command written; firmware confirmation is separate")
        except Exception as exc:
            event = TimeSyncEvent(unix, False, str(exc))
        log.info("TimeSync unix=%s success=%s detail=%s", unix, event.success, event.detail)
        self.record(event)
        return event

    async def connection_changed(self, event: ConnectionEvent) -> None:
        await self.stop()
        if event.connected and self.config.enabled:
            self._task = asyncio.create_task(self._periodic())

    async def _periodic(self) -> None:
        if self.config.on_connect:
            await self.send_now()
        while self.transport.connected:
            await asyncio.sleep(self.config.interval_seconds)
            if self.transport.connected:
                await self.send_now()

    async def wait_failure(self) -> None:
        """Surface diagnostic persistence failures instead of orphaning task exceptions."""
        while True:
            task = self._task
            if task is not None and task.done():
                task.result()
            await asyncio.sleep(0.05)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
