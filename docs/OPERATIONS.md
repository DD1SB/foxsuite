# M1 operations

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

## Recovery, troubleshooting and shutdown

Ctrl+C cancels TimeSync and closes serial/SQLite. Reconnect preserves partial fragments. Raw input commits before processing; disk/SQLite errors exit visibly. Fix capacity/permissions and restart to process pending rows. Parser failures retain status/error; replay after parser changes. Subscriber errors log without interrupting ingest; slow subscribers must enqueue work. Broken logging handlers cannot interrupt ingest.

Serial streams without newline buffer until newline or disconnect/shutdown; sustained corruption without delimiters can grow memory. In-memory incomplete fragments and hardware/OS buffers cannot survive abrupt process/power loss. Radio/firmware queue losses before PC reception cannot be recovered here. No automatic retention exists; monitor disk. See DATABASE for safe backups.

## Hardware validation checklist — not performed

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

Evidence labels: protocol is source-code verified; core/fake transport are unit tested; stdin pipeline is simulator tested. Physical serial/radio operation is not hardware verified.
