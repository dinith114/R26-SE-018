/**
 * The arithmetic behind the placement-flow charts, kept apart from the screen.
 *
 * DELIBERATELY IMPORTS NOTHING, like request.js, so it can be tested in plain
 * Node (see __tests__/placementFlow.test.mjs). Every number the charts draw is
 * read straight off the analysis the server returned; nothing here invents a
 * point, smooths a line or fills a gap. A missing value stays missing.
 */

/** Tick values that read like a person chose them: 0, 0.5, 1.0 - not 0.37. */
export function niceTicks(min, max, count = 4) {
  if (!(Number.isFinite(min) && Number.isFinite(max))) return [];
  if (max <= min) return [min];
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    out.push(Number(v.toFixed(10)));
  }
  return out;
}

/** domain -> pixels. y is flipped, so larger values sit higher on the chart. */
export function scaler([d0, d1], [r0, r1]) {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/**
 * A straight line drawn with one rotated View.
 * Positioned by its CENTRE and rotated about it, which is React Native's
 * default origin - so this works without transformOrigin on any version.
 */
export function segment(x1, y1, x2, y2, thickness = 2) {
  const len = Math.hypot(x2 - x1, y2 - y1);
  return {
    left: (x1 + x2) / 2 - len / 2,
    top: (y1 + y2) / 2 - thickness / 2,
    width: len,
    height: thickness,
    angle: Math.atan2(y2 - y1, x2 - x1),
  };
}

/** Upper bound for an axis that starts at zero, with a little headroom. */
export function axisMax(values, floor = 0) {
  const vs = values.filter((v) => Number.isFinite(v));
  const m = Math.max(floor, ...vs);
  return m > 0 ? m * 1.12 : 1;
}

export const METHOD_LABEL = {
  pysensors: 'PySensors (SSPOR)',
  grid: 'Even spread (grid)',
  kriging_greedy: 'Kriging variance',
  random: 'Random (average)',
  best: 'Best possible',
  worst: 'Worst possible',
};

/**
 * Coverage chart: every PAIR of nodes as a dot (distance, mean difference),
 * the fitted line, the sensor-accuracy line, and where they cross.
 */
export function coverageChart(analysis, field = 'temperature') {
  const cov = (analysis || {}).coverage || {};
  const fit = (cov.fields || {})[field] || {};
  const points = (cov.pairs || [])
    .filter((p) => Number.isFinite(p[field]))
    .map((p) => ({ x: p.distance, y: p[field], label: `${p.a}–${p.b}` }));
  const tol = fit.tolerance;
  const radius = Number.isFinite(fit.radius) ? fit.radius : null;
  // Where the house changes with DIRECTION rather than distance there is no
  // fitted radius, only an upper bound: the closest pair that already disagrees.
  const atMost = Number.isFinite(fit.atMost) ? fit.atMost : null;
  const xMax = axisMax([...points.map((p) => p.x), radius || 0, atMost || 0]);
  const yMax = axisMax([...points.map((p) => p.y), tol || 0]);
  let line = null;
  if (Number.isFinite(fit.slope) && Number.isFinite(fit.intercept)) {
    // Drawn only across the chart, never past its edges.
    const at = (x) => fit.intercept + fit.slope * x;
    line = { x0: 0, y0: at(0), x1: xMax, y1: at(xMax) };
  }
  return {
    points, line, tolerance: tol, radius, atMost,
    status: fit.status || null, r2: fit.r2 ?? null, unit: fit.unit || '',
    note: fit.note || null, xMax, yMax,
  };
}

/**
 * One node's reach, worded for what it is. A fitted radius reads "4.9 m"; an
 * upper bound must read "under 5.0 m" - printing a bound as a plain number is
 * claiming a measurement that was never made.
 */
export function reachText(node) {
  if (!node) return null;
  if (Number.isFinite(node.radius)) {
    const r = node.radius.toFixed(1);
    const a = Math.round(node.areaM2 ?? Math.PI * node.radius ** 2);
    return node.bound === 'atMost'
      ? { short: `under ${r} m`, long: `less than ${r} m around itself (under ${a} m²)`, upper: true }
      : { short: `${r} m`, long: `about ${r} m around itself (≈ ${a} m²)`, upper: false };
  }
  if (Number.isFinite(node.atLeast)) {
    const r = node.atLeast.toFixed(1);
    return { short: `at least ${r} m`, long: `at least ${r} m - the whole span measured`, upper: false };
  }
  return null;
}

/** The k values, each method's TEST error, and the best-worst range. */
export function placementChart(analysis) {
  const p = (analysis || {}).placement || {};
  const rows = p.rows || [];
  const methods = ['pysensors', 'grid', 'kriging_greedy', 'random'];
  const lines = {};
  for (const m of methods) {
    const pts = rows
      .filter((r) => r.methods && r.methods[m] && Number.isFinite(r.methods[m].normalized))
      .map((r) => ({ x: r.sensors, y: r.methods[m].normalized }));
    if (pts.length) lines[m] = pts;
  }
  const range = rows
    .filter((r) => r.methods && r.methods.best && r.methods.worst)
    .map((r) => ({ x: r.sensors, lo: r.methods.best.normalized, hi: r.methods.worst.normalized }));
  const selected = rows
    .filter((r) => r.selected && r.methods[r.selected])
    .map((r) => ({ x: r.sensors, y: r.methods[r.selected].normalized, method: r.selected }));
  const ks = rows.map((r) => r.sensors);
  const all = [
    ...Object.values(lines).flat().map((q) => q.y),
    ...range.map((q) => q.hi),
    1,                                            // keep the sensor-accuracy line in view
  ];
  return {
    ks, lines, range, selected,
    recommended: p.recommended ?? null,
    xMin: ks.length ? Math.min(...ks) - 0.5 : 0,
    xMax: ks.length ? Math.max(...ks) + 0.5 : 1,
    yMax: axisMax(all),
  };
}

/** Hourly lines per node, x in hours from the first hour. */
export function seriesChart(analysis, field = 'temperature') {
  const s = (analysis || {}).series || {};
  const hours = s.hourMs || [];
  const t0 = hours[0] || 0;
  const xs = hours.map((h) => (h - t0) / 3600000);
  const lines = {};
  let lo = Infinity, hi = -Infinity;
  for (const [sid, f] of Object.entries(s.nodes || {})) {
    const ys = (f || {})[field] || [];
    lines[sid] = xs.map((x, i) => ({ x, y: ys[i] })).filter((q) => Number.isFinite(q.y));
    for (const q of lines[sid]) { lo = Math.min(lo, q.y); hi = Math.max(hi, q.y); }
  }
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  const pad = (hi - lo) * 0.08 || 0.5;
  return { t0, xMax: xs.length ? xs[xs.length - 1] : 1, lines, yMin: lo - pad, yMax: hi + pad };
}

/** How the readings were divided in time: choose / validate / test, as fractions. */
export function periodSplit(analysis) {
  const b = (analysis || {}).buckets || {};
  const per = ((analysis || {}).placement || {}).periods || {};
  const total = b.common || 0;
  if (!total) return null;
  const choose = per.choose ?? Math.max(0, (b.fit || 0) - (per.validate || 0));
  const validate = per.validate ?? 0;
  const test = per.test ?? b.test ?? 0;
  const hrs = (n) => (n * (b.minutes || 10)) / 60;
  return {
    total,
    parts: [
      { key: 'choose', n: choose, frac: choose / total, hours: hrs(choose) },
      { key: 'validate', n: validate, frac: validate / total, hours: hrs(validate) },
      { key: 'test', n: test, frac: test / total, hours: hrs(test) },
    ],
  };
}

/** Per-node cleaning counts, in one shape the table can map over. */
export function cleaningRows(analysis) {
  const raw = (analysis || {}).raw || {};
  return Object.entries(raw).map(([sid, s]) => {
    const rej = (s || {}).rejected || {};
    const t = rej.temperature || {};
    const h = rej.humidity || {};
    return {
      sid,
      records: s.records || 0,
      failed: (t.failed || 0) + (h.failed || 0),
      missing: (t.missing || 0) + (h.missing || 0),
      implausible: (t.implausible || 0) + (h.implausible || 0),
      validT: ((s.valid || {}).temperature) || 0,
      validLight: ((s.valid || {}).light) || 0,
      firstMs: s.first, lastMs: s.last,
    };
  });
}

/** 0.1234 -> "0.12"; null -> "—". Never prints NaN at somebody. */
export function fmt(v, digits = 2) {
  return Number.isFinite(v) ? v.toFixed(digits) : '—';
}

/** "Sat 10 Oct, 14:00" in the farm's time (UTC+5:30), whatever the phone says. */
export function farmTime(ms, withDay = true) {
  if (!Number.isFinite(ms)) return '—';
  const d = new Date(ms + 330 * 60000);
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const mons = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return withDay
    ? `${days[d.getUTCDay()]} ${d.getUTCDate()} ${mons[d.getUTCMonth()]}, ${hh}:${mm}`
    : `${hh}:${mm}`;
}
