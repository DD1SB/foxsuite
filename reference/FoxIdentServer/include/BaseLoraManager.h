/******************************************************************************
 *
 *  FoxBase
 *
 *  File:
 *      BaseLoraManager.h
 *
 ******************************************************************************/

#pragma once

#include <cstdint>

#include "RHMesh.h"
#include "RH_RF95.h"

#include "PacketManager.h"
#include "Types.h"

namespace Fox
{
    class BaseLoraManager
    {
    public:
        explicit BaseLoraManager(PacketManager &packets) noexcept;

        bool begin() noexcept;
        void update() noexcept;
        void synchronizeClock(std::uint32_t unixTime) noexcept;
        bool hasValidTime() const noexcept;

    private:
        void processPacket(const RawPacket &raw, std::uint8_t meshSource) noexcept;
        void printTag(const TagPacket &packet, std::int16_t rssi) const noexcept;
        void sendAck(std::uint16_t sequence, std::uint16_t destination) noexcept;
        bool sendRaw(RawPacket &raw, std::uint16_t destination) noexcept;
        void sendSync(std::uint32_t unixTime, std::uint16_t destination) noexcept;
        std::uint32_t currentUnixTime() const noexcept;
        void setBaseCallsign(Fox::PacketHeader &header) noexcept;

    private:
        PacketManager &m_packets;
        RH_RF95 m_driver;
        RHMesh m_mesh;
        bool m_initialized = false;
        std::uint16_t m_sequence = 0U;
        bool m_timeValid = false;
        std::uint32_t m_referenceUnixTime = 0U;
        std::uint32_t m_referenceMillis = 0U;
    };
}
