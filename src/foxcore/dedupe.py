"""Retry identity excludes RSSI and receive time, includes original station time."""

from .events import Punch


def duplicate_key(punch: Punch) -> tuple[str, str, int, int, str, int]:
    return (
        punch.scope,
        punch.source,
        punch.station_id,
        punch.sequence,
        punch.uid,
        punch.station_timestamp,
    )
