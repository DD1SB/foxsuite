#include <SPI.h>
#include <RH_SX126x.h>
#include <RHMesh.h>

// Typische SX1262 Pins (z.B. für Lilygo T-Beam v1.1/v1.2 SX1262)
#define SX126X_CS   18
#define SX126X_RST  14
#define SX126X_BUSY 25
#define SX126X_DIO1 26

#define NODE_ADDRESS 2    // Jede Node braucht eine eindeutige ID (1-254)
#define SERVER_ADDRESS 1  // ID des Servers

// Instanzen für Funk (SX126x) und Mesh
RH_SX126x sx1262(SX126X_CS, SX126X_DIO1, SX126X_RST, SX126X_BUSY);
RHMesh manager(sx1262, NODE_ADDRESS);

// Struktur für die Funk-Payload (Datenpaket)
// Wichtig: Rufzeichen integrieren für Amateurfunk-Konformität!
struct __attribute__((__packed__)) Payload {
    uint32_t timestamp;
    uint8_t uid[7];      // Array auf 7 Byte korrigiert (typisch für RFID ISO14443A)
    char callsign[10];   // Ihr Amateurfunk-Rufzeichen (z.B. "DO1XYZ\0")
};

// Lokaler Speicher zur Entkopplung
Payload pendingData;
bool hasPendingData = false;
uint32_t currentStationTime = 0; 
uint32_t lastTick = 0;

void setup() {
    Serial.begin(115200);
    
    // RFID-Hardware Setup hier einfügen
    // initRFID();

    // 1. Treiber-Initialisierung für den SX1262
    if (!sx1262.init()) {
        Serial.println("SX1262 Treiber-Init fehlgeschlagen!");
        while (1);
    }
    
    // Zwingend erforderlich für SX1262: Chip-Typ spezifizieren
    // Optionen sind meist RH_SX126x::SX1261 oder RH_SX126x::SX1262
    sx1262.setModemConfig(RH_SX126x::LoRa_Bw125Cr45Sf128); // Standard-Profil setzen

    // 2. Mesh-Manager über den SX1262-Treiber initialisieren
    if (!manager.init()) {
        Serial.println("Mesh-Manager Init fehlgeschlagen!");
        while (1);
    }
    
    // Frequenz einstellen (Bereich für digitale Breitbandexperimente)
    sx1262.setFrequency(439.700);
    
    // Sendeleistung anpassen (SX1262 kann bis zu +22dBm / ~160mW)
    // Als Funkamateur dürfen Sie das ausreizen, sofern thermisch stabil
    sx1262.setTxPower(2);  // max 22dBm
    
    // Timeouts für dynamisches Mesh drastisch kürzen (12-Stunden-Betrieb!)
    manager.setTimeout(1500); 
    
    // Erste Zeitsynchronisation triggern
    requestTimeFromServer();
}

void loop() {
    // 1. Interne Uhr emulieren (Sekundentakt)
    if (millis() - lastTick >= 1000) {
        currentStationTime++;
        lastTick = millis();
    }

    // 2. ABSOLUTE PRIORITÄT: RFID Tag erkennen
    // Dieser Block läuft blockierungsfrei ohne delay()!
    if (checkForNewRFIDTag()) { 
        uint8_t detectedUid[7] = {0x04, 0xDE, 0xAD, 0xBE, 0xEF, 0x23, 0x42}; // Beispiel-UID
        
        // SOFORT auf das Tag schreiben! (Höchste Priorität)
        writeToRFIDTag(NODE_ADDRESS, currentStationTime);
        
        // Daten für das Mesh-Netzwerk im Hintergrund zwischenspeichern
        pendingData.timestamp = currentStationTime;
        memcpy(pendingData.uid, detectedUid, 7);
        strcpy(pendingData.callsign, "DO1XYZ"); // Zwingend Ihr Rufzeichen!
        hasPendingData = true;
        
        Serial.println("Tag beschrieben & in Mesh-Queue eingereiht.");
    }

    // 3. MESH-VERKEHR (Nur wenn RFID IDLE ist und Daten warten)
    if (hasPendingData) {
        Serial.println("Versuche Daten an Server zu senden...");
        
        // Senden via Mesh (blockiert kurz, aber RFID ist bereits abgearbeitet)
        uint8_t error = manager.sendtoWait((uint8_t*)&pendingData, sizeof(pendingData), SERVER_ADDRESS);
        
        if (error == RH_ROUTER_ERROR_NONE) {
            Serial.println("Mesh-Senden erfolgreich!");
            hasPendingData = false; 
        } else {
            Serial.print("Mesh-Fehler, Code: ");
            Serial.println(error);
            // Behält hasPendingData = true für den nächsten Versuch
        }
    }

    // Laufend eingehende Mesh-Pakete abfangen (z.B. automatische Zeitantworten)
    uint8_t buf[RH_MESH_MAX_MESSAGE_LEN];
    uint8_t len = sizeof(buf);
    uint8_t from;
    if (manager.recvfromAck(buf, &len, &from)) {
        if (from == SERVER_ADDRESS && len == sizeof(uint32_t)) {
            memcpy(&currentStationTime, buf, sizeof(uint32_t));
            Serial.print("Uhrzeit vom Server synchronisiert: ");
            Serial.println(currentStationTime);
        }
    }
}

// --- DUMMY FUNKTIONEN ---
bool checkForNewRFIDTag() { return false; }
void writeToRFIDTag(uint8_t nodeID, uint32_t timestamp) {}
void requestTimeFromServer() {
    uint8_t req = 0xFF;
    manager.sendtoWait(&req, 1, SERVER_ADDRESS);
}
