/*
 * ============================================================
 *  SENSOR-ONLY NODE  —  validate the shade-house assumption
 *  R26-SE-018 · Component 3
 * ============================================================
 *  WHY THIS SKETCH EXISTS
 *  ----------------------
 *  Every model in this project rests on ONE unmeasured assumption: that inside
 *  a shade house it is +3.5 C warmer at full sun, +7% more humid, and 45% as
 *  bright as the open air. Those numbers were modelled, never measured.
 *
 *  This sketch measures them. It needs only the parts already on the desk -
 *  ESP32, DHT22 and BH1750 - with no relays, valve, pump or fertiliser dosing.
 *  Leave it running inside the house for a day, then run:
 *
 *      python ml_pipeline/validate_shadehouse_assumption.py H1 S1
 *
 *  It writes to EXACTLY the same Firebase paths as the full section node, so
 *  the app, the backend and the models all see it as a real device. When the
 *  relays arrive, switch to section_node_v2.ino and nothing downstream changes.
 *
 *  WIRING  (ESP32 DevKit V1, 30-pin)
 *  ---------------------------------
 *    DHT22 module        ESP32
 *      DAT      ------->  D4      (GPIO4)
 *      VCC      ------->  3V3
 *      GND      ------->  GND
 *      (the red breakout has its own pull-up resistor - none needed)
 *
 *    Soil probe          ESP32     (capacitive v1.2)
 *      AOUT     ------->  D34     (GPIO34 - ADC1, input-only)
 *      VCC      ------->  3V3     <-- 3V3, NOT VIN. Powered at 5 V this probe
 *      GND      ------->  GND         puts >3.3 V on AOUT and damages the ADC.
 *
 *    BH1750 module       ESP32
 *      VCC      ------->  3V3
 *      GND      ------->  GND
 *      SDA      ------->  D21     (GPIO21)
 *      SCL      ------->  D22     (GPIO22)
 *      ADD      ------->  leave unconnected (selects address 0x23)
 *
 *  LIBRARIES (Arduino IDE -> Library Manager)
 *    "DHT sensor library" by Adafruit
 *    "Adafruit Unified Sensor"
 *    "BH1750" by Christopher Laws
 *    "ArduinoJson" by Benoit Blanchon
 *
 *  BOARD: Tools -> Board -> esp32 -> "ESP32 Dev Module"
 *         Tools -> Port  -> the COM port that appears when you plug it in
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <Wire.h>
#include <BH1750.h>
#include <ArduinoJson.h>
#include <time.h>

// ═══════════ 1. SET THESE ═══════════
#define TENANT_ID  "t_REPLACE_ME"   // the farm this board belongs to
#define HOUSE_ID   "H1"
#define SECTION_ID "S1"          // must match a section that exists in the app

const char* WIFI_SSID     = "SLT-4G-2.4_1C6F07";
const char* WIFI_PASSWORD = "EF4282A7";

// ═══════════ 2. PINS ═══════════
#define DHT_PIN   4
#define DHT_TYPE  DHT22
#define I2C_SDA   21
#define I2C_SCL   22
// How often to re-probe a light meter that was absent at boot. Five minutes is
// short enough that a farmer who reconnects a wire sees it return while still
// standing there, and long enough to cost a healthy node nothing.
#define LIGHT_RETRY_MS 300000UL
#define SOIL_PIN  34          // GPIO34: ADC1, input-only, safe for an analogue sensor

/* Relay outputs.
   The 4-channel SONGLE module is opto-isolated and ACTIVE LOW: pulling an IN
   pin to ground energises that channel. Writing HIGH releases it. That is the
   opposite of what most people expect, so the two constants below exist to keep
   the rest of the code readable and to make the polarity a single-line change if
   this board turns out to be active high. */
#define RELAY_ON    LOW
#define RELAY_OFF   HIGH

/* ---- PLUMBING: how water actually gets to the plant ------------------------
   Two arrangements, chosen here at compile time. Change PLUMBING, reflash, and
   nothing else in the sketch or the backend needs to know.

   PLUMBING_TWO_PUMPS  (default - what the bench is wired for)
       One pump per relay channel. Nothing to sequence, nothing can deadhead,
       and a failure in one loop leaves the other running. Both pumps sit on the
       SAME supply - they are two loads on one rail, not two power supplies.
           IN1/D25 -> watering pump
           IN2/D26 -> humidity tray pump

   PLUMBING_VALVES
       One pump feeding a T manifold, with a normally-closed solenoid valve on
       each branch. This is the arrangement that scales - four sections would
       otherwise want eight pumps - but it introduces a way to destroy the pump,
       so the sequencing in runPath() is not optional.
           IN1/D25 -> pump
           IN2/D26 -> valve A, mister line
           IN3/D27 -> valve B, tray line
       D27 is free, has no strapping function and is safe as an output. It is an
       ADC2 pin, which only matters for analogRead under WiFi - not for us. */
#define PLUMBING_TWO_PUMPS 1
#define PLUMBING_VALVES    2

#ifndef PLUMBING
#define PLUMBING PLUMBING_TWO_PUMPS
#endif

#if PLUMBING == PLUMBING_VALVES
  #define RELAY_PUMP  25      // IN1 - the single pump
  #define VALVE_MIST  26      // IN2 - normally-closed, mister line
  #define VALVE_TRAY  27      // IN3 - normally-closed, tray line
  /* The valve must have physically moved before there is pressure behind it,
     and the pressure must be gone before it shuts. Generous on purpose: these
     are milliseconds against a pour measured in seconds. */
  const uint16_t VALVE_SETTLE_MS = 250;   // valve open -> pump start
  const uint16_t VALVE_BLEED_MS  = 400;   // pump stop  -> valve close
#else
  #define RELAY_WATER 25      // IN1 - watering pump
  #define RELAY_TRAY  26      // IN2 - humidity tray pump
#endif

/* Order matters here. An ESP32 GPIO floats during boot, and on an active-low
   board a floating input reads as ON, which would run a pump every time the node
   resets. Driving the pin to the OFF level BEFORE switching it to an output
   means the very first electrical state the relay ever sees is "off". */
#if PLUMBING == PLUMBING_VALVES
static const int   RELAY_PINS[]  = { RELAY_PUMP, VALVE_MIST, VALVE_TRAY };
static const char* RELAY_NAMES[] = { "PUMP (IN1/D25)", "VALVE mist (IN2/D26)",
                                     "VALVE tray (IN3/D27)" };
#else
static const int   RELAY_PINS[]  = { RELAY_WATER, RELAY_TRAY };
static const char* RELAY_NAMES[] = { "WATER (IN1/D25)", "TRAY (IN2/D26)" };
#endif
static const int RELAY_COUNT = sizeof(RELAY_PINS) / sizeof(RELAY_PINS[0]);

/* How often the board asks whether the farmer has pressed anything.

   This used to be once per READING, because loop() ended in
   delay(readIntervalMs) and pollCommand() sat inside that same cycle. On the
   5-minute production interval that meant Water Now took up to five minutes to
   reach the pump - and the app gives up waiting after 60 s, so every manual
   command also reported "the node has not confirmed yet" before running
   minutes later. Changing the read interval, and Identify, were just as slow.

   Reading the sensors and listening for orders are different jobs at different
   rates. /command.json is a ~150 byte document, so 2 s costs roughly 17 MB of
   egress a day per node against a 360 MB budget - affordable, and the reason
   this is a constant rather than tied to readIntervalMs.

   A Firebase event-stream (Accept: text/event-stream) would be instant and
   nearly free, and is the right long-term answer; it needs reconnect handling
   this sketch does not have yet. */
const uint32_t COMMAND_POLL_MS = 2000UL;

/* How often the board checks its own device record for things the app has asked
   for: Identify, and a Wi-Fi scan.

   These used to be handled only inside takeReading(), so on the 5-minute
   production interval pressing Identify took over three minutes to blink a LED
   that is meant to answer "which of these four boxes is it?". Same mistake as
   the command poll: a human-initiated action was tied to the sensor clock.

   Slower than COMMAND_POLL_MS because nothing here moves water. The record is
   ~250 bytes, so 5 s is roughly 8 MB of egress a day per node. */
const uint32_t DEVICE_POLL_MS = 5000UL;

/* How often the node says "I am here", independent of any reading.

   Before this existed the only proof a node was alive was a posted reading, so
   the backend could not call a node offline until it had missed two of them -
   ten minutes at a 5-minute interval. The node was in fact talking to Firebase
   every 2 seconds the whole time to poll for commands; it simply never said so.
   At 30 s the backend can decide after three missed beats instead. */
const uint32_t HEARTBEAT_MS = 30000UL;

// While a pour is running: checked so a second command cannot start one on top
// of it, and so a stop can be recognised as belonging to this run.
bool     pouring     = false;
String   pouringId   = "";
bool     lastRunStopped = false;   // did the last pour end early, by request


/* Defined further down, next to pollCommand(), because they need BASE and the
   JSON helpers. Declared here so the relay code above can call them. */
bool stopRequested(const String& runningId);
bool sleepWatchingForStop(uint32_t totalMs, const String& runningId);

void setupRelays() {
  for (int i = 0; i < RELAY_COUNT; i++) {
    digitalWrite(RELAY_PINS[i], RELAY_OFF);
    pinMode(RELAY_PINS[i], OUTPUT);
    digitalWrite(RELAY_PINS[i], RELAY_OFF);
  }
  Serial.printf("[RELAY] %d channels off\n", RELAY_COUNT);
}

/* Runs one relay for a bounded time.
   The cap is a safety net, not a preference: a command that arrives corrupted,
   or a backend bug asking for 9999 seconds, must not empty a tank over a plant.
   Anything longer than the cap is clamped and the clamp is reported. */
const uint32_t RELAY_MAX_SEC = 120;

void runRelay(int pin, uint32_t seconds, const char* what, const String& cmdId) {
  if (seconds == 0) return;
  if (seconds > RELAY_MAX_SEC) {
    Serial.printf("[RELAY] %s asked for %us, clamped to %us\n", what, seconds, RELAY_MAX_SEC);
    seconds = RELAY_MAX_SEC;
  }
  Serial.printf("[RELAY] %s ON for %us\n", what, seconds);
  digitalWrite(pin, RELAY_ON);
  bool full = sleepWatchingForStop(seconds * 1000UL, cmdId);
  digitalWrite(pin, RELAY_OFF);
  lastRunStopped = !full;
  Serial.printf("[RELAY] %s OFF (%s)\n", what,
                full ? "ran full time" : "STOPPED early");
}

#if PLUMBING == PLUMBING_VALVES
/* Open the valve, THEN start the pump. Stop the pump, THEN close the valve.

   A diaphragm pump running against a closed valve is deadheaded: it has nowhere
   to push, so it heats and eventually fails. The pump is therefore the LAST
   thing switched on and the FIRST thing switched off, every time, with a settle
   gap either side. If you edit this function, keep that order - it is the whole
   reason the single-pump arrangement needs code at all. */
void runPath(int valvePin, uint32_t seconds, const char* what, const String& cmdId) {
  if (seconds == 0) return;
  if (seconds > RELAY_MAX_SEC) {
    Serial.printf("[FLOW] %s asked for %us, clamped to %us\n", what, seconds, RELAY_MAX_SEC);
    seconds = RELAY_MAX_SEC;
  }
  Serial.printf("[FLOW] %s: valve open\n", what);
  digitalWrite(valvePin, RELAY_ON);
  delay(VALVE_SETTLE_MS);

  Serial.printf("[FLOW] %s: pump ON for %us\n", what, seconds);
  digitalWrite(RELAY_PUMP, RELAY_ON);
  bool full = sleepWatchingForStop(seconds * 1000UL, cmdId);
  lastRunStopped = !full;

  digitalWrite(RELAY_PUMP, RELAY_OFF);        // pump off FIRST, always
  Serial.printf("[FLOW] %s: pump OFF\n", what);
  delay(VALVE_BLEED_MS);
  digitalWrite(valvePin, RELAY_OFF);
  Serial.printf("[FLOW] %s: valve closed\n", what);
}
#endif

/* The one place the rest of the sketch asks for water. Both plumbing modes
   answer the same two actions, so pollCommand() does not change. */
void deliver(const String& action, uint32_t seconds, const String& cmdId) {
  pouring   = true;
  pouringId = cmdId;
#if PLUMBING == PLUMBING_VALVES
  if (action == "water")     runPath(VALVE_MIST, seconds, "WATER", cmdId);
  else if (action == "tray") runPath(VALVE_TRAY, seconds, "TRAY",  cmdId);
#else
  if (action == "water")     runRelay(RELAY_WATER, seconds, "WATER", cmdId);
  else if (action == "tray") runRelay(RELAY_TRAY,  seconds, "TRAY",  cmdId);
#endif
  pouring   = false;
  pouringId = "";
}

/* Clicks each channel once so the wiring can be confirmed by ear before any
   water is involved. Deliberately short: the pumps may be dry at this point. */
void relaySelfTest() {
  Serial.printf("[RELAY] self test - listen for two clicks per channel (%d channels)\n",
                RELAY_COUNT);
  for (int i = 0; i < RELAY_COUNT; i++) {
    Serial.printf("   %s on\n", RELAY_NAMES[i]);
    digitalWrite(RELAY_PINS[i], RELAY_ON);
    delay(700);
    Serial.printf("   %s off\n", RELAY_NAMES[i]);
    digitalWrite(RELAY_PINS[i], RELAY_OFF);
    delay(700);
  }
  Serial.println("[RELAY] self test done");
}

// ═══════════ 3. TIMING ═══════════
// 5 minutes matches the production node. Use 30000 while you are watching the
// serial monitor, then put it back before leaving it in the house.
#define READ_INTERVAL_MS 15000UL

/* The interval the board is ACTUALLY using, settable from the app.

   A demo wants fast updates and a real house wants a slow, battery-friendly
   one, and reflashing a board on a roof to change a number is not a workflow.
   The app writes /devices/{mac}/readIntervalMs and this picks it up on the next
   cycle, inside the assignment fetch that already happens - no extra request.

   Bounds are enforced here as well as in the backend, because this is the side
   that pays for a mistake: a 1-second interval would hammer Firebase from a
   board nobody is watching, and anything longer than an hour is
   indistinguishable from a dead node. */
const uint32_t READ_INTERVAL_MIN_MS =    5000UL;   //  5 s
const uint32_t READ_INTERVAL_MAX_MS = 3600000UL;   //  1 hour
uint32_t readIntervalMs = READ_INTERVAL_MS;


// ═══════════ 4. CLOUD ═══════════
const char* FB_HOST = "https://orchid-smart-care-default-rtdb.firebaseio.com";

// Live state the app reads, and the archive the models learn from. History is
// deliberately on its own branch: when it lived under the section, every app
// poll dragged the whole archive down with it (1 MB against 8 KB of state).
/* These were compile-time constants, which meant one build per node and a
   laptop to move a node between zones. They are now rebuilt from whatever
   section the farmer has assigned this board to in the app.

   HOUSE_ID/SECTION_ID above survive as the fallback for an unassigned board, so
   a node that has never been claimed still reports somewhere sensible instead of
   going silent. */

/* Every farm path this board writes hangs off ONE base, the firmware's version
   of the chokepoint the backend uses. Built once here so a path cannot be
   assembled from FB_HOST by hand and quietly miss the tenant - which is exactly
   how a board would end up writing to the old shared tree with nothing to show
   for it but readings nobody reads.

   /devices/... deliberately does NOT hang off this. That registry is global: a
   board belongs to no tenant until it is flashed with one, and the app's
   Link-a-node list has to see boards before they are anybody's. */
// KEEP THIS IN THE MAIN SKETCH. Arduino concatenates the .ino files into one
// translation unit with the main sketch first and the other tabs after it, in
// alphabetical order - which is the only reason master_queue.ino can see FARM
// at all. Moved into a tab that sorts after it, this stops compiling.
const String FARM = String(FB_HOST) + "/tenants/" TENANT_ID "/farm";

String BASE = FARM + "/houses/" HOUSE_ID "/sections/" SECTION_ID;
String HIST = FARM + "/history/" HOUSE_ID "/" SECTION_ID;

String assignedHouse   = HOUSE_ID;
String assignedSection = SECTION_ID;
bool   isClaimed       = false;      // false = no farmer has assigned this board

static void rebuildPaths() {
  BASE = FARM + "/houses/" + assignedHouse + "/sections/" + assignedSection;
  HIST = FARM + "/history/" + assignedHouse + "/" + assignedSection;
}

DHT dht(DHT_PIN, DHT_TYPE);
BH1750 lightMeter;
bool lightOK = false;

// -999 is the project-wide "sensor faulty" flag. The backend maps it to a safe
// training-range default rather than feeding garbage to a model.
const float SENTINEL = -999.0;


/* Brownout mitigation.
   The radio is by far the biggest load on this board: switching it on pulls a
   surge of a few hundred mA, and a USB port or cable that cannot deliver that
   fast enough drags 3V3 below 2.43V, which trips the brownout detector and
   resets the chip. That showed up as "BOD: Brownout detector was triggered"
   printed exactly at the [WIFI] joining line, with 3V3 measured sagging from
   3.3V to 2.7V under load.

   These three settings cut the demand rather than masking the symptom. The
   brownout detector itself is deliberately left enabled: disabling it does not
   add any power, it only hides the warning and lets the chip run unstably. */
void reduceCurrentDraw() {
  // 80MHz is plenty for reading three sensors and posting JSON, and it frees
  // roughly 30mA of headroom for the radio surge.
  setCpuFrequencyMhz(80);
  Serial.printf("[PWR] cpu clock %u MHz\n", getCpuFrequencyMhz());
}

/* ─────────────── WiFi provisioning over a temporary hotspot ───────────────
   A node shipped to a farm cannot have its network compiled in: the farmer has
   no laptop, and four boards would need four builds. So credentials live in
   flash (NVS), and a node with none raises its own WiFi network and serves a
   page where they can be entered from a phone.

   The compiled-in WIFI_SSID/WIFI_PASSWORD are kept as a FALLBACK rather than
   deleted. A board that has never been provisioned still joins the development
   network, so this change cannot strand the node currently on the bench.

   Deliberately not using an external captive-portal library: WebServer, DNSServer
   and Preferences all ship with the core, and one less dependency is one less
   thing to break at 2am before a demo. */
#include <Preferences.h>
#include <WebServer.h>
#include <DNSServer.h>

Preferences prefs;
WebServer  portalServer(80);
DNSServer  dnsServer;
bool  portalRunning = false;
String provSsid, provPass;

static String apName() {
  // Last two bytes of the MAC make each node distinguishable on a bench where
  // four identical boxes are advertising at once.
  uint8_t m[6];
  WiFi.macAddress(m);
  char buf[24];
  snprintf(buf, sizeof(buf), "OrchidNode-%02X%02X", m[4], m[5]);
  return String(buf);
}

/* Changing WiFi remotely is the one operation that can permanently strand a
   node: send one wrong character and it can never reach the network again, and
   nobody can send a correction because there is no path back.

   So a change is treated as PROVISIONAL. The working credentials are kept as a
   backup, the new ones are marked "on trial", and if they fail to connect the
   node rolls back to the pair that last worked. The farmer sees a failed change
   instead of a dead node.

   Confirmation happens on the first successful join, at which point the trial
   flag is cleared and the new pair becomes the backup for next time. */
static void saveCredsProvisional(const String& ssid, const String& pass) {
  prefs.begin("orchid", false);
  prefs.putString("bk_ssid", prefs.getString("ssid", WIFI_SSID));   // keep what works
  prefs.putString("bk_pass", prefs.getString("pass", WIFI_PASSWORD));
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putBool("trial", true);
  prefs.end();
  Serial.printf("[PROV] '%s' saved on trial, previous network kept as backup\n", ssid.c_str());
}

static void confirmCreds() {
  prefs.begin("orchid", false);
  if (prefs.getBool("trial", false)) {
    prefs.putBool("trial", false);
    Serial.println("[PROV] new network confirmed working");
  }
  prefs.end();
}

/* Called after repeated failures. Returns true if a rollback happened, in which
   case the caller restarts so the restored credentials are used from a clean
   boot rather than mid-retry. */
static bool rollbackCreds() {
  prefs.begin("orchid", false);
  bool onTrial = prefs.getBool("trial", false);
  String bs = prefs.getString("bk_ssid", "");
  if (onTrial && bs != "") {
    prefs.putString("ssid", bs);
    prefs.putString("pass", prefs.getString("bk_pass", ""));
    prefs.putBool("trial", false);
    prefs.end();
    Serial.printf("[PROV] new network failed - rolled back to '%s'\n", bs.c_str());
    return true;
  }
  prefs.end();
  return false;
}

/* Physical escape hatch. Holding BOOT at power-on forces the setup portal even
   when the stored network works. This is the only route in when a node is
   unreachable - no cloud command can help a board that cannot reach the cloud. */
static bool bootButtonHeld() {
  pinMode(0, INPUT_PULLUP);       // GPIO0 is the BOOT button, LOW when pressed
  delay(50);
  if (digitalRead(0) != LOW) return false;
  Serial.println("[PROV] BOOT held - keep holding for 3s to force setup mode");
  for (int i = 0; i < 30; i++) {
    delay(100);
    if (digitalRead(0) != LOW) { Serial.println("[PROV] released, normal start"); return false; }
  }
  Serial.println("[PROV] forced into setup mode");
  return true;
}

static void loadCreds() {
  prefs.begin("orchid", true);              // read-only
  provSsid = prefs.getString("ssid", "");
  provPass = prefs.getString("pass", "");
  bool onTrial = prefs.getBool("trial", false);
  prefs.end();
  if (onTrial) Serial.println("[PROV] this network is on trial - will roll back if it fails");
  if (provSsid == "") {
    provSsid = WIFI_SSID;                   // fallback: compiled-in dev network
    provPass = WIFI_PASSWORD;
    Serial.println("[PROV] no saved credentials, using compiled-in network");
  } else {
    Serial.printf("[PROV] using saved network '%s'\n", provSsid.c_str());
  }
}

static void saveCreds(const String& ssid, const String& pass) {
  prefs.begin("orchid", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.end();
  Serial.printf("[PROV] saved '%s' to flash\n", ssid.c_str());
}

/* Wipes stored credentials so the node returns to the setup portal on next
   boot. Reachable at http://192.168.4.1/forget while the portal is up. */
static void forgetCreds() {
  prefs.begin("orchid", false);
  prefs.clear();
  prefs.end();
  Serial.println("[PROV] credentials cleared");
}

static String portalPage(const String& msg) {
  // Scan happens before the page is built so the farmer picks from a real list
  // rather than typing an SSID they might get wrong.
  int n = WiFi.scanNetworks();
  String opts;
  for (int i = 0; i < n && i < 15; i++) {
    opts += "<option value='" + WiFi.SSID(i) + "'>" + WiFi.SSID(i) +
            "  (" + String(WiFi.RSSI(i)) + " dBm)</option>";
  }
  WiFi.scanDelete();

  String p = F("<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
               "<style>body{font-family:system-ui;margin:0;padding:24px;background:#f6f5f2;color:#1b1a20}"
               "h1{font-size:20px;margin:0 0 4px}p.s{color:#63616c;font-size:14px;margin:0 0 20px}"
               "label{display:block;font-size:13px;font-weight:600;margin:14px 0 5px}"
               "select,input{width:100%;padding:11px;font-size:15px;border:1px solid #d5d1c9;border-radius:8px;background:#fff}"
               "button{width:100%;margin-top:20px;padding:13px;font-size:15px;font-weight:600;"
               "background:#5b3a8e;color:#fff;border:0;border-radius:8px}"
               ".m{background:#eaf3ec;border-left:3px solid #3f7a52;padding:10px 14px;border-radius:0 6px 6px 0;font-size:14px;margin-bottom:16px}"
               "</style><h1>Orchid sensor node</h1><p class=s>Choose the WiFi network this node should join.</p>");
  if (msg != "") p += "<div class=m>" + msg + "</div>";
  p += "<form method=POST action=/save><label>Network</label><select name=ssid>" + opts +
       "</select><label>Password</label><input name=pass type=password autocomplete=off>"
       "<button type=submit>Save and connect</button></form>";
  return p;
}

void startPortal() {
  WiFi.disconnect(true, true);
  delay(200);
  WiFi.mode(WIFI_AP_STA);                   // AP for the phone, STA so we can scan
  WiFi.softAP(apName().c_str());            // open network: the farmer has no password yet
  delay(400);

  dnsServer.start(53, "*", WiFi.softAPIP());  // any hostname resolves here -> captive portal

  portalServer.on("/", HTTP_GET, []() { portalServer.send(200, "text/html", portalPage("")); });
  portalServer.on("/save", HTTP_POST, []() {
    String s = portalServer.arg("ssid"), p = portalServer.arg("pass");
    if (s == "") { portalServer.send(200, "text/html", portalPage("Please choose a network.")); return; }
    saveCreds(s, p);
    portalServer.send(200, "text/html",
      "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
      "<body style='font-family:system-ui;padding:24px'><h2>Saved</h2>"
      "<p>The node is restarting and will join <b>" + s + "</b>.</p>"
      "<p>Reconnect your phone to your normal WiFi.</p>");
    delay(1200);
    ESP.restart();
  });
  portalServer.on("/forget", HTTP_GET, []() {
    forgetCreds();
    portalServer.send(200, "text/plain", "Cleared. Restarting.");
    delay(800); ESP.restart();
  });
  // Phones probe these URLs to detect a captive portal; answering pops the page up.
  portalServer.onNotFound([]() { portalServer.send(200, "text/html", portalPage("")); });
  portalServer.begin();

  portalRunning = true;
  Serial.printf("\n[PROV] ===== SETUP MODE =====\n");
  Serial.printf("[PROV] join WiFi network '%s' on your phone\n", apName().c_str());
  Serial.printf("[PROV] then open http://192.168.4.1\n\n");
}

void servePortal() {
  if (!portalRunning) return;
  dnsServer.processNextRequest();
  portalServer.handleClient();
}

void connectWiFi() {
  loadCreds();
  Serial.printf("\n[WIFI] joining %s", provSsid.c_str());
  // Tear the previous attempt down first. Calling begin() while the station is
  // already mid-connect gives "sta is connecting, cannot set config" and the
  // radio never actually joins - which is exactly what the serial log showed.
  WiFi.disconnect(true, true);
  delay(300);
  WiFi.mode(WIFI_STA);

  // Lower transmit power before begin(), so the very first transmission is
  // already reduced. 11dBm instead of the default 19.5dBm is a large cut in
  // peak current. The measured link is about -48dBm, which is a strong signal
  // with a wide margin, so range is not a concern at this site.
  WiFi.setTxPower(WIFI_POWER_11dBm);

  // Modem sleep lets the radio idle between beacons. This node only posts
  // outward and never waits on inbound traffic, so nothing is lost.
  WiFi.setSleep(true);

  // Let the supply settle after the mode change before drawing the surge.
  delay(200);

  WiFi.begin(provSsid.c_str(), provPass.c_str());
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 25000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] connected, ip=%s rssi=%d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.printf("\n[WIFI] FAILED (status=%d)\n", WiFi.status());
    Serial.println("[WIFI] networks this radio can actually see:");
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n && i < 12; i++)
      Serial.printf("   %-28s %4d dBm  ch%d\n",
                    WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i));
    if (n == 0)
      Serial.println("   (none - the ESP32 is 2.4GHz only and cannot see 5GHz)");
    WiFi.scanDelete();

    /* Three consecutive failures means the stored network is gone, renamed, or
       the password changed - a farmer moving house, or a new router. Raising the
       portal is the only way back without a laptop.
       Three, not one: a router rebooting should not drop a working node into
       setup mode and stop it reporting. */
    static uint8_t failures = 0;
    if (++failures >= 3 && !portalRunning) {
      // A failed REMOTE change is recoverable: restore what worked and restart.
      // Only raise the portal when there is nothing left to fall back to.
      if (rollbackCreds()) { delay(500); ESP.restart(); }
      Serial.println("[WIFI] 3 failed attempts - starting setup hotspot");
      startPortal();
    }
  }
}


/* Real wall-clock time matters: the validation script pairs each reading with
   the outdoor weather for that same hour, so a wrong clock ruins the comparison.

   NOT using SNTP/configTime. On ESP32 Arduino core 3.3.x that path asserts with
       udp_new_ip_type ... Required to lock TCPIP core functionality!
   and panics the board the moment Wi-Fi comes up. Instead the time is taken
   from the HTTP Date header Google returns on any request - which we are
   already making anyway, needs no extra library, and cannot crash the stack. */
static long epochOffset = 0;      // realEpoch = millis()/1000 + epochOffset
static bool clockOK = false;

static long parseHttpDate(const String& d) {
  // e.g. "Fri, 22 Aug 2026 16:45:02 GMT"
  static const char* M[] = {"Jan","Feb","Mar","Apr","May","Jun",
                            "Jul","Aug","Sep","Oct","Nov","Dec"};
  if (d.length() < 25) return 0;
  int day = d.substring(5, 7).toInt();
  String mon = d.substring(8, 11);
  int year = d.substring(12, 16).toInt();
  int hh = d.substring(17, 19).toInt();
  int mm = d.substring(20, 22).toInt();
  int ss = d.substring(23, 25).toInt();
  int m = 0; for (int i = 0; i < 12; i++) if (mon == M[i]) m = i;
  struct tm t = {};
  t.tm_year = year - 1900; t.tm_mon = m; t.tm_mday = day;
  t.tm_hour = hh; t.tm_min = mm; t.tm_sec = ss;
  time_t e = mktime(&t);
  return (e < 1700000000) ? 0 : (long)e;
}

void syncClock() {
  HTTPClient http;
  http.setTimeout(9000);
  http.begin("http://google.com/generate_204");
  const char* want[] = {"Date"};
  http.collectHeaders(want, 1);
  int code = http.GET();
  long e = (code > 0) ? parseHttpDate(http.header("Date")) : 0;
  http.end();
  if (e) {
    epochOffset = e - (long)(millis() / 1000);
    clockOK = true;
    Serial.printf("[TIME] ok from HTTP Date, epoch=%ld\n", e);
  } else {
    Serial.println("[TIME] could not read the time; readings will be timestamped wrongly");
  }
}

static uint64_t nowMs() {
  return clockOK ? ((uint64_t)((long)(millis() / 1000) + epochOffset)) * 1000ULL : 0ULL;
}


float vpdKpa(float t, float rh) {
  float svp = 0.6108 * exp(17.27 * t / (t + 237.3));
  return svp * (1.0 - rh / 100.0);
}


bool postJson(const String& url, const String& body, bool put) {
  HTTPClient http;
  http.setTimeout(9000);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = put ? http.PUT(body) : http.POST(body);
  http.end();
  return code == 200;
}


/* ---- device self-registration -------------------------------------------
   A board knows one thing about itself with certainty: its MAC address, burned
   in at the factory and globally unique. That is enough to identify it without
   any configuration, which is what lets identical firmware go onto every node.

   The node writes a record under its own MAC and then reads back the section a
   farmer has assigned it to. It never chooses its own section - assignment is
   the app's decision, and writing it from the node would let two boards claim
   the same zone. */
String deviceMac;                       // "1CC3ABC321A0", no separators
uint32_t lastAnnounce = 0;
// Whether this boot has announced at all yet. Without it the 30 s gate below
// silently skips the FIRST cycle after a reset: lastAnnounce starts at 0 and
// millis() is only a few thousand by then, so the difference is never > 30000.
// The device record - firmware version, ip, rssi, ssid, read interval - then
// stayed stale until the SECOND reading cycle, which is over five minutes at
// the production interval. A node you had just rebooted looked dead in the
// device list, and a Wi-Fi change could not be confirmed from the app.
bool announcedThisBoot = false;

#define LED_PIN 2                       // onboard blue LED on the DevKit V1

static String macKey() {
  if (deviceMac != "") return deviceMac;
  uint8_t m[6];
  WiFi.macAddress(m);
  char b[13];
  snprintf(b, sizeof(b), "%02X%02X%02X%02X%02X%02X", m[0],m[1],m[2],m[3],m[4],m[5]);
  deviceMac = String(b);
  return deviceMac;
}

/* Announce presence. Deliberately a PATCH-style write of individual fields
   rather than a whole-object PUT: a PUT would wipe `assignedTo`, which the app
   owns and the node must never clobber. */
void announceDevice() {
  if (WiFi.status() != WL_CONNECTED) return;
  String url = String(FB_HOST) + "/devices/" + macKey() + ".json";
  String body = "{\"mac\":\"" + macKey() +
                "\",\"ip\":\"" + WiFi.localIP().toString() +
                "\",\"rssi\":" + String(WiFi.RSSI()) +
                ",\"fw\":\"validation-2.0\"" +
                // Which farm this board was flashed for. The backend filters
                // the global registry on it, so an unflashed board carries no
                // tenant and stays claimable by anyone - which is right: it
                // belongs to nobody yet.
                ",\"tenantId\":\"" TENANT_ID "\"" +
                // The network it is ACTUALLY on. Without this the app can offer
                // to change the Wi-Fi but cannot show what it is changing from,
                // and a farmer has no way to confirm the change took - the node
                // goes quiet during the reboot either way, so "it came back" is
                // not on its own proof it came back on the new network.
                ",\"ssid\":\"" + WiFi.SSID() + "\"" +
                ",\"lastSeen\":" + String((long long)(nowMs()/1000)) + "}";
  HTTPClient http;
  http.setTimeout(8000);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.PATCH(body);          // merge, never replace
  http.end();
  if (code != 200)
    Serial.printf("[DEV] announce failed (%d)\n", code);
}

/* These two live with the command parser further down, but the assignment fetch
   needs them first. Declared here rather than relying on the Arduino
   preprocessor to hoist prototypes for `static` functions, which it does not
   always do. */
static String jsonStr(const String& src, const char* key);
static long   jsonNum(const String& src, const char* key, long dflt);

/* Read back what the app has decided this board is. Unassigned boards keep
   reporting to their fallback section and simply wait to be claimed.

   This fetches the WHOLE device record rather than just assignedTo, so the read
   interval rides along in the same request: one HTTP round trip, two settings.
   A second GET here would have slowed every reading cycle, which is already
   dominated by network time. */
void fetchAssignment() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.setTimeout(8000);
  http.begin(String(FB_HOST) + "/devices/" + macKey() + ".json");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200) return;

  // ---- read interval, when the app has set one ----
  long want = jsonNum(body, "readIntervalMs", 0);
  if (want > 0) {
    uint32_t ms = (uint32_t)want;
    if (ms < READ_INTERVAL_MIN_MS) ms = READ_INTERVAL_MIN_MS;
    if (ms > READ_INTERVAL_MAX_MS) ms = READ_INTERVAL_MAX_MS;
    if (ms != readIntervalMs) {
      Serial.printf("[CFG] read interval %lu -> %lu ms\n",
                    (unsigned long)readIntervalMs, (unsigned long)ms);
      readIntervalMs = ms;
    }
  }

  // ---- assignment ----
  String v = jsonStr(body, "assignedTo");
  v.trim();
  if (v == "" || v == "null") {
    if (isClaimed) Serial.println("[DEV] assignment removed, reverting to fallback section");
    isClaimed = false;
    return;
  }
  int slash = v.indexOf('/');
  if (slash <= 0) return;                       // expects "H1/S2"
  String h = v.substring(0, slash), sec = v.substring(slash + 1);
  if (h == assignedHouse && sec == assignedSection && isClaimed) return;   // unchanged
  assignedHouse = h; assignedSection = sec; isClaimed = true;
  rebuildPaths();
  Serial.printf("[DEV] assigned to %s/%s\n", h.c_str(), sec.c_str());
}

/* Four identical boxes on a bench look the same in a list. Tapping Identify in
   the app sets a flag here and this blinks the onboard LED so the farmer can see
   which physical unit they are about to assign. The node clears the flag itself
   so the app does not have to. */
/* Ask the RADIO what it can see, and publish it for the app.

   This has to happen on the node, not the phone. The two are in different
   places - the board is in the greenhouse and the phone is in a hand - so the
   networks the phone can see are not the ones the node can join, and offering
   the phone's list would invite exactly the wrong choice. Android also gates
   Wi-Fi scanning behind location permission, which this avoids entirely.

   scanNetworks() briefly disturbs the connection; the ESP32 reconnects on its
   own, and the next reading cycle would re-establish it in any case. */
void scanNetworks() {
  if (WiFi.status() != WL_CONNECTED) return;
  Serial.println("[SCAN] looking for networks");
  int found = WiFi.scanNetworks();
  if (found < 0) found = 0;

  // Strongest first, capped: a long list is not more useful and the document is
  // read by a phone.
  const int MAX_REPORT = 12;
  String json = "[";
  int written = 0;
  for (int i = 0; i < found && written < MAX_REPORT; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid.length() == 0) continue;              // hidden network, unusable here
    ssid.replace("\"", "\\\"");   // keep the JSON well formed
    if (written) json += ",";
    json += "{\"ssid\":\"" + ssid + "\",";
    json += "\"rssi\":" + String(WiFi.RSSI(i)) + ",";
    json += "\"secure\":" + String(WiFi.encryptionType(i) == WIFI_AUTH_OPEN
                                                 ? "false" : "true") + "}";
    written++;
  }
  json += "]";
  WiFi.scanDelete();

  Serial.printf("[SCAN] %d networks, reporting %d\n", found, written);
  postJson(String(FB_HOST) + "/devices/" + macKey() + "/scan.json", json, true);
  postJson(String(FB_HOST) + "/devices/" + macKey() + "/scanRequest.json", "false", true);
}

void handleIdentify() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.setTimeout(6000);
  http.begin(String(FB_HOST) + "/devices/" + macKey() + "/identify.json");
  int code = http.GET();
  String v = (code == 200) ? http.getString() : "";
  http.end();
  if (v.indexOf("true") < 0) return;

  Serial.println("[DEV] identify - blinking onboard LED");
  pinMode(LED_PIN, OUTPUT);
  for (int i = 0; i < 20; i++) {                // ~10 seconds
    digitalWrite(LED_PIN, HIGH); delay(250);
    digitalWrite(LED_PIN, LOW);  delay(250);
  }
  HTTPClient clr;
  clr.begin(String(FB_HOST) + "/devices/" + macKey() + "/identify.json");
  clr.addHeader("Content-Type", "application/json");
  clr.PUT("false");
  clr.end();
}

/* ---- command path: cloud -> node ----------------------------------------
   Until now this node only pushed data up. The app's watering buttons and the
   backend's automation engine had no way to reach the relays.

   The backend writes a single pending command to
       /farm/houses/H1/sections/S1/command
   shaped like  {"id":"abc123","action":"water","durationSec":45}
   and this node acknowledges it at  .../commandAck  once the pump has run.

   Commands are matched by id rather than cleared by the node, because a node
   that deletes its own command loses the record if it resets mid-pour. Keeping
   the last executed id in RAM means a repeated poll of the same command is
   ignored, while a genuinely new command always has a new id.

   Parsing is done with string search rather than a JSON library: the payload is
   three known fields written by our own backend, and adding a dependency for
   that is not worth the flash. */
String lastCmdId = "";

static String jsonStr(const String& src, const char* key) {
  String pat = String("\"") + key + "\":\"";
  int i = src.indexOf(pat);
  if (i < 0) return "";
  i += pat.length();
  int j = src.indexOf('"', i);
  return j < 0 ? "" : src.substring(i, j);
}
static long jsonNum(const String& src, const char* key, long dflt) {
  String pat = String("\"") + key + "\":";
  int i = src.indexOf(pat);
  if (i < 0) return dflt;
  i += pat.length();
  return src.substring(i).toInt();
}

/* On a cold boot lastCmdId is empty, so a command still sitting in Firebase
   would be treated as new and executed a second time. That is how a reset turned
   into an unexpected pour on the bench.

   The acknowledgement we already write is the durable record of what ran, so
   read it back once at startup and seed lastCmdId from it. RAM state is
   reconstructed from the cloud instead of being lost. */
void seedLastCommandFromAck() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.setTimeout(8000);
  http.begin(BASE + "/commandAck.json");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || body.length() < 5 || body == "null") return;
  String id = jsonStr(body, "id");
  if (id != "") {
    lastCmdId = id;
    Serial.printf("[CMD] resuming after reset, last completed id=%s\n", id.c_str());
  }
}

/* Is there a stop order waiting for the pour that is running right now?

   Read directly rather than through pollCommand(), because pollCommand() would
   try to START something and we are already inside a pour. */
bool stopRequested(const String& runningId) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setTimeout(4000);
  http.begin(BASE + "/command.json");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || body.length() < 5 || body == "null") return false;

  if (jsonStr(body, "action") != "stop") return false;
  String id = jsonStr(body, "id");
  if (id == "" || id == lastCmdId) return false;      // already acted on

  // A stop may name the run it is meant for. An unaddressed stop applies to
  // whatever is running, which is what the section's Stop button sends.
  String target = jsonStr(body, "targetId");
  if (target != "" && target != runningId) return false;

  lastCmdId = id;
  Serial.printf("[CMD] STOP received during %s\n", runningId.c_str());
  return true;
}

/* Waits in slices while watching for a stop. Returns false if cut short.

   The old code waited with delay(seconds * 1000UL) in one piece, so for the
   whole length of a pour the board could not be reached at all. That is why a
   Stop button was impossible before this, and why a 120 s watering could not be
   interrupted even by the farmer standing next to it. */
/* How often a RUNNING pour checks whether it has been told to stop.

   Deliberately slower than COMMAND_POLL_MS. Each check is a fresh HTTPS request
   to Firebase, and a TLS handshake on this chip costs seconds - measured at
   roughly 9 s per check during a bench run. At 2 s that meant a pour spent more
   time checking than pouring. 5 s bounds how long Stop takes to bite while
   keeping the handshakes down. */
const uint32_t STOP_POLL_MS = 5000;

/* Never start a stop-check that would outlast the pour it guards. */
const uint32_t STOP_CHECK_BUDGET_MS = 6000;

bool sleepWatchingForStop(uint32_t totalMs, const String& runningId) {
  /* Timed by WALL CLOCK, not by accumulated sleep.

     The first version added up its own 250 ms slices and ignored the time spent
     inside stopRequested(). Since each of those is a multi-second HTTPS round
     trip, the pump ran far longer than asked: a 25 s command measured 173 s on
     the bench before this was fixed. Anything that happens while the relay is
     on is part of the pour and must be counted as such. */
  const uint32_t start = millis();
  uint32_t lastCheck = start;

  while (millis() - start < totalMs) {
    delay(50);
    servePortal();

    const uint32_t elapsed   = millis() - start;
    const uint32_t remaining = (elapsed >= totalMs) ? 0 : totalMs - elapsed;

    if (remaining > STOP_CHECK_BUDGET_MS && millis() - lastCheck >= STOP_POLL_MS) {
      lastCheck = millis();
      if (stopRequested(runningId)) return false;
    }
  }
  return true;
}

void pollCommand() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (lastCmdId == "") seedLastCommandFromAck();   // first poll after a reset

  HTTPClient http;
  http.setTimeout(8000);
  http.begin(BASE + "/command.json");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || body.length() < 5 || body == "null") return;

  String id     = jsonStr(body, "id");
  String action = jsonStr(body, "action");
  long   secs   = jsonNum(body, "durationSec", 0);
  if (id == "" || action == "") return;
  if (id == lastCmdId) return;                 // already done, backend has not cleared it yet

  /* A stop that arrives while nothing is running.

     A pour watches for its own stop from inside sleepWatchingForStop(), so
     reaching here means the run has already finished. Acknowledge it anyway,
     or the app waits for a confirmation that will never come. This is also why
     the duration check below had to move: a stop carries no durationSec, and
     the old guard rejected it as malformed. */
  if (action == "stop") {
    lastCmdId = id;
    Serial.println("[CMD] stop received, but nothing is running");
    postJson(BASE + "/commandAck.json",
             "{\"id\":\"" + id + "\",\"action\":\"stop\",\"done\":true,\"idle\":true,\"at\":" +
             String((long long)(nowMs()/1000)) + "}", true);
    return;
  }

  // Everything past here moves water, so it needs a duration.
  if (secs <= 0 && action != "wifi") return;

  /* Refuse a command that has been sitting in the document too long.

     A command doc persists until something overwrites it, so a board that
     reboots hours later would find the last one and pour. That is exactly what
     happened during testing, and it is the same class of fault as a relay
     clicking at midday with nobody touching the app.

     Seconds, not milliseconds: long is 32-bit here and an epoch in ms
     overflows it. Commands without the field are obeyed, so an older backend
     keeps working. */
  const long COMMAND_MAX_AGE_SEC = 900;             // 15 minutes
  long issuedAtSec = jsonNum(body, "issuedAtSec", 0);
  if (issuedAtSec > 0 && clockOK) {
    long age = (long)(nowMs() / 1000ULL) - issuedAtSec;
    if (age > COMMAND_MAX_AGE_SEC) {
      lastCmdId = id;                               // never look at it again
      Serial.printf("[CMD] ignoring %s: issued %ld s ago, too old to obey\n",
                    action.c_str(), age);
      return;
    }
  }

  Serial.printf("[CMD] %s for %lds (id=%s)\n", action.c_str(), secs, id.c_str());

  if (action == "water" || action == "tray") {
    /* Say the pour has BEGUN, before it runs.

       The completion ack is only posted when the pour ends, so until now the
       app had no signal for "it is running right now" - it could only show
       "sent" and then, up to two minutes later, "done". A countdown and a Stop
       button need to be anchored to something the NODE said, not to a timer the
       phone started hopefully. */
    postJson(BASE + "/commandAck.json",
             "{\"id\":\"" + id + "\",\"action\":\"" + action + "\",\"durationSec\":" + String(secs) + ",\"started\":true,\"done\":false,\"at\":" +
             String((long long)(nowMs()/1000)) + "}", true);
    deliver(action, secs, id);
  }
  else if (action == "wifi") {
    // Credentials arrive from the app. Saved on trial, never blindly trusted.
    String ns = jsonStr(body, "ssid"), np = jsonStr(body, "pass");
    if (ns == "") { Serial.println("[CMD] wifi change missing ssid, ignored"); return; }
    lastCmdId = id;
    postJson(BASE + "/commandAck.json",
             "{\"id\":\"" + id + "\",\"action\":\"wifi\",\"done\":true,\"at\":" +
             String((long long)(nowMs()/1000)) + "}", true);
    saveCredsProvisional(ns, np);
    Serial.println("[CMD] restarting onto the new network");
    delay(800);
    ESP.restart();
  }
  else { Serial.printf("[CMD] unknown action '%s', ignored\n", action.c_str()); return; }

  lastCmdId = id;

  /* stopped=true tells the app the pour ended early because someone pressed
     Stop, not because it ran its course. The app needs to tell those apart:
     one is "watered for 90 s", the other is "stopped after 12 s". */
  String ack = "{\"id\":\"" + id + "\",\"action\":\"" + action +
               "\",\"durationSec\":" + String(secs) +
               ",\"started\":true,\"stopped\":" + String(lastRunStopped ? "true" : "false") +
               ",\"done\":true,\"at\":" + String((long long)(nowMs()/1000)) + "}";
  bool ok = postJson(BASE + "/commandAck.json", ack, true);
  Serial.printf("[CMD] ack %s\n", ok ? "sent" : "FAILED");
}

/* Free a bus that a reset left mid-transaction.
 *
 * An RTS reset restarts the ESP32 but NOT the BH1750, so a reset landing between
 * a slave's address byte and its data leaves that slave still driving SDA low,
 * waiting to finish. A held-low SDA means no START condition can be generated,
 * so every later Wire.begin() fails and a full bus scan finds nothing at ANY
 * address - which reads exactly like a disconnected sensor.
 *
 * The standard remedy: bit-bang up to nine SCL pulses, one more than the eight
 * bits a stuck slave could still be clocking out, then issue a STOP. Costs about
 * a millisecond when the bus is healthy.
 *
 * Measured evidence, 29 Aug 2026: the node reported "NOTHING on the bus", an RTS
 * reset did NOT clear it, and a reflash DID - on wiring that a probe sketch
 * proved good minutes later. Note this is the best explanation of that
 * behaviour, not a confirmed one; confirm by resetting the board ~20 times with
 * this in place and checking it never wedges.
 */
void i2cRecover() {
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, INPUT_PULLUP);
  delay(5);
  if (digitalRead(I2C_SDA) == HIGH) return;        // bus already free

  Serial.println("[I2C] SDA held low - clocking the bus free");
  pinMode(I2C_SCL, OUTPUT);
  for (int i = 0; i < 9 && digitalRead(I2C_SDA) == LOW; i++) {
    digitalWrite(I2C_SCL, LOW);  delayMicroseconds(5);
    digitalWrite(I2C_SCL, HIGH); delayMicroseconds(5);
  }
  // STOP condition: SDA rises while SCL is high.
  pinMode(I2C_SDA, OUTPUT);
  digitalWrite(I2C_SDA, LOW);  delayMicroseconds(5);
  digitalWrite(I2C_SCL, HIGH); delayMicroseconds(5);
  digitalWrite(I2C_SDA, HIGH); delayMicroseconds(5);
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, INPUT_PULLUP);
  Serial.printf("[I2C] recovery done, SDA now %s\n",
                digitalRead(I2C_SDA) == HIGH ? "free" : "STILL LOW");
}

/* Try the light meter a few times before giving up.
 *
 * relaySelfTest() clicks both relays immediately before this runs and dips the
 * 3.3 V rail while it does. A single attempt into a sagging rail is fragile, and
 * the cost of losing that gamble is a whole boot reporting -999 lux.
 */
bool beginLightMeter() {
  for (int a = 1; a <= 3; a++) {
    if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
      Serial.printf("[BH1750] found (attempt %d)\n", a);
      return true;
    }
    delay(120);
  }
  Serial.println("[BH1750] NOT FOUND after 3 attempts");
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println("\n\n=== SENSOR NODE (validation build) " HOUSE_ID "-" SECTION_ID " ===");

  // Do this before anything touches the radio, so the clock is already down
  // when the first surge arrives.
  reduceCurrentDraw();

  // Before anything else that takes time: get the relays into a known-off state
  // so a reset can never leave a pump running.
  setupRelays();

  // Before the radio starts: does the farmer want the setup portal?
  if (bootButtonHeld()) { startPortal(); }

  relaySelfTest();

  dht.begin();
  i2cRecover();
  Wire.begin(I2C_SDA, I2C_SCL);
  lightOK = beginLightMeter();
  if (!lightOK) {
    // Scanning the bus makes the cause obvious: nothing at all means the wiring
    // is wrong; a device at 0x5C means ADD is tied high instead of left floating.
    Serial.println("[I2C] scanning bus...");
    int found = 0;
    for (uint8_t a = 1; a < 127; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) { Serial.printf("   device at 0x%02X\n", a); found++; }
    }
    if (!found)
      Serial.println("   NOTHING on the bus - check SDA->D21, SCL->D22, VCC->3V3, GND->GND");
  }

  // Every relay channel driven OFF before Wi-Fi comes up, so a queued command
  // cannot arrive while a pin is still floating. On an ACTIVE-LOW board a
  // floating pin reads as ON, which is a valve opening at power-up.
  masterSetupRelays();

  connectWiFi();
  syncClock();
}


/* One full sensor cycle: read, announce, upload. Called on its own schedule by
   loop(), which is now free to answer commands in between. */
void takeReading() {
  float t  = dht.readTemperature();
  float rh = dht.readHumidity();
  float lx = lightOK ? lightMeter.readLightLevel() : SENTINEL;

  // Capacitive probe: raw ADC counts fall as moisture rises.
  //
  // These are MEASURED on this physical probe, 23 Aug 2026, not datasheet
  // guesses: 2596-2607 counts held in open air, 1095-1103 with the blade in
  // water to the printed line. Both ends repeated within ~11 counts, and the
  // 1500-count span between them is the usable range.
  //
  // On a Vanda there is no growing medium to measure, so this probe sits in the
  // humidity tray and reports its water level: 0% is an empty tray, 100% is
  // full. A different probe, or a move to a different medium, needs these two
  // numbers re-measured the same way.
  const int SOIL_DRY = 2600, SOIL_WET = 1100;
  int raw = analogRead(SOIL_PIN);

  /* A count outside the calibrated span is a DISCONNECTED PROBE, not a very wet
     or very dry one, and must not be clamped into a confident answer.

     Clamping is what this did, and it turned a floating ADC pin into a
     measurement: raw 3015 - drier than open air, which is physically impossible
     - clamped to 0% "empty tray", and raw 111 - wetter than water - clamped to
     100% "full tray". Both were sent with sensorFault false and both were
     believed. A false empty makes the system fill a tray it cannot see; a false
     full stops it filling one that needs it. -999 is safe because the backend
     already knows to distrust it; a clamped 0 or 100 is not.

     The margin lets a healthy probe drift past either end without being called
     faulty. */
  const int SOIL_MARGIN = 150;
  bool soilOK = (raw >= SOIL_WET - SOIL_MARGIN) && (raw <= SOIL_DRY + SOIL_MARGIN);
  float soil = 100.0 * (SOIL_DRY - raw) / (float)(SOIL_DRY - SOIL_WET);
  if (soil < 0) soil = 0; if (soil > 100) soil = 100;
  if (!soilOK) {
    Serial.printf("[SOIL] raw %d outside %d-%d - probe disconnected\n",
                  raw, SOIL_WET - SOIL_MARGIN, SOIL_DRY + SOIL_MARGIN);
    soil = SENTINEL;
  }

  bool tempOK  = !isnan(t) && !isnan(rh);
  bool lightIsOK = lightOK && lx >= 0;
  if (!tempOK) { t = SENTINEL; rh = SENTINEL; }
  if (!lightIsOK) lx = SENTINEL;

  if (!clockOK && WiFi.status() == WL_CONNECTED) syncClock();
  uint64_t ms = nowMs();

  JsonDocument d;
  d["temperature"]  = tempOK ? roundf(t * 10) / 10.0 : SENTINEL;
  d["humidity"]     = tempOK ? roundf(rh * 10) / 10.0 : SENTINEL;
  d["light"]        = lightIsOK ? roundf(lx) : SENTINEL;
  d["vpd"]          = tempOK ? roundf(vpdKpa(t, rh) * 1000) / 1000.0 : SENTINEL;
  d["timestamp"]    = ms;
  d["sampleMoisture"] = roundf(soil * 10) / 10.0;
  d["soilRaw"]        = raw;
  d["sensorFault"]    = (!tempOK || !lightIsOK);
  d["node"]         = "validation";

  String body;
  serializeJson(d, body);

  // soilRaw is printed so the probe can be calibrated: note the value in open
  // air (dry end) and in a glass of water (wet end), then correct SOIL_DRY and
  // SOIL_WET above. Until then the percentage is indicative only.
  Serial.printf("[READ] %.1fC  %.1f%%  %.0f lux  soil=%.0f%% (raw %d)  vpd=%.3f%s\n",
                t, rh, lx, soil, raw, tempOK ? vpdKpa(t, rh) : 0.0,
                (!tempOK || !lightIsOK) ? "   <-- SENSOR FAULT" : "");

  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  // Announce presence and pick up any assignment change before posting, so a
  // reading always lands in whatever section the board currently belongs to.
  if (WiFi.status() == WL_CONNECTED) {
    if (!announcedThisBoot || millis() - lastAnnounce > 30000UL) {
      announceDevice();
      lastAnnounce = millis();
      announcedThisBoot = true;
    }
    fetchAssignment();
    handleIdentify();
  }

  if (WiFi.status() == WL_CONNECTED) {
    bool a = postJson(BASE + "/latest.json", body, true);   // current state
    bool b = postJson(HIST + ".json",        body, false);  // archive
    Serial.printf("[CLOUD] latest=%s history=%s\n", a ? "ok" : "FAIL", b ? "ok" : "FAIL");
    if (!a || !b) {
      Serial.println("[CLOUD] if WiFi is connected but this keeps failing, the");
      Serial.println("        network is probably behind a captive portal login.");
    }
  }

}


/* Two jobs at two rates.

   Readings are expensive and slow-moving, so they run at readIntervalMs.
   Commands are cheap and urgent, so they run at COMMAND_POLL_MS. Before this
   split, both ran at readIntervalMs and a pressed button waited for the sensor
   clock - see the note on COMMAND_POLL_MS.

   Nothing here blocks for longer than one slice, so servePortal() keeps
   answering and a running pour can still be stopped. */
/* Say "I am here". Deliberately a tiny PATCH of two fields: announceDevice()
   also sends ip, ssid and fw, which is right once per reading cycle and
   wasteful every 30 seconds.

   Gated on clockOK because nowMs() returns 0 until the clock syncs, and a
   lastSeen of 0 reads as 1970 - far worse than sending no heartbeat at all. */
void sendHeartbeat() {
  if (WiFi.status() != WL_CONNECTED || !clockOK) return;
  String body = "{\"lastSeen\":" + String((long long)(nowMs() / 1000)) +
                ",\"rssi\":" + String(WiFi.RSSI()) + "}";
  HTTPClient http;
  http.setTimeout(6000);
  http.begin(String(FB_HOST) + "/devices/" + macKey() + ".json");
  http.addHeader("Content-Type", "application/json");
  int code = http.PATCH(body);
  http.end();
  if (code != 200) Serial.printf("[HB] heartbeat failed (%d)\n", code);
}

/* Answer a ping, so a farmer can ask "is this node there?" and get an answer in
   seconds instead of waiting for the next reading.

   `pingRequest` carries a TOKEN minted by the backend rather than `true`, and
   the node echoes it back as `pingAck`. That is what makes the answer
   unambiguous: the backend compares a token it minted against the same token
   returned, entirely within its own clock domain. Comparing lastSeen (node
   clock) against a request time (server clock) would be comparing two clocks
   that are allowed to disagree - the mistake behind the "161 days ago" bug.

   The ack and the flag clear are ONE patch, so a ping cannot be answered twice
   or left half-consumed if Wi-Fi drops mid-write. */
void answerPing(const String& body) {
  long token = jsonNum(body, "pingRequest", 0);
  if (token <= 0) return;
  Serial.printf("[PING] answering token %ld\n", token);
  String ack = "{\"pingAck\":" + String(token) + ",\"pingRequest\":0";
  if (clockOK) ack += ",\"lastSeen\":" + String((long long)(nowMs() / 1000));
  ack += "}";
  HTTPClient http;
  http.setTimeout(6000);
  http.begin(String(FB_HOST) + "/devices/" + macKey() + ".json");
  http.addHeader("Content-Type", "application/json");
  int code = http.PATCH(ack);
  http.end();
  if (code != 200) Serial.printf("[PING] ack failed (%d)\n", code);
}

/* Identify and Wi-Fi scan, on their own clock.
   One GET of the device record answers both, rather than two requests. */
void pollDeviceFlags() {
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.setTimeout(6000);
  http.begin(String(FB_HOST) + "/devices/" + macKey() + ".json");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || body.length() < 5 || body == "null") return;

  // Ping first: handleIdentify() blocks ~10 s blinking the LED, and a ping is
  // supposed to feel instant.
  if (body.indexOf("\"pingRequest\":") >= 0) answerPing(body);
  if (body.indexOf("\"identify\":true") >= 0) handleIdentify();
  if (body.indexOf("\"scanRequest\":true") >= 0) scanNetworks();
}

void loop() {
  // The setup page must answer while the node waits to be configured.
  servePortal();

  static uint32_t lastReadAt = 0;
  static uint32_t lastCmdAt  = 0;
  static bool     firstCycle = true;

  /* The reading cycle runs FIRST, and command polling waits for it.

     This order is not cosmetic. BASE starts as the compiled-in HOUSE_ID and
     SECTION_ID, and only fetchAssignment() - which lives inside takeReading() -
     repoints it at the section this board is actually assigned to. Polling
     before that reads a DIFFERENT section's command document: on the first
     build of this change the node booted, polled H1/S1 while assigned to
     H1/S5, found a 20-hour-old watering command there and ran the pump for
     90 seconds.

     lastReadAt is stamped AFTER the cycle, so the period stays readIntervalMs
     plus however long the HTTP work took, which is what the backend's
     freshness thresholds are calibrated against. */
  if (firstCycle || millis() - lastReadAt >= readIntervalMs) {
    firstCycle = false;
    takeReading();
    lastReadAt = millis();
  }

  if (!firstCycle && WiFi.status() == WL_CONNECTED
      && millis() - lastCmdAt >= COMMAND_POLL_MS) {
    lastCmdAt = millis();
    pollCommand();
  }

  /* Then act for the sections that have no node of their own.

     After pollCommand deliberately: this board is a sensor node first and a
     master second, so its own section is served before it opens a valve for
     anybody else. Harmless until a master is named for the house - the queue
     path is keyed by this board's MAC and simply reads back empty. */
  if (!firstCycle) masterPollQueue();

  // Identify and scan work whether or not this node is assigned to a section,
  // so unlike pollCommand they are not gated on the first reading cycle - the
  // Add Section picker identifies boards that have never been assigned.
  static uint32_t lastDevAt = 0;
  if (WiFi.status() == WL_CONNECTED && millis() - lastDevAt >= DEVICE_POLL_MS) {
    lastDevAt = millis();
    pollDeviceFlags();
  }

  /* Keep looking for a light meter that was not there at boot.
   *
   * THE PART THAT MATTERS. lightOK was set once in setup() and never revisited,
   * and takeReading() reads `lightOK ? read() : SENTINEL` - so a sensor missing
   * at boot stayed missing FOREVER. Reconnect the wire, fit a new sensor,
   * nothing changed: -999 until somebody rebooted the board, which a farmer has
   * no reason to know to do.
   *
   * Reported as "even after fixing it, it kept showing that -999 error the same
   * way", and that description is precisely this block being absent. Bus
   * recovery alone does not help here: with lightOK false, nothing ever asks the
   * sensor anything, however clean the bus is.
   *
   * Only runs while lightOK is false, so a healthy node pays nothing.
   */
  static uint32_t lastLightTry = 0;
  if (!lightOK && millis() - lastLightTry >= LIGHT_RETRY_MS) {
    lastLightTry = millis();
    i2cRecover();
    Wire.begin(I2C_SDA, I2C_SCL);
    if (beginLightMeter()) {
      lightOK = true;
      Serial.println("[BH1750] recovered at runtime - no reboot needed");
    }
  }

  // "I am here", on a clock of its own - not the reading clock.
  static uint32_t lastBeatAt = 0;
  if (WiFi.status() == WL_CONNECTED && millis() - lastBeatAt >= HEARTBEAT_MS) {
    lastBeatAt = millis();
    sendHeartbeat();
  }

  delay(50);
}
