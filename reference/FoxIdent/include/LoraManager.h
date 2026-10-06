/******************************************************************************
 *  Project : FoxIdent
 *  File    : LoraManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <array>
#include <cstdint>

#include "RHMesh.h"
#include "RH_SX126x.h"

#include "Types.h"
#include "Config.h"

namespace Fox
{

    class QueueManager;
    class PacketManager;
    class TimeManager;

    /**
     * @brief Handles LoRa mesh communication.
     *
     * Responsibilities:
     *
     * - RadioHead mesh transport
     * - packet transmit
     * - packet receive
     * - application ACK handling
     * - retry management
     * - time synchronization
     */
    class LoraManager
    {
    public:
        LoraManager(QueueManager &queues, PacketManager &packets, TimeManager &time);

        bool begin() noexcept;

        void update() noexcept;

    private:
        void receive() noexcept;

        void transmit() noexcept;

        void processPacket(const RawPacket &packet) noexcept;

        void processRetries() noexcept;

        void sendAck(std::uint16_t sequence, std::uint16_t destination) noexcept;

        void acknowledge(std::uint16_t sequence) noexcept;

        void addRetry(const RawPacket &packet, std::uint16_t sequence, std::uint16_t destination) noexcept;

        bool sendRaw(const RawPacket &packet, std::uint16_t destination) noexcept;

        void setCallsign(Fox::PacketHeader &header) noexcept;

        void processTimeRequest() noexcept;

        void sendTimeRequest() noexcept;

    private:
        QueueManager &m_queues;

        PacketManager &m_packets;

        TimeManager &m_time;

        RH_SX126x m_driver;

        RHMesh m_mesh;

        std::array<RetryEntry, Config::LoRa::RetryTableSize> m_retryTable{};

        std::uint16_t m_sequence = 0U;

        bool m_initialized = false;

        std::uint32_t m_lastTimeRequest = 0U;
    };

} // namespace Fox