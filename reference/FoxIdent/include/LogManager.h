/******************************************************************************
 *  Project : FoxIdent
 *  File    : LogManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <FS.h>
#include <SD_MMC.h>

#include "Types.h"

namespace Fox
{

    class QueueManager;

    /**
     * @brief Handles binary logging to SD card.
     *
     * Log entries are received from the LogQueue and appended
     * to a binary logfile.
     */
    class LogManager
    {
    public:
        explicit LogManager(QueueManager &queues);

        bool begin() noexcept;

        void update() noexcept;

    private:
        bool writeEntry(const LogEntry &entry) noexcept;

        bool openLogFile() noexcept;

    private:
        QueueManager &m_queues;

        File m_file;

        bool m_initialized = false;

        std::uint32_t m_lastFlush = 0U;
    };

} // namespace Fox