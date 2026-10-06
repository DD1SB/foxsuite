# Changelog

## 0.2.0 — M2 implementation

FoxBridge consumes FoxCore punches and emits the minimal SPORTident extended D3 AUTOSEND subset.
Adds explicit versioned UID/card and station/control mapping with atomic CSV import, event-timezone
conversion and validation, serial/file/fake output, audited at-most-once automatic delivery reservations,
replay guards, operator resend and bridge CLI diagnostics. Migration 2 preserves all M1 source data.
Adds tzdata for offline IANA timezone support on Windows. Simulator CLI now defaults to PC current
time, with an explicit timestamp option for deterministic fixtures; its source-shaped format is unchanged.
Protocol research, published vectors, serial capture and automated integration tests are documented.
FjwW and physical Fox→Fjw validation are pending. FoxLive/M3 has not been started.

## 0.1.1 — M1 maintenance

Concise configuration/task-group error messages, early missing-port validation, optional compact
live punch logging and clarified relative DB paths. Core transport/ingest behavior is unchanged.

## 0.1.0 — Milestone 1

Verified protocol documentation and offline foxcore: transport, raw-first SQLite recovery, canonical parsing, UID/mapping foundations, dedupe, TimeSync, replay, simulator, CLI and hardware-free regression tests. FoxBridge and FoxLive remain unimplemented.
