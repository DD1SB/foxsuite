# Windows operations (M4 design and validation boundary)

Normal operation uses a self-contained, per-user Windows installer and **FoxSuite** Start-menu
shortcut. The desktop launcher opens a localhost browser setup/settings page around the accepted
FoxLive application. It does not introduce another reader, parser, scorer or database schema.
The developer `foxsuite --config ...` CLI remains unchanged.

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

## Packaging and evidence

Build the PyInstaller one-directory bundle and Inno Setup per-user installer on Windows. The
installer bundles the interpreter, dependencies, local assets and IANA timezone data; no Python,
Git, pip, shell or Internet is needed on the event PC. No USB/virtual-COM driver is silently installed.
Build tooling is for release maintainers, not operators. Signing/SmartScreen reputation and USB
drivers require release/Windows validation. Linux tests cannot prove a Windows installer works.

On a Windows x64 release machine, install Python 3.12+, Inno Setup 6 and the project's
`.[dev,ui-test,windows-build]` dependencies in an isolated build environment. Run all existing
Chromium workflows (`FOXSUITE_BROWSER_TESTS=1`, Playwright Chromium installed), then
`packaging\windows\build.ps1 -Python PATH_TO_BUILD_PYTHON -Iscc PATH_TO_ISCC`.
The script checks tests/lint/format/types, builds wheel/sdist, bundles both windowed `FoxSuite.exe`
and optional console `foxsuite-cli.exe`, tests frozen CLI and desktop HTTP/WebSocket/backup/restart
startup with `packaging/smoke.py`, then compiles
`dist\installer\FoxSuite-0.4.0-windows-x64-setup.exe` and prints its SHA-256.
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
