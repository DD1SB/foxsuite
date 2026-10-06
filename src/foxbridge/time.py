"""Explicit UTC-to-event-wall-time conversion; never changes the source punch."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .sportident import PunchTime, bounded_integer


def convert_time(unix: int, timezone: str, week_counter: int = 0) -> PunchTime:
    bounded_integer(unix, 1, 4294967295, "Fox timestamp")
    bounded_integer(week_counter, 0, 3, "Week counter")
    local = datetime.fromtimestamp(unix, UTC).astimezone(ZoneInfo(timezone))
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise ValueError("Event-local time is ambiguous during DST fall-back")
    weekday = (local.weekday() + 1) % 7
    day_pm = (week_counter << 4) | (weekday << 1) | int(local.hour >= 12)
    seconds = (local.hour % 12) * 3600 + local.minute * 60 + local.second
    return PunchTime(day_pm, seconds)
