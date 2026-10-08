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
    (
        "CREATE TABLE live_events (id INTEGER PRIMARY KEY, name TEXT NOT NULL, date TEXT NOT NULL, "
        "timezone TEXT NOT NULL, description TEXT NOT NULL, state TEXT NOT NULL "
        "CHECK(state IN ('DRAFT','RUNNING','CLOSED','ARCHIVED')), timing_mode TEXT NOT NULL "
        "CHECK(timing_mode IN ('PUNCH_START_FINISH','PREDEFINED_START')), competition_start_at TEXT, "
        "competition_end_at TEXT, default_start_at TEXT, minimum_unix_timestamp INTEGER NOT NULL, "
        "maximum_receive_skew_seconds INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE UNIQUE INDEX live_one_running ON live_events(state) WHERE state='RUNNING'",
        "CREATE TABLE live_categories (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL "
        "REFERENCES live_events(id), code TEXT NOT NULL, display_name TEXT NOT NULL, "
        "active INTEGER NOT NULL, display_order INTEGER NOT NULL, UNIQUE(event_id,code), "
        "UNIQUE(event_id,id))",
        "CREATE TABLE live_participants (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL "
        "REFERENCES live_events(id), start_number INTEGER NOT NULL, first_name TEXT NOT NULL, "
        "last_name TEXT NOT NULL, category_id INTEGER NOT NULL, uid TEXT, club TEXT NOT NULL, "
        "start_time TEXT, manual_status TEXT, active INTEGER NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, UNIQUE(event_id,start_number), UNIQUE(event_id,id), "
        "FOREIGN KEY(event_id,category_id) REFERENCES live_categories(event_id,id))",
        "CREATE UNIQUE INDEX live_active_uid ON live_participants(event_id,uid) "
        "WHERE active=1 AND uid IS NOT NULL",
        "CREATE INDEX live_participant_category ON live_participants(event_id,category_id)",
        "CREATE TABLE live_event_stations (event_id INTEGER NOT NULL REFERENCES live_events(id), "
        "station_id INTEGER NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL "
        "CHECK(role IN ('CONTROL','START','FINISH')), enabled INTEGER NOT NULL, "
        "display_order INTEGER NOT NULL, PRIMARY KEY(event_id,station_id))",
        "CREATE TABLE live_event_punches (event_id INTEGER NOT NULL REFERENCES live_events(id), "
        "punch_id INTEGER NOT NULL REFERENCES punches(id), uid TEXT NOT NULL, associated_at TEXT NOT NULL, "
        "origin TEXT NOT NULL, PRIMARY KEY(event_id,punch_id))",
        "CREATE INDEX live_event_uid ON live_event_punches(event_id,uid,punch_id)",
        "CREATE TABLE live_punch_interpretations (event_id INTEGER NOT NULL, punch_id INTEGER NOT NULL, "
        "participant_id INTEGER, status TEXT NOT NULL, role TEXT, reason TEXT NOT NULL, "
        "PRIMARY KEY(event_id,punch_id), FOREIGN KEY(event_id,punch_id) "
        "REFERENCES live_event_punches(event_id,punch_id), FOREIGN KEY(event_id,participant_id) "
        "REFERENCES live_participants(event_id,id))",
        "CREATE TABLE live_results (event_id INTEGER NOT NULL, participant_id INTEGER NOT NULL, "
        "payload TEXT NOT NULL, PRIMARY KEY(event_id,participant_id), "
        "FOREIGN KEY(event_id,participant_id) REFERENCES live_participants(event_id,id))",
        "CREATE TABLE live_manual_exclusions (event_id INTEGER NOT NULL, punch_id INTEGER NOT NULL, "
        "reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(event_id,punch_id), "
        "FOREIGN KEY(event_id,punch_id) REFERENCES live_event_punches(event_id,punch_id))",
        "CREATE TABLE live_audit_events (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL "
        "REFERENCES live_events(id), created_at TEXT NOT NULL, operator TEXT NOT NULL, action TEXT NOT NULL, "
        "entity TEXT NOT NULL, before_json TEXT, after_json TEXT, reason TEXT NOT NULL)",
        "CREATE INDEX live_audit_event ON live_audit_events(event_id,id)",
    ),
    (
        "CREATE TABLE live_clubs (id INTEGER PRIMARY KEY, code TEXT NOT NULL, display_name TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)))",
        "CREATE UNIQUE INDEX live_club_code ON live_clubs(code) WHERE code<>''",
        "CREATE TABLE live_runners (id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_year INTEGER, birth_date TEXT, club_id INTEGER REFERENCES live_clubs(id), active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE INDEX live_runner_name ON live_runners(last_name,first_name,birth_year)",
        "CREATE TABLE live_category_master (id INTEGER PRIMARY KEY, code TEXT NOT NULL, display_name_en TEXT NOT NULL, display_name_de TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), needs_review INTEGER NOT NULL DEFAULT 0 CHECK(needs_review IN (0,1)))",
        "CREATE UNIQUE INDEX live_master_category_code ON live_category_master(code) WHERE needs_review=0",
        "CREATE TABLE live_event_categories (event_id INTEGER NOT NULL REFERENCES live_events(id), category_id INTEGER NOT NULL REFERENCES live_category_master(id), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), display_order INTEGER NOT NULL, code TEXT NOT NULL, display_name_en TEXT NOT NULL, display_name_de TEXT NOT NULL, PRIMARY KEY(event_id,category_id))",
        "CREATE TABLE live_entries (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES live_events(id), runner_id INTEGER NOT NULL REFERENCES live_runners(id), start_number INTEGER NOT NULL, category_id INTEGER NOT NULL, uid TEXT, start_time TEXT, manual_status TEXT, active INTEGER NOT NULL CHECK(active IN (0,1)), checked_in INTEGER NOT NULL CHECK(checked_in IN (0,1)), first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_year INTEGER, birth_date TEXT, club TEXT NOT NULL, club_code TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(event_id,start_number), UNIQUE(event_id,id), FOREIGN KEY(event_id,category_id) REFERENCES live_event_categories(event_id,category_id))",
        "CREATE UNIQUE INDEX live_entry_uid ON live_entries(event_id,uid) WHERE active=1 AND uid IS NOT NULL",
        "CREATE UNIQUE INDEX live_entry_runner ON live_entries(event_id,runner_id) WHERE active=1",
        "CREATE INDEX live_entry_category ON live_entries(event_id,category_id)",
        "CREATE TABLE live_entry_interpretations (event_id INTEGER NOT NULL, punch_id INTEGER NOT NULL, participant_id INTEGER, status TEXT NOT NULL, role TEXT, reason TEXT NOT NULL, PRIMARY KEY(event_id,punch_id), FOREIGN KEY(event_id,punch_id) REFERENCES live_event_punches(event_id,punch_id), FOREIGN KEY(event_id,participant_id) REFERENCES live_entries(event_id,id))",
        "CREATE TABLE live_entry_results (event_id INTEGER NOT NULL, participant_id INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(event_id,participant_id), FOREIGN KEY(event_id,participant_id) REFERENCES live_entries(event_id,id))",
        "CREATE TABLE live_master_audit (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, operator TEXT NOT NULL, action TEXT NOT NULL, entity_id INTEGER NOT NULL, before_json TEXT, after_json TEXT)",
        "INSERT INTO live_clubs(code,display_name,active) SELECT '',club,1 FROM live_participants WHERE club<>'' GROUP BY club ORDER BY club",
        "INSERT INTO live_runners SELECT p.id,p.first_name,p.last_name,NULL,NULL,c.id,1,p.created_at,p.updated_at FROM live_participants p LEFT JOIN live_clubs c ON c.display_name=p.club",
        "INSERT INTO live_category_master SELECT id,code,display_name,display_name,active,1 FROM live_categories",
        "INSERT INTO live_event_categories SELECT event_id,id,active,display_order,code,display_name,display_name FROM live_categories",
        "INSERT INTO live_entries SELECT id,event_id,id,start_number,category_id,uid,start_time,manual_status,active,0,first_name,last_name,NULL,NULL,club,'',created_at,updated_at FROM live_participants",
        "INSERT INTO live_entry_interpretations SELECT * FROM live_punch_interpretations",
        "INSERT INTO live_entry_results SELECT * FROM live_results",
    ),
    (
        "ALTER TABLE live_events ADD COLUMN tag_event_id INTEGER CHECK(tag_event_id BETWEEN 0 AND 65535)",
        "CREATE TABLE tag_readout_sessions (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES live_events(id), received_at TEXT NOT NULL, provider TEXT NOT NULL, raw_payload BLOB NOT NULL, uid TEXT, reader TEXT, status TEXT NOT NULL, errors TEXT NOT NULL DEFAULT '[]')",
        "CREATE INDEX tag_session_event_uid ON tag_readout_sessions(event_id,uid,id)",
        "CREATE TABLE tag_readout_records (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES tag_readout_sessions(id), file_id INTEGER, raw_value TEXT NOT NULL, raw_bytes BLOB, station_timestamp INTEGER, tag_event_id INTEGER, synchronized INTEGER, parse_status TEXT NOT NULL, error TEXT NOT NULL)",
        "CREATE INDEX tag_record_session_file ON tag_readout_records(session_id,file_id,id)",
        "CREATE TABLE live_evidence_decisions (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, participant_id INTEGER NOT NULL, station_id INTEGER NOT NULL, action TEXT NOT NULL, source_type TEXT, source_id INTEGER, station_timestamp INTEGER, fingerprint TEXT NOT NULL, reason TEXT NOT NULL, operator TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(event_id,participant_id) REFERENCES live_entries(event_id,id))",
        "CREATE INDEX live_decision_station ON live_evidence_decisions(event_id,participant_id,station_id,id)",
        "CREATE TABLE live_resolutions (event_id INTEGER NOT NULL REFERENCES live_events(id), uid TEXT NOT NULL, station_id INTEGER NOT NULL, participant_id INTEGER, payload TEXT NOT NULL, PRIMARY KEY(event_id,uid,station_id), FOREIGN KEY(event_id,participant_id) REFERENCES live_entries(event_id,id))",
        "CREATE TABLE live_review_cases (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES live_events(id), uid TEXT NOT NULL, station_id INTEGER NOT NULL, participant_id INTEGER, status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED')), payload TEXT NOT NULL, decision_id INTEGER REFERENCES live_evidence_decisions(id), UNIQUE(event_id,uid,station_id), FOREIGN KEY(event_id,participant_id) REFERENCES live_entries(event_id,id))",
        "CREATE INDEX live_review_open ON live_review_cases(event_id,status)",
        "CREATE TRIGGER tag_record_no_update BEFORE UPDATE ON tag_readout_records BEGIN SELECT RAISE(ABORT,'Tag records are immutable'); END",
        "CREATE TRIGGER tag_record_no_delete BEFORE DELETE ON tag_readout_records BEGIN SELECT RAISE(ABORT,'Tag records are immutable'); END",
        "CREATE TRIGGER tag_session_no_update BEFORE UPDATE ON tag_readout_sessions WHEN OLD.status<>'PENDING' BEGIN SELECT RAISE(ABORT,'Tag sessions are immutable'); END",
        "CREATE TRIGGER tag_session_no_delete BEFORE DELETE ON tag_readout_sessions BEGIN SELECT RAISE(ABORT,'Tag sessions are immutable'); END",
        "CREATE TRIGGER evidence_decision_no_update BEFORE UPDATE ON live_evidence_decisions BEGIN SELECT RAISE(ABORT,'Decisions are append-only'); END",
        "CREATE TRIGGER evidence_decision_no_delete BEFORE DELETE ON live_evidence_decisions BEGIN SELECT RAISE(ABORT,'Decisions are append-only'); END",
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
