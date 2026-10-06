/******************************************************************************
 *  Project : FoxIdent
 *  File    : LogManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "LogManager.h"

#include <Arduino.h>

#include "Config.h"
#include "QueueManager.h"

namespace Fox
{

    LogManager::LogManager(QueueManager &queues): m_queues(queues)
    {
    }

    //=============================================================================

    bool LogManager::begin() noexcept
    {
        if(!SD_MMC.setPins(Config::SD::SD_CLK, Config::SD::SD_CMD, Config::SD::SD_DAT0)){
            m_initialized = false;

            return false;
        }

        if (!SD_MMC.begin("/sdcard", true))
        {
            m_initialized = false;

            return false;
        }

        if (!openLogFile())
        {
            m_initialized = false;

            return false;
        }

        m_initialized = true;

        m_lastFlush = millis();

        return true;
    }

    //=============================================================================

    void LogManager::update() noexcept
    {
        if (!m_initialized)
        {
            return;
        }

        LogEntry entry;

        while (xQueueReceive(m_queues.logQueue(), &entry, 0) == pdTRUE)
        {
            // TODO if DEBUG
            Serial.println("[LOG] event received.");
            if (!writeEntry(entry)){
                Serial.println("[LOG] writeEntry failed.");
            }
            Serial.println("[LOG] entry written.");
        }

        const std::uint32_t now = millis();

        if ((now - m_lastFlush) >= Config::SD::FlushIntervalMs)
        {
            if (m_file)
            {
                m_file.flush();
            }

            m_lastFlush = now;
        }
    }

    //=============================================================================

    bool LogManager::openLogFile() noexcept
    {
        /*
         * Binärlogdatei.
         *
         * Format:
         *
         * [uint32 timestamp]
         * [uint16 station]
         * [uint8  uidLength]
         * [uid bytes]
         */

        m_file = SD_MMC.open("/foxstation.log", FILE_APPEND);

        return static_cast<bool>(m_file);
    }

    //=============================================================================

    bool LogManager::writeEntry(const LogEntry &entry) noexcept
    {
        if (!m_file)
        {
            return false;
        }

        const std::uint32_t timestamp = entry.timestamp;

        const std::uint16_t station = entry.station;

        m_file.write(reinterpret_cast<const std::uint8_t *>(&timestamp), sizeof(timestamp));

        m_file.write(reinterpret_cast<const std::uint8_t *>(&station), sizeof(station));

        m_file.write(&entry.uid.length, sizeof(entry.uid.length));

        m_file.write( entry.uid.value.data(), entry.uid.length);

        return true;
    }

} // namespace Fox