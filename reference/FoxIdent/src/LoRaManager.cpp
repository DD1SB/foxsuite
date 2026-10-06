/******************************************************************************
 *  Project : FoxIdent
 *  File    : LoRaManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "LoraManager.h"

#include <Arduino.h>
#include <SPI.h>

#include "Config.h"
#include "PacketManager.h"
#include "QueueManager.h"
#include "TimeManager.h"
#include <cstring>

namespace Fox
{

    LoraManager::LoraManager(QueueManager &queues, PacketManager &packets, TimeManager &time)
        : m_queues(queues), m_packets(packets), m_time(time), m_driver(
                                                                  Config::LoRa::LORA_NSS, Config::LoRa::LORA_DIO1, Config::LoRa::LORA_BUSY, Config::LoRa::LORA_RST),
          m_mesh(m_driver, Config::Station::Id)
    {
    }

    //=============================================================================

    bool LoraManager::begin() noexcept
    {

        SPI.begin(Config::SPI::SPI_SCK, Config::SPI::SPI_MISO, Config::SPI::SPI_MOSI, Config::LoRa::LORA_NSS);

        if (!m_mesh.init())
        {
            Serial.println("[LORA] mesh init failed.");
            m_initialized = false;

            return false;
        }

        if (!m_driver.setFrequency(static_cast<float>(Config::LoRa::Frequency) / 1000000.0F))
        {
            Serial.println("[LORA] set frequency failed.");
            m_initialized = false;

            return false;
        }

        if (!m_driver.setTxPower(Config::LoRa::TxPower))
        {
            Serial.println("[LORA] set power failed.");
            m_initialized = false;

            return false;
        }

        m_initialized = true;

        m_lastTimeRequest = millis() - Config::Time::RetryIntervalMs;

        return true;
    }

    //=============================================================================

    void LoraManager::update() noexcept
    {
        if (!m_initialized)
        {
            return;
        }

        receive();

        transmit();

        processRetries();

        processTimeRequest();
    }

    //=============================================================================

    void LoraManager::receive() noexcept
    {
        std::uint8_t buffer[RH_MESH_MAX_MESSAGE_LEN];

        std::uint8_t length = sizeof(buffer);

        std::uint8_t from = 0U;

        if (!m_mesh.recvfromAck(buffer, &length, &from))
        {
            return;
        }

        RawPacket packet;

        if (length > packet.data.size())
        {
            return;
        }

        packet.length = length;

        for (std::uint8_t i = 0U; i < length; ++i)
        {
            packet.data[i] = buffer[i];
        }

        processPacket(packet);
    }

    //=============================================================================

    void LoraManager::transmit() noexcept
    {
        TagPacket packet;

        if (xQueueReceive(m_queues.txQueue(), &packet, 0) != pdTRUE)
        {
            return;
        }

        // TODO if DEBUG
        // Serial.println("[LORA] event received.");

        const std::uint16_t sequence = m_sequence++;

        packet.header.sequence = sequence;

        RawPacket raw;

        if (!m_packets.encode(packet, raw))
        {
            return;
        }

        if (sendRaw(raw, packet.header.destination))
        {
            addRetry(raw, sequence, packet.header.destination);
        }
    }

    //=============================================================================

    void LoraManager::processPacket(const RawPacket &packet) noexcept
    {

        // TODO if DEBUG
        // Serial.println("[RFID] process packet.");

        TagPacket tag;

        if (m_packets.decode(packet, tag))
        {
            /*
             * Weitergabe des empfangenen
             * RFID-Ereignisses.
             *
             * Der empfangene Datensatz wird
             * lokal protokolliert.
             */

            // TODO if DEBUG
            // Serial.println("[RFID] tag packet.");

            LogEntry entry;

            entry.timestamp = tag.header.timestamp;

            entry.station = tag.stationId;

            entry.uid = tag.uid;

            xQueueSend(m_queues.logQueue(), &entry, 0);

            sendAck(tag.header.sequence, tag.header.source);

            return;
        }

        AckPacket ack;

        if (m_packets.decode(packet, ack))
        {
            // TODO if DEBUG
            // Serial.println("[RFID] ack packet.");

            acknowledge(ack.acknowledgedSequence);

            return;
        }

        SyncPacket sync;

        if (m_packets.decode(packet, sync))
        {
            // TODO if DEBUG
            // Serial.println("[RFID] sync packet.");
            if (sync.header.source != Config::Station::BaseId)
            {
                // TODO if DEBUG
                // Serial.println("[RFID] sync not from base.");
                return;
            }

            if (sync.header.destination != Config::Station::Id)
            {
                // TODO if DEBUG
                // Serial.println("[RFID] sync not for this station.");
                return;
            }

            m_time.synchronize(sync.unixTime);

            Serial.printf("[TIME] synchronized: %lu\n", static_cast<unsigned long>(sync.unixTime));

            return;
        }
    }

    //=============================================================================

    void LoraManager::sendAck(std::uint16_t sequence, std::uint16_t destination) noexcept
    {
        AckPacket packet;

        packet.header.type = PacketType::Ack;

        packet.header.source = Config::Station::Id;

        packet.header.destination = destination;

        packet.header.timestamp = m_time.now();

        setCallsign(packet.header);

        packet.acknowledgedSequence = sequence;

        RawPacket raw;

        if (!m_packets.encode(packet, raw))
        {
            return;
        }

        sendRaw(raw, destination);
    }

    //=============================================================================

    bool LoraManager::sendRaw(const RawPacket &packet, std::uint16_t destination) noexcept
    {
        std::array<std::uint8_t, MaxPacketSize> buffer = packet.data;

        uint8_t success = m_mesh.sendtoWait(buffer.data(), static_cast<std::uint8_t>(packet.length), static_cast<std::uint8_t>(destination));
        if (success != RH_ROUTER_ERROR_NONE)
        {
            Serial.println("[LORA] packet NOT sent to mesh.");
            return false;
        }
        return true;
    }

    //=============================================================================

    void LoraManager::addRetry(const RawPacket &packet, std::uint16_t sequence, std::uint16_t destination) noexcept
    {
        // TODO if DEBUG
        // Serial.println("[LORA] entry added.");
        for (RetryEntry &entry : m_retryTable)
        {
            if (!entry.active)
            {
                entry.active = true;

                entry.retries = 0U;

                entry.nextRetry = millis() + Config::LoRa::AckTimeoutMs;

                entry.destination = destination;

                entry.sequence = sequence;

                entry.packet = packet;

                return;
            }
        }
    }

    //=============================================================================

    void LoraManager::acknowledge(std::uint16_t sequence) noexcept
    {
        for (RetryEntry &entry : m_retryTable)
        {
            if (entry.active && entry.sequence == sequence)
            {
                entry.active = false;

                return;
            }
        }
    }

    //=============================================================================

    void LoraManager::processRetries() noexcept
    {
        const std::uint32_t now = millis();

        for (RetryEntry &entry : m_retryTable)
        {
            if (!entry.active)
            {
                continue;
            }

            if (now < entry.nextRetry)
            {
                continue;
            }

            if (entry.retries >= Config::LoRa::MaxRetries)
            {
                entry.active = false;

                continue;
            }

            if (sendRaw(entry.packet, entry.destination))
            {
                entry.retries++;

                entry.nextRetry = now + Config::LoRa::AckTimeoutMs;
            }
            else
            {
                /*
                 * Funkfehler:
                 *
                 * nächster Versuch später
                 */

                entry.nextRetry = now + Config::LoRa::AckTimeoutMs;
            }
        }
    }

    void LoraManager::setCallsign(Fox::PacketHeader &header) noexcept
    {
        header.callsign.fill('\0');

        std::strncpy(header.callsign.data(), Config::Station::Callsign, header.callsign.size() - 1U);
    }

    void LoraManager::processTimeRequest() noexcept
    {
        const std::uint32_t now = millis();

        const std::uint32_t interval = m_time.isSynchronized() ? Config::Time::RequestIntervalMs : Config::Time::RetryIntervalMs;

        if ((now - m_lastTimeRequest) < interval)
        {
            return;
        }

        m_lastTimeRequest = now;

        sendTimeRequest();
    }

    void LoraManager::sendTimeRequest() noexcept
    {
        TimeRequestPacket packet{};

        packet.header.type = PacketType::TimeRequest;
        packet.header.source = Config::Station::Id;
        packet.header.destination = Config::Station::BaseId;
        packet.header.sequence = m_sequence++;
        packet.header.timestamp = m_time.now();

        setCallsign(packet.header);

        RawPacket raw{};

        if (!m_packets.encode(packet, raw))
        {
            Serial.println("[LORA] TimeRequest encode failed.");
            return;
        }

        if (!sendRaw(raw, packet.header.destination))
        {
            Serial.println("[LORA] TimeRequest send failed.");
            return;
        }

        Serial.println("[LORA] TimeRequest sent.");
    }

} // namespace Fox