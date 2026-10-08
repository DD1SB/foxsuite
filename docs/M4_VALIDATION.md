# M4 validation — 2026-10-08

Accepted baseline: `4cef9abdb8e0a87d80b24cf16c12b6e91c0a8abf`. M1/M2 acceptance remains
unchanged; **M3 physical Windows acceptance is still pending**. No M4 physical evidence supplied.

## Native Windows filesystem correction

The operator subsequently reported Windows 11 / Python 3.13: **9 failed, 230 passed, 15 skipped**.
The first traceback identified `data.backup` reopening a completed ZIP as `rb` before `fsync`, which
raises `OSError: [Errno 9] Bad file descriptor` on native Windows. An operations-test guard enforcing
writable regular-file descriptors (zero-byte access check followed by **real** `fsync`) reproduced
exactly the same nine failing tests on Linux, including the KeyError and message-assertion cascades.
The same tests passed after correcting the handle; those assertions were not weakened.

`foxops.files.sync_file` reopens completed files as `r+b` and closes the handle before replacement.
Closed database snapshots, validated restore staging files and imported backup archives also use it.
The [filesystem audit](WINDOWS.md#filesystem-durability-audit) records every flush/replacement path,
including settings, backup, Copy/Move/Use-existing, restore, import and unchanged FoxBridge captures.
No global fsync disabling, directory-fsync workaround, new migration or domain/protocol change.

New regressions exercise real platform flushes, preserved bytes, closed handles, failed staging
flushes, failure-safe settings and source data, and flush-before-publication order. These correction
checks were performed on Linux, not native Windows. The subsequent maintainer report below confirms
the native Windows filesystem failures are resolved; **release packaging remains pending**.
Required release-machine commands, using the same Windows Python/environment as the original failure:

```powershell
python -m pytest tests/test_operations.py -vv
python -m pytest -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src tests
.\packaging\windows\build.ps1
```

Run existing Chromium workflows as described in WINDOWS when their dependencies are installed.
Do not declare this Windows repair validated until the full native suite passes and `build.ps1`
reaches packaging; retain its complete test/build output as release evidence. The historical Linux
implementation results below are not evidence of a passing native Windows retest.

Correction checks performed here (Linux):

- `python -m pytest tests/test_operations.py -vv`: **36 passed**, including 13 new regression cases.
- Full Python 3.12 suite with `FOXSUITE_BROWSER_TESTS=1`: **267 passed, none skipped**, including
  all 14 Chromium workflows.
- Full Python 3.13 suite: **253 passed, 14 optional browser cases skipped** in that environment;
  those same browser cases were all executed in the Python 3.12 full suite.
- Ruff lint/format pass; strict mypy passes on 64 source/test files (65 including release smoke).
- Wheel/sdist and Linux PyInstaller bundle build; fresh offline wheel installation, installed
  desktop and frozen desktop HTTP/WebSocket/backup/restore/data-copy/restart/shutdown smokes pass.
- All 518 reference firmware hashes match the baseline; no FoxCore/FoxBridge/FoxLive changes.
- One existing upstream Starlette deprecation warning remains visible; no gate was weakened and
  no existing assertion or skip condition was changed.

**Not executed here:** native Windows full-suite retest, Windows `build.ps1`, Inno Setup packaging
and physical Windows acceptance. Linux bundle output is not a Windows release artifact.

## Native Windows PTY type-check correction

The maintainer subsequently reported **252 passed, 15 skipped, one upstream warning** on native
Windows, confirming the filesystem failures are resolved. Ruff passed. The build stopped at strict
mypy because the optional POSIX PTY test referenced `os.openpty` and `os.ttyname`, which are absent
from Windows' `os` types despite the test's existing runtime skip marker.

`test_serial_capture_through_os_device` now also checks `sys.platform == "win32"` and calls
`pytest.skip` before defining/executing its POSIX implementation. Mypy recognizes this branch and
its non-returning skip; the original POSIX runtime marker and actual capture assertions remain.
A regression exercises the Windows skip branch on Linux. No FoxBridge production changes,
type-checker setting changes, `type: ignore` additions or attribute-error suppressions.

Strict mypy is checked against both the Linux host and `--platform win32`; the latter reproduces
the reported errors before the fix and passes afterward. This is static Windows-target validation,
not a native Windows build. The maintainer must rerun `packaging\windows\build.ps1` to establish
progress through frozen-app/installer packaging. M3 physical Windows acceptance remains pending.

Correction gates: complete Linux suite **268 passed, none skipped**, including all 14 Chromium
workflows and real PTY capture; Ruff lint/format pass; strict mypy passes for Linux and Windows
targets (also Windows/Python 3.13). All 518 reference hashes remain unchanged. The existing upstream
Starlette warning remains visible. No production files or quality settings changed.

## Native Windows release-build bootstrap

The maintainer's next Windows run passed **253 tests**, skipped 15 platform/optional cases, and
passed Ruff and strict mypy. The package build then stopped because the caller's Python did not
have `setuptools.build_meta`; no frozen application or installer was built in that run.

The Windows build script now creates/reuses `.venv-windows-build`, upgrades pip there, installs the
declared setuptools/wheel/build tools and `.[dev,ui-test,windows-build]` extras there, and uses that
interpreter for every existing gate. It finds a supported base Python and an Inno Setup 6 compiler
before installing packages. The PEP 517 backend and wheel requirement are explicit in `pyproject.toml`.
On Linux, PowerShell syntax and the interpreter/compiler helper behavior passed with PowerShell.
The complete Python 3.12 suite passed **268 tests with all Chromium workflows enabled**. A clean
Python 3.12 venv started without setuptools, upgraded pip, installed the declared backend and extras,
then passed its default suite (**254 passed, 14 existing optional skips**), Ruff lint/format, strict
mypy and `build --no-isolation`. Its Linux PyInstaller bundle and installed/frozen desktop smoke also
passed. All 518 reference firmware hashes match the baseline. One existing upstream Starlette
warning remains visible. A native Windows rerun of `packaging\windows\build.ps1` is still needed to
validate the frozen Windows application and installer. M3 physical acceptance remains pending.

## Original M4 implementation checks (Linux)

| Gate | Evidence and boundary |
| --- | --- |
| Full Python 3.12 suite | 254 passed, including all accepted M1/M2/M3 tests and 27 new operations/browser cases |
| Python 3.13 | 240 passed, 14 optional browser cases skipped in that environment; browsers were executed in Python 3.12 |
| Chromium | 14 workflows passed, including four new wizard, EN/DE persistence, described-port/USB confirmation and backup import/download workflows |
| Ruff | Lint and format pass; original rules unchanged |
| Strict mypy | Pass, 63 source/test files; maintainer smoke also type checked |
| Packaging | 0.4.0 sdist/wheel build; normal desktop and advanced CLI entry points, all local assets and catalogs included |
| Offline installation | Fresh Python 3.12 environment installs all 20 runtime packages from a local wheelhouse only |
| Installed desktop | Real localhost setup, assets, settings save, operator/display WebSockets, backup/restore, data copy, restart and shutdown smoke pass outside repository |
| Accepted CLI/source | Installed M3/Core smoke passes: simulator preserves 7 raw rows / 2 punches / 1 duplicate; restart/recalculation, exports and no telemetry regressions |
| Self-contained | Same PyInstaller spec builds and passes desktop/CLI HTTP/WebSocket/backup/restart smoke on Linux, without relying on external Python in the launched bundle |
| Persistence | No new migration; raw-first probe retains malformed bytes, online backup includes committed WAL/source duplicates; invalid/future archives rejected; failed settings saves retain original location/facts; Move recovery-rename failure cannot diverge from committed settings |
| Accepted boundaries | No changes to FoxCore, FoxBridge, FoxLive models/persistence/scoring/service or reference firmware; all 518 reference hashes match baseline |
| Windows installer | Inno Setup/PyInstaller release recipes provided; **not compiled/executed on Windows here** |
| Physical/manual | M3 FoxLive and M4 clean-Windows/USB/upgrade/uninstall/native-folder-picker/long-running acceptance **pending** |

One upstream Starlette HTTPX deprecation warning remains visible. Nothing was suppressed and no
quality gate was weakened. Native Windows APIs and installer behavior cannot be proved by Linux
tests; the [Windows checklist](WINDOWS.md) specifies these steps. Build dependencies/Internet are
release-maintainer concerns only; the intended operator installer bundles runtime dependencies.

Remaining operational limits: one trusted local desktop/operator, no authentication or public
deployment; no other CLI/database writer during data moves or restore; whole-DB backups rather than
individual event archives; browser upload limit 512 MiB compressed / 8 GiB uncompressed; ZIP
checksums are not signatures; large backup/compression can briefly delay the owner loop; serial
command write is not device acknowledgement. Devices without reliable USB serial metadata require
manual port identification. Move retains a recovery copy rather than deleting historical data.
Program/driver signing, SmartScreen, Windows USB behavior and physical field acceptance remain
release/operator checks, not assumed successes. No automatic update, cloud deployment or new
competition feature milestone has been added.

COM re-identification does not change FoxCore's accepted source identity rules: `serial:<port>` is
part of its duplicate key. A retry observed after an explicitly confirmed port change can therefore
have a different source identity. Check diagnostics and bridge delivery history rather than assuming
USB metadata changes radio duplicate semantics. This existing limitation was not redesigned in M4.
