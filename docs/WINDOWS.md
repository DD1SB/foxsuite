# Windows operations (M4 design and validation boundary)

Normal operation uses a self-contained, per-user Windows installer and **FoxSuite** Start-menu
shortcut. After first-run setup, the desktop launcher opens the **FoxSuite Control Center** on
localhost. FoxLive is the competition module and FoxBridge is the SPORTident module, both consuming
the shared FoxCore ingest in one process. There is one FoxIdentServer reader, store and parser.
The developer `foxsuite --config ...` CLI remains unchanged.

## Control Center and runtime ownership (M4.1)

The Control Center at `/` shows the receiver's current connection/reconnection/error state, input
port, last message/error and TimeSync result; **Reconnect** closes the owned reader before reopening
it. Missing/ambiguous saved USB identity keeps reception paused and directs the operator to Settings.
**Open FoxLive** opens the existing desk at `/live`; its running event and processing error are shown
separately from source health. The desk links back to FoxSuite.

FoxBridge shows its actual worker/output state, endpoint, queue, last delivery and delivery counts.
**Start/Stop** persists the desired startup state in normal desktop settings. Bridge Settings supports
the virtual output COM port or absolute binary-capture path, baud, target, timezone, week counter and
the existing explicit UID/SI-card and station/control mappings. Provision a virtual COM pair separately;
FoxSuite does not install drivers. The output cannot be the input COM port, including case/device-prefix
aliases. Sent means a driver write, not FjwW acknowledgement. Stopping unsubscribes Bridge before
closing output, records interrupted/pending deliveries, and does not interrupt the receiver or FoxLive.
Starting or restarting never automatically sends historical punches or retries uncertain writes.

**System** provides settings, backups, recent diagnostics, version and the existing log location.
**Restart FoxSuite** replaces the owned runtime/server inside the same process after closing source,
TimeSync, Bridge output and SQLite. **Exit FoxSuite** closes those components and ends the process.
Closing browser windows leaves the owned runtime running; reopening the Start-menu shortcut returns
to the Control Center using the existing single-instance lock. There are no hidden module processes.
Do not run a developer CLI serial reader alongside the installed runtime against the same receiver.

With an explicit configuration override, settings/mappings remain read-only. Reconnect, restart, exit
and temporary Bridge start/stop still work; temporary module controls do not rewrite the override or
saved settings. A new process reloads the override's desired state. Details and validation boundaries
are in [M4.1 runtime composition](M4_1_RUNTIME.md). This milestone does not start M6 visual redesign.

## Locations and precedence

Windows user root: `%LOCALAPPDATA%\FoxSuite`. Settings: `config\settings.toml`; default database:
`data\foxsuite.db`; rotating logs: `logs\foxsuite.log`; backups: `backups`. Installation is separate:
`%LOCALAPPDATA%\Programs\FoxSuite`. Upgrades/uninstall do not remove the user root. Normal runtime
needs no administrator rights. On other systems the desktop launcher uses `$XDG_DATA_HOME/FoxSuite`
(or `~/.local/share/FoxSuite`). Paths saved by the launcher are absolute.

Desktop precedence: application defaults, then saved user settings, then an explicit `--config`
override. Explicit overrides are read-only in the graphical settings; edit that file through the
advanced/developer workflow, or relaunch without the override. This avoids unexpectedly overwriting
advanced configuration. The existing CLI retains its documented relative-path semantics.

## First run and serial identity

An incomplete configuration opens setup, not a serial error. Choose EN/DE, refresh/select an
enumerated port, explicitly test, accept/change the data location and finish. USB description,
manufacturer, VID/PID and serial number are retained when available. A unique matching VID/PID/
serial number on a different port is **offered**, never automatically selected/opened. Missing or
ambiguous USB identity needs manual selection. An open port and successful `TIME <unix>\n` write
are not a firmware acknowledgement or proof of device identity. Test input uses FoxCore raw-first
persistence in the current database, including malformed/debug lines.
Port changes retain FoxCore's existing `serial:<port>` source/deduplication semantics. USB identity
metadata helps selection, not LoRa packet identity; an old retry on a newly confirmed port may have
a different source key. See the accepted bridge recovery/source warning in OPERATIONS.

## Data safety

Backups use SQLite's online backup API, not a copy of a live WAL database. An archive contains a
consistent database, settings snapshot, manifest and SHA-256 checksums. Restore validates archive
members, integrity and supported schema before any replacement. Restoring restores competition
data, not old COM/HTTP/device settings. A safety backup precedes restore and data-location changes.
Data-location actions are explicit: copy current data, move current data (retain a recoverable old
copy), or use a validated existing destination database. They stop the source and close SQLite
before switching. Copy/move never overwrite an existing destination database. Cancellation or
validation failure leaves the current data location unchanged. Do not run the developer CLI or
another FoxSuite instance against the database while changing/restoring its location.
Move publishes the new settings before renaming the old recovery copy, eliminating a crash window
in which the old configured path could disappear. If the recovery rename fails it remains under
its original filename with a warning; the successfully committed new data location stays active.

### Filesystem durability audit

Completed staging files use `foxops.files.sync_file`: reopen **`r+b`**, call the real `os.fsync`, then
close the handle before publication. No creation/truncation, permission bypass or ignored flush
failure is involved. A read-only `rb` handle is only used for reading/checksums, never for flushing.
Python uses Windows' `_commit` for `os.fsync`; Windows file-buffer flushing requires write access.
See [Python fsync](https://docs.python.org/3.13/library/os.html#os.fsync) and
[Microsoft FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers).

| Path | Flush and publication order |
| --- | --- |
| Settings and running-instance marker | `mkstemp` writable descriptor; write, Python `flush`, `fsync`, close, replace in the same directory |
| Backup | Close SQLite snapshot connection, validate/flush snapshot; close complete ZIP, flush ZIP, replace on destination volume |
| Copy/Move | Flush completed destination snapshot before replace; safety backup and source checkpoint retained; save settings before optional recovery rename |
| Use existing | Validate existing destination without replacing it; safety backup current data, checkpoint source, durably save settings |
| Restore | Validate/flush staged database before safety backup/checkpoint/shutdown and current-database replacement |
| Archive import | Close uploaded archive, validate contents, flush archive before publishing its generated backup name |
| FoxBridge capture | Existing unbuffered writable `ab` handle; real `fsync` after each complete write; unchanged |

All replacements retain the existing destination-volume staging strategy; handles owned by SQLite,
ZIP and flushing code are closed before replacement. Windows sharing/permission failures propagate;
the optional recovery-copy rename retains its existing warning-only handling *after* the new settings
and data are committed. No directory-descriptor `fsync` calls existed or have been added: POSIX-style
directory descriptors are not a portable Windows flushing interface. No existing file flush is
disabled on Windows. Flushed file contents and same-volume publication must not be confused with
a portable transaction over directory metadata/settings/data, or a hardware power-loss guarantee
independent of the filesystem/storage device. Recovery copies and safety archives remain essential.

## Packaging and evidence

Build the PyInstaller one-directory bundle and Inno Setup per-user installer on Windows. The
installer bundles the interpreter, dependencies, local assets and IANA timezone data; no Python,
Git, pip, shell or Internet is needed on the event PC. No USB/virtual-COM driver is silently installed.
Build tooling is for release maintainers, not operators. Signing/SmartScreen reputation and USB
drivers require release/Windows validation. Linux tests cannot prove a Windows installer works.

On a Windows x64 release machine with 64-bit Python 3.12+ and Inno Setup 6 installed, run from a
fresh source checkout in PowerShell:

```powershell
.\packaging\windows\build.ps1
```

No activated venv or globally installed Python package is required. A callable `python.exe` on PATH
is sufficient when it reports Python 3.12+ and 64-bit. The script tries it first (or accepts
`-Python 'C:\path\to\python.exe'`); `py.exe` is an optional fallback for discovering an interpreter,
and the Python launcher is not a prerequisite. The selected interpreter creates the isolated venv.
The script finds `ISCC.exe` on PATH, under Program Files or in the per-user LocalAppData Programs
directory (or accepts
`-Iscc 'C:\path\to\ISCC.exe'`), and gives an actionable error if either external tool is missing.
It creates/reuses `.venv-windows-build\` in the checkout, upgrades pip *there*, and runs
`python.exe -m pip install -e ".[dev]"` through that venv. The `dev` extra provides all Python build/test
dependencies, including setuptools, wheel, build, PyInstaller and Playwright; Inno Setup 6 is the
separately installed build tool. All Python build/test/package steps, including the frozen-app smoke
runner, use `.venv-windows-build\Scripts\python.exe`. On a later run it refreshes the dependencies; if
the venv is incomplete, exposes global packages or uses an unsupported Python, remove only
`.venv-windows-build\` and rerun.
The build host needs access to the required Python packages (Internet or configured local wheels);
the installed application still has no runtime network dependency. For optional Chromium tests, run
`.\.venv-windows-build\Scripts\python.exe -m playwright install chromium` after the first build
bootstrap, then set `$env:FOXSUITE_BROWSER_TESTS="1"` and rerun the build script. The default test
gate retains its existing optional-browser skips when that flag is unset.

The script checks tests/lint/format/strict types, builds wheel/sdist, bundles both windowed `FoxSuite.exe`
and optional console `foxsuite-cli.exe`, tests frozen CLI and desktop HTTP/WebSocket/backup/restart
startup with `packaging/smoke.py`, then compiles
`dist\installer\FoxSuite-0.5.0-windows-x64-setup.exe` and prints its SHA-256.
The folder `dist\FoxSuite` must be distributed as a whole if using the advanced portable path;
an executable alone is insufficient. Data still lives in the user root, not the portable folder.
Build-time dependencies/Internet are permitted on the release machine; runtime is offline.
The optional frozen CLI retains accepted M1/M2/M3 commands and explicit configuration.
No automatic cloud deployment, driver installation, installer signing or update download is added.
Reopening the Start-menu shortcut while the desktop is running opens its existing browser endpoint
instead of starting another reader/writer. Closing all browser windows does not stop the server.

## Windows manual acceptance (pending)

- [ ] On a clean Windows 11 x64 VM with no Python/Git and standard user rights, run the installer
  offline, inspect publisher/signing/SmartScreen behavior and launch the Start-menu shortcut.
- [ ] Verify first-run EN default; switch DE/EN and preserve language across launch/browser windows.
- [ ] Connect a real FoxIdentServer; check described COM enumeration, metadata and 115200/8N1.
- [ ] Test connection with raw/debug/malformed lines; verify raw preservation and actual firmware
  time response/station SyncPacket separately from a successful PC command write.
- [ ] Finish setup without a shell/TOML editor. Verify FoxLive opens on localhost and settings
  paths are independent of the install working directory, including a read-only install directory.
- [ ] Change USB socket/COM assignment and verify explicit identity confirmation, never arbitrary
  port selection. Check devices with no serial number and ambiguous USB identities manually.
- [ ] Complete the existing M3 event/registration/live RFID/scoring/second-monitor checklist in
  OPERATIONS; do not infer M3 acceptance from a successful setup test.
- [ ] Create/download/import/restore a backup with event data; compare source rows, audit and results.
  Try invalid/future/corrupt archives and verify current data remains intact.
- [ ] Copy/Move/Use existing data folders; cancel each confirmation; verify safety/recovery copies,
  no silently empty event history, and clear permission/disk-full/port-in-use errors.
- [ ] Restart, disconnect/reconnect USB, verify independent TimeSync and no historical re-emission.
- [ ] Run a program upgrade and uninstall/reinstall; verify settings, DB and backups survive.
- [ ] Confirm closing browser leaves reception running; graphical Shutdown releases COM/DB, and
  a later Start-menu launch recovers correctly. Exercise long-running field operation.

Primary references: [PyInstaller usage](https://www.pyinstaller.org/en/stable/usage.html),
[spec files](https://pyinstaller.org/en/stable/spec-files.html),
[Inno Setup non-admin privileges](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[pyserial port metadata](https://pyserial.readthedocs.io/en/latest/tools.html).

M1/M2 physical acceptance remains accepted. M3 physical Windows acceptance remains **pending**.
M4 clean-Windows install, first-run USB test, upgrade/uninstall preservation and backup/restore
acceptance must be performed on Windows before claiming operator deployment acceptance.
