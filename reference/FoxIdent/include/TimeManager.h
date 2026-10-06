/******************************************************************************
 *  Project : FoxIdent
 *  File    : TimeManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <cstdint>

namespace Fox
{

    /**
     * @brief Provides the local station time base.
     *
     * Time is received from the base station via LoRa sync packets.
     * Until synchronization is completed, the manager reports an invalid state.
     */
    class TimeManager
    {
    public:
        TimeManager() = default;

        /**
         * @brief Initialize time manager.
         *
         * @return true if initialization succeeded.
         */
        bool begin() noexcept;

        /**
         * @brief Update internal time reference.
         *
         * @param unixTime Unix timestamp in seconds.
         */
        void synchronize(std::uint32_t unixTime) noexcept;

        /**
         * @brief Get current Unix timestamp.
         *
         * @return Current timestamp.
         */
        std::uint32_t now() const noexcept;

        /**
         * @brief Check synchronization status.
         *
         * @return true if synchronized.
         */
        bool isSynchronized() const noexcept;

    private:
        bool m_synchronized = false;

        std::uint32_t m_referenceTime = 0U;

        std::uint32_t m_referenceMillis = 0U;
    };

} // namespace Fox