# M4 validation — 2026-10-08

Accepted baseline: `4cef9abdb8e0a87d80b24cf16c12b6e91c0a8abf`. M1/M2 acceptance remains
unchanged; **M3 physical Windows acceptance is still pending**. No M4 physical evidence supplied.

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
