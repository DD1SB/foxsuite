# SQLite schema, version 4

M4 introduces **no database migration** and changes no core, bridge or live source/domain tables.
Desktop storage is outside installation, at `%LOCALAPPDATA%\FoxSuite\data\foxsuite.db` by default.
Online backup includes committed WAL data using SQLite's backup API. The `.foxbackup` archive also
contains settings and a checksummed manifest; restore validates integrity/schema and preserves
current device/browser configuration. Restore/data-location changes close all owned handles first
and create a safety backup. Copy/Move refuse existing destinations; Use existing refuses absent or
invalid DBs. Move retains a named original recovery copy. See [operations](OPERATIONS.md) for the
graphical workflow and exclusive-writer boundary; ZIP checksums are not signatures/authentication.

One sqlite3 connection belongs to the ingest loop thread. WAL, synchronous FULL, foreign keys and a 5s busy timeout are enabled. Ordered SQL migrations run under BEGIN IMMEDIATE; `schema_migrations(version)` tracks applied IDs. Unknown/future or noncontiguous versions are rejected. Table creation is exclusively migration-driven.

| Table | Purpose |
| --- | --- |
| raw_events | Exact BLOB including newline/CR or disconnect fragment; replacement-decoded text; UTC receive time; parse status/type/error; source, replayed, scope; optional original_raw_id FK |
| punches | UNIQUE raw_event_id FK; original station integer timestamp and PC receive time; station, sequence, canonical UID, optional callsign/RSSI; source/replay/scope; duplicate flag and duplicate_of FK |
| diagnostics | UTC connection and TimeSync attempt/result descriptions |
| participants | ID and name only |
| participant_uids | Canonical UID primary key mapping to participant FK |
| stations | Station ID, name and optional callsign; no control-code semantics |
| schema_migrations | Applied version IDs |

Indexes: `raw_chronological(received_at,id)` supports recovery/replay; `punch_identity(scope,source,station_id,sequence,uid,station_timestamp)` supports retry detection. SQLite also indexes unique raw_event_id and UID primary key.

Raw insertion commits independently before parsing. Normalized insertion, duplicate decision and raw status update then share a transaction. A crash between commits leaves pending raw data, processed on run/replay startup. Parser failures are marked failed/malformed and remain available for explicit replay. Subscribers run after commit; delivery is best effort, not exactly once.

## Duplicate rule and limitations

Exact `(scope, source, station_id, sequence, normalized_uid, original_station_timestamp)` matches the earliest nonduplicate punch. RSSI, callsign and PC receive time are excluded. Firmware retries resend the stored packet unchanged. Changed sequence or timestamp preserves a new visit; uint16 wrap alone does not collide when timestamp changes.

A reboot with identical sequence, UID and timestamp can collide. Firmware exposes no boot/session ID, so perfect disambiguation is impossible. Changing port/source changes identity; use consistent source labels for a base. Duplicates are never deleted. Each replay has a fresh scope and detects retries within that replay without contaminating live identity.

Replay appends rows with original receive times, replayed=1 and original_raw_id provenance. Original
rows never change. Repeated replay grows the database intentionally. Use one ingest/replay/bridge/live
writer process; SQLite serializes transactions but multi-process event ownership is not implemented.

## M2 migration

Migration 1 is unchanged. Opening an M1 database applies migration 2 transactionally without rewriting
any raw events or punches. The migration is covered by an actual v1-to-v2 upgrade regression test.
Back up before upgrade: M1 binaries reject a v2 database; there is no destructive downgrade tool.

| Added table | Purpose |
| --- | --- |
| bridge_uid_maps | Versioned canonical UID → explicit card number; soft `active` flag |
| bridge_station_maps | Versioned Fox station → control code and CONTROL/START/FINISH role |
| bridge_offsets | Next synthetic 24-bit backup offset per target/control; allocate in steps of 8 |
| bridge_deliveries | Source punch FK, target, UTC creation/finish times, mapping FKs and frozen identity/role/offset/frame, status/error, output endpoint, automatic flag |
| bridge_output_state | Last recorded connection/detail/endpoint/time per stable target |

Partial unique indexes enforce one active mapping per UID, per card number and per Fox station.
Removing a mapping sets `active=0`, preserving historical FK audit data. Re-adding creates a new
version; adding an identical active mapping is idempotent. CSV imports are one transaction and
reject the entire import on an invalid/conflicting row. UID/card reassignment always requires an
explicit remove followed by add. There is no auto-allocation or hidden virtual-number range.

`bridge_once(target,punch_id) WHERE automatic=1` enforces one automatic reservation for each source
punch/target across restarts. `bridge_status(target,status,id)` supports diagnostics. Reservation,
mapping lookup/snapshot, frame construction and offset increment share `BEGIN IMMEDIATE`. A failed
encoding does not consume an offset. Offsets never silently wrap; exhaustion is an encoding error.

Statuses: `queued`, `writing`, `sent`, `failed`, `uncertain`, `mapping_error`, `encoding_error`,
`duplicate_ignored`, `replay_blocked`. The internal `reserved` status is completed within the preparation
transaction and is not a committed intermediate state in normal operation. `writing` is committed
before the external write. A crash after write but before `sent` remains ambiguous and is **not** retried.
No old queue is loaded at startup. Source rows are never modified by bridge delivery.

Explicit resend creates `automatic=0` with a new audit row. If a previous frame exists for that
punch/target, it freezes the same card/control/time/offset/frame, including after mapping changes.
Otherwise it resolves current mappings (for example after repairing a mapping failure). Resend can
duplicate receiver data and requires operator review. Replayed sources also require the replay flag;
FoxCore duplicate sources are not emitted even by resend. `sent` is driver/file-write success only.

Changing the target name establishes a distinct delivery identity, not a harmless display rename.
Keep it stable across port changes. Failed/unmapped rows are retained indefinitely; mapping repairs
do not trigger automatic resend. Diagnostic status contains last persisted states, not process liveness.

## M3 migration and immutable interpretation boundary

The following describes original migration 3. Migration 4 below supersedes its event-local
registration/cache tables without rewriting the migration or deleting those historical records.

Migrations 1 and 2 are unchanged. Additive migration 3 creates only `live_*` tables/indexes; a genuine
v2 upgrade test checks preserved raw/punch facts and foreign keys. FoxBridge tables are untouched.
Back up before opening with 0.3.0: older M1/M2 binaries reject schema 3. No downgrade is implemented.

| Added table | Purpose |
| --- | --- |
| live_events | Metadata, lifecycle/timing mode, canonical UTC windows/default start, persisted timestamp guards, source-ID cursor and UTC creation/update times |
| live_categories | Event code/name/active/display order |
| live_participants | Event bib/name/category, optional canonical UID/club/predefined start, active flag, optional operator status override, UTC creation/update times |
| live_event_stations | Event Fox station ID/name/role/enabled/order; no SI codes |
| live_event_punches | Explicit `(event_id,punch_id)` association FK to immutable FoxCore punch, cached canonical UID for lookup, UTC association time, origin live/recovery/historical |
| live_punch_interpretations | Derived status, role, participant and reason per association |
| live_results | Rebuildable typed JSON participant timing/control/status/rank cache |
| live_manual_exclusions | Event/punch exclusion with mandatory reason and UTC creation time |
| live_audit_events | UTC operator label/action/entity/before/after/reason history |

`live_one_running` is a partial unique index for one RUNNING event. Event/category code and event/bib
are unique; `live_active_uid` permits one active canonical UID per event. Composite foreign keys keep
category/participant/interpretation/result relationships in the same event. Event stations and source
associations use composite primary keys. `live_event_uid(event_id,uid,punch_id)` supports bounded UID
history reads; category and audit indexes support bulk rankings/history. All original source indexes
and duplicate semantics remain unchanged. Different events can reuse UIDs and explicitly associate
the same immutable source fact; an association itself is never duplicated inside one event.

Source raw/punch commits happen before FoxLive sees a punch. FoxLive commits association/cursor first,
then interpretation and results. Interrupted derivation is recoverable on restart because that
relationship is durable. Startup recalculates existing RUNNING associations and catches up only IDs
after its cursor, skipping replay copies. Startup does not emit historical punch notifications.
Starting/resuming snapshots the maximum source ID; CLOSED/ARCHIVED never auto-associate. An explicit
historical association operation is audited, transactionally validated and idempotent, with no source
insertion. Recalculation never invokes the append-only core replay function.

Interpretations/results are caches derived from event configuration, associations, immutable facts,
manual statuses and exclusions. Full calculation is deterministic; source time then ID determines
first timing/control visits. Sporting ties remain equal-rank; display bib/ID do not break them.
DNS/DNF/DSQ preserve data but are unranked. Administrative updates and recalculation/audit commit
atomically. UID/category/status/station/lifecycle/exclusion history is retained; post-close actions
carry an `after_close:` audit prefix. No destructive participant/category/event deletion exists:
deactivate or archive. A reasoned exclusion is not deletion of a source punch.

## M3 registration correction — additive migration 4

| Current table | Purpose |
| --- | --- |
| live_clubs | Reusable generated ID, optional unique nonblank code/DOK, name and active flag |
| live_runners | Reusable generated ID, person names, birth_year, optional birth_date, club FK, active flag and UTC creation/update times |
| live_category_master | Generated ID, code, English/German names, active flag and legacy needs_review flag |
| live_event_categories | Event/category composite key, enabled/order and event-specific code/bilingual name snapshots |
| live_entries | Generated entry ID, event/runner/category references, event start number/UID/start/status/active/check-in, person/club/birth snapshots and UTC creation/update times |
| live_entry_interpretations | Derived event/punch status/role/reason and event-entry FK; immutable source association remains live_event_punches |
| live_entry_results | Rebuildable typed result cache referencing event entries; API participant_id means entry ID |
| live_master_audit | UTC operator/action/entity/before/after for reusable person/club/category changes |

Runner owns no RFID, start number, competition category/status or start time. EventEntry owns them.
`live_entry_runner` and `live_entry_uid` are partial unique indexes among active entries per event;
event start numbers are unique even for inactive entries. Event/category and interpretation/result
foreign keys enforce event scoping. Check-in is independent of scoring. Master activity controls
availability for new selections; it does not deactivate existing registrations/category selections.
New category codes must not conflict with any existing master, including legacy review records.
`live_master_category_code` enforces uniqueness of reviewed/new codes; duplicate old codes are
preserved with needs_review rather than silently merged. Club codes are unique when nonblank.

Migration copies each old participant into one runner and one entry, preserving entry IDs. Names
alone cannot prove person identity; automatic merging is unsafe and not supplied. Birth data is
NULL for legacy records, displayed as unknown, and must be completed when editing the person.
Distinct exact old club text creates clubs with unknown DOK. Each old category becomes a master
plus event selection; exact names are copied into both languages because their language is unknown.
All legacy categories are marked for review. IDs and existing result JSON remain aligned; derived
cache contents are copied and can be deterministically rebuilt. Old live_categories,
live_participants, live_punch_interpretations and live_results remain untouched as legacy snapshots.
Existing event/source associations, exclusions, audit, cursors, FoxCore and FoxBridge tables remain.
Schema 4 has no downgrade; earlier binaries reject it. Back up first.

Registration edits audit/recalculate only the affected event. Runner/category master edits do not
silently rewrite existing registration/category label snapshots. New registrations use current
master data; deliberate runner reassignment refreshes person snapshots and is event-audited.
Inline runner+entry creation and CSV master/entry/audit changes use a single BEGIN IMMEDIATE
transaction, so a validation/storage failure cannot leave an orphan person or partially import.
Bulk ranking queries remain independent of participant count; no per-runner joins occur in live
scoring. All accepted timing, duplicate, exclusion and tie semantics remain unchanged.

## Backup

Stop ingest gracefully, then copy the closed database and any surviving WAL/SHM alongside it. Never copy only the main DB while a writer is active. Use SQLite/Python's backup API for online backup. Raw records are the recovery source and regression corpus; no automatic retention/deletion exists.
