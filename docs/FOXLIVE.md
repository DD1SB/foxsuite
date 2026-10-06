# FoxLive — M3 domain and operational contract

FoxLive is a standalone local competition desk consuming immutable FoxCore punches. It does not use
FoxBridge, Fjw, SPORTident numbers or another serial reader/parser. M1/M2 remain accepted siblings.
The domain contract was committed before implementation; the final section records actual validation.

## Events and association

Events have a name, date (display label, not an implicit time window), IANA timezone, optional
description, timing mode, optional UTC competition start/end and default start, and UTC audit times.
DRAFT does not automatically ingest. DRAFT → RUNNING → CLOSED → ARCHIVED is the normal lifecycle;
DRAFT may be archived, and CLOSED may explicitly resume RUNNING. ARCHIVED is read-only. No historical
event is deleted. A partial unique index enforces at most one RUNNING event.

Starting/resuming snapshots the current source ID: historical DB punches do not silently enter the
event. New non-replayed source punches are associated with that event, including duplicates, unknown
tags/stations and invalid/out-of-window punches. Associations persist independently of derived results.
The event cursor allows restart recovery of facts committed during interrupted processing. Startup
recovers pending FoxCore raw records and catches up only the persisted RUNNING event after its cursor;
no old associations are re-emitted as new browser punches. Closing stops automatic association.

An explicit historical-source association operation accepts existing source IDs for a selected event.
It is audited and idempotent, never creates a punch, and does not consult today's active event.
Recalculation reads associated normalized facts; it deliberately does not call FoxCore's raw `replay`,
whose M1 contract appends records. Use a separate DB and simulator/core stdin ingest for offline tests.

## Registration, categories and stations

Organizer-defined categories contain code, display name, active flag and display order; no age rules.
Entries contain a unique event bib, first/last name, category, optional canonical UID/club/start time,
active flag and optional operator status override. One UID can belong to only one active entry per
event. A different historical event can reuse it. UID/category edits are audited and recalculate all
associations; no source facts move or change. Deactivation retains history.

Event stations contain Fox station ID, display name, CONTROL/START/FINISH role, enabled flag/order.
Unconfigured/disabled stations remain visible but never score. No SPORTident control mapping exists.

## Interpretation and timing decisions

Order is original station timestamp, then source punch ID. Receipt order does not change scoring.
Precedence: SOURCE_DUPLICATE, MANUALLY_EXCLUDED, INVALID_TIMESTAMP, OUTSIDE_EVENT_WINDOW, UNKNOWN_UID,
UNKNOWN_STATION, DISABLED_STATION, then timing/control interpretation. Window boundaries are inclusive.
Defaults reject timestamps before 2020-01-01 UTC, outside uint32 seconds or more than 86400 seconds
from original PC receipt; validation thresholds are persisted per event for deterministic recomputation.
PC receipt is never substituted as race time. No source validity flag currently guarantees sync.

PUNCH_START_FINISH uses the earliest valid START and first FINISH at/after it. FINISH before START is
INVALID_FOR_TIMING. Equal-second start/finish permits zero elapsed because source precision is seconds.
Additional START/FINISH are REPEAT_START/REPEAT_FINISH and never replace the timing pair. Controls
before/missing start or after scoring finish are INVALID_FOR_TIMING. The first enabled CONTROL visit
inside that interval is VALID_CONTROL; subsequent visits are REPEAT_CONTROL and remain visible.

PREDEFINED_START uses entry start, else event default, else no start. START punches cannot replace it
and are repeat/ignored timing markers. FINISH still needs a known start. A first valid punch at/after
the configured start establishes observed RUNNING state; a schedule alone does not invent a physical
start observation. Elapsed/running displays use the configured start, not that first punch.

UTC instants are stored canonically; display/input use the event timezone. Explicit offset input is
unambiguous; local inputs during DST fold/gap are rejected rather than guessed. Absolute source
timestamps across DST/midnight/next-day finishes remain valid elapsed-time arithmetic. Configuration
uses whole seconds, matching firmware precision; fractional seconds are rejected, never truncated.

## States and scoring

REGISTERED derives to RUNNING with a valid observed start condition, then FINISHED with a valid pair.
DNS/DNF/DSQ are never inferred automatically; operator overrides are audited. Clearing an override
restores derived state. All timing/control evidence is retained for DNS/DNF/DSQ, but they are not ranked.
Inactive entries/categories are not eligible for official ranks.

The sole scoring strategy is DistinctControlsThenTime: distinct controls descending, finished elapsed
seconds ascending, independently per category. Exact equal control/time results are sporting ties with
competition ranks 1,2,2,4; bib then entry ID only stabilize display. Eligible finished results require a
valid start/finish pair. Unfinished runners are shown separately/provisionally, never as official ranks.
Running-time displays may use current PC time but are not persisted sporting results or tie breakers.

## Unknown tags, corrections and audit

UNKNOWN_UID lists include station, source time/ID and UID. Assign to an existing entry after checking
active-UID uniqueness; all event history is reinterpreted and rankings update without new source rows.
Manual exclusion requires a reason, retains the source and visible interpretation, and recalculates.
No timestamp edits or synthetic punches are available. Significant changes record local operator label,
UTC time, action, entity, before/after and reason. Corrections after CLOSED are permitted and visible;
ARCHIVED rejects edits. Force recalculation reports source/status counts and is deterministic.

## Web and concurrency

FastAPI/Uvicorn serve localhost by default. SQLite, routes, ingest and live services share one asyncio
owner loop/thread; serial worker calls remain FoxCore's. No database calls run in FastAPI sync handlers.
Typed routes delegate to domain services; scoring is outside HTTP/templates. Local HTML/JS/CSS require
no CDN/Node. User text is escaped; arbitrary filesystem paths are never accepted by the HTTP API.
Native FastAPI tracing/metrics/logs and environment-driven exporter setup are explicitly disabled;
its transitive OpenTelemetry API is not an enabled exporter or cloud service.
One trusted operator process is supported; network binding has no authentication/RBAC and is unsafe
on untrusted networks. Cross-origin write/WebSocket access is rejected; browser access is same-origin.

Version-1 WebSocket messages include `type`, `version`, `event_id`, `payload`: punch_received,
ranking_changed, unknown_uid, station_updated, participant_updated, event_state_changed,
connection_changed; initial snapshot and resync recover reconnect/slow clients. Bounded client queues
and independent send tasks isolate bad browsers from ingest. The UI fetches an authoritative snapshot
after notifications rather than applying potentially stale rank deltas.

Live intake recalculates the affected UID's history and category ranks in bulk; configuration changes
force full event calculation. Dashboard reads join/cache results rather than N+1 source queries.

## Administration, CSV and backup

Browser administration covers event/lifecycle/window/timezone/mode, categories, entries/UID/status,
station roles, unknown assignment, exclusion, source association, recalculation and audit. Participant
detail shows timing, controls and chronological interpreted source history; station activity shows
counts, last source time/callsign/RSSI. Dashboard separates recent punches, unknowns and standings.

UTF-8 CSV required headers: `start_number,first_name,last_name,category`. Optional: `uid,club,start_time`.
Category is its event code. Start time is ISO 8601 (offset recommended; naive local input uses event
timezone). Validate the whole file, report row numbers/errors and preview summary; import atomically
only if all rows pass. Existing bib/UID conflicts reject rather than overwrite. Participant export uses
the same columns. Results export: rank,start_number,first_name,last_name,club,category,status,controls,
start_time,finish_time,elapsed_time. Equal sporting ranks are exported unchanged; times are UTC ISO
instants and elapsed is whole seconds. Optional fields can be blank.

CSV is limited to 2 MB and duplicate/unsupported headers or mismatched columns are rejected. The
browser decodes uploaded files as strict UTF-8. Preview does not mutate; failed validation or any
mid-import DB failure rolls back all entries and audits. Exports preserve literal user data (including
leading `=`, `+`, `-`, `@`): use text import with spreadsheet formulas disabled when opening untrusted
CSV. Registration export is not a lossless backup of active flags/manual overrides/audit; use the DB.

Back up the closed SQLite DB plus TOML config; use SQLite backup API for a running DB, not a live copy
of only the main file. CSV exports supplement but do not replace the DB's facts/associations/audit.

## API and live message contract

All APIs are local, typed JSON. `POST` creates; `PUT` replaces documented configuration fields; no
destructive DELETE exists. Deactivate categories/entries/stations, or archive events. Scoped paths
and composite FKs reject cross-event relationships. Invalid input yields concise 422 detail, forbidden
origin 403, non-JSON mutation 415, persistence errors 503. The offline `/openapi.json` describes models;
Swagger/Redoc UI is disabled to avoid external assets. No raw SQL is accepted.

| Operation | Endpoint |
| --- | --- |
| Desk/health/snapshot | `GET /`, `GET /api/status?event_id=ID` |
| List/create/edit events | `GET/POST /api/events`, `PUT /api/events/ID` |
| Lifecycle/recalculate/history association | `POST /api/events/ID/state`, `/recalculate`, `/associate` |
| Categories/participants/stations | `GET /api/categories`, `/api/participants`, `/api/stations` with `event_id=ID` |
| Create/edit category/entry | `POST /api/events/ID/categories` or `/participants`; `PUT .../ENTITY_ID` |
| Configure station | `PUT /api/events/ID/stations/STATION_ID` |
| Participant detail | `GET /api/events/ID/participants/ENTRY_ID` |
| Recent punches/rankings/audit | `GET /api/punches`, `/api/rankings`, `/api/audit` with `event_id=ID` |
| Existing source-ID diagnostics | `GET /api/source-punches?after_id=0&limit=100` (read-only) |
| Exclusion | `POST /api/events/ID/punches/SOURCE_ID/exclude` with `reason` |
| CSV preview/import | `POST /api/events/ID/import` with `text`, `commit` (default false) |
| CSV download | `GET /api/events/ID/export/participants` or `/results` |
| Live notifications | `/ws` |

Lifecycle body is `{"state":"RUNNING"}`; association body is `{"punch_ids":[1,2]}`. Results include
`participant_id,category_id,start_number,status,controls,start,finish,elapsed,rank,eligible`; timing
values are immutable-source-derived Unix seconds or null. Snapshot has current local application
reader/TimeSync configuration and connection state, selected event/configuration,
active event ID, diagnostics, recent/unknown punches, station activity and cached results. Recent
rows include source/raw IDs and interpretation; history ordering uses source timestamp/ID.

WebSocket envelope example:

```json
{"type":"punch_received","version":1,"event_id":1,"payload":{"punch_id":42}}
```

`ranking_changed` requests fresh rankings (payload may have recalculation counts); `unknown_uid` has
UID/source ID; `station_updated` has station ID for a punch/configuration change; `participant_updated`
has UID or entry ID where available; `event_state_changed` requests fresh event state;
`connection_changed` carries a core connection/TimeSync diagnostic or source error. Initial `snapshot`
contains authoritative desk state. On queue overflow `resync` discards stale notifications. Treat all
notifications as invalidations, not a durable delivery journal. Clients reconnect and fetch status;
one broken/slow client cannot block source persistence. Idle clients do not time out just for inactivity.

Lifecycle ownership follows [FastAPI lifespan guidance](https://fastapi.tiangolo.com/advanced/events/);
WebSocket tests use the [official testing approach](https://fastapi.tiangolo.com/advanced/testing-websockets/).
The single-process server uses [Uvicorn configuration](https://www.uvicorn.org/settings/); no extra
worker or externally hosted frontend is started.

## Offline simulator, history and restart workflow

Use a separate DB, not a competition database:

1. `foxsuite --db data/live-demo.db live run --no-serial --no-browser`; open localhost desk.
2. Create PREDEFINED_START event with a recent default start a minute before now, category OPEN,
   entry UID `04A78319BCDE12`, and Fox station 1 CONTROL. Set the event RUNNING, then Ctrl+C.
3. POSIX: `foxsuite simulate | foxsuite --db data/live-demo.db run --stdin`.
   Windows: `cmd /c ".venv\Scripts\foxsuite simulate | .venv\Scripts\foxsuite --db data\live-demo.db run --stdin"`.
4. Restart `live run --no-serial --no-browser` against that DB. The cursor recovers source facts:
   7 raw lines, 2 normalized source punches, one valid control and one SOURCE_DUPLICATE. Malformed
   and unknown JSON are still raw facts, not fake competitors. One competitor is provisional RUNNING.
5. Recalculate twice; results remain identical. Participant/result exports and audit remain available.

Do not run the simulator core writer alongside the live writer. Facts ingested before event RUNNING
need explicit `live associate EVENT_ID SOURCE_ID ...` (or browser source association). This may be
used on DRAFT/CLOSED events deliberately and is audited. Association is atomic/idempotent, rejects
appended replay copies and creates no raw/punch rows. Plain FoxCore `replay` remains available for
parser debugging but appends records: those copies do not automatically enter FoxLive. Hardware-free
domain tests supply start/control/finish source-shaped fixtures without a public fake-punch editor.

Restart retains the RUNNING event, entries/categories/stations, associations, status overrides and
audit. It rebuilds associated caches then catches up original IDs after the cursor. Existing facts
arrive in the browser snapshot, not as fresh punch notifications. CLOSED/ARCHIVED history remains
reviewable without consulting today's active event. A failed derived write retains committed source
and association; repair storage, restart and recalculate. No automatic retention/deletion exists.

## Windows hardware/manual smoke test — pending

Use a backed-up/separate DB and stop competing serial readers. Set the real base COM port, 115200,
default TimeSync; `[live]` localhost. Record app/Python/Windows/browser and firmware versions.
Path: real RFID → FoxIdent → LoRa → FoxIdentServer USB → FoxCore → FoxLive. No Fjw/virtual COM.

1. Start `foxsuite --config config/foxsuite.toml live run`; create the smoke-test event, Europe/Berlin.
2. Choose PREDEFINED_START with default local start a minute before current synchronized time.
   Create category OPEN (using this mode permits control-only hardware to exercise the desk).
3. Create participant #17 with first/last name and OPEN category.
4. Assign the real canonical UID (e.g. accepted M2 tag `046365525C6180`, only if it is your tag).
5. Configure the actual Fox station as CONTROL with a visible name; IDs are not defaults.
6. Set RUNNING and verify source CONNECTED, recent TimeSync write and firmware time confirmation.
7. Punch the real tag once at the field station.
8. Verify a row appears without browser reload and note its source/raw IDs.
9. Verify #17/name/OPEN are correct.
10. Verify Fox ID/name, local event time, callsign/RSSI and VALID_CONTROL.
11. Verify distinct controls becomes 1 and state RUNNING; missing finish remains unranked.
12. Verify the category's provisional list updates (official rank requires a valid FINISH).
13. After the firmware's debounce interval, revisit with a genuinely later timestamp/sequence:
    REPEAT_CONTROL remains visible, controls stays 1. A radio retry is SOURCE_DUPLICATE, not revisit.
14. Punch an unregistered second UID and verify prominent UNKNOWN with station/time.
15. Assign that UID to an existing unassigned participant; history reinterprets, provisional state
    updates and raw/source row counts do not increase. Record audit before/after.
16. Note snapshots/results/IDs; Ctrl+C and restart using the same config/DB.
17. Verify event/registration/stations/audit/history remain intact, with no historical punch alerts.
18. Force recalculation twice; compare identical counts/results and export participant/results CSV.

Extended timing acceptance, when START/FINISH hardware is available: repeat in PUNCH_START_FINISH
with enabled START/CONTROL/FINISH stations; verify exact source timing and official rank, then test
entry-specific PREDEFINED_START, ties with test runners, event windows, exclusions/category changes,
USB reconnect and a long-running session. These are automated today, not physically verified M3.
No checkboxes above should be claimed successful until the actual FoxLive test is performed.

## Validation boundary and remaining risks

Automated domain/API/WebSocket and existing M1/M2 regression gates are required before completion.
No FoxLive physical/manual validation has been performed in this environment. M1 Fox hardware and
M2 Fjw SI-C acceptance do not prove FoxLive dashboard operation. HTTP/template/WebSocket and source
fake-transport tests are automated, not a manually observed browser or hardware acceptance test.

Remaining limits: no source time-valid/sync flag, so passing configurable guards is not proof of sync;
one local owner/operator, no authentication or network-security claim; full event recalculation/import
can briefly pause the desk; high-volume/long-running Windows/browser field behavior needs validation;
CLI source diagnostics/TimeSync writes are last records rather than station acknowledgement; CSV exports
are not a full audit backup and spreadsheet formula interpretation must be disabled for untrusted text.
HTTP has no source insertion/timestamp-edit route. No championship/federation/course/certificate logic
or future milestone work is included.

## Completed automated gates — 2026-10-06

| Gate | Result and boundary |
| --- | --- |
| Full pytest | **163 passed** on Python 3.12.3 and 3.13.15: all 122 accepted M1/M2 regressions plus 41 M3 cases |
| Ruff lint / format | Pass; existing settings unchanged, all 46 Python source/test files formatted |
| Strict mypy | Pass on both environments, 46 source/test files; strict settings unchanged |
| JavaScript | Syntax check passes; no Node/frontend build dependency introduced |
| Build | Source distribution and `foxsuite-0.3.0-py3-none-any.whl` build with local build dependencies |
| Offline install | Final wheel installs into clean Python 3.12 environment with `--offline --no-index` and downloaded local wheels; all 20 runtime packages compatible |
| Installed-package smoke | Outside repository: actual localhost HTTP, local assets, WebSocket snapshot, simulator/core raw-first ingest, cursor restart, deterministic recalculation, CSV and graceful Ctrl+C all pass |
| Source retention | Simulator smoke keeps 7 raw / 2 source punch / 1 transport duplicate; FoxLive has one counted control, no fabricated source records |
| Upgrade/recovery | Genuine v2→v3 fixture preserves source facts; derived-write failure, mid-CSV rollback, active-event restart and no historical live re-emission covered |
| Domain | Both timing modes, pre-sync/skew/window validation, repeat/duplicate distinction, DST/midnight, tie ranks/CSV, category/UID/status/station changes and exclusions covered |
| Desk/API | Escaped templates, typed CRUD/deactivation, atomic CSV, unknown assignment, history/exclusion, origin/host checks, WebSocket client isolation/resync and fake-source reconnect/TimeSync covered |
| Offline/no telemetry | Export environment variables do not enable FastAPI telemetry or automatic exporters; also passes installed-package smoke with such variables present |
| Reference/M1/M2 boundary | All 518 tracked firmware/reference hashes match pre-M3 snapshot; no reference or FoxBridge implementation changes, original migrations 1/2 unchanged |
| Physical/manual FoxLive | **Pending**; no browser-driven/hardware test claimed. HTTP/template/WebSocket and Linux localhost smoke are automated evidence only |

The latest Starlette TestClient emits one upstream HTTPX deprecation warning during pytest;
it does not fail tests or affect the runtime. It is not filtered/suppressed by relaxed quality settings.
The clean installation used Linux dependency wheels; provision Python-version/Windows-compatible
wheels separately for an offline Windows PC. No actual Windows installation or long-running field
benchmark was performed here. Full-recalculation/import can briefly pause live updates; large-volume
performance and real operational recovery are part of the pending field acceptance, not assumed.

The repository review checked source-fact immutability, event uniqueness/cursors, deterministic
timestamp/ID ordering and ties, UID reassignment, SQLite thread ownership, WebSocket resync/detail
freshness, bulk dashboard queries (201-entry query-count regression), HTML escaping, configurable
host/port/paths and concise operator errors. Core changes are limited to suite version, CLI composition
and additive migration 3; accepted serial/parser/TimeSync/dedupe logic is untouched. The prior fixed
schema-version assertion now checks the migration count without dropping its source-preservation test.
M4 has not been started.
