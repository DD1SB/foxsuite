/******************************************************************************
 *  Project : FoxIdent
 *  File    : TaskManager.h
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

    class RFIDManager;
    class LogManager;
    class LoraManager;
    class StationController;

    /**
     * @brief Creates and manages FreeRTOS tasks.
     */
    class TaskManager
    {
    public:
        TaskManager(RFIDManager &rfid, LogManager &log, LoraManager &lora, StationController &controller);

        bool begin() noexcept;

    private:
        static void rfidTask(void *parameter);

        static void logTask(void *parameter);

        static void loraTask(void *parameter);

        static void controllerTask(void *parameter);

    private:
        RFIDManager &m_rfid;

        LogManager &m_log;

        LoraManager &m_lora;

        StationController &m_controller;
    };

} // namespace Fox