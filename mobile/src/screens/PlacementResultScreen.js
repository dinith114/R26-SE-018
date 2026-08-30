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
import {
  applyPlacement, getHouse, getDevices, setHouseMaster,
} from '../services/careV2';

export default function PlacementResultScreen({ route, navigation }) {
  const houseId = route.params?.houseId;
  const result  = route.params?.result || {};

  const table = result.table || [];
  const [picked, setPicked] = useState(result.recommendedSensors ?? table[0]?.sensors);
  const [busy,   setBusy]   = useState(false);
  const [toast,  setToast]  = useState(null);
  const [house,  setHouse]  = useState(route.params?.house || null);
  /* THE LAST STEP OF THE FLOW, not a card somewhere else.
     Freeing sensors is what makes a controller compulsory: the zones they leave
     can only be watered through the relay board. Told once in a toast, that
     lands while the farmer is already walking away - so the flow does not end
     until it is answered. */
  const [step,    setStep]    = useState('table');   // 'table' | 'master'
  const [devices, setDevices] = useState(null);
  const [savingMaster, setSavingMaster] = useState(false);

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

  /* Applying the decision is what makes it real.
     This used to set the lifecycle to active and stop, so the farmer was told
     which sensors to take out and the system carried on believing all twelve
     were still installed. The server now frees those nodes and clears their
     sections' last reading in one call, which is what lets kriging take over
     the zones instead of them sitting frozen on the reading they had when the
     sensor was pulled. */
  const confirm = async () => {
    try {
      setBusy(true);
      const r = await applyPlacement(houseId, [...keepIds]);
      const n = (r.freed || []).length;
      /* Naming the controller becomes REQUIRED the moment sensors come out: the
         zones they leave behind can only be watered through the relay board. It
         is said here, at the moment it becomes true, because the farmer is
         about to walk away thinking the setup is finished. The dashboard also
         carries it until it is done - one telling is not enough for a step that
         silently stops water reaching plants. */
      setToast({
        text: r.needsMaster
          ? `${n} sensor${n === 1 ? '' : 's'} freed. Now choose a master controller — `
            + 'those zones cannot be watered without one.'
          : n
            ? `${n} sensor${n === 1 ? '' : 's'} freed — take them out of the house.`
            : `${house?.meta?.name || houseId} is now active.`,
        kind: r.needsMaster ? 'info' : 'success',
      });
      if (r.needsMaster) {
        setStep('master');
        getDevices()
          .then((d) => setDevices(d.devices || []))
          .catch((e) => { setDevices([]); setToast({ text: e.message, kind: 'error' }); });
      } else {
        setTimeout(() => navigation.navigate('MainTabs'), 1600);
      }
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setBusy(false);
    }
  };

  /* Two kinds of board can run the valves, and the difference is physical. A
     node still IN this house does both jobs. A spare belonging to no house can
     only be a controller - it sits in no section, so anything it "measured"
     would describe wherever it happens to be. Boards from ANOTHER house are not
     offered: taking one would strip that house of a sensor. */
  const masterChoices = () => {
    const list = devices || [];
    return [
      ...list.filter((d) => d.house === houseId).map((d) => ({
        ...d, why: `In ${d.section} · keeps sensing and runs the valves` })),
      ...list.filter((d) => !d.assignedTo).map((d) => ({
        ...d, why: 'Spare board · runs the valves only, gives no readings' })),
    ];
  };

  const chooseMaster = async (mac) => {
    setSavingMaster(true);
    try {
      await setHouseMaster(houseId, mac);
      setToast({ text: 'Controller set. The house is ready.', kind: 'success' });
      setTimeout(() => navigation.navigate('MainTabs'), 1200);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
      setSavingMaster(false);
    }
  };

  if (step === 'master') {
    const choices = masterChoices();
    return (
      <View style={styles.container}>
        <ScreenHeader title="Choose the controller"
          subtitle={house?.meta?.name || houseId} navigation={navigation} />
        <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={[styles.card, styles.sourceCard, SHADOW.sm]}>
            <Ionicons name="git-network" size={16} color={COLORS.primary} />
            <Text style={styles.sourceTxt}>
              The zones you just freed have no sensor of their own, so they are
              watered through one board's relay. Pick that board — without it
              nothing can water them.
            </Text>
          </View>

          <Text style={styles.h}>Boards that can do it</Text>
          <View style={[styles.card, SHADOW.sm]}>
            {devices === null ? (
              <View style={{ paddingVertical: SPACE.xl, alignItems: 'center' }}>
                <ActivityIndicator color={COLORS.primary} />
              </View>
            ) : choices.length ? choices.map((d) => (
              <TouchableOpacity key={d.mac} style={styles.masterRow}
                disabled={savingMaster} activeOpacity={0.7}
                accessibilityRole="button"
                accessibilityLabel={`Use node ${d.shortId || d.mac.slice(-4)} as the controller`}
                onPress={() => chooseMaster(d.mac)}>
                <Ionicons name="hardware-chip-outline" size={20}
                  color={d.online ? COLORS.primary : COLORS.textTertiary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.masterName}>
                    Node {d.shortId || d.mac.slice(-4)}
                    {!d.online && <Text style={styles.masterOff}>  offline</Text>}
                  </Text>
                  <Text style={styles.masterWhy}>{d.why}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />
              </TouchableOpacity>
            )) : (
              <Text style={styles.masterWhy}>
                No board is available. A controller must be a node already in this
                house, or a spare that belongs to no house — taking one from
                another house would leave that house a sensor short.
              </Text>
            )}
          </View>

          {/* Skippable, because refusing to let someone leave a screen is worse
              than a farm that is briefly not wired up - and the dashboard
              carries the same blocker until it is done. */}
          <TouchableOpacity style={styles.skip} disabled={savingMaster}
            onPress={() => navigation.navigate('MainTabs')}>
            <Text style={styles.skipTxt}>Set this up later</Text>
          </TouchableOpacity>
          <View style={{ height: 40 }} />
        </ScrollView>
      </View>
    );
  }

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

  masterRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
               paddingVertical: SPACE.md, borderTopWidth: 1,
               borderTopColor: COLORS.borderLight },
  masterName:{ color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  masterOff: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '500' },
  masterWhy: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, marginTop: 1 },
  skip:      { alignItems: 'center', paddingVertical: SPACE.lg, marginTop: SPACE.sm },
  skipTxt:   { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },

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
