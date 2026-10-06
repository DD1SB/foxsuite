/******************************************************************************
 *  Project : FoxIdent
 *  File    : StationController.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include "Types.h"

namespace Fox
{

    class QueueManager;
    class TimeManager;

    /**
     * @brief Central application state controller.
     *
     * Connects RFID events with logging and LoRa transmission.
     */
    class StationController
    {
    public:
        StationController(QueueManager &queues, TimeManager &time);

        bool begin() noexcept;

        void update() noexcept;

        StationState state() const noexcept;

    private:
        void processRFID() noexcept;

    private:
        QueueManager &m_queues;

        TimeManager &m_time;

        StationState m_state = StationState::Startup;

        bool m_initialized = false;
    };

} // namespace Fox