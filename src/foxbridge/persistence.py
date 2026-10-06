"""Bridge ledger atop the FoxCore-owned connection. No Fox source rows are changed."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from foxcore.events import Punch
from foxcore.persistence import Store

from .config import BridgeConfig
from .mapping import MappingRepository
from .sportident import SportIdentEncoder, SportIdentPunch
from .time import convert_time


@dataclass(frozen=True)
class Delivery:
    id: int
    punch_id: int
    status: str
    frame: bytes | None
    error: str | None


def now_text() -> str:
    return datetime.now(UTC).isoformat()


class DeliveryRepository:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.mapping = MappingRepository(store)

    def get(self, delivery_id: int) -> Delivery:
        row = self.store.db.execute(
            "SELECT * FROM bridge_deliveries WHERE id=?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Bridge delivery {delivery_id} does not exist")
        return Delivery(
            row["id"], row["punch_id"], row["status"], row["encoded_frame"], row["error"]
        )

    def prepare(
        self,
        punch: Punch,
        config: BridgeConfig,
        encoder: SportIdentEncoder,
        allow_replay: bool = False,
        explicit: bool = False,
    ) -> Delivery | None:
        if punch.id is None:
            raise ValueError("FoxBridge requires a persisted FoxCore punch ID")
        db = self.store.db
        with db:
            db.execute("BEGIN IMMEDIATE")
            if (
                not explicit
                and db.execute(
                    "SELECT 1 FROM bridge_deliveries WHERE target=? AND punch_id=? AND automatic=1",
                    (config.target, punch.id),
                ).fetchone()
            ):
                return None
            cursor = db.execute(
                "INSERT INTO bridge_deliveries(punch_id,target,created_at,status,"
                "output_endpoint,automatic) VALUES (?,?,?,'reserved',?,?)",
                (punch.id, config.target, now_text(), config.output.endpoint, not explicit),
            )
            assert cursor.lastrowid is not None
            delivery_id = cursor.lastrowid
            status, error = "queued", None
            if punch.duplicate:
                status, error = "duplicate_ignored", "FoxCore transport duplicate"
            elif punch.replayed and not allow_replay:
                status, error = "replay_blocked", "Replay output requires --allow-replay-output"
            else:
                old = (
                    db.execute(
                        "SELECT * FROM bridge_deliveries WHERE target=? AND punch_id=? "
                        "AND encoded_frame IS NOT NULL ORDER BY id DESC LIMIT 1",
                        (config.target, punch.id),
                    ).fetchone()
                    if explicit
                    else None
                )
                if old:
                    # Resend exact frozen identity/frame, even if current mappings changed.
                    db.execute(
                        "UPDATE bridge_deliveries SET uid_mapping_id=?,station_mapping_id=?,"
                        "card_number=?,control_code=?,role=?,backup_offset=?,encoded_frame=? WHERE id=?",
                        (
                            old["uid_mapping_id"],
                            old["station_mapping_id"],
                            old["card_number"],
                            old["control_code"],
                            old["role"],
                            old["backup_offset"],
                            old["encoded_frame"],
                            delivery_id,
                        ),
                    )
                else:
                    uid = self.mapping.uid(punch.uid)
                    station = self.mapping.station(punch.station_id)
                    missing = []
                    if uid is None:
                        missing.append(f"RFID UID {punch.uid} has no SI-card mapping")
                    if station is None:
                        missing.append(
                            f"Station {punch.station_id} has no SPORTident control mapping"
                        )
                    if missing:
                        status, error = "mapping_error", "; ".join(missing)
                    else:
                        assert uid is not None and station is not None
                        db.execute(
                            "UPDATE bridge_deliveries SET uid_mapping_id=?,station_mapping_id=?,"
                            "card_number=?,control_code=?,role=? WHERE id=?",
                            (
                                uid.id,
                                station.id,
                                uid.card_number,
                                station.control_code,
                                station.role,
                                delivery_id,
                            ),
                        )
                        try:
                            policy = config.sportident
                            if punch.station_timestamp < policy.minimum_unix_timestamp:
                                raise ValueError("Fox timestamp is below the configured minimum")
                            skew = abs(punch.station_timestamp - punch.received_at_pc.timestamp())
                            if skew > policy.maximum_receive_skew_seconds:
                                raise ValueError(
                                    "Fox timestamp differs too far from original PC receive time"
                                )
                            time = convert_time(
                                punch.station_timestamp, policy.timezone, policy.week_counter
                            )
                            offset_row = db.execute(
                                "SELECT next_offset FROM bridge_offsets "
                                "WHERE target=? AND control_code=?",
                                (config.target, station.control_code),
                            ).fetchone()
                            offset = int(offset_row[0]) if offset_row else 0
                            encoded = encoder.encode_punch(
                                SportIdentPunch(uid.card_number, station.control_code, time, offset)
                            )
                            db.execute(
                                "INSERT INTO bridge_offsets VALUES (?,?,?) "
                                "ON CONFLICT(target,control_code) DO UPDATE "
                                "SET next_offset=excluded.next_offset",
                                (config.target, station.control_code, offset + 8),
                            )
                            db.execute(
                                "UPDATE bridge_deliveries SET backup_offset=?,encoded_frame=? WHERE id=?",
                                (offset, encoded, delivery_id),
                            )
                        except ValueError as exc:
                            status, error = "encoding_error", str(exc)
            db.execute(
                "UPDATE bridge_deliveries SET status=?,error=?,finished_at=? WHERE id=?",
                (status, error, None if status == "queued" else now_text(), delivery_id),
            )
        return self.get(delivery_id)

    def claim(self, delivery_id: int) -> Delivery | None:
        with self.store.db:
            cursor = self.store.db.execute(
                "UPDATE bridge_deliveries SET status='writing' WHERE id=? AND status='queued'",
                (delivery_id,),
            )
        return self.get(delivery_id) if cursor.rowcount else None

    def finish(self, delivery_id: int, status: str, error: str | None = None) -> None:
        with self.store.db:
            self.store.db.execute(
                "UPDATE bridge_deliveries SET status=?,error=?,finished_at=? WHERE id=?",
                (status, error, now_text(), delivery_id),
            )

    def output_state(self, config: BridgeConfig, connected: bool, detail: str) -> None:
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO bridge_output_state VALUES (?,?,?,?,?) "
                "ON CONFLICT(target) DO UPDATE SET updated_at=excluded.updated_at,"
                "endpoint=excluded.endpoint,connected=excluded.connected,detail=excluded.detail",
                (config.target, now_text(), config.output.endpoint, connected, detail),
            )

    def list_deliveries(self, target: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT * FROM bridge_deliveries WHERE target=? ORDER BY id DESC LIMIT ?",
            (target, limit),
        )
        result = []
        for row in rows:
            value = dict(row)
            if value["encoded_frame"] is not None:
                value["encoded_frame"] = value["encoded_frame"].hex().upper()
            result.append(value)
        return result

    def status(self, config: BridgeConfig) -> dict[str, Any]:
        db = self.store.db
        counts = dict(
            db.execute(
                "SELECT status,COUNT(*) FROM bridge_deliveries WHERE target=? GROUP BY status",
                (config.target,),
            ).fetchall()
        )
        last = db.execute(
            "SELECT id,punch_id,card_number,control_code,finished_at FROM bridge_deliveries "
            "WHERE target=? AND status='sent' ORDER BY id DESC LIMIT 1",
            (config.target,),
        ).fetchone()
        state = db.execute(
            "SELECT * FROM bridge_output_state WHERE target=?", (config.target,)
        ).fetchone()
        uids = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT p.uid FROM bridge_deliveries d JOIN punches p "
                "ON p.id=d.punch_id LEFT JOIN bridge_uid_maps m ON m.uid=p.uid AND m.active=1 "
                "WHERE d.target=? AND d.status='mapping_error' AND m.id IS NULL ORDER BY p.uid",
                (config.target,),
            )
        ]
        stations = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT p.station_id FROM bridge_deliveries d JOIN punches p "
                "ON p.id=d.punch_id LEFT JOIN bridge_station_maps m ON m.station_id=p.station_id AND m.active=1 "
                "WHERE d.target=? AND d.status='mapping_error' AND m.id IS NULL ORDER BY p.station_id",
                (config.target,),
            )
        ]
        sources = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT p.source FROM bridge_deliveries d JOIN punches p "
                "ON p.id=d.punch_id WHERE d.target=? ORDER BY p.source",
                (config.target,),
            )
        ]
        return {
            "target": config.target,
            "endpoint": config.output.endpoint,
            "foxcore": self.store.stats(),
            "sources": sources,
            "output_state": dict(state) if state else None,
            "status_counts": counts,
            "delivered": counts.get("sent", 0),
            "mapping_failures": counts.get("mapping_error", 0),
            "encoding_failures": counts.get("encoding_error", 0),
            "last_delivered": dict(last) if last else None,
            "unmapped_uids": uids,
            "unmapped_stations": stations,
            "note": "Last persisted states; sent means driver write, not Fjw acknowledgement. "
            "Queued/writing records from previous runs are not resumed automatically.",
        }
