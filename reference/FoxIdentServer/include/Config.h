/******************************************************************************
 *
 *  FoxBase
 *
 *  File:
 *      Config.h
 *
 ******************************************************************************/

#pragma once

#include <Arduino.h>

namespace Config
{
    namespace Base
    {
        constexpr std::uint8_t MeshAddress = 0U;
        constexpr std::uint32_t SerialBaud = 115200UL;
        constexpr char Callsign[] = "DD1SB";

    }

    namespace SPI
    {
        constexpr std::int8_t SCK = 5;
        constexpr std::int8_t MISO = 19;
        constexpr std::int8_t MOSI = 27;
    }

    namespace LoRa
    {
        constexpr std::int8_t NSS = 18;
        constexpr std::int8_t DIO0 = 26;
        constexpr std::int8_t RESET = 23;

        constexpr float FrequencyMHz = 434.1F;
        constexpr std::int8_t TxPower = 17;
    }
}
