/* Offline fallback: a master waters from its own copy of today's plan when the
 * cloud cannot be reached.
 *
 * Every watering is decided by the engine in the cloud. If the engine, or the
 * farm's internet, is down at a section's planned minute, nothing would water
 * that day - and Vanda are watered every day. So the engine writes each master
 * a copy of the day's plan (backend app/services/fallback.py), this file keeps
 * it in flash, and once the cloud has been silent past a section's planned
 * minute AND past the engine's own late window, the master waters that section
 * itself, once, and reports it when the cloud is back.
 *
 *   /farm/masters/{MAC}/fallbackPlan       <- engine: day, dayStartSec, entries
 *   /farm/engineBeat                       <- engine: its epoch, every pass
 *   /farm/masters/{MAC}/fallbackDone/{id}  -> this: what it watered on its own
 *
 * "THE CLOUD IS GONE" means: the database has not answered for FB_SILENT_MS, or
 * it answers but the engine's beat is older than that - nobody is deciding
 * anything. A beat never seen since boot (a backend older than this) does not
 * count as stopped, so this firmware is safe against the old backend.
 *
 * WHAT IT WILL NOT DO:
 *   - pour without a known clock. After a reboot with no internet the hour is
 *     unknown, and a pour at an unknown hour could be at midnight;
 *   - water a section twice in a day. Any watering of that section today, from
 *     the queue or from here, counts (fallbackNoteWatered);
 *   - start before the engine has given up on that minute (afterMin is longer
 *     than the engine's 20-minute late window), so the two never both pour;
 *   - use a plan more than a day old ("today's plan, else yesterday's");
 *   - pour longer than MASTER_MAX_SEC, or on a channel outside 1..8;
 *   - fill trays or feed. Watering only.
 * The decision itself is fbDecide() in fallback_decide.h, tested on a PC.
 */
#include "fallback_decide.h"

const char* FB_PLAN_FILE = "/fb_plan.json";     // the latest plan from the engine
const char* FB_LAST_FILE = "/fb_last.txt";      // "<section> <epoch s>" per line: last watered
const char* FB_PEND_FILE = "/fb_pending.txt";   // one report per line, not yet uploaded
const unsigned long FB_SYNC_MS   = 300000UL;    // plan and beat, every 5 min on a master
const unsigned long FB_IDLE_MS   = 1800000UL;   // a board with no plan looks every 30 min
const unsigned long FB_CHECK_MS  = 30000UL;     // is a fallback watering due? every 30 s
const unsigned long FB_SILENT_MS = 600000UL;    // the cloud counts as gone after 10 min
const int FB_MAX_SECTIONS = 16;

static unsigned long fbCloudOkMs = 0;   // millis() of the last successful database read
static long fbBeatAt = 0;               // the engine's last beat (epoch s), as it wrote it
static String fbPlan;                   // the cached plan document
static bool fbLoaded = false;
static unsigned long fbLastSync = 0, fbLastCheck = 0, fbSyncEvery = FB_SYNC_MS;

struct FbLast { String section; long at; };
static FbLast fbLast[FB_MAX_SECTIONS];
static int fbLastN = 0;

static long fbNow() { return (long)(nowMs() / 1000ULL); }

/* Any successful read from the database means it can be reached. */
void fallbackNoteCloudOk() {
  fbCloudOkMs = millis();
  if (fbCloudOkMs == 0) fbCloudOkMs = 1;
}

static void fbLoad() {
  if (fbLoaded) return;
  fbLoaded = true;
  File f = LittleFS.open(FB_PLAN_FILE, "r");
  if (f) { fbPlan = f.readString(); f.close(); }
  File l = LittleFS.open(FB_LAST_FILE, "r");
  if (!l) return;
  while (l.available() && fbLastN < FB_MAX_SECTIONS) {
    String line = l.readStringUntil('\n');
    line.trim();
    int sp = line.indexOf(' ');
    if (sp <= 0) continue;
    fbLast[fbLastN].section = line.substring(0, sp);
    fbLast[fbLastN].at = line.substring(sp + 1).toInt();
    fbLastN++;
  }
  l.close();
}

static long fbLastRun(const String& section) {
  for (int i = 0; i < fbLastN; i++)
    if (fbLast[i].section == section) return fbLast[i].at;
  return 0;
}

/* This section's watering pump has run. Called after EVERY watering - from the
 * queue (masterRunOne) as well as from here - so a section the cloud watered
 * this morning is never watered again by the fallback. Kept in flash: a reset
 * must not forget it. */
void fallbackNoteWatered(const String& section) {
  if (!clockOK || section.length() == 0) return;
  fbLoad();
  int i = 0;
  while (i < fbLastN && fbLast[i].section != section) i++;
  if (i == fbLastN) {
    if (fbLastN >= FB_MAX_SECTIONS) return;
    fbLast[fbLastN++].section = section;
  }
  fbLast[i].at = fbNow();
  File f = LittleFS.open(FB_LAST_FILE, "w");
  if (!f) return;
  for (int j = 0; j < fbLastN; j++) f.printf("%s %ld\n", fbLast[j].section.c_str(), fbLast[j].at);
  f.close();
}

static bool fbCloudGone() {
  unsigned long since = fbCloudOkMs ? millis() - fbCloudOkMs : millis();
  bool silent = since > FB_SILENT_MS;
  bool engineQuiet = clockOK && fbBeatAt > 0 &&
                     (fbNow() - fbBeatAt) > (long)(FB_SILENT_MS / 1000UL);
  return silent || engineQuiet;
}

/* Upload the reports of offline waterings, oldest first. Any that fail stay. */
static void fbFlushReports() {
  if (WiFi.status() != WL_CONNECTED) return;
  File f = LittleFS.open(FB_PEND_FILE, "r");
  if (!f) return;
  String keep = "";
  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length() < 10) continue;
    JsonDocument d;
    if (deserializeJson(d, line)) continue;            // unreadable: nothing to send
    String id = String((const char*)(d["id"] | ""));
    if (id.length() == 0) continue;
    HTTPClient h;
    h.setTimeout(6000);
    h.begin(FARM + "/masters/" + macKey() + "/fallbackDone/" + id + ".json");
    h.addHeader("Content-Type", "application/json");
    int code = h.PUT(line);
    h.end();
    if (code == 200) fallbackNoteCloudOk();
    else keep += line + "\n";
  }
  f.close();
  if (keep.length() == 0) { LittleFS.remove(FB_PEND_FILE); return; }
  File w = LittleFS.open(FB_PEND_FILE, "w");
  if (w) { w.print(keep); w.close(); }
}

/* While online: the latest plan (kept in flash), the engine's beat, and any
 * reports still waiting. A board that is no master gets "null" for its plan and
 * looks again only every FB_IDLE_MS - each read is a TLS handshake of seconds,
 * and a sensor node has its own readings to take. */
void fallbackSync() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (fbLastSync != 0 && millis() - fbLastSync < fbSyncEvery) return;
  fbLastSync = millis();
  fbLoad();

  HTTPClient p;
  p.setTimeout(6000);
  p.begin(FARM + "/masters/" + macKey() + "/fallbackPlan.json");
  int code = p.GET();
  String body = (code == 200) ? p.getString() : "";
  p.end();
  if (code != 200) return;
  fallbackNoteCloudOk();
  if ((body.length() < 10 || body == "null") && fbPlan.length() == 0) {
    fbSyncEvery = FB_IDLE_MS;                          // not a master
    return;
  }
  fbSyncEvery = FB_SYNC_MS;
  if (body.length() >= 10 && body != "null" && body != fbPlan) {
    fbPlan = body;
    File f = LittleFS.open(FB_PLAN_FILE, "w");
    if (f) { f.print(body); f.close(); }
    Serial.println("[FALLBACK] new plan kept in case the cloud goes quiet");
  }

  HTTPClient b;
  b.setTimeout(6000);
  b.begin(FARM + "/engineBeat.json");
  code = b.GET();
  body = (code == 200) ? b.getString() : "";
  b.end();
  if (code == 200) {
    fallbackNoteCloudOk();
    long v = body.toInt();
    if (v > 1700000000L) fbBeatAt = v;
  }
  fbFlushReports();
}

static void fbWater(const String& house, const String& section, int ch, int secs,
                    long due, bool fromYesterday) {
  int pin = CHANNEL_PIN[ch];
  String id = "fb" + String(fbNow()) + "-" + section;
  Serial.printf("[FALLBACK] cloud gone - watering %s on channel %d for %ds, from %s plan\n",
                section.c_str(), ch, secs, fromYesterday ? "yesterday's" : "today's");
  if (WiFi.status() == WL_CONNECTED) masterRunning(id, section, ch, secs);

  unsigned long start = millis();
  digitalWrite(pin, RELAY_ON);
  bool stopped = false;
  const uint32_t totalMs = (uint32_t)secs * 1000UL;
  uint32_t lastCheck = start;
  while (millis() - start < totalMs) {
    delay(50);
    servePortal();
    // Stop still works whenever the database answers: it may be only the engine
    // that is down. Same budget rule as masterRunOne.
    if (WiFi.status() == WL_CONNECTED) {
      const uint32_t elapsed   = millis() - start;
      const uint32_t remaining = (elapsed >= totalMs) ? 0 : totalMs - elapsed;
      if (remaining > STOP_CHECK_BUDGET_MS && millis() - lastCheck >= STOP_POLL_MS) {
        lastCheck = millis();
        if (masterStopRequested(id)) { stopped = true; break; }
      }
    }
  }
  digitalWrite(pin, RELAY_OFF);
  int ran = (int)((millis() - start) / 1000UL);
  if (WiFi.status() == WL_CONNECTED) masterClearRunning();
  fallbackNoteWatered(section);
  Serial.printf("[FALLBACK] %s %s after %ds\n", section.c_str(), stopped ? "stopped" : "done", ran);

  String rep = "{\"id\":\"" + id + "\",\"house\":\"" + house +
               "\",\"targetSection\":\"" + section + "\",\"channel\":" + String(ch) +
               ",\"ranSec\":" + String(ran) +
               ",\"outcome\":\"" + String(stopped ? "stopped" : "done") + "\"" +
               ",\"at\":" + String(fbNow()) + ",\"dueSec\":" + String(due) +
               ",\"fromYesterday\":" + String(fromYesterday ? "true" : "false") +
               ",\"by\":\"" + macKey() + "\"}";
  File f = LittleFS.open(FB_PEND_FILE, "a");
  if (f) { f.println(rep); f.close(); }
  fbFlushReports();
}

/* Every FB_CHECK_MS, online or not: is a fallback watering due? One pour per
 * check; the next check takes the next section. */
void fallbackTick() {
  if (fbLastCheck != 0 && millis() - fbLastCheck < FB_CHECK_MS) return;
  fbLastCheck = millis();
  if (!clockOK) return;                       // no clock, no pour: the hour is unknown
  fbLoad();
  if (fbPlan.length() < 10 || !fbCloudGone()) return;

  JsonDocument doc;
  if (deserializeJson(doc, fbPlan)) return;
  long dayStart = doc["dayStartSec"] | 0L;
  long afterSec = (long)(doc["afterMin"] | 25) * 60L;
  long untilSec = (long)(doc["untilMin"] | 120) * 60L;

  FbEntry rows[FB_MAX_SECTIONS];
  String houses[FB_MAX_SECTIONS], sections[FB_MAX_SECTIONS];
  int n = 0;
  for (JsonPair kv : doc["entries"].as<JsonObject>()) {
    if (n >= FB_MAX_SECTIONS) break;
    JsonObject e = kv.value().as<JsonObject>();
    sections[n] = String((const char*)(e["section"] | ""));
    if (sections[n].length() == 0) continue;
    houses[n] = String((const char*)(e["house"] | ""));
    rows[n].due = e["dueSec"] | 0L;
    rows[n].secs = e["durationSec"] | 0L;
    rows[n].channel = e["channel"] | 0;
    rows[n].lastRun = fbLastRun(sections[n]);
    n++;
  }
  bool fromYesterday = false;
  int i = fbDecide(fbNow(), dayStart, afterSec, untilSec, rows, n, &fromYesterday);
  if (i < 0) return;
  long secs = rows[i].secs > MASTER_MAX_SEC ? MASTER_MAX_SEC : rows[i].secs;
  fbWater(houses[i], sections[i], rows[i].channel, (int)secs,
          rows[i].due + (fromYesterday ? 86400L : 0L), fromYesterday);
}
