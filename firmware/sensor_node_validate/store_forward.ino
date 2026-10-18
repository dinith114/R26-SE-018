/* ==== STORE AND FORWARD: readings survive a Wi-Fi outage ====================
 *
 * WHY. Until validation-2.3 a reading taken while the router was down was
 * simply lost: takeReading() posted only when WiFi.status() == WL_CONNECTED.
 * For the placement study that costs more than it looks. The analysis keeps
 * only the moments EVERY section saw (house_planner.py, "Only the moments every
 * section saw"), so one node missing ten minutes throws those ten minutes away
 * for all four.
 *
 * WHAT. A linked node with a synced clock that cannot upload (no Wi-Fi, or the
 * history POST failed) appends the reading to /buf.bin in LittleFS - flash, so
 * it survives a reboot or a battery brown-out. When uploads work again it sends
 * them oldest first, BUF_BATCH per HTTPS request, one request per loop pass so
 * the portal, commands and stop checks keep being served in between.
 *
 * KEYS. The backend reads history with orderBy="$key", finds a section's NEWEST
 * reading with limitToLast=1, and counts calibration readings by decoding the
 * time inside push-id keys (smart_care_v2._push_id_ms). A buffered reading
 * POSTed late would get a push id for its UPLOAD time: an hour-old reading
 * would sort as the newest, and be counted in the wrong window. So each one is
 * written with PATCH under a key built in push-id format from its OWN time -
 * 8 chars of epoch ms, then 12 chars derived from (MAC, time). Deterministic on
 * purpose: a batch that reached Firebase but whose reply was lost is sent again
 * under the SAME keys and overwrites itself instead of duplicating.
 *
 * POWER CUTS. The data file is append-only. What has been uploaded is recorded
 * as a sequence number in NVS ("orchidbuf"/"flushed"), never by editing the
 * file, and only AFTER Firebase accepts the batch - so a cut mid-upload costs
 * at worst one batch sent twice, which the keys make harmless. The file is
 * rewritten only to shed dead records, by writing a complete new file first and
 * then swapping it in; bufBegin() finishes or discards a swap that a cut
 * interrupted. LittleFS commits a write only on close, so a cut mid-append
 * loses that one reading, not the file.
 *
 * WHAT IT CANNOT DO. A reading taken before the clock has synced since boot has
 * no time, and a reading without a time cannot be placed in the analysis - it
 * would sort as 1970. The clock comes from an HTTP Date header (see syncClock),
 * so a board that RESTARTS while the router is down stores nothing until Wi-Fi
 * returns. Only a battery-backed RTC module would close that hole.
 */

static const char* BUF_FILE = "/buf.bin";
static const char* BUF_TMP  = "/buf.tmp";

/* Six days at the 60 s QUIET interval, 36 hours at 15 s. At 40 bytes a record
   that is 345 KB - under a quarter of the 1.375 MB "spiffs" partition in the
   default scheme, leaving room for the old and the new copy side by side while
   the file is rewritten. bufBegin() lowers it if the partition is smaller. */
const uint32_t BUF_MAX_RECORDS = 8640;
// When full, the oldest hour (at 60 s) goes in one step: one rewrite of the
// file per 60 readings instead of a 345 KB rewrite for every new one.
const uint32_t BUF_DROP_CHUNK  = 60;
// ~6 KB of JSON. Big enough that the TLS handshake - seconds on this chip - is
// paid once per 25 readings; small enough to build in one heap String.
const uint32_t BUF_BATCH       = 25;
// After a failed upload, leave the backlog alone this long - unless a live
// reading gets through first, which is proof uploads work and ends the wait.
const uint32_t BUF_RETRY_MS    = 60000UL;

#define BUF_FNV32_INIT 2166136261u

static bool     bufReady      = false;
static uint32_t bufCap        = BUF_MAX_RECORDS;
static uint32_t bufCount      = 0;   // records physically in the file
static uint32_t bufDead       = 0;   // leading records already uploaded or dropped
static uint32_t bufFlushedSeq = 0;   // highest seq uploaded or dropped (kept in NVS)
static uint32_t bufNextSeq    = 1;
static uint32_t bufRetryAt    = 0;   // millis() to retry after; 0 = no back-off
static bool     bufFlushing   = false;
static Preferences bufPrefs;

static uint32_t bufLive() { return bufCount - bufDead; }

// No default arguments anywhere in this file: Arduino copies them into the
// prototype it generates, and a default given twice does not compile.
static uint32_t bufFnv(const void* data, size_t n, uint32_t h) {
  const uint8_t* p = (const uint8_t*)data;
  while (n--) { h ^= *p++; h *= 16777619u; }
  return h;
}

static uint32_t bufCheck(const BufRec& r) {
  return bufFnv(&r, offsetof(BufRec, check), BUF_FNV32_INIT);
}

static bool bufValid(const BufRec& r) {
  return r.ver == BUF_REC_VER && r.seq != 0 && r.ms > 1700000000000ULL &&
         r.check == bufCheck(r);
}

/* Which section a record belongs to, as a hash. TENANT_ID is in it because
   LittleFS outlives a reflash: a board reflashed for another farm must not
   deliver this farm's readings to a same-named section over there. */
static uint32_t bufSectionHash() {
  String s = String(TENANT_ID) + "/" + assignedHouse + "/" + assignedSection;
  return bufFnv(s.c_str(), s.length(), BUF_FNV32_INIT);
}

/* "12 min ago" when the clock is set, a UTC time when it is not (at boot,
   before Wi-Fi). UTC is local Sri Lanka time minus 5:30. */
static String bufWhen(uint64_t ms) {
  char b[32];
  uint64_t now = nowMs();
  if (now && now >= ms) {
    uint32_t mins = (uint32_t)((now - ms) / 60000ULL);
    if (mins < 120)       snprintf(b, sizeof b, "%lu min ago", (unsigned long)mins);
    else if (mins < 2880) snprintf(b, sizeof b, "%.1f h ago", mins / 60.0);
    else                  snprintf(b, sizeof b, "%.1f days ago", mins / 1440.0);
  } else {
    time_t s = (time_t)(ms / 1000ULL);
    struct tm t;
    gmtime_r(&s, &t);
    strftime(b, sizeof b, "%Y-%m-%d %H:%M UTC", &t);
  }
  return String(b);
}

static void bufSavePointer(uint32_t seq) {
  bufFlushedSeq = seq;
  bufPrefs.begin("orchidbuf", false);
  bufPrefs.putUInt("flushed", seq);
  bufPrefs.end();
}

static bool bufReadAt(uint32_t index, BufRec& r) {
  File f = LittleFS.open(BUF_FILE, "r");
  if (!f) return false;
  bool ok = f.seek(index * (uint32_t)sizeof(BufRec)) &&
            f.read((uint8_t*)&r, sizeof r) == sizeof r;
  f.close();
  return ok;
}

/* Rewrite the file keeping only good records still waiting, oldest first.

   The new file is written IN FULL and closed before the old one is removed.
   A power cut therefore leaves either the old file plus a half-written tmp
   (bufBegin deletes the tmp) or a complete tmp and no old file (bufBegin
   renames it into place) - never neither. */
static bool bufCompact(const char* why) {
  if (!LittleFS.exists(BUF_FILE)) { bufCount = bufDead = 0; return true; }
  File in = LittleFS.open(BUF_FILE, "r");
  if (!in) return false;
  File out = LittleFS.open(BUF_TMP, "w");
  if (!out) {
    in.close();
    Serial.println("[BUF] compaction could not create a new file - kept the old one");
    return false;
  }
  uint32_t n = in.size() / sizeof(BufRec), kept = 0, bad = 0;
  uint32_t lastSeq = bufFlushedSeq;
  bool ok = true;
  BufRec r;
  for (uint32_t i = 0; i < n; i++) {
    if (in.read((uint8_t*)&r, sizeof r) != sizeof r) break;
    if (!bufValid(r)) { bad++; continue; }
    if (r.seq <= lastSeq) continue;              // uploaded, dropped, or out of order
    if (out.write((const uint8_t*)&r, sizeof r) != sizeof r) { ok = false; break; }
    lastSeq = r.seq;
    kept++;
  }
  in.close();
  out.close();
  if (!ok) {
    LittleFS.remove(BUF_TMP);
    Serial.println("[BUF] compaction failed writing flash - kept the old file");
    return false;
  }
  LittleFS.remove(BUF_FILE);
  if (kept == 0) {
    LittleFS.remove(BUF_TMP);
  } else if (!LittleFS.rename(BUF_TMP, BUF_FILE)) {
    // The readings are safe in BUF_TMP and bufBegin() adopts it at the next
    // restart. Appending to a fresh BUF_FILE now would make the two files look
    // like an interrupted rewrite and the tmp would be thrown away, so stop
    // buffering for the rest of this boot instead.
    Serial.println("[BUF] could not rename the compacted file - buffering OFF until restart");
    bufReady = false;
    return false;
  }
  bufCount = kept;
  bufDead  = 0;
  if (bad) Serial.printf("[BUF] dropped %lu damaged records while compacting\n", (unsigned long)bad);
  Serial.printf("[BUF] file compacted (%s): %lu waiting\n", why, (unsigned long)kept);
  return true;
}

/* Rebuild the RAM picture from flash: how many records, how many at the front
   are already uploaded, what seq comes next. Anything odd - a damaged record, a
   torn tail, records out of order - is repaired by compacting, which keeps only
   good records still waiting. */
static void bufScan() {
  bufCount = bufDead = 0;
  uint32_t maxSeq = 0;
  bool messy = false;
  if (LittleFS.exists(BUF_FILE)) {
    File f = LittleFS.open(BUF_FILE, "r");
    if (f) {
      size_t size = f.size();
      uint32_t n = size / sizeof(BufRec);
      messy = (size % sizeof(BufRec)) != 0;
      bool inPrefix = true;
      BufRec r;
      for (uint32_t i = 0; i < n; i++) {
        if (f.read((uint8_t*)&r, sizeof r) != sizeof r) { messy = true; break; }
        if (!bufValid(r) || r.seq <= maxSeq) { messy = true; continue; }
        maxSeq = r.seq;
        if (r.seq <= bufFlushedSeq) {
          if (inPrefix) bufDead++; else messy = true;
        } else {
          inPrefix = false;
        }
        bufCount++;
      }
      f.close();
    }
  }
  bufNextSeq = (maxSeq > bufFlushedSeq ? maxSeq : bufFlushedSeq) + 1;
  if (messy) {
    bufCompact("repairing after a restart");
  } else if (bufCount && bufDead == bufCount) {
    LittleFS.remove(BUF_FILE);                   // everything in it was uploaded
    bufCount = bufDead = 0;
  }
}

bool bufBegin() {
  if (!LittleFS.begin(false)) {
    Serial.println("[BUF] no filesystem on flash yet - formatting (first boot on this firmware)");
    if (!LittleFS.begin(true)) {
      Serial.println("[BUF] flash storage UNAVAILABLE - readings taken without Wi-Fi will be lost");
      return false;
    }
  }
  uint32_t fit = (uint32_t)(LittleFS.totalBytes() / 4 / sizeof(BufRec));
  bufCap = fit < BUF_MAX_RECORDS ? fit : BUF_MAX_RECORDS;
  if (bufCap < BUF_DROP_CHUNK * 2) {
    Serial.printf("[BUF] flash partition too small (%u bytes) - buffering OFF\n",
                  (unsigned)LittleFS.totalBytes());
    return false;
  }

  bufPrefs.begin("orchidbuf", false);
  bufFlushedSeq = bufPrefs.getUInt("flushed", 0);
  bufPrefs.end();

  // Finish, or throw away, a rewrite that a power cut interrupted.
  bool hasFile = LittleFS.exists(BUF_FILE), hasTmp = LittleFS.exists(BUF_TMP);
  if (hasTmp && hasFile) {
    LittleFS.remove(BUF_TMP);
    Serial.println("[BUF] discarded a half-written rewrite (power cut) - original intact");
  } else if (hasTmp) {
    LittleFS.rename(BUF_TMP, BUF_FILE);
    Serial.println("[BUF] completed a rewrite that a power cut interrupted");
  }

  // Ready BEFORE the scan, so a repair whose rename fails can switch it off.
  bufReady = true;
  bufScan();
  if (!bufReady) return false;
  if (bufLive()) {
    BufRec oldest;
    String when = bufReadAt(bufDead, oldest) ? bufWhen(oldest.ms) : String("?");
    Serial.printf("[BUF] %lu readings waiting from before the restart (oldest %s);"
                  " room for %lu\n", (unsigned long)bufLive(), when.c_str(),
                  (unsigned long)bufCap);
  } else {
    Serial.printf("[BUF] ready, nothing waiting; holds up to %lu readings"
                  " (%.1f days at 60 s)\n", (unsigned long)bufCap, bufCap / 1440.0);
  }
  return true;
}

/* Called after every live upload attempt by a linked board. Success ends any
   back-off, so the backlog starts going up on the very next loop pass. Failure
   starts one, so a network that is up but not reaching Firebase (a captive
   portal, a router with no internet) is not hit with a doomed batch every pass. */
void bufNoteUpload(bool ok) {
  if (ok) {
    bufRetryAt = 0;
  } else {
    bufRetryAt = millis() + BUF_RETRY_MS;
    if (bufRetryAt == 0) bufRetryAt = 1;
  }
}

static int32_t bufScaled(double v, double k) {
  if (isnan(v) || isinf(v)) v = SENTINEL;
  return (int32_t)lround(v * k);
}

/* Keep a reading the live path could not deliver. `d` is the exact document
   takeReading() built, so what is stored is what would have been sent. */
void bufStore(JsonDocument& d, const char* why) {
  static bool saidNoClock = false, saidNoFlash = false;
  if (!bufReady) {
    if (!saidNoFlash) {
      Serial.println("[BUF] flash storage unavailable - this reading and any more"
                     " without Wi-Fi are LOST");
      saidNoFlash = true;
    }
    return;
  }
  uint64_t ms = d["timestamp"].as<uint64_t>();
  if (ms == 0) {
    if (!saidNoClock) {
      Serial.println("[BUF] clock not set since this restart - a reading with no time"
                     " cannot be placed, so readings are NOT stored until Wi-Fi returns");
      saidNoClock = true;
    }
    return;
  }

  // Full: the OLDEST go, an hour's worth at a time, and the log says so.
  if (bufLive() >= bufCap) {
    uint32_t drop = bufLive() < BUF_DROP_CHUNK ? bufLive() : BUF_DROP_CHUNK;
    BufRec first, last;
    if (bufReadAt(bufDead, first) && bufReadAt(bufDead + drop - 1, last)) {
      bufSavePointer(last.seq);
      bufDead += drop;
      Serial.printf("[BUF] FULL (%lu readings) - dropped the %lu oldest, from %s\n",
                    (unsigned long)bufCap, (unsigned long)drop, bufWhen(first.ms).c_str());
    }
  }
  if (bufCount >= bufCap && bufDead > 0) bufCompact("making room");
  if (!bufReady || bufCount >= bufCap) {
    Serial.println("[BUF] full and could not make room - this reading is LOST");
    return;
  }

  BufRec r;
  memset(&r, 0, sizeof r);
  r.ms      = ms;
  r.seq     = bufNextSeq;
  r.sect    = bufSectionHash();
  r.t10     = (int16_t)bufScaled(d["temperature"].as<double>(), 10.0);
  r.rh10    = (int16_t)bufScaled(d["humidity"].as<double>(), 10.0);
  r.lux     = bufScaled(d["light"].as<double>(), 1.0);
  r.vpd1000 = bufScaled(d["vpd"].as<double>(), 1000.0);
  r.flags   = d["sensorFault"].as<bool>() ? 1 : 0;
  r.ver     = BUF_REC_VER;
  r.check   = bufCheck(r);

  File f = LittleFS.open(BUF_FILE, "a");
  size_t w = f ? f.write((const uint8_t*)&r, sizeof r) : 0;
  if (f) f.close();
  if (w != sizeof r) {
    Serial.println("[BUF] flash write FAILED - this reading is LOST");
    bufScan();                    // a torn tail would misalign every later record
    return;
  }
  bufNextSeq++;
  bufCount++;
  Serial.printf("[BUF] stored 1 (total %lu waiting) - %s\n", (unsigned long)bufLive(), why);
}

static const char BUF_PUSH_CHARS[] =
  "-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz";

static uint64_t bufMix64(uint64_t x) {           // splitmix64 finaliser
  x += 0x9E3779B97F4A7C15ULL;
  x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
  x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
  return x ^ (x >> 31);
}

/* A Firebase push id for a reading taken at `ms`, written into out[0..20].
   First 8 chars: ms in the push alphabet, most significant first - the same
   encoding the server uses and smart_care_v2._push_id_ms decodes, so the key
   sorts by READING time among real push ids. Last 12: a hash of (MAC, ms) in
   place of the server's random bits, so the same reading always gets the same
   key and a resend overwrites instead of duplicating. */
static void bufKey(uint64_t ms, char* out) {
  uint64_t t = ms;
  for (int i = 7; i >= 0; i--) { out[i] = BUF_PUSH_CHARS[t & 63]; t >>= 6; }
  String mac = macKey();
  uint64_t h = 1469598103934665603ULL;          // FNV-1a 64 over MAC, then ms
  for (size_t i = 0; i < mac.length(); i++) { h ^= (uint8_t)mac[i]; h *= 1099511628211ULL; }
  for (int i = 0; i < 8; i++) { h ^= (uint8_t)(ms >> (8 * i)); h *= 1099511628211ULL; }
  uint64_t a = bufMix64(h), b = bufMix64(a);
  for (int i = 0; i < 10; i++) { out[8 + i]  = BUF_PUSH_CHARS[a & 63]; a >>= 6; }
  for (int i = 0; i < 2; i++)  { out[18 + i] = BUF_PUSH_CHARS[b & 63]; b >>= 6; }
  out[20] = 0;
}

/* Send ONE batch of the backlog, if there is one and uploads are working.

   One batch per call, and loop() calls this once per pass: a day's backlog at
   60 s is ~58 batches of several seconds each, and doing them back to back
   would leave the setup portal, Stop and Identify unanswered for minutes.

   Records for a section this board is no longer assigned to are DROPPED and
   logged, never written to the current one - a reading from S2 filed under S5
   would put a false temperature on the map. Never written to latest either:
   latest is "now", and these are not. */
void bufFlushStep() {
  if (!bufReady || bufLive() == 0) return;
  if (!isClaimed || WiFi.status() != WL_CONNECTED) return;
  if (bufRetryAt && (int32_t)(millis() - bufRetryAt) < 0) return;
  bufRetryAt = 0;

  if (!bufFlushing) {
    bufFlushing = true;
    Serial.printf("[BUF] flushing %lu buffered readings to %s/%s, oldest first,"
                  " %lu per request\n", (unsigned long)bufLive(),
                  assignedHouse.c_str(), assignedSection.c_str(),
                  (unsigned long)BUF_BATCH);
  }

  File f = LittleFS.open(BUF_FILE, "r");
  if (!f || !f.seek(bufDead * (uint32_t)sizeof(BufRec))) {
    if (f) f.close();
    Serial.println("[BUF] buffer file unreadable - rescanning it");
    bufScan();
    return;
  }

  const uint32_t mine = bufSectionHash();
  String body;
  body.reserve(BUF_BATCH * 240);
  body = "{";
  uint32_t taken = 0, sent = 0, foreign = 0, bad = 0, lastSeq = bufFlushedSeq;
  uint64_t firstMs = 0;
  BufRec r;
  while (taken < BUF_BATCH && bufDead + taken < bufCount) {
    if (f.read((uint8_t*)&r, sizeof r) != sizeof r) break;
    taken++;
    if (!bufValid(r)) { bad++; continue; }
    lastSeq = r.seq;
    if (r.sect != mine) { foreign++; continue; }
    if (!firstMs) firstMs = r.ms;

    // Same fields, same order, same rounding as takeReading() - plus
    // "buffered", so anyone reading the archive can tell these arrived late.
    JsonDocument d;
    d["temperature"]    = r.t10 / 10.0;
    d["humidity"]       = r.rh10 / 10.0;
    d["light"]          = (float)r.lux;
    d["vpd"]            = r.vpd1000 / 1000.0;
    d["timestamp"]      = r.ms;
    d["sensorFault"]    = (r.flags & 1) != 0;
    d["node"]           = "validation";
    d["buffered"]       = true;
    String one;
    serializeJson(d, one);
    char key[21];
    bufKey(r.ms, key);
    if (sent) body += ",";
    body += "\"";
    body += key;
    body += "\":";
    body += one;
    sent++;
  }
  f.close();
  body += "}";

  if (taken == 0) {
    Serial.println("[BUF] buffer file shorter than expected - rescanning it");
    bufScan();
    return;
  }

  if (sent) {
    // PATCH writes every key in one request, and Firebase applies it whole or
    // not at all. print=silent: the reply would otherwise echo all ~6 KB back.
    HTTPClient http;
    http.setTimeout(15000);
    http.begin(HIST + ".json?print=silent");
    http.addHeader("Content-Type", "application/json");
    int code = http.PATCH(body);
    http.end();
    if (code != 200 && code != 204) {
      bufNoteUpload(false);
      Serial.printf("[BUF] upload of %lu FAILED (HTTP %d) - %lu still waiting,"
                    " retry in %lus\n", (unsigned long)sent, code,
                    (unsigned long)bufLive(), (unsigned long)(BUF_RETRY_MS / 1000));
      return;
    }
  }

  // Only now, with Firebase's yes in hand, is the batch marked done.
  bufSavePointer(lastSeq);
  bufDead += taken;
  if (foreign)
    Serial.printf("[BUF] dropped %lu recorded for a different section (board is now"
                  " %s/%s) - NOT written anywhere\n", (unsigned long)foreign,
                  assignedHouse.c_str(), assignedSection.c_str());
  if (bad)
    Serial.printf("[BUF] dropped %lu damaged records\n", (unsigned long)bad);
  if (sent)
    Serial.printf("[BUF] uploaded %lu (oldest taken %s) - %lu left\n",
                  (unsigned long)sent, bufWhen(firstMs).c_str(), (unsigned long)bufLive());

  if (bufLive() == 0) {
    LittleFS.remove(BUF_FILE);
    bufCount = bufDead = 0;
    bufFlushing = false;
    Serial.println("[BUF] all buffered readings uploaded - buffer emptied");
  }
}
