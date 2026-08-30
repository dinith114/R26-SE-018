/*
 * ============================================================
 *  Smart Orchid Care v2 â€” SECTION NODE
 *  R26-SE-018 Â· Component 3
 * ============================================================
 *  One node per SECTION (= one microclimate zone).
 *
 *  EVERY node:
 *    - reads temperature + humidity (DHT22), light (BH1750),
 *      and a reference root-moisture probe on ONE sample plant
 *    - computes VPD (drying power of the air)
 *    - pushes readings to  /farm/houses/{H}/sections/{S}/latest
 *      and appends the same reading to  /farm/history/{H}/{S}
 *    - polls  /farm/houses/{H}/sections/{S}/control  and obeys:
 *          trayCommand  -> opens the tray solenoid valve N seconds
 *          waterCommand -> (master node only) runs the pump N seconds
 *
 *  The MASTER node (IS_MASTER = true, normally S1) additionally drives the
 *  house water pump and the fertilizer dosing pump. Fertilizer is ONLY ever
 *  delivered while water is already flowing â€” never onto dry roots.
 *
 *  POWER: this farm has Wi-Fi but NO MAINS. Set POWER_MODE below.
 *
 *  WIRING (see WIRING_SIMPLE.html / DEVICE_ASSEMBLY_FULL_3D.html)
 *    DHT22   DATA -> GPIO4   (10k pull-up to 3V3)
 *    BH1750  SDA  -> GPIO21   SCL -> GPIO22
 *    Probe   AOUT -> GPIO34   (input-only ADC)
 *    Tray valve relay IN  -> GPIO26
 *    Pump relay IN        -> GPIO27   (master only)
 *    Fertilizer relay IN  -> GPIO25   (master only)
 *    All sensor VCC -> 3V3 rail, all GND -> GND rail
 *
 *  LIBRARIES: DHT sensor library (Adafruit), Adafruit Unified Sensor,
 *             BH1750 (Christopher Laws), ArduinoJson (Benoit Blanchon)
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <BH1750.h>
#include <ArduinoJson.h>
#include <time.h>

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• 1. SET THESE PER DEVICE â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#define HOUSE_ID   "H1"
#define SECTION_ID "S1"          // S1 / S2 / S3 / S4  â€” must match the app
#define IS_MASTER  true          // true ONLY on the node wired to the pump

const char* WIFI_SSID     = "Pixel_8047";
const char* WIFI_PASSWORD = "24681012";

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• 2. POWER MODE â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
//  ALWAYS_ON  : stays awake, reacts to app commands within POLL_MS.
//               Use for the demo and for the master node. ~2 days per charge.
//  DEEP_SLEEP : sleeps between readings, ~50 days per charge, but a manual
//               command waits until the next wake (up to READ_INTERVAL_MS).
#define POWER_ALWAYS_ON  0
#define POWER_DEEP_SLEEP 1
#define POWER_MODE  POWER_ALWAYS_ON

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• 3. TIMING â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#define READ_INTERVAL_MS  300000UL   // 5 min â€” matches the ML trend window
#define POLL_MS           10000UL    // command poll (ALWAYS_ON only)
#define PUMP_MAX_SEC      300
#define VALVE_MAX_SEC     120
#define FERT_MAX_SEC      30

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• 4. PINS â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#define DHT_PIN     4
#define DHT_TYPE    DHT22
#define PROBE_PIN   34
#define TRAY_PIN    26
#define PUMP_PIN    27
#define FERT_PIN    25
#define RELAY_ACTIVE_LOW true      // most modules switch ON when IN is LOW

// Probe calibration â€” measure YOUR probe (serial command 'C')
#define PROBE_DRY   4095
#define PROBE_WET   1500

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• 5. FIREBASE â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#define FB_HOST "https://orchid-smart-care-default-rtdb.firebaseio.com"
const String BASE    = String(FB_HOST) + "/farm/houses/" HOUSE_ID "/sections/" SECTION_ID;
const String CTRL    = BASE + "/control";
// History is stored OUTSIDE the section node on purpose. When it lived at
// BASE + "/history", every app poll of /farm/houses.json dragged the whole
// archive down with it - about 1 MB after a few days, against 8 KB of actual
// state - which made the dashboard take seconds to load. Keeping the archive on
// its own branch lets the app fetch live state alone.
const String HIST    = String(FB_HOST) + "/farm/history/" HOUSE_ID "/" SECTION_ID;

DHT dht(DHT_PIN, DHT_TYPE);
BH1750 lightMeter;

bool     bhOK = false;
uint32_t lastRead = 0, lastPoll = 0;
uint32_t readingCount = 0;

// non-blocking actuator timers (0 = idle)
uint32_t trayUntil = 0, pumpUntil = 0, fertUntil = 0;

struct Reading {
  float temperature, humidity, light, vpd;
  int   probeRaw;
  float sampleMoisture;
  bool  tempOK, lightOK;
};

/* Dose length for the fertilizer pump.
   Must START and FINISH inside the watering window so the nutrient is always
   carried onto wet roots â€” dosing onto dry roots burns them. Returns 0 if the
   watering run is too short to dose safely. */
int fertSeconds(int waterSecs) {
  if (waterSecs < 6) return 0;                 // too short to be safe
  int f = waterSecs / 4;                       // ~25% of the run
  int cap = waterSecs - 3;                     // must end before the water stops
  if (f > cap) f = cap;
  if (f > FERT_MAX_SEC) f = FERT_MAX_SEC;
  return f < 3 ? 3 : f;
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• SETUP â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println(F("\n==============================================="));
  Serial.println(F("  Smart Orchid Care v2 - Section Node"));
  Serial.printf ("  Device: %s-%s   %s\n", HOUSE_ID, SECTION_ID,
                 IS_MASTER ? "[MASTER: pump + fertilizer]" : "[sensors + tray]");
  Serial.println(F("==============================================="));

  // relays OFF first, before anything can float them on
  pinMode(TRAY_PIN, OUTPUT); relayWrite(TRAY_PIN, false);
  if (IS_MASTER) {
    pinMode(PUMP_PIN, OUTPUT); relayWrite(PUMP_PIN, false);
    pinMode(FERT_PIN, OUTPUT); relayWrite(FERT_PIN, false);
  }
  Serial.println(F("[OK] Relays initialised OFF"));

  dht.begin();
  Serial.printf("[OK] DHT22 on GPIO%d\n", DHT_PIN);

  initBH1750();

  pinMode(PROBE_PIN, INPUT);
  Serial.printf("[OK] Moisture probe on GPIO%d (reference only)\n", PROBE_PIN);

  connectWiFi();
  syncTime();

  Serial.println(F("\nCommands: R=read  T=tray 5s  P=pump 5s  F=fert 3s  C=calibrate  H=help\n"));
  lastRead = millis() - READ_INTERVAL_MS;   // take a reading immediately
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• LOOP â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void loop() {
  serviceActuators();          // always first â€” safety
  handleSerial();

  uint32_t now = millis();

  if (now - lastRead >= READ_INTERVAL_MS) {
    lastRead = now;
    Reading r = readSensors();
    printReading(r);
    if (WiFi.status() == WL_CONNECTED) pushReading(r);
    else { Serial.println(F("[WiFi] offline - reconnecting")); connectWiFi(); }

#if POWER_MODE == POWER_DEEP_SLEEP
    if (idle()) {
      pollCommands();                       // last chance before sleeping
      if (idle()) deepSleep();
    }
#endif
  }

#if POWER_MODE == POWER_ALWAYS_ON
  if (now - lastPoll >= POLL_MS) {
    lastPoll = now;
    if (WiFi.status() == WL_CONNECTED) pollCommands();
  }
#endif

  delay(50);
}

bool idle() { return trayUntil == 0 && pumpUntil == 0 && fertUntil == 0; }

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• SENSORS â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void initBH1750() {
  const uint8_t addrs[2] = {0x23, 0x5C};
  const uint8_t pins[2][2] = {{21, 22}, {22, 21}};   // also try swapped wires
  for (int p = 0; p < 2 && !bhOK; p++) {
    for (int a = 0; a < 2 && !bhOK; a++) {
      Wire.begin(pins[p][0], pins[p][1]);
      delay(120);
      if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, addrs[a], &Wire)) {
        bhOK = true;
        Serial.printf("[OK] BH1750 SDA=%d SCL=%d addr=0x%02X%s\n",
                      pins[p][0], pins[p][1], addrs[a],
                      p == 1 ? "  <-- your SDA/SCL are swapped" : "");
      }
    }
  }
  if (!bhOK) Serial.println(F("[ERROR] BH1750 not found - check wiring"));
}

float computeVPD(float t, float rh) {
  float svp = 0.6108 * exp((17.27 * t) / (t + 237.3));
  return svp * (1.0 - rh / 100.0);
}

Reading readSensors() {
  Reading r;

  r.temperature = dht.readTemperature();
  r.humidity    = dht.readHumidity();
  if (isnan(r.temperature) || isnan(r.humidity)) {
    delay(2200);                                   // DHT22 needs 2s between reads
    r.temperature = dht.readTemperature();
    r.humidity    = dht.readHumidity();
  }
  r.tempOK = !(isnan(r.temperature) || isnan(r.humidity));
  if (!r.tempOK) { r.temperature = -999; r.humidity = -999; }

  r.light   = bhOK ? lightMeter.readLightLevel() : -999;
  r.lightOK = (r.light >= 0);
  if (!r.lightOK) r.light = -999;

  long sum = 0;
  for (int i = 0; i < 5; i++) { sum += analogRead(PROBE_PIN); delay(20); }
  r.probeRaw = sum / 5;
  float pct = map(r.probeRaw, PROBE_DRY, PROBE_WET, 0, 100);
  r.sampleMoisture = constrain(pct, 0, 100);

  // VPD only means anything when temp AND humidity are valid
  r.vpd = r.tempOK ? computeVPD(r.temperature, r.humidity) : -999;

  readingCount++;
  return r;
}

void printReading(Reading r) {
  Serial.printf("#%lu  T=%.1fC  RH=%.1f%%  L=%.0flx  VPD=%.3f  probe=%d (%.1f%%)%s\n",
                readingCount, r.temperature, r.humidity, r.light, r.vpd,
                r.probeRaw, r.sampleMoisture,
                (!r.tempOK || !r.lightOK) ? "   <-- SENSOR FAULT" : "");
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• FIREBASE â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// The backend does all time reasoning (e.g. the tray cooldown) using the
// timestamp WE send, so it must be a real epoch â€” hence syncTime() via NTP.
void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print(F("[TIME] syncing"));
  for (int i = 0; i < 20 && time(nullptr) < 100000; i++) { delay(500); Serial.print('.'); }
  time_t t = time(nullptr);
  if (t > 100000) Serial.printf(" ok (epoch %ld)\n", (long)t);
  else            Serial.println(F(" FAILED - timestamps will be wrong"));
}

uint64_t epochMillis() {
  time_t t = time(nullptr);
  return (t > 100000) ? (uint64_t)t * 1000ULL : (uint64_t)millis();
}

String readingJson(Reading r) {
  JsonDocument d;   // ArduinoJson v7: sizes itself
  d["temperature"]    = r.temperature;
  d["humidity"]       = r.humidity;
  d["light"]          = r.light;
  d["vpd"]            = r.vpd;
  d["sampleMoisture"] = r.sampleMoisture;
  d["probeRaw"]       = r.probeRaw;
  d["timestamp"]      = epochMillis();
  d["deviceId"]       = HOUSE_ID "-" SECTION_ID;
  d["sensorFault"]    = (!r.tempOK || !r.lightOK);
  String out; serializeJson(d, out); return out;
}

void pushReading(Reading r) {
  String body = readingJson(r);
  HTTPClient http;
  http.setTimeout(8000);

  http.begin(BASE + "/latest.json");
  http.addHeader("Content-Type", "application/json");
  int c1 = http.PUT(body);
  http.end();

  http.begin(HIST + ".json");
  http.addHeader("Content-Type", "application/json");
  int c2 = http.POST(body);
  http.end();

  Serial.printf("[CLOUD] latest=%d history=%d\n", c1, c2);
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• COMMANDS â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
// Polls the control node the app/backend writes to. Acknowledges BEFORE acting
// so a command can never run twice if we reboot mid-operation.
void pollCommands() {
  HTTPClient http;
  http.setTimeout(8000);
  http.begin(CTRL + ".json");
  int code = http.GET();
  if (code != 200) { http.end(); return; }
  String payload = http.getString();
  http.end();
  if (payload.length() < 5 || payload == "null") return;

  JsonDocument d;
  if (deserializeJson(d, payload)) return;

  // ---- tray valve (every node) ----
  JsonObject tc = d["trayCommand"];
  if (!tc.isNull() && tc["requested"] == true) {
    int secs = constrain((int)(tc["fillSeconds"] | 15), 1, VALVE_MAX_SEC);
    ackCommand("trayCommand", "running", secs);
    trayUntil = millis() + (uint32_t)secs * 1000UL;
    relayWrite(TRAY_PIN, true);
    Serial.printf("[TRAY] valve OPEN %ds (by %s)\n", secs,
                  (const char*)(tc["triggeredBy"] | "?"));
  }

  if (!IS_MASTER) return;

  // ---- water pump + fertilizer (master only) ----
  JsonObject wc = d["waterCommand"];
  if (!wc.isNull() && wc["requested"] == true) {
    int secs = constrain((int)(wc["durationSec"] | 45), 1, PUMP_MAX_SEC);
    bool withFert = wc["withFertilizer"] | false;
    ackCommand("waterCommand", "running", secs);

    pumpUntil = millis() + (uint32_t)secs * 1000UL;
    relayWrite(PUMP_PIN, true);
    Serial.printf("[PUMP] ON %ds (by %s)\n", secs,
                  (const char*)(wc["triggeredBy"] | "?"));

    if (withFert) {
      int f = fertSeconds(secs);
      if (f > 0) {
        fertUntil = millis() + (uint32_t)f * 1000UL;
        relayWrite(FERT_PIN, true);
        Serial.printf("[FERT] dosing %ds into the water stream\n", f);
      } else {
        Serial.println(F("[FERT] watering too short to dose safely - skipped"));
      }
    }
  }
}

void ackCommand(const char* key, const char* status, int val) {
  JsonDocument d;
  d["requested"] = false;
  d["status"]    = status;
  d["ranSec"]    = val;
  d["deviceTs"]  = epochMillis();
  String body; serializeJson(d, body);
  HTTPClient http;
  http.setTimeout(6000);
  http.begin(CTRL + "/" + key + ".json");
  http.addHeader("Content-Type", "application/json");
  http.PUT(body);
  http.end();
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• ACTUATORS â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void relayWrite(int pin, bool on) {
  digitalWrite(pin, RELAY_ACTIVE_LOW ? (on ? LOW : HIGH) : (on ? HIGH : LOW));
}

void serviceActuators() {
  uint32_t now = millis();
  if (trayUntil && now >= trayUntil) {
    relayWrite(TRAY_PIN, false); trayUntil = 0;
    Serial.println(F("[TRAY] valve CLOSED"));
  }
  if (IS_MASTER) {
    if (fertUntil && now >= fertUntil) {
      relayWrite(FERT_PIN, false); fertUntil = 0;
      Serial.println(F("[FERT] dosing done"));
    }
    if (pumpUntil && now >= pumpUntil) {
      relayWrite(PUMP_PIN, false); pumpUntil = 0;
      relayWrite(FERT_PIN, false); fertUntil = 0;   // never leave fert on alone
      Serial.println(F("[PUMP] OFF"));
    }
  }
}

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• WIFI / SLEEP â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void connectWiFi() {
  Serial.printf("[WiFi] connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print('.'); }
  if (WiFi.status() == WL_CONNECTED)
    Serial.println(" connected, IP " + WiFi.localIP().toString());
  else
    Serial.println(F(" FAILED (will retry next cycle)"));
}

#if POWER_MODE == POWER_DEEP_SLEEP
void deepSleep() {
  Serial.printf("[SLEEP] %lu s\n", READ_INTERVAL_MS / 1000);
  Serial.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)READ_INTERVAL_MS * 1000ULL);
  esp_deep_sleep_start();
}
#endif

// â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• SERIAL TOOLS â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
void handleSerial() {
  if (!Serial.available()) return;
  String c = Serial.readStringUntil('\n'); c.trim(); c.toUpperCase();

  if (c == "R") { Reading r = readSensors(); printReading(r); }
  else if (c == "T") { trayUntil = millis() + 5000; relayWrite(TRAY_PIN, true);
                       Serial.println(F("[TEST] tray valve 5s")); }
  else if (c == "P") { if (IS_MASTER) { pumpUntil = millis() + 5000; relayWrite(PUMP_PIN, true);
                       Serial.println(F("[TEST] pump 5s")); } else Serial.println(F("not master")); }
  else if (c == "F") { if (IS_MASTER) { fertUntil = millis() + 3000; relayWrite(FERT_PIN, true);
                       Serial.println(F("[TEST] fertilizer 3s")); } else Serial.println(F("not master")); }
  else if (c == "C") calibrate();
  else if (c == "H") {
    Serial.println(F("R=read  T=tray 5s  P=pump 5s  F=fert 3s  C=calibrate  H=help"));
  }
}

void calibrate() {
  Serial.println(F("\n--- PROBE CALIBRATION ---"));
  Serial.println(F("Hold the probe in DRY AIR, then press Enter"));
  while (!Serial.available()) delay(100);
  Serial.readStringUntil('\n');
  long dry = 0; for (int i = 0; i < 20; i++) { dry += analogRead(PROBE_PIN); delay(50); }
  dry /= 20;
  Serial.printf("  dry  = %ld\n", dry);

  Serial.println(F("Press it on WET ROOTS, then press Enter"));
  while (!Serial.available()) delay(100);
  Serial.readStringUntil('\n');
  long wet = 0; for (int i = 0; i < 20; i++) { wet += analogRead(PROBE_PIN); delay(50); }
  wet /= 20;
  Serial.printf("  wet  = %ld\n", wet);
  Serial.printf("\nPut these in the sketch:\n  #define PROBE_DRY %ld\n  #define PROBE_WET %ld\n\n", dry, wet);
}
