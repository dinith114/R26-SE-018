/**
 * Pour lengths: how long a watering or a tray fill runs.
 *
 * Since 19 Oct 2026 every length is the grower's - a farm default in Settings
 * (10 minutes unless changed) and each section's own Pour length - and the
 * farmer picks a length each time they water or fill by hand. There is no
 * length model any more. The server allows 1 second to 1 hour; a master on
 * firmware before validation-2.9 still stops at 2 minutes, and the server says
 * so (pourLimit), which is what limitNote() puts into words.
 *
 * Pure functions, no React Native, so node --test can run them.
 */

export const DEFAULT_POUR_SEC = 600;
export const MAX_POUR_SEC = 3600;
export const POUR_PRESETS = [60, 300, 600, 900, 1800];

/** 600 -> "10 min", 90 -> "1 min 30 s", 45 -> "45 s". */
export function pourLabel(secs) {
  const s = Math.max(0, Math.round(Number(secs) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (!m) return `${r} s`;
  return r ? `${m} min ${r} s` : `${m} min`;
}

/** A live countdown: 598 -> "9:58", 45 -> "45 s". */
export function countdown(secs) {
  const s = Math.max(0, Math.round(Number(secs) || 0));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** 630 -> { min: 10, sec: 30 } */
export function splitSecs(secs) {
  const s = Math.max(0, Math.round(Number(secs) || 0));
  return { min: Math.floor(s / 60), sec: s % 60 };
}

/**
 * Minutes and seconds as typed, to a length in seconds, or null when it is not
 * a usable length. Blank boxes count as 0; "10" minutes and "" seconds is 600.
 */
export function joinSecs(min, sec) {
  const read = (v) => {
    const t = String(v ?? '').trim();
    if (!t) return 0;
    if (!/^\d+$/.test(t)) return NaN;
    return parseInt(t, 10);
  };
  const m = read(min);
  const s = read(sec);
  if (Number.isNaN(m) || Number.isNaN(s)) return null;
  const total = m * 60 + s;
  return total >= 1 && total <= MAX_POUR_SEC ? total : null;
}

/** Keep a length inside 1 second to 1 hour. */
export function clampPour(secs) {
  const s = Math.round(Number(secs) || 0);
  return Math.min(MAX_POUR_SEC, Math.max(1, s));
}

/** One step of the minus and plus buttons: 10 s below 2 minutes, 1 minute above. */
export function stepPour(secs, dir) {
  const s = clampPour(secs);
  const step = (dir > 0 ? s : s - 1) >= 120 ? 60 : 10;
  return clampPour(s + dir * step);
}

/** "About 180 L" from a length and a flow rate in ml per second, or null. */
export function litresLabel(secs, mlPerSec) {
  const rate = Number(mlPerSec);
  if (!rate || rate <= 0) return null;
  const l = (Math.max(0, Number(secs) || 0) * rate) / 1000;
  return `about ${l >= 10 ? Math.round(l) : l.toFixed(1)} L`;
}

/**
 * What the farmer must be told when the master cannot run this long, or null.
 * `limit` is the server's { maxSec, reason }.
 */
export function limitNote(secs, limit) {
  const max = Number(limit?.maxSec);
  if (!max || !(Number(secs) > max)) return null;
  const why = limit?.reason ? ` ${limit.reason}` : '';
  return `This house's master controller will stop after ${pourLabel(max)}.${why}`;
}
