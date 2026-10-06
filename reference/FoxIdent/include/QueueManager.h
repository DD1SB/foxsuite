/******************************************************************************
 *  Project : FoxIdent
 *  File    : QueueManager.h
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#pragma once

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include "Types.h"

namespace Fox
{

    class QueueManager
    {
    public:
        QueueManager() = default;

        ~QueueManager();

        bool begin();

        QueueHandle_t rfidQueue() const noexcept;
        QueueHandle_t logQueue() const noexcept;
        QueueHandle_t txQueue() const noexcept;

    private:
        QueueHandle_t m_rfidQueue = nullptr;
        QueueHandle_t m_logQueue = nullptr;
        QueueHandle_t m_txQueue = nullptr;
    };

} // namespace Fox