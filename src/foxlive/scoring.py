"""Pure deterministic interpretation and the one M3 scoring strategy."""

from collections import Counter
from typing import Protocol

from foxcore.events import Punch

from .models import (
    Calculation,
    Category,
    Entry,
    Event,
    Interpretation,
    Result,
    Role,
    Timing,
    unix,
)
from .models import (
    CompetitionStatus as CS,
)
from .models import (
    InterpretationStatus as IS,
)


class ScoringStrategy(Protocol):
    def calculate(self, results: list[Result]) -> list[Result]: ...


class DistinctControlsThenTime:
    def calculate(self, results: list[Result]) -> list[Result]:
        ranked = [r.model_copy(update={"rank": None}) for r in results]
        categories = sorted({r.category_id for r in ranked})
        for category in categories:
            finished = sorted(
                (
                    r
                    for r in ranked
                    if r.category_id == category
                    and r.eligible
                    and r.status == CS.FINISHED
                    and r.elapsed is not None
                ),
                key=lambda r: (-r.controls, r.elapsed, r.start_number, r.participant_id),
            )
            previous: tuple[int, int | None] | None = None
            rank = 0
            for position, result in enumerate(finished, 1):
                key = (result.controls, result.elapsed)
                if key != previous:
                    rank = position
                result.rank = rank
                previous = key
        return sorted(
            ranked,
            key=lambda r: (
                r.category_id,
                r.rank is None,
                r.rank or 0,
                -r.controls,
                r.start_number,
                r.participant_id,
            ),
        )


def interpret(
    event: Event,
    entries: list[Entry],
    categories: list[Category],
    stations: dict[int, tuple[Role, bool]],
    punches: list[Punch],
    exclusions: dict[int, str],
) -> Calculation:
    active = {e.uid: e for e in entries if e.active and e.uid}
    category_active = {c.id: c.active for c in categories}
    results = {
        e.id: Result(
            participant_id=e.id,
            category_id=e.category_id,
            start_number=e.start_number,
            start=unix(e.start_time or event.default_start_at)
            if event.timing_mode == Timing.PREDEFINED_START
            else None,
            eligible=e.active and category_active.get(e.category_id, False),
        )
        for e in entries
    }
    counted: dict[int, set[int]] = {e.id: set() for e in entries}
    window_start, window_end = unix(event.competition_start_at), unix(event.competition_end_at)
    interpretations: list[Interpretation] = []
    for punch in sorted(punches, key=lambda p: (p.station_timestamp, p.id or 0)):
        assert punch.id is not None
        entry = active.get(punch.uid)
        station = stations.get(punch.station_id)
        role = station[0] if station else None
        reason = ""
        time = punch.station_timestamp
        if punch.duplicate:
            status = IS.SOURCE_DUPLICATE
        elif punch.id in exclusions:
            status, reason = IS.MANUALLY_EXCLUDED, exclusions[punch.id]
        elif (
            not event.minimum_unix_timestamp <= time <= 4294967295
            or abs(time - punch.received_at_pc.timestamp()) > event.maximum_receive_skew_seconds
        ):
            status = IS.INVALID_TIMESTAMP
        elif (window_start is not None and time < window_start) or (
            window_end is not None and time > window_end
        ):
            status = IS.OUTSIDE_EVENT_WINDOW
        elif entry is None:
            status = IS.UNKNOWN_UID
        elif station is None:
            status = IS.UNKNOWN_STATION
        elif not station[1]:
            status = IS.DISABLED_STATION
        else:
            result = results[entry.id]
            start_valid = (
                result.start is not None
                and (window_start is None or result.start >= window_start)
                and (window_end is None or result.start <= window_end)
            )
            if role == Role.START and event.timing_mode == Timing.PUNCH_START_FINISH:
                if result.start is None:
                    result.start = time
                    result.status = CS.RUNNING
                    status = IS.VALID_START
                else:
                    status = IS.REPEAT_START
            elif not start_valid or result.start is None or time < result.start:
                status = IS.INVALID_FOR_TIMING
            elif role == Role.START:
                status = IS.REPEAT_START
                reason = "Predefined start remains authoritative"
                if result.status == CS.REGISTERED:
                    result.status = CS.RUNNING
            elif role == Role.FINISH:
                if result.finish is None:
                    result.finish = time
                    result.elapsed = time - result.start
                    result.status = CS.FINISHED
                    status = IS.VALID_FINISH
                else:
                    status = IS.REPEAT_FINISH
            elif result.finish is not None and time > result.finish:
                status = IS.INVALID_FOR_TIMING
            elif punch.station_id in counted[entry.id]:
                status = IS.REPEAT_CONTROL
            else:
                counted[entry.id].add(punch.station_id)
                result.controls += 1
                if result.status == CS.REGISTERED:
                    result.status = CS.RUNNING
                status = IS.VALID_CONTROL
        interpretations.append(
            Interpretation(
                punch_id=punch.id,
                participant_id=entry.id if entry else None,
                status=status,
                role=role,
                reason=reason,
            )
        )
    for entry in entries:
        if entry.manual_status is not None:
            results[entry.id].status = entry.manual_status
    return Calculation(
        interpretations=interpretations,
        results=DistinctControlsThenTime().calculate(list(results.values())),
        counts=dict(Counter(i.status.value for i in interpretations)),
    )
