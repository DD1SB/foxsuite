"""Real Chromium M5 desk acceptance; acquisition is simulated, not physical."""

import json
import time
from datetime import UTC, datetime
from typing import Any

from test_live_browser import desk as desk

from foxlive.readout import capture, station_record

UID = "046365525C6180"


def configured(page: Any, uid: str | None = UID) -> tuple[int, int]:
    def post(path: str, data: dict[str, Any], method: str = "post") -> Any:
        response = getattr(page.request, method)(path, data=data)
        assert response.ok, response.text()
        return response.json()

    event = post(
        "/api/events",
        {
            "name": "Autumn recovery",
            "date": "2026-10-06",
            "timezone": "Europe/Berlin",
            "timing_mode": "PREDEFINED_START",
            "default_start_at": datetime.fromtimestamp(int(time.time()) - 60, UTC).isoformat(),
            "tag_event_id": 1825,
        },
    )["id"]
    category = post(
        "/api/master/categories",
        {"code": "M40", "display_name_en": "Men 40", "display_name_de": "Männer 40"},
    )["id"]
    post(f"/api/events/{event}/categories", {"category_id": category})
    runner = post(
        "/api/runners", {"first_name": "Max", "last_name": "Mustermann", "birth_year": 1984}
    )["id"]
    entry = post(
        f"/api/events/{event}/participants",
        {"runner_id": runner, "start_number": 17, "category_id": category, "uid": uid},
    )["id"]
    for station, role in [(1, "CONTROL"), (2, "CONTROL"), (11, "FINISH")]:
        post(
            f"/api/events/{event}/stations/{station}",
            {"station_id": station, "display_name": f"Fox {station}", "role": role},
            "put",
        )
    post(f"/api/events/{event}/state", {"state": "RUNNING"})
    page.goto(f"/events/{event}/readout")
    page.wait_for_function(
        "() => document.querySelector('#event-context').textContent==='Autumn recovery'"
    )
    page.wait_for_function("() => !document.querySelector('#readout-file').disabled")
    return event, entry


def upload(page: Any, records: list[dict[str, Any]], uid: str = UID) -> None:
    page.locator("#readout-file").set_input_files(
        {"name": "capture.json", "mimeType": "application/json", "buffer": capture(uid, records)}
    )
    page.wait_for_function("() => document.querySelector('#readout-file').value===''")


def test_finish_desk_recovery_conflict_decision_and_public_updates(desk: Any) -> None:
    page, base, punch = desk
    event, entry = configured(page)
    punch(UID, 1)
    punch(UID, 11)
    sources = page.request.get("/api/source-punches").json()
    stamp = sources[0]["station_timestamp"]
    public = page.context.new_page()
    public.goto(f"{base}/live/display?event_id={event}")
    public.wait_for_function(
        "() => document.querySelector('#rankings').textContent.includes('Mustermann')"
    )
    upload(page, [station_record(1, stamp, 1825), station_record(2, stamp, 1825)])
    page.wait_for_function(
        "() => document.querySelector('#readout-result').textContent.includes('Recovered: 1')"
    )
    page.wait_for_function(
        "() => document.querySelector('#readout-stats').textContent.includes('Readouts: 1')"
    )
    public.wait_for_function(
        "() => [...document.querySelectorAll('#rankings tbody tr')].some(r=>r.cells[2].textContent==='2')"
    )
    upload(page, [station_record(1, stamp + 15, 1825)])
    page.locator('#sub-nav [data-view-link="reviews"]').click()
    page.locator("#review-list [data-review]").click()
    page.locator('[data-select-evidence="0"]').click()
    page.locator('#review-form [name="reason"]').fill("Marshal confirmed the first visit")
    page.locator('#review-form [name="operator"]').fill("Finish jury")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('#review-form button[type="submit"], #review-form button:not([type])').click()
    page.wait_for_function(
        "() => !document.querySelector('#review-dialog').open && document.querySelector('#review-list').textContent.includes('No open review')"
    )
    public.wait_for_function(
        "() => !document.querySelector('#rankings').textContent.includes('Review required')"
    )
    result = page.request.get(f"/api/events/{event}/participants/{entry}").json()
    assert result["result"]["controls"] == 2 and result["result"]["manual_decision"]
    assert result["decisions"][0]["operator"] == "Finish jury"
    assert page.request.get("/api/source-punches").json() == sources
    public.reload()
    public.wait_for_function(
        "() => document.querySelector('#rankings').textContent.includes('Mustermann')"
    )
    assert UID not in public.locator("body").inner_text()
    public.close()


def test_unknown_readout_assigns_existing_registration_without_fake_sources(desk: Any) -> None:
    page, _, _ = desk
    event, entry = configured(page, None)
    upload(page, [station_record(2, int(time.time()), 1825)])
    # A completed import is actionable even before its snapshot invalidation arrives.
    page.evaluate("snapshot.readouts = []")
    page.locator("#readout-result [data-unknown-readout]").click()
    page.locator("#unknown-entry-search").fill("Max")
    page.locator('#unknown-entry-suggestions [role="option"]').first.click()
    page.locator("#use-existing-entry").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#confirm-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#assigned-tag').textContent.includes('046365525C6180')"
    )
    page.locator("#close-registration").click()
    page.locator('#sub-nav [data-view-link="readout"]').click()
    page.wait_for_function(
        "() => document.querySelector('#readout-result').textContent.includes('#17 Max Mustermann')"
    )
    detail = page.request.get(f"/api/events/{event}/participants/{entry}").json()
    assert detail["participant"]["uid"] == UID and detail["result"]["controls"] == 1
    assert page.request.get("/api/source-punches").json() == []
    page.locator("#language").select_option("de")
    assert page.locator("#sub-nav").inner_text().find("Auslesen / Ziel") >= 0
    assert "Ergänzt: 1" in page.locator("#readout-result").inner_text()
    assert "Prüffälle" in page.locator("#sub-nav").inner_text()
    page.locator("#language").select_option("en")
    assert "Recovered: 1" in page.locator("#readout-result").inner_text()


def test_simulator_ui_native_times_and_bilingual_evidence(desk: Any) -> None:
    page, _, _ = desk
    event, _ = configured(page)
    page.locator("details").filter(has=page.locator("#readout-simulate")).locator("summary").click()
    page.locator("#readout-participant").select_option(label="#17 Max Mustermann")
    page.locator('[data-read-file="2"]').check()
    page.locator("#readout-simulate button").click()
    page.wait_for_function(
        "() => document.querySelector('#readout-result').textContent.includes('Recovered: 1')"
    )
    page.wait_for_function(
        "() => document.querySelector('#readout-stats').textContent.includes('Readouts: 1')"
    )
    page.locator("#language").select_option("de")
    assert "Auslesungen: 1" in page.locator("#readout-stats").inner_text()
    page.locator("#readout-result [data-detail]").click()
    page.wait_for_function(
        "() => document.querySelector('#detail-body').textContent.includes('Vom RFID-Tag ergänzt')"
    )
    assert "RFID-Tag-Auslesung" in page.locator("#detail-body").inner_text()
    exported = json.loads(page.request.get(f"/api/events/{event}/export/evidence").text())
    assert exported["readouts"][0]["provider"] == "simulator"
