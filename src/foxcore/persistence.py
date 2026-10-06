"""Single-owner SQLite repository with explicit transactional migrations."""

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dedupe import duplicate_key
from .events import Punch

MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        "CREATE TABLE raw_events (id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, "
        "raw_bytes BLOB NOT NULL, raw_text TEXT NOT NULL, parse_status TEXT NOT NULL DEFAULT 'pending', "
        "event_type TEXT, error TEXT, source TEXT NOT NULL, replayed INTEGER NOT NULL, "
        "scope TEXT NOT NULL, original_raw_id INTEGER REFERENCES raw_events(id))",
        "CREATE TABLE punches (id INTEGER PRIMARY KEY, raw_event_id INTEGER NOT NULL UNIQUE "
        "REFERENCES raw_events(id), received_at TEXT NOT NULL, station_id INTEGER NOT NULL, "
        "station_timestamp INTEGER NOT NULL, sequence INTEGER NOT NULL, uid TEXT NOT NULL, "
        "callsign TEXT, rssi INTEGER, source TEXT NOT NULL, replayed INTEGER NOT NULL, "
        "scope TEXT NOT NULL, duplicate INTEGER NOT NULL, duplicate_of INTEGER REFERENCES punches(id))",
        "CREATE INDEX punch_identity ON punches "
        "(scope, source, station_id, sequence, uid, station_timestamp)",
        "CREATE INDEX raw_chronological ON raw_events(received_at, id)",
        "CREATE TABLE diagnostics (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, "
        "kind TEXT NOT NULL, detail TEXT NOT NULL)",
        "CREATE TABLE participants (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
        "CREATE TABLE participant_uids (uid TEXT PRIMARY KEY, participant_id INTEGER NOT NULL "
        "REFERENCES participants(id))",
        "CREATE TABLE stations (station_id INTEGER PRIMARY KEY, name TEXT NOT NULL, callsign TEXT)",
    ),
    (
        "CREATE TABLE bridge_uid_maps (id INTEGER PRIMARY KEY, uid TEXT NOT NULL, "
        "card_number INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)))",
        "CREATE UNIQUE INDEX bridge_uid_active ON bridge_uid_maps(uid) WHERE active=1",
        "CREATE UNIQUE INDEX bridge_card_active ON bridge_uid_maps(card_number) WHERE active=1",
        "CREATE TABLE bridge_station_maps (id INTEGER PRIMARY KEY, station_id INTEGER NOT NULL, "
        "control_code INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('CONTROL','START','FINISH')), "
        "active INTEGER NOT NULL CHECK(active IN (0,1)))",
        "CREATE UNIQUE INDEX bridge_station_active ON bridge_station_maps(station_id) WHERE active=1",
        "CREATE TABLE bridge_offsets (target TEXT NOT NULL, control_code INTEGER NOT NULL, "
        "next_offset INTEGER NOT NULL, PRIMARY KEY(target,control_code))",
        "CREATE TABLE bridge_deliveries (id INTEGER PRIMARY KEY, punch_id INTEGER NOT NULL "
        "REFERENCES punches(id), target TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT, "
        "uid_mapping_id INTEGER REFERENCES bridge_uid_maps(id), station_mapping_id INTEGER "
        "REFERENCES bridge_station_maps(id), card_number INTEGER, control_code INTEGER, role TEXT, "
        "backup_offset INTEGER, encoded_frame BLOB, status TEXT NOT NULL, error TEXT, "
        "output_endpoint TEXT NOT NULL, automatic INTEGER NOT NULL CHECK(automatic IN (0,1)))",
        "CREATE UNIQUE INDEX bridge_once ON bridge_deliveries(target,punch_id) WHERE automatic=1",
        "CREATE INDEX bridge_status ON bridge_deliveries(target,status,id)",
        "CREATE TABLE bridge_output_state (target TEXT PRIMARY KEY, updated_at TEXT NOT NULL, "
        "endpoint TEXT NOT NULL, connected INTEGER NOT NULL, detail TEXT NOT NULL)",
    ),
)


@dataclass(frozen=True)
class RawEvent:
    id: int
    received_at: datetime
    raw_bytes: bytes
    source: str
    replayed: bool
    scope: str


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self._migrate()
        except BaseException:
            self.db.close()
            raise

    def _migrate(self) -> None:
        # BEGIN IMMEDIATE also serializes simultaneous first-open migrations.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'")
            if exists.fetchone() is None:
                self.db.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
            versions = [
                r[0]
                for r in self.db.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
            if versions != list(range(1, len(versions) + 1)) or len(versions) > len(MIGRATIONS):
                raise ValueError("Unsupported or noncontiguous schema version")
            for version, statements in enumerate(MIGRATIONS, 1):
                if version > len(versions):
                    for statement in statements:
                        self.db.execute(statement)
                    self.db.execute("INSERT INTO schema_migrations VALUES (?)", (version,))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    @property
    def version(self) -> int:
        return int(self.db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])

    def close(self) -> None:
        self.db.close()

    def get_punch(self, punch_id: int) -> Punch:
        """Canonical persisted punch for explicit downstream operations."""
        row = self.db.execute("SELECT * FROM punches WHERE id=?", (punch_id,)).fetchone()
        if row is None:
            raise ValueError(f"Punch {punch_id} does not exist")
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

    def insert_raw(
        self,
        raw: bytes,
        received: datetime,
        source: str,
        replayed: bool = False,
        scope: str = "live",
        original_raw_id: int | None = None,
    ) -> int:
        if received.tzinfo is None:
            raise ValueError("Receive time must be timezone aware")
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO raw_events(received_at,raw_bytes,raw_text,source,replayed,scope,"
                "original_raw_id) VALUES (?,?,?,?,?,?,?)",
                (
                    received.astimezone(UTC).isoformat(),
                    raw,
                    raw.decode("utf-8", errors="replace"),
                    source,
                    replayed,
                    scope,
                    original_raw_id,
                ),
            )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def finish(
        self, raw_id: int, status: str, kind: str, error: str | None, punch: Punch | None
    ) -> Punch | None:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if punch is not None:
                row = self.db.execute(
                    "SELECT id FROM punches WHERE scope=? AND source=? AND station_id=? "
                    "AND sequence=? AND uid=? AND station_timestamp=? AND duplicate=0 ORDER BY id LIMIT 1",
                    duplicate_key(punch),
                ).fetchone()
                original = int(row[0]) if row else None
                cursor = self.db.execute(
                    "INSERT INTO punches(raw_event_id,received_at,station_id,station_timestamp,"
                    "sequence,uid,callsign,rssi,source,replayed,scope,duplicate,duplicate_of) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        raw_id,
                        punch.received_at_pc.isoformat(),
                        punch.station_id,
                        punch.station_timestamp,
                        punch.sequence,
                        punch.uid,
                        punch.callsign,
                        punch.rssi,
                        punch.source,
                        punch.replayed,
                        punch.scope,
                        original is not None,
                        original,
                    ),
                )
                punch = replace(
                    punch,
                    id=cursor.lastrowid,
                    duplicate=original is not None,
                    duplicate_of=original,
                )
            self.db.execute(
                "UPDATE raw_events SET parse_status=?,event_type=?,error=? WHERE id=?",
                (status, kind, error, raw_id),
            )
        return punch

    def raw_events(self, pending: bool = False, live_only: bool = False) -> list[RawEvent]:
        conditions = []
        if pending:
            conditions.append("parse_status='pending'")
        if live_only:
            conditions.append("replayed=0")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return [
            RawEvent(
                r["id"],
                datetime.fromisoformat(r["received_at"]),
                r["raw_bytes"],
                r["source"],
                bool(r["replayed"]),
                r["scope"],
            )
            for r in self.db.execute(
                "SELECT * FROM raw_events" + where + " ORDER BY received_at,id"
            )
        ]

    def diagnostic(self, kind: str, detail: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO diagnostics(created_at,kind,detail) VALUES (?,?,?)",
                (datetime.now(UTC).isoformat(), kind, detail),
            )

    def stats(self) -> dict[str, Any]:
        return {
            "schema_version": self.version,
            "raw_events": self.db.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0],
            "punches": self.db.execute("SELECT COUNT(*) FROM punches").fetchone()[0],
            "duplicates": self.db.execute(
                "SELECT COUNT(*) FROM punches WHERE duplicate=1"
            ).fetchone()[0],
            "pending": self.db.execute(
                "SELECT COUNT(*) FROM raw_events WHERE parse_status='pending'"
            ).fetchone()[0],
            "last_connection": self.db.execute(
                "SELECT detail FROM diagnostics WHERE kind='connection' ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            if self.db.execute(
                "SELECT 1 FROM diagnostics WHERE kind='connection' LIMIT 1"
            ).fetchone()
            else None,
        }
