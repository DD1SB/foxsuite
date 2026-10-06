/******************************************************************************
 *
 *  FoxBase
 *
 *  File:
 *      main.cpp
 *
 ******************************************************************************/

#include <Arduino.h>

#include "BaseLoraManager.h"
#include "Config.h"
#include "PacketManager.h"

using namespace Fox;

PacketManager packetManager;
BaseLoraManager loraManager(packetManager);
String serialLine;

void processSerial() noexcept
{
  while (Serial.available() > 0)
  {
    const char character = static_cast<char>(Serial.read());

    if (character == '\r')
    {
      continue;
    }

    if (character != '\n')
    {
      serialLine += character;
      continue;
    }

    serialLine.trim();

    if (serialLine.startsWith("TIME "))
    {
      const std::uint32_t unixTime = static_cast<std::uint32_t>(serialLine.substring(5).toInt());

      if (unixTime > 0U)
      {
        loraManager.synchronizeClock(unixTime);
      }
    }
    serialLine.clear();
  }
}

void setup()
{
  Serial.begin(Config::Base::SerialBaud);
  delay(500U);

  Serial.println();
  Serial.println("FoxBase 1.0.0");

  if (!loraManager.begin())
  {
    Serial.println("[BASE] startup failed");
  }

}

void loop()
{
  processSerial();
  loraManager.update();
}
