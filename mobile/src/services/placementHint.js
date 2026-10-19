/**
 * Where a NEW sensor would teach the most (18 Oct 2026).
 *
 * The point of the house furthest from every measuring sensor. Kriging's
 * uncertainty grows with the distance to the nearest measured point, so this is
 * where the estimates for the house know least - the same idea the placement
 * analysis scores layouts on, applied to one extra sensor and to any spot, not
 * only to sections that already exist.
 *
 * A SUGGESTION, never a rule. The farmer knows where the power point is and
 * which bench can be reached; the map lets them tap anywhere else instead.
 *
 * No imports: plain arithmetic, tested with node --test.
 */

const round1 = (v) => Math.round(v * 10) / 10;

/**
 * @param {number} width   house width, metres
 * @param {number} length  house length, metres
 * @param {{x:number,y:number}[]} sensors  positions of sections that MEASURE
 * @returns {{x:number,y:number,distance:number|null}|null}  null without a size
 */
export function furthestPoint(width, length, sensors, step = 0.25) {
  const W = Number(width);
  const L = Number(length);
  if (!(W > 0 && L > 0)) return null;
  const pts = (sensors || []).filter((p) => p && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)))
    .map((p) => ({ x: Number(p.x), y: Number(p.y) }));
  // Half a metre in from the walls (less in a tiny house): a board against the
  // sheeting reads the wall, not the plants, and a corner is rarely reachable.
  const margin = Math.min(0.5, W / 10, L / 10);
  if (!pts.length) return { x: round1(W / 2), y: round1(L / 2), distance: null };
  let best = null;
  for (let x = margin; x <= W - margin + 1e-9; x += step) {
    for (let y = margin; y <= L - margin + 1e-9; y += step) {
      let d = Infinity;
      for (const p of pts) d = Math.min(d, Math.hypot(x - p.x, y - p.y));
      if (!best || d > best.distance + 1e-9) best = { x, y, distance: d };
    }
  }
  return { x: round1(best.x), y: round1(best.y), distance: round1(best.distance) };
}
