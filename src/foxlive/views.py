"""Read-only desk projections; never change facts or calculate another result."""

from typing import Any

from .service import LiveService


def display_state(service: LiveService, event_id: int | None = None) -> dict[str, Any]:
    state = service.snapshot(event_id)

    def pick(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {k: value.get(k) for k in keys}

    return {
        "event": pick(state["event"], ("id", "name", "date", "timezone", "state"))
        if state["event"]
        else None,
        "now": state["now"],
        "categories": [
            pick(c, ("id", "code", "display_name_en", "display_name_de", "enabled"))
            for c in state["categories"]
        ],
        "participants": [
            pick(p, ("id", "start_number", "first_name", "last_name", "category_id"))
            for p in state["participants"]
        ],
        "results": [
            pick(
                r,
                (
                    "participant_id",
                    "category_id",
                    "start_number",
                    "status",
                    "controls",
                    "start",
                    "finish",
                    "elapsed",
                    "rank",
                    "eligible",
                    "completeness",
                ),
            )
            for r in state["results"]
        ],
        "recent": [
            pick(
                p,
                (
                    "station_timestamp",
                    "station_name",
                    "station_id",
                    "role",
                    "participant_id",
                    "start_number",
                    "first_name",
                    "last_name",
                    "category",
                    "status",
                ),
            )
            for p in state["recent"][:12]
        ],
        "running": sum(r["status"] == "RUNNING" for r in state["results"]),
        "stations_active": sum(
            bool(s.get("punch_count")) for s in state["stations"] if s["enabled"]
        ),
        "stations_enabled": sum(bool(s["enabled"]) for s in state["stations"]),
    }


def master_summary(service: LiveService) -> dict[str, Any]:
    db = service.repo.db
    return {
        "runners": [
            dict(r)
            for r in db.execute(
                "SELECT e.runner_id AS id,COUNT(*) AS count,MAX(v.date) AS last_date FROM live_entries e JOIN live_events v ON v.id=e.event_id GROUP BY e.runner_id"
            )
        ],
        "clubs": [
            dict(r)
            for r in db.execute(
                "SELECT club_id AS id,COUNT(*) AS count FROM live_runners WHERE club_id IS NOT NULL GROUP BY club_id"
            )
        ],
        "categories": [
            dict(r)
            for r in db.execute(
                "SELECT category_id AS id,COUNT(*) AS count FROM live_event_categories GROUP BY category_id"
            )
        ],
    }


def runner_history(service: LiveService, runner_id: int) -> list[dict[str, Any]]:
    service.repo.runner(runner_id)
    return [
        dict(r)
        for r in service.repo.db.execute(
            "SELECT e.*,v.name AS event_name,v.date AS event_date,c.code,c.display_name_en,c.display_name_de "
            "FROM live_entries e JOIN live_events v ON v.id=e.event_id JOIN live_event_categories c "
            "ON c.event_id=e.event_id AND c.category_id=e.category_id WHERE e.runner_id=? ORDER BY v.date DESC,e.id DESC",
            (runner_id,),
        )
    ]
