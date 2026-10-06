"""Canonical PC models, independent of serial formatting."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Message:
    event_type: str
    status: str
    payload: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class TagEvent(Message):
    pass


@dataclass(frozen=True)
class DiagnosticEvent(Message):
    """Firmware time, time_request, sync and error messages."""


@dataclass(frozen=True)
class UnknownJsonEvent(Message):
    pass


@dataclass(frozen=True)
class MalformedLineEvent(Message):
    pass


@dataclass(frozen=True)
class ConnectionEvent:
    connected: bool
    detail: str


@dataclass(frozen=True)
class TimeSyncEvent:
    unix: int
    success: bool
    detail: str


@dataclass(frozen=True)
class Punch:
    raw_event_id: int
    received_at_pc: datetime
    station_id: int
    station_timestamp: int
    sequence: int
    uid: str
    callsign: str | None
    rssi: int | None
    source: str
    replayed: bool
    scope: str = "live"
    id: int | None = None
    duplicate: bool = False
    duplicate_of: int | None = None
