"""Atomic UTF-8 registration import and portable participant/result exports."""

import csv
import io
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .models import EntryData
from .service import LiveService

HEADERS = ["start_number", "first_name", "last_name", "category", "uid", "club", "start_time"]


def preview(service: LiveService, event_id: int, text: str) -> dict[str, Any]:
    service.mutable(event_id)
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV exceeds 2 MB")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    if not set(HEADERS[:4]).issubset(reader.fieldnames or []) or len(
        reader.fieldnames or []
    ) != len(set(reader.fieldnames or [])):
        raise ValueError("Required CSV headers: start_number,first_name,last_name,category")
    if set(reader.fieldnames or []) - set(HEADERS):
        raise ValueError("Unsupported CSV columns")
    categories = {c.code: c.id for c in service.repo.categories(event_id)}
    errors: list[dict[str, Any]] = []
    entries: list[EntryData] = []
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
                data = EntryData(
                    start_number=int(row["start_number"]),
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    category_id=categories[category],
                    uid=row.get("uid") or None,
                    club=row.get("club", ""),
                    start_time=row.get("start_time") or None,
                )
                data = service.validate_entry(event_id, data)
                if data.start_number in seen_bibs:
                    raise ValueError(f"Duplicate start number {data.start_number} in CSV")
                if data.uid and data.uid in seen_uids:
                    raise ValueError(f"Duplicate UID {data.uid} in CSV")
                seen_bibs.add(data.start_number)
                if data.uid:
                    seen_uids.add(data.uid)
                entries.append(data)
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
        "entries": [e.model_dump(mode="json") for e in entries],
    }


def import_participants(service: LiveService, event_id: int, text: str) -> dict[str, Any]:
    with service.repo.db:
        service.repo.db.execute("BEGIN IMMEDIATE")
        summary = preview(service, event_id, text)
        if not summary["valid"]:
            return summary
        for values in summary["entries"]:
            service._put_entry(event_id, EntryData.model_validate(values))
        service._audit(event_id, "csv_import", str(event_id), None, {"count": summary["count"]})
        service._calculate(event_id)
    service.notify(event_id, "participant_updated")
    return {"valid": True, "count": summary["count"], "errors": []}


def safe_cell(value: Any) -> Any:
    # Spreadsheet formula injection is not needed for a local desk, but exports should be safe.
    return (
        "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
    )


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
            ]
        )
        for result in service.repo.results(event_id):
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
                    safe_cell(v)
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
                    ]
                ]
            )
    else:
        writer.writerow(HEADERS)
        for entry in entries.values():
            writer.writerow(
                [
                    safe_cell(v)
                    for v in [
                        entry.start_number,
                        entry.first_name,
                        entry.last_name,
                        categories[entry.category_id],
                        entry.uid or "",
                        entry.club,
                        entry.start_time or "",
                    ]
                ]
            )
    return stream.getvalue()
