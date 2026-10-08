# FoxSuite architecture — M1 through M4

## M4 desktop operations boundary

`foxops` composes the accepted FoxLive HTTP lifespan and existing FoxCore transport/ingest/TimeSync.
Its Start-menu launcher adds per-user paths, atomic settings, a process lock, setup/settings routes,
device-enumeration metadata, backup/restore and controlled server restart. FoxCore, FoxBridge and
the competition domain/scoring remain unchanged. No schema migration or second serial parser.

The desktop controller owns one source task; probing/settings serialize with an asyncio lock.
A probe pauses that task, uses the same raw-first pipeline, then resumes it. SQLite stays on the
HTTP lifespan's owner loop. Online backup is synchronous on that owner to preserve thread affinity;
large snapshots/compression can briefly delay HTTP/ingest while serial buffers provide backpressure.
Restore/location changes queue a single operation, refuse further mutations, stop HTTP/source,
close SQLite, perform validated filesystem work, then start a fresh lifespan. Connected desk/display
clients use their existing reconnect behavior; no source history is re-emitted. No uncontrolled
concurrent SQLite writer or cross-thread database connection is introduced.

Host checks, same-origin mutation checks and CSP apply to operations too. Only the fixed archive
upload endpoint permits binary POST; member names are validated without arbitrary ZIP extraction.
The local trusted-PC/no-auth boundary remains. Settings paths are operator input, not a public file
server. Desktop binding is localhost-only; advanced developer CLI LAN exposure remains explicitly
unsecured. See [Windows operations](WINDOWS.md) for packaging, precedence and validation limits.

## Accepted application boundaries

`foxcore` owns serial, parsing, UID normalization, dedupe, persistence, replay and TimeSync.
`foxbridge` is an event consumer and SPORTident live-output gateway, not competition software.
M3 adds FoxLive as a sibling event consumer, with the domain contract in [FOXLIVE.md](FOXLIVE.md).
The shared CLI is the composition root; its command registration
does not make core event/parser/transport modules depend on bridge logic.

```mermaid
flowchart TD
  Transport --> RawCommit[SQLite raw commit]
  RawCommit --> Parser --> Punch[Canonical punch]
  Punch --> Dedupe --> NormalizedCommit[SQLite normalized commit]
  NormalizedCommit --> Subscribers
  Subscribers --> Bridge[FoxBridge durable reservation]
  Subscribers --> Association[FoxLive event association and cursor commit]
  Association --> Interpretation[Pure interpretation and timing]
  Interpretation --> Ranking[Scoring and derived cache commit]
  Ranking --> Notification[Bounded WebSocket notifications]
  Notification --> Desk[Local browser snapshot and history]
  Admin[Audited event administration] --> Interpretation
  Bridge --> Maps[Explicit UID and station mapping]
  Maps --> Time[Event-local time validation]
  Time --> Encoder[D3 encoder and frame commit]
  Encoder --> Queue[Bounded delivery queue]
  Queue --> Output[Serial pair or binary capture]
  Output --> Ledger[Delivery result]
  TimeSync --> Transport
  Replay --> RawCommit
```

One asyncio loop owns SQLite and ingest. Serial open/read/write/close run through bounded blocking pyserial calls in worker threads for Windows support. Reader and writes are independent; writes are serialized. Connection changes drive a separate TimeSync task. SQLite writes never run in those threads. Raw commits use FULL synchronous WAL before processing; downstream exceptions leave recoverable raw records. Database failures propagate visibly and stop ingest rather than continue losing input. Bytes already outside the application (USB/OS buffers) cannot be guaranteed on power loss. Pending raw records are processed on startup; replay creates new records and a separate dedupe scope.

Subscribers are synchronous, short callbacks isolated by exception handling; slow consumers should
enqueue their own work. They must not perform blocking I/O. Transport reconnect only handles I/O
errors, never mistakes persistence errors for USB errors. Shutdown cancels time service, disconnects
transport, flushes partial serial input and closes SQLite. Competition interpretation is exclusively
FoxLive's responsibility, never a parser/serial/TimeSync policy.

## FoxBridge boundaries

Flat, small modules: `config`, `mapping`, `sportident`, `time`, `persistence`, `output`, `service`,
`cli`. Mapping is explicit and separate from FoxCore participant metadata. The encoder is a pure
typed bytes API with no database, serial or Fjw dependencies. Time conversion never changes the
original source timestamp. Serial output wraps the existing FoxCore serial mechanics; it does not
duplicate the FoxIdentServer reader/parser or TimeSync. No virtual COM driver is installed.

One bridge worker consumes a bounded queue (default 1024 IDs). Its subscriber commits mapping
snapshots, validated frame and offset allocation before enqueueing. Database operations remain on
the same loop/thread as FoxCore. Output writes use bounded pyserial worker calls; file capture
writes/fsync use a worker and wait for completion even on cancellation. Incoming serial and TimeSync
remain independent of a slow output, subject to brief serialized SQLite transactions. Queue overflow
records a failed delivery rather than dropping it invisibly. Mapping/encoding errors skip one punch,
not the stream. Delivery-ledger failures stop bridge operation visibly; FoxCore raw/punch data was
already committed. Logging remains protected by FoxCore's SafeLogger.

## Reservation and recovery

The durable automatic key is `(target, punch_id)`. Existing reservations, regardless of status,
prevent another automatic attempt. `queued → writing` is committed before external I/O. `sent`
means the local driver/file accepted the bytes, **not** FjwW acknowledgement. Failed connection is
`failed`; interrupted/possibly partial writes are `uncertain`. A crash can leave `queued` or `writing`.
None of those rows is automatically resumed. This prefers possible missed delivery requiring operator
action over uncontrolled competition duplicates; exactly-once receiver acceptance is impossible on
this unacknowledged stream.

Startup recovers pending FoxCore raw records **before** bridge subscription. It never scans historical
punches for delivery. New source retries are suppressed by unchanged FoxCore dedupe. Output reconnect
only admits new events; explicit `resend` creates a separate audited attempt and reuses any previously
encoded frame. Do not change `target` to bypass the ledger. One active bridge writer per DB/target is
the operational model; status reads and brief mapping commands can use separate SQLite connections.

Replay uses FoxCore's original path and provenance. Replayed punches are recorded as `replay_blocked`
unless an operator explicitly supplies `--allow-replay-output`; the guarded bridge replay command
does not even open the output endpoint. Explicit output replay can duplicate an event already in Fjw.

## FoxLive boundaries and lifecycle

The event desk presents three areas: event operations, master-data maintenance and technical System
views. `workspace.js` manages stable deep links, browser history and visible event context without
changing domain ownership. `combobox.js` is a dependency-free accessible widget: debounced filtering,
20 choices, explicit quick-create, no writes on search. Tables render 50 rows at a time. Reusable
lookups remain bounded/local; bulk participation/usage/history projections avoid per-row queries.
Duplicate review in `lookup` uses normalized strings and simple similarity, never automatic merging.
Service quick-create methods use the existing SQLite owner/transactions: new club+runner+entry are
atomic; explicit category create+enable is a separate atomic commit. No new tables/migrations/scorer.

`views.display_state` whitelists the existing snapshot for presentation, stripping UID/source/raw,
RSSI, diagnostics, audit and configuration. `/live/display`, `/api/display` and `/ws/display` are
read-only consumers. They share the accepted result calculation and bounded client Hub with the desk,
but display WebSocket invalidations have empty payloads; no operator data leaks via those messages.
The presentation client coalesces refreshes and reconnects independently. A dropped/slow client does
not affect other clients or ingestion. This boundary is not authorization: M3 remains a trusted-local
single-operator server, with administration endpoints reachable on the same origin.

Registration separates reusable Runner, Club/DOK and bilingual Category master data from EventEntry
and EventCategory. UID resolution and scoring use active entries in the selected event, never a
runner's global identity. Entries snapshot person/club fields and event categories snapshot labels
so master edits cannot rewrite history. Master changes have a separate audit; event changes retain
the existing audit/recalculation transaction. Inline new-runner registration is a single transaction.
Additive migration 4 preserves old event-local tables and creates corrected tables/caches; association,
exclusion, event lifecycle/cursors and all FoxCore source facts remain unchanged. No new serial/parser
path or change to ranking/timing rules is introduced. Ambiguous legacy identity/code data is retained
and flagged rather than automatically merged.

`models` and `scoring` define typed domain inputs and pure deterministic rules; `persistence` reads
facts in bulk and supplies event-scoped repositories; `service` owns association, administration,
recalculation and audit; `csvio` supplies atomic registration import/export. `web` composes accepted
FoxCore transport/ingest/TimeSync and domain services; `cli` owns operations. `templates` and `static`
are local assets. No FoxLive module imports FoxBridge. The shared `foxcore.cli` is only the suite's
composition root, not a product dependency of the core services.

Uvicorn has one worker. FastAPI lifespan creates/owns SQLite on the asyncio loop thread; all routes
are async and invoke brief synchronous domain/database operations on that same thread. Do not use
sync routes/thread-pool DB access or multiple workers. Existing pyserial workers never access SQLite.
FoxLive does no independent reading/parsing. `--no-serial` allows administration and historical tests.
Core raw recovery precedes Live recovery/subscription; an existing RUNNING event then catches up
source IDs after its durable cursor. Starting/resuming sets a fresh cursor rather than backfilling
all history. Association is committed separately before interpretation: a derived-write failure leaves
both the core fact and its event relationship recoverable. Closing stops new automatic associations;
archiving makes normal administration read-only. DB-enforced uniqueness prevents overlapping events.

Live intake recalculates one UID's associated history, updates its cache, then ranks the event's cached
results in bulk. Configuration changes fully recompute affected event interpretation/results. Source
timestamp then source ID is the deterministic order, not arrival time. Audit and administrative writes
share transactions with the derived recalculation. Source rows are read-only to these operations.
No generic plugin bus, scoring in routes, Redis or cross-process coordination is introduced.

WebSocket clients have bounded 128-message queues. Overflow emits `resync`; a blocked sender times
out without stopping ingest or other clients. The browser fetches an authoritative snapshot after
notifications/reconnect; open participant detail refreshes too. UI running clocks are provisional,
not persisted sporting results. HTTP host/origin checks, JSON-only mutations, autoescaping and local
assets constrain common browser hazards, but there is no network authentication/RBAC.
FastAPI native telemetry and automatic environment exporter setup are explicitly disabled. The
transitive OpenTelemetry API has no enabled instrumentation/exporter; runtime does not send telemetry.

Expected validation errors are concise HTTP 422/CLI ERROR messages. Persistence errors return 503;
an error latches visible health instead of pretending successful ongoing scoring. Core raw/database
failure stops the serial task explicitly. Derived scoring failure does not stop raw capture or later
subscriber calls: sources/associations remain recoverable, and other UIDs can still process. Repair
disk/permissions then restart/recover. Ingest isolates normal
unknown tags/stations as interpretations, not exceptions. SafeLogger protects ingest from log handlers.
Large operator-triggered recalculation/import is synchronous and may briefly pause desk updates;
this is deliberately a small single-operator event desk, not a multi-user/distributed service.
See [FOXLIVE](FOXLIVE.md) for timing, tie, correction and restart contracts. Full SPORTident readout,
station programming, complete Fjw replacement and all later milestones remain out of scope.
# M5 evidence boundary

Offline readout acquisition is separate from interpretation: a small provider
returns an immutable snapshot; raw snapshot persistence precedes reconciliation.
LIVE references FoxCore IDs, TAG_READOUT references raw station records, and
MANUAL references append-only reasoned decisions. FoxLive's resolved cache feeds
the existing scorer; no alternate serial reader or scoring strategy is added.
See [TAG_READOUT.md](TAG_READOUT.md) and [RECONCILIATION.md](RECONCILIATION.md).
SQLite writes remain serialized on the existing application owner loop. Snapshot
facts commit before derived processing; a downstream failure is recoverable by
recalculation. Slow WebSocket clients continue using the existing bounded hub.
