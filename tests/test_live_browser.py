"""Optional real-browser desk acceptance checks; no physical hardware or production APIs added."""

import asyncio
import importlib
import json
import os
import socket
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import uvicorn
from fastapi import Request
from starlette.responses import Response

from foxcore.config import Config, SerialConfig, TimeSyncConfig
from foxcore.serial import FakeTransport
from foxlive.web import create_app


@pytest.fixture
def desk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Any, str, Callable[[str], None]]]:
    if os.environ.get("FOXSUITE_BROWSER_TESTS") != "1":
        pytest.skip("Enable optional Playwright checks with FOXSUITE_BROWSER_TESTS=1")
    playwright = importlib.import_module("playwright.sync_api")
    transport = FakeTransport()
    monkeypatch.setattr("foxlive.web.SerialTransport", lambda config: transport)
    app = create_app(
        tmp_path / "browser.db",
        Config(serial=SerialConfig("FAKE"), time_sync=TimeSyncConfig(enabled=False)),
        serial_enabled=True,
    )
    loop: asyncio.AbstractEventLoop | None = None

    @app.middleware("http")
    async def owner(request: Request, call_next: Any) -> Response:
        nonlocal loop
        loop = asyncio.get_running_loop()
        response: Response = await call_next(request)
        return response

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        with playwright.sync_playwright() as tools:
            browser = tools.chromium.launch()
            base = f"http://127.0.0.1:{port}"
            context = browser.new_context(
                locale="en-US", timezone_id="Europe/Berlin", base_url=base
            )
            browser_errors: list[str] = []
            context.on(
                "page",
                lambda opened: opened.on("pageerror", lambda exc: browser_errors.append(str(exc))),
            )
            page = context.new_page()
            page.goto(base)
            page.wait_for_function(
                "() => document.querySelector('#connection').textContent.includes('Connected')"
            )
            sequence = 0

            def punch(uid: str, station: int = 1) -> None:
                nonlocal sequence
                sequence += 1
                raw = json.dumps(
                    {
                        "type": "tag",
                        "station": station,
                        "sequence": sequence,
                        "timestamp": int(time.time()),
                        "uid": uid,
                    }
                ).encode()
                assert loop is not None
                asyncio.run_coroutine_threadsafe(transport.input.put(raw), loop).result(timeout=5)
                page.wait_for_function(
                    "async count => (await (await fetch('/api/source-punches')).json()).length >= count",
                    arg=sequence,
                )

            try:
                yield page, base, punch
                assert not browser_errors, browser_errors
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def save_event(page: Any) -> None:
    page.locator('#event-form [name="name"]').fill("Herbstlauf")
    page.locator('#event-form [name="date"]').fill("2026-10-06")
    page.locator('#event-form [name="timing_mode"]').select_option("PREDEFINED_START")
    local = datetime.fromtimestamp(time.time() - 60, ZoneInfo("Europe/Berlin")).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    # HTML normalizes zero seconds away; Chromium's fill requires the canonical value.
    page.locator('#event-form [name="default_start_at"]').fill(
        local[:-3] if local.endswith(":00") else local
    )
    page.locator("#event-form button").first.click()
    page.wait_for_function("() => document.querySelector('#event-form').dataset.entityId")


def category_and_participant(page: Any) -> None:
    view(page, "participants")
    page.locator("#register-participant").click()
    page.locator("#registration-category-search").fill("M40")
    page.locator('[data-combo="registration-category"] [data-combo-create]').click()
    page.locator('[data-category="display_name_en"]').fill("Men 40")
    page.locator('[data-category="display_name_de"]').fill("Männer 40")
    page.locator("#create-enable-category").click()
    page.wait_for_function("() => !document.querySelector('#category-dialog').open")
    page.locator('#participant-form [name="start_number"]').fill("17")
    page.locator("#create-runner").click()
    page.locator('#participant-form [data-person="first_name"]').fill("Max")
    page.locator('#participant-form [data-person="last_name"]').fill("Müller")
    page.locator('#participant-form [data-person="birth_year"]').fill("1980")
    choose(page, "registration-category", "M40")


def choose(page: Any, combo: str, query: str) -> None:
    page.locator(f"#{combo}-search").fill(query)
    option = page.locator(f"#{combo}-suggestions [role=option]").first
    option.wait_for(state="visible")
    # Wait for the debounced search, not an old focus-time result.
    page.wait_for_timeout(150)
    page.locator(f"#{combo}-search").press("ArrowDown")
    page.locator(f"#{combo}-search").press("Enter")


def view(page: Any, name: str) -> None:
    # Explicit UI navigation replaces the old single-page CRUD layout.
    page.locator(f'[data-view-link="{name}"]').first.click()
    page.locator(f'[data-view="{name}"]').wait_for(state="visible")


def station_and_start(page: Any) -> None:
    view(page, "stations")
    page.locator('#station-form [name="station_id"]').fill("1")
    page.locator('#station-form [name="display_name"]').fill("Fox 1")
    page.locator("#station-form button").click()
    page.wait_for_function(
        "() => document.querySelector('#station-list').textContent.includes('Fox 1')"
    )
    view(page, "overview")
    page.locator('[data-state="RUNNING"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Running')"
    )


def test_browser_language_and_rfid_create_confirm_history_collision(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, punch = desk
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator('#event-form [name="timezone"]').input_value() == "Europe/Berlin"
    save_event(page)
    station_and_start(page)
    category_and_participant(page)
    assert "M40 – Men 40" in page.locator("#registration-category-search").input_value()
    punch("04BB")  # Old unknown tag must not be selected by the next-punch workflow.
    page.locator("#read-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#tag-status').textContent.includes('Waiting')"
    )
    punch("046365525C6180")
    page.wait_for_function("() => !document.querySelector('#confirm-tag').hidden")
    assert "046365525C6180" in page.locator("#tag-status").inner_text()
    assert "Fox 1" in page.locator("#tag-status").inner_text()
    assert page.request.get("/api/participants?event_id=1").json() == []
    page.once("dialog", lambda dialog: dialog.dismiss())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    assert page.request.get("/api/participants?event_id=1").json() == []
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    assert page.request.get("/api/participants?event_id=1").json()[0]["uid"] == "046365525C6180"
    assert page.request.get("/api/rankings?event_id=1").json()[0]["controls"] == 1
    assert len(page.request.get("/api/source-punches").json()) == 2
    page.locator("#close-registration").click()
    page.locator("#language").select_option("de")
    page.locator('[data-edit-participant="1"]').last.click()
    assert page.locator("html").get_attribute("lang") == "de"
    assert "Startnummer" in page.locator("#participant-form").inner_text()
    assert "M40 – Männer 40" in page.locator("#registration-category-search").input_value()
    assert "Fuchs" in page.locator('#station-form [name="role"]').inner_text()
    assert "RFID-Tag einlesen" in page.locator("#read-tag").inner_text()
    page.reload()
    page.wait_for_function("() => document.documentElement.lang === 'de'")
    page.locator("#language").select_option("en")
    page.locator('[data-edit-participant="1"]').last.click()
    assert "Start number" in page.locator("#participant-form").inner_text()
    page.reload()
    page.wait_for_function("() => document.documentElement.lang === 'en'")
    page.locator("#language").select_option("de")
    page.locator("#register-participant").click()
    page.locator('#participant-form [name="start_number"]').fill("18")
    page.locator("#create-runner").click()
    page.locator('#participant-form [data-person="first_name"]').fill("Anna")
    page.locator('#participant-form [data-person="last_name"]').fill("Meyer")
    page.locator('#participant-form [data-person="birth_year"]').fill("1980")
    choose(page, "registration-category", "M40")
    page.locator("#participant-form details").first.locator("summary").click()
    page.locator('#participant-form [name="uid"]').fill("046365525C6180")
    page.get_by_role("button", name="Teilnehmer speichern", exact=True).click()
    page.wait_for_function("() => !document.querySelector('#error').hidden")
    assert "Startnummer 17" in page.locator("#error").inner_text()
    page.locator("#close-registration").click()
    page.locator("#language").select_option("en")
    assert "start number 17" in page.locator("#error").inner_text()
    # Reopen the same draft by browser history without discarding its entered fields.
    page.evaluate("() => document.querySelector('#registration-dialog').showModal()")
    page.locator('#participant-form [name="uid"]').fill("")
    recent = page.locator("#recent-tags option").filter(has_text="04BB").get_attribute("value")
    page.locator("#recent-tags").select_option(recent)
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#participant-form').dataset.entityId === '2'"
    )
    assert page.request.get("/api/participants?event_id=1").json()[1]["uid"] == "04BB"
    assert len(page.request.get("/api/source-punches").json()) == 2
    assert not errors


def test_browser_inline_club_category_registration_and_explicit_cancel(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, _ = desk
    save_event(page)
    category_and_participant(page)
    page.locator("#registration-club-search").fill("S01")
    page.locator('[data-combo="registration-club"] [data-combo-create]').click()
    page.locator('[data-club="display_name"]').fill("DARC OV Schwerin")
    page.locator("#create-select-club").click()
    page.wait_for_function("() => !document.querySelector('#club-dialog').open")
    assert "S01" in page.locator("#registration-club-search").input_value()
    assert page.request.get("/api/clubs").json() == []  # Still staged, no orphan data.
    page.locator("#close-registration").click()
    assert page.request.get("/api/runners").json() == []
    assert page.request.get("/api/clubs").json() == []
    assert len(page.request.get("/api/master/categories").json()) == 1  # Explicit commit.
    page.locator("#register-participant").click()
    page.locator("#create-runner").click()
    for field_name, value in [
        ("first_name", "Anna"),
        ("last_name", "Example"),
        ("birth_year", "1991"),
    ]:
        page.locator(f'[data-person="{field_name}"]').fill(value)
    page.locator('#participant-form [name="start_number"]').fill("18")
    # Existing global category can be enabled without duplicate creation.
    page.request.post(
        "/api/master/categories",
        data={"code": "W35", "display_name_en": "Women 35", "display_name_de": "Frauen 35"},
    )
    page.wait_for_timeout(300)
    choose(page, "registration-category", "W35")
    page.locator("#enable-category").click()
    page.wait_for_function(
        "() => document.querySelector('#registration-category-search').value.includes('Women 35') && document.querySelector('#category-enable').hidden"
    )
    page.locator("#registration-club-search").fill("S01")
    page.locator('[data-combo="registration-club"] [data-combo-create]').click()
    page.locator('[data-club="display_name"]').fill("DARC OV Schwerin")
    page.locator("#create-select-club").click()
    page.wait_for_function("() => !document.querySelector('#club-dialog').open")
    page.locator("#save-registration").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    assert "/events/1/participants" in page.url
    club = page.request.get("/api/clubs").json()[0]
    runner = page.request.get("/api/runners").json()[0]
    entry = page.request.get("/api/participants?event_id=1").json()[0]
    assert runner["club_id"] == club["id"] and entry["club_code"] == "S01"
    assert entry["start_number"] == 18 and entry["category_id"] == 2
    page.locator("#close-registration").click()
    page.wait_for_function(
        "() => document.querySelector('#participant-list').textContent.includes('Anna Example')"
    )
    assert "Anna Example" in page.locator("#participant-list").inner_text()


def test_browser_duplicate_club_person_review_and_same_workflow(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, _ = desk
    save_event(page)
    category_and_participant(page)
    original = page.request.post(
        "/api/clubs", data={"code": "S01", "display_name": "DARC OV Schwerin"}
    ).json()
    existing = page.request.post(
        "/api/runners",
        data={
            "first_name": "Max",
            "last_name": "Müller",
            "birth_year": 1980,
            "club_id": original["id"],
        },
    ).json()
    page.wait_for_timeout(300)
    # Exact normalized code cannot be bypassed; choose existing in the dialog.
    page.locator("#registration-club-search").fill("s01")
    page.locator('[data-combo="registration-club"] [data-combo-create]').click()
    page.locator('[data-club="display_name"]').fill("Other name")
    page.locator("#create-select-club").click()
    page.locator("#club-matches").wait_for(state="visible")
    assert "already exists" in page.locator("#club-matches").inner_text()
    page.locator("[data-use-club]").click()
    assert "S01" in page.locator("#registration-club-search").input_value()
    assert len(page.request.get("/api/clubs").json()) == 1
    # A near match requires an explicit review/override, never an automatic merge.
    page.locator("#registration-club-search").fill("S10")
    page.locator('[data-combo="registration-club"] [data-combo-create]').click()
    page.locator('[data-club="display_name"]').fill("OV Schwerin")
    page.locator("#create-select-club").click()
    page.locator("#club-anyway").click()
    page.wait_for_function("() => !document.querySelector('#club-dialog').open")
    assert len(page.request.get("/api/clubs").json()) == 1
    page.locator("#save-registration").click()
    page.locator("#person-matches").wait_for(state="visible")
    assert "Possible existing runners" in page.locator("#person-matches").inner_text()
    page.locator("[data-use-runner]").click()
    assert "1980" in page.locator("#runner-search").input_value()
    page.locator("#save-registration").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    assert page.request.get("/api/participants?event_id=1").json()[0]["runner_id"] == existing["id"]
    assert len(page.request.get("/api/clubs").json()) == 1  # Discarded unused staged club.
    assert len(page.request.get("/api/runners").json()) == 1


def test_browser_keyboard_quick_create_and_distinct_same_named_runner(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, _ = desk
    save_event(page)
    category_and_participant(page)
    page.request.post(
        "/api/runners", data={"first_name": "Max", "last_name": "Müller", "birth_year": 1980}
    )
    # Keyboard Tab reaches the text-labeled create action, not an inaccessible popup.
    search = page.locator("#registration-club-search")
    search.fill("X99")
    page.locator('[data-combo="registration-club"] .suggestions').wait_for(state="visible")
    search.press("Tab")
    page.keyboard.press("Enter")
    page.locator("#club-dialog").wait_for(state="visible")
    page.locator('[data-club="display_name"]').fill("Distinct DX Association")
    page.locator("#create-select-club").click()
    page.wait_for_function("() => !document.querySelector('#club-dialog').open")
    page.locator("#save-registration").click()
    page.locator("#person-matches").wait_for(state="visible")
    page.locator("#runner-anyway").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    assert len(page.request.get("/api/runners").json()) == 2
    assert len(page.request.get("/api/clubs").json()) == 1
    page.locator("#close-registration").click()
    page.locator("#register-participant").click()
    # An immediate keyboard choice must filter fresh text, never select stale suggestions.
    search = page.locator("#runner-search")
    search.fill("Müller")
    search.press("ArrowDown")
    search.press("Enter")
    assert "Max Müller" in search.input_value()
    assert page.locator("#participant-form [name=runner_id]").input_value()
    choose(page, "registration-category", "M40")
    page.locator("#registration-category-search").fill("M40")
    page.locator("#registration-category-suggestions [role=option]").wait_for(state="visible")
    page.locator("#registration-category-suggestions [role=option]").click()
    assert page.locator("#participant-form [name=category_id]").input_value() == "1"


def test_browser_navigation_drafts_deep_links_and_history(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, base, _ = desk
    save_event(page)
    view(page, "participants")
    assert "No participants registered yet" in page.locator("#participant-list").inner_text()
    page.locator("#register-participant").click()
    page.locator('#participant-form [name="start_number"]').fill("23")
    page.locator("#close-registration").click()
    view(page, "overview")
    page.go_back()
    assert "/events/1/participants" in page.url
    assert page.locator('#participant-form [name="start_number"]').input_value() == "23"
    page.go_forward()
    assert page.locator('[data-view="overview"]').is_visible()
    view(page, "runners")
    assert page.locator('[data-view="participants"]').is_hidden()
    assert page.locator("#event-context").inner_text() == "Herbstlauf"
    view(page, "diagnostics")
    page.goto(base + "/events/1/participants")
    page.locator("#register-participant").wait_for(state="visible")
    assert page.locator("#event-context").inner_text() == "Herbstlauf"
    assert page.locator("input[name=id]").count() == 0
    assert page.locator("[name=runner_id]").get_attribute("type") == "hidden"
    assert page.locator("[name=category_id]").first.get_attribute("type") == "hidden"


def test_browser_display_multiple_windows_updates_reconnect_languages_and_privacy(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, base, punch = desk
    save_event(page)
    station_and_start(page)
    category_and_participant(page)
    page.locator("#read-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#tag-status').textContent.includes('Waiting')"
    )
    punch("046365525C6180")
    page.wait_for_function("() => !document.querySelector('#confirm-tag').hidden")
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    page.locator("#close-registration").click()
    view(page, "overview")
    with page.expect_popup() as popup:
        page.locator("#open-display").click()
    display = popup.value
    display.wait_for_function(
        "() => document.querySelector('#rankings').textContent.includes('Max Müller')"
    )
    assert "event_id=1" in display.url and "/events/1/overview" in page.url
    second = page.context.new_page()
    second.add_init_script(
        "window.testSockets=[]; const NativeWebSocket=WebSocket; window.WebSocket=class extends NativeWebSocket {constructor(...args){super(...args);window.testSockets.push(this);}};"
    )
    second.goto(base + "/live/display?event_id=1")
    second.wait_for_function(
        "() => document.querySelector('#rankings').textContent.includes('Max Müller')"
    )
    for client in (display, second):
        assert client.locator("form,input,a").count() == 0
        assert "046365525C6180" not in client.locator("body").inner_text()
        assert "FAKE" not in client.locator("body").inner_text()
        assert "Max Müller" in client.locator("#recent").inner_text()
        assert client.locator("#fullscreen").inner_text() == "Fullscreen"
    display.locator("#language").select_option("de")
    assert "Letzte Stempel" in display.locator("body").inner_text()
    assert "Männer 40" in display.locator("#rankings").inner_text()
    assert second.locator("html").get_attribute("lang") == "en"
    punch("04EE")
    for client in (display, second):
        client.wait_for_function(
            "() => document.querySelector('#recent').textContent.includes(document.documentElement.lang==='de'?'Unbekannter Teilnehmer':'Unknown participant')"
        )
        assert "04EE" not in client.locator("body").inner_text()
    second.evaluate("() => window.testSockets[0].close()")
    second.wait_for_function(
        "() => window.testSockets.length>1 && document.querySelector('#updates').textContent==='Connected'"
    )
    page.request.put(
        "/api/events/1/stations/11",
        data={"station_id": 11, "display_name": "Finish", "role": "FINISH"},
    )
    from typing import cast

    cast(Any, punch)("046365525C6180", 11)
    for client in (display, second):
        client.wait_for_function(
            "() => document.querySelector('#rankings').textContent.includes(document.documentElement.lang==='de'?'Im Ziel':'Finished')"
        )
        assert (
            client.locator("#rankings tbody")
            .first.locator("tr")
            .first.locator("td")
            .first.inner_text()
            == "1"
        )
    assert len(page.request.get("/api/source-punches").json()) == 3
    display.close()
    second.close()


def test_browser_bounded_autocomplete_and_tables_with_realistic_master_data(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, _ = desk
    save_event(page)
    for index in range(200):
        assert page.request.post(
            "/api/clubs", data={"code": f"C{index:03}", "display_name": f"Association {index:03}"}
        ).ok
    for index in range(50):
        assert page.request.post(
            "/api/events/1/quick-category",
            data={
                "code": f"CAT{index:02}",
                "display_name_en": f"Class {index}",
                "display_name_de": f"Klasse {index}",
            },
        ).ok
    csv = "start_number,first_name,last_name,birth_year,category,club_code,club\n" + "\n".join(
        f"{i + 1},Runner,Person{i:03},1980,CAT00,C{i % 200:03},Association {i % 200:03}"
        for i in range(500)
    )
    assert page.request.post("/api/events/1/import", data={"text": csv, "commit": True}).json()[
        "valid"
    ]
    view(page, "participants")
    page.wait_for_function(
        "() => document.querySelector('#participant-pages').textContent.includes('500 records')"
    )
    assert page.locator("#participant-list tbody tr").count() == 50
    page.locator("#participant-search").fill("Person499")
    assert page.locator("#participant-list tbody tr").count() == 1
    assert "Person499" in page.locator("#participant-list").inner_text()
    # Master search remains usable for a runner not already registered in the event.
    view(page, "overview")
    page.locator("#new-event").click()
    save_event(page)
    view(page, "participants")
    page.locator("#register-participant").click()
    page.locator("#runner-search").fill("Runner")
    page.wait_for_timeout(160)
    assert page.locator("#runner-suggestions [role=option]").count() == 20
    choose(page, "runner", "Person499 C099")
    assert "Person499" in page.locator("#runner-search").input_value()
    page.locator("#create-runner").click()
    choose(page, "registration-club", "C199")
    assert "Association 199" in page.locator("#registration-club-search").input_value()
    choose(page, "registration-category", "CAT49")
    page.locator("#enable-category").click()
    page.wait_for_function("() => document.querySelector('#category-enable').hidden")
    assert len(page.request.get("/api/master/categories").json()) == 50
    page.locator("#registration-category-search").fill("")
    page.wait_for_function(
        "() => document.querySelector('#registration-category-suggestions [role=option]')?.textContent.startsWith('CAT49')"
    )


def test_browser_read_tag_during_draft_registration(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, punch = desk
    save_event(page)
    category_and_participant(page)
    page.locator("#read-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#tag-status').textContent.includes('Waiting')"
    )
    punch("04AA")
    page.wait_for_function("() => !document.querySelector('#confirm-tag').hidden")
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    page.wait_for_function("() => document.querySelector('#participant-form').dataset.entityId")
    assert page.request.get("/api/participants?event_id=1").json()[0]["uid"] == "04AA"
    assert page.request.get("/api/punches?event_id=1").json() == []
    assert len(page.request.get("/api/source-punches").json()) == 1


def test_browser_native_times_preserve_instant_and_require_dst_choice(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, _ = desk
    page.locator("#event-form details summary").click()
    page.locator('#event-form [name="competition_start_at"]').fill("2026-10-25T02:30")
    page.locator('#event-form [name="name"]').fill("DST run")
    page.locator('#event-form [name="date"]').fill("2026-10-25")
    page.locator("#event-form button").first.click()
    choice = (
        page.locator('#event-form [name="competition_start_at"]')
        .locator("..")
        .locator("[data-time-choice]")
    )
    choice.wait_for(state="visible")
    assert "occurs twice" in page.locator("#error").inner_text()
    choice.select_option(index=2)
    page.locator("#event-form button").first.click()
    page.wait_for_function("() => document.querySelector('#event-form').dataset.entityId")
    saved = page.request.get("/api/events").json()[0]
    assert saved["competition_start_at"] == "2026-10-25T01:30:00+00:00"
    page.locator("#language").select_option("de")
    assert (
        "25.10.2026"
        in page.locator('#event-form [name="competition_start_at"]')
        .locator("..")
        .locator("[data-time-caption]")
        .inner_text()
    )
    assert (
        page.locator('#event-form [name="competition_start_at"]').input_value()
        == "2026-10-25T02:30"
    )
    page.locator("#event-form button").first.click()
    page.wait_for_function("() => document.querySelector('#error').hidden")
    page.wait_for_function("() => !document.querySelector('#event-form').dataset.saving")
    assert (
        page.request.get("/api/events").json()[0]["competition_start_at"]
        == saved["competition_start_at"]
    )
    page.locator('#event-form [name="competition_start_at"]').fill("2026-03-29T02:30")
    page.locator("#event-form button").first.click()
    page.wait_for_function("() => !document.querySelector('#error').hidden")
    assert "existiert" in page.locator("#error").inner_text()
    assert (
        page.request.get("/api/events").json()[0]["competition_start_at"]
        == saved["competition_start_at"]
    )


def test_browser_reusable_runner_club_category_and_unknown_registration(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, punch = desk
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    view(page, "runners")
    view(page, "clubs")
    page.locator('#club-form [name="code"]').fill("P01")
    page.locator('#club-form [name="display_name"]').fill("Ortsverband Test")
    page.locator("#club-form button").first.click()
    page.wait_for_function("() => document.querySelector('#club-list').textContent.includes('P01')")
    view(page, "overview")
    save_event(page)
    category_and_participant(page)
    choose(page, "registration-club", "P01")
    page.get_by_role("button", name="Save participant", exact=True).click()
    page.wait_for_function(
        "() => !document.querySelector('#participant-form').dataset.saving && document.querySelector('#participant-form').dataset.entityId"
    )
    first = page.request.get("/api/participants?event_id=1").json()[0]
    page.reload()
    page.locator('[data-edit-participant="1"]').last.click()
    assert page.locator("#participant-form [name=runner_id]").input_value() == str(
        first["runner_id"]
    )
    assert "1980" in page.locator("#runner-search").input_value()
    assert "P01" in page.locator("#runner-search").input_value()
    page.locator('#participant-form [name="checked_in"]').check()
    page.get_by_role("button", name="Save participant", exact=True).click()
    page.wait_for_function("() => !document.querySelector('#participant-form').dataset.saving")
    page.locator("#close-registration").click()
    view(page, "overview")
    page.locator('[data-state="RUNNING"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Running')"
    )
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator('[data-state="CLOSED"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Closed')"
    )
    page.locator("#new-event").click()
    save_event(page)
    page.wait_for_function("() => document.querySelector('#event-select').value === '2'")
    view(page, "categories")
    page.locator('[data-category-toggle="1"]').check()
    page.wait_for_function("() => document.querySelector('[data-category-toggle]').checked")
    station_and_start(page)
    view(page, "live")
    punch("04CC")
    page.locator("[data-register-tag]").first.click()
    choose(page, "runner", "Müller 1980 P01")
    page.locator('#participant-form [name="start_number"]').fill("42")
    choose(page, "registration-category", "M40")
    page.once("dialog", lambda dialog: dialog.accept())
    with page.expect_event("dialog"):
        page.locator("#confirm-tag").click()
    page.wait_for_function(
        "() => document.querySelector('#participant-form').dataset.entityId === '2'"
    )
    second = page.request.get("/api/participants?event_id=2").json()[0]
    assert second["runner_id"] == first["runner_id"] and second["uid"] == "04CC"
    assert second["start_number"] == 42 and second["checked_in"]
    assert page.request.get("/api/participants?event_id=1").json()[0]["uid"] is None
    assert page.request.get("/api/rankings?event_id=2").json()[0]["controls"] == 1
    assert len(page.request.get("/api/runners").json()) == 1
    assert len(page.request.get("/api/master/categories").json()) == 1
    assert len(page.request.get("/api/source-punches").json()) == 1
    page.locator("#close-registration").click()
    page.locator("#language").select_option("de")
    page.locator('[data-edit-participant="2"]').last.click()
    assert "Teilnehmer melden" in page.locator("#participant-form").inner_text()
    assert "M40 – Männer 40" in page.locator("#registration-category-search").input_value()
    assert not errors
