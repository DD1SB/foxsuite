/******************************************************************************
 *  Project : FoxIdent
 *  File    : PacketManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <cstddef>
#include <cstdint>

#include "Types.h"

namespace Fox
{

    class PacketManager
    {
    public:
        PacketManager() = default;

        bool encode(const TagPacket &packet, RawPacket &raw) const noexcept;
        bool encode(const AckPacket &packet, RawPacket &raw) const noexcept;
        bool encode(const SyncPacket &packet, RawPacket &raw) const noexcept;
        bool encode(const TimeRequestPacket& packet, RawPacket& raw) const noexcept;

        bool decode(const RawPacket &raw, TagPacket &packet) const noexcept;
        bool decode(const RawPacket &raw, AckPacket &packet) const noexcept;
        bool decode(const RawPacket &raw, SyncPacket &packet) const noexcept;
        bool decode(const RawPacket& raw, TimeRequestPacket& packet) const noexcept;

    private:
        static constexpr std::uint8_t ProtocolVersion = 2U;

        static constexpr std::size_t HeaderSize = sizeof(std::uint8_t) + sizeof(PacketHeader);

        template <typename T>
        bool encodePacket(const T &packet, RawPacket &raw) const noexcept;

        template <typename T>
        bool decodePacket(const RawPacket &raw, T &packet) const noexcept;

        static std::uint16_t crc16(const std::uint8_t *data, std::size_t length) noexcept;
    };

} // namespace Fox