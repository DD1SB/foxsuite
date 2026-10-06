# SQLite schema, version 1

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

Replay appends rows with original receive times, replayed=1 and original_raw_id provenance. Original rows never change. Repeated replay grows the database intentionally. Use one ingest/replay writer process; SQLite serializes transactions but multi-process event ownership is outside M1.

## Backup

Stop ingest gracefully, then copy the closed database and any surviving WAL/SHM alongside it. Never copy only the main DB while a writer is active. Use SQLite/Python's backup API for online backup. Raw records are the recovery source and regression corpus; no automatic retention/deletion exists.
