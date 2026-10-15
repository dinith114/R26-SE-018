/**
 * Which notifications a person has cleared, and which still show.
 *
 * DELIBERATELY IMPORTS NOTHING, like request.js and deviceHealth.js, so it is
 * tested in plain Node (__tests__/notifyRules.test.mjs).
 *
 * The server keeps no notification list: /alerts works out what to say from the
 * farm's state every time it is asked, and each item has an id that stays the
 * same while the condition lasts ("H1-S1-stale"). So clearing one cannot delete
 * anything. It records the item's key on this phone and hides it while it keeps
 * coming back.
 *
 *   - A problem (urgent, action, warning) is keyed by its id: cleared, it stays
 *     hidden for as long as the problem lasts, even as its wording changes
 *     ("no reading for 4 days", then 5).
 *   - An info item is keyed by id AND message: "Today's watering" has the same
 *     id every day, and clearing today's must not hide tomorrow's.
 *   - A key the server has not sent for FORGET_AFTER_MS is dropped. The problem
 *     went away, so if it comes back the farmer is told again. Two hours rather
 *     than at once, so one bad fetch (an empty list while Firebase hiccups) does
 *     not bring back everything that was cleared.
 *
 * `cleared` is a plain object: key -> the last time the server still sent it.
 */

export const FORGET_AFTER_MS = 2 * 3600000;

export function clearKey(a) {
  if (!a || !a.id) return null;
  return a.level === 'info' ? `${a.id}|${a.message || ''}` : String(a.id);
}

/** { shown, hidden }: the live list split by whether it was cleared. */
export function splitAlerts(alerts, cleared) {
  const c = cleared || {};
  const shown = [];
  const hidden = [];
  for (const a of alerts || []) {
    const k = clearKey(a);
    if (k && c[k] != null) hidden.push(a); else shown.push(a);
  }
  return { shown, hidden };
}

/** What the bell counts: problems not cleared. Info items are not problems. */
export function badgeCount(alerts, cleared) {
  return splitAlerts(alerts, cleared).shown.filter((a) => a.level !== 'info').length;
}

export function clearOne(cleared, a, now) {
  const k = clearKey(a);
  return k ? { ...(cleared || {}), [k]: now } : (cleared || {});
}

export function clearAll(cleared, alerts, now) {
  const next = { ...(cleared || {}) };
  for (const a of alerts || []) {
    const k = clearKey(a);
    if (k) next[k] = now;
  }
  return next;
}

export function restoreOne(cleared, a) {
  const k = clearKey(a);
  const next = { ...(cleared || {}) };
  if (k) delete next[k];
  return next;
}

/**
 * After a fetch: mark every cleared key the server still sent as seen now, and
 * forget keys it has not sent for FORGET_AFTER_MS. Returns the SAME object when
 * nothing changed beyond the timestamps of a quiet minute, so callers can skip
 * writing storage on every poll.
 */
export function refreshSeen(cleared, alerts, now) {
  const c = cleared || {};
  const live = new Set((alerts || []).map(clearKey).filter(Boolean));
  let changed = false;
  const next = {};
  for (const [k, seen] of Object.entries(c)) {
    if (live.has(k)) {
      next[k] = now;
      // Re-stamping is only worth a write once it moves the forget time a lot.
      if (now - seen > FORGET_AFTER_MS / 4) changed = true;
    } else if (now - seen <= FORGET_AFTER_MS) {
      next[k] = seen;
    } else {
      changed = true;                          // forgotten
    }
  }
  return changed ? next : c;
}
