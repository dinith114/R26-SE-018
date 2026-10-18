/**
 * Metres and feet for house sizes and section positions.
 *
 * DELIBERATELY IMPORTS NOTHING, like deviceHealth.js, so it is tested in plain
 * Node (__tests__/lengthUnits.test.mjs).
 *
 * The server and the kriging keep METRES, always. Feet exist only on the
 * screen: what the farmer types is converted to metres before it is sent, and
 * metres are converted back for display. The farm measured its house as
 * 16 ft x 32 ft (17 Oct 2026), which is why feet are offered at all.
 */

export const M_PER_FT = 0.3048;
export const UNITS = ['m', 'ft'];

export const toMetres = (n, unit) => (unit === 'ft' ? n * M_PER_FT : n);
export const fromMetres = (m, unit) => (unit === 'ft' ? m / M_PER_FT : m);

const round = (n, d) => {
  const f = 10 ** d;
  return Math.round(n * f) / f;
};
// metres to the centimetre, feet to a tenth: what a tape measure gives
const DIGITS = { m: 2, ft: 1 };

/** "4.99 m" or "16.4 ft" for a length held in metres; '--' when unknown. */
export function formatLength(m, unit = 'm') {
  const n = Number(m);
  if (m == null || !Number.isFinite(n)) return '--';
  return `${round(fromMetres(n, unit), DIGITS[unit] ?? 2)} ${unit}`;
}

/** The text to put in an input box for a length held in metres. */
export function editText(m, unit = 'm') {
  const n = Number(m);
  if (m == null || m === '' || !Number.isFinite(n)) return '';
  return String(round(fromMetres(n, unit), DIGITS[unit] ?? 2));
}

/**
 * A typed length -> { m } (metres, to the centimetre) or { error }.
 * `min` and `max` are METRES; the error message speaks the farmer's unit.
 */
export function parseLength(text, unit = 'm', { min = 0, max = 500, what = 'This' } = {}) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (!t) return { error: `${what} is empty.` };
  if (!/^\d+(\.\d+)?$/.test(t)) return { error: `${what} must be a number, like 4.99.` };
  const m = round(toMetres(parseFloat(t), unit), 2);
  if (m < min || m > max) {
    const lo = round(fromMetres(min, unit), DIGITS[unit] ?? 2);
    const hi = round(fromMetres(max, unit), DIGITS[unit] ?? 2);
    return { error: `${what} must be between ${lo} and ${hi} ${unit}.` };
  }
  return { m };
}

/** Re-express a typed value when the farmer switches unit, so the box keeps
 *  meaning the same length. Unparseable text is left as typed. */
export function convertText(text, from, to) {
  if (from === to) return text;
  const t = String(text ?? '').trim().replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(t)) return text;
  return editText(toMetres(parseFloat(t), from), to);
}
