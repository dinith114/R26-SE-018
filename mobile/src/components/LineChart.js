/**
 * Two-series line chart, drawn without a charting library.
 *
 * The previous chart plotted loose dots, which was unreadable: with two series
 * scattered over the same box you cannot tell which dot belongs to which line,
 * or follow the shape of the day.
 *
 * react-native-svg is not installed and adding a native dependency days before
 * a demo is not worth the risk, so each segment is a thin View rotated to the
 * angle between two consecutive points. For every pair we compute:
 *
 *     length = hypot(dx, dy)          angle = atan2(dy, dx)
 *
 * and render one `length`-wide, 2px-tall View rotated by `angle`, anchored at
 * the left-hand point. Strung together those segments form a real polyline.
 * ~60 tiny Views per series renders fine on a low-end phone.
 *
 * Temperature and humidity have different units, so each is normalised to its
 * own scale and the axis labels say which range is being shown.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS, SPACE, RADIUS } from '../config/theme';

const H = 120;          // plot height in px
const STROKE = 2.5;

/** One polyline: `pts` are already in pixel space, origin bottom-left.
 *
 * Each segment is positioned by its MIDPOINT and then rotated. React Native
 * rotates a view about its own centre and has no transform-origin, so anchoring
 * a segment at its start point requires shifting the rotation origin by hand —
 * which is what the first version got backwards (it pivoted about the right
 * edge), leaving every segment offset from its neighbour and the line looking
 * dashed. Centring on the midpoint needs no origin trick at all: the default
 * centre rotation is already the correct pivot.
 */
function Polyline({ pts, color }) {
  const segs = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const { x: x1, y: y1 } = pts[i];
    const { x: x2, y: y2 } = pts[i + 1];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (!isFinite(len) || len === 0) continue;

    // y is measured upward (we position with `bottom`) but rotation is in
    // screen space where y grows downward, so the angle is negated.
    const angle = -Math.atan2(dy, dx);
    // half a pixel of overlap hides sub-pixel seams between segments
    const w = len + 0.5;

    segs.push(
      <View
        key={i}
        pointerEvents="none"
        style={{
          position: 'absolute',
          left: (x1 + x2) / 2 - w / 2,
          bottom: (y1 + y2) / 2 - STROKE / 2,
          width: w,
          height: STROKE,
          borderRadius: STROKE / 2,
          backgroundColor: color,
          transform: [{ rotate: `${angle}rad` }],
        }}
      />,
    );
  }
  return <>{segs}</>;
}

/**
 * @param series  [{ temperature, humidity, label }]
 * @param band    { low, high } humidity comfort band, drawn behind the lines
 */
export default function LineChart({ series = [], band, width = 300 }) {
  if (!series || series.length < 2) {
    return (
      <View style={[s.empty, { height: H }]}>
        <Text style={s.emptyTxt}>Not enough readings yet to draw a chart.</Text>
      </View>
    );
  }

  const temps = series.map(r => r.temperature).filter(v => typeof v === 'number');
  const tMin = Math.floor(Math.min(...temps) - 1);
  const tMax = Math.ceil(Math.max(...temps) + 1);

  const norm = (v, lo, hi) => Math.max(0, Math.min(1, (v - lo) / Math.max(0.001, hi - lo)));
  const xAt  = i => (i / (series.length - 1)) * width;

  const tempPts = series.map((r, i) => ({ x: xAt(i), y: norm(r.temperature, tMin, tMax) * H }));
  const humPts  = series.map((r, i) => ({ x: xAt(i), y: norm(r.humidity, 0, 100) * H }));

  const bandLow  = band ? norm(band.low, 0, 100) * H : 0;
  const bandHigh = band ? norm(band.high, 0, 100) * H : 0;

  return (
    <View>
      <View
        style={[s.plot, { height: H, width }]}
        accessible
        accessibilityLabel={
          `Chart of temperature and humidity over ${series.length} readings, from `
          + `${series[0].label} to ${series[series.length - 1].label}. Temperature `
          + `between ${tMin} and ${tMax} degrees.`
        }>
        {band && (
          <View pointerEvents="none"
            style={[s.band, { bottom: bandLow, height: Math.max(1, bandHigh - bandLow) }]} />
        )}
        <Polyline pts={humPts}  color={COLORS.humidity} />
        <Polyline pts={tempPts} color={COLORS.temperature} />
      </View>

      <View style={[s.axis, { width }]}>
        <Text style={s.axisTxt}>{series[0].label}</Text>
        <Text style={s.axisTxt}>{series[Math.floor(series.length / 2)].label}</Text>
        <Text style={s.axisTxt}>{series[series.length - 1].label}</Text>
      </View>

      <View style={s.legend}>
        <Legend color={COLORS.temperature} text={`Temperature ${tMin}-${tMax}°C`} />
        <Legend color={COLORS.humidity} text="Humidity 0-100%" />
        {band && <Legend color={`${COLORS.success}44`} text={`Ideal ${band.low}-${band.high}%`} />}
      </View>
    </View>
  );
}

function Legend({ color, text }) {
  return (
    <View style={s.lg}>
      <View style={[s.lgLine, { backgroundColor: color }]} />
      <Text style={s.lgTxt}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  plot:  { position: 'relative', overflow: 'hidden', borderRadius: RADIUS.sm,
           backgroundColor: COLORS.bgCardAlt },
  band:  { position: 'absolute', left: 0, right: 0, backgroundColor: `${COLORS.success}22` },

  empty:    { alignItems: 'center', justifyContent: 'center',
              backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm },
  emptyTxt: { color: COLORS.textTertiary, fontSize: 13 },

  axis:    { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  axisTxt: { color: COLORS.textTertiary, fontSize: 11 },

  legend:  { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.md, marginTop: SPACE.md },
  lg:      { flexDirection: 'row', alignItems: 'center', gap: 5 },
  lgLine:  { width: 14, height: 3, borderRadius: 2 },
  lgTxt:   { color: COLORS.textSecondary, fontSize: 11 },
});
