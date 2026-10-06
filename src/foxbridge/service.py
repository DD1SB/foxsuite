"""FoxCore event subscriber with a bounded queue and durable at-most-once reservations."""

import asyncio

from foxcore.events import Punch
from foxcore.logging import SafeLogger

from .config import BridgeConfig
from .output import SportIdentOutput
from .persistence import Delivery, DeliveryRepository
from .sportident import SportIdentEncoder

log = SafeLogger(__name__)


class BridgeService:
    def __init__(
        self,
        repository: DeliveryRepository,
        config: BridgeConfig,
        output: SportIdentOutput,
        allow_replay: bool = False,
    ) -> None:
        self.repository = repository
        self.config = config
        self.output = output
        self.allow_replay = allow_replay
        self.encoder = SportIdentEncoder()
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=config.queue_capacity)
        self._fatal: Exception | None = None
        self._last_state: tuple[bool, str] | None = None
        self._next_connect_at = 0.0

    def accept(self, punch: Punch) -> None:
        try:
            self.enqueue(punch)
        except Exception as exc:
            # FoxCore isolates subscriber errors. A ledger failure must also stop the bridge.
            self._fatal = exc
            log.warning("ERROR FoxBridge delivery persistence failed: %s", exc)

    def enqueue(self, punch: Punch, explicit: bool = False) -> Delivery | None:
        result = self.repository.prepare(
            punch, self.config, self.encoder, self.allow_replay, explicit
        )
        if result is not None:
            if result.status == "queued":
                try:
                    self.queue.put_nowait(result.id)
                except asyncio.QueueFull:
                    self.repository.finish(
                        result.id, "failed", "Bridge queue full; operator resend required"
                    )
                    result = self.repository.get(result.id)
            if result.status in {"duplicate_ignored", "replay_blocked"}:
                log.debug("FoxBridge skipped punch=%s reason=%s", punch.id, result.error)
            elif result.error:
                log.warning("ERROR punch=%s %s", punch.id, result.error)
        return result

    def _state(self, connected: bool, detail: str) -> None:
        state = (connected, detail)
        if state != self._last_state:
            self.repository.output_state(self.config, connected, detail)
            log.info(
                "FoxBridge output connected=%s endpoint=%s detail=%s",
                connected,
                self.config.output.endpoint,
                detail,
            )
            self._last_state = state
            if not connected and detail.startswith("Output"):
                log.warning("ERROR FoxBridge output %s: %s", self.config.output.endpoint, detail)

    async def _connect(self) -> bool:
        if self.output.connected:
            return True
        now = asyncio.get_running_loop().time()
        if now < self._next_connect_at:
            return False
        try:
            await self.output.connect()
        except OSError as exc:
            self._next_connect_at = now + self.config.output.reconnect_interval_seconds
            self._state(False, f"Output unavailable: {exc}")
            return False
        self._state(True, "Output opened; peer acceptance is unacknowledged")
        return True

    async def _deliver(self, delivery_id: int) -> None:
        delivery = self.repository.claim(delivery_id)
        if delivery is None:
            return
        attempted_write = False
        try:
            if not await self._connect():
                self.repository.finish(
                    delivery.id, "failed", "Output port unavailable; operator resend required"
                )
                return
            assert delivery.frame is not None
            attempted_write = True
            await self.output.write(delivery.frame)
        except asyncio.CancelledError:
            self.repository.finish(
                delivery.id,
                "uncertain" if attempted_write else "failed",
                "Shutdown interrupted delivery; inspect receiver before resend",
            )
            raise
        except OSError as exc:
            self.repository.finish(
                delivery.id, "uncertain" if attempted_write else "failed", str(exc)
            )
            await self.output.close()
            self._state(False, f"Output write failed: {exc}")
            log.warning("ERROR FoxBridge delivery=%s failed: %s", delivery.id, exc)
        else:
            self.repository.finish(delivery.id, "sent")
            log.debug("FoxBridge sent delivery=%s punch=%s", delivery.id, delivery.punch_id)

    async def run(self, connect_on_start: bool = True) -> None:
        try:
            if connect_on_start:
                await self._connect()
            while True:
                if self._fatal is not None:
                    raise self._fatal
                try:
                    delivery_id = await asyncio.wait_for(
                        self.queue.get(), min(self.config.output.reconnect_interval_seconds, 0.1)
                    )
                except TimeoutError:
                    if connect_on_start and not self.output.connected:
                        await self._connect()
                    continue
                try:
                    await self._deliver(delivery_id)
                finally:
                    self.queue.task_done()
        finally:
            await self.output.close()
            self._state(False, "Bridge stopped")

    async def drain(self) -> None:
        await self.queue.join()
