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
which bytes every FjwW release accepts. The user-supplied manual evidence below now establishes
acceptance for the tested FoxBridge/FjwW SI-C setup.

## Manually validated Windows topology

```text
FoxIdentServer physical COM3 → FoxCore → FoxBridge → COM10 ↔ VSPE pair ↔ COM11 → FjwW SI-C
```

These COM numbers are the actual tested assignments, not hardcoded requirements. FoxCore alone opens
the physical base port. FoxBridge opens one endpoint of a user-provisioned COM pair; FjwW opens the
other. Never select the same endpoint.
The [original com0com project](https://com0com.sourceforge.net/) documents paired endpoints;
FoxBridge does not install drivers or depend on a particular vendor. Use an existing pair whose
driver is accepted by the target Windows/Secure Boot configuration, or two USB serial adapters
with a proper null-modem connection. Driver installation/signing is outside FoxSuite.
The operator's VSPE pair was successfully tested on Windows. Other virtual-pair providers, driver
versions and Windows/Secure Boot configurations are not validated by that observation; com0com and
physical null-modem adapters remain untested alternatives, not validated recommendations.

## Configuration and mapping

Copy the example TOML and set `[bridge].enabled=true`, the stable target name, `[serial].port`
for the physical base, `[bridge.output].port` for the bridge side and the event IANA timezone.
Set both virtual serial endpoints to 38400, 8 data bits, no parity, 1 stop bit, no flow control
(or another documentation-supported matching rate). FoxSuite rejects equal base/output port names;
the **operator** must also keep Fjw on the opposite pair endpoint.

```text
foxsuite --config config/foxsuite.toml bridge uid-map add 046365525C6180 912345
foxsuite --config config/foxsuite.toml bridge station-map add 1 31 --role CONTROL
foxsuite --config config/foxsuite.toml bridge station-map add 2 3 --role START
foxsuite --config config/foxsuite.toml bridge station-map add 3 4 --role FINISH
foxsuite --config config/foxsuite.toml bridge run --show-punches
foxsuite --config config/foxsuite.toml bridge status
foxsuite --config config/foxsuite.toml bridge deliveries
```

The UID/card and CONTROL 31 mappings above match the manual acceptance test; START/FINISH lines
are additional operational examples, not manually validated Fjw roles. No identity is auto-assigned.
A participant/event setup was not needed for the SI-C protocol acceptance test. For competition use,
configure the chosen card and controls in Fjw separately; that workflow was not tested. No Fjw files
are edited by FoxBridge.

## Observed behavior

The user supplied successful Windows manual validation of implementation commit
`31c3761df118370148175bc7cbabde8e48907b8b`. A real RFID punch traversed the field station, LoRa,
base USB/COM3, FoxCore/FoxBridge, COM10/COM11 VSPE pair and FjwW SI-C. Bridge output was 38400
baud, timezone Europe/Berlin; UID `046365525C6180` mapped to card `912345`, station 1 to CONTROL 31.

Before Fjw testing, an independent serial capture of the real hardware punch produced:

```text
02 D3 0D 00 1F 00 0D EB D9 05 15 9E 00 00 00 00 76 93 03
```

The operator independently checked length, extended D3 / C_TRANS_REC AUTOSEND, control/card/time,
CRC and framing. With SI-C enabled on COM11, FjwW decoded the punch and displayed `SI-No=31`
and `CN=912345` in SI Status. A screenshot was observed manually; it is not a repository artifact.
No additional handshake or Fjw competition configuration was required for this observed acceptance
path. The Linux agent did not run this Windows test; exact software versions/test date were not supplied.

## Resolved assumptions and remaining limits

The tested SI-C path passively accepts FoxBridge D3 without an additional handshake, and the tested
Windows VSPE transport works. These are now observations, not unresolved assumptions. They do not
establish compatibility with every Fjw/driver version or station mode.

CONTROL/START/FINISH are mapping roles; D3 has no separate role field. Card/control decoding was
observed for 912345/31, not association with an actual competitor or configured competition fox.
Full competition creation, participant assignment, fox configuration, result calculation, complete
Start/Finish semantics and certificates/results were not tested and are not M2 closure requirements.
We do not calculate results or alter competition files. Date/week rollover, nonzero synthetic offsets,
other identities and Start/Finish require separate Fjw observations.

## Validation stages and repeatable acceptance procedure

Stage A is automated: published vector/CRC and full regression suite. Stage B is automated on Linux:
`test_serial_output_known_frame_capture` sends the published frame through pyserial to a POSIX
pseudo-terminal diagnostic receiver and compares all 19 bytes and CRC. Stage B additionally passed
with independent Windows VSPE capture of a real hardware punch. Stage C SI-C reception passed as
recorded above. To repeat the accepted scope on Windows:

1. Provision the VSPE pair; FoxBridge uses COM10 and the receiver uses COM11 in the tested layout.
2. Configure physical source COM3, output COM10 at 38400, Europe/Berlin and the explicit mappings.
3. With Fjw not holding COM11, independently capture a real hardware punch and validate all frame fields.
4. Close the diagnostic receiver, enable FjwW SI-C on COM11 and use the matching baud.
5. Punch the real tag; observe SI Status `SI-No=31` and `CN=912345`. The reported acceptance test
   needed no additional competition configuration or handshake.

Record Fjw version, Windows/driver versions, mappings, timezone, captured frames and observations.
The supplied observations close M2's SI-C transport scope. For optional competition/field follow-up,
separately configure a test event and verify actual participant/fox/time association, Start/Finish,
multiple controls and date boundaries. Revisit/duplicate behavior, source/output reconnect, restart,
independent TimeSync and long-running Fjw operation still need end-to-end Fjw field observations;
their automated or M1 evidence is not a substitute. These are remaining operational limits, not a
claim that full competition operation was validated or a request to start M3.

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
