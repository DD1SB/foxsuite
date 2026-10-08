# FoxIdent DESFire readout (M5)

## Verified current source

Authoritative files are `reference/FoxIdent/src/RFIDManager.cpp` (especially
`selectApplication`, `readTag`, `writeTimestampFile`), `include/Config.h` and
`src/TimeManager.cpp`. Reference firmware is read-only.

Each successful station visit writes eight bytes at offset zero using wrapped
DESFire WriteData (`90 3D`), with file number equal to the **low byte** of the
configured station ID. It overwrites the previous visit in that file; this is
not a chronological log. The current configured station is 7; event ID is
`0x0721`, declared `uint16_t`. These are firmware configuration, not FoxLive
defaults.

| Offset | Length | Meaning |
| --- | --- | --- |
| 0 | 4 | Little-endian unsigned station timestamp |
| 4 | 2 | Little-endian unsigned event ID (0–65535) |
| 6 | 1 | Reserved, written as zero |
| 7 | 1 | `isSynchronized()`: zero or one |

After synchronization time is Unix UTC whole seconds. **Before synchronization
`TimeManager::now()` returns `millis()`, not Unix seconds.** An equal numerical
live/tag timestamp is not proof of a valid race time. No timestamp is derived
from the PC readout time.

## Known discrepancies and limitations

The SelectApplication comment names AID `0x56789A` and says LSB first, but the
actual transmitted application bytes are **`56 78 9A`**. Under little-endian AID
notation those bytes mean `0x9A7856`. Do not silently reverse them. Future reader
firmware must validate application selection on deployed tags and report the
actual application bytes. M5's capture contract identifies the source format,
not an unverified numeric AID.

The current operational firmware only selects and writes an existing file. It
does not create files, enumerate them, or implement a USB readout mode. DESFire
GetFileIDs/ReadData discovery is a **future acquisition requirement**, not a
verified current firmware capability. The file number is truncated to eight
bits whereas LoRa station IDs are wider. Actual tag/file-number limits need
hardware validation. The parser preserves every discovered byte-sized file ID,
including unconfigured files; it does not assume the event's station list is
the tag directory.

The source does not establish how tags are initialized. M5 treats an eight-byte
all-zero file as **EMPTY**, a conservative import convention rather than a
verified factory/unwritten representation. Other malformed/reserved values
remain raw evidence and require review. Reading a tag does not prove that every
previous station visit is still present.

## Canonical model and acquisition boundary

`TagReadoutProvider.read()` returns a canonical readout containing UID, PC read
time, provider/reader identity, original payload, session status and station
records. Each record retains its raw input, decoded bytes (when possible),
timestamp, event ID, reserved and synchronization bytes, and parse status.
Sessions are COMPLETE, PARTIAL, FAILED or ABORTED. Failed file attempts and
unknown files are retained. A bad file never discards successfully read files.
Simulator and file providers are included; no physical USB reader is claimed.

## FoxIdent Readout Firmware Requirements

Version 1 is newline-delimited UTF-8 JSON, one **completed snapshot per line**:

```json
{"type":"tag_readout","version":1,"format":"foxident-desfire-8","uid":"046365525C6180","reader":"finish-reader-1","status":"COMPLETE","records":[{"file_id":1,"data":"0100000021070001"}],"errors":[]}
```

* Autosend one envelope after each physical read operation, including incomplete
  operations. FoxSuite does not require a handshake in this import contract.
* UID is the original ISO14443 UID in hexadecimal; FoxCore normalization makes
  it uppercase and separator-free. Never substitute a fabricated identity.
* Enumerate the application's actual files, then read offset zero, length eight
  for each relevant station file. Include every discovered file, not only
  configured stations. Report application bytes in optional `application_bytes`.
* `file_id` is an integer 0–255. `data` is hex of the **raw bytes**, not a
  reader-side interpretation. Unknown fields are retained in the raw envelope.
* On file failure include `{"file_id":3,"data":null,"error":"timeout"}`.
  Use PARTIAL when some files succeeded; FAILED when acquisition failed;
  ABORTED when removed/cancelled. Include diagnostic strings in `errors`.
* COMPLETE means enumeration and all relevant reads completed, including a
  legitimately empty directory (`records: []`). PARTIAL/ABORTED must never be
  used to infer absence. Absence even in COMPLETE never invalidates live data.
* Future transport adapters add the PC UTC receipt time, preserve the exact
  received bytes and identify their provider. Firmware must not implement
  reconciliation, scoring or operator decisions.
* Bound a snapshot to 256 discovered files and a 1 MiB envelope. Readers should
  retry explicitly after a partial/aborted read, emitting a new snapshot.

Unknown envelope versions/formats are retained as failed imports, not guessed.
Hardware validation must establish actual AID, file provisioning/access rights,
UID stability, complete enumeration, partial/removal behavior and record bytes.
