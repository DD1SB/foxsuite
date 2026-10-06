"""Local HTTP desk; all SQLite/domain calls execute on the lifespan owner loop."""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from foxcore.config import Config
from foxcore.errors import error_message
from foxcore.events import ConnectionEvent, TimeSyncEvent
from foxcore.logging import SafeLogger
from foxcore.persistence import Store
from foxcore.serial import SerialTransport
from foxcore.service import IngestService
from foxcore.timesync import TimeSyncService

from . import csvio
from .config import LiveConfig
from .models import (
    Category,
    CategoryData,
    Entry,
    EntryData,
    Event,
    EventData,
    Model,
    Result,
    State,
    Station,
    StationData,
)
from .persistence import LiveRepository
from .service import LiveService

log = SafeLogger(__name__)


class LifecycleInput(Model):
    state: State


class ExclusionInput(Model):
    reason: str = Field(min_length=1, max_length=1000)


class AssociationInput(Model):
    punch_ids: list[int] = Field(min_length=1, max_length=100000)


class CSVInput(Model):
    text: str = Field(max_length=2_000_000)
    commit: bool = False


class Hub:
    def __init__(self, capacity: int = 128) -> None:
        self.capacity = capacity
        self.clients: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.capacity)
        self.clients.add(queue)
        return queue

    def publish(self, kind: str, event_id: int | None, payload: dict[str, Any]) -> None:
        message = {"type": kind, "version": 1, "event_id": event_id, "payload": payload}
        for queue in tuple(self.clients):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(
                    {"type": "resync", "version": 1, "event_id": event_id, "payload": {}}
                )
            else:
                queue.put_nowait(message)


@dataclass
class Runtime:
    store: Store
    ingest: IngestService
    live: LiveService
    hub: Hub
    source_connected: bool | None = None


async def source(runtime: Runtime, core: Config) -> None:
    """Compose existing transport/TimeSync services, never another serial reader/parser."""
    transport = SerialTransport(core.serial)

    def record(event: TimeSyncEvent) -> None:
        runtime.store.diagnostic("timesync", json.dumps(asdict(event)))
        runtime.hub.publish("connection_changed", None, {"timesync": asdict(event)})

    sync = TimeSyncService(transport, core.time_sync, record)

    async def state(event: ConnectionEvent) -> None:
        runtime.source_connected = event.connected
        runtime.store.diagnostic("connection", json.dumps(asdict(event)))
        runtime.hub.publish("connection_changed", None, {"connection": asdict(event)})
        await sync.connection_changed(event)

    async def line(raw: bytes) -> None:
        runtime.ingest.ingest(raw, "serial:" + core.serial.port)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(transport.run(line, state))
            group.create_task(sync.wait_failure())
    except Exception as exc:
        runtime.live.failure = exc
        log.warning("ERROR FoxLive source stopped: %s", error_message(exc))
        runtime.hub.publish("connection_changed", None, {"error": error_message(exc)})
    finally:
        runtime.source_connected = False
        try:
            await sync.stop()
        except Exception as exc:
            runtime.live.failure = exc
            log.warning("ERROR FoxLive TimeSync stopped: %s", error_message(exc))
        finally:
            await transport.disconnect()


def create_app(
    path: Path,
    core: Config | None = None,
    config: LiveConfig | None = None,
    serial_enabled: bool = False,
) -> FastAPI:
    core, config = core or Config(), config or LiveConfig()
    runtime: Runtime | None = None
    assets = Path(__file__).parent
    templates = Environment(
        loader=FileSystemLoader(assets / "templates"), autoescape=select_autoescape(["html"])
    )

    def current() -> Runtime:
        if runtime is None:
            raise ValueError("FoxLive is not started")
        return runtime

    def snapshot(event_id: int | None = None) -> dict[str, Any]:
        owner = current()
        return owner.live.snapshot(event_id) | {
            "application": {
                "serial_enabled": serial_enabled,
                "source_port": core.serial.port,
                "source_connected": owner.source_connected,
                "time_sync_enabled": core.time_sync.enabled and serial_enabled,
            }
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime
        if serial_enabled and not core.serial.port:
            raise ValueError("Configure a FoxIdentServer serial port or use live run --no-serial")
        store = Store(path)
        task: asyncio.Task[None] | None = None
        try:
            hub = Hub()
            live = LiveService(LiveRepository(store), config.operator, hub.publish)
            ingest = IngestService(store, minimum_unix_timestamp=core.minimum_unix_timestamp)
            ingest.recover()
            live.recover()
            ingest.subscribe(live.accept)
            runtime = Runtime(store, ingest, live, hub)
            app.state.runtime = runtime
            log.info(
                "FoxLive started database=%s version=%s serial=%s",
                path,
                store.version,
                serial_enabled,
            )
            if serial_enabled:
                task = asyncio.create_task(source(runtime, core))
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            store.close()
            runtime = None
            log.info("FoxLive stopped")

    # No Swagger CDN dependencies: use the typed /openapi.json directly if needed.
    app = FastAPI(
        title="FoxLive",
        version="0.3.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]", config.host]
    if config.host in {"0.0.0.0", "::"}:
        allowed_hosts = ["*"]  # Explicit network exposure is documented as unsecured.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.mount("/static", StaticFiles(directory=assets / "static"), name="static")

    @app.middleware("http")
    async def same_origin(request: Request, call_next: Any) -> Response:
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse(
                    {"detail": "Cross-origin writes are not permitted"}, status_code=403
                )
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "Use application/json"}, status_code=415)
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(sqlite3.DatabaseError)
    async def storage_error(_request: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
        log.warning("ERROR FoxLive persistence failed: %s", exc)
        return JSONResponse(
            {"detail": "Persistence failure; check disk/permissions before continuing"},
            status_code=503,
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(templates.get_template("desk.html").render(snapshot=snapshot()))

    @app.get("/api/status")
    async def status(event_id: int | None = None) -> dict[str, Any]:
        return snapshot(event_id)

    @app.get("/api/events", response_model=list[Event])
    async def events() -> list[Event]:
        return current().live.repo.events()

    @app.post("/api/events", response_model=Event)
    async def create_event(data: EventData) -> Event:
        return current().live.put_event(data)

    @app.put("/api/events/{event_id}", response_model=Event)
    async def edit_event(event_id: int, data: EventData) -> Event:
        return current().live.put_event(data, event_id)

    @app.post("/api/events/{event_id}/state", response_model=Event)
    async def lifecycle(event_id: int, data: LifecycleInput) -> Event:
        return current().live.transition(event_id, data.state)

    @app.post("/api/events/{event_id}/recalculate")
    async def recalculate(event_id: int) -> dict[str, int]:
        return current().live.recalculate(event_id)

    @app.post("/api/events/{event_id}/associate")
    async def associate(event_id: int, data: AssociationInput) -> dict[str, int]:
        return current().live.associate(event_id, data.punch_ids)

    @app.get("/api/categories", response_model=list[Category])
    async def categories(event_id: int) -> list[Category]:
        current().live.repo.event(event_id)
        return current().live.repo.categories(event_id)

    @app.post("/api/events/{event_id}/categories", response_model=Category)
    async def create_category(event_id: int, data: CategoryData) -> Category:
        return current().live.put_category(event_id, data)

    @app.put("/api/events/{event_id}/categories/{category_id}", response_model=Category)
    async def edit_category(event_id: int, category_id: int, data: CategoryData) -> Category:
        return current().live.put_category(event_id, data, category_id)

    @app.get("/api/participants", response_model=list[Entry])
    async def entries(event_id: int) -> list[Entry]:
        current().live.repo.event(event_id)
        return current().live.repo.entries(event_id)

    @app.post("/api/events/{event_id}/participants", response_model=Entry)
    async def create_entry(event_id: int, data: EntryData) -> Entry:
        return current().live.put_entry(event_id, data)

    @app.put("/api/events/{event_id}/participants/{participant_id}", response_model=Entry)
    async def edit_entry(event_id: int, participant_id: int, data: EntryData) -> Entry:
        return current().live.put_entry(event_id, data, participant_id)

    @app.get("/api/events/{event_id}/participants/{participant_id}")
    async def entry_detail(event_id: int, participant_id: int) -> dict[str, Any]:
        service = current().live
        entry = next((e for e in service.repo.entries(event_id) if e.id == participant_id), None)
        if entry is None:
            raise ValueError("Participant does not exist in this event")
        result = next(
            r for r in service.repo.results(event_id) if r.participant_id == participant_id
        )
        return {
            "participant": entry.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "history": list(reversed(service.repo.recent(event_id, 100000, participant_id))),
        }

    @app.get("/api/stations")
    async def stations(event_id: int) -> list[dict[str, Any]]:
        return list(current().live.snapshot(event_id)["stations"])

    @app.put("/api/events/{event_id}/stations/{station_id}", response_model=Station)
    async def configure_station(event_id: int, station_id: int, data: StationData) -> Station:
        if station_id != data.station_id:
            raise ValueError("Station ID does not match path")
        return current().live.put_station(event_id, data)

    @app.get("/api/punches")
    async def punches(event_id: int, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Punch limit must be 1..1000")
        return current().live.repo.recent(event_id, limit)

    @app.get("/api/source-punches")
    async def source_punches(after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if after_id < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid source ID/limit")
        return [
            dict(r)
            for r in current().store.db.execute(
                "SELECT * FROM punches WHERE id>? ORDER BY id LIMIT ?", (after_id, limit)
            )
        ]

    @app.post("/api/events/{event_id}/punches/{punch_id}/exclude")
    async def exclude(event_id: int, punch_id: int, data: ExclusionInput) -> dict[str, int]:
        return current().live.exclude(event_id, punch_id, data.reason)

    @app.get("/api/rankings", response_model=list[Result])
    async def rankings(event_id: int) -> list[Result]:
        current().live.repo.event(event_id)
        return [Result.model_validate(r) for r in current().live.snapshot(event_id)["results"]]

    @app.get("/api/audit")
    async def audit(event_id: int) -> list[dict[str, Any]]:
        current().live.repo.event(event_id)
        return current().live.repo.audit(event_id)

    @app.post("/api/events/{event_id}/import")
    async def import_csv(event_id: int, data: CSVInput) -> dict[str, Any]:
        live = current().live
        return (
            csvio.import_participants(live, event_id, data.text)
            if data.commit
            else csvio.preview(live, event_id, data.text)
        )

    @app.get("/api/events/{event_id}/export/{kind}")
    async def export_csv(event_id: int, kind: str) -> Response:
        if kind not in {"participants", "results"}:
            raise ValueError("Export kind must be participants or results")
        return Response(
            csvio.export(current().live, event_id, kind == "results"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{kind}-{event_id}.csv"'},
        )

    @app.websocket("/ws")
    async def websocket(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if origin and urlparse(origin).netloc != socket.headers.get("host"):
            await socket.close(code=1008)
            return
        await socket.accept()
        runtime = current()
        queue = runtime.hub.subscribe()

        async def send() -> None:
            async with asyncio.timeout(5):
                await socket.send_json(
                    {"type": "snapshot", "version": 1, "event_id": None, "payload": snapshot()}
                )
            while True:
                message = await queue.get()
                async with asyncio.timeout(5):
                    await socket.send_json(message)

        async def receive() -> None:
            while True:
                await socket.receive_text()  # Read-only channel; ignore client commands.

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, OSError, TimeoutError, RuntimeError):
            pass
        finally:
            runtime.hub.clients.discard(queue)
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(
                    asyncio.CancelledError, WebSocketDisconnect, OSError, TimeoutError, RuntimeError
                ):
                    await task

    return app
