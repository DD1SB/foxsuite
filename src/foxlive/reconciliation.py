"""Deterministic evidence rules, separate from acquisition, persistence and sporting ranking."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field

from .models import Event, Model, Role, unix


class Evidence(Model):
    source_type: str
    source_id: int
    station_timestamp: int | None
    validity: str
    session_id: int | None = None
    tag_event_id: int | None = None
    time_synchronized: bool | None = None
    received_at_pc: str | None = None


class Resolution(Model):
    uid: str
    station_id: int
    participant_id: int | None
    role: Role | None
    status: str
    issues: list[str] = Field(default_factory=list)
    needs_review: bool = False
    fingerprint: str
    evidence: list[Evidence]
    accepted: list[Evidence] = Field(default_factory=list)
    scored: list[dict[str, int | str]] = Field(default_factory=list)
    decision_id: int | None = None
    presence_only: bool = False


@dataclass(frozen=True)
class Observation:
    """Ephemeral competition observation, NOT a FoxCore Punch or raw serial event."""

    id: int
    uid: str
    station_id: int
    station_timestamp: int
    received_at_pc: datetime | None
    duplicate: bool = False


def time_validity(event: Event, stamp: int | None, received: datetime | None = None) -> str:
    if stamp is None or not event.minimum_unix_timestamp <= stamp <= 4294967295:
        return "INVALID_TIMESTAMP"
    if (
        received is not None
        and abs(stamp - received.timestamp()) > event.maximum_receive_skew_seconds
    ):
        return "INVALID_TIMESTAMP"
    start, end = unix(event.competition_start_at), unix(event.competition_end_at)
    if (start is not None and stamp < start) or (end is not None and stamp > end):
        return "OUTSIDE_EVENT_WINDOW"
    return "VALID"


def fingerprint(values: object) -> str:
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def resolve(
    uid: str,
    station_id: int,
    participant_id: int | None,
    role: Role | None,
    enabled: bool,
    evidence: list[Evidence],
    source_fingerprint: str,
) -> Resolution:
    tag = next((e for e in evidence if e.source_type == "TAG_READOUT"), None)
    if tag is not None and tag.validity == "UNSYNC_TAG_TIME":
        evidence = [
            e.model_copy(update={"validity": "UNTRUSTED_LIVE_TIME"})
            if e.source_type == "LIVE"
            and e.validity == "VALID"
            and e.station_timestamp == tag.station_timestamp
            else e
            for e in evidence
        ]
    live = [e for e in evidence if e.source_type == "LIVE" and e.validity == "VALID"]
    issues = sorted(
        {
            e.validity
            for e in evidence
            if e.source_type == "TAG_READOUT" and e.validity not in {"VALID", "EMPTY"}
        }
    )
    result = Resolution(
        uid=uid,
        station_id=station_id,
        participant_id=participant_id,
        role=role,
        fingerprint=source_fingerprint,
        evidence=evidence,
        accepted=live,
        status="LIVE_ONLY",
        issues=issues,
    )
    if participant_id is None:
        result.status = "UNKNOWN_UID"
        result.issues.append("UNKNOWN_UID")
        result.accepted = []
    elif role is None or not enabled:
        result.status = "UNKNOWN_STATION" if role is None else "DISABLED_STATION"
        result.issues.append(result.status)
        result.accepted = []
    elif tag is not None and tag.validity == "VALID":
        excluded = any(
            e.source_type == "LIVE"
            and e.validity == "MANUALLY_EXCLUDED"
            and e.station_timestamp == tag.station_timestamp
            for e in evidence
        )
        matches = [e for e in live if e.station_timestamp == tag.station_timestamp]
        if matches:
            result.status = "MATCHED" if len(live) == 1 else "TAG_CONFIRMED_LIVE"
        elif not live:
            result.status = "TAG_ONLY_RECOVERED"
            result.accepted = [tag]
        else:
            result.status = "CONFLICT"
            result.issues.append("CONFLICT")
            if role in {Role.START, Role.FINISH}:
                result.accepted = []
        if excluded:
            result.issues.append("EXCLUDED_LIVE_MATCH")
            result.accepted = live
    elif not live:
        result.status = tag.validity if tag else "EXCLUDED"
    # LIVE invalid/duplicates alone retain M3 behavior without generating a new review queue.
    result.needs_review = bool(result.issues) and tag is not None
    return result


def observation(evidence: Evidence, resolution: Resolution) -> Observation:
    assert evidence.station_timestamp is not None
    role_order = {Role.START: 0, Role.CONTROL: 1, Role.BEACON: 1, Role.FINISH: 2}.get(
        resolution.role or Role.CONTROL, 1
    )
    # Private, non-persisted sort keys: whole-second offline ties process START,
    # CONTROL/BEACON, FINISH in that order. Wide bands cannot collide with SQLite IDs;
    # all-live ties still use the original source-ID order as in M3.
    key = (
        evidence.source_id
        if evidence.source_type == "LIVE"
        else -(1 << 66)
        + role_order * (1 << 64)
        + 2 * evidence.source_id
        + (evidence.source_type == "TAG_READOUT")
    )
    return Observation(
        int(key),
        resolution.uid,
        resolution.station_id,
        evidence.station_timestamp,
        datetime.fromisoformat(evidence.received_at_pc) if evidence.received_at_pc else None,
    )
