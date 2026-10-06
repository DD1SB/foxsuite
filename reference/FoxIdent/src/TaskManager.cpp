/******************************************************************************
 *  Project : FoxIdent
 *  File    : TaskManager.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include "TaskManager.h"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include "Config.h"
#include "LogManager.h"
#include "LoraManager.h"
#include "RFIDManager.h"
#include "StationController.h"

namespace Fox
{

    TaskManager::TaskManager(RFIDManager &rfid, LogManager &log, LoraManager &lora, StationController &controller)
        : m_rfid(rfid), m_log(log), m_lora(lora), m_controller(controller)
    {
    }

    //=============================================================================

    bool TaskManager::begin() noexcept
    {

        if (xTaskCreate(rfidTask, "RFID", Config::Stack::RFID, &m_rfid, Config::Priority::RFID, nullptr) != pdPASS)
        {
            return false;
        }

        if (xTaskCreate(controllerTask, "CTRL", Config::Stack::Station, &m_controller, Config::Priority::Station, nullptr) != pdPASS)
        {
            return false;
        }

        if (xTaskCreate(loraTask, "LORA", Config::Stack::LoRa, &m_lora, Config::Priority::LoRa, nullptr) != pdPASS)
        {
            return false;
        }

        if (xTaskCreate(logTask, "LOG", Config::Stack::Logger, &m_log, Config::Priority::Logger, nullptr) != pdPASS)
        {
            return false;
        }

        return true;
    }

    //=============================================================================

    void TaskManager::rfidTask(void *parameter)
    {
        auto *manager = static_cast<RFIDManager *>(parameter);

        for (;;)
        {
            manager->update();

            vTaskDelay(pdMS_TO_TICKS(5U));
        }
    }

    //=============================================================================

    void TaskManager::controllerTask(void *parameter)
    {
        auto *controller = static_cast<StationController *>(parameter);

        for (;;)
        {
            controller->update();

            vTaskDelay(pdMS_TO_TICKS(10U));
        }
    }

    //=============================================================================

    void TaskManager::loraTask(void *parameter)
    {
        auto *manager = static_cast<LoraManager *>(parameter);

        for (;;)
        {
            manager->update();

            vTaskDelay(pdMS_TO_TICKS(20U));
        }
    }

    //=============================================================================

    void TaskManager::logTask(void *parameter)
    {
        auto *manager = static_cast<LogManager *>(parameter);

        for (;;)
        {
            manager->update();

            vTaskDelay(pdMS_TO_TICKS(50U));
        }
    }

} // namespace Fox