# Changelog

## M4 maintenance — Windows release-build bootstrap

The Windows build script now selects a supported Python and Inno Setup compiler, creates/reuses an
ignored local build venv, upgrades pip and installs setuptools, wheel, build and the declared
dev/browser/PyInstaller extras inside it. Existing Python test, lint, type, package and frozen-app
smoke gates use that venv; Inno Setup compiles the installer afterward. PEP 517 requirements are
explicit in `pyproject.toml`. Missing external tools produce actionable errors. Global Python
packages and venv activation are no longer prerequisites. Native Windows installer validation is
pending.

## M4 maintenance — PTY test portability

The optional POSIX serial-capture test now has a type-checker-visible Windows skip guard as well
as its existing pytest platform marker. Strict mypy excludes unsupported `os.openpty`/`os.ttyname`
calls when targeting Windows; the real PTY test remains active on POSIX. A regression verifies the
Windows skip branch. No production behavior, type-checker settings or error suppressions changed.

## M4 maintenance — Windows filesystem durability

Completed backup archives now reopen with a non-truncating `r+b` handle before `fsync`, fixing the
native Windows/Python 3.13 `EBADF` failure. A small operations-only helper also flushes closed SQLite
snapshots, validated restore staging databases and imported archives before publication. Flush
errors remain visible; settings' writable-handle flush, same-volume replacements, safety backups
and recovery/configuration ordering are preserved. No Core/Bridge/scoring/schema changes.

Operations tests enforce Windows' writable-file requirement while still calling the real `fsync`
on all platforms. The guard reproduced exactly the nine reported failures before the fix, including
the cascading KeyError and message assertions. New regressions cover non-truncation, handle closure,
flush-error propagation and preservation of current data/settings when staging flushes fail.
Native Windows full-suite and `packaging\windows\build.ps1` validation remain required; passing Linux
tests does not establish a successful Windows build. See M4_VALIDATION for results and boundaries.
Linux correction checks: 36 operations cases and all 267 full-suite cases pass, including 14 Chromium
workflows; Ruff lint/format, strict mypy, wheel/sdist, offline installation and installed/frozen
desktop smokes pass. All 518 firmware hashes are unchanged. Native Windows packaging is pending.

## 0.4.0 — M4 Windows operations and deployment support

Adds a separate desktop operations composition (`foxops`) with per-user absolute settings/data/
logs/backups, atomic TOML saves, OS single-instance lock and Start-menu relaunch-to-browser behavior.
Graphical EN/DE first-run setup enumerates described serial ports with retained USB metadata, tests
through accepted raw-first ingest/TimeSync, selects the data location and opens FoxLive. Saved
VID/PID/serial on a changed/missing/ambiguous port requires confirmation; no arbitrary port is claimed.
System Settings offers connection, advanced intervals/logging/browser port, consistent online backup,
checksummed archive import/download/restore and explicit Copy/Move/Use-existing data-folder changes.
Safety backups, source/database shutdown, recoverable originals and failure-safe settings publication
protect data-location changes; restore preserves current machine connection settings. No migrations,
FoxCore/FoxBridge changes or competition-domain/scoring changes. Developer CLI remains unchanged.

PyInstaller onedir/windowed desktop plus optional frozen CLI and per-user Inno Setup installer recipes
bundle Python/dependencies/assets/timezones for offline Windows 11 x64 operation without Python/Git/
shell/TOML editing. Installation/upgrades/uninstall do not target competition data or install drivers.
Release-maintainer smoke exercises actual desktop setup, HTTP/WebSockets, backup/restore, data copy,
restart and graceful shutdown. Normal user logs rotate outside installation.

Validation: 254 tests pass, including all 14 Chromium workflows; 27 new operations/browser cases.
Ruff lint/format, strict mypy (63 source/test files), sdist/wheel, offline installation and Linux
self-contained bundle gates pass. All 518 reference hashes remain unchanged. Windows installer
compilation/execution, clean-PC/USB deployment and M3 physical Windows acceptance remain pending;
Linux checks are not hardware evidence. One upstream Starlette deprecation warning remains visible.

## M3 maintenance — event-desk information architecture

Separates Event operations (overview/participants/categories/stations/live/rankings), Master data
(runners/clubs/categories) and System (base/diagnostics/settings), with persistent event context and
meaningful deep links/back-forward navigation. Registration stays in one event-local dialog with
bounded, debounced, keyboard/mouse-accessible runner/club/category comboboxes and inline creation.
Enabled event categories are prioritized; existing global categories can be enabled/selectable
without duplicates. Category quick-create explicitly saves bilingual master data and event selection.
New club/runner/registration commit atomically; canceling a staged registration leaves no debris.
Exact normalized club duplicates are rejected; near clubs/people require review, never automatic merge.
Read/confirm RFID and unknown-tag reassociation retain the existing audited reinterpretation path.

Participant/master tables have search, 50-row pages, event filters/sorting, usage/participation counts
and historical snapshots. Operator Live retains useful punch/tag/station detail; technical source
data is under System. A separate `/live/display` window uses a restricted read-only HTTP/WebSocket
projection of the same results: no raw RFID/COM/audit/debug/admin data, large responsive presentation,
EN/DE, fullscreen, multiple clients and automatic reconnect. No new scorer, domain/schema migration,
runtime dependency, frontend build or FoxCore/FoxBridge behavior change.

Validation: 227 tests pass, including ten Chromium workflows (20 new cases plus updated accepted UI
checks). Synthetic coverage includes 500 runners, 200 clubs, 50 categories, 500 entries and 3,000
punches, with bounded rendering and bulk-query projections. Ruff lint/format, strict mypy (53 files),
sdist/wheel, offline installation and installed HTTP/WebSocket/simulator/restart/shutdown smoke pass.
All 518 firmware hashes remain unchanged. Physical Windows FoxLive acceptance/long-running field
operation remain pending; no later milestone started. One upstream Starlette warning remains visible.

## M3 maintenance — reusable master data and event registrations

Additive migration 4 separates Runner (person/birth information/Club-DOK) and global bilingual
Category from EventEntry (start number/category/RFID/status/start/check-in) and EventCategory.
Generated references remain hidden behind human-facing selections. One active registration per
runner/event, unique event start numbers and active event tags are enforced. Tags and runners can
be reused across events; historical registration/category labels remain snapshots.

Event registration offers searchable existing runners or atomic inline person creation, retaining
read/confirm RFID assignment, unknown-tag registration and deterministic reinterpretation. Reusable
runner/club/category administration and audit are separate from event setup. EN/DE catalogs cover
all new workflows; no age/category suggestion or federation rules were added.

Migration preserves original M3 records/cache/audit/source associations. Each old registration
becomes a separate runner with explicitly unknown birth information; old categories retain their
names in both languages and are marked for review. Duplicate legacy codes are retained, not merged.
CSV retains existing column names and adds birth_year, birth_date, club_code; birth information is
required for new person imports. Ambiguous matches require manual registration; master/entry/audit
changes commit or roll back together. Tests asserting the old event-local model were adapted;
accepted timing/ranking/duplicate semantics and FoxCore/FoxBridge behavior are unchanged.

Validation: 207 tests pass including four Chromium workflows; Ruff lint/format, strict mypy,
sdist/wheel build, clean offline installation and installed HTTP/WebSocket/simulator/restart smoke
pass. All 518 reference hashes remain unchanged. One unfiltered upstream Starlette warning remains.
FoxLive physical Windows hardware acceptance remains pending. Milestone 4 has not been started.

## M3 maintenance — operator UX and EN/DE localization

English-default local desk with immediate English/Deutsch selection and browser-persisted preference.
Central local JSON catalogs cover normal navigation, forms, tables, states/roles, validation,
confirmations, unknown tags and CSV help with English fallback; raw diagnostics remain technical.
Language changes presentation only, never event timezone, stored UTC times, user-entered domain
content, neutral enums or protocol data.

Start number / Startnummer replaces Bib. Category references are generated automatically and hidden;
selectors display code – name. Native date/time pickers have localized captions, preserve saved
absolute instants and require explicit DST-fold choices; gaps are rejected. Timezone is prefilled
and moved to advanced settings. Historical selection uses meaningful tag/station/time checkboxes,
not manually entered database IDs.

Read RFID tag captures the next original unassigned live tag, shows station/time and requires
confirmation before the existing audited participant update. Also supports recent unassigned tags,
DRAFT registration and advanced manual fallback. Ownership collisions are rejected; replacing a
participant's tag requires confirmation. Existing event history recalculates without source edits or
synthetic punches. No schema/domain/scoring/Core/Bridge redesign or new runtime dependencies.

Adds 25 automated cases: 190 pass on Python 3.12 including three Linux Chromium workflows; Python
3.13 passes 187 with optional browser checks disabled. Ruff lint/format, strict mypy, sdist/wheel,
clean offline installed-package smoke and all 518 unchanged reference hashes pass. FoxLive physical
Windows/hardware acceptance remains pending. No M4 work included.

## 0.3.0 — M3 FoxLive implementation

Adds the standalone offline FoxLive competition desk as a FoxCore sibling consumer, with additive
migration 3 and no changes to accepted parsing, serial, dedupe, TimeSync or SPORTident behavior.
Event lifecycle, inclusive windows, event-local timezone input/display, two timing modes, registration,
categories and per-event station roles are persisted. Immutable source associations feed deterministic
interpretation and DistinctControlsThenTime scoring with sporting ties; provisional/nonfinisher state
is separate. Unknown-UID reassignment, category/status/station changes and reasoned exclusions are
audited and recalculate without altering source facts. No timestamp edits or synthetic punches.

FastAPI/Uvicorn local desk, bounded WebSocket notifications, escaped local HTML/JS/CSS, typed APIs,
atomic UTF-8 CSV preview/import and participant/result export; extended `live` CLI. Restart recovers
the RUNNING event cursor and caches without treating history as new browser punches. Historical
source association is explicit and idempotent; appended FoxCore replay copies are ignored.
M1/M2 regression gates retained: 165 tests pass on Python 3.12/3.13; Ruff lint/format, strict mypy,
sdist/wheel, clean offline installed-package HTTP/WebSocket/simulator/restart smoke pass. All 518
reference hashes unchanged. Details in FOXLIVE.md; physical FoxLive/Windows/browser acceptance is
pending. Native FastAPI telemetry/environment exporters explicitly disabled. Derived scoring failure
never stops raw capture; source-storage failure remains explicit. No M4 work included.

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
