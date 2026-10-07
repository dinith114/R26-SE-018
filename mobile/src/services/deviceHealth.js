/**
 * Reading the hardware health checks for the screens.
 *
 * DELIBERATELY IMPORTS NOTHING, like request.js and placementFlow.js, so it is
 * tested in plain Node (__tests__/deviceHealth.test.mjs). The checks themselves
 * run on the server (backend app/services/device_health.py); this only turns
 * the response into what a screen shows, and never invents an all-clear.
 */

/** The issues standing for one section, oldest first. Junk entries dropped. */
export function sectionIssues(health, sectionId) {
  const list = (((health || {}).sections) || {})[sectionId];
  if (!Array.isArray(list)) return [];
  return list
    .filter((i) => i && typeof i.title === 'string' && typeof i.message === 'string')
    .sort((a, b) => (Number(a.sinceMs) || 0) - (Number(b.sinceMs) || 0));
}

/** How many sections of the house have at least one issue. */
export function sectionsWithIssues(health) {
  const secs = ((health || {}).sections) || {};
  return Object.keys(secs).filter((sid) => sectionIssues(health, sid).length > 0).length;
}

/**
 * Have the checks run since the server last started? Until they have, "no
 * issues" means "not looked yet", and a screen must say so rather than show
 * a green tick it has not earned.
 */
export function checksStarted(health) {
  return Number.isFinite((health || {}).checkedAtMs);
}

/** "14:20" in farm time (UTC+5:30), whatever the phone's clock is set to. */
export function farmClock(ms) {
  if (!Number.isFinite(ms)) return '';
  const d = new Date(ms + 330 * 60000);
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
}
