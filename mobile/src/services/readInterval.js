/**
 * How often a node reads: the choices, any custom value, and how to say it.
 *
 * DELIBERATELY IMPORTS NOTHING, like deviceHealth.js, so it is tested in plain
 * Node (__tests__/readInterval.test.mjs).
 *
 * The limits are the firmware's (sensor_node_validate.ino READ_INTERVAL_MIN_MS
 * and READ_INTERVAL_MAX_MS) and the server's clamp (devices.py): a node never
 * reads faster than every 5 s or slower than every hour, whatever is asked.
 * Until 17 Oct 2026 the app offered four fixed values with "Demo", "Bench",
 * "Normal" and "Production" under them; the farmer asked for any value.
 */

export const READ_MIN_MS = 5000;
export const READ_MAX_MS = 3600000;

/** The quick choices. Anything else is a custom value. */
export const READ_PRESETS = [15000, 30000, 60000, 300000, 900000, 1800000];

export const isPreset = (ms) => READ_PRESETS.includes(Number(ms));

/** "15 s", "1 min", "1 min 30 s", "1 h". */
export function formatInterval(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return '--';
  const total = Math.round(n / 1000);
  if (total < 60) return `${total} s`;
  if (total === 3600) return '1 h';
  const m = Math.floor(total / 60);
  const s = total % 60;
  return s ? `${m} min ${s} s` : `${m} min`;
}

/** "every 15 s" — how the interval reads in a sentence. */
export const intervalSentence = (ms) => {
  const f = formatInterval(ms);
  return f === '--' ? '--' : `every ${f}`;
};

/**
 * A typed custom value -> { ms } or { error }. `unit` is 's' or 'min'.
 * Minutes may have a decimal ("1.5"); the result is whole seconds.
 */
export function parseCustom(text, unit) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (!t) return { error: 'Type how long to wait between readings.' };
  if (!/^\d+(\.\d+)?$/.test(t)) return { error: 'Use a number, like 90 or 2.5.' };
  const n = parseFloat(t);
  const ms = Math.round(n * (unit === 'min' ? 60 : 1)) * 1000;
  if (ms < READ_MIN_MS) return { error: 'The shortest a node can do is 5 seconds.' };
  if (ms > READ_MAX_MS) return { error: 'The longest is 60 minutes.' };
  return { ms };
}

/** Prefill for the custom box: whole minutes as minutes, anything else in seconds. */
export function splitForEdit(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return { text: '', unit: 'min' };
  const s = Math.round(n / 1000);
  return s % 60 === 0 ? { text: String(s / 60), unit: 'min' } : { text: String(s), unit: 's' };
}
