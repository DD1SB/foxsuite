# FoxSuite operations — FoxCore, FoxBridge and FoxLive

## Windows installation

The normal M4 path is the self-contained Windows installer and **FoxSuite** Start-menu shortcut.
No Python, Git, PowerShell, pip or TOML editing is needed on the event PC. First launch opens the
EN/DE setup wizard: select the described USB/COM port, test connection, accept the data folder,
finish and use FoxLive. **System → Settings** opens graphical configuration, backups and safe
shutdown. Browser/baud/reconnect/TimeSync interval/log detail are under Advanced. A test pauses the
existing reader briefly and retains all received bytes using FoxCore. Write success does not prove
firmware identity or acknowledgement. A saved USB VID/PID/serial on a changed COM port is offered
for confirmation; missing/ambiguous identity pauses reception until corrected. Without reliable
USB identity the explicitly chosen port remains the reconnect target.

Normal data is `%LOCALAPPDATA%\FoxSuite\data\foxsuite.db`; settings are in
`config\settings.toml`, rotating logs in `logs`, backups in `backups` below the same user root.
Installation is separately `%LOCALAPPDATA%\Programs\FoxSuite`. Upgrades/uninstall do not remove
competition data. Paths are absolute and independent of the Start-menu working directory.
Closing a browser does **not** stop the application; use **Settings → Shut down FoxSuite**.
M4 Windows release-build/clean-machine validation remains pending; build recipes and the exact
acceptance checklist are in [Windows operations](WINDOWS.md). M3 physical acceptance also remains
pending. No new hardware acceptance is claimed by Linux tests.

### Advanced/developer installation (unchanged)

Install Python 3.12+ and run in PowerShell from the repository:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item config\foxsuite.example.toml config\foxsuite.toml
.venv\Scripts\foxsuite --config config\foxsuite.toml run
```

Set the COM port shown in Device Manager. Baud defaults to source-verified 115200; pyserial defaults to 8N1 and no flow control. USB driver/reset/DTR behavior requires hardware validation. TOML paths are relative to its folder; `--db` paths are relative to the working directory. The example stores under `config/data`; use `../data/foxsuite.db` if preferred. Linux/macOS use `.venv/bin/foxsuite` and their actual device path. Runtime is offline. To install offline, pre-download dependency wheels elsewhere and use pip `--no-index --find-links`.

## CLI and TimeSync

Global options go before the subcommand:

Relative TOML database paths resolve beside the TOML file; `--db` resolves relative to the
working directory. `run --show-punches` logs compact punch summaries for field testing.
Expected errors print one concise ERROR message; tracebacks require logging level DEBUG.

```text
foxsuite --config config/foxsuite.toml run
foxsuite --db data/demo.db status
foxsuite --db data/demo.db db-info
foxsuite --config config/foxsuite.toml send-time
foxsuite --db data/demo.db replay
foxsuite --db data/demo.db replay --speed 10
foxsuite simulate --count 3 --interval 0.2
python -m foxcore.simulator --count 1
```

`status` reports the **last recorded connection**, not live IPC or a hardware probe. `send-time` opens a separate session, waits 600ms for potential board startup, sends once, and closes; stop `run` first because Windows handles are exclusive. Write success does not claim firmware acknowledgement.

TimeSync defaults to `TIME {unix}\n`, positive uint32 UTC seconds, immediately on successful connection and every 60s while connected. Enabled, on_connect, interval and template are configurable. Disabled suppresses automatic sends; manual send-time still works. Connection changes cancel/restart the independent timer. Attempts/results are logged and persisted as diagnostics. If board reset loses the immediate command, periodic refresh should recover; inspect firmware `time` JSON. Base time acceptance and station Sync application are distinct. The base answers station TimeRequest; PC time-setting does not broadcast. Change the template only for explicitly changed firmware.

## Simulator and replay

Simulator prints source-shaped tag/retry/time_request/time/sync lines plus deliberately synthetic unknown/malformed probes. It does not emulate USB/LoRa or consume time commands; FakeTransport tests exercise bidirectional TimeSync independently. No Unix PTY is required.

CLI timestamps default to current PC Unix time. Use `simulate --timestamp 1770000000` for deterministic
fixtures; old fixed timestamps can deliberately fail the bridge's stale-time guard. Python `messages()`
still defaults to the fixed regression timestamp. All timestamp-bearing simulator lines use the chosen
value; each subsequent cycle increments it by one second.

POSIX:

```sh
foxsuite simulate | foxsuite --db data/demo.db run --stdin
foxsuite --db data/demo.db db-info
foxsuite --db data/demo.db replay
```

PowerShell may alter native pipeline encoding; use cmd.exe for a native byte pipeline:

```powershell
cmd /c ".venv\Scripts\foxsuite simulate | .venv\Scripts\foxsuite --db data\demo.db run --stdin"
```

One cycle gives 7 raw rows, 2 punches and 1 duplicate. Replay adds another 7 raw rows/2 punches in a fresh scope, including malformed/unknown input. Speed 0 is immediate, 1 follows original delays, 10 is ten times faster. Original records are untouched.

## FoxBridge configuration and mappings

Use the same TOML/database as FoxCore. Enable `[bridge].enabled=true` for `bridge run` and keep
`target="fjww"` stable across restarts and port changes. The target is a persistent delivery identity,
not a display label. Set `[bridge.output].type="serial"`, the bridge side of a user-provisioned COM
pair and baud 38400; Fjw opens the other endpoint at the same rate. Never share an endpoint or use
the physical base port as output. Driver installation is not performed; Windows driver/Secure Boot
compatibility remains operator responsibility. See [Fjw integration](FJW_INTEGRATION.md).

The manually validated Windows layout is physical base COM3, FoxBridge output COM10 at 38400,
VSPE pair COM10 ↔ COM11 and FjwW SI-C receiver COM11, with timezone Europe/Berlin. The real tag UID
`046365525C6180` mapped to card 912345, Fox station 1 to CONTROL 31. SI Status showed `SI-No=31`
and `CN=912345`; no extra handshake or Fjw competition configuration was needed for protocol
acceptance. These are tested assignments, not hardcoded defaults or proof for other virtual drivers.
Close a diagnostic COM11 capture before Fjw opens that endpoint; never let both hold it at once.

For diagnostics instead use `type="file"` and `path="data/bridge-capture.bin"`; frames append to this
binary capture and are fsynced, without opening any Fjw port. TOML capture paths, like DB paths,
are relative to the config folder. `test-frame` only prints hex and never opens output.
The installed `tzdata` dependency supplies offline IANA timezone rules on Windows.

```text
foxsuite --config config/foxsuite.toml bridge uid-map add 04A78319BCDE12 912345
foxsuite --config config/foxsuite.toml bridge uid-map list
foxsuite --config config/foxsuite.toml bridge uid-map remove 04A78319BCDE12
foxsuite --config config/foxsuite.toml bridge station-map add 1 31 --role CONTROL
foxsuite --config config/foxsuite.toml bridge station-map add 2 3 --role START
foxsuite --config config/foxsuite.toml bridge station-map add 3 4 --role FINISH
foxsuite --config config/foxsuite.toml bridge station-map list
foxsuite --config config/foxsuite.toml bridge station-map remove 1
foxsuite --config config/foxsuite.toml bridge uid-map import uids.csv
foxsuite --config config/foxsuite.toml bridge station-map import stations.csv
```

CSV headers must be `uid,card_number` or `station_id,control_code,role`. Entire imports roll back on
any invalid/conflicting row. No automatic card-number allocation is supported; choose explicit
identities matching Fjw participants and check real-card collisions externally. Active card numbers
are unique. Reassignment requires explicit remove/add; removed versions remain in the audit history.
CONTROL codes are 20..254, START is 3, FINISH is 4 as documented by Fjw's manual.

## Bridge run, time and diagnostics

```text
foxsuite --config config/foxsuite.toml bridge run --show-punches
foxsuite --config config/foxsuite.toml bridge status
foxsuite --config config/foxsuite.toml bridge deliveries --limit 100
foxsuite --config config/foxsuite.toml bridge test-frame 912345 31 --timestamp 1770000000
```

Bridge live run reuses FoxCore's physical reader, raw-first persistence, dedupe and independent
TimeSync. It never scans history on startup; pending core raw recovery happens before subscription.
`--stdin` provides the same pipeline for native byte simulator input. Use a fresh test DB or inspect
its persistent ledger before expecting repeats. A default simulator cycle with valid mappings emits
one 19-byte frame, retains a duplicate and preserves malformed/unknown raw lines.

`[bridge.sportident].timezone` is explicit (default UTC, example Europe/Berlin), not the PC's implicit
local zone. Configure it to the event's wall-clock timezone. `week_counter` is 0..3, default 0;
Fjw date interpretation must be verified in the event. Integer Unix time gives zero subseconds.
Both occurrences of DST fall-back ambiguous local times are rejected because D3 cannot preserve
UTC offset/fold. Midnight/day and morning/afternoon are encoded; original Fox timestamps stay intact.
Default minimum timestamp is 2020-01-01 UTC; maximum difference from **original** PC receive time
is 86400 seconds. Configure these guards deliberately for event conditions; do not relax them merely
to make an unsynchronized station appear valid. A passing guard does not prove synchronization.

Status shows source/last core connection, last recorded output connection, delivery/error counts,
last sent punch and unresolved UID/station mappings. These are persisted diagnostics, **not** a
process-aliveness probe. `sent` means driver/capture success, not Fjw acknowledgement.

## Bridge failure and replay safety

Mapping/encoding errors skip one punch, preserve it and log concise messages. Repairing a mapping
does not resend history. Output disconnect is visible; reconnect delivers new punches only. An
unavailable port before write is `failed`; write interruption is `uncertain`. Abrupt crash can leave
`queued` or `writing`. There is no automatic retry of any of these states. Inspect Fjw/capture first:

```text
foxsuite --config config/foxsuite.toml bridge resend PUNCH_ID
foxsuite --config config/foxsuite.toml bridge replay
foxsuite --config config/foxsuite.toml bridge replay --speed 10 --allow-replay-output
```

Resend is explicitly authorized ONE punch and may duplicate Fjw data. Previously encoded identity,
time, offset and frame are reused even if mappings changed. A previously unencodable/unmapped punch
uses repaired current mappings. Core transport duplicates remain suppressed. Replayed-source resend
also requires `--allow-replay-output`.

Default `bridge replay` appends replayed core records/diagnostics but does **not open output**.
The explicit output flag can duplicate the whole replay in Fjw; use isolated test events. Plain M1
`replay` has no bridge subscriber/output at all. Replay/restart never overwrites original raw records.
Do not run two ingest/bridge writers against the same DB/target. Before upgrading to migration 2,
back up the closed database; old M1 code cannot open version 2. Graceful Ctrl+C records interrupted
delivery where possible, closes output/core serial and stops TimeSync; a non-empty unsent queue is
operator-recoverable, not automatically restarted. `--stdin` is intended for finite byte pipelines,
not interactive blocked-input operation.

Keep the physical source COM assignment stable too: source label is part of FoxCore's duplicate key.
Changing it can turn a newly received old retry into a different source punch. The bridge cannot
infer a source identity that the firmware does not provide. A new target or database also creates
new delivery identities; neither is a safe workaround for uncertain writes.

## Recovery, troubleshooting and shutdown

### Graphical backup/restore and data-folder changes

In desktop **Settings**, create a backup, download it to another disk/USB, or import a `.foxbackup`
file and explicitly restore it. Archives contain an online SQLite snapshot (including committed WAL
data), settings snapshot, manifest and SHA-256 checksums. Import/restore reject unsupported/corrupt
databases, invalid archive members and checksums. Browser import is limited to 512 MiB compressed,
8 GiB total uncompressed contents. Backups include all core/bridge/live data, mappings, history and
audit; these are whole-database backups, not single-event exports. No cloud or automatic pruning.
Restore preserves this machine's current serial/HTTP settings and makes a safety backup first.
Only restore backups you trust; checksums detect corruption, not malicious provenance.

Backup/import archives and completed copy/restore database files are explicitly flushed through
writable, non-truncating handles before publication, including on native Windows. Flush failures
abort the operation rather than silently accepting an undurable file. Keep the current data and
safety archives until the operation has succeeded; see the filesystem audit in [WINDOWS](WINDOWS.md).

**Change data location** shows the current folder and offers Copy, Move, or Use existing database
at destination. Use the Windows folder chooser or enter an absolute folder in Advanced. The database
filename for a new location is `foxsuite.db`. Copy/Move reject an existing destination rather than
overwriting it; Use existing rejects a missing/invalid database rather than creating an empty one.
Move keeps `foxsuite-moved-<reference>.db` at the old location as a recovery copy (the original
filename remains if its rename is unavailable, with a log warning). Backups stay in
the original per-user backups folder. A safety backup precedes all changes; the source and database
close before switching, and the browser reconnects. Canceling confirmation changes nothing.
Do not run another CLI/writer against either database during restore/location changes.
If an operation fails, Settings shows its error after reconnect; inspect the log and retained
original/backup. Failed configuration save does not activate the new path. Keep adequate disk space
for original, snapshot, archive and safety copy; use local SQLite storage, not a cloud-sync folder.

Desktop settings precedence is defaults → saved per-user settings → explicit `foxsuite-desktop
--config custom.toml`. An explicit override is read-only in graphical settings; existing developer
`foxsuite --config ...` commands still use their original config and relative-path behavior.
Use `foxsuite-desktop --user-directory ABSOLUTE_FOLDER --no-browser` for isolated diagnostics.
Only one desktop instance per user root is allowed, with an OS lock released even after a crash.
Back up settings/DB and CSV exports before upgrades; never open a newer schema with an older binary.

Ctrl+C cancels TimeSync and closes serial/SQLite. Reconnect preserves partial fragments. Raw input commits before processing; disk/SQLite errors exit visibly. Fix capacity/permissions and restart to process pending rows. Parser failures retain status/error; replay after parser changes. Subscriber errors log without interrupting ingest; slow subscribers must enqueue work. Broken logging handlers cannot interrupt ingest.

Serial streams without newline buffer until newline or disconnect/shutdown; sustained corruption without delimiters can grow memory. In-memory incomplete fragments and hardware/OS buffers cannot survive abrupt process/power loss. Radio/firmware queue losses before PC reception cannot be recovered here. No automatic retention exists; monitor disk. See DATABASE for safe backups.

## Hardware validation boundary

The user reports M1 acceptance with physical FoxIdentServer/station/tag, PC TimeSync, station
TimeRequest/SyncPacket, USB reconnect and persistence across restart. Those observations precede
M2 closure. The user has now also supplied successful M2 Windows VSPE serial capture, real Fox live
hardware path and FjwW SI-C decoding observations, recorded in [M2_VALIDATION.md](M2_VALIDATION.md).
The Linux agent records that evidence rather than claiming it performed the Windows test. Full Fjw
competition setup, participant/card assignment, competition fox mapping, result calculation,
Start/Finish competition semantics and certificate/result workflows were not tested. These are
outside the accepted M2 transport test and do not prevent closure.

Remaining field risks: no receiver acknowledgement after write; explicit resend/replay can intentionally
duplicate Fjw data; Start/Finish and long-running Fjw operation are unvalidated. Reconnect, retry,
revisit and restart have automated/M1 evidence as documented but were not newly field-tested against
Fjw in the supplied single-punch observation. Other versions/drivers and event date/week semantics need
separate validation. The checklist below is for future revalidation/stress testing, not outstanding M2
transport acceptance. FoxLive's separate M3 acceptance remains pending; see its checklist below.

- [ ] Connect actual FoxIdentServer; record board/firmware/USB driver versions.
- [ ] Verify 115200 baud, 8N1, reset/DTR on Windows.
- [ ] Compare actual received tag JSON, UID, callsign and RSSI with fixtures.
- [ ] Verify malformed/debug/non-UTF8 lines preserve bytes and later ingest continues.
- [ ] Repeatedly unplug/replug USB and inspect reconnection/fragment preservation.
- [ ] Verify immediate, periodic, disabled and manual TimeSync operations.
- [ ] Observe base time confirmation and station TimeRequest response.
- [ ] Verify field station receives and applies resulting SyncPacket.
- [ ] Exercise retry, legitimate revisit, reboot and sequence wrap behavior.
- [ ] Run many hours at representative volume; inspect disk/memory/time drift.
- [ ] Validate disk-full recovery, safe shutdown, backup and restore.

Evidence labels: Fox protocol is source-code verified; core/bridge fake transports are unit tested;
stdin pipeline is simulator tested; published D3 framing is regression-tested and serial-capture tested
on a POSIX pseudo-terminal. Independent Windows serial validation, real Fox hardware delivery and
real FjwW SI-C acceptance are user-supplied manual evidence for the tested VSPE configuration.
Full competition workflows remain untested: see [Fjw integration](FJW_INTEGRATION.md).

## FoxLive startup and administration

The desk has three top-level areas: **Event / Veranstaltung**, **Master data / Stammdaten**, and
**System**. Open an event once; its name/date remains in the header. Event tabs contain overview,
participants, enabled categories, stations, operator live and rankings. Master-data pages are for
cleanup/history, not prerequisites to check-in; System holds COM/source/debug and detailed health.

**Participants → Register participant / Teilnehmer melden** is a single event-local dialog. Search
runner name/year/DOK (20 keyboard-operable suggestions), select an existing person or create one
inline, select/create a club, select/enable/create a category, set start number/time and read/confirm
the tag. No master-data navigation round-trip is necessary. Near club/person matches ask for review;
exact normalized club duplicates are rejected, never merged. Club+new runner+registration commit
together; canceling that staged workflow leaves no new club/person. Category create-and-enable is
an explicit separate save and remains after cancellation. The dialog explains this distinction.
Participant tables have search/category/status/sort and 50-row pages; master tables have search,
counts/history and 50-row pages. Back/forward keeps forms within the opened event. Opening another
event intentionally cancels/reset registration to prevent assigning a tag across events.

Use Event → Live for operator details and unknown-tag resolution. **Open live display /
Live-Anzeige öffnen** opens a read-only window; move it to a second monitor and choose Fullscreen.
It shows participant visits and the same finished/provisional results, never RFID/COM/debug/admin
controls. Multiple windows update/reconnect independently without refresh. Each window can select
EN/DE; the origin's saved preference applies on reload. Without authentication this is not a secured
public endpoint: keep localhost or a trusted isolated network, never port-forward the server.

Back up the DB/config before opening 0.3.0: additive schema 3 cannot be opened by older M1/M2 binaries.
Stop other `run`/`bridge run`/`live run` processes before opening the physical base; one writer/owner
process is supported. FoxLive requires neither FjwW nor a virtual COM pair. Keep `[serial]`, DB and
TimeSync settings; add:

```toml
[live]
host = "127.0.0.1"
port = 8765
open_browser = true
operator = "event desk"
```

```powershell
.venv\Scripts\foxsuite --config config\foxsuite.toml live run
# Offline administration, no serial reader/browser launch:
.venv\Scripts\foxsuite --db data\live-test.db live run --no-serial --no-browser
```

Open the configured URL, default `http://127.0.0.1:8765/`. English is the default; switch **Language:
English / Deutsch** in the header at any time. This browser remembers the choice for that host/port,
without login or restarting FoxSuite. Language changes labels and date/time presentation only,
not user-entered names, persisted UTC timestamps, the event IANA zone, CSV columns or protocol data.

Create an event and choose Start/finish punches or Predefined start time. The advanced timezone is
prefilled from the selected event, previous saved preference or browser/PC timezone (UTC fallback);
German PCs configured for Europe/Berlin default accordingly. Verify it once rather than reentering it.
Date/start/window controls are normal browser pickers, with localized captions. Choose a first/second
occurrence with explicit offset for DST fall-back; nonexistent spring-forward times are rejected.
Saved unchanged times preserve their exact instant even on a language switch. Picker chrome follows
the browser/OS locale, while captions/tables follow FoxLive's selected EN/DE language.

Under **Reusable data / Stammdaten**, create categories with code and English/German display names,
and optional clubs/DOKs. Enable existing categories in event setup; no category recreation is required.
**Add participant / Teilnehmer melden** searches people by name, birth year or club/DOK, or creates
a runner inline (birth year or full birth date required). Then set event start number, category and
optional start time. A runner is reusable; tag/category/start number/status belong to their event entry.
Dropdowns show code – localized name; use **Start number / Startnummer** (CSV/API `start_number`).
For RFID assignment, select/create runner and enter start number/category, click **Read RFID tag / RFID-Tag einlesen**,
punch the tag, inspect the detected UID/station/time, then confirm and save. No assignment occurs
before confirmation. You can also select a recently seen unassigned tag; manual entry/removal is an
advanced fallback. Existing ownership by another active participant is rejected. For deliberate
reassignment, clear the old owner's tag first; replacing the target participant's prior tag asks for
confirmation and records history. Existing event punches are reinterpreted, never duplicated.
The unknown-tag dashboard also offers registration for an existing/new runner; choose the detected
tag and confirm after completing the registration. A tag used in a historical event is available
in a new event; only active ownership within the same event is rejected. Master edits do not change
existing event snapshots. Check-in is an organizer flag and does not affect scoring.

Before schema-4 upgrade, back up SQLite/config. Migration 3 is not rewritten. Original registration
records are retained; migrated runners have unknown birth data and are not merged based on names.
Complete birth information in reusable-data administration before editing a migrated person.
Migrated category names are retained in both languages, flagged for review; rename conflicting
master codes deliberately before reuse. Existing event labels and results remain unchanged.
Reading during DRAFT is registration only: the punch remains in FoxCore and does not silently become
competition data. An outstanding read cancels on event/entry change, connection loss or after two
minutes. Re-arm it after reconnect. See [FOXLIVE](FOXLIVE.md) for precise boundaries.

RFID assignment is independent of FoxBridge SI mappings. Optional windows are absolute,
inclusive instants. Event date is a label, not an implicit midnight filter. API/CSV timestamps still
use ISO 8601. Ambiguous/nonexistent naive API/CSV times and fractional seconds are rejected. No PC receive
time is substituted for a bad station time. The event's persisted validation thresholds can be
configured through the typed event API; defaults are 2020 minimum and 86400s receive skew.

Click RUNNING only after setup. Historical facts already in the DB do not enter automatically.
Recent punches, unknown tags, station activity, participant state and category standings update via
WebSocket without reload; open participant history also refreshes. Finished ranks are separate from
provisional/unranked states. With only CONTROL stations and no FINISH, expect provisional state, not
an official finished rank. Assign UNKNOWN UID to an existing entry; prior associations recalculate.
Edit/clear operator status as needed; DNS/DNF/DSQ never derive from lack of finish. Exclude only with
a reason. CLOSED stops association but permits visibly audited corrections; ARCHIVED is read-only.
Deactivation retains entries/categories, and no source timestamp editor exists.

```text
foxsuite --config config/foxsuite.toml live status
foxsuite --config config/foxsuite.toml live status --event EVENT_ID
foxsuite --config config/foxsuite.toml live recalculate EVENT_ID
foxsuite --config config/foxsuite.toml live associate EVENT_ID SOURCE_ID SOURCE_ID
foxsuite --config config/foxsuite.toml live export-participants EVENT_ID
foxsuite --config config/foxsuite.toml live export-results EVENT_ID
```

CLI status is a snapshot of persisted facts/diagnostics, not IPC or a device probe. Browser source is
the current local reader connection (or OFFLINE MODE), but TimeSync only confirms the last local
write; inspect firmware `time` JSON before inferring field synchronization. Export writes CSV to stdout (redirect using a UTF-8-capable
shell; in older Windows PowerShell explicitly choose `Out-File -Encoding utf8`). Browser downloads
are UTF-8. Import preview reports all row errors; valid import commits atomically without overwrite.
See [FOXLIVE](FOXLIVE.md) for columns, rules, API and offline simulator procedure.

CSV preview presents row-level problems and human-facing category/start-number labels. Column names
retain `start_number,first_name,last_name,category,uid,club,start_time` and add
`birth_year,birth_date,club_code`. Supply birth_year or full birth_date for each imported runner;
unique matching runners/clubs are reused, ambiguous matches require manual selection. All masters,
registrations and audits commit atomically. `category`
is the code, `uid` the RFID tag and `start_time` an ISO instant. Expanded technical details may contain
raw source/database references in English; ordinary registration and historical selection never
require typing database primary keys. Browser preferences are not part of the SQLite backup; exports
and backups retain genuine event data independently of the selected UI language.

Ctrl+C stops HTTP/WebSockets, independent TimeSync, core serial and SQLite. Restart keeps the RUNNING
event/configuration/audit, rebuilds caches and recovers interrupted associations after its cursor.
Unknown/disabled mappings are diagnostics, not fatal errors. Persistence/source failures are visible
in health/logs (HTTP writes return 503 for DB errors); stop, repair capacity/permissions and restart.
Do not ignore a latched processing error or run two readers as a recovery workaround.

Default binding is localhost; M3 has no authentication/RBAC/TLS. Changing `[live].host` to a network
address explicitly exposes competition data and administration. Use only a trusted local PC; do not
port-forward. There is no arbitrary-path HTTP file access, CDN or telemetry. Keep a backup of closed
DB plus TOML; online backup must use SQLite backup API. Participant/results CSV do not contain the
raw facts, associations or audit and are not a complete backup.

## FoxLive Windows hardware smoke test — not yet performed

Follow the extended setup/registration/live/second-monitor/restart checklist in the hardware/manual
smoke section of [FOXLIVE](FOXLIVE.md).
Use real RFID → FoxIdent → LoRa → base USB → FoxCore → FoxLive (no FoxBridge/Fjw/VSPE required).
Record Python/app/firmware/Windows/browser versions, COM port, event timezone and test source IDs.
M1 hardware and M2 SI-C acceptance remain valid evidence for those layers, not FoxLive validation.
During this test, also switch EN → DE → EN, reload to verify language preference, read/confirm a tag
in DRAFT registration, decline an assignment once, verify collisions are rejected, and inspect the
localized date/time and category labels. Automated Linux Chromium checks do not replace this Windows
physical acceptance test.
