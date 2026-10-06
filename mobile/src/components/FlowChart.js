/**
 * A small x-y chart drawn with plain Views.
 *
 * The app has no SVG or chart library, and adding a native one means a new
 * build of the APK for three charts. Lines here are single Views rotated about
 * their centre (see placementFlow.segment), which React Native has always
 * supported. The arithmetic lives in services/placementFlow.js, where it is
 * tested; this file only places Views where that arithmetic says.
 *
 * Layers, drawn in order:
 *   { type: 'line',  points: [{x, y}], color, width }
 *   { type: 'dots',  points: [{x, y}], color, size, hollow }
 *   { type: 'range', points: [{x, lo, hi}], color }     vertical bars
 *   { type: 'hline', y, color, label }                   dashed
 *   { type: 'vline', x, color, label }                   dashed
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { COLORS } from '../config/theme';
import { niceTicks, scaler, segment } from '../services/placementFlow';

const AXIS_W = 34;
const AXIS_H = 18;

function Dashes({ horizontal, at, length, color }) {
  const out = [];
  for (let p = 0; p < length; p += 7) {
    out.push(
      <View key={p} style={[styles.dash, horizontal
        ? { left: p, top: at - 0.75, width: Math.min(4, length - p), height: 1.5 }
        : { top: p, left: at - 0.75, height: Math.min(4, length - p), width: 1.5 },
      { backgroundColor: color }]} />,
    );
  }
  return out;
}

export default function FlowChart({
  width, height = 170,
  xDomain, yDomain,
  layers = [],
  xLabel, yLabel,
  xTicks, yTicks,
  xFormat = (v) => String(v),
  yFormat = (v) => String(v),
}) {
  const pw = Math.max(60, width - AXIS_W);
  const ph = height;
  const sx = scaler(xDomain, [0, pw]);
  const sy = scaler(yDomain, [ph, 0]);
  const xt = xTicks || niceTicks(xDomain[0], xDomain[1], 4);
  const yt = yTicks || niceTicks(yDomain[0], yDomain[1], 4);
  const inX = (v) => v >= xDomain[0] - 1e-9 && v <= xDomain[1] + 1e-9;
  const inY = (v) => v >= yDomain[0] - 1e-9 && v <= yDomain[1] + 1e-9;

  return (
    <View>
      {!!yLabel && <Text style={styles.yLabel}>{yLabel}</Text>}
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: AXIS_W, height: ph }}>
          {yt.filter(inY).map((v) => (
            <Text key={`yt${v}`} style={[styles.tick, { top: sy(v) - 6, right: 4 }]}>
              {yFormat(v)}
            </Text>
          ))}
        </View>

        <View style={[styles.plot, { width: pw, height: ph }]}>
          {yt.filter(inY).map((v) => (
            <View key={`yg${v}`} style={[styles.grid, { top: sy(v), width: pw }]} />
          ))}

          {layers.map((layer, li) => {
            const color = layer.color || COLORS.primary;
            if (layer.type === 'hline' && Number.isFinite(layer.y) && inY(layer.y)) {
              return (
                <React.Fragment key={li}>
                  <Dashes horizontal at={sy(layer.y)} length={pw} color={color} />
                  {!!layer.label && (
                    <Text style={[styles.lineLabel, { color, top: sy(layer.y) - 14, right: 3 }]}>
                      {layer.label}
                    </Text>
                  )}
                </React.Fragment>
              );
            }
            if (layer.type === 'vline' && Number.isFinite(layer.x) && inX(layer.x)) {
              return (
                <React.Fragment key={li}>
                  <Dashes at={sx(layer.x)} length={ph} color={color} />
                  {!!layer.label && (
                    <Text style={[styles.lineLabel, { color, top: 2, left: sx(layer.x) + 4 }]}>
                      {layer.label}
                    </Text>
                  )}
                </React.Fragment>
              );
            }
            if (layer.type === 'range') {
              return (layer.points || []).map((p, i) => {
                const top = sy(Math.min(p.hi, yDomain[1]));
                const bottom = sy(Math.max(p.lo, yDomain[0]));
                return (
                  <View key={`${li}r${i}`} style={[styles.range, {
                    left: sx(p.x) - 7, top, height: Math.max(2, bottom - top),
                    backgroundColor: color,
                  }]} />
                );
              });
            }
            if (layer.type === 'line') {
              const pts = (layer.points || []).filter((p) => Number.isFinite(p.y));
              const th = layer.width || 2;
              return pts.slice(1).map((p, i) => {
                const a = pts[i];
                const s = segment(sx(a.x), sy(a.y), sx(p.x), sy(p.y), th);
                return (
                  <View key={`${li}l${i}`} style={{
                    position: 'absolute', left: s.left, top: s.top,
                    width: s.width, height: s.height, borderRadius: th,
                    backgroundColor: color, opacity: layer.opacity ?? 1,
                    transform: [{ rotate: `${s.angle}rad` }],
                  }} />
                );
              });
            }
            if (layer.type === 'dots') {
              const sz = layer.size || 7;
              return (layer.points || []).filter((p) => Number.isFinite(p.y)).map((p, i) => (
                <View key={`${li}d${i}`} style={{
                  position: 'absolute', left: sx(p.x) - sz / 2, top: sy(p.y) - sz / 2,
                  width: sz, height: sz, borderRadius: sz / 2,
                  backgroundColor: layer.hollow ? COLORS.bgCard : color,
                  borderWidth: layer.hollow ? 1.5 : 0, borderColor: color,
                }} />
              ));
            }
            return null;
          })}
        </View>
      </View>

      <View style={{ marginLeft: AXIS_W, width: pw, height: AXIS_H }}>
        {xt.filter(inX).map((v) => (
          <Text key={`xt${v}`} style={[styles.tick, { left: sx(v) - 15, width: 30,
                                                       textAlign: 'center', top: 3 }]}>
            {xFormat(v)}
          </Text>
        ))}
      </View>
      {!!xLabel && <Text style={styles.xLabel}>{xLabel}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  plot:  { backgroundColor: COLORS.bgCardAlt, borderLeftWidth: 1, borderBottomWidth: 1,
           overflow: 'hidden',           // a fitted line can run past the top
           borderColor: COLORS.textTertiary },
  grid:  { position: 'absolute', left: 0, height: 1, backgroundColor: COLORS.border },
  dash:  { position: 'absolute' },
  range: { position: 'absolute', width: 14, borderRadius: 3, opacity: 0.18 },
  tick:  { position: 'absolute', color: COLORS.textTertiary, fontSize: 9, fontWeight: '700',
           fontVariant: ['tabular-nums'] },
  lineLabel: { position: 'absolute', fontSize: 9, fontWeight: '800' },
  yLabel: { color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '700', marginBottom: 4 },
  xLabel: { color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '700', textAlign: 'center',
            marginTop: 2 },
});
