"""Bulk reads of source facts and event-scoped FoxLive configuration/cache writes."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from foxcore.events import Punch
from foxcore.persistence import Store

from .models import Category, Club, Entry, Event, MasterCategory, Result, Runner, Station


def source_punch(row: sqlite3.Row) -> Punch:
    return Punch(
        raw_event_id=row["raw_event_id"],
        received_at_pc=datetime.fromisoformat(row["received_at"]),
        station_id=row["station_id"],
        station_timestamp=row["station_timestamp"],
        sequence=row["sequence"],
        uid=row["uid"],
        callsign=row["callsign"],
        rssi=row["rssi"],
        source=row["source"],
        replayed=bool(row["replayed"]),
        scope=row["scope"],
        id=row["id"],
        duplicate=bool(row["duplicate"]),
        duplicate_of=row["duplicate_of"],
    )


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class LiveRepository:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.db = store.db

    def events(self) -> list[Event]:
        return [
            Event.model_validate(dict(r))
            for r in self.db.execute("SELECT * FROM live_events ORDER BY id DESC")
        ]

    def event(self, event_id: int) -> Event:
        row = self.db.execute("SELECT * FROM live_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError(f"Event {event_id} does not exist")
        return Event.model_validate(dict(row))

    def running(self) -> Event | None:
        row = self.db.execute("SELECT id FROM live_events WHERE state='RUNNING'").fetchone()
        return self.event(row[0]) if row else None

    def categories(self, event_id: int) -> list[Category]:
        return [
            Category.model_validate(dict(r))
            for r in self.db.execute(
                "SELECT * FROM live_event_categories WHERE event_id=? ORDER BY display_order,code,category_id",
                (event_id,),
            )
        ]

    def entries(self, event_id: int) -> list[Entry]:
        return [
            Entry.model_validate(dict(r))
            for r in self.db.execute(
                "SELECT * FROM live_entries WHERE event_id=? ORDER BY start_number,id",
                (event_id,),
            )
        ]

    def clubs(self) -> list[Club]:
        return [
            Club.model_validate(dict(r))
            for r in self.db.execute("SELECT * FROM live_clubs ORDER BY code,display_name,id")
        ]

    def master_categories(self) -> list[MasterCategory]:
        return [
            MasterCategory.model_validate(dict(r))
            for r in self.db.execute("SELECT * FROM live_category_master ORDER BY code,id")
        ]

    def runners(self, search: str = "", limit: int | None = None) -> list[Runner]:
        rows = self.db.execute(
            "SELECT r.*,COALESCE(c.display_name,'') AS club,COALESCE(c.code,'') AS club_code "
            "FROM live_runners r LEFT JOIN live_clubs c ON c.id=r.club_id "
            "ORDER BY r.last_name,r.first_name,r.birth_year,r.id"
        )
        terms = search.casefold().split()
        result = []
        for row in rows:
            runner = Runner.model_validate(dict(row))
            label = f"{runner.first_name} {runner.last_name} {runner.birth_year or ''} {runner.club} {runner.club_code}".casefold()
            if all(t in label for t in terms):
                result.append(runner)
                if limit is not None and len(result) >= limit:
                    break
        return result

    def runner(self, runner_id: int) -> Runner:
        row = self.db.execute(
            "SELECT r.*,COALESCE(c.display_name,'') AS club,COALESCE(c.code,'') AS club_code "
            "FROM live_runners r LEFT JOIN live_clubs c ON c.id=r.club_id WHERE r.id=?",
            (runner_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Runner does not exist")
        return Runner.model_validate(dict(row))

    def master_audit(self) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.db.execute("SELECT * FROM live_master_audit ORDER BY id DESC")
        ]

    def stations(self, event_id: int) -> list[Station]:
        return [
            Station.model_validate(dict(r))
            for r in self.db.execute(
                "SELECT * FROM live_event_stations WHERE event_id=? ORDER BY display_order,station_id",
                (event_id,),
            )
        ]

    def punches(self, event_id: int, uid: str | None = None) -> list[Punch]:
        query = "SELECT p.* FROM punches p JOIN live_event_punches a ON a.punch_id=p.id WHERE a.event_id=?"
        params: tuple[Any, ...] = (event_id,)
        if uid is not None:
            query += " AND a.uid=?"
            params += (uid,)
        return [
            source_punch(r)
            for r in self.db.execute(query + " ORDER BY p.station_timestamp,p.id", params)
        ]

    def results(self, event_id: int) -> list[Result]:
        return [
            Result.model_validate_json(r[0])
            for r in self.db.execute(
                "SELECT payload FROM live_entry_results WHERE event_id=? ORDER BY participant_id",
                (event_id,),
            )
        ]

    def exclusions(self, event_id: int) -> dict[int, str]:
        return dict(
            self.db.execute(
                "SELECT punch_id,reason FROM live_manual_exclusions WHERE event_id=?", (event_id,)
            ).fetchall()
        )

    def audit(self, event_id: int) -> list[dict[str, Any]]:
        result = []
        for row in self.db.execute(
            "SELECT * FROM live_audit_events WHERE event_id=? ORDER BY id DESC", (event_id,)
        ):
            data = dict(row)
            before, after = data.pop("before_json"), data.pop("after_json")
            data["before"] = json.loads(before) if before else None
            data["after"] = json.loads(after) if after else None
            result.append(data)
        return result

    def recent(
        self, event_id: int, limit: int = 100, participant_id: int | None = None
    ) -> list[dict[str, Any]]:
        where = "a.event_id=?"
        params: tuple[Any, ...] = (event_id,)
        if participant_id is not None:
            where += " AND i.participant_id=?"
            params += (participant_id,)
        query = (
            "SELECT p.*,i.participant_id,i.status,i.role,i.reason,e.start_number,e.first_name,e.last_name,"
            "c.code AS category,s.display_name AS station_name FROM live_event_punches a "
            "JOIN punches p ON p.id=a.punch_id LEFT JOIN live_entry_interpretations i "
            "ON i.event_id=a.event_id AND i.punch_id=a.punch_id LEFT JOIN live_entries e "
            "ON e.id=i.participant_id LEFT JOIN live_event_categories c ON c.category_id=e.category_id AND c.event_id=e.event_id "
            "LEFT JOIN live_event_stations s ON s.event_id=a.event_id AND s.station_id=p.station_id "
            f"WHERE {where} ORDER BY p.station_timestamp DESC,p.id DESC LIMIT ?"
        )
        zone = ZoneInfo(self.event(event_id).timezone)
        result = []
        for row in self.db.execute(query, params + (limit,)):
            data = dict(row)
            data["local_time"] = (
                datetime.fromtimestamp(data["station_timestamp"], UTC).astimezone(zone).isoformat()
            )
            result.append(data)
        return result
