import base64
import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_live_web import STAMP, UID, configure, receive, request

from foxlive.readout import capture, station_record
from foxlive.web import create_app


def prepare(client: TestClient) -> tuple[str, int]:
    event, _, entry = configure(client)
    root = f"/api/events/{event}"
    data = client.get("/api/events").json()[0]
    for key in ("id", "state", "cursor", "created_at", "updated_at"):
        data.pop(key)
    request(client, root, data | {"tag_event_id": 1825}, "PUT")
    participant = client.get(root + f"/participants/{entry}").json()["participant"]
    fields = {k: participant[k] for k in ("runner_id", "category_id", "start_number")}
    request(client, root + f"/participants/{entry}", fields | {"uid": UID}, "PUT")
    request(
        client,
        root + "/stations/2",
        {"station_id": 2, "display_name": "Fox 2", "role": "CONTROL"},
        "PUT",
    )
    return root, entry


def import_capture(
    client: TestClient, root: str, records: list[dict[str, Any]], uid: str = UID
) -> dict[str, Any]:
    return dict(
        request(client, root + "/readouts/import", {"payload": capture(uid, records).decode()})
    )


def test_readout_recovery_review_audit_export_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "m5.db"
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        live_id = receive(client, seconds=10)
        receive(client, station=11, seconds=60)
        raw_before = client.get("/api/source-punches").json()
        session = import_capture(
            client, root, [station_record(1, STAMP + 10, 1825), station_record(2, STAMP + 20, 1825)]
        )
        detail = client.get(root + f"/participants/{entry}").json()
        assert detail["result"]["controls"] == 2 and detail["result"]["recovered_controls"] == 1
        assert session["summary"] == {
            "controls_found": 2,
            "beacon_punched": False,
            "finish_punched": True,
            "live_controls": 1,
            "tag_controls": 2,
            "recovered": 1,
            "matches": 1,
            "open_reviews": 0,
        }
        import_capture(client, root, [station_record(1, STAMP + 15, 1825)])
        reviews = client.get(root + "/reviews").json()
        assert len(reviews) == 1 and reviews[0]["status"] == "OPEN"
        request(
            client,
            root + "/decisions",
            {
                "participant_id": entry,
                "station_id": 1,
                "action": "SELECT",
                "source_type": "LIVE",
                "source_id": live_id,
                "reason": "Marshal confirmed first visit",
                "operator": "Jury A",
            },
        )
        assert not client.get(root + "/reviews").json()
        assert client.get(root + "/reviews?include_resolved=true").json()[0]["status"] == "RESOLVED"
        exported = client.get(root + "/export/evidence").json()
        assert len(exported["readouts"]) == 2 and exported["decisions"][0]["operator"] == "Jury A"
        assert any(a["operator"] == "Jury A" and a["reason"] for a in exported["audit"])
        csv_rows = list(csv.DictReader(io.StringIO(client.get(root + "/export/results").text)))
        assert (
            csv_rows[0]["manual_decision"] == "True" and csv_rows[0]["completeness"] == "COMPLETE"
        )
        assert client.get("/api/source-punches").json() == raw_before
        results = client.get(root + f"/participants/{entry}").json()["result"]
    with TestClient(create_app(path), base_url="http://127.0.0.1") as client:
        assert client.get(root + f"/participants/{entry}").json()["result"] == results
        request(client, root + "/recalculate", {})
        assert client.get(root + f"/participants/{entry}").json()["result"] == results


def test_multiple_websockets_receive_readout_and_review_events(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "sockets.db"), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        live_id = receive(client)
        with (
            client.websocket_connect("ws://127.0.0.1/ws") as first,
            client.websocket_connect("ws://127.0.0.1/ws") as second,
        ):
            first.receive_json()
            second.receive_json()
            import_capture(client, root, [station_record(1, STAMP + 10, 1825)])
            for ws in (first, second):
                messages = [ws.receive_json() for _ in range(4)]
                assert {m["type"] for m in messages} == {
                    "review_case_created",
                    "ranking_changed",
                    "reconciliation_updated",
                    "tag_readout_completed",
                }
                assert all(m["version"] == 1 for m in messages)
            request(
                client,
                root + "/decisions",
                {
                    "participant_id": entry,
                    "station_id": 1,
                    "action": "SELECT",
                    "source_type": "LIVE",
                    "source_id": live_id,
                    "reason": "checked",
                },
            )
            for ws in (first, second):
                assert {ws.receive_json()["type"] for _ in range(3)} == {
                    "review_case_resolved",
                    "reconciliation_updated",
                    "ranking_changed",
                }


@pytest.mark.parametrize("workflow", ["entry", "runner", "new_runner"])
def test_unknown_readout_reuses_registration_workflows(tmp_path: Path, workflow: str) -> None:
    with TestClient(create_app(tmp_path / "unknown.db"), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        unknown = "04AABBCCDDEE11"
        session = import_capture(client, root, [station_record(2, STAMP + 2, 1825)], unknown)
        assert session["participant_id"] is None
        entry_data = client.get(root + f"/participants/{entry}").json()["participant"]
        if workflow == "entry":
            data = {k: entry_data[k] for k in ("runner_id", "start_number", "category_id")}
            request(client, root + f"/participants/{entry}", data | {"uid": unknown}, "PUT")
        else:
            registration = {
                "start_number": 18,
                "category_id": entry_data["category_id"],
                "uid": unknown,
            }
            runner = {"first_name": "Anna", "last_name": "Example", "birth_year": 1985}
            if workflow == "runner":
                runner_id = request(client, "/api/runners", runner)["id"]
                request(client, root + "/participants", registration | {"runner_id": runner_id})
            else:
                request(
                    client, root + "/register-new-runner", {"runner": runner, "entry": registration}
                )
        session_after = client.get(root + f"/readouts/{session['id']}").json()
        assert (
            session_after["participant_id"] is not None
            and session_after["summary"]["recovered"] == 1
        )
        assert len(client.get(root + "/readouts").json()) == 1
        assert client.get("/api/source-punches").json() == []


def test_localized_errors_and_manual_times(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "errors.db"), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        data = {"participant_id": entry, "station_id": 11, "action": "PRESENCE", "reason": "check"}
        result = client.post(root + "/decisions", json=data, headers={"Accept-Language": "de"})
        assert result.status_code == 422 and "nur bei Füchsen" in result.json()["detail"]
        for value in ["2026-10-25T02:30:00", "2026-03-29T02:30:00", "2026-10-06T12:00:00.123Z"]:
            result = client.post(
                root + "/decisions", json=data | {"action": "MANUAL", "timestamp": value}
            )
            assert result.status_code == 422
        result = request(
            client,
            root + "/decisions",
            data
            | {
                "action": "MANUAL",
                "timestamp": datetime.fromtimestamp(STAMP + 100, UTC).isoformat(),
            },
        )
        assert result["station_timestamp"] == STAMP + 100
        result = client.post(
            root + "/decisions", json=data | {"reason": "   "}, headers={"Accept-Language": "de"}
        )
        assert result.status_code == 422 and "Begründung" in result.json()["detail"]


def test_public_view_redacts_evidence_and_technical_details(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "public.db"), base_url="http://127.0.0.1") as client:
        root, _ = prepare(client)
        receive(client)
        import_capture(client, root, [station_record(1, STAMP + 2, 1825)])
        document = client.get("/api/display").text
        assert "REVIEW_REQUIRED" in document
        assert UID not in document and "raw_bytes" not in document and "source_id" not in document
        html = client.get("/live/display").text
        assert "review-form" not in html and "COM" not in html
        for section in ["readout", "reviews"]:
            assert client.get(f"/events/1/{section}").status_code == 200


def test_browser_simulator_and_partial_retry(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "sim.db"), base_url="http://127.0.0.1") as client:
        root, _ = prepare(client)
        data = {
            "uid": UID,
            "records": [
                {"file_id": 1, "timestamp": datetime.fromtimestamp(STAMP + 1, UTC).isoformat()}
            ],
            "scenario": "partial",
        }
        session = request(client, root + "/readouts/simulate", data)
        assert session["status"] == "PARTIAL" and session["summary"]["recovered"] == 1
        assert client.get(root + "/reviews").json()
        session = request(client, root + "/readouts/simulate", data | {"scenario": "valid"})
        assert session["status"] == "COMPLETE"
        assert not client.get(
            root + "/reviews"
        ).json()  # completed retry closes incomplete-session case


@pytest.mark.parametrize("status", ["DNS", "DNF", "DSQ"])
def test_reasoned_status_rulings_preserve_evidence(tmp_path: Path, status: str) -> None:
    with TestClient(create_app(tmp_path / "status.db"), base_url="http://127.0.0.1") as client:
        root, entry = prepare(client)
        receive(client)
        receive(client, station=11, seconds=20)
        source = client.get("/api/source-punches").json()
        request(
            client,
            root + f"/participants/{entry}/status",
            {"status": status, "reason": "Jury ruling", "operator": "Jury"},
        )
        result = client.get(root + f"/participants/{entry}").json()["result"]
        assert result["status"] == status and result["rank"] is None and result["controls"] == 1
        audit = client.get(root + "/export/evidence").json()["audit"]
        assert any(
            a["action"] == "status_adjudication" and a["reason"] == "Jury ruling" for a in audit
        )
        request(
            client,
            root + f"/participants/{entry}/status",
            {"status": None, "reason": "Ruling withdrawn"},
        )
        assert client.get(root + f"/participants/{entry}").json()["result"]["rank"] == 1
        assert client.get("/api/source-punches").json() == source


def test_binary_capture_preserved_exactly_and_exported_losslessly(tmp_path: Path) -> None:
    raw = b"\xff\xfe malformed capture\x00"
    with TestClient(create_app(tmp_path / "binary.db"), base_url="http://127.0.0.1") as client:
        root, _ = prepare(client)
        result = request(
            client, root + "/readouts/import", {"raw_base64": base64.b64encode(raw).decode()}
        )
        assert result["status"] == "FAILED"
        assert base64.b64decode(result["raw_payload_base64"]) == raw
        exported = client.get(root + "/export/evidence").json()
        assert base64.b64decode(exported["readouts"][0]["raw_payload_base64"]) == raw
