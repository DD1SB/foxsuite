"""Persistent, explicit mapping versions, independent of parsing and scoring."""

import csv
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from foxcore.persistence import Store
from foxcore.protocol import normalize_uid

from .sportident import bounded_integer, card_bytes


class Role(StrEnum):
    CONTROL = "CONTROL"
    START = "START"
    FINISH = "FINISH"


@dataclass(frozen=True)
class UidMapping:
    id: int
    uid: str
    card_number: int


@dataclass(frozen=True)
class StationMapping:
    id: int
    station_id: int
    control_code: int
    role: Role


def validate_station(station_id: int, control_code: int, role: Role) -> None:
    bounded_integer(station_id, 0, 65535, "Fox station ID")
    bounded_integer(control_code, 1, 1023, "SPORTident control code")
    if not isinstance(role, Role):
        raise ValueError("Station role must be CONTROL, START or FINISH")
    if role == Role.CONTROL:
        bounded_integer(control_code, 20, 254, "FjwW CONTROL code")
    elif role == Role.START and control_code != 3:
        raise ValueError("FjwW START must use control code 3")
    elif role == Role.FINISH and control_code != 4:
        raise ValueError("FjwW FINISH must use control code 4")


class MappingRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    def uid(self, uid: str) -> UidMapping | None:
        row = self.store.db.execute(
            "SELECT id,uid,card_number FROM bridge_uid_maps WHERE uid=? AND active=1",
            (normalize_uid(uid),),
        ).fetchone()
        return UidMapping(*row) if row else None

    def station(self, station_id: int) -> StationMapping | None:
        row = self.store.db.execute(
            "SELECT id,station_id,control_code,role FROM bridge_station_maps "
            "WHERE station_id=? AND active=1",
            (station_id,),
        ).fetchone()
        return StationMapping(row[0], row[1], row[2], Role(row[3])) if row else None

    def _add_uid(self, uid: str, card_number: int) -> UidMapping:
        uid = normalize_uid(uid)
        card_bytes(card_number)
        current = self.uid(uid)
        if current:
            if current.card_number == card_number:
                return current
            raise ValueError(
                f"UID {uid} already maps to {current.card_number}; remove it explicitly first"
            )
        try:
            cursor = self.store.db.execute(
                "INSERT INTO bridge_uid_maps(uid,card_number,active) VALUES (?,?,1)",
                (uid, card_number),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"SI card number {card_number} already has an active UID mapping"
            ) from exc
        assert cursor.lastrowid is not None
        return UidMapping(cursor.lastrowid, uid, card_number)

    def add_uid(self, uid: str, card_number: int) -> UidMapping:
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            return self._add_uid(uid, card_number)

    def _add_station(self, station_id: int, control_code: int, role: Role) -> StationMapping:
        validate_station(station_id, control_code, role)
        current = self.station(station_id)
        if current:
            if current.control_code == control_code and current.role == role:
                return current
            raise ValueError(f"Station {station_id} already mapped; remove it explicitly first")
        cursor = self.store.db.execute(
            "INSERT INTO bridge_station_maps(station_id,control_code,role,active) VALUES (?,?,?,1)",
            (station_id, control_code, role),
        )
        assert cursor.lastrowid is not None
        return StationMapping(cursor.lastrowid, station_id, control_code, role)

    def add_station(self, station_id: int, control_code: int, role: Role) -> StationMapping:
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            return self._add_station(station_id, control_code, role)

    def remove_uid(self, uid: str) -> None:
        with self.store.db:
            self.store.db.execute(
                "UPDATE bridge_uid_maps SET active=0 WHERE uid=? AND active=1",
                (normalize_uid(uid),),
            )

    def remove_station(self, station_id: int) -> None:
        with self.store.db:
            self.store.db.execute(
                "UPDATE bridge_station_maps SET active=0 WHERE station_id=? AND active=1",
                (station_id,),
            )

    def list_uids(self) -> list[UidMapping]:
        return [
            UidMapping(*r)
            for r in self.store.db.execute(
                "SELECT id,uid,card_number FROM bridge_uid_maps WHERE active=1 ORDER BY uid"
            )
        ]

    def list_stations(self) -> list[StationMapping]:
        return [
            StationMapping(r[0], r[1], r[2], Role(r[3]))
            for r in self.store.db.execute(
                "SELECT id,station_id,control_code,role FROM bridge_station_maps WHERE active=1 ORDER BY station_id"
            )
        ]

    def import_csv(self, path: Path, kind: str) -> int:
        headers = {
            "uid": {"uid", "card_number"},
            "station": {"station_id", "control_code", "role"},
        }
        if kind not in headers:
            raise ValueError("Mapping import kind must be uid or station")
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if set(reader.fieldnames or []) != headers[kind]:
                raise ValueError(
                    "CSV headers must be uid,card_number or station_id,control_code,role"
                )
            rows = list(reader)
        with self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            for row in rows:
                try:
                    if kind == "uid":
                        self._add_uid(row["uid"], int(row["card_number"]))
                    else:
                        self._add_station(
                            int(row["station_id"]),
                            int(row["control_code"]),
                            Role(row["role"].upper()),
                        )
                except (KeyError, TypeError) as exc:
                    raise ValueError(
                        "CSV headers must be uid,card_number or station_id,control_code,role"
                    ) from exc
        return len(rows)
