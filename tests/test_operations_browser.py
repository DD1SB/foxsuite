"""Actual Chromium first-run/settings checks (optional, same gate as the M3 desk)."""

import importlib
import os
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from foxcore.config import Config
from foxcore.serial import FakeTransport
from foxlive.config import LiveConfig
from foxops import ports
from foxops.settings import Device, Locations, Settings, load
from foxops.web import Controller, create_app


@pytest.fixture
def setup_desk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Controller]]:
    if os.environ.get("FOXSUITE_BROWSER_TESTS") != "1":
        pytest.skip("Enable optional Playwright checks with FOXSUITE_BROWSER_TESTS=1")
    playwright = importlib.import_module("playwright.sync_api")
    choices = [ports.Port("COM3", Device(12, 34, "XYZ", "USB Serial Device"))]
    monkeypatch.setattr(ports, "enumerate_ports", lambda: choices)

    def transport(config: Any) -> FakeTransport:
        fake = FakeTransport()
        fake.input.put_nowait(b'{"type":"time","timestamp":1791280800}\n')
        return fake

    monkeypatch.setattr("foxops.runtime.SerialTransport", transport)
    endpoint = socket.socket()
    endpoint.bind(("127.0.0.1", 0))
    endpoint.listen()
    port = endpoint.getsockname()[1]
    locations = Locations(tmp_path / "user")
    locations.create()
    controller = Controller(
        locations,
        Settings(
            Config(database_path=locations.database), LiveConfig(port=port, open_browser=False)
        ),
        lambda: None,
    )
    app = create_app(controller)
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
    thread = threading.Thread(target=lambda: server.run(sockets=[endpoint]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        with playwright.sync_playwright() as tools:
            browser = tools.chromium.launch()
            page = browser.new_page(base_url=f"http://127.0.0.1:{port}", locale="en-US")
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("/")
            try:
                page.wait_for_function("() => !document.querySelector('#next').disabled")
            except Exception:
                assert not errors, errors
                raise
            yield page, controller
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        endpoint.close()
        assert not thread.is_alive()


def finish(page: Any) -> None:
    page.locator("#next").click()
    page.locator("#port").select_option("COM3")
    page.locator("#next").click()
    page.locator("#test").click()
    page.wait_for_function(
        "() => document.querySelector('#test-result').textContent.includes('written successfully')"
    )
    page.locator("#next").click()
    page.locator("#next").click()
    page.locator("#finish").click()
    page.wait_for_url("**/")
    page.locator("#control-title").wait_for()
    page.locator("#open-live").click()
    page.locator('[data-view-link="diagnostics"]').wait_for()


def test_first_run_english_ports_test_and_finish(setup_desk: tuple[Any, Controller]) -> None:
    page, controller = setup_desk
    assert page.locator("#title").inner_text() == "First-run setup"
    assert not controller.settings.completed
    finish(page)
    assert load(controller.locations).completed
    assert load(controller.locations).device.serial_number == "XYZ"
    page.locator('[data-view-link="diagnostics"]').click()
    page.locator('[data-view-link="settings"]').click()
    page.locator('[data-view="settings"] a[href="/settings"]').click()
    page.locator("#backup").wait_for(state="visible")
    assert page.locator("#data-location").input_value() == str(controller.locations.database.parent)


def test_setup_language_switch_persistence_and_validation(
    setup_desk: tuple[Any, Controller],
) -> None:
    page, _ = setup_desk
    page.locator("#language").select_option("de")
    assert page.locator("#title").inner_text() == "Ersteinrichtung"
    page.reload()
    page.wait_for_function("() => document.documentElement.lang === 'de'")
    page.locator("#next").click()
    page.locator("#next").click()
    assert page.locator("#error").inner_text() == "FoxIdentServer-Anschluss auswählen"
    page.locator("#language").select_option("en")
    assert page.locator("#title").inner_text() == "First-run setup"
    assert page.evaluate("localStorage.getItem('foxlive.language')") == "en"


def test_graphical_backup_import_download_same_workflow(setup_desk: tuple[Any, Controller]) -> None:
    page, controller = setup_desk
    finish(page)
    page.goto("/settings")
    page.locator("#backup").click()
    page.wait_for_function("() => document.querySelector('#backups').options.length===1")
    with page.expect_download() as download:
        page.locator("#download").click()
    file = download.value.path()
    page.locator("#import-file").set_input_files(file)
    page.locator("#import-backup").click()
    page.wait_for_function("() => document.querySelector('#backups').options.length===2")
    assert len(list(controller.locations.backups.glob("*.foxbackup"))) == 2
    page.locator("#language").select_option("de")
    assert page.locator("#restore").inner_text() == "Ausgewählte Sicherung wiederherstellen"


def test_reidentified_device_requires_explicit_selection(
    setup_desk: tuple[Any, Controller], monkeypatch: pytest.MonkeyPatch
) -> None:
    page, controller = setup_desk
    controller.settings = replace(controller.settings, device=Device(12, 34, "XYZ", "USB"))
    monkeypatch.setattr(
        ports, "enumerate_ports", lambda: [ports.Port("COM5", Device(12, 34, "XYZ", "USB"))]
    )
    page.reload()
    page.locator("#next").click()
    page.locator("#use-suggestion").wait_for(state="visible")
    assert page.locator("#port").input_value() == ""
    page.locator("#use-suggestion").click()
    assert page.locator("#port").input_value() == "COM5"


def test_control_center_status_module_settings_and_navigation(
    setup_desk: tuple[Any, Controller], tmp_path: Path
) -> None:
    page, controller = setup_desk
    finish(page)
    page.goto("/")
    page.locator("#control-title").wait_for()
    page.locator("#source-state").get_by_text("Connected", exact=True).wait_for()
    assert page.locator("#source-state").inner_text() == "Connected"
    assert page.locator("#bridge-state").inner_text() == "Not configured"
    assert page.locator("#system-version").inner_text()
    page.locator("#language").select_option("de")
    assert page.locator("#control-title").inner_text() == "Kontrollzentrum"
    page.goto("/settings#bridge")
    page.locator("#bridge-save").wait_for(state="visible")
    page.locator("#bridge-type").select_option("file")
    page.locator("#bridge-path").fill(str(tmp_path / "bridge.bin"))
    page.locator("#bridge-enabled").check()
    page.locator("#bridge-save").click()
    page.wait_for_function(
        "() => document.querySelector('#message').textContent.includes('gespeichert')"
    )
    assert load(controller.locations).bridge.enabled
    page.locator("#mapping-uid").fill("046365525C6180")
    page.locator("#mapping-card").fill("912345")
    page.locator("#uid-map-form button").click()
    page.locator("#bridge-mappings").get_by_text("046365525C6180 → 912345").wait_for()
    page.locator("#mapping-station").fill("1")
    page.locator("#mapping-control").fill("31")
    page.locator("#station-map-form button").click()
    page.locator("#bridge-mappings").get_by_text("1 → 31 (CONTROL)").wait_for()
    page.goto("/")
    page.locator("#bridge-state").get_by_text("Läuft", exact=True).wait_for()
    page.locator("#bridge-toggle").click()
    page.locator("#bridge-state").get_by_text("Gestoppt", exact=True).wait_for()
    assert not load(controller.locations).bridge.enabled
    page.locator("#bridge-toggle").click()
    page.locator("#bridge-state").get_by_text("Läuft", exact=True).wait_for()
    page.locator("#reconnect").click()
    page.locator("#source-state").get_by_text("Verbunden", exact=True).wait_for()
    page.locator("#diagnostics").click()
    page.locator("#diagnostic-panel[open]").wait_for()
    assert page.locator("#diagnostic-panel").get_attribute("open") is not None
    assert "timesync" in page.locator("#diagnostic-entries").inner_text()
    page.locator("#open-live").click()
    page.locator("h1").get_by_text("FoxLive", exact=True).wait_for()
    page.locator('#top-nav a[href="/"]').click()
    page.locator("#control-title").get_by_text("Kontrollzentrum").wait_for()
