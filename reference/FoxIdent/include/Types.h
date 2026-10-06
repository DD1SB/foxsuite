/******************************************************************************
 *  Project : FoxIdent
 *  File    : Types.h
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

namespace Fox
{

    //------------------------------------------------------------
    // Konstanten
    //------------------------------------------------------------

    constexpr std::size_t MaxUidLength = 7U;
    constexpr std::size_t MaxCallsignLength = 12U;
    constexpr std::size_t MaxPacketSize = 64U;

    //------------------------------------------------------------
    // Pakettypen
    //------------------------------------------------------------

    enum class PacketType : std::uint8_t
    {
        None = 0U,
        Sync = 1U,
        Tag = 2U,
        Ack = 3U,
        TimeRequest = 4U
    };

    //------------------------------------------------------------
    // Stationszustand
    //------------------------------------------------------------

    enum class StationState : std::uint8_t
    {
        Startup = 0U,
        WaitForTime,
        Ready,
        Error
    };

    //------------------------------------------------------------
    // UID
    //------------------------------------------------------------

    struct UID
    {
        std::uint8_t length = 0U;
        std::array<std::uint8_t, MaxUidLength> value{};
    };

    //------------------------------------------------------------
    // Data for the Tag
    //------------------------------------------------------------

    struct TagFileData
    {
        std::uint32_t timestamp;
        std::uint32_t eventId;
    };

    static_assert(sizeof(TagFileData) == 8U);

    //------------------------------------------------------------
    // RFID Event
    //------------------------------------------------------------

    struct TagEvent
    {
        UID uid;
        std::uint32_t timestamp = 0U;
    };

    //------------------------------------------------------------
    // Logeintrag
    //------------------------------------------------------------

    struct LogEntry
    {
        std::uint32_t timestamp = 0U;
        std::uint16_t station = 0U;
        UID uid;
    };

    //------------------------------------------------------------
    // Paketheader
    //------------------------------------------------------------

    struct PacketHeader
    {
        PacketType type = PacketType::None;
        std::uint16_t source = 0U;
        std::uint16_t destination = 0U;
        std::uint16_t sequence = 0U;
        std::uint32_t timestamp = 0U;
        std::array<char, MaxCallsignLength> callsign{};
    };

    //------------------------------------------------------------
    // Time request packet
    //------------------------------------------------------------

    struct TimeRequestPacket
    {
        PacketHeader header;
    };

    //------------------------------------------------------------
    // Tag Packet
    //------------------------------------------------------------

    struct TagPacket
    {
        PacketHeader header;
        std::uint16_t stationId = 0U;
        UID uid;
    };

    //------------------------------------------------------------
    // ACK Packet
    //------------------------------------------------------------

    struct AckPacket
    {
        PacketHeader header;
        std::uint16_t acknowledgedSequence = 0U;
    };

    //------------------------------------------------------------
    // Zeit-Synchronisation
    //------------------------------------------------------------

    struct SyncPacket
    {
        PacketHeader header;
        std::uint32_t unixTime = 0U;
    };

    //------------------------------------------------------------
    // Rohdatenpaket
    //------------------------------------------------------------

    struct RawPacket
    {
        std::uint16_t length = 0U;
        std::array<std::uint8_t, MaxPacketSize> data{};
    };

    //------------------------------------------------------------
    // Retry-Eintrag
    //------------------------------------------------------------

    struct RetryEntry
    {
        bool active = false;
        std::uint8_t retries = 0U;
        std::uint32_t nextRetry = 0U;
        std::uint16_t destination = 0U;
        std::uint16_t sequence = 0U;
        RawPacket packet;
    };

    //------------------------------------------------------------
    // Statistiken
    //------------------------------------------------------------

    struct Statistics
    {
        std::uint32_t rfidDetected = 0U;
        std::uint32_t tagWritten = 0U;
        std::uint32_t logWritten = 0U;
        std::uint32_t txPackets = 0U;
        std::uint32_t rxPackets = 0U;
        std::uint32_t retries = 0U;
        std::uint32_t crcErrors = 0U;
        std::uint32_t ackTimeouts = 0U;
    };

    //------------------------------------------------------------
    // Fehlercodes
    //------------------------------------------------------------

    enum class ErrorCode : std::uint8_t
    {
        None = 0U,
        RFIDInit,
        RFIDWrite,
        SDInit,
        SDWrite,
        LoRaInit,
        LoRaSend,
        TimeNotSynchronized,
        QueueOverflow,
        Internal
    };

} // namespace Fox