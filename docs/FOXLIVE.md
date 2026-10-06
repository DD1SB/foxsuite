# FoxLive — M3 domain and operational contract

FoxLive is a standalone local competition desk consuming immutable FoxCore punches. It does not use
FoxBridge, Fjw, SPORTident numbers or another serial reader/parser. M1/M2 remain accepted siblings.
This contract is written before implementation; the final validation section records actual gates.

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
timestamps across DST/midnight/next-day finishes remain valid elapsed-time arithmetic.

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

Back up the closed SQLite DB plus TOML config; use SQLite backup API for a running DB, not a live copy
of only the main file. CSV exports supplement but do not replace the DB's facts/associations/audit.

## Validation boundary

Automated domain/API/WebSocket and existing M1/M2 regression gates are required before completion.
No FoxLive physical/manual validation has been performed in this environment. M1 Fox hardware and
M2 Fjw SI-C acceptance do not prove FoxLive dashboard operation. Windows smoke procedure and final
test/build results will be recorded below before handoff. M4 is outside this task.
