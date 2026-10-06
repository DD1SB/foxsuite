import serial
import time
import sqlite3
import threading

# Konfiguration (Hier den COM-Port des LILYGO-Boards eintragen)
SERIAL_PORT = "COM3"  # Unter Linux/Mac z.B. "/dev/ttyACM0" oder "/dev/ttyUSB0"
BAUD_RATE = 115200
DB_NAME = "laufzeit_erfassung.db"

# 1. SQLite Datenbank initialisieren
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pc_timestamp INTEGER,
        node_id INTEGER,
        callsign TEXT,
        rfid_uid TEXT,
        node_timestamp INTEGER
    )
''')
conn.commit()

# Seriellen Port öffnen
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)

# Thread 1: Sendet jede Sekunde die aktuelle Rechnerzeit an den ESP32
def send_time_sync():
    while True:
        try:
            current_time = int(time.time())
            # Format: T<timestamp>\n
            ser.write(f"T{current_time}\n".encode())
            time.sleep(1)
        except Exception as e:
            print(f"Fehler beim Zeitsynchronisieren: {e}")
            break

# Thread starten
threading.Thread(target=send_time_sync, daemon=True).start()

print("Warte auf LoRa-Daten vom USB-Interface...")

# Hauptschleife: Daten vom ESP32 empfangen und in SQLite schreiben
try:
    while True:
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            
            # Prüfen, ob es sich um Datensätze handelt
            if line.startswith("DATA;"):
                parts = line.split(";")
                if len(parts) == 5:
                    _, node_id, callsign, rfid_uid, node_timestamp = parts
                    pc_time = int(time.time())
                    
                    # In SQLite schreiben
                    cursor.execute('''
                        INSERT INTO scans (pc_timestamp, node_id, callsign, rfid_uid, node_timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (pc_time, int(node_id), callsign, rfid_uid, int(node_timestamp)))
                    conn.commit()
                    
                    print(f" -> [SQLITE GEPEICHERT] Node #{node_id} ({callsign}) - UID: {rfid_uid}")
except KeyboardInterrupt:
    print("\nProgramm beendet.")
finally:
    ser.close()
    conn.close()
