# FoxSuite

FoxSuite is the offline PC-side suite for FoxIdent field stations and the FoxIdentServer USB base.
M1 provides shared `foxcore` infrastructure. M2 implements `foxbridge`, a minimal SPORTident live
compatibility gateway for FjwW. M3 adds `foxlive`, a standalone local competition desk. Neither
application replaces the complete Fjw software suite.

FoxBridge: Milestone 2 complete; FjwW SI-C compatibility manually validated on the tested Windows/VSPE setup.

Full FjwW competition workflow not tested.

FoxLive: M3 implemented and automatically tested; physical hardware/manual validation pending.

M4 adds a desktop operations layer and Windows release recipes; clean-Windows installer/USB
acceptance remains pending. M3 physical acceptance is not implied by M4 automated checks.

M5 adds DESFire capture import/simulation, offline recovery, evidence reconciliation,
review and audited jury decisions. Software validation uses simulated/imported tag data;
physical FoxIdent tag-readout integration is pending. M6 has not been started.

Runner RFID → FoxIdent → LoRa → FoxIdentServer → USB → foxcore → FoxBridge → COM pair → FjwW SI-C.

M1 includes typed TOML config, reconnecting serial, source-derived parsing, canonical punches/UIDs,
raw-first SQLite persistence/migrations, retained duplicates, mapping foundations, subscriptions,
TimeSync, replay, simulator and CLI. Its physical hardware acceptance was supplied by the user.
M2 adds explicit UID/SI-card and station/control mappings, extended D3 AUTOSEND encoding, explicit
timezone handling, serial/binary-capture output and persistent delivery audit/idempotency.
M3 adds reusable runners/clubs/categories, event registration/UID assignment, station roles, deterministic timing and
distinct-controls/time rankings, corrections/audit, CSV and an offline local browser desk. FoxLive is
a sibling consumer of FoxCore, not a FoxBridge client. No cloud, telemetry, CDN or frontend build exists.

## Installation and configuration

Normal Windows operation: install the self-contained FoxSuite installer, launch **FoxSuite** from
Start, complete EN/DE setup (COM selection/test/data location), and FoxLive opens in your browser.
No Python/Git/pip/TOML editing is needed. **System → Settings** manages connection, data folder,
backup/restore and safe shutdown. User data lives under `%LOCALAPPDATA%\FoxSuite`, separately from
installation/upgrades. See [Windows deployment and validation](docs/WINDOWS.md) and
[operations](docs/OPERATIONS.md). Windows installer production/acceptance still requires a Windows
release build; the repository includes PyInstaller/Inno Setup recipes, not a claimed tested installer.
On a Windows release machine with Python 3.12+ and Inno Setup 6, run
`.\packaging\windows\build.ps1` from a source checkout. It creates its own local build venv and
installs the declared build/test dependencies; see [one-command build setup](docs/WINDOWS.md#packaging-and-evidence).

### Developer installation (preserved)

Python 3.12+:

```sh
python -m venv .venv
# Activate the environment for your platform's shell.
python -m pip install -e '.[dev]'
foxsuite --help
foxsuite-desktop --help
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

## FoxLive

```sh
foxsuite --config config/foxsuite.toml live run
foxsuite --db data/live-test.db live run --no-serial --no-browser
foxsuite --config config/foxsuite.toml live status
foxsuite --config config/foxsuite.toml live recalculate EVENT_ID
foxsuite --config config/foxsuite.toml live export-results EVENT_ID
foxsuite --config config/foxsuite.toml live export-participants EVENT_ID
```

Open `http://127.0.0.1:8765/` (configurable). English is the default; the header's **English / Deutsch**
selector switches instantly and remembers the language in this browser. This changes presentation
only, never competition timestamps, event timezone or protocol data. Native date/time pickers include
localized captions and safe explicit DST choices; the prefilled IANA timezone is in advanced settings
(existing/saved/browser timezone, Europe/Berlin on appropriately configured German PCs).

Use **Event / Veranstaltung** for overview, participants, categories, stations, live and rankings;
**Master data / Stammdaten** for reusable-data cleanup/history; **System** for technical diagnostics.
The selected event name/date remains visible. Create an event and timing mode, enable its categories,
and configure CONTROL/START/FINISH stations. Existing categories need not be recreated.
Use **Add participant / Teilnehmer melden**: search an existing runner by name/birth year/club/DOK,
or create a runner inline with birth year (optional full date), then assign **Start number / Startnummer**,
category and start time. Searchable keyboard comboboxes show at most 20 choices; club/category creation
and enabling happen inline, without leaving registration. Duplicate matches are reviewed, not merged.
New club/person/registration save atomically; explicit category create-and-enable remains saved if
registration is canceled. Category labels show code – localized name; all internal keys are generated.
Runner is a reusable person; EventEntry is their registration for one event. UID belongs to EventEntry,
so the same person or tag may be reused in later events without changing historical assignments.
Use **Read RFID tag / RFID-Tag einlesen**, punch the tag, review station/time and confirm assignment.
Recent unassigned tags are selectable; manual UID entry is an advanced fallback. Assigned tags cannot
be silently moved from another active participant. Then start the event.
Only one event can be RUNNING. CLOSED stops new live association but permits audited corrections;
ARCHIVED is read-only. Old events are retained. Stop other serial readers before `live run`.

PUNCH_START_FINISH uses the earliest valid START and first FINISH at/after it. PREDEFINED_START uses
participant start, else event mass/default start. Controls count once; revisits and FoxCore retries
remain visible but do not add points. Finished results rank by controls descending then elapsed
seconds ascending, per category; exact ties use 1,2,2,4. Unfinished/DNS/DNF/DSQ are not ranked as
finishers. Unknown UID assignment and reasoned exclusion recalculate interpretation only: source
punches/timestamps are never edited, deleted or duplicated by FoxLive.

Browser administration includes CSV preview/atomic import, exports, history, audit and explicit
historical punch selection by tag/station/time (internal references are hidden in normal forms).
Recalculation never calls the append-only FoxCore raw replay.
WebSockets signal snapshot refreshes; no browser refresh is needed for new punches or ranking changes.
Participant/master tables offer search and 50-row pages. **Open live display / Live-Anzeige öffnen**
opens a separate read-only tab for monitor 2, with large results/punches, EN/DE, fullscreen and automatic
reconnect. It shares scoring state, but excludes raw RFID, COM/debug and administrative controls.
M3 assumes one trusted local operator process; non-local binding has no authentication and is unsafe
on untrusted networks. Back up the DB and TOML before upgrading to migration 5; older binaries reject it.
Legacy registrations are preserved conservatively as separate runners with unknown birth data;
legacy category names/codes need review. No identity is silently merged or birth information invented.
See [FoxLive](docs/FOXLIVE.md) for complete rules, offline test workflow, API and Windows smoke checklist.

### Offline readout and evidence (M5)

Event → **Readout / Finish / Auslesen / Ziel** imports captured DESFire snapshots or
runs the test simulator. Set the embedded 16-bit tag event number in advanced event
settings; it is not the database event ID. Valid tag-only controls recover lost
radio data. Matching any legitimate live revisit confirms evidence; a tag is not
a full chronological history. Source snapshots, live punches and manual decisions
stay separate and immutable. No new reader firmware or serial parser is included.

Event → **Review cases / Prüffälle** compares discrepancies. Select live/tag evidence,
exclude, explicitly accept control presence, or add a reasoned manual control/time
ruling. START/FINISH conflicts require review rather than silently changing elapsed
time. Unknown readout tags reuse existing registration/assignment. Participant
detail explains provenance; results/export add completeness/recovery/review indicators
without changing sporting ranks. All normal workflows support EN/DE.

```sh
foxsuite --db data/test.db live readout import EVENT_ID captured-readout.json
foxsuite --db data/test.db live readout simulate EVENT_ID 046365525C6180 --record 2:UNIX_SECONDS
foxsuite --db data/test.db live reconcile EVENT_ID
foxsuite --db data/test.db live review list EVENT_ID
```

See [verified tag layout and future firmware contract](docs/TAG_READOUT.md),
[reconciliation rules](docs/RECONCILIATION.md) and
[software acceptance procedure](docs/OPERATIONS.md#m5-software-acceptance--simulatorimport).
Only current FoxIdent DESFire format is supported; no other chip-family adapter,
blind tag/live priority or M6 visual redesign is implemented.

## Development and architecture

```sh
pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Tests require no hardware. M5 validates parser/provider, readout sessions, conservative
reconciliation, timing/manual review, source immutability, unknown-tag assignment,
restart, browser flows and event-scale data alongside all accepted M1–M4 regressions.
Run the complete Chromium-enabled suite with the command below; final M5 validation
results are recorded in [FoxLive](docs/FOXLIVE.md).
Final M5 gates: **344 tests passed including 17 Chromium workflows**; the separate
Python 3.13 run passed 327 with only those 17 browser tests skipped. Ruff/strict mypy,
sdist/wheel, clean offline installation and installed/Linux-frozen HTTP/WebSocket,
recovery/backup/restart smoke pass. No Windows or physical-reader acceptance is implied.
Lint, formatting, strict typing, sdist/wheel and clean offline installed-package
HTTP/WebSocket/simulator smoke pass. All 518
reference hashes remain unchanged. One upstream Starlette HTTPX deprecation warning is not suppressed.
See [FoxLive validation](docs/FOXLIVE.md) for evidence boundaries.

The dependency-free browser helper tests use Node.js if available (no npm/build required).
For the optional real-browser tests, install `.[dev,ui-test]`, provision Chromium once with
`python -m playwright install chromium`, then run `FOXSUITE_BROWSER_TESTS=1 pytest` (PowerShell:
`$env:FOXSUITE_BROWSER_TESTS="1"; pytest`). Browsers are development-test dependencies only, not runtime
requirements; pre-provision their local cache for offline testing. These simulated browser checks
do not claim physical FoxLive/Windows acceptance.
[Protocol](docs/PROTOCOL.md) separates source facts, discrepancies and assumptions.
[Architecture](docs/ARCHITECTURE.md) covers concurrency; [database](docs/DATABASE.md) covers
migrations/recovery/dedupe; [operations](docs/OPERATIONS.md) includes the hardware checklist.

Repository: read-only `reference/`; shared `src/foxcore/`; gateway `src/foxbridge/` (config, mapping,
encoder/time, delivery persistence/service, output and CLI); standalone `src/foxlive/` (domain,
scoring, persistence, service, readout/providers, evidence/reconciliation, CSV, API, CLI,
local templates/assets); operations `src/foxops/`
(desktop launcher, user settings, ports, backup/restore, setup assets); `packaging/windows/`
(maintainer build/bundle/installer recipes); hardware-free `tests/` with a published protocol vector;
`config/`; `docs/`. Flat modules avoid speculative future packages.

M2 transport acceptance is closed; full competition semantics, Start/Finish and long-running Fjw field
operation remain unvalidated. Serial write is not receiver acknowledgement, and explicit resend/replay
can duplicate competition data. FoxLive is implemented but its physical Windows desk acceptance and
long-running Windows field operation are still pending. M4 Windows installer execution, clean-PC
deployment/upgrade/uninstall and real USB first-run testing remain pending; Linux self-contained
bundle/installed-package checks are not Windows acceptance. Physical offline reader acquisition,
DESFire application/file provisioning and long-running readout desk acceptance remain pending.
Manual/review provenance is transparent, not an automatic guarantee of correctness; explicit jury
actions can change results and require reasons. No M6 feature or visual-polish work is included.
