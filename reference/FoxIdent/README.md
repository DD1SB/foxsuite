# FoxIdent

> **An ESP32-based RFID and LoRa Mesh station for modern ARDF/Foxoring events**

FoxIdent is a modern electronic checkpoint designed for **Amateur Radio Direction Finding (ARDF)**, **Foxoring** and similar outdoor navigation events.

Each station detects a competitor's **MIFARE DESFire EV1** tag, stores the visit timestamp directly on the tag, logs the event locally and forwards the information through a **LoRa Mesh network** to a central base station.

The project has been designed with reliability, modularity and long-term maintainability in mind. It is intended as an open hardware / open software platform that can evolve over multiple hardware and firmware generations.

---

## Features

* ESP32-S3 based hardware
* MIFARE DESFire EV1 support
* Direct timestamp storage on RFID tag
* Local binary event logging on SD card
* LoRa Mesh communication using RadioHead RHMesh
* Automatic time synchronization via the mesh network
* Queue-based multitasking architecture (FreeRTOS)
* Modular C++17 software design
* Remote event monitoring through a USB-connected base station
* Designed for battery-powered outdoor operation

---

## System Overview

```text
Runner
   │
   ▼
DESFire RFID Tag
   │
   ▼
FoxIdent
 ├── RFID Manager
 ├── Time Manager
 ├── SD Log
 ├── Packet Manager
 └── LoRa Mesh
          │
          ▼
      Mesh Network
          │
          ▼
     FoxBase Station
          │
          ▼
      USB / PC Server
```

---

## Event Flow

1. Runner presents RFID tag.
2. Station reads the DESFire tag.
3. Current timestamp is written to the configured DESFire file.
4. Event is logged locally on the SD card.
5. A LoRa packet is transmitted through the mesh.
6. The base station forwards the event to the host computer.

---

## Hardware

### FoxIdent

* ESP32-S3
* PN532 NFC reader
* SX1262 LoRa transceiver
* MicroSD card
* Status LEDs
* Piezo buzzer

### FoxBase

* LilyGO T3 v1.6.1
* SX1278 (433 MHz)
* USB Serial connection

---

## Software Architecture

The firmware is divided into independent modules.

* RFIDManager
* LoraManager
* PacketManager
* TimeManager
* LogManager
* StationController
* QueueManager

Communication between modules is performed through FreeRTOS queues in order to keep the individual components independent and testable.

---

## Communication

The stations communicate through a **LoRa Mesh** network.
PLEASE NOTE: depending on the frequency and the transmit power, you may have to own a ham radio license for transmission part!

Packet types currently implemented:

* Tag
* ACK
* Sync
* TimeRequest

Each packet contains

* protocol version
* packet type
* source station
* destination
* sequence number
* timestamp
* callsign

---

## Time Synchronization

Stations do not require a real-time clock.

After startup a station periodically requests the current Unix time from the base station.

```text
Station
     │
TimeRequest
     │
     ▼
Base Station
     │
 SyncPacket
     │
     ▼
Station
```

---

## Repository Structure

```text
.
├── include/
├── src/
├── lib/
├── docs/
├── platformio.ini
└── README.md
```

---

## Project Status

Current status:

* ✔ RFID subsystem operational
* ✔ DESFire timestamp writing
* ✔ Local SD logging
* ✔ LoRa Mesh communication
* ✔ Time synchronization
* ✔ Base station communication
* ✔ Queue-based architecture

The project is currently in **hardware validation and field testing**.

---

## Roadmap

### Version 1.0

* Stable FoxIdent firmware
* Stable FoxBase firmware
* Reliable field operation
* Event logging
* Time synchronization

### Version 1.1

* Advanced signal manager
* Improved diagnostics
* Extended monitoring
* Additional configuration options

### Version 2.x

* Additional event features
* Extended base station software
* Optional web interface
* Further protocol extensions

---

## License

This project is published as open source under MIT License.
(see LICENSE)

---

## Acknowledgements

Special thanks to the ARDF community and all testers who helped validating the hardware and firmware during development.

# Your contribution
If you improve this project, I'd be happy if you open a Pull Request or let me know about your changes. Seeing the project evolve is always appreciated.
