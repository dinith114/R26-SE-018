/*
 * ============================================================
 * Smart Orchid Care System — Sensor Data Logger
 * ============================================================
 * Board:    NodeMCU ESP32 WiFi + Bluetooth
 * Sensors:  DHT22 (Temp/Humidity), BH1750 (Light), Capacitive Root Moisture
 * Purpose:  Read all sensors every INTERVAL and log to Serial + WiFi
 *
 * VANDA ORCHID NOTE:
 *   Vanda orchids have EXPOSED AERIAL ROOTS — they grow in baskets
 *   with no soil. The capacitive moisture sensor is pressed directly
 *   against the root mass. Wet roots (green) have higher dielectric
 *   permittivity → lower ADC reading. Dry roots (silvery-white) have
 *   lower permittivity → higher ADC reading. This gives a reliable
 *   0-100% root hydration proxy without needing any soil.
 *
 * WIRING:
 *   DHT22:
 *     VCC  → 3.3V
 *     GND  → GND
 *     DATA → GPIO 4
 *     (10K pull-up resistor between VCC and DATA recommended)
 *
 *   BH1750:
 *     VCC  → 3.3V
 *     GND  → GND
 *     SDA  → GPIO 21 (default I2C SDA)
 *     SCL  → GPIO 22 (default I2C SCL)
 *
 *   Capacitive Root Moisture Sensor (on Vanda aerial root mass):
 *     VCC  → 3.3V (or 5V depending on module)
 *     GND  → GND
 *     AO   → GPIO 34 (analog input, ADC1)
 *
 * LIBRARIES REQUIRED (install via Arduino Library Manager):
 *   - DHT sensor library by Adafruit
 *   - Adafruit Unified Sensor
 *   - BH1750 by Christopher Laws
 *   - WiFi (built-in with ESP32 board package)
 *   - HTTPClient (built-in with ESP32 board package)
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <BH1750.h>

// ======================== CONFIGURATION ========================

// WiFi Credentials
const char* WIFI_SSID     = "Pixel_8047";
const char* WIFI_PASSWORD = "24681012";

// Device identity — set per device before flashing.
// Each sensor pack covers ONE microclimate zone of ONE house
// (zone count per house comes from the app's Sensor Device Calculator).
#define HOUSE_ID  "H1"
#define ZONE_ID   "Z1"

// Firebase Realtime Database URLs
// Per-house/zone paths (read by the multi-house app):
const char* FIREBASE_LATEST_URL  = "https://orchid-smart-care-default-rtdb.firebaseio.com/houses/" HOUSE_ID "/zones/" ZONE_ID "/latest.json";
const char* FIREBASE_HISTORY_URL = "https://orchid-smart-care-default-rtdb.firebaseio.com/houses/" HOUSE_ID "/zones/" ZONE_ID "/history.json";
// Legacy flat path (kept so the old dashboard still updates):
const char* FIREBASE_LEGACY_LATEST_URL = "https://orchid-smart-care-default-rtdb.firebaseio.com/latest.json";

// ======================== WATER PUMP (RELAY) ========================
// The app's "Water This House" button writes /houses/{H}/control/waterCommand.
// This device polls that path and runs the pump for the requested duration.
//
// WIRING (see PUMP_SIMPLE.html):
//   Relay module:  IN → GPIO26,  VCC → 5V(VIN),  GND → GND
//   Pump circuit:  12V adapter(+) → relay COM, relay NO → pump(+), pump(−) → adapter(−)
#define ENABLE_PUMP       true
#define PUMP_RELAY_PIN    26
#define RELAY_ACTIVE_LOW  true     // most relay modules switch ON when IN is LOW; set false if yours is reversed
#define CMD_CHECK_MS      5000     // poll the water command every 5 s
#define PUMP_MAX_SEC      300      // hard safety cap

// ======================== FERTILIZER DOSING (2nd relay) ========================
// Fertilizer is NEVER a separate line running on its own — it is a short dose of
// concentrate injected into the SAME hose while the water pump is already running,
// so it's never applied to dry roots. The backend decides per-zone (High-N/High-P)
// and folds the flag into the same waterCommand — this device just fires relay 2.
//
// WIRING (see FERT_SIMPLE.html):
//   2nd relay channel: IN2 → GPIO27, VCC/GND shared with relay 1
//   Dosing pump circuit: 12V adapter(+) → relay2 COM, relay2 NO → dosing pump(+),
//                         dosing pump(−) → adapter(−); dosing pump outlet → check
//                         valve → T-fitting into the main water hose.
#define ENABLE_FERTILIZER true
#define FERT_RELAY_PIN    27
#define FERT_DOSE_SEC     8        // short dose — carried onto the roots by the water flow

const char* FIREBASE_CMD_URL = "https://orchid-smart-care-default-rtdb.firebaseio.com/houses/" HOUSE_ID "/control/waterCommand.json";

// Sensor Pins
#define DHT_PIN           4     // DHT22 data pin
#define DHT_TYPE          DHT22
#define ROOT_MOISTURE_PIN 34    // Analog input for capacitive sensor on root mass

// Timing
#define READ_INTERVAL_MS  300000   // 5 minutes (production — matches ML trend window)
// Use 10000 (10 s) only for bench testing

// Root Moisture Calibration (capacitive sensor on Vanda aerial root mass)
// Calibrate with YOUR sensor against the actual roots:
//   - Hold sensor in AIR (no contact) → note ADC value  (ROOT_DRY_VALUE)
//   - Press sensor against freshly watered roots          (ROOT_WET_VALUE)
// Silvery-white dry roots → high ADC; green wet roots → low ADC
#define ROOT_DRY_VALUE    4095    // ADC reading when sensor is in dry air
#define ROOT_WET_VALUE    1500    // ADC reading when pressed on wet roots (adjust after testing)

// ======================== GLOBAL OBJECTS ========================

DHT dht(DHT_PIN, DHT_TYPE);
BH1750 lightSensor;

// Tracking
unsigned long lastReadTime = 0;
unsigned long lastWaterTime = 0;    // Track when last watered (manual input or auto)
int readingCount = 0;

// Pump state
unsigned long lastCmdCheck = 0;
unsigned long pumpUntil    = 0;     // millis() when the pump must stop (0 = idle)
int lastPumpRunSec         = 0;

// Fertilizer dosing state (runs inside the same watering window)
bool          fertPending  = false; // this run should dose fertilizer
unsigned long fertUntil    = 0;     // millis() when the dosing pump must stop (0 = idle/not started)
String        lastFertType = "";

// ======================== SENSOR DATA STRUCTURE ========================

struct SensorData {
  float temperature;       // °C
  float humidity;          // %
  float light;             // lux
  int rootMoistureRaw;     // raw ADC value (0-4095) from capacitive sensor on root mass
  float rootMoisturePct;   // normalized 0-100% (100% = wet green roots, 0% = dry silvery roots)
  float hoursSinceWater;   // hours since last watering
  bool isValid;            // all readings OK?
};

// ======================== SETUP ========================

void setup() {
  Serial.begin(115200);
  delay(2000);  // Wait for serial monitor
  
  Serial.println();
  Serial.println("============================================");
  Serial.println("  Smart Orchid Care — Sensor Data Logger");
  Serial.println("  Vanda Orchid Watering Prediction System");
  Serial.println("============================================");
  Serial.println();

  // Initialize DHT22
  dht.begin();
  Serial.println("[OK] DHT22 initialized on GPIO " + String(DHT_PIN));

  // Initialize BH1750 — auto-detect address (0x23 / 0x5C) and pin order
  bool bh1750Ok = false;

  // Attempt 1: SDA=D21, SCL=D22, addr=0x23 (ADDR pin floating/LOW)
  Wire.begin(21, 22);
  delay(150);
  if (lightSensor.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire)) {
    Serial.println("[OK] BH1750 on SDA=D21 SCL=D22 addr=0x23");
    bh1750Ok = true;
  }

  // Attempt 2: SDA=D21, SCL=D22, addr=0x5C (ADDR pin HIGH)
  if (!bh1750Ok) {
    Wire.begin(21, 22);
    delay(150);
    if (lightSensor.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x5C, &Wire)) {
      Serial.println("[OK] BH1750 on SDA=D21 SCL=D22 addr=0x5C");
      bh1750Ok = true;
    }
  }

  // Attempt 3: SDA=D22, SCL=D21 (wires swapped), addr=0x23
  if (!bh1750Ok) {
    Wire.begin(22, 21);
    delay(150);
    if (lightSensor.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x23, &Wire)) {
      Serial.println("[OK] BH1750 on SDA=D22 SCL=D21 addr=0x23  <-- your wires are swapped!");
      bh1750Ok = true;
    }
  }

  // Attempt 4: SDA=D22, SCL=D21 (wires swapped), addr=0x5C
  if (!bh1750Ok) {
    Wire.begin(22, 21);
    delay(150);
    if (lightSensor.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, 0x5C, &Wire)) {
      Serial.println("[OK] BH1750 on SDA=D22 SCL=D21 addr=0x5C  <-- wires swapped + ADDR=HIGH");
      bh1750Ok = true;
    }
  }

  if (!bh1750Ok) {
    Serial.println("[ERROR] BH1750 not found on any address or pin combo!");
    Serial.println("        Check: VCC=3.3V GND SDA SCL all connected.");
    Serial.println("[SCAN]  I2C bus scan (SDA=D21 SCL=D22):");
    Wire.begin(21, 22);
    bool found = false;
    for (uint8_t a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) {
        Serial.println("        Device at 0x" + String(a, HEX));
        found = true;
      }
    }
    if (!found) Serial.println("        No devices found.");
    Serial.println("[SCAN]  I2C bus scan (SDA=D22 SCL=D21 swapped):");
    Wire.begin(22, 21);
    found = false;
    for (uint8_t a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) {
        Serial.println("        Device at 0x" + String(a, HEX));
        found = true;
      }
    }
    if (!found) Serial.println("        No devices found.");
  }

  // Initialize Capacitive Root Moisture Sensor
  pinMode(ROOT_MOISTURE_PIN, INPUT);
  Serial.println("[OK] Root Moisture Sensor on GPIO " + String(ROOT_MOISTURE_PIN));

  // Initialize Water Pump Relay (starts OFF)
  if (ENABLE_PUMP) {
    pinMode(PUMP_RELAY_PIN, OUTPUT);
    pumpWrite(false);
    Serial.println("[OK] Pump relay on GPIO " + String(PUMP_RELAY_PIN) + " (OFF)");
  }

  // Initialize Fertilizer Dosing Relay (starts OFF)
  if (ENABLE_FERTILIZER) {
    pinMode(FERT_RELAY_PIN, OUTPUT);
    fertWrite(false);
    Serial.println("[OK] Fertilizer relay on GPIO " + String(FERT_RELAY_PIN) + " (OFF)");
  }

  // Connect to WiFi
  if (strlen(WIFI_SSID) > 0 && String(WIFI_SSID) != "YOUR_WIFI_NAME") {
    connectWiFi();
  } else {
    Serial.println("[SKIP] WiFi not configured — logging to Serial only");
  }

  // Print CSV header
  Serial.println();
  Serial.println("--- DATA LOG START ---");
  Serial.println("Reading#,Timestamp_ms,Temperature_C,Humidity_Pct,Light_lux,RootMoisture_raw,RootMoisture_pct,HoursSinceWater");

  // Record start time as "last watered" (you can change this)
  lastWaterTime = millis();
}

// ======================== MAIN LOOP ========================

void loop() {
  unsigned long now = millis();
  
  // Check if it's time to read
  if (now - lastReadTime >= READ_INTERVAL_MS || lastReadTime == 0) {
    lastReadTime = now;
    readingCount++;
    
    // Read all sensors
    SensorData data = readAllSensors();
    
    // Print to Serial (CSV format for easy copy-paste)
    printCSV(data);
    
    // Send to Firebase
    if (WiFi.status() == WL_CONNECTED) {
      sendToFirebase(data);
    }
  }

  // Check for serial commands
  handleSerialCommands();

  // ---- Water pump control ----
  if (ENABLE_PUMP) {
    // Stop the pump when its run time is over
    if (pumpUntil > 0 && millis() >= pumpUntil) {
      pumpWrite(false);
      pumpUntil = 0;
      // Never let the dosing pump keep injecting into a hose with no water flowing
      if (fertUntil > 0) { fertWrite(false); fertUntil = 0; }
      Serial.println("[PUMP] Done — ran " + String(lastPumpRunSec) + " s. Relay OFF.");
      reportPumpDone();
    }
    // Poll Firebase for a new water command (only while idle)
    if (pumpUntil == 0 && WiFi.status() == WL_CONNECTED &&
        millis() - lastCmdCheck >= CMD_CHECK_MS) {
      lastCmdCheck = millis();
      checkWaterCommand();
    }
  }

  // ---- Fertilizer dosing control ----
  // Dosing pump runs a short window INSIDE the water pump's run — never on its own,
  // so fertilizer concentrate always gets carried onto the roots by flowing water.
  if (ENABLE_FERTILIZER) {
    if (fertUntil > 0 && millis() >= fertUntil) {
      fertWrite(false);
      fertUntil = 0;
      Serial.println("[FERT] Dose complete (" + lastFertType + "). Relay OFF.");
    }
    if (fertPending && pumpUntil > 0 && fertUntil == 0) {
      // Water pump just started this run — begin the fertilizer dose now
      fertUntil = millis() + (unsigned long)FERT_DOSE_SEC * 1000UL;
      fertWrite(true);
      fertPending = false;
      Serial.println("[FERT] Dosing " + lastFertType + " for " + String(FERT_DOSE_SEC) + " s — relay ON");
    }
  }

  delay(100);
}

// ======================== WATER PUMP ========================

void pumpWrite(bool on) {
  if (RELAY_ACTIVE_LOW) digitalWrite(PUMP_RELAY_PIN, on ? LOW : HIGH);
  else                  digitalWrite(PUMP_RELAY_PIN, on ? HIGH : LOW);
}

// Poll /houses/{H}/control/waterCommand — if requested, run the pump.
void checkWaterCommand() {
  HTTPClient http;
  http.begin(FIREBASE_CMD_URL);
  int code = http.GET();
  String payload = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || payload.length() < 2 || payload == "null") return;

  if (payload.indexOf("\"requested\":true") < 0) return;

  // Parse durationSec (defaults to 30, capped for safety)
  int duration = 30;
  int di = payload.indexOf("\"durationSec\":");
  if (di >= 0) duration = payload.substring(di + 14).toInt();
  if (duration < 1)            duration = 30;
  if (duration > PUMP_MAX_SEC) duration = PUMP_MAX_SEC;

  // Parse fertilize flag + type — backend already decided this from the zone
  // predictions, so the device just needs to know whether to dose this run.
  bool doFert = ENABLE_FERTILIZER && payload.indexOf("\"fertilize\":true") >= 0;
  String fertType = "";
  if (doFert) {
    int fi = payload.indexOf("\"fertilizerType\":\"");
    if (fi >= 0) {
      int start = fi + 19;
      int end   = payload.indexOf("\"", start);
      if (end > start) fertType = payload.substring(start, end);
    }
  }

  // Acknowledge FIRST (requested:false) so the command never runs twice
  HTTPClient ack;
  ack.begin(FIREBASE_CMD_URL);
  ack.addHeader("Content-Type", "application/json");
  ack.PUT("{\"requested\":false,\"status\":\"running\",\"durationSec\":" + String(duration) +
          ",\"fertilizing\":" + String(doFert ? "true" : "false") + "}");
  ack.end();

  // Start the pump (non-blocking — loop() stops it when time is up)
  lastPumpRunSec = duration;
  pumpUntil = millis() + (unsigned long)duration * 1000UL;
  pumpWrite(true);
  lastWaterTime = millis();     // watering resets the hoursSinceWater timer
  Serial.println("[PUMP] Watering " + String(duration) + " s — relay ON");

  // Arm the fertilizer dose — loop() starts relay 2 now that the pump is running
  fertPending  = doFert;
  lastFertType = doFert ? (fertType.length() ? fertType : "fertilizer") : "";
}

void fertWrite(bool on) {
  if (RELAY_ACTIVE_LOW) digitalWrite(FERT_RELAY_PIN, on ? LOW : HIGH);
  else                  digitalWrite(FERT_RELAY_PIN, on ? HIGH : LOW);
}

void reportPumpDone() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(FIREBASE_CMD_URL);
  http.addHeader("Content-Type", "application/json");
  http.PUT("{\"requested\":false,\"status\":\"done\",\"ranSec\":" + String(lastPumpRunSec) +
          ",\"fertilized\":" + String(lastFertType.length() ? "true" : "false") + "}");
  http.end();
}


// ======================== SENSOR READING ========================

SensorData readAllSensors() {
  SensorData data;
  data.isValid = true;

  // --- DHT22: Temperature & Humidity ---
  data.temperature = dht.readTemperature();
  data.humidity = dht.readHumidity();
  
  if (isnan(data.temperature) || isnan(data.humidity)) {
    Serial.println("[WARN] DHT22 read failed — retrying...");
    delay(2000);
    data.temperature = dht.readTemperature();
    data.humidity = dht.readHumidity();
    if (isnan(data.temperature) || isnan(data.humidity)) {
      Serial.println("[ERROR] DHT22 read failed twice!");
      data.temperature = -999;
      data.humidity = -999;
      data.isValid = false;
    }
  }

  // --- BH1750: Light ---
  data.light = lightSensor.readLightLevel();
  if (data.light < 0) {
    Serial.println("[WARN] BH1750 read error");
    data.light = -999;
    data.isValid = false;
  }

  // --- Capacitive Root Moisture Sensor (pressed against Vanda aerial root mass) ---
  // Average 5 readings for stability
  long rootSum = 0;
  for (int i = 0; i < 5; i++) {
    rootSum += analogRead(ROOT_MOISTURE_PIN);
    delay(50);
  }
  data.rootMoistureRaw = rootSum / 5;

  // Normalize to 0-100% (0% = dry silvery-white roots, 100% = wet green roots)
  // High ADC = dry (low capacitance), Low ADC = wet (high capacitance)
  data.rootMoisturePct = map(data.rootMoistureRaw, ROOT_DRY_VALUE, ROOT_WET_VALUE, 0, 100);
  data.rootMoisturePct = constrain(data.rootMoisturePct, 0, 100);

  // --- Hours Since Last Watering ---
  data.hoursSinceWater = (millis() - lastWaterTime) / 3600000.0;

  return data;
}

// ======================== OUTPUT: SERIAL CSV ========================

void printCSV(SensorData data) {
  Serial.print(readingCount);
  Serial.print(",");
  Serial.print(millis());
  Serial.print(",");
  Serial.print(data.temperature, 1);
  Serial.print(",");
  Serial.print(data.humidity, 1);
  Serial.print(",");
  Serial.print(data.light, 1);
  Serial.print(",");
  Serial.print(data.rootMoistureRaw);
  Serial.print(",");
  Serial.print(data.rootMoisturePct, 1);
  Serial.print(",");
  Serial.print(data.hoursSinceWater, 2);
  Serial.println();
}

// ======================== OUTPUT: FIREBASE ========================

void sendToFirebase(SensorData data) {
  HTTPClient http;
  
  // Create JSON payload manually
  String json = "{";
  json += "\"timestamp\":" + String(millis()) + ",";
  json += "\"temperature\":" + String(data.temperature, 1) + ",";
  json += "\"humidity\":" + String(data.humidity, 1) + ",";
  json += "\"light\":" + String(data.light, 1) + ",";
  json += "\"rootMoistureRaw\":" + String(data.rootMoistureRaw) + ",";
  json += "\"rootMoisturePct\":" + String(data.rootMoisturePct, 1) + ",";
  json += "\"hoursSinceWater\":" + String(data.hoursSinceWater, 2);
  json += "}";

  // 1. Save to History Log (Use POST to add a new record)
  http.begin(FIREBASE_HISTORY_URL);
  http.addHeader("Content-Type", "application/json");
  int historyCode = http.POST(json);
  http.end();

  // 2. Update Latest State (Use PUT to overwrite)
  http.begin(FIREBASE_LATEST_URL);
  http.addHeader("Content-Type", "application/json");
  int latestCode = http.PUT(json);
  http.end();

  // 3. Mirror to the legacy flat /latest so the old dashboard keeps working
  http.begin(FIREBASE_LEGACY_LATEST_URL);
  http.addHeader("Content-Type", "application/json");
  http.PUT(json);
  http.end();

  if (latestCode > 0 && historyCode > 0) {
    Serial.println("[CLOUD] Saved to /houses/" HOUSE_ID "/zones/" ZONE_ID " (+ legacy /latest)");
  } else {
    Serial.println("[CLOUD] Failed to send to Firebase.");
  }
}

// ======================== WIFI CONNECTION ========================

void connectWiFi() {
  Serial.print("[WiFi] Connecting to " + String(WIFI_SSID));
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(" Connected!");
    Serial.println("[WiFi] IP: " + WiFi.localIP().toString());
  } else {
    Serial.println(" Failed! Continuing without WiFi.");
  }
}

// ======================== SERIAL COMMANDS ========================

void handleSerialCommands() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    
    if (cmd == "W" || cmd == "WATER") {
      // User signals they just watered the plant
      lastWaterTime = millis();
      Serial.println("[CMD] Watering recorded! Timer reset.");
    }
    else if (cmd == "R" || cmd == "READ") {
      // Force an immediate reading
      SensorData data = readAllSensors();
      Serial.println("[CMD] Manual reading:");
      Serial.println("  Temperature: " + String(data.temperature, 1) + " °C");
      Serial.println("  Humidity:    " + String(data.humidity, 1) + " %");
      Serial.println("  Light:       " + String(data.light, 1) + " lux");
      Serial.println("  Root (raw):  " + String(data.rootMoistureRaw));
      Serial.println("  Root (%):    " + String(data.rootMoisturePct, 1) + " % (0=dry/silvery, 100=wet/green)");
      Serial.println("  Hours since water: " + String(data.hoursSinceWater, 2));
    }
    else if (cmd == "P" || cmd == "PUMP") {
      // Bench test: run the pump for 5 seconds without the app
      if (ENABLE_PUMP) {
        lastPumpRunSec = 5;
        pumpUntil = millis() + 5000UL;
        pumpWrite(true);
        Serial.println("[CMD] Pump test — 5 s ON");
      } else {
        Serial.println("[CMD] Pump disabled (ENABLE_PUMP false)");
      }
    }
    else if (cmd == "F" || cmd == "FERT") {
      // Bench test: run the dosing pump for 5 seconds without the app
      // (normally the pump must be running too — but a dry bench test is fine
      //  as long as the tube isn't actually pushing concentrate into a dry hose)
      if (ENABLE_FERTILIZER) {
        lastFertType = "test";
        fertUntil = millis() + 5000UL;
        fertWrite(true);
        Serial.println("[CMD] Fertilizer dosing test — 5 s ON");
      } else {
        Serial.println("[CMD] Fertilizer dosing disabled (ENABLE_FERTILIZER false)");
      }
    }
    else if (cmd == "H" || cmd == "HELP") {
      Serial.println("[HELP] Commands:");
      Serial.println("  W or WATER  — Record that you just watered the plant");
      Serial.println("  R or READ   — Take an immediate sensor reading");
      Serial.println("  P or PUMP   — Test the pump relay for 5 seconds");
      Serial.println("  F or FERT   — Test the fertilizer dosing relay for 5 seconds");
      Serial.println("  H or HELP   — Show this help message");
    }
  }
}
