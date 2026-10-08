"""Atomic UTF-8 registration import and portable participant/result exports."""

import csv
import io
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from foxcore.protocol import normalize_uid

from .models import EntryData, RegistrationData, RunnerData, instant, unix
from .scoring import DistinctControlsThenTime
from .service import LiveService

HEADERS = [
    "start_number",
    "first_name",
    "last_name",
    "category",
    "uid",
    "club",
    "start_time",
    "birth_year",
    "birth_date",
    "club_code",
]


def preview(service: LiveService, event_id: int, text: str) -> dict[str, Any]:
    event = service.mutable(event_id)
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV exceeds 2 MB")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    if not set(HEADERS[:4]).issubset(reader.fieldnames or []) or len(
        reader.fieldnames or []
    ) != len(set(reader.fieldnames or [])):
        raise ValueError("Required CSV headers: start_number,first_name,last_name,category")
    if set(reader.fieldnames or []) - set(HEADERS):
        raise ValueError("Unsupported CSV columns")
    category_data = service.repo.categories(event_id)
    categories = {c.code: c.id for c in category_data}
    errors: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    runners = service.repo.runners()
    clubs = service.repo.clubs()
    existing = service.repo.entries(event_id)
    seen_people: set[tuple[Any, ...]] = set()
    seen_runner_ids: set[int] = set()
    seen_club_codes: dict[str, str] = {}
    seen_bibs: set[int] = set()
    seen_uids: set[str] = set()
    try:
        for number, row in enumerate(reader, 2):
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Column count does not match headers")
                category = row["category"]
                if category not in categories:
                    raise ValueError(f"Category {category} does not exist")
                club_name, club_code = row.get("club", "").strip(), row.get("club_code", "").strip()
                if club_code:
                    label = club_name or club_code
                    if club_code in seen_club_codes and seen_club_codes[club_code] != label:
                        raise ValueError("Club code and name do not match")
                    seen_club_codes[club_code] = label
                club_matches = (
                    [
                        c
                        for c in clubs
                        if (c.code == club_code if club_code else c.display_name == club_name)
                    ]
                    if club_name or club_code
                    else []
                )
                if len(club_matches) > 1:
                    raise ValueError("Club selection is ambiguous")
                if (
                    club_code
                    and club_matches
                    and club_name
                    and club_matches[0].display_name != club_name
                ):
                    raise ValueError("Club code and name do not match")
                person = service.validate_runner(
                    RunnerData(
                        first_name=row["first_name"],
                        last_name=row["last_name"],
                        birth_year=int(row["birth_year"]) if row.get("birth_year") else None,
                        birth_date=row.get("birth_date") or None,
                        club_id=club_matches[0].id if club_matches else None,
                    )
                )
                matches = [
                    r
                    for r in runners
                    if r.first_name == person.first_name
                    and r.last_name == person.last_name
                    and r.birth_year == person.birth_year
                    and r.birth_date == person.birth_date
                    and r.club_id == person.club_id
                ]
                # An as-yet unknown club is not the same as no club.
                if (club_name or club_code) and not club_matches:
                    matches = []
                if len(matches) > 1:
                    raise ValueError("Runner selection is ambiguous; register manually")
                if matches and not matches[0].active:
                    raise ValueError("Runner is inactive")
                if matches and any(e.active and e.runner_id == matches[0].id for e in existing):
                    raise ValueError("Runner is already registered in this event")
                if matches and matches[0].id in seen_runner_ids:
                    raise ValueError(
                        "Runner appears twice in CSV; register ambiguous people manually"
                    )
                data = RegistrationData(
                    start_number=int(row["start_number"]),
                    category_id=categories[category],
                    uid=row.get("uid") or None,
                    start_time=row.get("start_time") or None,
                )
                start = instant(data.start_time, event.timezone)
                seconds = unix(start)
                if (
                    seconds is not None
                    and not event.minimum_unix_timestamp <= seconds <= 4294967295
                ):
                    raise ValueError("Predefined start fails event timestamp validation")
                data = data.model_copy(
                    update={
                        "uid": normalize_uid(data.uid) if data.uid else None,
                        "start_time": start,
                    }
                )
                if not next(c for c in category_data if c.id == data.category_id).enabled:
                    raise ValueError("Category is not enabled for this event")
                for entry in existing:
                    if entry.start_number == data.start_number:
                        raise ValueError(f"Start number {data.start_number} already exists")
                    if data.uid and entry.active and entry.uid == data.uid:
                        raise ValueError(
                            f"UID {data.uid} is already assigned to participant {entry.start_number}"
                        )
                if data.start_number in seen_bibs:
                    raise ValueError(f"Duplicate start number {data.start_number} in CSV")
                if data.uid and data.uid in seen_uids:
                    raise ValueError(f"Duplicate UID {data.uid} in CSV")
                seen_bibs.add(data.start_number)
                if data.uid:
                    seen_uids.add(data.uid)
                identity = (
                    person.first_name,
                    person.last_name,
                    person.birth_year,
                    person.birth_date,
                    club_code,
                    club_name,
                )
                if identity in seen_people:
                    raise ValueError(
                        "Runner appears twice in CSV; register ambiguous people manually"
                    )
                seen_people.add(identity)
                if matches:
                    seen_runner_ids.add(matches[0].id)
                entries.append(
                    data.model_dump(mode="json")
                    | {
                        "first_name": person.first_name,
                        "last_name": person.last_name,
                        "runner": person.model_dump(),
                        "runner_id": matches[0].id if matches else None,
                        "club": club_name,
                        "club_code": club_code,
                    }
                )
            except (ValueError, TypeError, KeyError) as exc:
                message = str(exc)
                if isinstance(exc, ValidationError):
                    message = "; ".join(e["msg"] for e in exc.errors())
                errors.append({"row": number, "error": message})
    except csv.Error as exc:
        errors.append({"row": reader.line_num, "error": str(exc)})
    return {
        "valid": not errors,
        "count": len(entries),
        "errors": errors,
        "entries": entries,
    }


def import_participants(service: LiveService, event_id: int, text: str) -> dict[str, Any]:
    with service.repo.db:
        service.repo.db.execute("BEGIN IMMEDIATE")
        summary = preview(service, event_id, text)
        if not summary["valid"]:
            return summary
        for values in summary["entries"]:
            runner_id = values["runner_id"]
            if runner_id is None:
                person = RunnerData.model_validate(values["runner"])
                if person.club_id is None and (values["club"] or values["club_code"]):
                    club = next(
                        (
                            c
                            for c in service.repo.clubs()
                            if (
                                c.code == values["club_code"]
                                if values["club_code"]
                                else c.display_name == values["club"]
                            )
                        ),
                        None,
                    )
                    if club is None:
                        club_id = service._insert(
                            "live_clubs",
                            {
                                "code": values["club_code"],
                                "display_name": values["club"] or values["club_code"],
                                "active": True,
                            },
                        )
                        service._master_audit(
                            "club",
                            club_id,
                            None,
                            {
                                "code": values["club_code"],
                                "display_name": values["club"] or values["club_code"],
                            },
                        )
                    else:
                        club_id = club.id
                    person = person.model_copy(update={"club_id": club_id})
                runner_id = service._put_runner(person).id
            data = EntryData(
                runner_id=runner_id, **{k: values[k] for k in RegistrationData.model_fields}
            )
            service._put_entry(event_id, service.validate_entry(event_id, data))
        service._audit(event_id, "csv_import", str(event_id), None, {"count": summary["count"]})
        service._calculate(event_id)
    service.notify(event_id, "participant_updated")
    service.publish("master_data_changed", None, {})
    return {"valid": True, "count": summary["count"], "errors": []}


def export(service: LiveService, event_id: int, results: bool = False) -> str:
    service.repo.event(event_id)
    categories = {c.id: c.code for c in service.repo.categories(event_id)}
    entries = {e.id: e for e in service.repo.entries(event_id)}
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    if results:
        writer.writerow(
            [
                "rank",
                "start_number",
                "first_name",
                "last_name",
                "club",
                "category",
                "status",
                "controls",
                "start_time",
                "finish_time",
                "elapsed_time",
                "completeness",
                "provenance",
                "recovered_controls",
                "open_reviews",
                "manual_decision",
            ]
        )
        for result in DistinctControlsThenTime().calculate(service.repo.results(event_id)):
            entry = entries[result.participant_id]
            start = (
                datetime.fromtimestamp(result.start, UTC).isoformat()
                if result.start is not None
                else ""
            )
            finish = (
                datetime.fromtimestamp(result.finish, UTC).isoformat()
                if result.finish is not None
                else ""
            )
            writer.writerow(
                [
                    v
                    for v in [
                        result.rank if result.rank is not None else "",
                        entry.start_number,
                        entry.first_name,
                        entry.last_name,
                        entry.club,
                        categories[entry.category_id],
                        result.status,
                        result.controls,
                        start,
                        finish,
                        result.elapsed if result.elapsed is not None else "",
                        result.completeness,
                        result.provenance,
                        result.recovered_controls,
                        result.open_reviews,
                        result.manual_decision,
                    ]
                ]
            )
    else:
        writer.writerow(HEADERS)
        for entry in entries.values():
            writer.writerow(
                [
                    v
                    for v in [
                        entry.start_number,
                        entry.first_name,
                        entry.last_name,
                        categories[entry.category_id],
                        entry.uid or "",
                        entry.club,
                        entry.start_time or "",
                        entry.birth_year or "",
                        entry.birth_date or "",
                        entry.club_code,
                    ]
                ]
            )
    return stream.getvalue()
