/* The offline fallback's decision, with no Arduino in it, so it can be checked
 * on a PC (firmware/fallback_test/test_decide.cpp). queue_fallback.ino turns
 * the cached plan into FbEntry rows and asks this which one, if any, to water.
 *
 * Times are epoch seconds. dayStart is local midnight of the day the plan was
 * made for. A plan one day old is used as yesterday's plan, moved to today
 * ("today's plan, else yesterday's"); anything older is never used.
 */
#pragma once

struct FbEntry {
  long due;        // the planned minute on the plan's own day, epoch s
  long secs;       // pour length, s
  int  channel;    // relay channel, 1..8
  long lastRun;    // when this section was last watered, epoch s (0 = never)
};

/* The index of the entry to water now, or -1.
 *   afterSec  how long past the planned minute the master waits first: longer
 *             than the engine's own late window, so the two never both pour
 *   untilSec  how long past it the master gives up
 *   *fromYesterday is set when a one-day-old plan was used */
static int fbDecide(long now, long dayStart, long afterSec, long untilSec,
                    const FbEntry* e, int n, bool* fromYesterday) {
  if (fromYesterday) *fromYesterday = false;
  if (dayStart <= 0 || now < dayStart || afterSec < 0 || untilSec <= afterSec) return -1;
  long k = (now - dayStart) / 86400L;          // 0 = today's plan, 1 = yesterday's
  if (k > 1) return -1;                        // older than yesterday: never
  long shift = k * 86400L;
  long todayStart = dayStart + shift;
  for (int i = 0; i < n; i++) {
    if (e[i].channel < 1 || e[i].channel > 8) continue;
    if (e[i].secs <= 0 || e[i].due <= 0) continue;
    long due = e[i].due + shift;
    if (now < due + afterSec || now > due + untilSec) continue;
    if (e[i].lastRun >= todayStart) continue;  // already watered today, by anyone
    if (fromYesterday) *fromYesterday = (k == 1);
    return i;
  }
  return -1;
}
