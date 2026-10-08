"""Owner-loop persistence and adjudication of independent tag/manual evidence."""

import json
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from .models import Calculation, Entry, Model, Role, instant, unix
from .persistence import timestamp
from .readout import TagReadout, parse_readout
from .reconciliation import Evidence, Resolution, fingerprint, observation, resolve, time_validity
from .scoring import DistinctControlsThenTime, interpret

if TYPE_CHECKING:
    from .service import LiveService


class DecisionInput(Model):
    participant_id: int = Field(ge=1)
    station_id: int = Field(ge=-1, le=65535)
    action: str
    source_type: str | None = None
    source_id: int | None = None
    timestamp: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    operator: str = Field(default="", max_length=100)


class ReadoutInput(Model):
    payload: str = Field(max_length=1_048_576)


class EvidenceService:
    def __init__(self, live: "LiveService") -> None:
        self.live = live
        self.repo = live.repo
        self.db = live.repo.db

    def import_raw(
        self,
        event_id: int,
        raw: bytes,
        provider: str = "import",
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        self.live.mutable(event_id)
        if len(raw) > 1_048_576:
            raise ValueError("Readout exceeds 1 MiB")
        received = received_at.isoformat() if received_at else timestamp()
        # Raw capture commits independently of parsing and derived processing.
        with self.db:
            session = self.live._insert(
                "tag_readout_sessions",
                {
                    "event_id": event_id,
                    "received_at": received,
                    "provider": provider,
                    "raw_payload": raw,
                    "status": "PENDING",
                },
            )
        readout = parse_readout(raw, provider, datetime.fromisoformat(received))
        self._finalize(session, readout)
        self.live.recalculate(event_id)
        self.live.publish(
            "tag_readout_completed",
            event_id,
            {"session_id": session, "uid": readout.uid, "status": readout.status},
        )
        return self.session(session)

    def import_readout(self, event_id: int, readout: TagReadout) -> dict[str, Any]:
        return self.import_raw(event_id, readout.raw_payload, readout.provider, readout.received_at)

    def _finalize(self, session: int, readout: TagReadout) -> None:
        with self.db:
            for item in readout.records:
                self.live._insert(
                    "tag_readout_records",
                    {
                        "session_id": session,
                        "file_id": item.file_id,
                        "raw_value": item.raw_value,
                        "raw_bytes": item.raw_bytes,
                        "station_timestamp": item.station_timestamp,
                        "tag_event_id": item.event_id,
                        "synchronized": item.time_synchronized,
                        "parse_status": item.parse_status,
                        "error": item.error,
                    },
                )
            self.db.execute(
                "UPDATE tag_readout_sessions SET uid=?,reader=?,status=?,errors=? WHERE id=?",
                (readout.uid, readout.reader, readout.status, json.dumps(readout.errors), session),
            )

    def recover_pending(self) -> None:
        for row in self.db.execute(
            "SELECT * FROM tag_readout_sessions WHERE status='PENDING' ORDER BY id"
        ).fetchall():
            self._finalize(
                row["id"],
                parse_readout(
                    bytes(row["raw_payload"]),
                    row["provider"],
                    datetime.fromisoformat(row["received_at"]),
                ),
            )

    def sessions(self, event_id: int, limit: int = 50) -> list[dict[str, Any]]:
        # Desk snapshots are bounded metadata, not repeated raw payload/record queries.
        return [
            dict(r) | {"errors": json.loads(r["errors"])}
            for r in self.db.execute(
                "SELECT s.id,s.event_id,s.received_at,s.provider,s.uid,s.reader,s.status,s.errors,e.id AS participant_id "
                "FROM tag_readout_sessions s LEFT JOIN live_entries e ON e.event_id=s.event_id AND e.uid=s.uid AND e.active=1 "
                "WHERE s.event_id=? ORDER BY s.id DESC LIMIT ?",
                (event_id, limit),
            )
        ]

    def session(self, session_id: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM tag_readout_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Readout does not exist")
        result = dict(row)
        result["raw_payload"] = bytes(result["raw_payload"]).decode("utf-8", errors="replace")
        result["errors"] = json.loads(result["errors"])
        result["records"] = []
        for r in self.db.execute(
            "SELECT * FROM tag_readout_records WHERE session_id=? ORDER BY id", (session_id,)
        ):
            item = dict(r)
            item["raw_bytes"] = (
                bytes(item["raw_bytes"]).hex().upper() if item["raw_bytes"] is not None else None
            )
            result["records"].append(item)
        entry = next(
            (
                e
                for e in self.repo.entries(result["event_id"])
                if e.active and e.uid == result["uid"]
            ),
            None,
        )
        result["participant_id"] = entry.id if entry else None
        result["summary"] = self.summary(result["event_id"], result["uid"]) if result["uid"] else {}
        return result

    def resolutions(self, event_id: int, participant_id: int | None = None) -> list[Resolution]:
        query = "SELECT payload FROM live_resolutions WHERE event_id=?"
        args: tuple[Any, ...] = (event_id,)
        if participant_id is not None:
            query += " AND participant_id=?"
            args += (participant_id,)
        return [
            Resolution.model_validate_json(r[0])
            for r in self.db.execute(query + " ORDER BY uid,station_id", args)
        ]

    def reviews(self, event_id: int, include_resolved: bool = False) -> list[dict[str, Any]]:
        return [
            dict(r) | {"resolution": json.loads(r["payload"])}
            for r in self.db.execute(
                "SELECT * FROM live_review_cases WHERE event_id=?"
                + ("" if include_resolved else " AND status='OPEN'")
                + " ORDER BY id",
                (event_id,),
            )
        ]

    def decisions(self, event_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM live_evidence_decisions WHERE event_id=? ORDER BY id", (event_id,)
            )
        ]

    def summary(self, event_id: int, uid: str | None) -> dict[str, Any]:
        rows = [r for r in self.resolutions(event_id) if r.uid == uid]
        return {
            "live_controls": sum(
                r.role == Role.CONTROL
                and any(e.source_type == "LIVE" and e.validity == "VALID" for e in r.evidence)
                for r in rows
            ),
            "tag_controls": sum(
                r.role == Role.CONTROL
                and any(
                    e.source_type == "TAG_READOUT" and e.validity == "VALID" for e in r.evidence
                )
                for r in rows
            ),
            "recovered": sum(
                r.role == Role.CONTROL
                and r.status == "TAG_ONLY_RECOVERED"
                and any(s["status"] == "VALID_CONTROL" for s in r.scored)
                for r in rows
            ),
            "matches": sum(r.status in {"MATCHED", "TAG_CONFIRMED_LIVE"} for r in rows),
            "open_reviews": sum(r.needs_review for r in rows),
        }

    def calculate(self, event_id: int, entries: list[Entry], uid: str | None = None) -> Calculation:
        event = self.repo.event(event_id)
        stations = {s.station_id: s for s in self.repo.stations(event_id)}
        # Stable private scoring identity permits manual rulings for an entry without a tag.
        scoring_entries = [e.model_copy(update={"uid": e.uid or f"entry:{e.id}"}) for e in entries]
        active = {e.uid: e for e in scoring_entries if e.active}
        groups: dict[tuple[str, int], list[Evidence]] = defaultdict(list)
        exclusions = self.repo.exclusions(event_id)
        for punch in self.repo.punches(event_id, uid):
            assert punch.id is not None
            validity = (
                "SOURCE_DUPLICATE"
                if punch.duplicate
                else "MANUALLY_EXCLUDED"
                if punch.id in exclusions
                else time_validity(event, punch.station_timestamp, punch.received_at_pc)
            )
            groups[(punch.uid, punch.station_id)].append(
                Evidence(
                    source_type="LIVE",
                    source_id=punch.id,
                    station_timestamp=punch.station_timestamp,
                    validity=validity,
                )
            )
        params: tuple[Any, ...] = (event_id,) if uid is None else (event_id, uid)
        filter_uid = "" if uid is None else " AND s.uid=?"
        records = self.db.execute(
            "SELECT r.*,s.uid,s.status AS session_status FROM tag_readout_records r JOIN tag_readout_sessions s ON s.id=r.session_id WHERE s.event_id=? AND s.uid IS NOT NULL"
            + filter_uid
            + " ORDER BY r.id",
            params,
        ).fetchall()
        latest: dict[tuple[str, int], Any] = {}
        for row in records:
            latest[(row["uid"], row["file_id"] if row["file_id"] is not None else -1)] = row
        for key, row in latest.items():
            validity = row["parse_status"]
            if row["session_status"] == "FAILED":
                validity = "FAILED_READOUT"
            elif validity == "VALID":
                validity = (
                    "EVENT_ID_UNKNOWN"
                    if event.tag_event_id is None
                    else "WRONG_EVENT"
                    if row["tag_event_id"] != event.tag_event_id
                    else "UNSYNC_TAG_TIME"
                    if not row["synchronized"]
                    else time_validity(event, row["station_timestamp"])
                )
            groups[key].append(
                Evidence(
                    source_type="TAG_READOUT",
                    source_id=row["id"],
                    station_timestamp=row["station_timestamp"],
                    validity=validity,
                    session_id=row["session_id"],
                    tag_event_id=row["tag_event_id"],
                    time_synchronized=bool(row["synchronized"])
                    if row["synchronized"] is not None
                    else None,
                )
            )
        sessions = self.db.execute(
            "SELECT s.uid,s.status,s.id FROM tag_readout_sessions s WHERE s.event_id=? AND s.uid IS NOT NULL"
            + filter_uid
            + " ORDER BY s.id",
            params,
        ).fetchall()
        session_state: dict[str, str] = {}
        for session in sessions:
            session_state[session["uid"]] = session["status"]
        for key_uid, status in session_state.items():
            if status != "COMPLETE":
                groups[(key_uid, -1)].append(
                    Evidence(
                        source_type="TAG_READOUT",
                        source_id=0,
                        station_timestamp=None,
                        validity="INCOMPLETE_READOUT",
                    )
                )
        all_decisions = self.decisions(event_id)
        decisions = {(d["participant_id"], d["station_id"]): d for d in all_decisions}
        for scoring_entry in scoring_entries:
            for participant, station in decisions:
                if participant == scoring_entry.id:
                    groups.setdefault((str(scoring_entry.uid), station), [])
        observations = []
        resolved: list[Resolution] = []
        for (key_uid, station_id), items in sorted(groups.items()):
            entry = active.get(key_uid)
            station = stations.get(station_id)
            file = latest.get((key_uid, station_id))
            # Identity excludes snapshot/record IDs for identical repeated bytes.
            signature = fingerprint(
                {
                    "uid": key_uid,
                    "station": station_id,
                    "entry": entry.id if entry else None,
                    "event": event.model_dump(
                        exclude={"updated_at", "created_at", "cursor", "state"}
                    ),
                    "station_config": station.model_dump() if station else None,
                    "live": [e.model_dump() for e in items if e.source_type == "LIVE"],
                    "tag": [file["raw_value"], file["session_status"]] if file else None,
                    "session_status": session_state.get(key_uid) if station_id == -1 else None,
                }
            )
            resolution = resolve(
                key_uid,
                station_id,
                entry.id if entry else None,
                station.role if station else None,
                station.enabled if station else False,
                items,
                signature,
            )
            decision = decisions.get((entry.id, station_id)) if entry else None
            if decision is not None and decision["action"] != "AUTO":
                if decision["fingerprint"] == signature:
                    self._apply(resolution, decision)
                else:
                    resolution.issues.append("NEW_EVIDENCE")
                    resolution.needs_review = True
            for accepted in resolution.accepted:
                observations.append(observation(accepted, resolution))
            resolved.append(resolution)
        calculation = interpret(
            event,
            scoring_entries,
            self.repo.categories(event_id),
            {s.station_id: (s.role, s.enabled) for s in stations.values()},
            observations,
            {},
        )
        indexed = {i.punch_id: i for i in calculation.interpretations}
        for resolution in resolved:
            for accepted in resolution.accepted:
                item = indexed[observation(accepted, resolution).id]
                resolution.scored.append(
                    {
                        "source_type": accepted.source_type,
                        "source_id": accepted.source_id,
                        "status": item.status.value,
                    }
                )
            self._cache(event_id, resolution)
        for result in calculation.results:
            rows = [r for r in resolved if r.participant_id == result.participant_id]
            counted = {
                r.station_id for r in rows if any(s["status"] == "VALID_CONTROL" for s in r.scored)
            }
            for r in rows:
                if r.presence_only and r.station_id not in counted:
                    counted.add(r.station_id)
                    result.controls += 1
            result.open_reviews = sum(r.needs_review for r in rows)
            result.manual_decision = any(r.decision_id is not None for r in rows)
            result.recovered_controls = sum(
                r.status == "TAG_ONLY_RECOVERED" and r.station_id in counted for r in rows
            )
            result.completeness = (
                "REVIEW_REQUIRED"
                if result.open_reviews
                else "COMPLETE"
                if session_state.get(
                    next((str(e.uid) for e in scoring_entries if e.id == result.participant_id), "")
                )
                == "COMPLETE"
                else "PROVISIONAL"
            )
            result.provenance = (
                "MANUAL"
                if result.manual_decision
                else "RECOVERED"
                if any(r.status == "TAG_ONLY_RECOVERED" for r in rows)
                else "CONFIRMED"
                if any(r.status in {"MATCHED", "TAG_CONFIRMED_LIVE"} for r in rows)
                else "LIVE"
            )
        calculation.results = DistinctControlsThenTime().calculate(calculation.results)
        return calculation

    def _cache(self, event_id: int, resolution: Resolution) -> None:
        values = (
            event_id,
            resolution.uid,
            resolution.station_id,
            resolution.participant_id,
            resolution.model_dump_json(),
        )
        self.db.execute(
            "INSERT INTO live_resolutions VALUES (?,?,?,?,?) ON CONFLICT(event_id,uid,station_id) DO UPDATE SET participant_id=excluded.participant_id,payload=excluded.payload",
            values,
        )
        previous = self.db.execute(
            "SELECT status FROM live_review_cases WHERE event_id=? AND uid=? AND station_id=?",
            values[:3],
        ).fetchone()
        if resolution.needs_review or previous is not None or resolution.decision_id is not None:
            status = "OPEN" if resolution.needs_review else "RESOLVED"
            self.db.execute(
                "INSERT INTO live_review_cases(event_id,uid,station_id,participant_id,payload,status,decision_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id,uid,station_id) DO UPDATE SET participant_id=excluded.participant_id,payload=excluded.payload,status=excluded.status,decision_id=excluded.decision_id",
                values + (status, resolution.decision_id),
            )

    def _apply(self, resolution: Resolution, decision: dict[str, Any]) -> None:
        action = decision["action"]
        resolution.decision_id = decision["id"]
        resolution.status = "EXCLUDED" if action == "EXCLUDE" else "MANUAL"
        resolution.needs_review = False
        resolution.accepted = []
        if action == "SELECT":
            resolution.accepted = [
                e
                for e in resolution.evidence
                if e.source_type == decision["source_type"]
                and (e.source_id == decision["source_id"] or e.source_type == "TAG_READOUT")
                and e.validity == "VALID"
            ]
        elif action == "MANUAL":
            evidence = Evidence(
                source_type="MANUAL",
                source_id=decision["id"],
                station_timestamp=decision["station_timestamp"],
                validity="VALID",
            )
            resolution.evidence.append(evidence)
            resolution.accepted = [evidence]
        elif action == "PRESENCE":
            resolution.presence_only = True

    def decide(self, event_id: int, data: DecisionInput) -> dict[str, Any]:
        event = self.live.mutable(event_id)
        entry = next(
            (e for e in self.repo.entries(event_id) if e.id == data.participant_id and e.active),
            None,
        )
        if entry is None:
            raise ValueError("Participant does not exist in this event")
        if not data.reason.strip():
            raise ValueError("Decision requires a reason")
        if data.action not in {"SELECT", "EXCLUDE", "PRESENCE", "MANUAL", "AUTO"}:
            raise ValueError("Unsupported adjudication action")
        station = next(
            (s for s in self.repo.stations(event_id) if s.station_id == data.station_id), None
        )
        if data.action in {"MANUAL", "PRESENCE", "SELECT"} and (
            station is None or not station.enabled
        ):
            raise ValueError("Station is not enabled for this event")
        if data.action == "PRESENCE" and station is not None and station.role != Role.CONTROL:
            raise ValueError("Presence-only decisions are allowed for controls only")
        # Build a new station's fingerprint before a manual-only decision, without source writes.
        uid = entry.uid or f"entry:{entry.id}"
        current = next(
            (
                r
                for r in self.resolutions(event_id)
                if r.uid == uid and r.station_id == data.station_id
            ),
            None,
        )
        if current is None:
            signature = fingerprint(
                {
                    "uid": uid,
                    "station": data.station_id,
                    "entry": entry.id,
                    "event": event.model_dump(
                        exclude={"updated_at", "created_at", "cursor", "state"}
                    ),
                    "station_config": station.model_dump() if station else None,
                    "live": [],
                    "tag": None,
                    "session_status": None,
                }
            )
        else:
            signature = current.fingerprint
        stamp = unix(instant(data.timestamp, event.timezone)) if data.timestamp else None
        if data.action == "MANUAL" and time_validity(event, stamp) != "VALID":
            raise ValueError("Manual time fails event timestamp validation")
        if data.action == "SELECT":
            selected = (
                next(
                    (
                        e
                        for e in current.evidence
                        if e.source_type == data.source_type
                        and e.source_id == data.source_id
                        and e.validity == "VALID"
                    ),
                    None,
                )
                if current
                else None
            )
            if selected is None:
                raise ValueError("Select valid current evidence or enter an explicit manual time")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            decision_id = self.live._insert(
                "live_evidence_decisions",
                {
                    "event_id": event_id,
                    "participant_id": entry.id,
                    "station_id": data.station_id,
                    "action": data.action,
                    "source_type": data.source_type,
                    "source_id": data.source_id,
                    "station_timestamp": stamp,
                    "fingerprint": signature,
                    "reason": data.reason.strip(),
                    "operator": data.operator.strip() or self.live.operator,
                    "created_at": timestamp(),
                },
            )
            self.live._audit(
                event_id,
                "adjudication",
                str(decision_id),
                current.model_dump() if current else None,
                data.model_dump() | {"decision_id": decision_id},
                data.reason.strip(),
            )
            self.live._calculate(event_id)
        self.live.notify(event_id, "reconciliation_updated", {"decision_id": decision_id})
        return next(d for d in self.decisions(event_id) if d["id"] == decision_id)

    def publish_review_changes(self, event_id: int, before: dict[int, str]) -> None:
        for review in self.reviews(event_id, True):
            if before.get(review["id"]) != review["status"]:
                self.live.publish(
                    "review_case_created" if review["status"] == "OPEN" else "review_case_resolved",
                    event_id,
                    {"review_id": review["id"]},
                )
