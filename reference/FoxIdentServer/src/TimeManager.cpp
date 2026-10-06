/******************************************************************************
 *
 *  FoxStation
 *
 *  File:
 *      TimeManager.cpp
 *
 *  Version:
 *      1.0.0
 *
 ******************************************************************************/

#include "TimeManager.h"

#include <Arduino.h>

namespace Fox
{

    bool TimeManager::begin() noexcept
    {
        m_synchronized = false;

        m_referenceTime = 0U;

        m_referenceMillis = millis();

        return true;
    }

    //=============================================================================

    void TimeManager::synchronize(std::uint32_t unixTime) noexcept
    {
        m_referenceTime = unixTime;

        m_referenceMillis = millis();

        m_synchronized = true;
    }

    //=============================================================================

    std::uint32_t TimeManager::now() const noexcept
    {
        if (!m_synchronized)
        {
            return millis();
        }

        const std::uint32_t elapsedSeconds = (millis() - m_referenceMillis) / 1000U;

        return m_referenceTime + elapsedSeconds;
    }

    //=============================================================================

    bool TimeManager::isSynchronized() const noexcept
    {
        return m_synchronized;
    }

} // namespace Fox