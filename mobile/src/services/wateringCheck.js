/**
 * The arithmetic behind "How watering times were checked", kept apart from the
 * screen.
 *
 * DELIBERATELY IMPORTS NOTHING, like placementFlow.js and request.js, so it can
 * be tested in plain Node (see __tests__/wateringCheck.test.mjs).
 *
 * Every number the screen shows is read off the two endpoints:
 *   /watering-validation              the model against its labels, by split
 *   /houses/{h}/shadehouse-check      the sensors against the indoor conversion
 * Nothing here invents a value, fills a gap or rounds a missing field to zero.
 * A missing value comes back as '—', and a release build must never meet a
 * TypeError from a field the server left out - so every read is guarded.
 */

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
const arr = (v) => (Array.isArray(v) ? v : []);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** 58436 -> "58,436". Without Intl, which some Hermes builds only half carry. */
export function int(v) {
  if (!isNum(v)) return '—';
  const s = String(Math.round(Math.abs(v)));
  return (v < 0 && Math.round(Math.abs(v)) !== 0 ? '-' : '')
    + s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** Rounded, trailing zeros dropped: 3.5 -> "3.5", 3.85 -> "3.85", 7 -> "7". */
export function num(v, digits = 2) {
  if (!isNum(v)) return '—';
  const r = Number(v.toFixed(digits));
  return String(r === 0 ? 0 : r);          // never "-0"
}

/**
 * A field as text, or the fallback. An object handed to <Text> as a child is a
 * render error, and in a release build a render error closes the app - so no
 * server field reaches the screen without passing through here or num()/int().
 */
export function str(v, fallback = '—') {
  if (typeof v === 'string') return v.trim() ? v : fallback;
  if (isNum(v)) return String(v);
  return fallback;
}

/** "nuwara-eliya" -> "Nuwara Eliya". The training sites are stored as slugs. */
export function siteName(slug) {
  if (typeof slug !== 'string' || !slug) return '—';
  return slug.split(/[-_\s]+/).filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
}

/* ── Step 2: the splits ──────────────────────────────────────────────────── */

/**
 * A split's display name, from the file's own label: "RANDOM 80/20 (2017-2024)"
 * -> "Random 80/20". Taken from the label rather than kept here, so the 80/20
 * on screen is whatever the script actually used.
 */
export function splitName(s) {
  const x = obj(s);
  const base = (typeof x.label === 'string' && x.label.split(' (')[0].trim())
    || (typeof x.name === 'string' && x.name.trim()) || '';
  if (!base) return '—';
  const low = base.toLowerCase();
  return low[0].toUpperCase() + low.slice(1);
}

/** One row per split, in the order the file lists them. */
export function splitRows(validation) {
  return arr(obj(validation).splits)
    .filter((s) => s && typeof s === 'object')
    .map((s) => ({
      key: String(s.name ?? s.label ?? ''),
      name: splitName(s),
      trainYears: typeof s.trainYears === 'string' ? s.trainYears : null,
      testYears: typeof s.testYears === 'string' ? s.testYears : null,
      trainRows: isNum(s.trainRows) ? s.trainRows : null,
      testRows: isNum(s.testRows) ? s.testRows : null,
      hourMaeMin: isNum(s.hourMaeMin) ? s.hourMaeMin : null,
      hourR2: isNum(s.hourR2) ? s.hourR2 : null,
      durMaeSec: isNum(s.durMaeSec) ? s.durMaeSec : null,
      durR2: isNum(s.durR2) ? s.durR2 : null,
      outOfTime: s.name === 'OUT-OF-TIME',
    }));
}

/** The split the answer quotes: whole years held out. Null if the file lacks it. */
export function headlineSplit(validation) {
  return splitRows(validation).find((r) => r.outOfTime) || null;
}

/* ── Step 3: the indoor conversion ───────────────────────────────────────── */

export const QUANTITIES = ['warming', 'humidityLift', 'transmission'];

/** The server's verdict string, sorted into the four things a pill can say. */
export function verdictKind(v) {
  if (typeof v !== 'string') return 'unknown';
  if (v === 'within tolerance') return 'ok';
  if (v === 'out of tolerance') return 'bad';
  if (v.startsWith('not enough data')) return 'unmeasured';
  return 'unknown';
}

export const VERDICT_TEXT = {
  ok: 'Within tolerance',
  bad: 'Out of tolerance',
  unmeasured: 'Not measured',
  unknown: 'No verdict',
};

/**
 * A value in the unit the server named. A transmission is a FRACTION on the
 * wire and is shown as a percentage of outdoor light; the server's 'C' is °C.
 */
export function valueText(v, unit, signed = false) {
  if (!isNum(v)) return '—';
  let x = v;
  let suffix = unit ? ` ${unit}` : '';
  let digits = 2;
  if (unit === 'fraction') { x = v * 100; suffix = ' %'; digits = 1; }
  else if (unit === 'C') { suffix = ' °C'; digits = 2; }
  else if (unit === '%') { suffix = ' %'; digits = 1; }
  const t = num(x, digits);
  return `${signed && Number(t) > 0 ? '+' : ''}${t}${suffix}`;
}

/** One row per constant: assumed, measured, gap, tolerance, hours, verdict. */
export function quantityRows(check) {
  const c = obj(check);
  const units = obj(c.units);
  return QUANTITIES.map((q) => {
    const verdict = obj(c.verdict)[q];
    const kind = verdictKind(verdict);
    const unit = typeof units[q] === 'string' ? units[q] : '';
    const tol = obj(c.tolerance)[q];
    const hours = obj(c.hoursUsed)[q];
    return {
      key: q,
      label: typeof obj(c.labels)[q] === 'string' ? obj(c.labels)[q] : q,
      assumed: valueText(obj(c.assumed)[q], unit),
      measured: valueText(obj(c.measured)[q], unit),
      gap: valueText(obj(c.gap)[q], unit, true),
      tolerance: isNum(tol) ? `±${valueText(tol, unit)}` : '—',
      hours: isNum(hours) ? hours : null,
      kind,
      // A pill says "Not measured"; the reason it could not be is the server's.
      reason: kind === 'ok' || kind === 'bad' ? null
        : (typeof verdict === 'string' ? verdict : null),
    };
  });
}

/** The constants grouped by verdict, by their labels, for the one-line answer. */
export function verdictGroups(check) {
  const out = { ok: [], bad: [], unmeasured: [] };
  for (const r of quantityRows(check)) {
    if (r.kind === 'ok') out.ok.push(r.label);
    else if (r.kind === 'bad') out.bad.push(r.label);
    else out.unmeasured.push(r.label);
  }
  return out;
}

/** Per-section measured values, the same rows the pooled table uses. */
export function sectionRows(check) {
  const per = obj(obj(check).perSection);
  const units = obj(obj(check).units);
  const ids = Object.keys(per).sort((a, b) => {
    const na = Number(String(a).replace(/\D+/g, ''));
    const nb = Number(String(b).replace(/\D+/g, ''));
    return (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) ? na - nb
      : String(a).localeCompare(String(b));
  });
  return ids.map((sid) => {
    const s = obj(per[sid]);
    const cells = {};
    for (const q of QUANTITIES) {
      cells[q] = {
        text: valueText(obj(s.measured)[q], typeof units[q] === 'string' ? units[q] : ''),
        kind: verdictKind(obj(s.verdict)[q]),
      };
    }
    return { sid, hours: isNum(s.hours) ? s.hours : null, ...cells };
  });
}

/** What was left out, summed over every section, so nothing drops silently. */
export function excludedTotals(check) {
  const t = { seeded: 0, badClock: 0, beforeSince: 0,
              temperature: 0, humidity: 0, light: 0, lightAtCeiling: 0 };
  for (const e of Object.values(obj(obj(check).excluded))) {
    const x = obj(e);
    for (const k of Object.keys(t)) if (isNum(x[k])) t[k] += x[k];
  }
  return t;
}

/* ── Where the outdoor weather came from ─────────────────────────────────── */

export const SOURCE_LABEL = {
  'era5-archive': 'ERA5 reanalysis: the dataset the model was trained on',
  'forecast-model': 'Forecast-model analysis, NOT ERA5',
  mixed: 'ERA5 for the older days, forecast model (NOT ERA5) for the last week',
  none: 'No outdoor weather was requested',
};

export const API_LABEL = { archive: 'ERA5 archive', forecast: 'Forecast model' };

/** "2026-08-20" -> "20 Aug" (or "20 Aug 2026"). A UTC calendar date, as written. */
export function dayText(iso, withYear = false) {
  const m = typeof iso === 'string' && /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return '—';
  const mon = MONTHS[Number(m[2]) - 1];
  if (!mon) return '—';
  return `${Number(m[3])} ${mon}${withYear ? ` ${m[1]}` : ''}`;
}

/** "one row per site and day" -> "One row per site and day." For prose. */
export function sentence(s) {
  if (typeof s !== 'string' || !s.trim()) return '';
  const t = s.trim();
  return t[0].toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? '' : '.');
}

/** Which API covered which days, as the server reported it. */
export function sourceParts(check) {
  return arr(obj(obj(check).outdoorSource).parts)
    .filter((p) => p && typeof p === 'object')
    .map((p) => ({
      api: API_LABEL[p.api] || (typeof p.api === 'string' ? p.api : '—'),
      era5: p.api === 'archive',
      from: dayText(p.from),
      to: dayText(p.to),
      hours: isNum(p.hours) ? p.hours : null,
    }));
}

/** "2026-08-20T16:00Z" (what compare() writes) -> epoch ms, or null. */
export function isoHourMs(s) {
  const m = typeof s === 'string'
    && /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?Z$/.exec(s);
  if (!m) return null;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]),
                      Number(m[4]), Number(m[5]), Number(m[6] || 0));
  return Number.isFinite(ms) ? ms : null;
}

/** "2026-10-06T18:54:02Z" -> epoch ms, or null. For generatedAt. */
export function isoMs(s) {
  if (typeof s !== 'string') return null;
  const ms = Date.parse(s);
  return Number.isFinite(ms) ? ms : null;
}

/* ── The 24-hour chart ───────────────────────────────────────────────────── */

const FIELD_KEYS = {
  temperature: { indoor: 'indoorTemp', assumed: 'assumedTemp', outdoor: 'outdoorTemp' },
  humidity: { indoor: 'indoorRh', assumed: 'assumedRh', outdoor: 'outdoorRh' },
};

/** "05:30" -> 5.5. The row's own farm-time label is the x position. */
export function localHour(text) {
  const m = typeof text === 'string' && /^(\d{1,2}):(\d{2})$/.exec(text);
  if (!m) return null;
  const h = Number(m[1]) + Number(m[2]) / 60;
  return h >= 0 && h < 24 ? h : null;
}

/** 6 -> "06:00", 24 -> "24:00". Chart ticks on a farm-time day. */
export function clockTick(x) {
  if (!isNum(x)) return '';
  const h = Math.floor(x);
  const m = Math.round((x - h) * 60);
  return `${h < 10 ? '0' : ''}${h}:${m < 10 ? '0' : ''}${m}`;
}

/**
 * The byHour rows as chart lines, x in farm-time hours of the day.
 *
 * Each line comes back as RUNS of consecutive hours. An hour nobody recorded
 * (n 0, value null) ends a run instead of being bridged, so a gap in the chart
 * is a gap in the data - the server keeps those hours for exactly that reason.
 */
export function hourlyChart(check, field = 'temperature') {
  const keys = FIELD_KEYS[field] || FIELD_KEYS.temperature;
  const rows = arr(obj(check).byHour)
    .filter((r) => r && typeof r === 'object')
    .map((r) => ({ x: localHour(r.localTime), r }))
    .filter((q) => q.x != null)
    .sort((a, b) => a.x - b.x);

  const runs = (key) => {
    const out = [];
    let cur = [];
    let prevX = null;
    for (const { x, r } of rows) {
      const y = r[key];
      const adjacent = prevX == null || x - prevX <= 1 + 1e-9;
      if (isNum(y) && adjacent) cur.push({ x, y });
      else {
        if (cur.length) out.push(cur);
        cur = isNum(y) ? [{ x, y }] : [];
      }
      prevX = x;
    }
    if (cur.length) out.push(cur);
    return out;
  };

  const indoor = runs(keys.indoor);
  const assumed = runs(keys.assumed);
  const outdoor = runs(keys.outdoor);
  const ys = [...indoor, ...assumed, ...outdoor].flat().map((p) => p.y);
  let lo = ys.length ? Math.min(...ys) : 0;
  let hi = ys.length ? Math.max(...ys) : 1;
  const pad = (hi - lo) * 0.08 || 0.5;
  lo -= pad; hi += pad;
  const hoursWithIndoor = rows.filter((q) => isNum(q.r[keys.indoor])).length;
  const nTotal = rows.reduce((s, q) => s + (isNum(q.r.n) ? q.r.n : 0), 0);
  return { indoor, assumed, outdoor, yMin: lo, yMax: hi,
           hoursWithIndoor, nTotal, empty: indoor.length === 0 };
}

/* ── Which house, and from when ──────────────────────────────────────────── */

/**
 * The house the indoor check should open on, from /overview.
 *
 * The house the live node reports into first - that is where a real sensor is.
 * Then the first house not marked simulated: the node bench writes invented
 * weather there, and the server refuses to check it. A simulated house only as
 * a last resort, where the refusal at least explains itself. Null if none.
 */
export function pickHouseId(overview, device) {
  const houses = arr(obj(overview).houses)
    .filter((h) => h && typeof h === 'object' && typeof h.houseId === 'string' && h.houseId);
  const real = (h) => obj(h.meta).simulated !== true;
  const assigned = typeof obj(device).assignedTo === 'string'
    ? obj(device).assignedTo.split('/')[0] : null;
  const mine = houses.find((h) => h.houseId === assigned);
  if (mine && real(mine)) return mine.houseId;
  const first = houses.find(real) || houses[0];
  return first ? first.houseId : null;
}

/** The read-window choices. The labels are labels; the window is computed. */
export const SINCE_CHOICES = [
  { key: 'all', label: 'All readings', days: null },
  { key: '7d', label: 'Last 7 days', days: 7 },
  { key: '3d', label: 'Last 3 days', days: 3 },
  { key: '1d', label: 'Last 24 h', days: 1 },
];

/** sinceMs for a choice, or null for "all readings". */
export function sinceMsFor(key, nowMs) {
  const c = SINCE_CHOICES.find((x) => x.key === key);
  if (!c || c.days == null || !isNum(nowMs)) return null;
  return nowMs - c.days * 86400000;
}

/**
 * What a failed check means, in words. The server's 409/404 detail already says
 * WHY; this adds what would fix it, which the detail does not.
 */
export function checkFailure(err, houseId) {
  if (!houseId) {
    return { kind: 'nohouse',
             reason: 'No house is selected, and the indoor check is made for one house.',
             needed: 'Open this page from a farm that has a house, with a sensor node '
                   + 'inside that house.' };
  }
  const status = err && isNum(err.status) ? err.status : null;
  const msg = err && typeof err.message === 'string' && err.message
    ? err.message : 'The check could not be loaded.';
  if (status === 409 || status === 404) {
    return { kind: 'notyet', status, reason: msg,
             needed: 'A sensor node inside the shade house, recording for at least a day '
                   + 'with some sunny hours, so its readings can be put beside the '
                   + 'outdoor weather for the same hours.' };
  }
  if (status === 503) {
    return { kind: 'offline', status, reason: msg,
             needed: 'The outdoor weather service has to be reachable. Try again.' };
  }
  return { kind: 'error', status, reason: msg, needed: null };
}
