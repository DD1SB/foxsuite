"""Station metadata is separate from firmware parsing."""

from dataclasses import dataclass

from .persistence import Store


@dataclass(frozen=True)
class Station:
    station_id: int
    name: str
    callsign: str | None = None


class StationRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    def put(self, station: Station) -> None:
        with self.store.db:
            self.store.db.execute("INSERT INTO stations VALUES (?,?,?) ON CONFLICT(station_id) "
                                  "DO UPDATE SET name=excluded.name,callsign=excluded.callsign",
                                  (station.station_id, station.name, station.callsign))

    def get(self, station_id: int) -> Station | None:
        row = self.store.db.execute("SELECT * FROM stations WHERE station_id=?",
                                    (station_id,)).fetchone()
        return Station(*row) if row else None
