# FjwW live integration — M2

## Verified protocol facts

The author's [FjwW English manual](http://www.ardf-fjww.com/download/FjwWenu.pdf), version
25.10.2.1, sections “The Interface menu / SportIdent” and “Hard- and software components”,
documents SI-C live AUTOSEND start/fox/finish input through transparent serial/radio transport.
Its station codes are start 3, finish 4 and controls 20..254. It supports 4800/38400 serial links.
It describes the Interface → SportIdent dialog (Ctrl+I) for COM and transfer-rate selection,
and up to 99 COM ports. M2 uses configurable 38400, 8N1; set the receiver identically.
The special `foxdataBaudrate` discussion names SI-B even inside the SI-C section, so M2 does
not assume that INI key configures SI-C.

Retrieved public PDF via HTTP after the author's HTTPS certificate mismatch prevented download.
SHA256: `7d0bc7f5265b45465c64b5c1e4ca862971e3d10950a1f8c5a87302d33ba61dd8`.
Menu names above are documentation-verified, not observed on the current machine.

## Third-party implementation evidence

[MeOS D3 receiver](https://github.com/melinsoftware/meos/blob/11dbad72b972353b4bcf7fa00535263c18616c7d/code/SportIdent.cpp)
and [sireader](https://github.com/gaudenz/sireader/blob/38b03e7e1b9b4da0aa6c3a7d756faa06a3a621c7/sireader.py)
establish extended AUTOSEND encoding. This supports the implementation target but does not prove
which bytes a particular FjwW release accepts. The exact D3/Fjw combination still requires validation.

## Intended Windows topology

```text
FoxIdentServer physical COM3 → FoxCore → FoxBridge → COM9 ↔ COM10 → FjwW SI-C
```

COM numbers are examples only. FoxCore alone opens the physical base port. FoxBridge opens one
endpoint of a user-provisioned COM pair; FjwW opens the other. Never select the same endpoint.
The [original com0com project](https://com0com.sourceforge.net/) documents paired endpoints;
FoxBridge does not install drivers or depend on a particular vendor. Use an existing pair whose
driver is accepted by the target Windows/Secure Boot configuration, or two USB serial adapters
with a proper null-modem connection. Driver installation/signing is outside FoxSuite.
No specific Windows driver has been tested in this environment.

## Configuration and mapping

Copy the example TOML and set `[bridge].enabled=true`, the stable target name, `[serial].port`
for the physical base, `[bridge.output].port` for the bridge side and the event IANA timezone.
Set both virtual serial endpoints to 38400, 8 data bits, no parity, 1 stop bit, no flow control
(or another documentation-supported matching rate). FoxSuite rejects equal base/output port names;
the **operator** must also keep Fjw on the opposite pair endpoint.

```text
foxsuite --config config/foxsuite.toml bridge uid-map add 04A78319BCDE12 912345
foxsuite --config config/foxsuite.toml bridge station-map add 1 31 --role CONTROL
foxsuite --config config/foxsuite.toml bridge station-map add 2 3 --role START
foxsuite --config config/foxsuite.toml bridge station-map add 3 4 --role FINISH
foxsuite --config config/foxsuite.toml bridge run --show-punches
foxsuite --config config/foxsuite.toml bridge status
foxsuite --config config/foxsuite.toml bridge deliveries
```

The card number is an example, not an automatically assigned identity. Confirm the chosen identity
exists in the isolated Fjw test event. No Fjw files are edited by FoxBridge.

## Observed behavior

FjwW is not installed/accessible on this Linux machine and Wine is unavailable. No Stage C or
physical Fox→Fjw test has been performed here. M1 hardware acceptance was supplied by the user;
it is not evidence for M2 compatibility.

## Assumptions

SI-C accepts D3 extended AUTOSEND directly, without a full programmable/readout station handshake.
Runner identities must already exist in the loaded Fjw event and match explicit SI mappings.
CONTROL/START/FINISH are mapping roles; D3 has no separate role field. Fjw recognizes configured
codes. We do not calculate results or alter competition files.

## Hardware/Fjw validation still required

Stage A is automated: published vector/CRC and full regression suite. Stage B is automated on Linux:
`test_serial_output_known_frame_capture` sends the published frame through pyserial to a POSIX
pseudo-terminal diagnostic receiver and compares all 19 bytes and CRC. Windows COM-pair capture is
still required. Stage C remains unperformed. On Windows:

1. Create an isolated Fjw test event with known runner/card and control assignments.
2. Provision the COM pair; confirm independent access to each endpoint.
3. Select SI-C receiver endpoint and matching baud in the documented SportIdent dialog.
4. Configure FoxBridge source port, distinct output port, target name, timezone and mappings.
5. Inject one mapped punch; verify acceptance, card/runner, control and exact event-local time.
6. Test START=3, FINISH=4, multiple controls, morning/afternoon and midnight crossing.
7. Inject a FoxCore duplicate; confirm only one live Fjw punch.
8. Disconnect/reconnect output and USB source; verify diagnostics and no historical resends.
9. Restart bridge; verify no historical backlog automatically appears.
10. Run real RFID → FoxIdent → LoRa → base → FoxCore → bridge → Fjw; verify later revisit,
    duplicate suppression, timestamps and independent TimeSync.

Record Fjw version, Windows/driver versions, mappings, timezone, captured frames and observations.
Only successful observations may mark FjwW compatibility as manually validated.

## Failure/recovery policy

Source data stays in FoxCore. Unmapped/invalid/failed punches are visible in bridge status and delivery
records. Reconnect allows new deliveries; uncertain writes are never automatically retried. Inspect
Fjw and captures before an explicit resend. A successful serial write only means the local driver
accepted bytes, not that Fjw parsed/persisted them. A crash after writing but before success recording
is inherently ambiguous on an unacknowledged stream; durable reservations prevent automatic resend.
Replay output is off by default and requires an explicit operator option.

Stop ingest before opening a separate physical-port `send-time` session. During bridge live run,
FoxCore already owns that port and maintains TimeSync. Use `bridge status` and `bridge deliveries`
to inspect failures. Correct mappings, then, only after inspecting Fjw's existing data, use
`foxsuite --config config/foxsuite.toml bridge resend PUNCH_ID`. A mapping repair alone never emits
old competition data. Keep the same target across restarts/port changes and do not run two writers.
