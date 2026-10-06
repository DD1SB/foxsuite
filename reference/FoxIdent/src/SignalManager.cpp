/******************************************************************************
 *  Project : FoxIdent
 *  File    : SignalManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "SignalManager.h"

#include "Config.h"

namespace Fox
{

    namespace
    {

        std::uint8_t ledLevel(bool enabled) noexcept
        {
            if (Config::Signal::LedActiveHigh)
            {
                return enabled ? HIGH : LOW;
            }

            return enabled ? LOW : HIGH;
        }

    }

    void SignalManager::begin() noexcept
    {
        pinMode(Config::Signal::BUZZER, OUTPUT);
        pinMode(Config::Signal::LED_RED, OUTPUT);
        pinMode(Config::Signal::LED_GREEN, OUTPUT);

        stopSignal();
    }

    void SignalManager::update() noexcept
    {
        if (m_pattern == Pattern::None)
        {
            return;
        }

        const std::uint32_t now = millis();
        const std::uint32_t elapsed = now - m_stepStartedAt;

        switch (m_pattern)
        {
        case Pattern::TagSuccess:
        {
            for (int f = 1000; f < 3000; f += 400)
            {
                tone(Config::Signal::BUZZER, f, 50);
                delay(60);
            }
            stopSignal();
            break;
        }

        case Pattern::TagError:
        {
            for (int f = 3000; f > 1000; f -= 400)
            {
                tone(Config::Signal::BUZZER, f, 50);
                delay(60);
            }
            stopSignal();
            break;
        }

        case Pattern::Startup:
        {
            switch (m_step)
            {
            case 0U:
            {
                if (elapsed >= 80U)
                {
                    noTone(Config::Signal::BUZZER);

                    m_step = 1U;
                    m_stepStartedAt = now;
                }

                break;
            }

            case 1U:
            {
                if (elapsed >= 150U)
                {
                    stopSignal();
                }

                break;
            }

            default:
            {
                stopSignal();
                break;
            }
            }

            break;
        }

        case Pattern::None:
        default:
        {
            break;
        }
        }
    }

    void SignalManager::signalTagSuccess() noexcept
    {
        startPattern(Pattern::TagSuccess);
    }

    void SignalManager::signalTagError() noexcept
    {
        startPattern(Pattern::TagError);
    }

    void SignalManager::signalStartup() noexcept
    {
        startPattern(Pattern::Startup);
    }

    void SignalManager::startPattern(
        Pattern pattern) noexcept
    {
        noTone(Config::Signal::BUZZER);

        setRedLed(false);
        setGreenLed(false);

        m_pattern = pattern;
        m_step = 0U;
        m_stepStartedAt = millis();

        switch (pattern)
        {
        case Pattern::TagSuccess:
        {
            setGreenLed(true);

            tone(
                Config::Signal::BUZZER,
                Config::Signal::SuccessToneHz);

            break;
        }

        case Pattern::TagError:
        {
            setRedLed(true);

            tone(
                Config::Signal::BUZZER,
                Config::Signal::ErrorToneHz);

            break;
        }

        case Pattern::Startup:
        {
            setGreenLed(true);

            tone(
                Config::Signal::BUZZER,
                1800U);

            break;
        }

        case Pattern::None:
        default:
        {
            stopSignal();
            break;
        }
        }
    }

    void SignalManager::setRedLed(
        bool enabled) noexcept
    {
        digitalWrite(
            Config::Signal::LED_RED,
            ledLevel(enabled));
    }

    void SignalManager::setGreenLed(
        bool enabled) noexcept
    {
        digitalWrite(
            Config::Signal::LED_GREEN,
            ledLevel(enabled));
    }

    void SignalManager::stopSignal() noexcept
    {
        noTone(Config::Signal::BUZZER);

        setRedLed(false);
        setGreenLed(false);

        m_pattern = Pattern::None;
        m_step = 0U;
        m_stepStartedAt = millis();
    }

}