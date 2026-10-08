# FoxLive — M3 domain and operational contract

M4 desktop setup/settings surround this accepted application without changing its domain/scoring.
Normal Windows launch uses the Start-menu FoxSuite shortcut; first-run setup selects language,
USB/COM and data location. System → Settings opens graphical connection, backup/restore and safe
shutdown. EN/DE remains browser-local presentation; a saved application preference initializes a
fresh browser, never translates persisted competition data. Accepted M3 physical Windows
registration/RFID/live/second-monitor/restart testing remains **pending** independently of packaging.
See [Windows operations](WINDOWS.md) for installation/storage and its separate acceptance checklist.

## Event desk information architecture

Event operations (overview, participants, category selection, stations, operator live and rankings)
are separate from reusable-data maintenance and System diagnostics/settings. Deep links retain event
context; navigation does not clear an unsaved registration. Register participant opens one local
dialog: bounded searchable runner/category/club suggestions, inline person creation, explicit club
and category creation, event fields, read/confirm RFID and save. No generated reference is entered.
Club+new runner+entry commit atomically; canceling staged club/person creation writes nothing.
Category creation/enabling is an explicit independent commit, retained if registration is canceled.
Similar people/clubs produce review choices, not automatic merges. Exact normalized club matches
are rejected. Category quick-create enables/selects the reusable category for the current event.

`/live/display` is a separate read-only second-monitor window. Its HTTP/WebSocket projection excludes
RFID values, raw source records, COM ports, diagnostics, audit and administration. It displays the
same persisted competition results, not another scoring implementation. EN/DE language and native
time inputs remain presentation concerns. Physical Windows acceptance is still pending.

### Registration and navigation

The header always shows the opened event name/date. Event selection is remembered locally in the
browser, distinct from the single RUNNING competition. Event tabs have deep links under
`/events/{event}/overview`, `participants`, `categories`, `stations`, `live`, and `rankings`.
Master data has `/master/runners`, `/master/clubs`, `/master/categories`; technical information has
`/system/base`, `/system/diagnostics`, `/system/settings`. Internal keys are only URL/API references
or hidden selections, never editable identity fields or navigation labels. Back/forward navigation
between views keeps unsaved form values; deliberately opening another event clears the registration
and cancels tag reading to prevent cross-event assignment. Closing a registration cancels/stops tag
capture. A new registration explicitly clears the old draft.

On **Participants**, use **Register participant / Teilnehmer melden**. Search by name, year or
club/DOK; suggestions include all three to disambiguate people. Select an existing runner or create
one in the same dialog. Club selection searches code/name; an unmatched query offers explicit quick
creation. Review existing exact/near matches, then select an existing club or confirm a distinct new
club. Code-only or name-only quick creation is permitted (code-only uses that code as the name).
Normal comparison trims/compacts whitespace and case-folds code/name. Exact normalized club code OR
name duplicates are rejected; simple string/meaningful-word similarity only warns, never merges.
Inline person creation similarly offers plausible existing people before saving; equal names may
legitimately represent different people, so explicit new-person confirmation is possible.

Category suggestions prioritize categories enabled for this event. A global category not enabled
offers **Enable and select**. Quick-create asks for code plus English and German names, then
atomically creates/enables/selects it; duplicate normalized codes are rejected. This is an explicit
independent commit (the dialog explains that canceling registration will not delete this category).
No write occurs merely from typing/searching. A new club is staged in new-runner registration and
commits with runner, entry and audit, or all roll back on a collision. Club quick creation in master
runner administration is an explicit independent commit, not a staged registration transaction.

Finish event fields (start number, category, optional native start time, check-in), read/confirm the
RFID tag or choose a recent unassigned tag, and save. Unknown tags in Operator Live offer **Assign
tag / register participant**, including selection of an existing registration. RFID remains on
EventEntry; assignment uses the existing audited recalculation and never creates/edits source facts.
To change another active owner's tag, first deliberately clear that registration's assignment.

Suggestions are debounced 120 ms and limited to 20 rendered choices; Arrow Up/Down and Enter select,
Escape dismisses, and Tab reaches the explicit create button. Typed text alone is not a selection.
Participants support name/year/club/start-number search, category/status filters, sorting and 50-row
pages. Master directories also have search/50-row pages, participation/usage counts, runner historical
registration snapshots and club-associated runner lookup. Master runners are fetched through the
existing bounded API (up to 10,000), not expanded into an enormous HTML dropdown. This is a local
single-operator desk, not an unbounded remote directory.

### Operator Live and presentation display

**Event → Live** shows participant/station/time/interpretation/RSSI, unknown-tag resolution and station
activity. COM ports, source JSON, source IDs, parser/database health and audit technical details are
under System, not the public display. Operational source connection/TimeSync status remains in the
desk's compact status bar; a failed TimeSync write is not a field-station acknowledgement.

**Open live display / Live-Anzeige öffnen** opens `/live/display?event_id=…` in a separate tab/window
without disturbing the desk. Move it to monitor 2 and optionally use **Fullscreen / Vollbild**.
The browser must allow fullscreen; its exit key remains available. The view is responsive at desktop
1080p and stacks on narrower tablets. It shows localized event name/date/state, recent punches,
finished category ranks and separately provisional state, running count and stations with recorded
activity. "Active station" here means an enabled station with an associated punch, not mesh health.
No registration, correction, source/debug/COM or configuration controls exist. Unknown people appear
without raw RFID values. Many categories/results may require scrolling; no automatic slideshow is
introduced. The display follows its window's selected language; changing another window does not
force an immediate switch. Local-storage preference remains shared by the browser origin for reloads.

`GET /api/display` and read-only `/ws/display` accept optional `event_id`. They whitelist display data:
event identity/labels, category labels, entry display names/start numbers, existing scoring results,
12 recent punch display rows and counts. IDs remain hidden internal references. The WebSocket starts
with this projection, then sends version-1 invalidations with empty payloads (never the operator
channel's UID/diagnostic content). The client coalesces HTTP refreshes, automatically reconnects
after two seconds and refreshes the current snapshot, not historical punch notifications. Both views
share the accepted result service and bounded isolated client queues; no duplicate scorer exists.
This is presentation separation, **not authentication**: all administration APIs still exist on the
same trusted-local-PC server. Do not expose it to untrusted spectators/networks.

### Conceptual views

| View | Operator sees | Main action |
| --- | --- | --- |
| Event Participants | Event name/date; search/category/status filters; start number, runner/year/DOK, category, tag, status | Register participant, import CSV, edit/tag/details/deactivate |
| Registration dialog | Find/create runner; inline club; event category/create-enable; start number/time; read/recent tag | Confirm tag and save without leaving the event |
| Event Categories | Localized reusable category labels with enabled checkboxes | Select existing or explicitly create/enable category |
| Master data | Searchable reusable people/clubs/categories, participation/usage counts, historical snapshots | Correct or deactivate reusable data, never automatic merge |
| Operator Live | Recent punches, interpretations/RSSI, unknown tags, station activity | Resolve tags or perform reasoned exclusion |
| Presentation display | Large event header, recent participant/control visits, finished/provisional category results | Language/fullscreen only; no administration |

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

Runner is reusable person master data: generated key, names, birth year/optional birth date, optional
reusable Club/DOK reference, activity and timestamps. New runners require birth year or a full date;
no automatic category/age rules exist. Category is reusable master data with code, English/German
names and activity. EventCategory selects/enables those categories and orders them for one event.
Master-data activity controls new selection, not historical eligibility.

EventEntry is one runner's event registration: generated key, event/runner/category references,
start number, canonical RFID UID, optional predefined start, activity/check-in and manual competition
status. Derived status/timing/rank remain in the event-specific result cache. Runner does not own any
of these competition fields. One active runner entry and one active UID per event are enforced;
start numbers remain unique within the event. Different events can reuse the person, tags and codes
with independent category/start number/start time/status. Disabling an EventCategory excludes its
entries from normal ranks without destroying their punches. Event-entry identity/club and enabled
category labels are snapshots; master edits never silently change past registration exports/results.
UID/category edits are audited and recalculate only event interpretations; source facts never move.

The event desk offers **Add participant / Teilnehmer melden**: search existing runners by name,
birth year or club/DOK, or create a runner inline, then assign event start number/category/tag/time.
Inline creation and registration commit atomically; a collision leaves neither half-created record.
Reusable runners, clubs and categories have their own administration area. Registration requires
an enabled event category; the category selector displays code and the selected-language name.

### Additive registration migration (schema 4)

Migrations 1–3 remain unchanged. The original event-local category/participant/interpretation/result
tables are retained as legacy records, not rewritten or deleted. New master/event-entry/cache tables
copy their identifiers and results so source references, associations, exclusions, audit and cursors
survive. Each legacy entry produces a separate runner: no inference/merge from name alone. Unknown
birth information remains NULL and is visibly marked for completion; it is not invented.
Distinct legacy club text creates reusable club records with unknown DOK code. Each old category
gets a master category and event selection, retaining the exact old display name in both languages
because the original language cannot be inferred. Duplicate legacy codes are marked for review;
new master edits/creation require unambiguous codes. IDs remain internal. These conservative copies
preserve history even where reuse cannot yet be inferred. Back up before opening schema 4: earlier
M3 binaries reject it and no destructive downgrade/automatic person merge is supplied.

Event stations contain Fox station ID, display name, CONTROL/START/FINISH role, enabled flag/order.
Unconfigured/disabled stations remain visible but never score. No SPORTident control mapping exists.

## Operator desk: language, registration and time inputs

English is the default. Use **Language: English / Deutsch** in the header to switch immediately,
without restarting FoxSuite. The choice persists in this browser's local storage for the current
URL origin (host/port); it is not an event property or account. If storage is unavailable, switching
still works for this page. Language affects labels, messages and date/time presentation only:
names/codes/club/reasons entered by organizers, UTC competition instants, event timezone, neutral
enums, CSV column names and protocol bytes remain unchanged.

Navigation, buttons, forms, validation/confirmation/empty states, lifecycle/participant/role/punch
labels, rankings, RFID workflow and CSV help use centralized English/German JSON catalogs under
`src/foxlive/static/translations/`. Python HTTP validation and local JavaScript share those catalogs.
Missing translations fall back to English; unknown keys display a human-readable unavailable label,
not the key. Raw data under collapsed **Technical details** remains untranslated for troubleshooting.
Catalog parity, nonempty values, formatting placeholders and used keys are regression-tested.

Reusable category creation asks for code and English/German display names; IDs are generated.
Event setup selects these existing categories and enables/orders them. Selectors show **M40 – Men 40**
or **M40 – Männer 40** according to UI language, never a database key.
Event/participant/category references stay behind controls. Physical FoxIdent station numbers remain
meaningful configuration, not database keys. Participant labels are **Start number / Startnummer**;
the stable CSV/API field remains `start_number`. CSV previews and history show meaningful names,
not raw model dumps. Advanced historical selection uses checkboxes labeled by tag/station/time;
CLI/API source references remain available for diagnostics.
The advanced source list retains its existing first-100-record limit; larger historical selections
can still use the existing CLI/API. It is separate from the recent-tag picker.

Date and competition/start-time forms use native `date` and `datetime-local` pickers, to whole seconds.
Localized captions and tables show EN `10/06/2026, 14:30:00` / DE `06.10.2026, 14:30:00` in the event
IANA zone. Native picker chrome itself follows the browser/OS locale; its adjacent caption follows
the selected FoxLive language. On a DST fall-back time, choose the first or second occurrence and
save again; the choices show explicit UTC offsets. A spring-forward nonexistent time is rejected.
Unchanged saved fields retain their original UTC instant, including which DST occurrence was chosen.
API/CSV/debug timestamps remain ISO 8601; ordinary forms do not require typing them.

Timezone is prefilled under **Advanced settings**: selected event's timezone, otherwise the last
saved timezone in this browser, otherwise the browser/PC's IANA zone, with UTC as fallback.
A correctly configured German event PC therefore defaults to Europe/Berlin. Verify it once for a new
event; changing UI language never changes the zone. Native picker values contain no zone themselves,
so the read-only `/api/ui/local-time` adapter resolves them before the unchanged domain validation.
These presentation choices follow the browser contracts for
[native local date/time inputs](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/datetime-local),
[localized formatting](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat)
and [browser preferences](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage).

### RFID registration without copying UIDs

1. Select an existing runner (name/birth year/club/DOK search), or create one inline; enter the
   registration's start number and enabled category. Person fields do not include tag/status/start.
2. Click **Read RFID tag / RFID-Tag einlesen**, then punch the tag at a FoxIdent station.
3. FoxLive waits for the next original, non-replayed, nonduplicate live punch whose canonical UID
   is not owned by another active entry in this event. It does not select an older punch silently.
4. Review detected tag, station, station time and separately labeled PC reception time. Bad/pre-sync
   station time is flagged; reading identity does not validate that punch for scoring.
5. Click **Confirm tag and save participant** and accept the confirmation. Canceling never assigns.

Alternatively choose one of the 20 most recently observed unassigned tags. Manual hexadecimal UID
entry/removal remains only under **Advanced: manual RFID entry**. Replacing this participant's old
tag requires confirmation; a tag owned by another active participant is rejected, not silently moved.
Deliberately clear the previous owner's assignment first if a transfer is intended. The server's
existing atomic uniqueness check is authoritative even if another assignment occurred after detection.

Reading works during DRAFT registration too: it observes existing FoxCore facts, not another reader
or parser. DRAFT punches are still **not** automatically associated with the competition. Confirmation
uses the existing audited participant create/edit operation and reinterprets already associated event
history for the affected UIDs. It creates no synthetic source punch and edits no source timestamps.
Earlier pre-event facts need deliberate historical selection if they should enter the competition.
The wait times out after two minutes; Cancel, changing event/participant, browser update
connection loss or an observed source disconnect cancels an outstanding wait. Read again to re-arm.
Language switching does not discard the participant form or detected tag. The wait is browser-local,
not persisted across reload/restart. `/api/events/ID/rfid-candidates` is a read-only observation with a
source cursor; recent tags are grouped by canonical UID. No schema/scoring/core/bridge change is needed.

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

UTC instants are stored canonically; display/input use the event timezone. API/CSV explicit offset input is
unambiguous; naive local inputs during DST fold/gap are rejected rather than guessed. The browser
offers an explicit fold choice and rejects gaps as described above. Absolute source
timestamps across DST/midnight/next-day finishes remain valid elapsed-time arithmetic. Configuration
uses whole seconds, matching firmware precision; fractional seconds are rejected, never truncated.

## States and scoring

REGISTERED derives to RUNNING with a valid observed start condition, then FINISHED with a valid pair.
DNS/DNF/DSQ are never inferred automatically; operator overrides are audited. Clearing an override
restores derived state. All timing/control evidence is retained for DNS/DNF/DSQ, but they are not ranked.
Inactive entries/categories are not eligible for official ranks.

The sole scoring strategy is DistinctControlsThenTime: distinct controls descending, finished elapsed
seconds ascending, independently per category. Exact equal control/time results are sporting ties with
competition ranks 1,2,2,4; start number then entry ID only stabilize display. Eligible finished results require a
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

UTF-8 CSV required headers: `start_number,first_name,last_name,category`, plus at least one birth
column (`birth_year` or `birth_date`) containing a value per row. Optional: `uid,club,club_code,start_time`.
`birth_date` is YYYY-MM-DD, and must agree with `birth_year` when both are present. `club_code` is the
reusable club/DOK code; code/name mismatch is rejected. Existing column names remain unchanged;
new exports append `birth_year,birth_date,club_code`. Old files without birth information require
completion before import: unknown legacy birth data is not guessed. Matching names, exact birth
information and club must resolve one reusable runner; ambiguous matches require manual selection.
CSV creates missing runners/clubs in the same atomic transaction as entries and audits. Matching
inactive runners or already-active event registrations are rejected. Preview creates nothing.
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
| Enable/edit event category | `POST /api/events/ID/categories` with category_id/enabled/display_order; `PUT .../CATEGORY_ID` |
| Register/edit existing runner | `POST /api/events/ID/participants` with runner_id and event fields; `PUT .../ENTRY_ID` |
| Inline new-runner registration | `POST /api/events/ID/register-new-runner` with typed runner/entry objects, atomic |
| Reusable people | `GET /api/runners?search=NAME%20YEAR%20DOK&limit=100`; `POST /api/runners`, `PUT /api/runners/ID` |
| Reusable clubs/categories | `GET/POST /api/clubs`, `/api/master/categories`; `PUT .../ID` |
| Reusable-data audit | `GET /api/master/audit` (UTC operator/action/before/after); technical details remain untranslated |
| Configure station | `PUT /api/events/ID/stations/STATION_ID` |
| Participant detail | `GET /api/events/ID/participants/ENTRY_ID` |
| Recent punches/rankings/audit | `GET /api/punches`, `/api/rankings`, `/api/audit` with `event_id=ID` |
| Existing source-ID diagnostics | `GET /api/source-punches?after_id=0&limit=100` (read-only) |
| RFID observation (also DRAFT) | `GET /api/events/ID/rfid-candidates?after_id=CURSOR&limit=20` (read-only; omit cursor for recent unique tags) |
| Native time resolution | `POST /api/ui/local-time` with `value`, `timezone` returns valid UTC choices; no DB writes |
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
notifications as invalidations, not a durable delivery journal. `master_data_changed` (event_id null)
invalidates reusable runner/club/category selections and lists;
it does not change existing competition snapshots or results. Treat all
clients as reconnectable and fetch fresh status;
one broken/slow client cannot block source persistence. Idle clients do not time out just for inactivity.

Lifecycle ownership follows [FastAPI lifespan guidance](https://fastapi.tiangolo.com/advanced/events/);
WebSocket tests use the [official testing approach](https://fastapi.tiangolo.com/advanced/testing-websockets/).
The single-process server uses [Uvicorn configuration](https://www.uvicorn.org/settings/); no extra
worker or externally hosted frontend is started.

## Offline simulator, history and restart workflow

Use a separate DB, not a competition database:

1. `foxsuite --db data/live-demo.db live run --no-serial --no-browser`; open localhost desk.
2. Create reusable category OPEN with both language names, then a PREDEFINED_START event with a
   recent default start a minute before now and enable OPEN. Register a runner with birth year in
   OPEN; use the advanced manual fallback UID `04A78319BCDE12` for this offline fixture, and Fox
   station 1 CONTROL. Set the event RUNNING, then Ctrl+C.
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

1. Start `foxsuite --config config/foxsuite.toml live run`; create/open the smoke-test event under
   Event → Overview, Europe/Berlin. Verify its name/date stays in the header across tabs.
2. Choose PREDEFINED_START with default local start a minute before current synchronized time.
   Select OPEN under Event → Categories or create it inline with both language names (using this
   mode permits control-only hardware to exercise the desk).
3. Under Event → Participants, register a known runner using keyboard name/year/DOK search. Then
   register a new runner inline, select an existing club and try explicit new-club creation in the
   same workflow. Review exact/near matches. Select/enable/create category without leaving the dialog.
   Set start number 17 in OPEN; no person master form owns an RFID tag. Cancel a staged registration
   once and verify no orphan club/person was saved. Explicit category creation remains saved.
4. Use Read RFID tag, punch the real tag, review station/time, and confirm/save the assignment.
   The accepted M2 tag `046365525C6180` is only an example, not a default.
5. Configure the actual Fox station as CONTROL with a visible name; IDs are not defaults.
6. Set RUNNING and verify source CONNECTED, recent TimeSync write and firmware time confirmation.
7. Punch the real tag once at the field station.
8. Open Event → Live; verify a row appears without browser reload. Source/raw IDs are available in
   System → Diagnostics only; note them for the test record.
9. Verify #17/name/OPEN are correct.
10. Verify Fox ID/name, local event time, callsign/RSSI and VALID_CONTROL.
11. Verify distinct controls becomes 1 and state RUNNING; missing finish remains unranked.
12. Verify the category's provisional list updates (official rank requires a valid FINISH).
13. After the firmware's debounce interval, revisit with a genuinely later timestamp/sequence:
    REPEAT_CONTROL remains visible, controls stays 1. A radio retry is SOURCE_DUPLICATE, not revisit.
14. Punch an unregistered second UID and verify prominent UNKNOWN with station/time.
15. Assign that UID to an existing unassigned participant; history reinterprets, provisional state
    updates and raw/source row counts do not increase. Record audit before/after.
    Also exercise unknown-tag registration of an existing/new runner.
    Open **Live-Anzeige öffnen / Open live display** in a second browser window, move to monitor 2,
    optionally enter fullscreen, and verify a subsequent real punch updates both views. Check EN/DE,
    participant/ranking correctness and absence of RFID/COM/admin/debug data in the presentation view.
16. Note snapshots/results/IDs; Ctrl+C and restart using the same config/DB.
17. Verify event/registration/stations/audit/history remain intact, with no historical punch alerts.
    Reopen/reconnect the display and check its same current state/results without manual refresh.
18. Force recalculation twice; compare identical counts/results and export participant/results CSV.

Extended timing acceptance, when START/FINISH hardware is available: repeat in PUNCH_START_FINISH
with enabled START/CONTROL/FINISH stations; verify exact source timing and official rank, then test
entry-specific PREDEFINED_START, ties with test runners, event windows, exclusions/category changes,
USB reconnect and a long-running session. These are automated today, not physically verified M3.
No checkboxes above should be claimed successful until the actual FoxLive test is performed.

## Validation boundary and remaining risks

Automated domain/API/WebSocket and existing M1/M2 regression gates are required before completion.
No FoxLive physical/manual validation has been performed in this environment. M1 Fox hardware and
M2 Fjw SI-C acceptance do not prove FoxLive dashboard operation. HTTP/template/WebSocket,
fake-transport and Chromium-driven desk checks are automated, not physical hardware acceptance.

Remaining limits: no source time-valid/sync flag, so passing configurable guards is not proof of sync;
one local owner/operator, no authentication or network-security claim; full event recalculation/import
can briefly pause the desk; high-volume/long-running Windows/browser field behavior needs validation;
CLI source diagnostics/TimeSync writes are last records rather than station acknowledgement; CSV exports
are not a full audit backup and spreadsheet formula interpretation must be disabled for untrusted text.
Derived failures latch a visible error and leave pending associations marked in the desk, but do not
stop FoxCore raw capture or later UID processing. Core raw-storage failure stops ingestion explicitly.
HTTP has no source insertion/timestamp-edit route. No championship/federation/course/certificate logic
or future milestone work is included.

## Initial M3 automated gates — 2026-10-06

| Gate | Result and boundary |
| --- | --- |
| Full pytest | **165 passed** on Python 3.12.3 and 3.13.15: all 122 accepted M1/M2 regressions plus 43 M3 cases |
| Ruff lint / format | Pass; existing settings unchanged, all 46 Python source/test files formatted |
| Strict mypy | Pass on both environments, 46 source/test files; strict settings unchanged |
| JavaScript | Syntax check passes; no Node/frontend build dependency introduced |
| Build | Source distribution and `foxsuite-0.3.0-py3-none-any.whl` build with local build dependencies |
| Offline install | Final wheel installs into clean Python 3.12 environment with `--offline --no-index` and downloaded local wheels; all 20 runtime packages compatible |
| Installed-package smoke | Outside repository: actual localhost HTTP, local assets, WebSocket snapshot, simulator/core raw-first ingest, cursor restart, deterministic recalculation, CSV and graceful Ctrl+C all pass |
| Source retention | Simulator smoke keeps 7 raw / 2 source punch / 1 transport duplicate; FoxLive has one counted control, no fabricated source records |
| Upgrade/recovery | Genuine v2→v3 fixture preserves source facts; derived failure retains capture/association and later UID processing; raw failure stops visibly; CSV rollback, active restart and no historical live re-emission covered |
| Domain | Both timing modes, pre-sync/skew/window validation, repeat/duplicate distinction, DST/midnight, tie ranks/CSV, category/UID/status/station changes and exclusions covered |
| Desk/API | Escaped templates, typed CRUD/deactivation, atomic CSV, unknown assignment, history/exclusion, origin/host checks, WebSocket client isolation/resync and fake-source reconnect/TimeSync covered |
| Offline/no telemetry | Export environment variables do not enable FastAPI telemetry or automatic exporters; also passes installed-package smoke with such variables present |
| Reference/M1/M2 boundary | All 518 tracked firmware/reference hashes match pre-M3 snapshot; no reference or FoxBridge implementation changes, original migrations 1/2 unchanged |
| Physical/manual FoxLive | **Pending**; initial HTTP/template/WebSocket and Linux localhost smoke are automated evidence only |

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
At this initial M3 snapshot, M4 had not been started. Current M4 operations are documented in WINDOWS.md.

## M3 event-desk UX / information architecture gates — 2026-10-08

| Gate | Result and boundary |
| --- | --- |
| Complete Python 3.12 pytest | **227 passed**, including all retained M1/M2/M3 checks and ten Chromium workflows; 20 new IA/quick-create/display cases |
| Chromium | Existing EN/DE/DST/RFID/history checks adapted to intentional navigation/combobox changes, not weakened; inline club/category/person review, cancel/atomic save, known runner selection, keyboard/mouse, event deep links/history and realistic tables pass |
| Display / WebSockets | Two concurrent real browser windows update punches/results without reload, reconnect, and render EN/DE; read-only HTTP/WS whitelist is tested against UID/raw/source/COM/audit leaks |
| Realistic data | 500 runners, 200 clubs, 50 categories, 500 EventEntries, 3,000 source punches; 20 suggestions/50-row pages and bulk snapshot queries (no per-entry N+1) verified; not a long-duration field benchmark |
| Visual review | Automated isolated screenshots of participants, grouped registration, master data and presentation reviewed; no brittle pixel snapshots or hardware claim |
| Ruff / strict mypy | Lint, format and strict types pass, 53 Python source/test files; original gates/settings unchanged |
| Build / installed wheel | Sdist/wheel, clean offline local-wheelhouse installation, CLI/local assets and operator/display HTTP/WS smoke, simulator/raw-first intake, restart/recalculation/CSV and graceful shutdown pass |
| Accepted boundaries | Schema remains 4; original migrations, source model/persistence, scoring, FoxCore and FoxBridge unchanged; all 518 reference hashes match |
| Hardware/manual acceptance | **Pending**; follow the updated setup/inline registration/live/second-monitor/recovery checklist above on Windows with physical Fox hardware |

The upstream Starlette HTTPX deprecation warning remains visible. Main remaining risks are physical
Windows/fullscreen/browser behavior and long-running operation, local-only/no authentication, briefly
blocking large recalculation/import, absence of a field-station synchronization acknowledgement and
intentional source association/exclusions requiring careful operators. Category quick-create is an
explicit independent commit; canceled registration does not remove it. Similarity review is a simple
warning, not identity proof or automatic merging. Presentation privacy is not access control.
No schema/domain/scoring redesign or later milestone work is included.

## Focused M3 operator-UX validation — 2026-10-07

No migration or change to domain models, scoring, repositories, source ingest, FoxCore or FoxBridge.
Only desk presentation, localized HTTP error adapters, read-only tag/time helpers, packaged local
assets, tests and documentation change. Public machine-readable fields and CSV format remain stable.
HTTP validation adds `ui_detail` English/German messages for immediate retranslation in the browser;
default English `detail` remains backward compatible. CSV row errors similarly include `ui_error`.

| Gate | Result and boundary |
| --- | --- |
| Full Python 3.12 suite | **190 passed**, all 165 prior regressions plus 22 presentation/API/helper cases and three real-browser cases |
| Python 3.13 suite | **187 passed**, three optional browser tests skipped (not enabled in that environment) |
| Ruff lint / format | Pass, unchanged quality settings; 49 Python source/test files |
| Strict mypy | Pass on Python 3.12/3.13, 49 source/test files |
| Browser | Linux Chromium with existing strict CSP: EN default; EN→DE→EN/reload preference; generated category references/code-name labels; read/cancel/confirm/recent tags, ownership error and immutable historical reinterpretation; DRAFT reading; native time/fold/gap/unchanged-instant checks pass |
| Packaging | Sdist and wheel include both JSON catalogs, presentation helpers and test fixtures; clean Python 3.12 offline wheel installation succeeds |
| Installed-package smoke | Out-of-repository localhost desk/assets/catalogs/time-resolution/RFID observation, WebSocket, simulator raw-first ingest, restart/recalculation, CSV and graceful shutdown pass; seven raw lines, two punches, one duplicate retained |
| Accepted boundary | All 518 reference hashes unchanged; Core/Bridge, schema migrations and competition interpretation/scoring untouched |
| Hardware/Windows | **Pending**, no physical/manual FoxLive acceptance or long-running field operation claimed |

Browser tests are optional development checks: install `.[dev,ui-test]`, provision Chromium with
`python -m playwright install chromium`, then `FOXSUITE_BROWSER_TESTS=1 pytest` (PowerShell:
`$env:FOXSUITE_BROWSER_TESTS="1"; pytest`). The browser cache can be provisioned in advance for offline
testing. Normal runtime has no Playwright, Node/npm, CDN or browser-download requirement. Five pure
JavaScript helper cases use Node.js when available without any npm dependencies; other regression
checks require only the project's Python test dependencies. The upstream Starlette HTTPX warning
remains visible and is not suppressed. At this UX snapshot, M4 had not been started.

## Focused M3 registration-domain correction — 2026-10-07

Runner = reusable person; EventEntry = one person's event registration. Category = reusable bilingual
master; EventCategory = category enabled for an event. RFID UID is owned only by the active EventEntry
in that event. Reuse in later events is allowed. Club/DOK is reusable and optional. Birth year or
optional full date is required for new people; no age-class rules or category suggestion exist.
Check-in is a presentation/registration flag, independent of scoring.

The registration UI separates stable person fields from event fields, supports name/year/club/DOK
search and creates a new person plus entry atomically. Read/confirm tag and recent-tag selection
assign to the event entry; the unknown-tag dashboard also starts registration for an existing/new
runner. Changing registration selections while waiting cancels the wait; a detected tag can be
reviewed/confirmed for the completed registration and is rechecked for ownership before saving.
Manual fallback remains advanced. Recalculation uses active event entries without changing source
records or accepted timing/scoring semantics. Names/club/birth and event category labels are snapshots,
so later master edits cannot rewrite historical outputs. Deliberate runner reassignment is audited.

Migration 4 adds master/entry/derived-cache tables while preserving the original M3 records and all
source/bridge facts. IDs are retained behind selections. Legacy person identities cannot be inferred
from names, so one runner per old entry is preserved; birth data is explicitly unknown. Duplicate
legacy category codes and unknown original language are retained and flagged for review. Complete
birth data and review/rename conflicting master codes before reuse; no automatic merging/downgrade.
Corrected registration inputs use runner_id and event fields, rather than event-local person fields;
category selection uses category_id/enabled/order. These are intentional M3 domain/API corrections.
CSV appends birth_year/birth_date/club_code; old machine column names remain unchanged. Files without
birth information require completion. Ambiguous identity matches fail visibly, never guess ownership.

| Gate | Result |
| --- | --- |
| Full Python 3.12 regression suite | **207 passed**, including all retained M1/M2/M3 assertions, 16 new master/registration/migration cases and a fourth Chromium workflow |
| Chromium | EN/DE registration and live RFID confirmation/collision/reinterpretation; reusable person/club/category across events; unknown-tag registration; native DST/unchanged-instant checks pass |
| Ruff lint / format | `ruff check src tests` and `ruff format --check src tests`: pass, 50 Python files, unchanged settings |
| Strict mypy | `mypy src tests`: pass, 50 files, existing strict settings |
| Packaging/offline install | Sdist/wheel build and clean Python 3.12 local-wheelhouse-only installation pass |
| Installed wheel smoke | Outside repository: person/category registration, local assets/catalogs/time/tag helpers, HTTP/WebSocket, simulator/core source intake, restart/recalculation, CSV and Ctrl+C pass; 7 raw / 2 source punches / 1 duplicate retained |
| Migration/restart | Genuine schema-3 fixture retains original tables/audit/associations/source/bridge facts, preserves ambiguous old identities and rebuilds without historical live emission; current master/entry restart and CSV rollback are tested |
| Accepted boundary | Original migrations 1–3 unchanged; source ingest and scoring module unchanged; no FoxBridge or reference changes; all 518 reference hashes match |
| Physical/manual Windows acceptance | **Pending**; automated Linux Chromium/local-host tests are not physical acceptance |

One upstream Starlette HTTPX deprecation warning remains visible (not suppressed). Previous fixtures
that created event-local person/category fields were updated to create reusable people and select
categories; collision/reassignment/tie/import fixtures now use distinct people and birth information.
Their timing, ranking, immutable-source and error-boundary assertions remain intact. Historical
validation sections above describe earlier commits, not the current schema/registration contract.
At this domain-model snapshot, M4 had not been started. Current M4 operations are documented in WINDOWS.md.
