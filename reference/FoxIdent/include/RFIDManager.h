/******************************************************************************
 *  Project : FoxIdent
 *  File    : RFIDManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

 #pragma once

#include "Adafruit_PN532.h"

#include "Types.h"

namespace Fox
{

    class QueueManager;
    class TimeManager;
    class SignalManager;

    /**
     * @brief Handles RFID tag detection and writing.
     *
     * The RFID manager is intentionally non-blocking.
     * It polls the PN532 periodically and pushes detected tags
     * into the RFID queue.
     */
    class RFIDManager
    {
    public:
        RFIDManager(QueueManager &queues, TimeManager &time, SignalManager& signal);

        bool begin() noexcept;

        void update() noexcept;

    private:
        bool readTag(TagEvent &event) noexcept;

        bool writeStationData(const UID &uid) noexcept;

        bool convertUid(const uint8_t *buffer, uint8_t length, UID &uid) noexcept;

        bool selectApplication() noexcept;

        void printHex(byte *buffer, uint16_t bufferSize) noexcept;

        bool writeTimestampFile(const UID &uid, std::uint32_t timestamp) noexcept;

    private:
        QueueManager &m_queues;

        TimeManager &m_time;

        SignalManager &m_signal;

        Adafruit_PN532 m_nfc;

        std::uint32_t m_lastPoll = 0U;

        UID m_lastUid;

        bool m_initialized = false;

        // UID Zeitsperre - mehrfaches Einlesen verhindern
        std::array<std::uint8_t, 7U> m_lastUids{};
        std::uint8_t m_lastUidsLength{0U};
        std::uint32_t m_lastReadTime{0U};

    };

} // namespace Fox