# FoxSuite

FoxSuite is the offline PC-side suite for FoxIdent field stations and the FoxIdentServer USB base. Milestone 1 implements only **foxcore**, infrastructure shared by future applications.

FoxBridge: not implemented yet

FoxLive: not implemented yet

Runner RFID → FoxIdent → LoRa mesh → FoxIdentServer → USB serial → foxcore → future consumers.

M1 includes typed TOML config, reconnecting bidirectional serial, source-derived parsing, canonical punches/UIDs, raw-first SQLite persistence/migrations, retained duplicate detection, participant/station mapping foundations, isolated subscriptions, TimeSync, replay, simulator and CLI. No scoring, SPORTident, Fjw integration, UI, cloud or telemetry exists.

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

## Development and architecture

```sh
pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Tests require no hardware. [Protocol](docs/PROTOCOL.md) separates source facts, discrepancies and assumptions. [Architecture](docs/ARCHITECTURE.md) covers concurrency; [database](docs/DATABASE.md) covers migrations/recovery/dedupe; [operations](docs/OPERATIONS.md) includes the hardware checklist.

Repository: `reference/` read-only authoritative firmware and supplementary context; `src/foxcore/` config, events, protocol, dedupe, persistence, service, serial, timesync, participants, stations, replay, simulator, CLI and safe logging modules; `tests/`; `config/`; `docs/`. Flat modules keep M1 small without empty future packages.

Roadmap: future FoxBridge will consume canonical events/mappings for existing-software compatibility; future FoxLive will add standalone competition functionality. Neither has been started. Both must reuse foxcore serial, parsing, persistence, TimeSync, dedupe and event transport.
