# FoxSuite operations — FoxCore and FoxBridge

## Windows installation

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

Ctrl+C cancels TimeSync and closes serial/SQLite. Reconnect preserves partial fragments. Raw input commits before processing; disk/SQLite errors exit visibly. Fix capacity/permissions and restart to process pending rows. Parser failures retain status/error; replay after parser changes. Subscriber errors log without interrupting ingest; slow subscribers must enqueue work. Broken logging handlers cannot interrupt ingest.

Serial streams without newline buffer until newline or disconnect/shutdown; sustained corruption without delimiters can grow memory. In-memory incomplete fragments and hardware/OS buffers cannot survive abrupt process/power loss. Radio/firmware queue losses before PC reception cannot be recovered here. No automatic retention exists; monitor disk. See DATABASE for safe backups.

## Hardware validation boundary

The user reports M1 acceptance with physical FoxIdentServer/station/tag, PC TimeSync, station
TimeRequest/SyncPacket, USB reconnect and persistence across restart. Those observations precede
this task. This environment has not performed M2 Windows/Fjw or physical Fox→Fjw validation.
The checklist below remains available for explicit field revalidation and untested stress/failure cases.

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
on a POSIX pseudo-terminal. M1 hardware acceptance is user-reported. M2 Windows/Fjw compatibility
and full physical-chain acceptance are pending: use the [Fjw checklist](FJW_INTEGRATION.md).
