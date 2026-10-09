"""FoxSuite Control Center and persistent operator settings on the shared HTTP server."""

import asyncio
import json
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from foxbridge.cli import validate_output
from foxbridge.config import BridgeConfig
from foxbridge.mapping import MappingRepository, Role
from foxbridge.persistence import DeliveryRepository
from foxlive.models import Model
from foxlive.web import Runtime
from foxlive.web import create_app as live_app

from . import data, i18n, native, ports
from .files import sync_file
from .runtime import FoxSuiteRuntime
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


class BridgeInput(Model):
    enabled: bool = False
    target: str = Field(default="fjww", min_length=1, max_length=100)
    output_type: Literal["serial", "file"] = "serial"
    port: str = Field(default="", max_length=300)
    baud_rate: int = Field(default=38400, ge=1, le=4000000)
    path: str = Field(default="", max_length=1000)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    week_counter: int = Field(default=0, ge=0, le=3)


class BridgeStateInput(Model):
    running: bool


class UIDInput(Model):
    uid: str = Field(min_length=1, max_length=64)


class UIDMappingInput(UIDInput):
    card_number: int = Field(ge=1, le=0xFFFFFF)


class StationInput(Model):
    station_id: int = Field(ge=0, le=65535)


class StationMappingInput(StationInput):
    control_code: int = Field(ge=1, le=1023)
    role: Role = Role.CONTROL


class Controller:
    def __init__(
        self, locations: Locations, settings: Settings, restart: Callable[[], None]
    ) -> None:
        self.locations, self.settings, self.restart = locations, settings, restart
        self.owner: Runtime | None = None
        self.supervisor: FoxSuiteRuntime | None = None
        self.lock = asyncio.Lock()
        self.pending: Callable[[], None] | None = None
        self.result: str | None = None
        self.restarting = False

    def runtime(self) -> Runtime:
        if self.owner is None:
            raise ValueError("FoxSuite is not started")
        return self.owner

    async def stop_source(self) -> None:
        await self.application().stop_source()

    def start_source(self) -> None:
        self.application().start_source(self.identity_confirmation())

    def application(self) -> FoxSuiteRuntime:
        if self.supervisor is None:
            raise ValueError("FoxSuite is not started")
        return self.supervisor

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
            try:
                return await self.application().probe(value.port, value.baud_rate, delay)
            finally:
                application = self.application()
                if application.source_task is None or application.source_task.done():
                    self.start_source()


def create_app(controller: Controller) -> FastAPI:
    settings = controller.settings
    app = live_app(
        settings.core.database_path,
        settings.core,
        settings.live,
        serial_enabled=False,
        runtime_factory=controller.runtime,
    )
    app.title = "FoxSuite"
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
        supervisor = FoxSuiteRuntime(controller.settings)
        controller.supervisor, controller.owner = supervisor, supervisor.owner
        application.state.supervisor = supervisor
        try:
            async with original(application):
                await supervisor.start(controller.identity_confirmation())
                yield
        finally:
            await supervisor.close()
            controller.owner, controller.supervisor = None, None

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def setup_redirect(request: Request, call_next: Any) -> Any:
        if not controller.settings.completed and request.url.path in {"/", "/live"}:
            return RedirectResponse("/setup")
        if controller.restarting and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse({"detail": "FoxSuite is restarting; wait for it to reconnect"}, 503)
        return await call_next(request)

    # Replace only the desktop landing route; all FoxLive routes/middleware stay on this app.
    app.router.routes = [
        route for route in app.router.routes if getattr(route, "path", None) != "/"
    ]

    @app.get("/", response_class=HTMLResponse)
    async def control_center() -> HTMLResponse:
        return HTMLResponse((assets / "control.html").read_text(encoding="utf-8"))

    @app.get("/api/ops/status")
    async def runtime_status() -> dict[str, Any]:
        return controller.application().status() | {
            "system": {
                "database": str(controller.settings.core.database_path),
                "settings": str(controller.locations.settings),
                "logs": str(controller.locations.logs),
                "backups": str(controller.locations.backups),
                "override": controller.settings.override,
                "language": controller.settings.language,
                "restarting": controller.restarting,
                "last_operation": controller.result,
            },
            "identity_confirmation": controller.identity_confirmation(),
        }

    @app.get("/api/ops/diagnostics")
    async def diagnostics() -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in controller.runtime().store.db.execute(
                "SELECT id,created_at,kind,detail FROM diagnostics ORDER BY id DESC LIMIT 50"
            )
        ]

    @app.post("/api/ops/reconnect")
    async def reconnect_source() -> dict[str, bool]:
        async with controller.lock:
            if controller.restarting:
                raise ValueError("FoxSuite is restarting; wait for it to reconnect")
            await controller.stop_source()
            controller.start_source()
            return {"reconnecting": bool(controller.runtime().source_enabled)}

    @app.post("/api/ops/restart")
    async def restart_runtime() -> dict[str, bool]:
        async with controller.lock:
            if controller.restarting:
                raise ValueError("FoxSuite is restarting; wait for it to reconnect")
            controller.pending, controller.restarting = lambda: None, True
            asyncio.get_running_loop().call_later(0.3, controller.restart)
            return {"restarting": True}

    @app.get("/api/ops/bridge")
    async def bridge_settings() -> dict[str, Any]:
        config = controller.settings.bridge
        return {
            "enabled": config.enabled,
            "target": config.target,
            "output_type": config.output.type,
            "port": config.output.port,
            "baud_rate": config.output.baud_rate,
            "path": str(config.output.path)
            if config.output.path.is_absolute()
            else str(controller.settings.core.database_path.parent / "bridge-capture.bin"),
            "timezone": config.sportident.timezone,
            "week_counter": config.sportident.week_counter,
        }

    @app.get("/api/ops/bridge/deliveries")
    async def deliveries() -> list[dict[str, Any]]:
        return DeliveryRepository(controller.runtime().store).list_deliveries(
            controller.settings.bridge.target, 50
        )

    @app.get("/api/ops/bridge/mappings")
    async def mappings() -> dict[str, Any]:
        repository = MappingRepository(controller.runtime().store)
        return {
            "uids": [asdict(item) for item in repository.list_uids()],
            "stations": [asdict(item) for item in repository.list_stations()],
        }

    @app.post("/api/ops/bridge/mappings/uid")
    async def uid_mapping(value: UIDMappingInput) -> dict[str, Any]:
        async with controller.lock:
            controller.writable()
            return asdict(
                MappingRepository(controller.runtime().store).add_uid(value.uid, value.card_number)
            )

    @app.post("/api/ops/bridge/mappings/station")
    async def station_mapping(value: StationMappingInput) -> dict[str, Any]:
        async with controller.lock:
            controller.writable()
            return asdict(
                MappingRepository(controller.runtime().store).add_station(
                    value.station_id, value.control_code, value.role
                )
            )

    @app.post("/api/ops/bridge/mappings/uid/remove")
    async def remove_uid(value: UIDInput) -> dict[str, bool]:
        async with controller.lock:
            controller.writable()
            MappingRepository(controller.runtime().store).remove_uid(value.uid)
            return {"removed": True}

    @app.post("/api/ops/bridge/mappings/station/remove")
    async def remove_station(value: StationInput) -> dict[str, bool]:
        async with controller.lock:
            controller.writable()
            MappingRepository(controller.runtime().store).remove_station(value.station_id)
            return {"removed": True}

    @app.post("/api/ops/bridge")
    async def configure_bridge(value: BridgeInput) -> dict[str, bool]:
        async with controller.lock:
            controller.writable()
            previous = controller.settings.bridge
            config = BridgeConfig(
                enabled=value.enabled,
                target=value.target,
                queue_capacity=previous.queue_capacity,
                output=replace(
                    previous.output,
                    type=value.output_type,
                    port=value.port.strip(),
                    baud_rate=value.baud_rate,
                    path=Path(value.path) if value.path else previous.output.path,
                ),
                sportident=replace(
                    previous.sportident, timezone=value.timezone, week_counter=value.week_counter
                ),
            )
            if config.enabled or config.output.port or config.output.type == "file":
                validate_output(config, controller.settings.core)
            updated = replace(controller.settings, bridge=config)
            save(controller.locations, updated)
            controller.settings = updated
            await controller.application().configure(updated, controller.identity_confirmation())
            return {"saved": True}

    @app.post("/api/ops/bridge/state")
    async def bridge_state(value: BridgeStateInput) -> dict[str, bool]:
        async with controller.lock:
            if controller.restarting:
                raise ValueError("FoxSuite is restarting; wait for it to reconnect")
            config = replace(controller.settings.bridge, enabled=value.running)
            if value.running:
                if not controller.settings.completed:
                    raise ValueError("Complete first-run setup before starting FoxBridge")
                validate_output(config, controller.settings.core)
            updated = replace(controller.settings, bridge=config)
            if not updated.override:
                save(controller.locations, updated)
            controller.settings = updated
            application = controller.application()
            await application.stop_bridge()
            application.settings = updated
            application.bridge_error = None
            application.start_bridge()
            return {"running": value.running}

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
            if updated.bridge.enabled or updated.bridge.output.port:
                validate_output(updated.bridge, updated.core)
            if updated.live.port != controller.settings.live.port:
                from foxlive.cli import bind

                endpoint = bind(updated.live)  # Fail before saving if the destination is in use.
                endpoint.close()

                def apply() -> None:
                    save(controller.locations, updated)
                    controller.settings = updated

                controller.queue(apply)
                return {"restart": True, "url": f"http://{updated.live.host}:{updated.live.port}/"}
            save(controller.locations, updated)
            controller.settings = updated
            await controller.application().configure(updated, controller.identity_confirmation())
            app.state.operator_language = updated.language
            logging.getLogger().setLevel(updated.core.logging_level)
            atomic_write(
                controller.locations.root / "running.json",
                json.dumps(
                    {"host": updated.live.host, "port": updated.live.port, "path": "/"}
                ).encode(),
            )
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
                sync_file(archive)
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
        async with controller.lock:
            if controller.restarting:
                raise ValueError("FoxSuite is restarting; wait for it to reconnect")
            controller.pending, controller.restarting = lambda: None, True
            asyncio.get_running_loop().call_later(0.3, controller.restart)
            app.state.exit_requested = True
            return {"stopping": True}

    return app
