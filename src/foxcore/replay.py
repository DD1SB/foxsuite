"""Replay appends records with provenance; originals remain untouched."""

import asyncio
from uuid import uuid4

from .service import IngestService


async def replay(service: IngestService, speed: float = 0) -> int:
    if speed < 0:
        raise ValueError("Replay speed cannot be negative; zero means immediate")
    records = service.store.raw_events(live_only=True)
    scope = "replay:" + uuid4().hex
    previous = None
    for raw in records:
        if speed and previous is not None:
            await asyncio.sleep(max(0, (raw.received_at - previous).total_seconds()) / speed)
        service.ingest(raw.raw_bytes, raw.source, raw.received_at, True, scope, raw.id)
        previous = raw.received_at
    return len(records)
