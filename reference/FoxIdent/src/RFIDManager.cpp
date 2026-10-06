/******************************************************************************
 *  Project : FoxIdent
 *  File    : RFIDManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "RFIDManager.h"

#include <Arduino.h>
#include <Wire.h>

#include "Config.h"
#include "QueueManager.h"
#include "TimeManager.h"
#include "SignalManager.h"

namespace Fox
{

    RFIDManager::RFIDManager(QueueManager &queues, TimeManager &time, SignalManager &signal) :
        m_queues(queues), m_time(time), m_signal(signal), m_nfc(Config::I2C::I2C_SDA, Config::I2C::I2C_SCL)
    {
    }

    //=============================================================================

    bool RFIDManager::begin() noexcept
    {
        Wire.begin(
            Config::I2C::I2C_SDA,
            Config::I2C::I2C_SCL,
            Config::I2C::Clock);

        m_nfc.begin();

        const std::uint32_t version = m_nfc.getFirmwareVersion();

        if (version == 0U)
        {
            m_initialized = false;

            return false;
        }

        if (!m_nfc.SAMConfig())
        {
            Serial.println("[RFID] SAMConfig failed");
            return false;
        }

        m_initialized = true;

        return true;
    }

    //=============================================================================

    void RFIDManager::update() noexcept
    {
        // TODO : if DEBUG
        /*
        static std::uint32_t lastDebug = 0U;
        if ((millis() - lastDebug) >= 2000U)
        {
            lastDebug = millis();
            Serial.println("[RFID] update()");
        }
        */

        m_signal.update();

        if (!m_initialized)
        {
            return;
        }

        const std::uint32_t now = millis();

        if ((now - m_lastPoll) < Config::PN532::PollIntervalMs)
        {
            return;
        }

        m_lastPoll = now;

        TagEvent event;

        if (readTag(event))
        {
            // TODO : if DEBUG
            // Serial.println("[RFID] readTag success");
            if (xQueueSend(m_queues.rfidQueue(), &event, 0) != pdTRUE)
            {
                Serial.println("[RFID] RFID queue full");
            }
            // TODO if DEBUG
            Serial.println("[RFID] RFID entry queued");
        }
    }

    //=============================================================================

    bool RFIDManager::readTag(TagEvent &event) noexcept
    {
        std::uint8_t uidBuffer[7]{};
        std::uint8_t uidLength = 0U;

        if (!m_nfc.readPassiveTargetID(
                PN532_MIFARE_ISO14443A,
                uidBuffer,
                &uidLength,
                1000U))
        {
            return false;
        }

        if (!convertUid(uidBuffer, uidLength, event.uid))
        {
            return false;
        }

        const std::uint32_t now = millis();

        bool sameTag = uidLength == m_lastUidsLength && std::equal(uidBuffer, uidBuffer + uidLength, m_lastUids.begin());

        if (sameTag && (now - m_lastReadTime) < Config::RFID::TAG_REPEAT_BLOCK_MS)
        {
            return false;
        }

        event.timestamp = m_time.now();

        // TODO - if DEBUG? oder permanent?
        /*
        Serial.printf("[RFID] Read tag - timestamp %u, UID: ", event.timestamp);
        printHex(uidBuffer, uidLength);
        Serial.println("");
        */

        if (!writeTimestampFile(event.uid, event.timestamp))
        {
            m_signal.signalTagError();   
            return false;
        }

        std::copy(uidBuffer, uidBuffer + uidLength, m_lastUids.begin());
        m_lastUidsLength = uidLength;
        m_lastReadTime = now;

        m_signal.signalTagSuccess();

        return true;
    }

    //=============================================================================

    bool RFIDManager::writeStationData(const UID &uid) noexcept
    {
        /*
         * Placeholder für MIFARE Block schreiben.
         *
         * Der konkrete Schreibvorgang hängt vom verwendeten
         * Kartentyp und Schlüsselmanagement ab.
         *
         * Die Schnittstelle bleibt bewusst bestehen.
         */

        (void)uid;

        return true;
    }

    //=============================================================================

    bool RFIDManager::convertUid(const uint8_t *buffer, uint8_t length, UID &uid) noexcept
    {
        if (length > uid.value.size())
        {
            return false;
        }

        uid.length = length;

        for (std::uint8_t i = 0U; i < length; ++i)
        {
            uid.value[i] = buffer[i];
        }

        return true;
    }

    bool RFIDManager::selectApplication() noexcept
    {
        constexpr std::array<std::uint8_t, 9U> sendData{
            0x90U, // CLA: wrapped native DESFire command
            0x5AU, // INS: SelectApplication
            0x00U, // P1
            0x00U, // P2
            0x03U, // Lc: drei AID-Bytes

            0x56U,
            0x78U,
            0x9AU, // AID 0x56789A, LSB first

            0x00U // Le
        };

        std::array<std::uint8_t, 61U> backData{};
        std::uint8_t backLen = static_cast<std::uint8_t>(backData.size());

        const bool exchangeOk = m_nfc.inDataExchange(
            const_cast<std::uint8_t *>(sendData.data()),
            static_cast<std::uint8_t>(sendData.size()),
            backData.data(),
            &backLen);

        // TODO if DEBUG
        /*
        Serial.printf(
            "[RFID] inDataExchange: %s, len=%u, response:",
            exchangeOk ? "OK" : "FAILED",
            static_cast<unsigned>(backLen));

        for (std::uint8_t i = 0U; i < backLen; ++i)
        {
            Serial.printf(
                " %02X",
                static_cast<unsigned>(backData[i]));
        }

        Serial.println();
        */

        if (!exchangeOk)
        {
            return false;
        }

        /*
         * Wrapped DESFire response:
         *
         * 91 00 = Kommando erfolgreich
         */
        if ((backLen != 2U) ||
            (backData[0] != 0x91U) ||
            (backData[1] != 0x00U))
        {
            // TODO : if DEBUG
            // Serial.println("[RFID] SelectApplication rejected");

            return false;
        }

        // TODO : if DEBUG
        // Serial.println("[RFID] Application 0x56789A selected");

        return true;
    }

    void RFIDManager::printHex(byte *buffer, uint16_t bufferSize) noexcept
    {
        for (uint16_t i = 0; i < bufferSize; i++)
        {
            Serial.print(buffer[i] < 0x10 ? " 0" : " ");
            Serial.print(buffer[i], HEX);
        }
    }

    bool RFIDManager::writeTimestampFile(const UID &uid, std::uint32_t timestamp) noexcept
    {
        (void)uid;
        // TODO : if DEBUG
        // Serial.printf("[RFID] writeTimestampFile - UID length: %u, timestamp: %lu \n", uid.length, timestamp);

        if (!selectApplication())
        {
            // TODO : if DEBUG
            // Serial.println("[RFID] Select application failed.");
            return false;
        }

        std::array<uint8_t, 8U> data{};

        const std::uint32_t eventId = Config::Event::Id;

        data[0] = static_cast<uint8_t>(timestamp);
        data[1] = static_cast<uint8_t>(timestamp >> 8U);
        data[2] = static_cast<uint8_t>(timestamp >> 16U);
        data[3] = static_cast<uint8_t>(timestamp >> 24U);

        data[4] = static_cast<uint8_t>(eventId);
        data[5] = static_cast<uint8_t>(eventId >> 8U);
        data[6] = 0x00;
        data[7] = m_time.isSynchronized();

        /*
         * File ID entspricht Station ID.
         */

        const uint8_t fileId = static_cast<uint8_t>(Config::Station::Id);

        /*
         * DESFire WRITE_DATA:
         *
         * Cmd      0x3D
         * File ID
         * Offset 0
         * Length 8
         */

        std::array<std::uint8_t, 21U> sendData{

            0x90,    // CLA
            0x3D,    // INS - write data into standard or backup data files
            0x00,    // P1
            0x00,    // P2
            0x0F,    // Lc - 7 (1 id + 3 offset + 3 length) + data length
            fileId,  // file number
            0x00,    // offset
            0x00,    // offset
            0x00,    // offset
            0x08,    // data length
            0x00,    // length
            0x00,    // length
            data[0], // data
            data[1], // data
            data[2], // data
            data[3], // data
            data[4], // data
            data[5], // data
            data[6], // data
            data[7], // data
            0x00,    // Le
        };

        std::array<std::uint8_t, 61U> backData{};
        std::uint8_t backLen = static_cast<std::uint8_t>(backData.size());

        const bool exchangeOk = m_nfc.inDataExchange(
            const_cast<std::uint8_t *>(sendData.data()),
            static_cast<std::uint8_t>(sendData.size()),
            backData.data(),
            &backLen);

        // TODO if DEBUG
        /*
        Serial.printf(
            "[RFID] inDataExchange: %s, len=%u, response:",
            exchangeOk ? "OK" : "FAILED",
            static_cast<unsigned>(backLen));

        for (std::uint8_t i = 0U; i < backLen; ++i)
        {
            Serial.printf(
                " %02X",
                static_cast<unsigned>(backData[i]));
        }

        Serial.println();
        */

        if (!exchangeOk)
        {
            return false;
        }

        /*
         * Wrapped DESFire response:
         *
         * 91 00 = Kommando erfolgreich
         */
        if ((backLen != 2U) ||
            (backData[0] != 0x91U) ||
            (backData[1] != 0x00U))
        {
            Serial.println("[RFID] Write data to tag failed");

            return false;
        }

        // TODO if DEBUG
        Serial.println("[RFID] Write data to tag success");

        return true;
    }

} // namespace Fox