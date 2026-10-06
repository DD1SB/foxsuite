"""Raw-first coordinator. Persistence errors always escape to the operator."""

from collections.abc import Callable
from datetime import UTC, datetime

from .events import Message, Punch
from .logging import SafeLogger
from .persistence import RawEvent, Store
from .protocol import normalize, parse_line

log = SafeLogger(__name__)


class IngestService:
    def __init__(
        self,
        store: Store,
        parser: Callable[[bytes], Message] = parse_line,
        minimum_unix_timestamp: int | None = None,
    ) -> None:
        self.store = store
        self.parser = parser
        self.minimum_unix_timestamp = minimum_unix_timestamp
        self.subscribers: list[Callable[[Punch], None]] = []

    def subscribe(self, callback: Callable[[Punch], None]) -> None:
        self.subscribers.append(callback)

    def ingest(
        self,
        raw: bytes,
        source: str,
        received: datetime | None = None,
        replayed: bool = False,
        scope: str = "live",
        original_raw_id: int | None = None,
    ) -> Punch | None:
        timestamp = received or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("Receive time must be timezone aware")
        timestamp = timestamp.astimezone(UTC)
        raw_id = self.store.insert_raw(raw, timestamp, source, replayed, scope, original_raw_id)
        return self.process(RawEvent(raw_id, timestamp, raw, source, replayed, scope))

    def recover(self) -> None:
        for raw in self.store.raw_events(pending=True):
            self.process(raw)

    def process(self, raw: RawEvent) -> Punch | None:
        try:
            message = self.parser(raw.raw_bytes)
            punch = normalize(message, raw.id, raw.received_at, raw.source, raw.replayed, raw.scope)
            status, kind, error = message.status, message.event_type, message.error
        except Exception as exc:
            punch, status, kind, error = None, "failed", "processing_error", str(exc)
        if error:
            log.warning("raw_id=%s parse/normalization error: %s", raw.id, error)
        # Separate committed raw record exists even if this transaction fails.
        punch = self.store.finish(raw.id, status, kind, error, punch)
        if punch is not None:
            if (
                self.minimum_unix_timestamp is not None
                and punch.station_timestamp < self.minimum_unix_timestamp
            ):
                log.warning("raw_id=%s timestamp below configured threshold", raw.id)
            log.debug("normalized raw_id=%s duplicate=%s", raw.id, punch.duplicate)
            for callback in tuple(self.subscribers):
                try:
                    callback(punch)
                except Exception:
                    log.exception("Subscriber failed for raw_id=%s", raw.id)
        return punch
