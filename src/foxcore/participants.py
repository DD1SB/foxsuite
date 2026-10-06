"""Minimal UID-to-participant mapping; no competition semantics."""

from dataclasses import dataclass

from .persistence import Store
from .protocol import normalize_uid


@dataclass(frozen=True)
class Participant:
    id: int
    name: str


class ParticipantRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, name: str) -> Participant:
        with self.store.db:
            cursor = self.store.db.execute("INSERT INTO participants(name) VALUES (?)", (name,))
        assert cursor.lastrowid is not None
        return Participant(cursor.lastrowid, name)

    def assign_uid(self, uid: str, participant_id: int) -> None:
        with self.store.db:
            self.store.db.execute("INSERT INTO participant_uids VALUES (?,?) "
                                  "ON CONFLICT(uid) DO UPDATE SET participant_id=excluded.participant_id",
                                  (normalize_uid(uid), participant_id))

    def find_by_uid(self, uid: str) -> Participant | None:
        row = self.store.db.execute("SELECT p.id,p.name FROM participants p JOIN participant_uids u "
                                    "ON p.id=u.participant_id WHERE u.uid=?",
                                    (normalize_uid(uid),)).fetchone()
        return Participant(row[0], row[1]) if row else None
