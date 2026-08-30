/**
 * What the calibration data says about where the sensors should stay.
 *
 * The table is deliberately three columns. The response carries a full
 * comparison against grid, random and kriging-greedy placements, and that
 * belongs in the report - it is what makes the error figure defensible - but a
 * farmer choosing how many sensors to buy is not helped by four competing
 * numbers per row. They need to know what each additional sensor costs and what
 * it buys.
 *
 * Every number here comes from readings the sensors recorded during
 * calibration, scored against LATER readings none of the placements was fitted
 * on. Nothing on this screen is generated.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import Toast from '../components/Toast';
import { setLifecycle, getHouse } from '../services/careV2';

export default function PlacementResultScreen({ route, navigation }) {
  const houseId = route.params?.houseId;
  const result  = route.params?.result || {};

  const table = result.table || [];
  const [picked, setPicked] = useState(result.recommendedSensors ?? table[0]?.sensors);
  const [busy,   setBusy]   = useState(false);
  const [toast,  setToast]  = useState(null);
  const [house,  setHouse]  = useState(route.params?.house || null);

  React.useEffect(() => {
    if (!house) getHouse(houseId).then((r) => setHouse(r?.house || null)).catch(() => {});
  }, [houseId, house]);

  const keep = result.positions?.[String(picked)] || [];
  const keepIds = new Set(keep.map((p) => p.sectionId));
  const row = table.find((r) => r.sensors === picked);

  /* Every instrumented section, drawn as kept or removed. Showing only the
     survivors would hide the actual decision - which sensors come out - and
     that is the part the farmer has to physically act on. */
  const allSections = Object.entries(house?.sections || {})
    .filter(([, sec]) => sec?.meta?.x != null && sec?.meta?.y != null)
    .map(([id, sec]) => ({
      id,
      short: String(id).replace(/^S/, ''),
      x: Number(sec.meta.x),
      y: Number(sec.meta.y),
      kind: keepIds.has(id) ? 'real' : 'estimated',
    }));

  const removed = allSections.filter((n) => !keepIds.has(n.id));

  const confirm = async () => {
    try {
      setBusy(true);
      await setLifecycle(houseId, 'active');
      setToast({ text: `${house?.meta?.name || houseId} is now active.`, kind: 'success' });
      setTimeout(() => navigation.navigate('MainTabs'), 1200);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Best placement"
        subtitle={house?.meta?.name || houseId}
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={styles.scroll}>

        <View style={[styles.card, styles.sourceCard, SHADOW.sm]}>
          <Ionicons name="checkmark-circle" size={16} color={COLORS.primary} />
          <Text style={styles.sourceTxt}>
            Calculated from {result.buckets?.fit ?? '—'} periods of your own readings,
            checked against {result.buckets?.test ?? '—'} later ones.
          </Text>
        </View>

        <Text style={styles.h}>How many sensors to keep</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <View style={styles.thead}>
            <Text style={[styles.th, { flex: 1 }]}>Sensors</Text>
            <Text style={[styles.th, styles.num, { flex: 1 }]}>Error</Text>
            <Text style={[styles.th, styles.num, { flex: 1.1 }]}>Cost</Text>
          </View>

          {table.map((r) => {
            const on = r.sensors === picked;
            return (
              <TouchableOpacity key={r.sensors} activeOpacity={0.7}
                onPress={() => setPicked(r.sensors)}
                style={[styles.tr, on && styles.trOn]}>
                <View style={[{ flex: 1 }, styles.cellRow]}>
                  <Text style={[styles.td, styles.tdN, on && styles.tdOn]}>{r.sensors}</Text>
                  {r.recommended && (
                    <View style={styles.recPill}>
                      <Text style={styles.recTxt}>best value</Text>
                    </View>
                  )}
                </View>
                <Text style={[styles.td, styles.num, { flex: 1 }, on && styles.tdOn]}>
                  {r.error == null ? '—' : `±${r.error.toFixed(2)}°C`}
                </Text>
                <Text style={[styles.td, styles.num, { flex: 1.1 }, on && styles.tdOn]}>
                  {r.costLkr.toLocaleString()}
                </Text>
              </TouchableOpacity>
            );
          })}

          <Text style={styles.tnote}>
            Error is how far a section without a sensor would be from the truth.
            Tap a row to see where those sensors go.
          </Text>
        </View>

        <Text style={styles.h}>Where they go</Text>
        <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
          <DigitalTwin
            width={house?.meta?.width || 10}
            length={house?.meta?.length || 14}
            nodes={allSections}
            plantRows={4}
            showPipes={false} />
        </View>

        {/* The action the farmer actually has to take. "Keep 5" is abstract;
            "take the sensor out of S1, S6, S8 and S9" is a job. */}
        {!!removed.length && (
          <View style={[styles.card, styles.removeCard, SHADOW.sm]}>
            <Text style={styles.removeHead}>
              Take the sensors out of these {removed.length}
            </Text>
            <View style={styles.chips}>
              {removed.map((n) => (
                <View key={n.id} style={styles.chip}>
                  <Text style={styles.chipTxt}>{n.id}</Text>
                </View>
              ))}
            </View>
            <Text style={styles.removeNote}>
              These sections keep working — their temperature and humidity will be
              estimated from the sensors that stay, and shown in purple with the
              margin of error. You can move the freed sensors to another house.
            </Text>
          </View>
        )}

        <TouchableOpacity style={[styles.primary, busy && { opacity: 0.6 }]}
          onPress={confirm} disabled={busy} activeOpacity={0.85}>
          {busy ? <ActivityIndicator color="#FFF" />
                : <Text style={styles.primaryTxt}>Confirm {picked} sensors and activate</Text>}
        </TouchableOpacity>
        <Text style={styles.foot}>
          Activating starts normal watering and begins estimating the sections
          without a sensor.
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.lg, paddingBottom: SPACE.xl * 3 },

  h: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '800',
       letterSpacing: 0.4, textTransform: 'uppercase',
       marginTop: SPACE.xl, marginBottom: SPACE.sm },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },

  sourceCard: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm,
                backgroundColor: COLORS.primaryDim },
  sourceTxt:  { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  thead: { flexDirection: 'row', borderBottomWidth: 1.5,
           borderBottomColor: COLORS.textSecondary, paddingBottom: 6 },
  th:    { color: COLORS.textTertiary, fontSize: 10, fontWeight: '800',
           letterSpacing: 0.3, textTransform: 'uppercase' },
  num:   { textAlign: 'right' },

  tr:    { flexDirection: 'row', alignItems: 'center', paddingVertical: 11,
           borderBottomWidth: 1, borderBottomColor: COLORS.borderLight,
           borderRadius: 5 },
  trOn:  { backgroundColor: COLORS.primaryDim },
  cellRow:{ flexDirection: 'row', alignItems: 'center', gap: 6 },
  td:    { color: COLORS.textSecondary, fontSize: FONT.sm,
           fontVariant: ['tabular-nums'] },
  tdN:   { color: COLORS.text, fontWeight: '800' },
  tdOn:  { color: COLORS.text, fontWeight: '700' },

  recPill: { backgroundColor: COLORS.primary, borderRadius: RADIUS.full,
             paddingHorizontal: 7, paddingVertical: 2 },
  recTxt:  { color: '#FFF', fontSize: 8.5, fontWeight: '800', letterSpacing: 0.2 },

  tnote: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
           marginTop: SPACE.md },

  removeCard: { backgroundColor: COLORS.estimatedDim, marginTop: SPACE.lg },
  removeHead: { color: COLORS.estimated, fontSize: FONT.sm, fontWeight: '800',
                marginBottom: SPACE.sm },
  chips:   { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  chip:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.full,
             paddingHorizontal: 11, paddingVertical: 5 },
  chipTxt: { color: COLORS.estimated, fontSize: FONT.xs, fontWeight: '800' },
  removeNote: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17,
                marginTop: SPACE.md },

  primary:    { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center', marginTop: SPACE.xl },
  primaryTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
          marginTop: SPACE.sm, textAlign: 'center' },
});
