/* Master controller: one ESP32, one relay board, many sections.
 *
 * A node normally waters only the section it is assigned to. A master also
 * drains a QUEUE of commands for sections that have no node of their own, and
 * opens the matching channel on its relay board for each.
 *
 * Drop this into sensor_node_validate.ino alongside the existing
 * pollCommand(). It does not replace it: the master is still a sensor node for
 * its own section, and that path is unchanged.
 *
 *   Firebase:  /farm/masters/{MAC}/queue/{id}   <- backend writes here
 *              /farm/masters/{MAC}/acks/{id}    <- this writes back
 *
 * Backend contract, from _issue_node_command():
 *   { "id", "action", "durationSec", "issuedAtSec",
 *     "targetSection": "S2", "channel": 3, "routedTo": "<this MAC>" }
 */

// ── Relay channels ───────────────────────────────────────────────────────────
// Channel number from the command maps to a pin here, so adding a section is a
// backend change and never a reflash. Index 0 is unused: the backend numbers
// channels from 1, matching how relay boards are silk-screened.
//
// D25 and D26 are the two the single-node build already uses, kept first so a
// board wired for that build still behaves. Avoid GPIO 6-11 (flash), 34-39
// (input only) and the strapping pins 0, 2, 12, 15.
const int CHANNEL_PIN[9] = { -1, 25, 26, 27, 14, 13, 4, 16, 17 };

// RELAY_ON / RELAY_OFF come from the host sketch, which already defines them
// for the SONGLE board (ACTIVE LOW). They are NOT redefined here on purpose:
// two definitions of relay polarity is one more than a project should have,
// and the first attempt at this file did redefine them, which expanded
// `const int RELAY_ON = LOW` into `const int LOW = 0x0` and failed to compile.

const unsigned long QUEUE_POLL_MS = 3000UL;
// The same ceiling the host sketch applies to its own pours, restated here
// because this path does not go through deliver(). Firmware is the last thing
// between a corrupted number and a pump.
const int MASTER_MAX_SEC = RELAY_MAX_SEC;
// A queued command that has sat unread is refused rather than obeyed. The
// single-node path learned this the hard way: a 20-hour-old command ran at
// boot and poured for ninety seconds unprompted.
const long MASTER_MAX_AGE_SEC = 900;

static unsigned long lastQueuePoll = 0;

void masterSetupRelays() {
  for (int ch = 1; ch <= 8; ch++) {
    int pin = CHANNEL_PIN[ch];
    if (pin < 0) continue;
    // Drive the pin OFF before pinMode, never after. A pin configured as an
    // output first floats for a few microseconds, and on an ACTIVE-LOW board a
    // float reads as ON - which is a valve opening at power-up.
    digitalWrite(pin, RELAY_OFF);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, RELAY_OFF);
  }
}

/* Report what actually happened, then delete the queue entry.
 *
 * Deleting is what stops a command being run twice: the entry is the only
 * record that it is outstanding. The ack is written FIRST so that a reset
 * between the two leaves evidence the pour happened, rather than a silently
 * empty queue.
 */
void masterAck(const String& id, const String& section, int channel,
               int ranSec, const char* outcome) {
  if (WiFi.status() != WL_CONNECTED) return;

  String body = "{\"id\":\"" + id + "\",\"targetSection\":\"" + section +
                "\",\"channel\":" + String(channel) +
                ",\"ranSec\":" + String(ranSec) +
                ",\"outcome\":\"" + String(outcome) + "\"" +
                ",\"by\":\"" + macKey() + "\"";
  if (clockOK) body += ",\"at\":" + String((long long)(nowMs() / 1000));
  body += "}";

  HTTPClient a;
  a.setTimeout(6000);
  a.begin(String(FB_HOST) + "/farm/masters/" + macKey() + "/acks/" + id + ".json");
  a.addHeader("Content-Type", "application/json");
  a.PUT(body);
  a.end();

  HTTPClient d;
  d.setTimeout(6000);
  d.begin(String(FB_HOST) + "/farm/masters/" + macKey() + "/queue/" + id + ".json");
  d.sendRequest("DELETE");
  d.end();
}

/* Run one queued command, start to finish.
 *
 * Deliberately blocking, and deliberately ONE at a time. The board has eight
 * channels but the farm has one pump: opening two valves together halves the
 * pressure at both, so a "parallel" pour would silently under-water two
 * sections instead of properly watering one. The queue is drained one entry
 * per poll for the same reason.
 */
void masterRunOne(const String& payload) {
  String id      = jsonStr(payload, "id");
  String action  = jsonStr(payload, "action");
  String section = jsonStr(payload, "targetSection");
  long   secs    = jsonNum(payload, "durationSec", 0);
  long   channel = jsonNum(payload, "channel", 0);
  long   issued  = jsonNum(payload, "issuedAtSec", 0);

  if (id.length() == 0 || channel < 1 || channel > 8) {
    Serial.printf("[MASTER] bad command (channel=%ld) - dropping\n", channel);
    masterAck(id, section, (int)channel, 0, "invalid");
    return;
  }
  if (action != "water" && action != "tray") {
    masterAck(id, section, (int)channel, 0, "unsupported");
    return;
  }
  if (issued > 0 && clockOK) {
    long age = (long)(nowMs() / 1000ULL) - issued;
    if (age > MASTER_MAX_AGE_SEC) {
      Serial.printf("[MASTER] %s issued %lds ago - too old to obey\n",
                    section.c_str(), age);
      masterAck(id, section, (int)channel, 0, "stale");
      return;
    }
  }
  if (secs <= 0) { masterAck(id, section, (int)channel, 0, "zero"); return; }
  if (secs > MASTER_MAX_SEC) {
    Serial.printf("[MASTER] %s asked %lds, clamped to %d\n",
                  section.c_str(), secs, MASTER_MAX_SEC);
    secs = MASTER_MAX_SEC;
  }

  int pin = CHANNEL_PIN[channel];
  Serial.printf("[MASTER] %s -> channel %ld (GPIO %d) for %lds\n",
                section.c_str(), channel, pin, secs);

  unsigned long start = millis();
  digitalWrite(pin, RELAY_ON);

  // Timed by the WALL CLOCK, not by summing sleeps. The single-node build had
  // this wrong: it added up its sleep slices and ignored the seconds each
  // HTTPS check took, so a 15-second command poured for 173.
  while (millis() - start < (unsigned long)secs * 1000UL) {
    servePortal();
    delay(50);
  }

  digitalWrite(pin, RELAY_OFF);
  int ran = (int)((millis() - start) / 1000UL);
  Serial.printf("[MASTER] %s done, %ds\n", section.c_str(), ran);
  masterAck(id, section, (int)channel, ran, "done");
}

/* Take the oldest outstanding command, if there is one.
 *
 * orderBy="$key" with limitToFirst=1 leans on the ids being written in the
 * order they were issued, and fetches ONE entry rather than the whole queue -
 * a queue that grows because a valve is stuck should not also grow the download
 * on every poll.
 */
void masterPollQueue() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (millis() - lastQueuePoll < QUEUE_POLL_MS) return;
  lastQueuePoll = millis();

  HTTPClient http;
  http.setTimeout(6000);
  http.begin(String(FB_HOST) + "/farm/masters/" + macKey() +
             "/queue.json?orderBy=%22$key%22&limitToFirst=1");
  int code = http.GET();
  String body = (code == 200) ? http.getString() : "";
  http.end();
  if (code != 200 || body.length() < 8 || body == "null") return;

  // Firebase returns { "<id>": { ... } }. The inner object is what runs.
  int open = body.indexOf('{', 1);
  int close = body.lastIndexOf('}');
  if (open < 0 || close <= open) return;
  masterRunOne(body.substring(open, close));
}

/* In setup():   masterSetupRelays();
 * In loop():    masterPollQueue();
 *
 * Place the call AFTER the existing pollCommand(), so this board keeps serving
 * its own section first and only then acts for the ones that have no node.
 */
