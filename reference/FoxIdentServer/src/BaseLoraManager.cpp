/******************************************************************************
 *
 *  FoxBase
 *
 *  File:
 *      BaseLoraManager.cpp
 *
 ******************************************************************************/

#include "BaseLoraManager.h"

#include <Arduino.h>
#include <SPI.h>

#include "Config.h"
#include <cstring>

namespace Fox
{
    BaseLoraManager::BaseLoraManager(PacketManager &packets) noexcept
        : m_packets(packets),
          m_driver(Config::LoRa::NSS, Config::LoRa::DIO0),
          m_mesh(m_driver, Config::Base::MeshAddress)
    {
    }

    bool BaseLoraManager::begin() noexcept
    {
        pinMode(Config::LoRa::RESET, OUTPUT);
        digitalWrite(Config::LoRa::RESET, HIGH);
        delay(10U);
        digitalWrite(Config::LoRa::RESET, LOW);
        delay(10U);
        digitalWrite(Config::LoRa::RESET, HIGH);
        delay(10U);

        SPI.begin(
            Config::SPI::SCK,
            Config::SPI::MISO,
            Config::SPI::MOSI,
            Config::LoRa::NSS);

        if (!m_mesh.init())
        {
            Serial.println("[BASE] mesh init failed");
            return false;
        }

        if (!m_driver.setFrequency(Config::LoRa::FrequencyMHz))
        {
            Serial.println("[BASE] set frequency failed");
            return false;
        }

        m_driver.setModemConfig(RH_RF95::Bw125Cr45Sf128);
        m_driver.setTxPower(Config::LoRa::TxPower, false);

        m_initialized = true;
        Serial.println("[BASE] LoRa ready");

        return true;
    }

    void BaseLoraManager::update() noexcept
    {
        if (!m_initialized)
        {
            return;
        }

        std::uint8_t buffer[RH_MESH_MAX_MESSAGE_LEN]{};
        std::uint8_t length = sizeof(buffer);
        std::uint8_t source = 0U;

        if (!m_mesh.recvfromAck(buffer, &length, &source))
        {
            return;
        }

        RawPacket raw{};

        if (length > raw.data.size())
        {
            return;
        }

        raw.length = length;

        for (std::uint8_t i = 0U; i < length; ++i)
        {
            raw.data[i] = buffer[i];
        }

        processPacket(raw, source);
    }

    void BaseLoraManager::processPacket(
        const RawPacket &raw,
        std::uint8_t meshSource) noexcept
    {
        TagPacket tag{};

        if (m_packets.decode(raw, tag))
        {
            printTag(tag, m_driver.lastRssi());
            sendAck(tag.header.sequence, tag.header.source);
            return;
        }

        AckPacket ack{};

        if (m_packets.decode(raw, ack))
        {
            return;
        }

        SyncPacket sync{};

        if (m_packets.decode(raw, sync))
        {
            return;
        }

        TimeRequestPacket request{};

        if (m_packets.decode(raw, request))
        {
            if (request.header.destination != Config::Base::MeshAddress)
            {
                return;
            }

            Serial.printf(
                "{\"type\":\"time_request\","
                "\"station\":%u,"
                "\"meshSource\":%u,"
                "\"sequence\":%u}\n",
                static_cast<unsigned>(request.header.source),
                static_cast<unsigned>(meshSource),
                static_cast<unsigned>(request.header.sequence));

            if (!m_timeValid)
            {
                Serial.printf(
                    "{\"type\":\"error\","
                    "\"error\":\"time_not_valid\","
                    "\"station\":%u}\n",
                    static_cast<unsigned>(request.header.source));

                return;
            }

            sendSync(currentUnixTime(), request.header.source);

            return;
        }

        Serial.printf(
            "{\"type\":\"error\",\"error\":\"decode\",\"meshSource\":%u,\"length\":%u}\n",
            static_cast<unsigned>(meshSource),
            static_cast<unsigned>(raw.length));
    }

    void BaseLoraManager::printTag(
        const TagPacket &packet,
        std::int16_t rssi) const noexcept
    {
        Serial.print("{\"type\":\"tag\",\"station\":");
        Serial.print(packet.stationId);
        Serial.print(",\"timestamp\":");
        Serial.print(packet.header.timestamp);
        Serial.print(",\"sequence\":");
        Serial.print(packet.header.sequence);
        Serial.print(",\"uid\":\"");

        const std::uint8_t uidLength =
            packet.uid.length <= packet.uid.value.size()
                ? packet.uid.length
                : static_cast<std::uint8_t>(packet.uid.value.size());

        for (std::uint8_t i = 0U; i < uidLength; ++i)
        {
            Serial.printf("%02X", static_cast<unsigned>(packet.uid.value[i]));
        }

        Serial.print("\",\"callsign\":\"");

        for (const char character : packet.header.callsign)
        {
            if (character == '\0')
            {
                break;
            }

            Serial.print(character);
        }

        Serial.print("\",\"rssi\":");
        Serial.print(rssi);
        Serial.println("}");
    }

    void BaseLoraManager::sendAck(
        std::uint16_t sequence,
        std::uint16_t destination) noexcept
    {
        AckPacket packet{};

        packet.header.type = PacketType::Ack;
        packet.header.source = Config::Base::MeshAddress;
        packet.header.destination = destination;
        packet.acknowledgedSequence = sequence;
        setBaseCallsign(packet.header);

        RawPacket raw{};

        if (!m_packets.encode(packet, raw))
        {
            return;
        }

        sendRaw(raw, destination);
    }

    bool BaseLoraManager::sendRaw(
        RawPacket &raw,
        std::uint16_t destination) noexcept
    {
        if (destination > UINT8_MAX || raw.length > UINT8_MAX)
        {
            return false;
        }

        return m_mesh.sendtoWait(
                   raw.data.data(),
                   static_cast<std::uint8_t>(raw.length),
                   static_cast<std::uint8_t>(destination)) == RH_ROUTER_ERROR_NONE;
    }

    void BaseLoraManager::setBaseCallsign(Fox::PacketHeader &header) noexcept
    {
        header.callsign.fill('\0');

        std::strncpy(
            header.callsign.data(),
            Config::Base::Callsign,
            header.callsign.size() - 1U);
    }

    void BaseLoraManager::sendSync(std::uint32_t unixTime, std::uint16_t destination) noexcept
    {
        SyncPacket packet{};

        packet.header.type = PacketType::Sync;
        packet.header.source = Config::Base::MeshAddress;
        packet.header.destination = destination;
        packet.header.sequence = m_sequence++;
        packet.header.timestamp = unixTime;

        setBaseCallsign(packet.header);

        packet.unixTime = unixTime;

        RawPacket raw{};

        if (!m_packets.encode(packet, raw))
        {
            Serial.println("{\"type\":\"error\",\"error\":\"sync_encode\"}");

            return;
        }

        if (!sendRaw(raw, destination))
        {
            Serial.printf("{\"type\":\"error\",\"error\":\"sync_send\",\"station\":%u}\n", static_cast<unsigned>(destination));

            return;
        }

        Serial.printf("{\"type\":\"sync\",\"station\":%u,\"timestamp\":%lu}\n", static_cast<unsigned>(destination), static_cast<unsigned long>(unixTime));
    }

    void BaseLoraManager::synchronizeClock(std::uint32_t unixTime) noexcept
    {
        m_referenceUnixTime = unixTime;
        m_referenceMillis = millis();
        m_timeValid = true;
        Serial.printf("{\"type\":\"time\",\"status\":\"synchronized\",\"timestamp\":%lu}\n", static_cast<unsigned long>(unixTime));
    }

    bool BaseLoraManager::hasValidTime() const noexcept
    {
        return m_timeValid;
    }

    std::uint32_t BaseLoraManager::currentUnixTime() const noexcept
    {
        if (!m_timeValid)
        {
            return 0U;
        }

        const std::uint32_t elapsed = (millis() - m_referenceMillis) / 1000U;
        return m_referenceUnixTime + elapsed;
    }
}
