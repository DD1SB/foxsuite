/******************************************************************************
 *  Project : FoxIdent
 *  File    : Config.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <Arduino.h>

#ifdef RESET
#undef RESET
#endif

#ifdef LOG
#undef LOG
#endif

namespace Config
{

    //======================================================================
    // Station
    //======================================================================

    namespace Station
    {
        constexpr uint16_t Id = 7U;

        constexpr uint16_t BaseId = 0U;

        constexpr bool BaseStation = false;

        constexpr char Callsign[] = "DD1SB";

    }

    //======================================================================
    // I2C
    //======================================================================

    namespace I2C
    {
        constexpr gpio_num_t I2C_SDA = GPIO_NUM_17;
        constexpr gpio_num_t I2C_SCL = GPIO_NUM_18;

        constexpr uint32_t Clock = 100000UL; // 400000
    }

    //======================================================================
    // PN532
    //======================================================================

    namespace PN532
    {
        constexpr uint8_t Address = 0x24;
        constexpr uint32_t PollIntervalMs = 10U;
        constexpr uint32_t Timeout = 500U;
        constexpr uint8_t StationBlock = 4U;
        constexpr uint8_t TimestampBlock = 5U;
    }

    //======================================================================
    // SD_MMC
    //======================================================================

    namespace SD
    {
        constexpr uint32_t FlushIntervalMs = 5000U;
        constexpr gpio_num_t SD_CLK = GPIO_NUM_14;
        constexpr gpio_num_t SD_CMD = GPIO_NUM_15;
        constexpr gpio_num_t SD_DAT0 = GPIO_NUM_21;
    }

    //======================================================================
    // LoRa
    //======================================================================

    namespace SPI
    {
        constexpr gpio_num_t SPI_SCK = GPIO_NUM_12;
        constexpr gpio_num_t SPI_MISO = GPIO_NUM_13;
        constexpr gpio_num_t SPI_MOSI = GPIO_NUM_11;
    }

    //======================================================================
    // LoRa
    //======================================================================

    namespace LoRa
    {
        constexpr gpio_num_t LORA_NSS = GPIO_NUM_10;
        constexpr gpio_num_t LORA_DIO1 = GPIO_NUM_7;
        constexpr gpio_num_t LORA_RST = GPIO_NUM_9;
        constexpr gpio_num_t LORA_BUSY = GPIO_NUM_1;

        constexpr long Frequency = 434100000L;

        constexpr int8_t TxPower = 20;

        constexpr uint8_t MaxRetries = 5U;

        constexpr uint32_t AckTimeoutMs = 1500U;

        constexpr uint8_t RetryTableSize = 16U;

        constexpr uint32_t RandomBackoffMinMs = 20U;
        constexpr uint32_t RandomBackoffMaxMs = 200U;
    }

    //======================================================================
    // RFID Einstellungen
    //======================================================================

    namespace RFID
    {

        constexpr std::uint32_t TAG_REPEAT_BLOCK_MS = 5000U;

    }

    //======================================================================
    // Queuegrößen
    //======================================================================

    namespace Queue
    {
        constexpr uint8_t RFID = 20U;

        constexpr uint8_t LOG = 100U;

        constexpr uint8_t TX = 20U;
    }

    //======================================================================
    // Taskprioritäten
    //======================================================================

    namespace Priority
    {
        constexpr UBaseType_t RFID = 5U;

        constexpr UBaseType_t Station = 4U;

        constexpr UBaseType_t LoRa = 3U;

        constexpr UBaseType_t Logger = 2U;
    }

    //======================================================================
    // Task-Stacks
    //======================================================================

    namespace Stack
    {
        constexpr uint32_t RFID = 4096U;

        constexpr uint32_t Station = 4096U;

        constexpr uint32_t LoRa = 6144U;

        constexpr uint32_t Logger = 4096U;
    }

    //======================================================================
    // Zeitsynchronisation
    //======================================================================

    namespace Time
    {
        constexpr uint32_t SyncIntervalMs = 60000U;

        constexpr uint32_t SyncTimeoutMs = 180000U;
    }

    //======================================================================
    // Event
    //======================================================================

    namespace Event
    {
        constexpr std::uint16_t Id = 0x0721;
    }

    namespace Time
    {
        constexpr std::uint32_t RequestIntervalMs = 600000U;
        constexpr std::uint32_t RetryIntervalMs = 30000U;
    }

    namespace Signal
{
    constexpr std::uint8_t BUZZER = GPIO_NUM_38;
    constexpr std::uint8_t LED_RED = GPIO_NUM_8;
    constexpr std::uint8_t LED_GREEN = GPIO_NUM_16;

    constexpr bool LedActiveHigh = true;

    constexpr std::uint16_t SuccessToneHz = 2400U;
    constexpr std::uint16_t SuccessSecondToneHz = 3000U;

    constexpr std::uint16_t ErrorToneHz = 500U;

    constexpr std::uint32_t SuccessLedDurationMs = 700U;
    constexpr std::uint32_t ErrorLedDurationMs = 1000U;
}

} // namespace Config