"""Local HTTP desk; all SQLite/domain calls execute on the lifespan owner loop."""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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
from foxcore.serial import SerialTransport, Transport
from foxcore.service import IngestService
from foxcore.timesync import TimeSyncService

from . import csvio, presentation, views
from .config import LiveConfig
from .evidence import DecisionInput, ReadoutInput, StatusDecisionInput
from .lookup import club_matches, runner_matches
from .models import (
    Category,
    CategoryData,
    Club,
    ClubData,
    Entry,
    EntryData,
    Event,
    EventCategoryData,
    EventData,
    MasterCategory,
    Model,
    RegistrationData,
    Result,
    Runner,
    RunnerData,
    State,
    Station,
    StationData,
)
from .persistence import LiveRepository
from .readout import capture, station_record
from .service import LiveService

log = SafeLogger(__name__)


class LifecycleInput(Model):
    state: State
    confirm_reviews: bool = False


class SimulationRecord(Model):
    file_id: int = Field(ge=0, le=255)
    timestamp: str


class SimulationInput(Model):
    uid: str
    records: list[SimulationRecord] = Field(max_length=256)
    scenario: str = "valid"


class ExclusionInput(Model):
    reason: str = Field(min_length=1, max_length=1000)


class AssociationInput(Model):
    punch_ids: list[int] = Field(min_length=1, max_length=100000)


class CSVInput(Model):
    text: str = Field(max_length=2_000_000)
    commit: bool = False


class LocalTimeInput(Model):
    value: str = Field(max_length=40)
    timezone: str = Field(max_length=100)


class NewRegistrationInput(Model):
    runner: RunnerData
    entry: RegistrationData
    club: ClubData | None = None
    allow_similar_club: bool = False


class QuickClubInput(Model):
    club: ClubData
    allow_similar: bool = False


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
    # Desktop operations own an optional source lifecycle; developer defaults are unchanged.
    source_config: Config | None = None
    source_enabled: bool | None = None
    source_health: dict[str, Any] = field(
        default_factory=lambda: {
            "state": "disconnected",
            "last_message": None,
            "last_error": None,
            "timesync": None,
        }
    )


async def source(runtime: Runtime, core: Config, transport: Transport | None = None) -> None:
    """Compose existing transport/TimeSync services, never another serial reader/parser."""
    transport = transport or SerialTransport(core.serial)
    runtime.source_health["state"] = "reconnecting"

    def record(event: TimeSyncEvent) -> None:
        runtime.store.diagnostic("timesync", json.dumps(asdict(event)))
        runtime.source_health["timesync"] = asdict(event) | {
            "recorded_at": datetime.now(UTC).isoformat()
        }
        runtime.hub.publish("connection_changed", None, {"timesync": asdict(event)})

    sync = TimeSyncService(transport, core.time_sync, record)

    async def state(event: ConnectionEvent) -> None:
        runtime.source_connected = event.connected
        runtime.source_health["state"] = "connected" if event.connected else "reconnecting"
        if not event.connected and event.detail != "shutdown":
            runtime.source_health["last_error"] = event.detail
        runtime.store.diagnostic("connection", json.dumps(asdict(event)))
        runtime.hub.publish("connection_changed", None, {"connection": asdict(event)})
        await sync.connection_changed(event)

    async def line(raw: bytes) -> None:
        runtime.ingest.ingest(raw, "serial:" + core.serial.port)
        runtime.source_health["last_message"] = datetime.now(UTC).isoformat()

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(transport.run(line, state))
            group.create_task(sync.wait_failure())
    except Exception as exc:
        runtime.source_health.update(state="error", last_error=error_message(exc))
        log.warning("ERROR FoxCore source stopped: %s", error_message(exc))
        runtime.hub.publish("connection_changed", None, {"error": error_message(exc)})
    finally:
        runtime.source_connected = False
        try:
            await sync.stop()
        except Exception as exc:
            runtime.source_health.update(state="error", last_error=error_message(exc))
            log.warning("ERROR FoxCore TimeSync stopped: %s", error_message(exc))
        finally:
            await transport.disconnect()
            if runtime.source_health["state"] != "error":
                runtime.source_health["state"] = "disconnected"


def create_runtime(
    path: Path, core: Config, config: LiveConfig, *, tolerate_live_failure: bool = False
) -> Runtime:
    """Construct the existing shared store/ingest/Live services on their owner loop."""
    store = Store(path)
    try:
        hub = Hub()
        live = LiveService(LiveRepository(store), config.operator, hub.publish)
        ingest = IngestService(store, minimum_unix_timestamp=core.minimum_unix_timestamp)
        ingest.recover()
        try:
            live.recover()
        except Exception as exc:
            if not tolerate_live_failure:
                raise
            live.failure = exc
            log.warning(
                "ERROR FoxLive recovery failed; FoxCore remains available: %s", error_message(exc)
            )
        ingest.subscribe(live.accept)
        return Runtime(store, ingest, live, hub)
    except BaseException:
        store.close()
        raise


def create_app(
    path: Path,
    core: Config | None = None,
    config: LiveConfig | None = None,
    serial_enabled: bool = False,
    runtime_factory: Callable[[], Runtime] | None = None,
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
        source_core = owner.source_config or core
        enabled = serial_enabled if owner.source_enabled is None else owner.source_enabled
        state = owner.live.snapshot(event_id)
        if not state["processing_error"] and owner.source_health["state"] == "error":
            state["processing_error"] = owner.source_health["last_error"]
        return state | {
            "application": {
                "serial_enabled": enabled,
                "source_port": source_core.serial.port,
                "source_connected": owner.source_connected,
                "time_sync_enabled": source_core.time_sync.enabled and enabled,
            }
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime
        if serial_enabled and not core.serial.port:
            raise ValueError("Configure a FoxIdentServer serial port or use live run --no-serial")
        task: asyncio.Task[None] | None = None
        try:
            if runtime_factory is not None and serial_enabled:
                raise ValueError("An externally owned runtime must own its serial lifecycle")
            runtime = runtime_factory() if runtime_factory else create_runtime(path, core, config)
            app.state.runtime = runtime
            log.info(
                "FoxLive started database=%s version=%s serial=%s",
                path,
                runtime.store.version,
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
            if runtime is not None and runtime_factory is None:
                runtime.store.close()
            runtime = None
            log.info("FoxLive stopped")

    # No Swagger CDN dependencies: use the typed /openapi.json directly if needed.
    app = FastAPI(
        title="FoxLive",
        version="0.5.0",
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
                    {
                        "detail": presentation.translate(
                            "error.cross_origin", request.headers.get("accept-language", "en")
                        )
                    },
                    status_code=403,
                )
            content_type = request.headers.get("content-type", "").split(";")[0]
            operations_upload = (
                getattr(app.state, "operations", False)
                and request.url.path == "/api/ops/import"
                and request.method == "POST"
                and content_type == "application/octet-stream"
            )
            if content_type != "application/json" and not operations_upload:
                return JSONResponse(
                    {
                        "detail": presentation.translate(
                            "error.json", request.headers.get("accept-language", "en")
                        )
                    },
                    status_code=415,
                )
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": presentation.error_text(
                    str(exc), request.headers.get("accept-language", "en")
                ),
                "ui_detail": {
                    lang: presentation.error_text(str(exc), lang, operator=True)
                    for lang in ("en", "de")
                },
            },
            status_code=422,
        )

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError) -> Response:
        lang = presentation.language(request.headers.get("accept-language", "en"))
        if lang == "en":
            response = await request_validation_exception_handler(request, exc)
            detail = json.loads(bytes(response.body))["detail"]
        else:
            detail = [
                {"loc": e["loc"], "type": e["type"], "msg": presentation.validation_text(e, lang)}
                for e in exc.errors()
            ]
        return JSONResponse(
            {
                "detail": detail,
                "ui_detail": {
                    code: [
                        {"loc": e["loc"], "msg": presentation.validation_text(e, code)}
                        for e in exc.errors()
                    ]
                    for code in ("en", "de")
                },
            },
            status_code=422,
        )

    @app.exception_handler(sqlite3.DatabaseError)
    async def storage_error(request: Request, exc: sqlite3.DatabaseError) -> JSONResponse:
        log.warning("ERROR FoxLive persistence failed: %s", exc)
        return JSONResponse(
            {
                "detail": presentation.translate(
                    "error.storage", request.headers.get("accept-language", "en")
                )
            },
            status_code=503,
        )

    @app.get("/", response_class=HTMLResponse)
    @app.get("/live", response_class=HTMLResponse)
    @app.get("/events/{event_id}/{section}", response_class=HTMLResponse)
    @app.get("/master/{section}", response_class=HTMLResponse)
    @app.get("/system/{section}", response_class=HTMLResponse)
    async def dashboard(event_id: int | None = None, section: str = "overview") -> HTMLResponse:
        return HTMLResponse(
            templates.get_template("desk.html").render(
                snapshot=snapshot(event_id),
                t=presentation.translate,
                operations=getattr(app.state, "operations", False),
                operator_language=getattr(app.state, "operator_language", "en"),
            )
        )

    @app.get("/live/display", response_class=HTMLResponse)
    async def live_display() -> HTMLResponse:
        return HTMLResponse(
            templates.get_template("display.html").render(
                t=presentation.translate,
                operator_language=getattr(app.state, "operator_language", "en"),
            )
        )

    @app.get("/api/display")
    async def display(event_id: int | None = None) -> dict[str, Any]:
        return views.display_state(current().live, event_id)

    @app.get("/api/ui/master-summary")
    async def master_summary() -> dict[str, Any]:
        return views.master_summary(current().live)

    @app.get("/api/runners/{runner_id}/history")
    async def runner_history(runner_id: int) -> list[dict[str, Any]]:
        return views.runner_history(current().live, runner_id)

    @app.post("/api/ui/club-matches")
    async def similar_clubs(data: ClubData) -> dict[str, list[Club]]:
        return club_matches(data, current().live.repo.clubs())

    @app.post("/api/ui/quick-club", response_model=Club)
    async def quick_club(data: QuickClubInput) -> Club:
        return current().live.quick_club(data.club, data.allow_similar)

    @app.post("/api/ui/runner-matches")
    async def similar_runners(data: RunnerData) -> list[Runner]:
        return runner_matches(data, current().live.repo.runners())

    @app.post("/api/events/{event_id}/quick-category", response_model=Category)
    async def quick_category(event_id: int, data: CategoryData) -> Category:
        return current().live.quick_category(event_id, data)

    @app.post("/api/ui/local-time")
    async def local_time(data: LocalTimeInput) -> dict[str, Any]:
        return {"options": presentation.local_time_options(data.value, data.timezone)}

    @app.get("/api/events/{event_id}/rfid-candidates")
    async def tags(event_id: int, after_id: int | None = None, limit: int = 20) -> dict[str, Any]:
        return presentation.rfid_candidates(current().live.repo, event_id, after_id, limit)

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
        return current().live.transition(event_id, data.state, data.confirm_reviews)

    @app.post("/api/events/{event_id}/readouts/import")
    async def import_readout(event_id: int, data: ReadoutInput) -> dict[str, Any]:
        return current().live.evidence.import_raw(event_id, data.raw(), "browser-import")

    @app.post("/api/events/{event_id}/readouts/simulate")
    async def simulate_readout(event_id: int, data: SimulationInput) -> dict[str, Any]:
        from foxcore.protocol import normalize_uid

        from .models import instant, unix

        event = current().live.repo.event(event_id)
        uid = normalize_uid(data.uid)
        if event.tag_event_id is None:
            raise ValueError("Configure the event tag ID before simulating a readout")
        if data.scenario not in {
            "valid",
            "empty",
            "wrong_event",
            "unsynchronized",
            "malformed",
            "partial",
            "aborted",
            "failed",
        }:
            raise ValueError("Unsupported readout scenario")
        records = []
        for record in data.records:
            stamp = unix(instant(record.timestamp, event.timezone))
            if stamp is None or not 0 <= stamp <= 4294967295:
                raise ValueError("Manual time fails event timestamp validation")
            records.append(
                station_record(
                    record.file_id,
                    stamp,
                    (event.tag_event_id + (data.scenario == "wrong_event")) % 65536,
                    data.scenario != "unsynchronized",
                )
            )
        if data.scenario == "empty":
            records = []
        if data.scenario == "malformed" and records:
            records[0]["data"] = "FF"
        status = (
            data.scenario.upper()
            if data.scenario in {"partial", "aborted", "failed"}
            else "COMPLETE"
        )
        return current().live.evidence.import_raw(
            event_id, capture(uid, records, status), "simulator"
        )

    @app.get("/api/events/{event_id}/readouts")
    async def readouts(event_id: int) -> list[dict[str, Any]]:
        current().live.repo.event(event_id)
        return current().live.evidence.sessions(event_id)

    @app.get("/api/events/{event_id}/readouts/{session_id}")
    async def readout_detail(event_id: int, session_id: int) -> dict[str, Any]:
        session = current().live.evidence.session(session_id)
        if session["event_id"] != event_id:
            raise ValueError("Readout does not exist")
        return session

    @app.get("/api/events/{event_id}/evidence")
    async def evidence(event_id: int, participant_id: int | None = None) -> dict[str, Any]:
        current().live.repo.event(event_id)
        service = current().live.evidence
        return {
            "resolutions": [
                r.model_dump(mode="json") for r in service.resolutions(event_id, participant_id)
            ],
            "decisions": service.decisions(event_id),
        }

    @app.get("/api/events/{event_id}/reviews")
    async def reviews(event_id: int, include_resolved: bool = False) -> list[dict[str, Any]]:
        current().live.repo.event(event_id)
        return current().live.evidence.reviews(event_id, include_resolved)

    @app.post("/api/events/{event_id}/decisions")
    async def adjudicate(event_id: int, data: DecisionInput) -> dict[str, Any]:
        return current().live.evidence.decide(event_id, data)

    @app.post("/api/events/{event_id}/participants/{participant_id}/status")
    async def status_ruling(
        event_id: int, participant_id: int, data: StatusDecisionInput
    ) -> dict[str, bool]:
        current().live.evidence.set_status(event_id, participant_id, data)
        return {"saved": True}

    @app.get("/api/events/{event_id}/export/evidence")
    async def export_evidence(event_id: int) -> Response:
        service = current().live.evidence
        current().live.repo.event(event_id)
        document = {
            "version": 1,
            "event": current().live.repo.event(event_id).model_dump(mode="json"),
            "readouts": [
                service.session(row[0])
                for row in service.db.execute(
                    "SELECT id FROM tag_readout_sessions WHERE event_id=? ORDER BY id", (event_id,)
                ).fetchall()
            ],
            "resolutions": [r.model_dump(mode="json") for r in service.resolutions(event_id)],
            "decisions": service.decisions(event_id),
            "audit": current().live.repo.audit(event_id),
        }
        return Response(
            json.dumps(document, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="evidence.json"'},
        )

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

    @app.get("/api/master/categories", response_model=list[MasterCategory])
    async def master_categories() -> list[MasterCategory]:
        return current().live.repo.master_categories()

    @app.post("/api/master/categories", response_model=MasterCategory)
    async def new_master_category(data: CategoryData) -> MasterCategory:
        return current().live.put_master_category(data)

    @app.put("/api/master/categories/{category_id}", response_model=MasterCategory)
    async def edit_master_category(category_id: int, data: CategoryData) -> MasterCategory:
        return current().live.put_master_category(data, category_id)

    @app.get("/api/clubs", response_model=list[Club])
    async def clubs() -> list[Club]:
        return current().live.repo.clubs()

    @app.post("/api/clubs", response_model=Club)
    async def new_club(data: ClubData) -> Club:
        return current().live.put_club(data)

    @app.put("/api/clubs/{club_id}", response_model=Club)
    async def edit_club(club_id: int, data: ClubData) -> Club:
        return current().live.put_club(data, club_id)

    @app.get("/api/runners", response_model=list[Runner])
    async def runners(
        search: str = "", limit: int = Query(default=100, ge=1, le=10000)
    ) -> list[Runner]:
        return current().live.repo.runners(search, limit)

    @app.post("/api/runners", response_model=Runner)
    async def new_runner(data: RunnerData) -> Runner:
        return current().live.put_runner(data)

    @app.put("/api/runners/{runner_id}", response_model=Runner)
    async def edit_runner(runner_id: int, data: RunnerData) -> Runner:
        return current().live.put_runner(data, runner_id)

    @app.get("/api/master/audit")
    async def master_audit() -> list[dict[str, Any]]:
        return current().live.repo.master_audit()

    @app.post("/api/events/{event_id}/categories", response_model=Category)
    async def create_category(event_id: int, data: EventCategoryData) -> Category:
        return current().live.put_category(event_id, data)

    @app.put("/api/events/{event_id}/categories/{category_id}", response_model=Category)
    async def edit_category(event_id: int, category_id: int, data: EventCategoryData) -> Category:
        return current().live.put_category(event_id, data, category_id)

    @app.get("/api/participants", response_model=list[Entry])
    async def entries(event_id: int) -> list[Entry]:
        current().live.repo.event(event_id)
        return current().live.repo.entries(event_id)

    @app.post("/api/events/{event_id}/participants", response_model=Entry)
    async def create_entry(event_id: int, data: EntryData) -> Entry:
        return current().live.put_entry(event_id, data)

    @app.post("/api/events/{event_id}/register-new-runner", response_model=Entry)
    async def register_runner(event_id: int, data: NewRegistrationInput) -> Entry:
        return current().live.register_new_runner(
            event_id, data.runner, data.entry, data.club, data.allow_similar_club
        )

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
            "evidence": [
                r.model_dump(mode="json")
                for r in service.evidence.resolutions(event_id, participant_id)
            ],
            "decisions": [
                d
                for d in service.evidence.decisions(event_id)
                if d["participant_id"] == participant_id
            ],
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
    async def import_csv(event_id: int, data: CSVInput, request: Request) -> dict[str, Any]:
        live = current().live
        summary = (
            csvio.import_participants(live, event_id, data.text)
            if data.commit
            else csvio.preview(live, event_id, data.text)
        )
        lang = request.headers.get("accept-language", "en")
        for error in summary["errors"]:
            error["ui_error"] = {
                code: presentation.error_text(error["error"], code, csv=True, operator=True)
                for code in ("en", "de")
            }
            error["error"] = presentation.error_text(error["error"], lang, csv=True)
        return summary

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
        await serve_socket(socket, False, None)

    @app.websocket("/ws/display")
    async def display_socket(socket: WebSocket, event_id: int | None = None) -> None:
        await serve_socket(socket, True, event_id)

    async def serve_socket(socket: WebSocket, public: bool, event_id: int | None) -> None:
        origin = socket.headers.get("origin")
        if origin and urlparse(origin).netloc != socket.headers.get("host"):
            await socket.close(code=1008)
            return
        if public and event_id is not None:
            try:
                current().live.repo.event(event_id)
            except ValueError:
                await socket.close(code=1008)
                return
        await socket.accept()
        runtime = current()
        queue = runtime.hub.subscribe()

        async def send() -> None:
            async with asyncio.timeout(5):
                await socket.send_json(
                    {
                        "type": "snapshot",
                        "version": 1,
                        "event_id": event_id,
                        "payload": views.display_state(runtime.live, event_id)
                        if public
                        else snapshot(),
                    }
                )
            while True:
                message = await queue.get()
                if public:
                    if event_id is not None and message["event_id"] not in {None, event_id}:
                        continue
                    message = {
                        "type": message["type"],
                        "version": 1,
                        "event_id": event_id,
                        "payload": {},
                    }
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
