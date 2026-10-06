# M2 validation record

Validation performed 2026-10-06 on Linux. M1 baseline accepted by the user:
`5a2d529d30a84193c4b47e182f308a432236775b`. Reference firmware remains read-only.

## Evidence levels

| Stage | Result | Boundary |
| --- | --- | --- |
| Protocol research | Documented before implementation | Official SPORTident guidance, author Fjw manual, pinned independent open-source receivers and published CRC/frame vector |
| A: encoder/unit tests | Passed | Literal published D3 frame/BE71 CRC; number/control limits; SI5 series; wall-clock/DST conversions |
| B: serial capture | Passed on POSIX pseudo-terminal | pyserial sent all 19 published bytes unchanged; not a Windows driver or physical SI station test |
| Installed package integration | Passed offline | Built wheel in clean Python 3.12 environment; simulator → core persistence/subscriber → bridge → binary capture |
| C: FjwW manual acceptance | Not performed | FjwW/Wine unavailable; no accepted runner/control/time observation |
| Physical Fox→Fjw chain | Not performed | M1 hardware acceptance is user-reported, not M2 end-to-end validation |

## Automated quality gates

- Python 3.12 and 3.13: full pytest suite, 122 tests.
- Ruff lint and formatting checks: pass.
- Strict mypy across `src` and `tests`: pass.
- Source distribution and platform-independent wheel: build successfully.
- Wheel installs with pyserial/tzdata from the local cache, without Internet.
- Installed `foxsuite --help`, mapping management, status, simulator, bridge stdin ingest and guarded
  replay start and work outside the repository source path.
- Upgrade a genuine schema-v1 fixture to v2: original raw/punch records unchanged; FK checks pass.
- Reference tracked-file hashes match the pre-task snapshot; no reference source changes.

The installed-wheel smoke test uses a temporary DB, explicit UID `04A78319BCDE12 → 912345`, station
`1 → CONTROL 31`, Europe/Berlin timezone and a file sink. One simulator cycle persists 7 raw records,
2 punches and 1 duplicate, with exactly one validated 19-byte frame. Guarded replay retains the
original capture unchanged while appending all 7 replayed raw records, including malformed/unknown
lines, and 2 replayed punches. No real receiver was opened.

Additional regressions cover unique mappings, atomic CSV imports, startup recovery without historical
delivery, source reconnect and independent TimeSync, ongoing output reconnect without backlog retry,
queue overflow, missing UID/station, implausible time, offset exhaustion, persistence failure after
write, shutdown during write, device-close failure, crash reservation, explicit frozen-frame resend
and replay authorization.

## Remaining manual acceptance

Use [FJW_INTEGRATION.md](FJW_INTEGRATION.md) for the Windows COM/Fjw and real Fox-chain checklist.
Record OS, COM-pair driver/signature/Secure Boot, Fjw version/event, source firmware version, card/control
assignments, event timezone/date, captured frames and actual runner/control/time results. Verify START,
CONTROL, FINISH, later valid visits, retry suppression, source/output reconnect, bridge restart and
independent TimeSync. Long-running volume and disk-failure field testing remain necessary.

## Operational risks

An unacknowledged stream cannot prove Fjw accepted a successful write or resolve crash/partial-write
ambiguity. Reservations intentionally prevent automatic retries; operators may need to repair/resend
missed punches after checking Fjw. Explicit resend/replay can duplicate competition data.
Synthetic backup offsets, fixed configured week counter, D3 acceptance without station discovery,
and date/zero-subsecond interpretation are still compatibility assumptions. There is no backup readout
or station programming. Offsets do not wrap silently; DST ambiguous punches are rejected.

Maintain stable target name, DB and physical source port assignment. A new target/DB loses the old
reservation identity; changing the physical source label changes FoxCore's dedupe key and can allow
a newly received old retry through. No history is scanned automatically. One bridge writer per
DB/target is supported. Status is last persisted state rather than a liveness probe.

FoxLive, scoring and Milestone 3 have not been started.
