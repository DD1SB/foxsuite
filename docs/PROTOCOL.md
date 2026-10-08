# FoxIdentServer protocol — M1

## Verified from current source

Paths below are relative to `reference/`. This is source-code verification, not hardware verification.

* `FoxIdentServer/include/Config.h`, `src/main.cpp`: serial baud 115200; input is newline delimited, CR ignored, surrounding whitespace trimmed. The exact command is `TIME <positive decimal Unix seconds>\n`. Arduino `String::toInt()` is cast to uint32; invalid/zero input is ignored. No command ACK other than the time JSON is defined. FoxCore validates positive uint32 before sending (firmware's signed conversion needs hardware validation for dates after 2038).
* `FoxIdentServer/src/BaseLoraManager.cpp::printTag`: emits `{"type":"tag","station":1,"timestamp":1770000000,"sequence":2,"uid":"04A78319BCDE12","callsign":"DD1SB","rssi":-70}`. Station is `TagPacket.stationId`, timestamp/sequence/callsign from its header. UID is uppercase two hex digits per byte, capped at seven bytes. Callsign stops at NUL; quotes and backslashes are **not escaped**. Header source, destination, packet version, and sync-validity flag are not exported.
* The same file emits `time` (`status:"synchronized", timestamp`), `time_request` (`station, meshSource, sequence`), `sync` (`station, timestamp`), and `error` (error string; optional station/meshSource/length). Error codes are `decode`, `time_not_valid`, `sync_encode`, `sync_send`. Startup text includes a blank line, `FoxBase 1.0.0`, `[BASE] LoRa ready`, and initialization failures (`main.cpp`, `BaseLoraManager.cpp`).
* `synchronizeClock` only sets the base reference Unix time/millis and emits time JSON. It does not broadcast Sync. `processPacket` answers TimeRequest addressed to base address 0 with current time in an addressed SyncPacket, or emits time_not_valid. Successful send emits sync JSON; it proves mesh-send success, not station clock application.
* Both `include/Types.h` files define packet types None=0, Sync=1, Tag=2, Ack=3, TimeRequest=4. Header has uint16 source/destination/sequence, uint32 timestamp, callsign[12]. Tag adds uint16 stationId and UID (length + seven bytes); Ack adds uint16 acknowledgedSequence; Sync adds uint32 unixTime; TimeRequest contains only header.
* Both `include/PacketManager.h` and `src/PacketManager.cpp`: version 2; version byte + native struct memory (including ABI padding) + native uint16 CRC; exact size/version/CRC checked. CRC starts FFFF with polynomial A001. This binary radio format is not the PC interface.
* `FoxIdent/src/StationController.cpp`: source and stationId originate from station configuration; original RFID event timestamp retained. `src/LoRaManager.cpp`: station-local uint16 sequence shared by tags/time requests; wraps and restarts on boot. Retries resend the stored raw packet unchanged. Mesh ACK and application ACK are distinct. Base prints every decoded tag then sends application ACK to header source; no tag destination check. Field ACK handling matches sequence without verifying source/destination.
* `FoxIdent/src/TimeManager.cpp`, `RFIDManager.cpp`: before sync, timestamp is millis since boot; after sync, Unix reference + elapsed whole seconds. RFID can queue pre-sync data; controller waits for Ready before draining. No sync-valid flag in serial tag JSON, so timestamp semantics cannot always be established from a tag alone.
* `FoxIdent/src/LoRaManager.cpp`, `include/Config.h`: first time request eligible immediately, then 30 s when unsynchronized and 600 s when synchronized. Sync accepted only from configured base and addressed to this station. Both packet header and payload carry Unix time in base-generated Sync.

## Supplementary documentation

`FoxIdent_V1.0.0_LLM_CONTEXT.md` describes the field firmware, architecture, DESFire layout and historical limitations. Its field packet/version/time details agree with inspected code. Samples excluded by PlatformIO are not authoritative PC interfaces.

## Known discrepancies

The supplementary document's incomplete base path warning applies to field `LoRaManager`, not the separate current FoxIdentServer implementation, which handles TimeRequest and Sync generation. The server still prints the legacy name `FoxBase 1.0.0`; this is current source output, not evidence of a legacy protocol. `TagFileData` declares two uint32s while `RFIDManager::writeTimestampFile` writes timestamp32, eventId16, reserved byte, sync flag; FoxCore does not decode tag memory. Unescaped callsigns can produce malformed JSON; raw bytes are retained rather than firmware modified.

M5 source inspection additionally found that `RFIDManager::selectApplication`
comments name AID `0x56789A` LSB-first, but transmit bytes `56 78 9A` (a different
numeric value under little-endian notation). Deployed tag selection remains a
physical reader validation requirement. [TAG_READOUT](TAG_READOUT.md) documents
the actual writer layout, discrepancy and separate version-1 acquisition contract;
that contract is not current FoxIdentServer serial output.

## Assumptions still requiring hardware validation

USB driver settings, reset/DTR behavior, effective 8N1, sustained throughput, radio interoperability across struct ABIs, actual PC-to-base-to-station sync latency, post-2038 conversion, reconnect reliability, timestamp validity and collisions after station reboot remain unverified. Automated fixtures are derived from source. See OPERATIONS for hardware checklist.
