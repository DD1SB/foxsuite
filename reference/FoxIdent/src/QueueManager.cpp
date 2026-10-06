/******************************************************************************
 *  Project : FoxIdent
 *  File    : QueueManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "QueueManager.h"

#include "Config.h"

namespace Fox
{

    QueueManager::~QueueManager()
    {
        if (m_rfidQueue != nullptr)
        {
            vQueueDelete(m_rfidQueue);
        }

        if (m_logQueue != nullptr)
        {
            vQueueDelete(m_logQueue);
        }

        if (m_txQueue != nullptr)
        {
            vQueueDelete(m_txQueue);
        }
    }

    bool QueueManager::begin()
    {
        m_rfidQueue = xQueueCreate(Config::Queue::RFID, sizeof(TagEvent));

        if (m_rfidQueue == nullptr)
        {
            return false;
        }

        m_logQueue = xQueueCreate(Config::Queue::LOG, sizeof(LogEntry));

        if (m_logQueue == nullptr)
        {
            return false;
        }

        m_txQueue = xQueueCreate(Config::Queue::TX, sizeof(TagPacket));

        if (m_txQueue == nullptr)
        {
            return false;
        }

        return true;
    }

    QueueHandle_t QueueManager::rfidQueue() const noexcept
    {
        return m_rfidQueue;
    }

    QueueHandle_t QueueManager::logQueue() const noexcept
    {
        return m_logQueue;
    }

    QueueHandle_t QueueManager::txQueue() const noexcept
    {
        return m_txQueue;
    }

} // namespace Fox