// bridge
// -*- mode: C++ -*-
// Example sketch showing how to create a simple addressed, routed reliable messaging client
// with the RHMesh class.
// It is designed to work with the other examples rf95_mesh_server*
// Hint: you can simulate other network topologies by setting the 
// RH_TEST_NETWORK define in RHRouter.h

// Mesh has much greater memory requirements, and you may need to limit the
// max message length to prevent wierd crashes
#define RH_MESH_MAX_MESSAGE_LEN 50

#include "pins.h"
#include <RHMesh.h>
#include <RH_RF95.h>
#include <SPI.h>
#include <Wire.h>
#include <U8g2lib.h>

// In this small artifical network of 4 nodes,
#define BRIDGE_ADDRESS 1  // address of the bridge ( we send our data to, hopefully the bridge knows what to do with our data )
#define NODE_ADDRESS 1
#define RXTIMEOUT 3000  // it is roughly the delay between successive transmissions
#define LORA_TX_POWER 20
#define LORA_FREQ 434.1

// Singleton instance of the radio driver
RH_RF95 driver(LLG_CS, LLG_DI0); // slave select pin and interrupt pin, [heltec|ttgo] ESP32 Lora OLED with sx1276/8
// Class to manage message delivery and receipt, using the driver declared above
RHMesh manager(driver, BRIDGE_ADDRESS);

U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE, OLED_SCL, OLED_SDA);

uint32_t masterTime = 0; // Wird vom Laptop via USB synchronisiert
uint32_t totalScansReceived = 0;
uint8_t lastActiveNode = 0;
String serialBuffer = "";

void updateDisplay() {
    u8g2.clearBuffer();
    
    u8g2.setFont(u8g2_font_6x10_tf);
    u8g2.drawStr(0, 10, "LoRa Mesh Server v1.0");
    u8g2.drawHLine(0, 14, 128);
    
    // Status-Werte
    u8g2.setCursor(0, 28);
    u8g2.print("Zeit: "); u8g2.print(masterTime);
    
    u8g2.setCursor(0, 42);
    u8g2.print("Scans gesamt: "); u8g2.print(totalScansReceived);
    
    u8g2.setCursor(0, 56);
    if (lastActiveNode > 0) {
        u8g2.print("Letzter Node: #"); u8g2.print(lastActiveNode);
    } else {
        u8g2.print("Warte auf Daten...");
    }
    u8g2.sendBuffer();
}

void setup() 
{
  Serial.begin(115200);

  Serial.println("Trying to initialize LoRa Mesh Bridge...");
  Serial.println("Display first.");
  // I2C und OLED initialisieren
  Wire.begin(OLED_SDA, OLED_SCL);
  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(0, 20, "Booting...");
  u8g2.sendBuffer();

  Serial.print(F("initializing node "));
  Serial.print(BRIDGE_ADDRESS);
  SPI.begin(LLG_SCK,LLG_MISO,LLG_MOSI,LLG_CS);
  if (!manager.init())
    {Serial.println(" init failed");} 
  else
    {Serial.println(" done");}  // Defaults after init are 434.0MHz, 0.05MHz AFC pull-in, modulation FSK_Rb2_4Fd36 

  driver.setTxPower(LORA_TX_POWER, false); // with false output is on PA_BOOST, power from 2 to 20 dBm, use this setting for high power demos/real usage
  //driver.setTxPower(1, true); // true output is on RFO, power from 0 to 15 dBm, use this setting for low power demos ( does not work on lilygo lora32 )
  driver.setFrequency(LORA_FREQ);
  driver.setCADTimeout(500);

  // long range configuration requires for on-air time
  boolean longRange = false;
  if (longRange) 
    {
    // custom configuration
    RH_RF95::ModemConfig modem_config = {
      0x78, // Reg 0x1D: BW=125kHz, Coding=4/8, Header=explicit
      0xC4, // Reg 0x1E: Spread=4096chips/symbol, CRC=enable
      0x08  // Reg 0x26: LowDataRate=On, Agc=Off.  0x0C is LowDataRate=ON, ACG=ON
      };
    driver.setModemRegisters(&modem_config);
    }
  else
    {
    // Predefined configurations( bandwidth, coding rate, spread factor ):
    // Bw125Cr45Sf128     Bw = 125 kHz, Cr = 4/5, Sf = 128chips/symbol, CRC on. Default medium range
    // Bw500Cr45Sf128     Bw = 500 kHz, Cr = 4/5, Sf = 128chips/symbol, CRC on. Fast+short range
    // Bw31_25Cr48Sf512   Bw = 31.25 kHz, Cr = 4/8, Sf = 512chips/symbol, CRC on. Slow+long range
    // Bw125Cr48Sf4096    Bw = 125 kHz, Cr = 4/8, Sf = 4096chips/symbol, low data rate, CRC on. Slow+long range
    // Bw125Cr45Sf2048    Bw = 125 kHz, Cr = 4/5, Sf = 2048chips/symbol, CRC on. Slow+long range
    if (!driver.setModemConfig(RH_RF95::Bw125Cr45Sf128))
      {Serial.println(F("set config failed"));}
    }
  Serial.println("RF95 ready");
  updateDisplay();
}

void Print_Hexa(uint8_t num) {
  char Hex_Array[2];

  sprintf(Hex_Array, "%02X", num);
  Serial.print(Hex_Array);
}

uint8_t data[] = "Hello back from bridge";
// Dont put this on the stack:
uint8_t buf[RH_MESH_MAX_MESSAGE_LEN];
uint8_t res;

void loop()
{
  uint8_t len = sizeof(buf);
  uint8_t from;
  if (manager.recvfromAck(buf, &len, &from))
    {
    totalScansReceived++;
    lastActiveNode = from;
    Serial.print("request from node n.");
    Serial.print(from);
    Serial.print(". rssi: ");
    Serial.print(driver.lastRssi());
    Serial.print(" dBm, with a SNR of ");
    Serial.print(driver.lastSNR());
    Serial.print(" dB. Data: ");
    for(int i = 0; i < len; i++){
      Serial.print("0x");
      Print_Hexa(buf[i]);
      Serial.print(" ");
    }
    updateDisplay();
    // manager.sendtoWait((uint8_t*)&masterTime, sizeof(masterTime), from);
    }
}