"""Desk-only translations, local-time choices and read-only RFID observations."""

import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .persistence import LiveRepository


def language(value: str) -> str:
    return "de" if value.split(",")[0].split(";")[0].split("-")[0].lower() == "de" else "en"


@lru_cache(maxsize=2)
def catalog(lang: str) -> dict[str, str]:
    data: Any = json.loads(
        (Path(__file__).parent / "static" / "translations" / f"{language(lang)}.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v for k, v in data.items()
    ):
        raise ValueError("Invalid FoxLive translation catalog")
    return dict(data)


def translate(key: str, lang: str = "en", **values: Any) -> str:
    fallback = catalog("en")
    text = catalog(lang).get(key, fallback.get(key, fallback["common.unavailable"]))
    return text.format_map(values) if values else text


ERROR_KEYS = {
    "Runner does not exist": "error.runner_missing",
    "Runner is inactive": "error.runner_inactive",
    "Runner names cannot be blank": "error.names_blank",
    "Runner is already registered in this event": "error.runner_registered",
    "Birth year or birth date is required": "runner.birth_required",
    "Invalid birth date": "error.birth_invalid",
    "Birth date cannot be in the future": "error.birth_future",
    "Birth year cannot be in the future": "error.birth_future",
    "Birth year does not match birth date": "error.birth_mismatch",
    "Club does not exist": "error.club_missing",
    "Club name cannot be blank": "error.club_blank",
    "Club code already exists": "error.club_exists",
    "Category does not exist": "error.category_missing",
    "Category is not enabled for this event": "error.category_disabled",
    "Category is inactive": "error.category_inactive",
    "Category selection cannot be changed; enable another category instead": "error.category_selection",
    "Runner selection is ambiguous; register manually": "error.runner_ambiguous",
    "Runner appears twice in CSV; register ambiguous people manually": "error.csv_runner_repeat",
    "Club selection is ambiguous": "error.club_ambiguous",
    "Club code and name do not match": "error.club_mismatch",
    "Archived events are read-only": "error.archived",
    "Cannot start event: another event is already RUNNING": "error.other_running",
    "Category does not exist in this event": "error.category_missing",
    "Category code/name cannot be blank": "error.category_blank",
    "Participant does not exist in this event": "error.participant_missing",
    "Participant names cannot be blank": "error.names_blank",
    "Station name cannot be blank": "error.station_blank",
    "Station ID does not match path": "error.station_path",
    "Event name cannot be blank": "error.event_blank",
    "Competition times must use whole seconds": "error.whole_seconds",
    "Configured time fails event timestamp validation": "error.time_guard",
    "Predefined start fails event timestamp validation": "error.time_guard",
    "Competition end must not precede start": "error.end_before_start",
    "Exclusion requires a reason of 1..1000 characters": "error.reason",
    "Punch is not associated with this event": "error.punch_missing",
    "UID must contain complete hexadecimal bytes": "error.uid_invalid",
    "CSV exceeds 2 MB": "error.csv_size",
    "Required CSV headers: start_number,first_name,last_name,category": "error.csv_headers",
    "Unsupported CSV columns": "error.csv_columns",
    "Column count does not match headers": "error.csv_count",
    "Invalid ISO timestamp": "error.time_invalid",
    "Local time is ambiguous or nonexistent; supply an explicit offset": "time.ambiguous",
    "This local time does not exist during the clock change": "time.nonexistent",
}
ERROR_PATTERNS = (
    (r"Category code (.+) already exists", "error.category_exists", "code"),
    (r"Start number (\d+) already exists", "error.start_number_exists", "number"),
    (r"Unknown IANA timezone: (.+)", "error.timezone", "timezone"),
    (r"Category (.+) does not exist", "error.csv_category", "code"),
    (r"Duplicate start number (\d+) in CSV", "error.csv_number", "number"),
    (r"Duplicate UID (.+) in CSV", "error.csv_uid", "uid"),
)


def error_text(message: str, lang: str, *, csv: bool = False, operator: bool = False) -> str:
    """Translate at HTTP boundary only; English machine API remains backward compatible."""
    if language(lang) == "en" and not operator:
        return message
    if message in ERROR_KEYS:
        return translate(ERROR_KEYS[message], lang)
    match = re.fullmatch(r"UID (.+) is already assigned to participant (\d+)", message)
    if match:
        return translate("error.uid_assigned", lang, uid=match[1], number=match[2])
    match = re.fullmatch(r"Cannot transition (\w+) to (\w+)", message)
    if match:
        return translate(
            "error.transition",
            lang,
            before=translate("event." + match[1], lang),
            after=translate("event." + match[2], lang),
        )
    if re.fullmatch(r"Event \d+ does not exist", message):
        return translate("error.event_missing", lang)
    if message.startswith("Invalid isoformat string"):
        return translate("error.time_invalid", lang)
    for pattern, key, field in ERROR_PATTERNS:
        match = re.fullmatch(pattern, message)
        if match:
            return translate(key, lang, **{field: match[1]})
    return translate("error.csv_parse", lang) if csv else message


def validation_text(error: dict[str, Any], lang: str) -> str:
    kind, ctx = error["type"], error.get("ctx", {})
    key, count = "error.validation", 0
    if kind == "missing":
        key = "error.required"
    elif kind in {"int_parsing", "int_type", "int_from_float", "float_parsing"}:
        key = "error.number"
    elif kind in {"enum", "literal_error", "bool_parsing"}:
        key = "error.choice"
    elif kind in {"string_too_short", "too_short"}:
        key, count = "error.too_short", ctx.get("min_length", 0)
    elif kind in {"string_too_long", "too_long"}:
        key, count = "error.too_long", ctx.get("max_length", 0)
    elif kind == "greater_than_equal":
        key, count = "error.minimum", ctx.get("ge", 0)
    elif kind == "less_than_equal":
        key, count = "error.maximum", ctx.get("le", 0)
    elif kind == "extra_forbidden":
        key = "error.unexpected"
    return translate(key, lang, count=count)


def local_time_options(value: str, timezone: str) -> list[dict[str, str]]:
    """Resolve a native datetime-local value without ever guessing a DST fold/gap."""
    try:
        parsed = datetime.fromisoformat(value)
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone}") from exc
    except ValueError as exc:
        raise ValueError("Invalid ISO timestamp") from exc
    if parsed.tzinfo is not None:
        raise ValueError("Invalid ISO timestamp")
    if parsed.microsecond:
        raise ValueError("Competition times must use whole seconds")
    try:
        candidates = sorted(
            {
                parsed.replace(tzinfo=zone, fold=fold).astimezone(UTC)
                for fold in (0, 1)
                if parsed.replace(tzinfo=zone, fold=fold)
                .astimezone(UTC)
                .astimezone(zone)
                .replace(tzinfo=None)
                == parsed
            }
        )
    except (ValueError, OverflowError) as exc:
        raise ValueError("Invalid ISO timestamp") from exc
    if not candidates:
        raise ValueError("This local time does not exist during the clock change")
    return [
        {
            "instant": candidate.isoformat(),
            "offset": candidate.astimezone(zone).strftime("%z")[:3]
            + ":"
            + candidate.astimezone(zone).strftime("%z")[3:],
        }
        for candidate in candidates
    ]


def rfid_candidates(
    repo: LiveRepository, event_id: int, after_id: int | None = None, limit: int = 20
) -> dict[str, Any]:
    """Read original live facts, including DRAFT registration; never create associations."""
    event = repo.event(event_id)
    if (after_id is not None and after_id < 0) or not 1 <= limit <= 100:
        raise ValueError("Invalid source ID/limit")
    cursor = repo.db.execute("SELECT COALESCE(MAX(id),0) FROM punches").fetchone()[0]
    # Rank once, rather than an N+1 search through source history for each tag.
    order = "ASC" if after_id is not None else "DESC"
    rows = repo.db.execute(
        "WITH candidates AS (SELECT p.*,ROW_NUMBER() OVER(PARTITION BY uid ORDER BY id DESC) AS latest "
        "FROM punches p WHERE p.id>? AND p.id<=? AND p.scope='live' AND p.replayed=0 AND p.duplicate=0 "
        "AND NOT EXISTS(SELECT 1 FROM live_entries e "
        "WHERE e.event_id=? AND e.active=1 AND e.uid=p.uid)) "
        "SELECT p.*,s.display_name AS station_name FROM candidates p "
        "LEFT JOIN live_event_stations s ON s.event_id=? AND s.station_id=p.station_id "
        + ("WHERE p.latest=1 " if after_id is None else "")
        + f"ORDER BY p.id {order} LIMIT ?",
        (after_id or 0, cursor, event_id, event_id, limit),
    )
    items = []
    for row in rows:
        received = datetime.fromisoformat(row["received_at"]).timestamp()
        stamp = row["station_timestamp"]
        items.append(
            {
                "id": row["id"],
                "uid": row["uid"],
                "station_id": row["station_id"],
                "station_name": row["station_name"],
                "station_timestamp": stamp,
                "received_at": row["received_at"],
                "station_time_valid": event.minimum_unix_timestamp <= stamp <= 4294967295
                and abs(received - stamp) <= event.maximum_receive_skew_seconds,
            }
        )
    return {"cursor": cursor, "items": items}
