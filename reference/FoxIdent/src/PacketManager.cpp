/******************************************************************************
 *  Project : FoxIdent
 *  File    : PacketManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "PacketManager.h"

#include <cstring>

namespace Fox
{

    //=============================================================================
    // Public Interface
    //=============================================================================

    bool PacketManager::encode(const TagPacket &packet, RawPacket &raw) const noexcept
    {
        return encodePacket(packet, raw);
    }

    //-----------------------------------------------------------------------------

    bool PacketManager::encode(const AckPacket &packet, RawPacket &raw) const noexcept
    {
        return encodePacket(packet, raw);
    }

    //-----------------------------------------------------------------------------

    bool PacketManager::encode(const SyncPacket &packet, RawPacket &raw) const noexcept
    {
        return encodePacket(packet, raw);
    }

    //-----------------------------------------------------------------------------

    bool PacketManager::decode(const RawPacket &raw, TagPacket &packet) const noexcept
    {
        if (!decodePacket(raw, packet))
        {
            return false;
        }

        return packet.header.type == PacketType::Tag;
    }

    //-----------------------------------------------------------------------------

    bool PacketManager::decode(const RawPacket &raw, AckPacket &packet) const noexcept
    {
        if (!decodePacket(raw, packet))
        {
            return false;
        }

        return packet.header.type == PacketType::Ack;
    }

    //-----------------------------------------------------------------------------

    bool PacketManager::decode(const RawPacket &raw, SyncPacket &packet) const noexcept
    {
        if (!decodePacket(raw, packet))
        {
            return false;
        }

        return packet.header.type == PacketType::Sync;
    }

    bool PacketManager::encode(const TimeRequestPacket &packet, RawPacket &raw) const noexcept
    {
        return encodePacket(packet, raw);
    }

    bool PacketManager::decode(const RawPacket &raw, TimeRequestPacket &packet) const noexcept
    {
        if (!decodePacket(raw, packet))
        {
            return false;
        }

        return packet.header.type == PacketType::TimeRequest;
    }

    //=============================================================================
    // Generic Encoder
    //=============================================================================

    template <typename T>
    bool PacketManager::encodePacket(const T &packet, RawPacket &raw) const noexcept
    {
        constexpr std::size_t packetSize = sizeof(T);

        constexpr std::size_t totalSize = sizeof(std::uint8_t) + packetSize + sizeof(std::uint16_t);

        if (totalSize > MaxPacketSize)
        {
            return false;
        }

        std::uint8_t *dst = raw.data.data();

        // Protocol version
        *dst++ = ProtocolVersion;

        // Payload
        std::memcpy(dst, &packet, packetSize);

        dst += packetSize;

        // CRC
        const std::uint16_t crc = crc16(raw.data.data(), sizeof(std::uint8_t) + packetSize);

        std::memcpy(dst, &crc, sizeof(crc));

        raw.length = static_cast<std::uint16_t>(totalSize);

        return true;
    }

    //=============================================================================
    // Generic Decoder
    //=============================================================================

    template <typename T>
    bool PacketManager::decodePacket(const RawPacket &raw, T &packet) const noexcept
    {
        constexpr std::size_t packetSize = sizeof(T);

        constexpr std::size_t expectedSize = sizeof(std::uint8_t) + packetSize + sizeof(std::uint16_t);

        if (raw.length != expectedSize)
        {
            return false;
        }

        const std::uint8_t *src = raw.data.data();

        if (*src != ProtocolVersion)
        {
            return false;
        }

        ++src;

        std::uint16_t receivedCRC;

        std::memcpy(&receivedCRC, raw.data.data() + sizeof(std::uint8_t) + packetSize, sizeof(receivedCRC));

        const std::uint16_t calculatedCRC = crc16(raw.data.data(), sizeof(std::uint8_t) + packetSize);

        if (receivedCRC != calculatedCRC)
        {
            return false;
        }

        std::memcpy(&packet, src, packetSize);

        return true;
    }

    //=============================================================================
    // CRC16
    //=============================================================================

    std::uint16_t PacketManager::crc16(const std::uint8_t *data, std::size_t length) noexcept
    {
        constexpr std::uint16_t polynomial = 0xA001U;

        std::uint16_t crc = 0xFFFFU;

        for (std::size_t i = 0U; i < length; ++i)
        {
            crc = static_cast<uint16_t>(crc ^ static_cast<uint16_t>(data[i]));

            for (std::uint8_t bit = 0U; bit < 8U; ++bit)
            {
                if ((crc & 0x0001U) != 0U)
                {
                    crc = static_cast<uint16_t>(crc >> 1U);
                    crc ^= polynomial;
                }
                else
                {
                    crc = static_cast<uint16_t>(crc >> 1U);
                }
            }
        }

        return crc;
    }

    //=============================================================================
    // Explicit template instantiation
    //
    // Packet types are known at compile time.
    // This keeps the implementation in the cpp file and avoids unnecessary
    // template generation.
    //=============================================================================

    template bool PacketManager::encodePacket<TagPacket>(const TagPacket &, RawPacket &) const noexcept;

    template bool PacketManager::encodePacket<AckPacket>(const AckPacket &, RawPacket &) const noexcept;

    template bool PacketManager::encodePacket<SyncPacket>(const SyncPacket &, RawPacket &) const noexcept;

    template bool PacketManager::decodePacket<TagPacket>(const RawPacket &, TagPacket &) const noexcept;

    template bool PacketManager::decodePacket<AckPacket>(const RawPacket &, AckPacket &) const noexcept;

    template bool PacketManager::decodePacket<SyncPacket>(const RawPacket &, SyncPacket &) const noexcept;

    template bool PacketManager::encodePacket<TimeRequestPacket>(const TimeRequestPacket &, RawPacket &) const noexcept;

    template bool PacketManager::decodePacket<TimeRequestPacket>(const RawPacket &, TimeRequestPacket &) const noexcept;

} // namespace Fox