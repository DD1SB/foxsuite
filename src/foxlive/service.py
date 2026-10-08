"""Event administration, durable association, audit and derived-only recalculation."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from foxcore.errors import error_message
from foxcore.events import Punch
from foxcore.logging import SafeLogger
from foxcore.protocol import normalize_uid

from .evidence import EvidenceService
from .lookup import club_matches, comparable
from .models import (
    Category,
    CategoryData,
    Club,
    ClubData,
    Entry,
    EntryData,
    Event,
    EventCategoryData,
    EventData,
    MasterCategory,
    RegistrationData,
    Runner,
    RunnerData,
    State,
    Station,
    StationData,
    instant,
    unix,
    validate_event,
)
from .persistence import LiveRepository, source_punch, timestamp
from .scoring import DistinctControlsThenTime, interpret

log = SafeLogger(__name__)


class LiveService:
    def __init__(
        self,
        repository: LiveRepository,
        operator: str = "local operator",
        publish: Callable[[str, int | None, dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo = repository
        self.operator = operator
        self.publish = publish or (lambda _type, _event, _payload: None)
        self.failure: Exception | None = None
        self.evidence = EvidenceService(self)
        self.review_notifications: dict[int, dict[int, str]] = {}

    def mutable(self, event_id: int) -> Event:
        event = self.repo.event(event_id)
        if event.state == State.ARCHIVED:
            raise ValueError("Archived events are read-only")
        return event

    def _audit(
        self,
        event_id: int,
        action: str,
        entity: str,
        before: Any,
        after: Any,
        reason: str = "",
        operator: str | None = None,
    ) -> None:
        if self.repo.event(event_id).state == State.CLOSED:
            action = "after_close:" + action
        self.repo.db.execute(
            "INSERT INTO live_audit_events(event_id,created_at,operator,action,entity,"
            "before_json,after_json,reason) VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                timestamp(),
                operator or self.operator,
                action,
                entity,
                json.dumps(before, sort_keys=True),
                json.dumps(after, sort_keys=True),
                reason,
            ),
        )

    def _insert(self, table: str, values: dict[str, Any]) -> int:
        cursor = self.repo.db.execute(
            f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _update(self, table: str, values: dict[str, Any], entity_id: int) -> None:
        self.repo.db.execute(
            f"UPDATE {table} SET {','.join(k + '=?' for k in values)} WHERE id=?",
            (*values.values(), entity_id),
        )

    def put_event(self, data: EventData, event_id: int | None = None) -> Event:
        data = validate_event(data)
        before = self.mutable(event_id).model_dump(mode="json") if event_id else None
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            values = data.model_dump(mode="json") | {"updated_at": timestamp()}
            if event_id is None:
                event_id = self._insert(
                    "live_events", values | {"state": "DRAFT", "created_at": timestamp()}
                )
            else:
                self._update("live_events", values, event_id)
            event = self.repo.event(event_id)
            self._audit(
                event_id,
                "event_configuration",
                str(event_id),
                before,
                event.model_dump(mode="json"),
            )
            self._calculate(event_id)
        self.notify(event_id, "event_state_changed")
        return event

    def transition(self, event_id: int, state: State, confirm_reviews: bool = False) -> Event:
        event = self.mutable(event_id)
        allowed = {
            State.DRAFT: {State.RUNNING, State.ARCHIVED},
            State.RUNNING: {State.CLOSED},
            State.CLOSED: {State.RUNNING, State.ARCHIVED},
        }
        if state == event.state:
            return event
        if state == State.CLOSED and self.evidence.reviews(event_id) and not confirm_reviews:
            raise ValueError("Open review cases remain; confirm close with provisional results")
        if state not in allowed.get(event.state, set()):
            raise ValueError(f"Cannot transition {event.state} to {state}")
        other = self.repo.running()
        if state == State.RUNNING and other is not None and other.id != event_id:
            raise ValueError("Cannot start event: another event is already RUNNING")
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            values: dict[str, Any] = {"state": state, "updated_at": timestamp()}
            if state == State.RUNNING:
                values["cursor"] = self.repo.db.execute(
                    "SELECT COALESCE(MAX(id),0) FROM punches"
                ).fetchone()[0]
            self._update("live_events", values, event_id)
            self._calculate(event_id)
            after = self.repo.event(event_id)
            self._audit(
                event_id,
                "lifecycle",
                str(event_id),
                event.model_dump(mode="json"),
                after.model_dump(mode="json"),
            )
        self.notify(event_id, "event_state_changed")
        return after

    def _master_audit(self, action: str, entity_id: int, before: Any, after: Any) -> None:
        self.repo.db.execute(
            "INSERT INTO live_master_audit(created_at,operator,action,entity_id,before_json,after_json) VALUES (?,?,?,?,?,?)",
            (
                timestamp(),
                self.operator,
                action,
                entity_id,
                json.dumps(before, sort_keys=True),
                json.dumps(after, sort_keys=True),
            ),
        )

    def _put_club(
        self, data: ClubData, club_id: int | None = None, allow_similar: bool = True
    ) -> Club:
        current = next((c for c in self.repo.clubs() if c.id == club_id), None)
        if club_id is not None and current is None:
            raise ValueError("Club does not exist")
        data = data.model_copy(
            update={
                "code": " ".join(data.code.strip().split()),
                "display_name": " ".join(data.display_name.strip().split()),
            }
        )
        if not data.display_name:
            raise ValueError("Club name cannot be blank")
        matches = club_matches(data, [c for c in self.repo.clubs() if c.id != club_id])
        if matches["exact"]:
            raise ValueError(
                "Club code already exists"
                if data.code
                and any(comparable(c.code) == comparable(data.code) for c in matches["exact"])
                else "Club name already exists"
            )
        if matches["similar"] and not allow_similar:
            raise ValueError("Similar clubs exist; review them before creating")
        values = data.model_dump(mode="json")
        if club_id is None:
            club_id = self._insert("live_clubs", values)
        else:
            self._update("live_clubs", values, club_id)
        club = Club(id=club_id, **values)
        self._master_audit(
            "club", club_id, current.model_dump() if current else None, club.model_dump()
        )
        return club

    def put_club(self, data: ClubData, club_id: int | None = None) -> Club:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            club = self._put_club(data, club_id)
        self.publish("master_data_changed", None, {})
        return club

    def quick_club(self, data: ClubData, allow_similar: bool = False) -> Club:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            club = self._put_club(data, allow_similar=allow_similar)
        self.publish("master_data_changed", None, {})
        return club

    def validate_runner(self, data: RunnerData) -> RunnerData:
        values = data.model_dump()
        values.update(first_name=data.first_name.strip(), last_name=data.last_name.strip())
        if not values["first_name"] or not values["last_name"]:
            raise ValueError("Runner names cannot be blank")
        if data.birth_date:
            try:
                born = date.fromisoformat(data.birth_date)
            except ValueError as exc:
                raise ValueError("Invalid birth date") from exc
            if born > date.today():
                raise ValueError("Birth date cannot be in the future")
            if data.birth_year is not None and data.birth_year != born.year:
                raise ValueError("Birth year does not match birth date")
            values.update(birth_year=born.year, birth_date=born.isoformat())
        if values["birth_year"] is None:
            raise ValueError("Birth year or birth date is required")
        if values["birth_year"] > date.today().year:
            raise ValueError("Birth year cannot be in the future")
        if data.club_id is not None and not any(c.id == data.club_id for c in self.repo.clubs()):
            raise ValueError("Club does not exist")
        return RunnerData.model_validate(values)

    def _put_runner(self, data: RunnerData, runner_id: int | None = None) -> Runner:
        current = self.repo.runner(runner_id) if runner_id else None
        data = self.validate_runner(data)
        values = data.model_dump(mode="json") | {"updated_at": timestamp()}
        if runner_id is None:
            runner_id = self._insert("live_runners", values | {"created_at": timestamp()})
        else:
            self._update("live_runners", values, runner_id)
        runner = self.repo.runner(runner_id)
        self._master_audit(
            "runner", runner_id, current.model_dump() if current else None, runner.model_dump()
        )
        return runner

    def put_runner(self, data: RunnerData, runner_id: int | None = None) -> Runner:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            runner = self._put_runner(data, runner_id)
        self.publish("master_data_changed", None, {})
        return runner

    def put_master_category(
        self, data: CategoryData, category_id: int | None = None
    ) -> MasterCategory:
        current = next((c for c in self.repo.master_categories() if c.id == category_id), None)
        if category_id is not None and current is None:
            raise ValueError("Category does not exist")
        values = data.model_dump(mode="json")
        for key in ("code", "display_name_en", "display_name_de"):
            values[key] = values[key].strip()
            if not values[key]:
                raise ValueError("Category code/name cannot be blank")
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            if any(
                comparable(c.code) == comparable(values["code"]) and c.id != category_id
                for c in self.repo.master_categories()
            ):
                raise ValueError(f"Category code {values['code']} already exists")
            values["needs_review"] = False
            if category_id is None:
                category_id = self._insert("live_category_master", values)
            else:
                self._update("live_category_master", values, category_id)
            category = MasterCategory(id=category_id, **values)
            self._master_audit(
                "category",
                category_id,
                current.model_dump() if current else None,
                category.model_dump(),
            )
        self.publish("master_data_changed", None, {})
        return category

    def quick_category(self, event_id: int, data: CategoryData) -> Category:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            self.mutable(event_id)
            values = {
                k: v.strip() if isinstance(v, str) else v for k, v in data.model_dump().items()
            }
            if not all(values[k] for k in ("code", "display_name_en", "display_name_de")):
                raise ValueError("Category code/name cannot be blank")
            if not data.active:
                raise ValueError("Category is inactive")
            if any(
                comparable(c.code) == comparable(data.code) for c in self.repo.master_categories()
            ):
                raise ValueError(f"Category code {data.code} already exists")
            category_id = self._insert("live_category_master", values | {"needs_review": False})
            master = MasterCategory.model_validate(values | {"id": category_id})
            self._master_audit("category", category_id, None, master.model_dump())
            self.repo.db.execute(
                "INSERT INTO live_event_categories VALUES (?,?,1,0,?,?,?)",
                (
                    event_id,
                    category_id,
                    master.code,
                    master.display_name_en,
                    master.display_name_de,
                ),
            )
            category = next(c for c in self.repo.categories(event_id) if c.id == category_id)
            self._audit(event_id, "category", str(category_id), None, category.model_dump())
            self._calculate(event_id)
        self.publish("master_data_changed", None, {})
        self.notify(event_id, "ranking_changed")
        return category

    def put_category(
        self, event_id: int, data: EventCategoryData, category_id: int | None = None
    ) -> Category:
        self.mutable(event_id)
        current = next((c for c in self.repo.categories(event_id) if c.id == category_id), None)
        if category_id is not None and current is None:
            raise ValueError("Category does not exist in this event")
        if category_id is not None and category_id != data.category_id:
            raise ValueError(
                "Category selection cannot be changed; enable another category instead"
            )
        master = next((c for c in self.repo.master_categories() if c.id == data.category_id), None)
        if master is None:
            raise ValueError("Category does not exist")
        if current is None and not master.active:
            raise ValueError("Category is inactive")
        current = next(
            (c for c in self.repo.categories(event_id) if c.id == data.category_id), current
        )
        if any(c.code == master.code and c.id != master.id for c in self.repo.categories(event_id)):
            raise ValueError(f"Category code {master.code} already exists")
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            self.repo.db.execute(
                "INSERT INTO live_event_categories VALUES (?,?,?,?,?,?,?) ON CONFLICT(event_id,category_id) "
                "DO UPDATE SET enabled=excluded.enabled,display_order=excluded.display_order",
                (
                    event_id,
                    master.id,
                    data.enabled,
                    data.display_order,
                    master.code,
                    master.display_name_en,
                    master.display_name_de,
                ),
            )
            category = next(c for c in self.repo.categories(event_id) if c.id == master.id)
            self._audit(
                event_id,
                "category",
                str(master.id),
                current.model_dump() if current else None,
                category.model_dump(),
            )
            self._calculate(event_id)
        self.notify(event_id, "ranking_changed")
        return category

    def validate_entry(
        self, event_id: int, data: EntryData, entry_id: int | None = None
    ) -> EntryData:
        event = self.mutable(event_id)
        current = next((e for e in self.repo.entries(event_id) if e.id == entry_id), None)
        if entry_id is not None and current is None:
            raise ValueError("Participant does not exist in this event")
        category = next(
            (c for c in self.repo.categories(event_id) if c.id == data.category_id), None
        )
        if category is None:
            raise ValueError("Category does not exist in this event")
        if not category.enabled and (current is None or current.category_id != data.category_id):
            raise ValueError("Category is not enabled for this event")
        runner = self.repo.runner(data.runner_id)
        if not runner.active and (current is None or current.runner_id != runner.id):
            raise ValueError("Runner is inactive")
        uid = normalize_uid(data.uid) if data.uid else None
        start = instant(data.start_time, event.timezone)
        seconds = unix(start)
        if seconds is not None and not event.minimum_unix_timestamp <= seconds <= 4294967295:
            raise ValueError("Predefined start fails event timestamp validation")
        for entry in self.repo.entries(event_id):
            if entry.id == entry_id:
                continue
            if entry.start_number == data.start_number:
                raise ValueError(f"Start number {data.start_number} already exists")
            if uid and data.active and entry.active and entry.uid == uid:
                raise ValueError(
                    f"UID {uid} is already assigned to participant {entry.start_number}"
                )
            if data.active and entry.active and entry.runner_id == data.runner_id:
                raise ValueError("Runner is already registered in this event")
        return data.model_copy(update={"uid": uid, "start_time": start})

    def _put_entry(self, event_id: int, data: EntryData, entry_id: int | None = None) -> Entry:
        current = next((e for e in self.repo.entries(event_id) if e.id == entry_id), None)
        if entry_id is not None and current is None:
            raise ValueError("Participant does not exist in this event")
        values = data.model_dump(mode="json") | {"updated_at": timestamp()}
        if current is None or current.runner_id != data.runner_id:
            runner = self.repo.runner(data.runner_id)
            values.update(
                {
                    key: getattr(runner, key)
                    for key in (
                        "first_name",
                        "last_name",
                        "birth_year",
                        "birth_date",
                        "club",
                        "club_code",
                    )
                }
            )
        if entry_id is None:
            entry_id = self._insert(
                "live_entries", values | {"event_id": event_id, "created_at": timestamp()}
            )
        else:
            self._update("live_entries", values, entry_id)
        entry = next(e for e in self.repo.entries(event_id) if e.id == entry_id)
        self._audit(
            event_id,
            "participant_uid_category_status",
            str(entry_id),
            current.model_dump(mode="json") if current else None,
            entry.model_dump(mode="json"),
        )
        return entry

    def register_new_runner(
        self,
        event_id: int,
        runner_data: RunnerData,
        data: RegistrationData,
        club_data: ClubData | None = None,
        allow_similar_club: bool = False,
    ) -> Entry:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            self.mutable(event_id)
            if club_data is not None:
                if runner_data.club_id is not None:
                    raise ValueError("Select an existing club or create a new club, not both")
                club = self._put_club(club_data, allow_similar=allow_similar_club)
                runner_data = runner_data.model_copy(update={"club_id": club.id})
            runner = self._put_runner(runner_data)
            entry_data = self.validate_entry(
                event_id, EntryData(runner_id=runner.id, **data.model_dump())
            )
            entry = self._put_entry(event_id, entry_data)
            self._calculate(event_id)
        self.publish("master_data_changed", None, {})
        self.notify(event_id, "participant_updated", {"participant_id": entry.id})
        return entry

    def put_entry(self, event_id: int, data: EntryData, entry_id: int | None = None) -> Entry:
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            data = self.validate_entry(event_id, data, entry_id)
            entry = self._put_entry(event_id, data, entry_id)
            self._calculate(event_id)
        self.notify(event_id, "participant_updated", {"participant_id": entry.id})
        return entry

    def put_station(self, event_id: int, data: StationData) -> Station:
        self.mutable(event_id)
        if not data.display_name.strip():
            raise ValueError("Station name cannot be blank")
        current = next(
            (s for s in self.repo.stations(event_id) if s.station_id == data.station_id), None
        )
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            self.repo.db.execute(
                "INSERT INTO live_event_stations VALUES (?,?,?,?,?,?) ON CONFLICT(event_id,station_id) "
                "DO UPDATE SET display_name=excluded.display_name,role=excluded.role,"
                "enabled=excluded.enabled,display_order=excluded.display_order",
                (
                    event_id,
                    data.station_id,
                    data.display_name,
                    data.role,
                    data.enabled,
                    data.display_order,
                ),
            )
            station = Station(event_id=event_id, **data.model_dump())
            self._audit(
                event_id,
                "station_configuration",
                str(data.station_id),
                current.model_dump(mode="json") if current else None,
                station.model_dump(mode="json"),
            )
            self._calculate(event_id)
        self.notify(event_id, "station_updated", {"station_id": data.station_id})
        return station

    def _calculate(self, event_id: int, uid: str | None = None) -> dict[str, int]:
        event = self.repo.event(event_id)
        entries = self.repo.entries(event_id)
        selected = [e for e in entries if uid is None or e.uid == uid]
        calculation = interpret(
            event,
            selected,
            self.repo.categories(event_id),
            {s.station_id: (s.role, s.enabled) for s in self.repo.stations(event_id)},
            self.repo.punches(event_id, uid),
            self.repo.exclusions(event_id),
        )
        self.review_notifications.setdefault(
            event_id, {r["id"]: r["status"] for r in self.evidence.reviews(event_id, True)}
        )
        resolved = self.evidence.calculate(event_id, selected, uid)
        for item in calculation.interpretations:
            self.repo.db.execute(
                "INSERT INTO live_entry_interpretations VALUES (?,?,?,?,?,?) ON CONFLICT(event_id,punch_id) "
                "DO UPDATE SET participant_id=excluded.participant_id,status=excluded.status,role=excluded.role,reason=excluded.reason",
                (event_id, item.punch_id, item.participant_id, item.status, item.role, item.reason),
            )
        for result in resolved.results:
            self.repo.db.execute(
                "INSERT INTO live_entry_results VALUES (?,?,?) ON CONFLICT(event_id,participant_id) "
                "DO UPDATE SET payload=excluded.payload",
                (event_id, result.participant_id, result.model_dump_json()),
            )
        existing = self.repo.results(event_id)
        previous = {r.participant_id: r.model_dump_json() for r in existing}
        self.repo.db.executemany(
            "UPDATE live_entry_results SET payload=? WHERE event_id=? AND participant_id=?",
            [
                (r.model_dump_json(), event_id, r.participant_id)
                for r in DistinctControlsThenTime().calculate(existing)
                if r.model_dump_json() != previous[r.participant_id]
            ],
        )
        return {
            "source_punches": len(calculation.interpretations),
            "recovered_controls": sum(r.recovered_controls for r in resolved.results),
            "open_reviews": len(self.evidence.reviews(event_id)),
        } | calculation.counts

    def recalculate(self, event_id: int) -> dict[str, int]:
        self.mutable(event_id)
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            counts = self._calculate(event_id)
            self._audit(event_id, "recalculate", str(event_id), None, counts)
        self.notify(event_id, "ranking_changed", counts)
        return counts

    def exclude(self, event_id: int, punch_id: int, reason: str) -> dict[str, int]:
        self.mutable(event_id)
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("Exclusion requires a reason of 1..1000 characters")
        if not self.repo.db.execute(
            "SELECT 1 FROM live_event_punches WHERE event_id=? AND punch_id=?", (event_id, punch_id)
        ).fetchone():
            raise ValueError("Punch is not associated with this event")
        before = self.repo.exclusions(event_id).get(punch_id)
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            self.repo.db.execute(
                "INSERT INTO live_manual_exclusions VALUES (?,?,?,?) ON CONFLICT(event_id,punch_id) "
                "DO UPDATE SET reason=excluded.reason",
                (event_id, punch_id, reason.strip(), timestamp()),
            )
            self._audit(
                event_id, "manual_exclusion", str(punch_id), before, reason.strip(), reason.strip()
            )
            counts = self._calculate(event_id)
        self.notify(event_id, "ranking_changed", counts)
        return counts

    def associate(self, event_id: int, punch_ids: list[int]) -> dict[str, int]:
        self.mutable(event_id)
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            for punch_id in sorted(set(punch_ids)):
                punch = self.repo.store.get_punch(punch_id)
                if punch.replayed:
                    raise ValueError(
                        "Associate original source punches, not appended replay copies"
                    )
                self.repo.db.execute(
                    "INSERT OR IGNORE INTO live_event_punches VALUES (?,?,?,?,?)",
                    (event_id, punch_id, punch.uid, timestamp(), "historical"),
                )
            self._audit(
                event_id, "historical_association", str(event_id), None, sorted(set(punch_ids))
            )
            counts = self._calculate(event_id)
        self.notify(event_id, "ranking_changed", counts)
        return counts

    def accept(self, punch: Punch) -> None:
        if punch.id is None or punch.replayed:
            return
        try:
            event = self.repo.running()
            if event is None or punch.id <= event.cursor:
                return
            with self.repo.db:
                self.repo.db.execute(
                    "INSERT OR IGNORE INTO live_event_punches VALUES (?,?,?,?,?)",
                    (event.id, punch.id, punch.uid, timestamp(), "live"),
                )
                self.repo.db.execute(
                    "UPDATE live_events SET cursor=? WHERE id=?", (punch.id, event.id)
                )
            with self.repo.db:
                self._calculate(event.id, punch.uid)
            self.notify(event.id, "punch_received", {"punch_id": punch.id})
            self.publish("station_updated", event.id, {"station_id": punch.station_id})
            self.publish("participant_updated", event.id, {"uid": punch.uid})
            if (
                self.repo.db.execute(
                    "SELECT status FROM live_entry_interpretations WHERE event_id=? AND punch_id=?",
                    (event.id, punch.id),
                ).fetchone()[0]
                == "UNKNOWN_UID"
            ):
                self.publish("unknown_uid", event.id, {"uid": punch.uid, "punch_id": punch.id})
        except Exception as exc:
            self.failure = exc
            log.warning("ERROR FoxLive processing failed; source remains stored: %s", exc)

    def recover(self) -> None:
        self.evidence.recover_pending()
        for historical in self.repo.events():
            if historical.state != State.ARCHIVED:
                with self.repo.db:
                    self._calculate(historical.id)
        self.review_notifications.clear()  # Restart is not a new readout/review arrival.
        event = self.repo.running()
        if event is None:
            return
        # Rebuild already associated facts first; no historic browser punch emissions.
        with self.repo.db:
            self._calculate(event.id)
        for row in self.repo.db.execute(
            "SELECT * FROM punches WHERE id>? AND replayed=0 ORDER BY id", (event.cursor,)
        ).fetchall():
            punch = source_punch(row)
            assert punch.id is not None
            with self.repo.db:
                self.repo.db.execute(
                    "INSERT OR IGNORE INTO live_event_punches VALUES (?,?,?,?,?)",
                    (event.id, punch.id, punch.uid, timestamp(), "recovery"),
                )
                self.repo.db.execute(
                    "UPDATE live_events SET cursor=? WHERE id=?", (punch.id, event.id)
                )
        with self.repo.db:
            self._calculate(event.id)

    def notify(self, event_id: int, kind: str, payload: dict[str, Any] | None = None) -> None:
        before = self.review_notifications.pop(event_id, None)
        if before is not None:
            self.evidence.publish_review_changes(event_id, before)
        self.publish(kind, event_id, payload or {})
        if kind != "ranking_changed":
            self.publish("ranking_changed", event_id, {})
        if (
            kind != "reconciliation_updated"
            and self.repo.db.execute(
                "SELECT EXISTS(SELECT 1 FROM tag_readout_sessions WHERE event_id=?) OR "
                "EXISTS(SELECT 1 FROM live_evidence_decisions WHERE event_id=?)",
                (event_id, event_id),
            ).fetchone()[0]
        ):
            self.publish("reconciliation_updated", event_id, {})

    def snapshot(self, event_id: int | None = None) -> dict[str, Any]:
        events = self.repo.events()
        running = self.repo.running()
        if event_id is None:
            event_id = running.id if running else (events[0].id if events else None)
        diagnostics: dict[str, Any] = {}
        for kind in ("connection", "timesync"):
            row = self.repo.db.execute(
                "SELECT detail FROM diagnostics WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,)
            ).fetchone()
            if row:
                try:
                    diagnostics[kind] = json.loads(row[0])
                except json.JSONDecodeError:
                    diagnostics[kind] = {"detail": row[0]}
        base: dict[str, Any] = {
            "events": [e.model_dump(mode="json") for e in events],
            "active_event_id": running.id if running else None,
            "diagnostics": diagnostics,
            "processing_error": error_message(self.failure) if self.failure else None,
            "now": timestamp(),
            "event": None,
            "participants": [],
            "categories": [],
            "stations": [],
            "recent": [],
            "unknown": [],
            "results": [],
            "readouts": [],
            "reviews": [],
            "reconciliation": {},
        }
        if event_id is None:
            return base
        event = self.repo.event(event_id)
        recent = self.repo.recent(event_id)
        unknown = [
            dict(r)
            for r in self.repo.db.execute(
                "SELECT p.uid,p.station_id,p.station_timestamp,p.id FROM live_entry_interpretations i JOIN punches p "
                "ON p.id=i.punch_id WHERE i.event_id=? AND i.status='UNKNOWN_UID' ORDER BY p.station_timestamp DESC,p.id DESC LIMIT 500",
                (event_id,),
            )
        ]
        activity = {
            r["station_id"]: dict(r)
            for r in self.repo.db.execute(
                "SELECT p.station_id,COUNT(*) AS punch_count,MAX(p.station_timestamp) AS last_time FROM punches p "
                "JOIN live_event_punches a ON a.punch_id=p.id WHERE a.event_id=? GROUP BY p.station_id",
                (event_id,),
            )
        }
        latest = {
            r["station_id"]: dict(r)
            for r in self.repo.db.execute(
                "SELECT station_id,callsign,rssi FROM (SELECT p.station_id,p.callsign,p.rssi,"
                "ROW_NUMBER() OVER (PARTITION BY p.station_id ORDER BY p.station_timestamp DESC,p.id DESC) AS n "
                "FROM punches p JOIN live_event_punches a ON a.punch_id=p.id WHERE a.event_id=?) WHERE n=1",
                (event_id,),
            )
        }
        results = self.repo.results(event_id)
        reviews = self.evidence.reviews(event_id)
        evidence_counts = self.repo.db.execute(
            "SELECT (SELECT COUNT(*) FROM tag_readout_sessions WHERE event_id=?),"
            "(SELECT COUNT(*) FROM live_evidence_decisions WHERE event_id=?) + "
            "(SELECT COUNT(*) FROM live_audit_events WHERE event_id=? AND action IN ('status_adjudication','after_close:status_adjudication'))",
            (event_id, event_id, event_id),
        ).fetchone()
        return base | {
            "event": event.model_dump(mode="json"),
            "participants": [e.model_dump(mode="json") for e in self.repo.entries(event_id)],
            "categories": [c.model_dump(mode="json") for c in self.repo.categories(event_id)],
            "stations": [
                s.model_dump(mode="json")
                | activity.get(s.station_id, {})
                | latest.get(s.station_id, {})
                for s in self.repo.stations(event_id)
            ],
            "recent": recent,
            "unknown": unknown,
            "readouts": self.evidence.sessions(event_id, 20),
            "reviews": reviews,
            "reconciliation": {
                "readouts": evidence_counts[0],
                "recovered": sum(r.recovered_controls for r in results),
                "open_reviews": len(reviews),
                "manual_decisions": evidence_counts[1],
            },
            "results": [
                r.model_dump(mode="json") for r in DistinctControlsThenTime().calculate(results)
            ],
        }
