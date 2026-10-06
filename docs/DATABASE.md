# SQLite schema, version 2

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
rows never change. Repeated replay grows the database intentionally. Use one ingest/replay/bridge
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

## Backup

Stop ingest gracefully, then copy the closed database and any surviving WAL/SHM alongside it. Never copy only the main DB while a writer is active. Use SQLite/Python's backup API for online backup. Raw records are the recovery source and regression corpus; no automatic retention/deletion exists.
