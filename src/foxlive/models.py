"""Typed domain inputs and derived state; no HTTP or serial policy."""

from datetime import UTC, date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field


class State(StrEnum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class Timing(StrEnum):
    PUNCH_START_FINISH = "PUNCH_START_FINISH"
    PREDEFINED_START = "PREDEFINED_START"


class Role(StrEnum):
    CONTROL = "CONTROL"
    START = "START"
    FINISH = "FINISH"


class CompetitionStatus(StrEnum):
    REGISTERED = "REGISTERED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    DNS = "DNS"
    DNF = "DNF"
    DSQ = "DSQ"


class InterpretationStatus(StrEnum):
    VALID_CONTROL = "VALID_CONTROL"
    REPEAT_CONTROL = "REPEAT_CONTROL"
    VALID_START = "VALID_START"
    REPEAT_START = "REPEAT_START"
    VALID_FINISH = "VALID_FINISH"
    REPEAT_FINISH = "REPEAT_FINISH"
    UNKNOWN_UID = "UNKNOWN_UID"
    UNKNOWN_STATION = "UNKNOWN_STATION"
    DISABLED_STATION = "DISABLED_STATION"
    OUTSIDE_EVENT_WINDOW = "OUTSIDE_EVENT_WINDOW"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_FOR_TIMING = "INVALID_FOR_TIMING"
    SOURCE_DUPLICATE = "SOURCE_DUPLICATE"
    MANUALLY_EXCLUDED = "MANUALLY_EXCLUDED"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventData(Model):
    name: str = Field(min_length=1, max_length=200)
    date: str
    timezone: str = "UTC"
    description: str = Field(default="", max_length=2000)
    timing_mode: Timing = Timing.PUNCH_START_FINISH
    competition_start_at: str | None = None
    competition_end_at: str | None = None
    default_start_at: str | None = None
    minimum_unix_timestamp: int = Field(default=1577836800, ge=1, le=4294967295)
    maximum_receive_skew_seconds: int = Field(default=86400, ge=1, le=31536000)


class Event(EventData):
    id: int
    state: State
    cursor: int
    created_at: str
    updated_at: str


class CategoryData(Model):
    code: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=200)
    active: bool = True
    display_order: int = 0


class Category(CategoryData):
    id: int
    event_id: int


class EntryData(Model):
    start_number: int = Field(ge=1, le=1000000000)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    category_id: int = Field(ge=1)
    uid: str | None = None
    club: str = Field(default="", max_length=200)
    start_time: str | None = None
    manual_status: CompetitionStatus | None = None
    active: bool = True


class Entry(EntryData):
    id: int
    event_id: int
    created_at: str
    updated_at: str


class StationData(Model):
    station_id: int = Field(ge=0, le=65535)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role
    enabled: bool = True
    display_order: int = 0


class Station(StationData):
    event_id: int


class Interpretation(Model):
    punch_id: int
    participant_id: int | None = None
    status: InterpretationStatus
    role: Role | None = None
    reason: str = ""


class Result(Model):
    participant_id: int
    category_id: int
    start_number: int
    status: CompetitionStatus = CompetitionStatus.REGISTERED
    controls: int = 0
    start: int | None = None
    finish: int | None = None
    elapsed: int | None = None
    rank: int | None = None
    eligible: bool = True


class Calculation(Model):
    interpretations: list[Interpretation]
    results: list[Result]
    counts: dict[str, int]


def instant(value: str | None, timezone: str) -> str | None:
    """Canonical UTC ISO instant. Never guess a local DST fold or gap."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        zone = ZoneInfo(timezone)
        if parsed.tzinfo is None:
            candidates = {
                parsed.replace(tzinfo=zone, fold=fold).astimezone(UTC)
                for fold in (0, 1)
                if parsed.replace(tzinfo=zone, fold=fold)
                .astimezone(UTC)
                .astimezone(zone)
                .replace(tzinfo=None)
                == parsed
            }
            if len(candidates) != 1:
                raise ValueError(
                    "Local time is ambiguous or nonexistent; supply an explicit offset"
                )
            parsed = candidates.pop()
        return parsed.astimezone(UTC).isoformat()
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone}") from exc
    except (TypeError, OverflowError) as exc:
        raise ValueError("Invalid ISO timestamp") from exc


def unix(value: str | None) -> int | None:
    return int(datetime.fromisoformat(value).timestamp()) if value else None


def validate_event(data: EventData) -> EventData:
    date.fromisoformat(data.date)
    try:
        ZoneInfo(data.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {data.timezone}") from exc
    if not data.name.strip():
        raise ValueError("Event name cannot be blank")
    values = {
        field: instant(getattr(data, field), data.timezone)
        for field in ("competition_start_at", "competition_end_at", "default_start_at")
    }
    start, end = unix(values["competition_start_at"]), unix(values["competition_end_at"])
    if start is not None and end is not None and start > end:
        raise ValueError("Competition end must not precede start")
    for value in values.values():
        seconds = unix(value)
        if seconds is not None and not data.minimum_unix_timestamp <= seconds <= 4294967295:
            raise ValueError("Configured time fails event timestamp validation")
    return data.model_copy(update=values)
