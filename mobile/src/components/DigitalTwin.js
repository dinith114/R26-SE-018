/**
 * A top-down blueprint of one house.
 *
 * Replaces the plain white rectangle with dots. That drew the positions and
 * nothing else, so a farmer could not tell which end of the drawing faced the
 * sun, how far apart two sensors really were, or which of the dots was the
 * board that opens the valves.
 *
 * Every element here answers a question somebody actually asks standing in the
 * house:
 *
 *   grid + scale     how far apart are these, in metres I can pace out
 *   sun edge         which way round is this drawing
 *   plant rows       where are the plants relative to the sensors
 *   pipe route       where does the water come from, and how far does it run
 *   node colour      is this reading measured or estimated, and which is the
 *                    master
 *
 * Deliberately plain Views and no WebView. The old planner loaded Three.js from
 * a CDN on three separate screens to draw a box with poles in it; this draws
 * more information, instantly, offline.
 *
 * ONE component for every phase. Planning, calibrating and active differ only
 * in what `nodes` contains - a phase is data here, not a third screen that
 * drifts out of step with the other two.
 */
import React from 'react';
import { View, Text, StyleSheet, useWindowDimensions, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';

/* What a marker means. `kind` is the single switch: colour, icon, outline and
   legend all derive from it, so a new kind cannot be half-added. */
export const NODE_KINDS = {
  real:      { color: COLORS.primary,   icon: 'radio-button-on',   label: 'Measured' },
  master:    { color: COLORS.warning,   icon: 'git-network',       label: 'Master controller' },
  estimated: { color: COLORS.estimated, icon: 'analytics-outline', label: 'Estimated' },
  planned:   { color: COLORS.info,      icon: 'add-circle-outline', label: 'Suggested' },
  offline:   { color: COLORS.textTertiary, icon: 'close-circle-outline', label: 'Not reporting' },
  /* No node has been LINKED here yet - which is not the same as a node that has
     gone quiet, and the fix is different: bring a board, rather than check the
     battery on one that is already there. During calibration this is the normal
     state of most of a new house, and painting it "Not reporting" made a house
     that was simply not wired up yet look like a farm full of dead hardware. */
  nonode:    { color: COLORS.textTertiary, icon: 'add-outline', label: 'No node yet' },
};

/* Grid spacing that keeps the drawing readable at any house size. A 6 m house
   wants a line every metre; a 40 m house drawn with 40 lines is a grey block. */
function gridStep(metres) {
  if (metres <= 8) return 1;
  if (metres <= 20) return 2;
  if (metres <= 50) return 5;
  return 10;
}

export default function DigitalTwin({
  width,                 // house width, metres
  length,                // house length, metres
  nodes = [],            // [{ id, name, x, y, kind, value, unit, sd }]
  pump = null,           // { x, y } - where the pump and relay board sit
  plantRows = 0,         // draw this many rows of plants
  showPipes = true,
  onPressNode,
  maxHeight = 380,
}) {
  const { width: screenW } = useWindowDimensions();

  const W = Number(width) || 0;
  const L = Number(length) || 0;
  if (!(W > 0 && L > 0)) {
    return (
      <View style={styles.empty}>
        <Ionicons name="grid-outline" size={22} color={COLORS.textTertiary} />
        <Text style={styles.emptyTxt}>Set the house width and length to see the map.</Text>
      </View>
    );
  }

  /* Fit the house into the space available while keeping it to scale. A plan
     drawn out of proportion is worse than no plan: it invites a farmer to pace
     out a distance that is not there. */
  const avail = Math.min(screenW - SPACE.lg * 4, 360);
  const scale = Math.min(avail / W, maxHeight / L);
  const pw = W * scale;
  const ph = L * scale;

  const mx = (m) => m * scale;
  const stepX = gridStep(W);
  const stepY = gridStep(L);

  const xs = [];
  for (let m = stepX; m < W; m += stepX) xs.push(m);
  const ys = [];
  for (let m = stepY; m < L; m += stepY) ys.push(m);

  const rows = [];
  for (let i = 1; i <= plantRows; i++) rows.push((i * L) / (plantRows + 1));

  return (
    <View style={styles.wrap}>
      {/* y = 0 is the open, sun-facing edge. The whole physics of the house
          hangs off which way this faces, and a map without it is ambiguous. */}
      <View style={[styles.sunBar, { width: pw }]}>
        <Ionicons name="sunny" size={11} color={COLORS.warning} />
        <Text style={styles.sunTxt}>open, sun-facing edge</Text>
      </View>

      <View style={styles.plotRow}>
        {/* metre scale down the left */}
        <View style={[styles.axisY, { height: ph }]}>
          {ys.map((m) => (
            <Text key={m} style={[styles.axisTxt, { top: mx(m) - 6 }]}>{m}</Text>
          ))}
        </View>

        <View style={[styles.plot, { width: pw, height: ph }]}>
          {/* graph-paper grid, so a distance can be read off rather than guessed */}
          {xs.map((m) => (
            <View key={`vx${m}`} style={[styles.vline, { left: mx(m), height: ph }]} />
          ))}
          {ys.map((m) => (
            <View key={`hz${m}`} style={[styles.hline, { top: mx(m), width: pw }]} />
          ))}

          {/* plant rows, under everything else */}
          {rows.map((m, i) => (
            <View key={`pr${i}`} style={[styles.plantRow, { top: mx(m), width: pw }]} />
          ))}

          {/* pipe route: pump to each node, straight runs. Not a survey - it
              shows which sections sit far from the pump, which is where flow
              drops and where a per-section ml/s measurement matters most. */}
          {showPipes && pump && nodes.map((n) => {
            const dx = mx(n.x - pump.x);
            const dy = mx(n.y - pump.y);
            const len = Math.hypot(dx, dy);
            if (!len) return null;
            return (
              <View key={`pipe${n.id}`} style={[styles.pipe, {
                left: mx(pump.x), top: mx(pump.y), width: len,
                transform: [{ rotate: `${Math.atan2(dy, dx)}rad` }],
              }]} />
            );
          })}

          {/* the pump and relay board */}
          {pump && (
            <View style={[styles.pump, { left: mx(pump.x) - 11, top: mx(pump.y) - 11 }]}>
              <Ionicons name="water" size={13} color="#FFF" />
            </View>
          )}

          {/* nodes */}
          {nodes.map((n) => {
            const k = NODE_KINDS[n.kind] || NODE_KINDS.real;
            const Tag = onPressNode ? TouchableOpacity : View;
            return (
              <Tag key={n.id} activeOpacity={0.7}
                onPress={onPressNode ? () => onPressNode(n) : undefined}
                style={[styles.node, {
                  left: mx(n.x) - 15, top: mx(n.y) - 15,
                  backgroundColor: n.kind === 'planned' ? 'transparent' : k.color,
                  borderColor: k.color,
                  borderStyle: n.kind === 'planned' ? 'dashed' : 'solid',
                }]}>
                <Text style={[styles.nodeTxt, {
                  color: n.kind === 'planned' ? k.color : '#FFF',
                }]} numberOfLines={1}>
                  {n.short || String(n.id).replace(/^S/, '')}
                </Text>
              </Tag>
            );
          })}
        </View>
      </View>

      {/* metre scale along the bottom */}
      <View style={[styles.axisX, { width: pw, marginLeft: 22 }]}>
        {xs.map((m) => (
          <Text key={m} style={[styles.axisTxt, { left: mx(m) - 6, top: 0 }]}>{m}</Text>
        ))}
        <Text style={styles.dims}>{W} m × {L} m</Text>
      </View>

      {/* Values live BELOW the map, not inside the markers. A number crammed
          into a 30 px circle is unreadable, and an estimate has to carry its
          error beside it or it reads as a measurement. */}
      {nodes.some((n) => n.value != null) && (
        <View style={styles.readouts}>
          {nodes.filter((n) => n.value != null).map((n) => {
            const k = NODE_KINDS[n.kind] || NODE_KINDS.real;
            return (
              <View key={`v${n.id}`} style={styles.readout}>
                <View style={[styles.swatch, { backgroundColor: k.color }]} />
                <Text style={styles.readoutId}>{n.id}</Text>
                <Text style={[styles.readoutVal, { color: k.color }]}>
                  {n.value}{n.unit || ''}
                  {n.sd != null ? ` ±${n.sd}` : ''}
                </Text>
                {n.kind === 'estimated' && (
                  <Text style={styles.estTag}>estimated</Text>
                )}
              </View>
            );
          })}
        </View>
      )}

      {/* Legend, showing only the kinds actually present. A key listing things
          that are not on the map is noise. */}
      <View style={styles.legend}>
        {Object.entries(NODE_KINDS)
          .filter(([kind]) => nodes.some((n) => n.kind === kind))
          .map(([kind, k]) => (
            <View key={kind} style={styles.legendItem}>
              <View style={[styles.legendDot, {
                backgroundColor: kind === 'planned' ? 'transparent' : k.color,
                borderColor: k.color,
              }]} />
              <Text style={styles.legendTxt}>{k.label}</Text>
            </View>
          ))}
        {!!pump && (
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: COLORS.humidity,
                                               borderColor: COLORS.humidity }]} />
            <Text style={styles.legendTxt}>Pump</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },

  empty:    { alignItems: 'center', gap: SPACE.sm, paddingVertical: SPACE.xl },
  emptyTxt: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center' },

  sunBar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 4, marginLeft: 22, paddingVertical: 3,
            backgroundColor: COLORS.warningDim,
            borderTopLeftRadius: 3, borderTopRightRadius: 3 },
  sunTxt: { color: COLORS.warning, fontSize: 9.5, fontWeight: '800', letterSpacing: 0.3 },

  plotRow: { flexDirection: 'row' },
  axisY:   { width: 22 },
  axisX:   { height: 16, marginTop: 2 },
  axisTxt: { position: 'absolute', color: COLORS.textTertiary, fontSize: 9,
             fontWeight: '700', width: 14, textAlign: 'center' },
  dims:    { position: 'absolute', right: 0, top: 1,
             color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '700' },

  plot:  { backgroundColor: COLORS.bgCardAlt, borderWidth: 1.5,
           borderColor: COLORS.textTertiary, borderRadius: 2 },
  vline: { position: 'absolute', top: 0, width: 1, backgroundColor: COLORS.border },
  hline: { position: 'absolute', left: 0, height: 1, backgroundColor: COLORS.border },

  plantRow: { position: 'absolute', left: 0, height: 0,
              borderTopWidth: 1, borderStyle: 'dashed',
              borderTopColor: COLORS.primaryDim },

  pipe: { position: 'absolute', height: 2, backgroundColor: COLORS.humidity,
          opacity: 0.35, transformOrigin: 'left center' },

  pump: { position: 'absolute', width: 22, height: 22, borderRadius: 5,
          backgroundColor: COLORS.humidity, alignItems: 'center',
          justifyContent: 'center' },

  node:    { position: 'absolute', width: 30, height: 30, borderRadius: 15,
             borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  nodeTxt: { fontSize: 11, fontWeight: '800' },

  readouts: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm,
              justifyContent: 'center', marginTop: SPACE.md },
  readout:  { flexDirection: 'row', alignItems: 'center', gap: 4,
              backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
              paddingHorizontal: 7, paddingVertical: 4 },
  swatch:   { width: 7, height: 7, borderRadius: 4 },
  readoutId:{ color: COLORS.textSecondary, fontSize: 10, fontWeight: '800' },
  readoutVal:{ fontSize: 10.5, fontWeight: '700' },
  estTag:   { color: COLORS.estimated, fontSize: 8.5, fontWeight: '800',
              letterSpacing: 0.2 },

  legend:     { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.md,
                justifyContent: 'center', marginTop: SPACE.md },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot:  { width: 9, height: 9, borderRadius: 5, borderWidth: 1.5 },
  legendTxt:  { color: COLORS.textTertiary, fontSize: 10, fontWeight: '600' },
});
