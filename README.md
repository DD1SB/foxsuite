# FoxSuite

FoxSuite is the offline PC-side suite for FoxIdent field stations and the FoxIdentServer USB base.
M1 provides shared `foxcore` infrastructure. M2 implements `foxbridge`, a minimal SPORTident live
compatibility gateway for FjwW; it does not replace Fjw competition software.

FoxBridge: Milestone 2 complete; FjwW SI-C compatibility manually validated on the tested Windows/VSPE setup.

Full FjwW competition workflow not tested.

FoxLive: not implemented yet

Runner RFID → FoxIdent → LoRa → FoxIdentServer → USB → foxcore → FoxBridge → COM pair → FjwW SI-C.

M1 includes typed TOML config, reconnecting serial, source-derived parsing, canonical punches/UIDs,
raw-first SQLite persistence/migrations, retained duplicates, mapping foundations, subscriptions,
TimeSync, replay, simulator and CLI. Its physical hardware acceptance was supplied by the user.
M2 adds explicit UID/SI-card and station/control mappings, extended D3 AUTOSEND encoding, explicit
timezone handling, serial/binary-capture output and persistent delivery audit/idempotency.
No scoring, rankings, categories, competition UI, cloud or telemetry exists.

## Installation and configuration

Python 3.12+:

```sh
python -m venv .venv
# Activate the environment for your platform's shell.
python -m pip install -e '.[dev]'
foxsuite --help
```

Copy `config/foxsuite.example.toml`, set the port and DB path, then:

```sh
foxsuite --config config/foxsuite.toml run
foxsuite --config config/foxsuite.toml send-time
foxsuite --db data/demo.db status
foxsuite simulate | foxsuite --db data/demo.db run --stdin
foxsuite --db data/demo.db db-info
foxsuite --db data/demo.db replay --speed 10
python -m foxcore.simulator
```

Windows installation/native pipeline instructions are in [operations](docs/OPERATIONS.md). Defaults are source-verified baud 115200 and `TIME <unix>\n`, refreshed every 60s. Relative TOML DB paths resolve beside the config. No application COM port is hardcoded. Runtime requires no Internet after installation.

## FoxBridge

Enable `[bridge]` in the copied TOML; configure distinct physical input and virtual output ports,
stable target name and explicit event timezone. Provision a virtual COM pair separately; FoxSuite
does not install drivers. FjwW opens the pair's **other** endpoint at a matching baud (default 38400).
The transport acceptance test required no additional competition configuration. For competition use,
configure runner/card and fox/control associations in Fjw separately; those workflows remain untested.

The user validated a real tag/station/LoRa/base path on COM3, FoxBridge output COM10 at 38400 with
Europe/Berlin, VSPE COM10 ↔ COM11 and FjwW SI-C on COM11. UID `046365525C6180 → 912345` and station
`1 → CONTROL 31` produced SI Status `SI-No=31`, `CN=912345`. An independent hardware-punch serial
capture passed protocol checks; no extra handshake was required for that observed live path.

The commands below use the simulator UID, not the real validation UID. Use separate test databases
for these mappings: both UIDs cannot actively map to the same SI number in one database.

```sh
foxsuite --config config/foxsuite.toml bridge uid-map add 04A78319BCDE12 912345
foxsuite --config config/foxsuite.toml bridge station-map add 1 31 --role CONTROL
foxsuite --config config/foxsuite.toml bridge station-map add 2 3 --role START
foxsuite --config config/foxsuite.toml bridge station-map add 3 4 --role FINISH
foxsuite --config config/foxsuite.toml bridge run --show-punches
foxsuite --config config/foxsuite.toml bridge status
foxsuite --config config/foxsuite.toml bridge deliveries
foxsuite --config config/foxsuite.toml bridge test-frame 912345 31
foxsuite --config config/foxsuite.toml bridge replay
```

No automatic virtual card allocation: explicit active SI identities must be unique. Unmapped or
invalid-time punches stay auditable and are not emitted. Automatic delivery is reserved once per
target/source punch; restart/reconnect never scans or silently resends old punches. Replayed punches
are blocked unless `--allow-replay-output` is explicit. `bridge resend PUNCH_ID` is operator-controlled
and can duplicate receiver data. `sent` means local write success, not Fjw acceptance.

For a safe offline test set output `type="file"` and its capture path, then:

```sh
foxsuite simulate | foxsuite --config config/foxsuite.toml bridge run --stdin
```

One cycle retains all 7 raw lines and 2 punches, marks the retry duplicate and emits one 19-byte frame
when mappings exist. CLI simulation uses current PC time; `simulate --timestamp UNIX_SECONDS` produces
fixed fixtures. Review [SPORTident evidence](docs/SPORTIDENT.md), [Fjw integration](docs/FJW_INTEGRATION.md)
and [M2 validation](docs/M2_VALIDATION.md) before connecting a real competition event.

## Development and architecture

```sh
pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Tests require no hardware. [Protocol](docs/PROTOCOL.md) separates source facts, discrepancies and assumptions. [Architecture](docs/ARCHITECTURE.md) covers concurrency; [database](docs/DATABASE.md) covers migrations/recovery/dedupe; [operations](docs/OPERATIONS.md) includes the hardware checklist.

Repository: read-only `reference/`; shared `src/foxcore/`; gateway `src/foxbridge/` (config, mapping,
encoder/time, delivery persistence/service, output and CLI); hardware-free `tests/` with a published
protocol vector; `config/`; `docs/`. Flat modules avoid empty or speculative future packages.

M2 transport acceptance is closed; full competition semantics, Start/Finish and long-running Fjw field
operation remain unvalidated. Serial write is not receiver acknowledgement, and explicit resend/replay
can duplicate competition data. FoxLive/M3 remains unstarted and requires explicit approval.
Future consumers must reuse FoxCore infrastructure.
