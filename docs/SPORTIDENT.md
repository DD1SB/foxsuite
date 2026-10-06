# FoxBridge SPORTident subset — M2

Researched 2026-10-06 before encoder implementation. Evidence classes below are deliberately distinct.

## Verified protocol facts

Official [SPORTident SRR documentation](https://docs.sportident.com/user-guide/short-range-radio)
requires Auto send enabled and Legacy protocol disabled for live BSF8-SRR data.
The official [card overview](https://docs.sportident.com/products/cards/cards-overview) lists
production number ranges, not a FoxBridge allocation namespace. Therefore M2 requires explicit,
unique UID-to-card mappings; it does not auto-allocate virtual numbers or claim a collision-free range.
The Bluetooth Reader BT protocol is a different interface and is outside this implementation.

## Third-party implementation evidence

Primary code sources inspected (not copied into FoxSuite):

- [sireader](https://github.com/gaudenz/sireader/blob/38b03e7e1b9b4da0aa6c3a7d756faa06a3a621c7/sireader.py): extended framing, CRC, card decoding, Control autosend offsets.
- [MeOS SportIdent.cpp](https://github.com/melinsoftware/meos/blob/11dbad72b972353b4bcf7fa00535263c18616c7d/code/SportIdent.cpp): `calcCRC`, `setCRC`, D3 receiver independently confirm field offsets, big-endian CRC, AM/PM and subseconds.
- [sportident-python](https://github.com/per-magnusson/sportident-python/blob/master/sireader2.py): corroborating PTD weekday/week bits and SI5 series versus 24-bit card identity.
- [Tinymesh crc-test](https://github.com/plengqui/SportidentTinymesh/blob/489452b8ed6816d0043f41480dc891eee2dea6fc/RadioUnit/TeensySketches/crc-test/crc-test.ino): independently published D3 body/CRC vector. The companion simulator writes native CRC bytes; its endianness is not adopted. MeOS/sireader establish wire CRC high byte first.

M2 emits only D3 extended AUTOSEND transactions, not card readout/configuration or legacy 53.

```text
02 D3 0D CN1 CN0 SN3 SN2 SN1 SN0 TD TH TL TSS MEM2 MEM1 MEM0 CRC1 CRC0 03
```

| Field | Meaning |
| --- | --- |
| 02 / 03 | STX / ETX; no DLE stuffing in extended frames |
| D3 / 0D | Live transaction command / 13 payload bytes |
| CN1 CN0 | Big-endian control code; encoder supports 1..1023; Fjw mappings are narrower |
| SN3..SN0 | Top byte zero; 24-bit number, except SI5 uses series + 16-bit number |
| TD | bit0 PM, bits1..3 weekday (Sunday=0), bits4..5 relative week counter; high bits zero |
| TH TL | Big-endian seconds since midnight/noon (0..43199) |
| TSS | Fractional second in 1/256 units; Fox source has whole seconds so zero |
| MEM2..MEM0 | Big-endian backup-record offset; FoxBridge supplies persisted station/target counter in steps of 8 |
| CRC1 CRC0 | Big-endian SPORTident CRC of command + length + payload, excluding STX/ETX |

CRC is polynomial 0x8005 with an unusual seed/padding convention: for two bytes the seed is
those bytes directly; for longer data polynomial division follows the first two-byte seed,
padding odd length with one zero byte or even length with two zero bytes. This is not
`binascii.crc_hqx` or FoxIdent's radio CRC. FoxSuite implements polynomial remainder independently.

Card identities: SI5 numbers 1..65000 use series 0; 200001..265000, 300001..365000 and
400001..465000 encode series 2/3/4 plus number minus 100000*series. Gaps below 500000 are
rejected. Numbers 500000..0xFFFFFF use a zero high byte + direct 24-bit number. The latter
is a wire constraint, not a claim every number is manufactured or accepted by every Fjw version.

Published vector body `D3 0D 00 2C 00 0B DF 77 27 0E 8D 27 00 0B 70` has CRC `BE71`.
Thus a known reference frame is `02 D3 0D 00 2C 00 0B DF 77 27 0E 8D 27 00 0B 70 BE 71 03`.
It represents card 778103, control 44, Wednesday PM/week counter 2, 13:02:05 + 39/256s,
offset 2928. This is a published regression vector, not a FoxSuite hardware capture.

## Observed behavior

No SPORTident or FjwW traffic was physically observed in this task. The user reports accepted
M1 Fox hardware tests including TimeSync/reconnect/persistence. FoxCore supplies stored absolute
station seconds; reference firmware and docs/PROTOCOL remain authoritative for its semantics.

## Assumptions and implementation policy

Timezone is an explicit IANA setting (example Europe/Berlin); no PC-local timezone is inferred.
Unix UTC maps through ZoneInfo to event wall time. Midnight changes weekday; noon sets PM.
Week counter is explicitly configured 0..3, default 0. The Fjw manual describes one-week usage;
it does not establish a base date for FoxBridge's relative weeks. DST fall-back repeats local
times and this protocol cannot encode UTC offset/fold; ambiguous fall-back punches are rejected.
Spring-forward conversion from absolute UTC is unambiguous. Absolute source timestamps remain untouched.

Bridge rejects implausible timestamps using configurable minimum Unix seconds and maximum difference
from original PC receive time. A zero/faulty pre-sync station value must never become a plausible SI
time. This cannot prove the station was synchronized; source has no validity flag.

Offsets are synthetic persistent counters, not accessible SI backup memory. M2 does not answer
backup commands, ACK-based card readout, station discovery/programming or Bluetooth requests.
No wakeup prefix is emitted; receivers consume exact length-delimited extended data.

## Implemented and automated validation

`foxbridge.sportident` implements the framing, independent polynomial CRC, SI5/direct card encoding,
control encoding and typed D3 punch model above. `foxbridge.time` converts validated Unix time;
roles are mapping policy, not extra D3 fields. Frame validation is a diagnostic helper for exactly
this subset, not a full SPORTident parser.

`tests/fixtures/sportident_vectors.json` records the published vector's provenance. Encoder tests
compare against its literal bytes/CRC rather than an encode/decode round trip. Further tests cover
SI5 series, unsupported gaps, 24-bit limits, control boundaries, AM/PM, midnight, weekday, timezone
and DST. POSIX pseudo-terminal capture verifies that the serial output transports the known frame
unchanged. This is software serial testing, not a physical SPORTident capture or Windows driver test.

## Hardware/Fjw validation still required

D3 acceptance, weekday/date interpretation, zero subseconds, synthetic offsets, lack of station
query responses and Windows virtual COM behavior require Stage C validation in FJW_INTEGRATION.
Protocol tests and serial capture prove framing, not FjwW compatibility.
