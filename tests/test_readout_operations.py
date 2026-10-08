import contextlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

from test_live_domain import STAMP, UID, setup

from foxcore.cli import main
from foxcore.persistence import Store
from foxcore.service import IngestService
from foxlive import csvio
from foxlive.models import EventData, Role, StationData, Timing
from foxlive.readout import capture, station_record


def test_cli_simulation_review_and_recalculation(tmp_path: Path) -> None:
    path = tmp_path / "cli.db"
    store, live, _, event, _ = setup(path, Timing.PREDEFINED_START)
    data = live.repo.event(event).model_dump(include=set(EventData.model_fields))
    live.put_event(EventData.model_validate(data | {"tag_event_id": 1825}), event)
    store.close()

    def run(arguments: list[str]) -> dict[str, object] | list[object]:
        stream = io.StringIO()
        with (
            patch.object(sys, "argv", ["foxsuite", "--db", str(path), "live", *arguments]),
            contextlib.redirect_stdout(stream),
        ):
            main()
        value: dict[str, object] | list[object] = json.loads(stream.getvalue())
        return value

    simulated = run(["readout", "simulate", str(event), UID, "--record", f"1:{STAMP + 1}"])
    assert isinstance(simulated, dict) and simulated["status"] == "COMPLETE"
    assert run(["review", "list", str(event)]) == []
    run(["reconcile", str(event)])
    path_capture = tmp_path / "capture.json"
    path_capture.write_bytes(capture(UID, [station_record(2, STAMP + 2, 99)]))
    run(["readout", "import", str(event), str(path_capture)])
    assert len(run(["review", "list", str(event)])) == 1
    run(["review", "resolve", str(event), "1", "2", "EXCLUDE", "--reason", "Old event on tag"])
    assert run(["review", "list", str(event)]) == []
    store = Store(path)
    assert store.stats()["punches"] == 0
    store.close()


def test_event_scale_bounded_snapshots_and_incremental_readouts(tmp_path: Path) -> None:
    store, live, _, event, _ = setup(tmp_path / "scale.db", Timing.PREDEFINED_START)
    data = live.repo.event(event).model_dump(include=set(EventData.model_fields))
    live.put_event(EventData.model_validate(data | {"tag_event_id": 1825}), event)
    for station in range(3, 8):
        live.put_station(
            event, StationData(station_id=station, display_name=f"Fox {station}", role=Role.CONTROL)
        )
    text = "start_number,first_name,last_name,category,uid,birth_year\n" + "".join(
        f"{number},Runner{number},Example,OPEN,{number:014X},1980\n" for number in range(2, 501)
    )
    assert csvio.import_participants(live, event, text)["count"] == 499
    ingest = IngestService(store)
    source_ids = []
    from datetime import UTC, datetime

    for entry in live.repo.entries(event):
        for station in range(1, 7):
            stamp = STAMP + station * 10
            raw = json.dumps(
                {
                    "type": "tag",
                    "station": station,
                    "timestamp": stamp,
                    "sequence": station,
                    "uid": entry.uid,
                }
            ).encode()
            punch = ingest.ingest(raw, "scale", datetime.fromtimestamp(stamp, UTC))
            assert punch is not None and punch.id is not None
            source_ids.append(punch.id)
    live.associate(event, source_ids)
    for entry in live.repo.entries(event)[:200]:
        assert entry.uid is not None
        live.evidence.import_raw(event, capture(entry.uid, [station_record(7, STAMP + 70, 1825)]))
    assert sum(r.recovered_controls for r in live.repo.results(event)) == 200
    queries: list[str] = []
    store.db.set_trace_callback(queries.append)
    state = live.snapshot(event)
    store.db.set_trace_callback(None)
    assert len(state["participants"]) == 500 and len(source_ids) == 3000
    assert len(state["readouts"]) == 20 and "raw_payload" not in state["readouts"][0]
    assert len(queries) < 25  # Bulk rendering, not one query per participant/readout.
    store.close()
