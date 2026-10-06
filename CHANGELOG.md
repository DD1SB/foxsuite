# Changelog

## M2 closure — successful Windows/FjwW SI-C validation

Recorded user-supplied manual validation of implementation commit
`31c3761df118370148175bc7cbabde8e48907b8b`: real RFID/FoxIdent/LoRa/base COM3 → FoxCore/FoxBridge
COM10 at 38400, Europe/Berlin → VSPE COM10 ↔ COM11 → FjwW SI-C. UID `046365525C6180 → 912345`,
station `1 → CONTROL 31`; SI Status displayed `SI-No=31`, `CN=912345`. Independent hardware-punch
capture verified the 19-byte D3 frame and CRC `7693`. Passive SI-C reception needed no additional
handshake or competition configuration for the observed path. M2 is complete for that transport scope.
Full competition workflow, Start/Finish semantics and long-running Fjw operation were not tested;
write acknowledgement/resend/replay risks remain documented. Documentation-only closure: no protocol
behavior, application code or reference firmware changed. Milestone 3 has not been started.

## 0.2.0 — M2 implementation

FoxBridge consumes FoxCore punches and emits the minimal SPORTident extended D3 AUTOSEND subset.
Adds explicit versioned UID/card and station/control mapping with atomic CSV import, event-timezone
conversion and validation, serial/file/fake output, audited at-most-once automatic delivery reservations,
replay guards, operator resend and bridge CLI diagnostics. Migration 2 preserves all M1 source data.
Adds tzdata for offline IANA timezone support on Windows. Simulator CLI now defaults to PC current
time, with an explicit timestamp option for deterministic fixtures; its source-shaped format is unchanged.
Protocol research, published vectors, serial capture and automated integration tests are documented.
At the initial implementation commit, manual FjwW and physical Fox→Fjw validation were pending;
the subsequent successful SI-C validation is recorded above. FoxLive/M3 has not been started.

## 0.1.1 — M1 maintenance

Concise configuration/task-group error messages, early missing-port validation, optional compact
live punch logging and clarified relative DB paths. Core transport/ingest behavior is unchanged.

## 0.1.0 — Milestone 1

Verified protocol documentation and offline foxcore: transport, raw-first SQLite recovery, canonical parsing, UID/mapping foundations, dedupe, TimeSync, replay, simulator, CLI and hardware-free regression tests. FoxBridge and FoxLive remain unimplemented.
