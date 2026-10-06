/******************************************************************************
 *  Project : FoxIdent
 *  File    : SignalManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <Arduino.h>
#include <cstdint>

namespace Fox
{

    class SignalManager
    {
    public:
        SignalManager() noexcept = default;

        void begin() noexcept;

        void update() noexcept;

        void signalTagSuccess() noexcept;

        void signalTagError() noexcept;

        void signalStartup() noexcept;

    private:
        enum class Pattern : std::uint8_t
        {
            None,
            TagSuccess,
            TagError,
            Startup,
            NoTimeSync,
            TimeSync
        };

        void startPattern(Pattern pattern) noexcept;

        void setRedLed(bool enabled) noexcept;

        void setGreenLed(bool enabled) noexcept;

        void stopSignal() noexcept;

        Pattern m_pattern = Pattern::None;

        std::uint8_t m_step = 0U;

        std::uint32_t m_stepStartedAt = 0U;
    };

}