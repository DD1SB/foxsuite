/******************************************************************************
 *  Project : FoxIdent
 *  File    : main.cpp
 *  Version : 1.0.0
 *
 *  Copyright (c) 2026 Stefan Biermann / DD1SB
 *
 *  Firmware licensed under the MIT License.
 *  See LICENSE for details.
 ******************************************************************************/

#include <Arduino.h>

#include "Config.h"
#include "LogManager.h"
#include "LoraManager.h"
#include "PacketManager.h"
#include "QueueManager.h"
#include "RFIDManager.h"
#include "StationController.h"
#include "TaskManager.h"
#include "TimeManager.h"
#include "SignalManager.h"

using namespace Fox;

QueueManager queueManager;

PacketManager packetManager;

TimeManager timeManager;

SignalManager signalManager;

RFIDManager rfidManager(queueManager, timeManager, signalManager);

LogManager logManager(queueManager);

LoraManager loraManager(queueManager, packetManager, timeManager);

StationController controller(queueManager, timeManager);

TaskManager taskManager(rfidManager, logManager, loraManager, controller);

void setup()
{
    Serial.begin(115200);

    delay(500);

    Serial.println();
    Serial.println("FoxStation 1.0.0");
    Serial.println("Starting...");

    if (!queueManager.begin())
    {
        Serial.println("Queue init failed");
        return;
    }

    if (!timeManager.begin())
    {
        Serial.println("Time init failed");
        return;
    }

    if (!rfidManager.begin())
    {
        Serial.println("RFID init failed");
        return;
    }

    if (!logManager.begin())
    {
        Serial.println("SD init failed");
        return;
    }

    if (!loraManager.begin())
    {
        Serial.println("LoRa init failed");
        return;
    }

    if (!controller.begin())
    {
        Serial.println("Controller init failed");
        return;
    }

    if (!taskManager.begin())
    {
        Serial.println("Task creation failed");
        return;
    }

    signalManager.begin();
    signalManager.signalStartup();

    Serial.println("FoxStation ready");
}

void loop()
{

    vTaskDelay(portMAX_DELAY);
}