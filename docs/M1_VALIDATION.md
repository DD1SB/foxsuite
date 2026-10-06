# M1 validation evidence

Validated on Linux on 2026-10-06. This is not Windows or physical hardware validation.

| Gate | Result |
| --- | --- |
| Python 3.12.3 pytest | 39 passed |
| Python 3.13.15 pytest | 39 passed |
| Ruff check src tests | passed |
| Ruff format --check src tests | 18 files formatted |
| mypy strict | no issues in 18 source/test files |
| build --no-isolation | sdist and universal Python wheel built |
| Editable install | installed on Python 3.12 |
| Wheel install | installed offline in clean Python 3.12 environment with cached pyserial |
| Installed CLI help/simulator | passed |
| Installed simulator → stdin ingest | 7 raw, 2 punches, 1 duplicate, no pending rows |
| Installed replay | 14 total raw, 4 total punches, 2 total duplicates, originals retained |
| Firmware reference SHA256 comparison | all supplied reference files unchanged |
| git diff --check | passed |

Tests cover current source tag fields, optional/extra fields, unknown/malformed/non-UTF8 input, UID formats/invalid values, migration version/reopen/future rejection, FK relationships, duplicate identity/revisits/restart, raw preservation through parsing and normalized transaction failures, pending recovery, mapping repositories, subscriber/logging failure isolation, fake transport integration, serial partial framing/open failure/reconnect/command/cancellation, automatic/disabled/manual/periodic/custom TimeSync and diagnostic/write failures, replay chronology/timing/provenance and duplicate scopes, and config validation.

Tests using asyncio worker threads needed execution outside the restricted sandbox because its socket wakeup restrictions stalled even a minimal `asyncio.to_thread` diagnostic. The same code completed normally outside that sandbox.

Hardware assumptions and operational risks remain listed in PROTOCOL and OPERATIONS: Windows driver/DTR/reset, sync latency/application, native radio struct ABI, timestamp validity, post-2038 firmware parsing, sequence/reboot identity ambiguity, corrupt undelimited stream memory growth, disk capacity and long-running operation. No M2 code or hardware verification is claimed.
