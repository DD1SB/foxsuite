"""Local operator setup/settings composed around the existing FoxLive lifespan."""

import asyncio
import json
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from foxcore.config import SerialConfig
from foxcore.events import ConnectionEvent, TimeSyncEvent
from foxcore.serial import SerialTransport
from foxcore.timesync import TimeSyncService
from foxlive.models import Model
from foxlive.web import Runtime, source
from foxlive.web import create_app as live_app

from . import data, i18n, native, ports
from .settings import Device, Locations, Settings, atomic_write, save, update


class SetupInput(Model):
    port: str = Field(min_length=1, max_length=300)
    language: Literal["en", "de"] = "en"
    http_port: int = Field(default=8765, ge=1024, le=65535)
    baud_rate: int = Field(default=115200, ge=1, le=4000000)
    time_sync: bool = True
    time_sync_interval: float = Field(default=60, gt=0, le=86400, allow_inf_nan=False)
    reconnect_interval: float = Field(default=2, gt=0, le=3600, allow_inf_nan=False)
    logging_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class ConnectionTestInput(Model):
    port: str = Field(min_length=1, max_length=300)
    baud_rate: int = Field(default=115200, ge=1, le=4000000)


class LocationInput(Model):
    directory: str = Field(min_length=1, max_length=1000)
    mode: Literal["copy", "move", "existing"]
    confirmed: bool = False


class RestoreInput(Model):
    name: str = Field(min_length=1, max_length=100)
    confirmed: bool = False


class Controller:
    def __init__(
        self, locations: Locations, settings: Settings, restart: Callable[[], None]
    ) -> None:
        self.locations, self.settings, self.restart = locations, settings, restart
        self.owner: Runtime | None = None
        self.task: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()
        self.pending: Callable[[], None] | None = None
        self.result: str | None = None
        self.restarting = False

    def runtime(self) -> Runtime:
        if self.owner is None:
            raise ValueError("FoxSuite is not started")
        return self.owner

    async def stop_source(self) -> None:
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.runtime().source_enabled = False

    def start_source(self) -> None:
        owner = self.runtime()
        owner.source_config = self.settings.core
        confirmation = self.identity_confirmation()
        owner.source_enabled = self.settings.completed and not confirmation
        if owner.source_enabled:
            self.task = asyncio.create_task(source(owner, self.settings.core))

    def identity_confirmation(self) -> bool:
        device = self.settings.device
        if device.vid is None or device.pid is None or not device.serial_number:
            return False
        choices = ports.enumerate_ports()
        matching = [
            port
            for port in choices
            if (port.device.vid, port.device.pid, port.device.serial_number)
            == (device.vid, device.pid, device.serial_number)
        ]
        return len(matching) != 1 or matching[0].port != self.settings.core.serial.port

    def writable(self) -> None:
        if self.settings.override:
            raise ValueError("Explicit configuration is read-only in desktop settings")
        if self.restarting:
            raise ValueError("FoxSuite is restarting; wait for it to reconnect")

    def queue(self, action: Callable[[], None]) -> None:
        self.writable()
        self.pending, self.restarting = action, True
        # Give the HTTP response a chance to reach the operator before graceful shutdown.
        asyncio.get_running_loop().call_later(0.3, self.restart)

    async def test(self, value: ConnectionTestInput, delay: float = 0.6) -> dict[str, Any]:
        """One bounded probe, preserving *all* received lines using the accepted reader."""
        async with self.lock:
            self.writable()
            await self.stop_source()
            owner = self.runtime()
            transport = SerialTransport(SerialConfig(value.port, value.baud_rate))
            sync = TimeSyncService(
                transport,
                self.settings.core.time_sync,
                lambda event: owner.store.diagnostic("timesync", json.dumps(event.__dict__)),
            )
            connected: asyncio.Future[ConnectionEvent] = asyncio.get_running_loop().create_future()
            first = owner.store.db.execute("SELECT COALESCE(MAX(id),0) FROM raw_events").fetchone()[
                0
            ]

            async def state(event: ConnectionEvent) -> None:
                if not connected.done():
                    connected.set_result(event)

            async def line(raw: bytes) -> None:
                owner.ingest.ingest(raw, "serial:" + value.port)

            task = asyncio.create_task(transport.run(line, state))
            try:
                connection = await asyncio.wait_for(asyncio.shield(connected), 5)
                if not connection.connected:
                    return {"opened": False, "time_sent": False, "detail": "port_unavailable"}
                await asyncio.sleep(delay)  # Board startup; reads continue during this wait.
                event: TimeSyncEvent = await sync.send_now()
                await asyncio.sleep(delay)
                if task.done():
                    task.result()  # Surface raw persistence failure, not a false success.
                observed = [
                    row[0]
                    for row in owner.store.db.execute(
                        "SELECT DISTINCT event_type FROM raw_events WHERE id>?", (first,)
                    )
                ]
                return {"opened": True, "time_sent": event.success, "observed_types": observed}
            except TimeoutError:
                return {"opened": False, "time_sent": False, "detail": "port_unavailable"}
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                await sync.stop()
                await transport.disconnect()
                self.start_source()


def create_app(controller: Controller) -> FastAPI:
    settings = controller.settings
    app = live_app(settings.core.database_path, settings.core, settings.live, serial_enabled=False)
    app.state.operations = True
    app.state.operator_language = settings.language
    app.state.controller = controller
    assets = Path(__file__).parent / "static"
    app.mount("/ops/static", StaticFiles(directory=assets), name="operations-assets")
    original = app.router.lifespan_context
    original_invalid = app.exception_handlers[ValueError]

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> Any:
        if str(exc) in i18n.ERRORS:
            return JSONResponse(
                {"detail": i18n.error_text(str(exc), request.headers.get("accept-language", "en"))},
                422,
            )
        handler = cast(Callable[[Request, ValueError], Any], original_invalid)
        return cast(Response, await handler(request, exc))

    @app.exception_handler(OSError)
    async def operation_error(request: Request, exc: OSError) -> JSONResponse:
        import logging

        logging.getLogger(__name__).error("Operator file operation failed: %s", exc)
        return JSONResponse(
            {
                "detail": i18n.catalog(request.headers.get("accept-language", "en"))[
                    "error.operation"
                ]
            },
            503,
        )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original(application):
            controller.owner = cast(Runtime, app.state.runtime)
            controller.start_source()
            try:
                yield
            finally:
                await controller.stop_source()
                controller.owner = None

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def setup_redirect(request: Request, call_next: Any) -> Any:
        if not controller.settings.completed and request.url.path in {"/", "/live"}:
            return RedirectResponse("/setup")
        if controller.restarting and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse({"detail": "FoxSuite is restarting; wait for it to reconnect"}, 503)
        return await call_next(request)

    @app.get("/setup", response_class=HTMLResponse)
    @app.get("/settings", response_class=HTMLResponse)
    async def page() -> HTMLResponse:
        return HTMLResponse((assets / "settings.html").read_text(encoding="utf-8"))

    @app.get("/api/ops/settings")
    async def status(request: Request) -> dict[str, Any]:
        current = controller.settings
        choices = ports.enumerate_ports()
        suggestion = ports.relocated(current.device, current.core.serial.port, choices)
        return {
            "completed": current.completed,
            "language": current.language,
            "override": current.override,
            "port": current.core.serial.port,
            "baud_rate": current.core.serial.baud_rate,
            "time_sync": current.core.time_sync.enabled,
            "time_sync_interval": current.core.time_sync.interval_seconds,
            "reconnect_interval": current.core.serial.reconnect_interval_seconds,
            "logging_level": current.core.logging_level,
            "http_port": current.live.port,
            "database": str(current.core.database_path),
            "data_directory": str(current.core.database_path.parent),
            "settings": str(controller.locations.settings),
            "logs": str(controller.locations.logs),
            "backups": str(controller.locations.backups),
            "ports": [port.json() for port in choices],
            "suggestion": suggestion.json() if suggestion else None,
            "identity_confirmation": controller.identity_confirmation(),
            "last_operation": i18n.error_text(
                controller.result, request.headers.get("accept-language", "en")
            )
            if controller.result
            else None,
            "free_bytes": shutil.disk_usage(current.core.database_path.parent).free,
        }

    @app.post("/api/ops/test")
    async def test(value: ConnectionTestInput) -> dict[str, Any]:
        return await controller.test(value)

    @app.post("/api/ops/browse")
    async def browse() -> dict[str, str | None]:
        controller.writable()
        return {"directory": await asyncio.to_thread(native.browse_folder)}

    @app.post("/api/ops/settings")
    async def configure(value: SetupInput) -> dict[str, Any]:
        async with controller.lock:
            controller.writable()
            choices = ports.enumerate_ports()
            selected = next((port for port in choices if port.port == value.port), None)
            # Manually configured advanced ports may not currently be attached.
            device = (
                selected.device
                if selected
                else controller.settings.device
                if value.port == controller.settings.core.serial.port
                else Device()
            )
            updated = update(controller.settings, **value.model_dump(), device=device)
            if updated.live.port != controller.settings.live.port:
                from foxlive.cli import bind

                endpoint = bind(updated.live)  # Fail before saving if the destination is in use.
                endpoint.close()

                def apply() -> None:
                    save(controller.locations, updated)
                    controller.settings = updated

                controller.queue(apply)
                return {"restart": True, "url": f"http://{updated.live.host}:{updated.live.port}/"}
            await controller.stop_source()
            try:
                save(controller.locations, updated)
                controller.settings = updated
                app.state.operator_language = updated.language
                logging.getLogger().setLevel(updated.core.logging_level)
                atomic_write(
                    controller.locations.root / "running.json",
                    json.dumps(
                        {"host": updated.live.host, "port": updated.live.port, "path": "/"}
                    ).encode(),
                )
            finally:
                controller.start_source()
            return {"restart": False, "url": "/"}

    @app.post("/api/ops/backup")
    async def backup() -> dict[str, str]:
        async with controller.lock:
            controller.writable()
            path = data.backup(
                controller.runtime().store, controller.locations, controller.settings
            )
            return {"name": path.name}

    @app.get("/api/ops/backups")
    async def backups() -> list[dict[str, Any]]:
        return [
            {"name": path.name, "size": path.stat().st_size}
            for path in sorted(controller.locations.backups.glob("*.foxbackup"), reverse=True)
            if path.is_file() and not path.is_symlink()
        ]

    def backup_path(name: str) -> Path:
        path = controller.locations.backups / name
        if (
            Path(name).name != name
            or not name.endswith(".foxbackup")
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ValueError("Choose an existing FoxSuite backup")
        return path

    @app.get("/api/ops/backups/{name}")
    async def download(name: str) -> FileResponse:
        return FileResponse(backup_path(name), filename=name, media_type="application/zip")

    @app.post("/api/ops/restore")
    async def restore(value: RestoreInput) -> dict[str, bool]:
        async with controller.lock:
            if not value.confirmed:
                raise ValueError("Confirm restore; current competition data will be replaced")
            path = backup_path(value.name)
            # Validate now as well as after shutdown so invalid requests do not interrupt the desk.
            with tempfile.TemporaryDirectory(
                prefix=".validate-", dir=controller.locations.backups
            ) as folder:
                data.unpack(path, Path(folder) / "foxsuite.db")
            controller.queue(lambda: data.restore(controller.locations, controller.settings, path))
            return {"restart": True}

    @app.post("/api/ops/import")
    async def import_backup(request: Request) -> dict[str, str]:
        controller.writable()
        # A browser File upload; no multipart framework and no client-controlled filename/path.
        async with controller.lock:
            with tempfile.TemporaryDirectory(
                prefix=".import-", dir=controller.locations.backups
            ) as folder:
                archive = Path(folder) / "upload"
                length = 0
                with archive.open("wb") as stream:
                    async for chunk in request.stream():
                        length += len(chunk)
                        if length > 512 * 1024**2:
                            raise ValueError("Backup is too large")
                        stream.write(chunk)
                data.unpack(archive, Path(folder) / "foxsuite.db")
                from uuid import uuid4

                name = "import-" + uuid4().hex + ".foxbackup"
                archive.replace(controller.locations.backups / name)
            return {"name": name}

    @app.post("/api/ops/location")
    async def location(value: LocationInput) -> dict[str, bool]:
        async with controller.lock:
            if not value.confirmed:
                raise ValueError("Confirm the data-location change")

            def apply() -> None:
                controller.settings = data.change_location(
                    controller.locations, controller.settings, Path(value.directory), value.mode
                )

            controller.queue(apply)
            return {"restart": True}

    @app.post("/api/ops/shutdown")
    async def shutdown() -> dict[str, bool]:
        # Shutdown does not change settings and must work with an explicit override too.
        if controller.restarting:
            raise ValueError("FoxSuite is restarting; wait for it to reconnect")
        controller.pending, controller.restarting = lambda: None, True
        asyncio.get_running_loop().call_later(0.3, controller.restart)
        app.state.exit_requested = True
        return {"stopping": True}

    return app
