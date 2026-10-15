/**
 * Date ranges and day grouping for the History tab.
 *
 * DELIBERATELY IMPORTS NOTHING, like request.js and deviceHealth.js, so it is
 * tested in plain Node (__tests__/historyRange.test.mjs).
 *
 * Every date here is a FARM date (UTC+5:30), whatever the phone's clock or
 * timezone says. "Yesterday" is the farm's yesterday, and a picked day runs from
 * the farm's midnight to the next one. The server labels every item with its
 * farm time ("2026-10-14 06:42:10"), so the timeline never converts times
 * itself; only the range sent to the server is computed here.
 */

export const FARM_OFFSET_MS = 330 * 60000;
const DAY_MS = 86400000;

/** Range choices. `kind` says how the window is worked out from now. */
export const HISTORY_PRESETS = [
  { key: 'h6',  kind: 'last', hours: 6,   label: 'Last 6 hours' },
  { key: 'h24', kind: 'last', hours: 24,  label: 'Last 24 hours' },
  { key: 'today',     kind: 'today',      label: 'Today' },
  { key: 'yesterday', kind: 'yesterday',  label: 'Yesterday' },
  { key: 'h72', kind: 'last', hours: 72,  label: 'Last 3 days' },
  { key: 'h168', kind: 'last', hours: 168, label: 'Last 7 days' },
];

/** The server keeps 31 days to a chart and 8 days to an export file. */
export const MAX_RANGE_DAYS = 31;
export const MAX_EXPORT_DAYS = 8;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const pad = (n) => String(n).padStart(2, '0');

/** "2026-10-14" for the farm date that `ms` falls on. */
export function farmDate(ms) {
  const d = new Date(ms + FARM_OFFSET_MS);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** Epoch ms of the farm's midnight starting "2026-10-14". */
export function farmMidnight(ymd) {
  const [y, m, d] = String(ymd).split('-').map(Number);
  return Date.UTC(y, m - 1, d) - FARM_OFFSET_MS;
}

/** "2026-10-14" moved by `days`. */
export function addDays(ymd, days) {
  const [y, m, d] = String(ymd).split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** "Tue 14 Oct" for "2026-10-14". */
export function dayTitle(ymd) {
  const [y, m, d] = String(ymd).split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d));
  return `${WEEKDAYS[t.getUTCDay()]} ${d} ${MONTHS[m - 1]}`;
}

/** "14 Oct 06:42" in farm time. */
export function farmStamp(ms) {
  const d = new Date(ms + FARM_OFFSET_MS);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/**
 * The window a range choice stands for, at `now`:
 * { start, end, label, live }. `live` is true when the window ends at now, so
 * the chart is worth refreshing while the screen is open.
 * A custom choice carries { from, to } as farm dates; its last day ends at the
 * farm's next midnight, or now if that is still to come.
 */
export function rangeWindow(choice, now) {
  const c = choice || HISTORY_PRESETS[1];
  const today = farmDate(now);
  if (c.kind === 'today') {
    return { start: farmMidnight(today), end: now, label: c.label, live: true };
  }
  if (c.kind === 'yesterday') {
    const y = addDays(today, -1);
    return { start: farmMidnight(y), end: farmMidnight(today) - 1, label: c.label, live: false };
  }
  if (c.kind === 'custom' && c.from && c.to) {
    const [from, to] = c.from <= c.to ? [c.from, c.to] : [c.to, c.from];
    const end = Math.min(farmMidnight(addDays(to, 1)) - 1, now);
    return { start: farmMidnight(from), end, label: customLabel(from, to), live: end === now };
  }
  const hours = Number(c.hours) || 24;
  return { start: now - hours * 3600000, end: now, label: c.label, live: true };
}

/** "14 Oct" or "10 Oct - 14 Oct". */
export function customLabel(from, to) {
  const one = (ymd) => { const [, m, d] = ymd.split('-').map(Number); return `${d} ${MONTHS[m - 1]}`; };
  return from === to ? one(from) : `${one(from)} - ${one(to)}`;
}

/** How many points the chart asks for: enough to show a day's shape, few
 *  enough that a week stays one small download. */
export function chartPoints(spanMs) {
  const h = spanMs / 3600000;
  if (h <= 8) return 36;
  if (h <= 26) return 48;
  if (h <= 80) return 60;
  return 72;
}

/** Whole days a window spans, rounded up (a day and a minute is two). */
export function spanDays(win) {
  return Math.ceil((win.end - win.start + 1) / DAY_MS);
}

/** The type filter chips and what each asks the server for. */
export const HISTORY_TYPES = [
  { key: 'all',     label: 'All',      types: 'reading,water,feed,tray' },
  { key: 'reading', label: 'Readings', types: 'reading' },
  { key: 'water',   label: 'Watering', types: 'water' },
  { key: 'feed',    label: 'Food',     types: 'feed' },
  { key: 'tray',    label: 'Tray',     types: 'tray' },
];

export function typesFor(key) {
  return (HISTORY_TYPES.find((t) => t.key === key) || HISTORY_TYPES[0]).types;
}

/**
 * Timeline items (newest first, each with a farm-time `local`) grouped into
 * days: [{ day: '2026-10-14', title: 'Tue 14 Oct', items }]. Order is kept.
 */
export function groupByDay(items) {
  const out = [];
  for (const it of items || []) {
    if (!it || typeof it.local !== 'string') continue;
    const day = it.local.slice(0, 10);
    const last = out[out.length - 1];
    if (last && last.day === day) last.items.push(it);
    else out.push({ day, title: dayTitle(day), items: [it] });
  }
  return out;
}

/** "06:42:10" out of "2026-10-14 06:42:10". */
export function clockOf(item) {
  return typeof item?.local === 'string' ? item.local.slice(11, 19) : '';
}

/**
 * The days of one month laid out Sunday-first for a calendar, as weeks of seven
 * cells. A cell is "2026-10-14" or null (padding before the 1st / after the end).
 */
export function monthGrid(year, month /* 1-12 */) {
  const first = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const cells = Array(first).fill(null);
  for (let d = 1; d <= days; d++) cells.push(`${year}-${pad(month)}-${pad(d)}`);
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

export function monthTitle(year, month) {
  const full = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December'];
  return `${full[month - 1]} ${year}`;
}

/**
 * The next state of a two-tap range pick. The first tap sets both ends; the
 * second sets the other end (either side). A third tap starts again.
 * Days after `today` are not pickable, and the range is held to MAX_RANGE_DAYS.
 */
export function pickDay(sel, ymd, today) {
  if (ymd > today) return sel;
  if (!sel || !sel.from || sel.done) return { from: ymd, to: ymd, done: false };
  const [from, to] = ymd < sel.from ? [ymd, sel.from] : [sel.from, ymd];
  const days = (farmMidnight(to) - farmMidnight(from)) / DAY_MS + 1;
  if (days > MAX_RANGE_DAYS) return { from: ymd, to: ymd, done: false };
  return { from, to, done: true };
}
