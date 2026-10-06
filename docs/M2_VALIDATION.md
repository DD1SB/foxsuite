# M2 validation record

M2 is complete. Initial automated validation was performed 2026-10-06 on Linux. The user subsequently
supplied successful real Windows/FjwW SI-C validation of implementation commit
`31c3761df118370148175bc7cbabde8e48907b8b`. This documentation closure records that manual evidence;
it does not claim the Linux agent performed the Windows test. M1 baseline accepted by the user:
`5a2d529d30a84193c4b47e182f308a432236775b`. Reference firmware remains read-only.

## Evidence levels

| Stage | Result | Boundary |
| --- | --- | --- |
| Protocol research | Documented before implementation | Official SPORTident guidance, author Fjw manual, pinned independent open-source receivers and published CRC/frame vector |
| A: encoder/unit tests | Passed | Literal published D3 frame/BE71 CRC; number/control limits; SI5 series; wall-clock/DST conversions |
| B: serial capture | Passed on POSIX pseudo-terminal | pyserial sent all 19 published bytes unchanged; not a Windows driver or physical SI station test |
| Installed package integration | Passed offline | Built wheel in clean Python 3.12 environment; simulator → core persistence/subscriber → bridge → binary capture |
| Independent Windows serial/protocol validation | Passed; user-supplied manual evidence | Real hardware punch captured through VSPE COM10 ↔ COM11; length, D3, control, card, punch time, CRC and framing independently checked |
| Real Fox hardware path | Passed; user-supplied manual evidence | Real tag → field station → LoRa → base → COM3 → FoxCore/FoxBridge → virtual pair → FjwW, for CONTROL 31/card 912345 |
| C: real FjwW SI-C acceptance | Passed; user-supplied manual evidence | SI-C on COM11 received the punch; SI Status displayed SI-No=31 and CN=912345; no additional handshake or competition configuration required for this observed path |
| Full FjwW competition workflow | Not tested; not required for M2 closure | No participant assignment, competition fox mapping, result calculation, complete Start/Finish semantics or certificate/result workflows |

## Manual Windows validation evidence

Tested physical/live topology:

```text
RFID tag → FoxIdent field station → LoRa mesh → FoxIdentServer → USB COM3
         → FoxCore → FoxBridge → COM10 ↔ VSPE virtual pair ↔ COM11 → FjwW SI-C
```

FoxBridge opened COM10 at 38400 baud with event timezone `Europe/Berlin`. FjwW SI-C was enabled
and received on COM11. Explicit mappings were UID `046365525C6180 → 912345` and Fox station
`1 → CONTROL 31`. No additional FjwW competition configuration was required for protocol acceptance.

Before the FjwW test, the output from a real hardware punch was independently captured through
the virtual pair:

```text
02 D3 0D 00 1F 00 0D EB D9 05 15 9E 00 00 00 00 76 93 03
```

The independent check confirmed 19 bytes, extended D3 / C_TRANS_REC AUTOSEND, control 31,
SI card 912345, correct punch time, CRC `7693`, and STX/ETX. The closure also rechecked the supplied
bytes with the existing frame validator; this is a software check of supplied evidence, not another
physical capture. The encoded wall time is 13:32:14; no absolute Unix timestamp/date was supplied.

FjwW successfully received and decoded the real punch. Its SI Status window explicitly displayed:

```text
SI-No=31
CN=912345
```

The operator manually observed a screenshot of that display. The screenshot is not attached to this
repository. Exact Windows, VSPE and FjwW versions, manual test date and original station timestamp
were not supplied; do not infer them from the previously researched manual or encoded weekday.

Resolved for this observed configuration: FoxBridge D3 acceptance, Windows VSPE serial transport,
passive SI-C live reception, and absence of an additional required handshake. This validates the
transport acceptance scope of M2, not every Fjw release/driver, a configured participant/fox, or scoring.

## Automated quality gates

Pytest, Ruff, strict mypy, build and clean offline installation were rerun for this documentation-only
closure; application code and tests are unchanged from the manually validated implementation commit.

- Python 3.12 and 3.13: full pytest suite, 122 tests.
- Ruff lint and formatting checks: pass.
- Strict mypy across `src` and `tests`: pass, 34 source files.
- Source distribution and platform-independent wheel: build successfully.
- Wheel installs with pyserial/tzdata from the local cache, without Internet.
- Closure package check: fresh Python 3.12 wheel install, top-level/bridge CLI help, typed markers and
  supplied-capture validation pass outside the repository source path.
- Initial implementation installed-package checks: mapping management, status, simulator, bridge stdin
  ingest and guarded replay start and work outside the repository source path.
- Upgrade a genuine schema-v1 fixture to v2: original raw/punch records unchanged; FK checks pass.
- Reference tracked-file hashes match the pre-task snapshot; no reference source changes.

The implementation-stage installed-wheel smoke test uses a temporary DB, explicit UID
`04A78319BCDE12 → 912345`, station
`1 → CONTROL 31`, Europe/Berlin timezone and a file sink. One simulator cycle persists 7 raw records,
2 punches and 1 duplicate, with exactly one validated 19-byte frame. Guarded replay retains the
original capture unchanged while appending all 7 replayed raw records, including malformed/unknown
lines, and 2 replayed punches. No real receiver was opened.

Additional regressions cover unique mappings, atomic CSV imports, startup recovery without historical
delivery, source reconnect and independent TimeSync, ongoing output reconnect without backlog retry,
queue overflow, missing UID/station, implausible time, offset exhaustion, persistence failure after
write, shutdown during write, device-close failure, crash reservation, explicit frozen-frame resend
and replay authorization.

## Untested competition workflow and field follow-up

Creating a full Fjw competition, assigning card 912345 to a participant, configuring control 31 as a
competition fox, calculating results, complete Start/Finish semantics and certificate/result workflows
were not tested. These are Fjw operation, not prerequisites to close the accepted transport scope of M2.

Use [FJW_INTEGRATION.md](FJW_INTEGRATION.md) for repeatable acceptance steps and separate field
follow-up. Later visits, duplicate/retry suppression, source/output reconnect, restart and TimeSync have
automated coverage (and earlier M1 hardware evidence where stated); they were not newly demonstrated
against FjwW by the supplied single-punch test. Start/Finish, long-running Fjw operation, date boundaries,
other mappings and configurations require their own observations. No M3 work is authorized here.

## Operational risks

An unacknowledged stream cannot prove Fjw accepted a successful write or resolve crash/partial-write
ambiguity. Reservations intentionally prevent automatic retries; operators may need to repair/resend
missed punches after checking Fjw. Explicit resend/replay can duplicate competition data.
D3 acceptance without an extra handshake is now observed, including zero subseconds and offset zero
in the captured frame. Full event date/week interpretation, nonzero synthetic offsets, other identities/
controls and Start/Finish semantics remain unvalidated against FjwW. Windows transport is validated
only for the tested VSPE pair, not arbitrary drivers/versions/Secure Boot setups. Long-running Fjw
operation is not field-tested. There is no backup readout or station programming. Offsets do not wrap
silently; DST ambiguous punches are rejected.

Maintain stable target name, DB and physical source port assignment. A new target/DB loses the old
reservation identity; changing the physical source label changes FoxCore's dedupe key and can allow
a newly received old retry through. No history is scanned automatically. One bridge writer per
DB/target is supported. Status is last persisted state rather than a liveness probe.

At this M2 closure, FoxLive/scoring/M3 had not been started. Subsequent M3 implementation and its
separate validation boundary are documented in [FOXLIVE.md](FOXLIVE.md); M2 acceptance above is unchanged.
