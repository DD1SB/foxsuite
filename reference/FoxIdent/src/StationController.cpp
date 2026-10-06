/******************************************************************************
 *  Project : FoxIdent
 *  File    : StationController.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/


#include "StationController.h"

#include "Config.h"
#include "QueueManager.h"
#include "TimeManager.h"
#include <cstring>

namespace Fox
{

    StationController::StationController(QueueManager &queues, TimeManager &time) : m_queues(queues), m_time(time)
    {
    }

    //=============================================================================

    bool StationController::begin() noexcept
    {
        m_state = StationState::WaitForTime;

        m_initialized = true;

        return true;
    }

    //=============================================================================

    void StationController::update() noexcept
    {
        if (!m_initialized)
        {
            return;
        }

        // TODO if DEBUG
        // Serial.println("[CTRL] update()");
        // Serial.printf("[CTRL] state: %i\n", m_state);

        switch (m_state)
        {
        case StationState::WaitForTime:

            if (m_time.isSynchronized())
            {
                m_state = StationState::Ready;
            }

            break;

        case StationState::Ready:

            processRFID();

            break;

        case StationState::Startup:

            break;

        case StationState::Error:

            break;

        default:

            m_state = StationState::Error;

            break;
        }
    }

    //=============================================================================

    void StationController::processRFID() noexcept
    {
        TagEvent event{};

        while (xQueueReceive(m_queues.rfidQueue(), &event, 0) == pdTRUE)
        {

            // TODO if DEBUG
            Serial.println("[CTRL] RFID event received");

            /*
             * Lokales Log
             */

            LogEntry log;
            log.timestamp = event.timestamp;
            log.station = Config::Station::Id;
            log.uid = event.uid;
            if (xQueueSend(m_queues.logQueue(), &log, 0U) != pdTRUE)
            {
                Serial.println("[CTRL] Log queue full");
            }
            // TODO if DEBUG
            Serial.println("[CTRL] Log entry queued");

            /*
             * LoRa Paket vorbereiten
             */

            TagPacket packet;
            packet.header.type = PacketType::Tag;
            packet.header.source = Config::Station::Id;
            packet.header.destination = Config::Station::BaseId;
            packet.header.timestamp = event.timestamp;
            std::strncpy(
                packet.header.callsign.data(),
                Config::Station::Callsign,
                packet.header.callsign.size() - 1U);
            packet.stationId = Config::Station::Id;
            packet.uid = event.uid;

            if (xQueueSend(m_queues.txQueue(), &packet, 0U) != pdTRUE)
            {
                Serial.println("[CTRL] TX queue full");
            }
            // TODO if DEBUG
            Serial.println("[CTRL] Tag packet queued");
        }
    }

    //=============================================================================

    StationState StationController::state() const noexcept
    {
        return m_state;
    }

} // namespace Fox