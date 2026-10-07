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
            page = browser.new_page(locale="en-US", timezone_id="Europe/Berlin", base_url=base)
            page.goto(base)
            page.wait_for_function(
                "() => document.querySelector('#connection').textContent.includes('Connected')"
            )
            sequence = 0

            def punch(uid: str) -> None:
                nonlocal sequence
                sequence += 1
                raw = json.dumps(
                    {
                        "type": "tag",
                        "station": 1,
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
    page.locator('#event-form [name="default_start_at"]').fill(
        datetime.fromtimestamp(time.time() - 60, ZoneInfo("Europe/Berlin")).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    )
    page.locator("#event-form button").first.click()
    page.wait_for_function("() => document.querySelector('#event-form').dataset.entityId")


def category_and_participant(page: Any) -> None:
    page.locator('#master-category-form [name="code"]').fill("M40")
    page.locator('#master-category-form [name="display_name_en"]').fill("Men 40")
    page.locator('#master-category-form [name="display_name_de"]').fill("Männer 40")
    page.locator("#master-category-form button").first.click()
    page.wait_for_function(
        "() => document.querySelector('#category-form [name=category_id]').options.length === 2"
    )
    page.locator('#category-form [name="category_id"]').select_option(label="M40 – Men 40")
    page.locator("#category-form button").first.click()
    page.wait_for_function(
        "() => document.querySelector('#participant-form [name=category_id]').options.length === 2"
    )
    page.locator('#participant-form [name="start_number"]').fill("17")
    page.locator("#create-runner").click()
    page.locator('#participant-form [data-person="first_name"]').fill("Max")
    page.locator('#participant-form [data-person="last_name"]').fill("Müller")
    page.locator('#participant-form [data-person="birth_year"]').fill("1980")
    page.locator('#participant-form [name="category_id"]').select_option(label="M40 – Men 40")


def test_browser_language_and_rfid_create_confirm_history_collision(
    desk: tuple[Any, str, Callable[[str], None]],
) -> None:
    page, _, punch = desk
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator('#event-form [name="timezone"]').input_value() == "Europe/Berlin"
    save_event(page)
    category_and_participant(page)
    assert "M40 – Men 40" in page.locator('#participant-form [name="category_id"]').inner_text()
    page.locator('#station-form [name="station_id"]').fill("1")
    page.locator('#station-form [name="display_name"]').fill("Fox 1")
    page.locator("#station-form button").click()
    page.locator('[data-state="RUNNING"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Running')"
    )
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
    page.locator("#language").select_option("de")
    assert page.locator("html").get_attribute("lang") == "de"
    assert "Startnummer" in page.locator("#participant-form").inner_text()
    assert "M40 – Männer 40" in page.locator('#participant-form [name="category_id"]').inner_text()
    assert "Fuchs" in page.locator('#station-form [name="role"]').inner_text()
    assert "RFID-Tag einlesen" in page.locator("#read-tag").inner_text()
    page.reload()
    page.wait_for_function("() => document.documentElement.lang === 'de'")
    page.locator("#language").select_option("en")
    assert "Start number" in page.locator("#participant-form").inner_text()
    page.reload()
    page.wait_for_function("() => document.documentElement.lang === 'en'")
    page.locator("#language").select_option("de")
    page.locator('#participant-form [name="start_number"]').fill("18")
    page.locator("#create-runner").click()
    page.locator('#participant-form [data-person="first_name"]').fill("Anna")
    page.locator('#participant-form [data-person="last_name"]').fill("Meyer")
    page.locator('#participant-form [data-person="birth_year"]').fill("1980")
    page.locator('#participant-form [name="category_id"]').select_option(label="M40 – Männer 40")
    page.locator("#participant-form details").first.locator("summary").click()
    page.locator('#participant-form [name="uid"]').fill("046365525C6180")
    page.get_by_role("button", name="Teilnehmer speichern", exact=True).click()
    page.wait_for_function("() => !document.querySelector('#error').hidden")
    assert "Startnummer 17" in page.locator("#error").inner_text()
    page.locator("#language").select_option("en")
    assert "start number 17" in page.locator("#error").inner_text()
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
    assert "25.10.2026" in page.locator("#event-form [data-time-caption]").first.inner_text()
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
    page.locator('#club-form [name="code"]').fill("P01")
    page.locator('#club-form [name="display_name"]').fill("Ortsverband Test")
    page.locator("#club-form button").first.click()
    page.wait_for_function(
        "() => document.querySelector('#participant-form [data-person=club_id]').options.length === 2"
    )
    save_event(page)
    category_and_participant(page)
    page.locator('#participant-form [data-person="club_id"]').select_option(
        label="P01 – Ortsverband Test"
    )
    page.get_by_role("button", name="Save participant", exact=True).click()
    page.wait_for_function(
        "() => !document.querySelector('#participant-form').dataset.saving && document.querySelector('#participant-form').dataset.entityId"
    )
    first = page.request.get("/api/participants?event_id=1").json()[0]
    page.reload()
    page.locator('[data-edit-participant="1"]').click()
    assert page.locator("#runner-choice").input_value() == str(first["runner_id"])
    assert "1980" in page.locator("#runner-choice").inner_text()
    assert "P01" in page.locator("#runner-choice").inner_text()
    page.locator('#participant-form [name="checked_in"]').check()
    page.get_by_role("button", name="Save participant", exact=True).click()
    page.wait_for_function("() => !document.querySelector('#participant-form').dataset.saving")
    page.locator('[data-state="RUNNING"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Running')"
    )
    page.locator('[data-state="CLOSED"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Closed')"
    )
    page.locator("#new-event").click()
    save_event(page)
    page.wait_for_function("() => document.querySelector('#event-select').value === '2'")
    page.locator('#category-form [name="category_id"]').select_option(label="M40 – Men 40")
    page.locator("#category-form button").first.click()
    page.wait_for_function(
        "() => document.querySelector('#participant-form [name=category_id]').options.length === 2"
    )
    page.locator('#station-form [name="station_id"]').fill("1")
    page.locator('#station-form [name="display_name"]').fill("Fox 1")
    page.locator("#station-form button").click()
    page.locator('[data-state="RUNNING"]').click()
    page.wait_for_function(
        "() => document.querySelector('#event-state').textContent.includes('Running')"
    )
    punch("04CC")
    page.locator("[data-register-tag]").first.click()
    page.locator("#runner-search").fill("Müller 1980 P01")
    page.locator("#runner-choice").select_option(label="Max Müller · 1980 · P01 – Ortsverband Test")
    page.locator('#participant-form [name="start_number"]').fill("42")
    page.locator('#participant-form [name="category_id"]').select_option(label="M40 – Men 40")
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
    page.locator("#language").select_option("de")
    assert "Teilnehmer melden" in page.locator("#participant-form").inner_text()
    assert "M40 – Männer 40" in page.locator("#participant-form [name=category_id]").inner_text()
    assert not errors
