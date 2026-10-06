#include "pins.h"
#include <Wire.h>
#include "Adafruit_PN532.h"
#include "ESP32_DESFire.h"

Adafruit_PN532 nfc(PN532_SDA, PN532_SCL);
ESP32_DESFire desfire(&nfc);

void printHex(byte *buffer, uint16_t bufferSize);

const char *DIVIDER = "-------------------------------------------------------------------------";

boolean success;
char scrBuf[60];                          // buffer for tft outputs
uint8_t uid[] = { 0, 0, 0, 0, 0, 0, 0 };  // Buffer to store the returned UID
uint8_t uidLength;                        // Length of the UID (4 or 7 bytes depending on ISO14443A card type)
ESP32_DESFire::DF_StatusCode dfStatusCode;

byte *appData = new byte[128];  // used as input or output buffer
byte appLen = 128;
uint16_t appLenExt = 128;
byte appDataByte = (byte)0xFF;

#include "T01_Basic.h"  // Tutorial workflow

void nfcInitialization() {
  Wire.begin(PN532_SDA, PN532_SCL);
  Wire.setClock(100000);
  nfc.begin();
  // nfc.SAMConfig();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.print("Didn't find PN53x board, halting");
    while (1)
      ;  // halt
  }

  // Got ok data, print it out!
  Serial.print("Found chip PN5");
  Serial.println((versiondata >> 24) & 0xFF, HEX);
  Serial.print("Firmware ver. ");
  Serial.print((versiondata >> 16) & 0xFF, DEC);
  Serial.print('.');
  Serial.println((versiondata >> 8) & 0xFF, DEC);

  // Set the max number of retry attempts to read from a card
  // This prevents us from waiting forever for a card, which is
  // the default behaviour of the PN532.
  // nfc.setPassiveActivationRetries(0xFF);
}

void printHex(byte *buffer, uint16_t bufferSize) {
  for (uint16_t i = 0; i < bufferSize; i++) {
    Serial.print(buffer[i] < 0x10 ? " 0" : " ");
    Serial.print(buffer[i], HEX);
  }
}

void printHexShort(byte *buffer, uint16_t bufferSize) {
  for (uint16_t i = 0; i < bufferSize; i++) {
    Serial.print(buffer[i] < 0x10 ? "0" : "");
    Serial.print(buffer[i], HEX);
  }
}

void setup() {
  Serial.begin(115200);
  nfcInitialization();
  Serial.println("Ready.");
}

void loop() {
  // Wait for an ISO14443A type cards (Mifare, etc.).
  success = nfc.inListPassiveTarget();

  if (success) {
    Serial.println("Found a card!");

    run_T01_Basic_Handling();

    delay(20000);
  }
}