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

    monkeypatch.setattr("foxops.web.SerialTransport", transport)
    monkeypatch.setattr("foxlive.web.SerialTransport", transport)
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
