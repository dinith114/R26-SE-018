/**
 * Plan a house, then create it.
 *
 * This replaces the old Farm Planner, which asked for eight photos and up to
 * two days of trial readings and then wrote its answer nowhere: the survey
 * produced recommendations, the farmer went to a different screen, and typed
 * everything in again by hand. Nothing joined the two.
 *
 * Here the plan IS the creation. The positions this screen shows are the
 * positions saved to each section's meta.x / meta.y, which is exactly what
 * spatial_service.py needs to start estimating unmonitored zones. There is no
 * step in between for a farmer to skip or mistype.
 *
 * The comparison table is not decoration. A placement that cannot be shown to
 * beat a regular grid is a placement nobody should pay for, and the farmer is
 * the one paying - so they see the error curve, the cost per row, and how the
 * chosen method compares against grid and random before they commit.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import Toast from '../components/Toast';
import DigitalTwin from '../components/DigitalTwin';
import { planHouse, addHouse, setSectionPosition } from '../services/careV2';

const HOUSE_TYPES = ['shade-net', 'greenhouse', 'open'];

/* Rows of the comparison table, in the order they are shown. `key` matches the
   backend's method keys; a method the server did not run (PySensors on a box
   without it) simply has no value and is rendered as a dash rather than
   omitted, so its absence is visible. */
const METHODS = [
  { key: 'pysensors',      label: 'PySensors',  hero: true },
  { key: 'kriging_greedy', label: 'Kriging-greedy' },
  { key: 'grid',           label: 'Regular grid' },
  { key: 'random',         label: 'Random' },
];

export default function HousePlannerScreen({ navigation }) {
  const [name,   setName]   = useState('');
  const [type,   setType]   = useState('shade-net');
  const [w,      setW]      = useState('10');
  const [l,      setL]      = useState('14');
  const [budget, setBudget] = useState(8);

  const [plan,    setPlan]    = useState(null);
  const [picked,  setPicked]  = useState(null);   // sensor count the farmer chose
  const [busy,    setBusy]    = useState(false);
  const [saving,  setSaving]  = useState(false);
  const [toast,   setToast]   = useState(null);

  const width  = parseFloat(w);
  const length = parseFloat(l);
  const sizeOk = width > 1 && length > 1 && width <= 200 && length <= 200;

  const runPlan = async () => {
    if (!sizeOk) {
      setToast({ text: 'Enter a width and length in metres, both above 1.', kind: 'error' });
      return;
    }
    try {
      setBusy(true);
      const r = await planHouse(width, length, budget);
      setPlan(r);
      setPicked(r.recommendedSensors);
      if (!r.pysensorsAvailable) setToast({ text: r.message, kind: 'info' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setBusy(false);
    }
  };

  /* Positions come per row, and must: the winning METHOD changes with the
     sensor count. Measured on a 10 x 14 m house, a plain grid wins at 3, 5 and
     7 sensors while PySensors wins at 6 and 8 - so slicing one method's largest
     layout would show a placement no method chose and no row scored. */
  const row       = plan?.curve?.find(r => r.sensors === picked) || null;
  const positions = row?.positions || [];
  const placedBy  = row?.placedBy || null;
  // The lowest-scoring method, which is not always the one that placed. Shown
  // when they differ rather than hidden - a table the farmer can read that
  // disagrees with the map they are given is worse than saying so plainly.
  const bestScore = row?.bestScoring || null;

  const save = async () => {
    if (!name.trim()) {
      setToast({ text: 'Give the house a name first.', kind: 'error' });
      return;
    }
    try {
      setSaving(true);
      const sections = positions.map((p, i) => ({
        name: `Section ${i + 1}`,
        label: '',
        plantCount: 0,
        growthStage: 'Active',
        lightExposure: 0.75,
      }));
      const r = await addHouse({
        name: name.trim(), type, plantCount: 0, sections,
      });
      const houseId = r.houseId || r.id;

      /* Positions are written per section AFTER creation rather than inside the
         house payload, because /houses does not accept coordinates - and adding
         them there would mean two places that decide what a section's x,y is.
         One failing here leaves a section unplaced, which the Setup tab shows
         as "not placed" and the farmer can fix; it does not lose the house. */
      let placed = 0;
      for (let i = 0; i < positions.length; i++) {
        try {
          await setSectionPosition(houseId, `S${i + 1}`, positions[i].x, positions[i].y);
          placed += 1;
        } catch (_) { /* reported in the summary below */ }
      }

      setToast({
        text: placed === positions.length
          ? `${name.trim()} created with ${placed} placed sections.`
          : `${name.trim()} created. ${placed} of ${positions.length} sections were `
            + `placed — set the rest in each section's Setup tab.`,
        kind: placed === positions.length ? 'success' : 'info',
      });
      setTimeout(() => navigation.goBack(), 1200);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Plan a house" subtitle="Sensor placement, then create"
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

        {/* ── 1. the house ───────────────────────────────────────────── */}
        <Text style={styles.step}>1 · The house</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <Text style={styles.lbl}>Name</Text>
          <TextInput style={styles.input} value={name} onChangeText={setName}
            placeholder="e.g. Back House" placeholderTextColor={COLORS.textTertiary}
            maxFontSizeMultiplier={1.15} />

          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Width (m)</Text>
              <TextInput style={styles.input} value={w} onChangeText={setW}
                keyboardType="decimal-pad" maxFontSizeMultiplier={1.15} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Length (m)</Text>
              <TextInput style={styles.input} value={l} onChangeText={setL}
                keyboardType="decimal-pad" maxFontSizeMultiplier={1.15} />
            </View>
          </View>

          <Text style={styles.lbl}>Type</Text>
          <View style={styles.chips}>
            {HOUSE_TYPES.map(t => (
              <TouchableOpacity key={t} onPress={() => setType(t)}
                style={[styles.chip, type === t && styles.chipOn]}>
                <Text style={[styles.chipTxt, type === t && styles.chipTxtOn]}>{t}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* ── 2. budget ──────────────────────────────────────────────── */}
        <Text style={styles.step}>2 · How many sensors can you buy?</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <Text style={styles.hint}>
            The most you would consider. You pick the actual number from the
            results, once you can see what each one buys.
          </Text>
          <View style={styles.chips}>
            {[4, 5, 6, 8, 10].map(n => (
              <TouchableOpacity key={n} onPress={() => setBudget(n)}
                style={[styles.chip, budget === n && styles.chipOn]}>
                <Text style={[styles.chipTxt, budget === n && styles.chipTxtOn]}>{n}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <TouchableOpacity style={[styles.primary, (busy || !sizeOk) && { opacity: 0.6 }]}
            onPress={runPlan} disabled={busy || !sizeOk} activeOpacity={0.85}>
            {busy ? <ActivityIndicator color="#FFF" />
                  : <Text style={styles.primaryTxt}>Find the best placement</Text>}
          </TouchableOpacity>
        </View>

        {plan && (
          <>
            {/* ── 3. the evidence ────────────────────────────────────── */}
            <Text style={styles.step}>3 · What each sensor buys you</Text>
            <View style={[styles.card, SHADOW.sm]}>
              <Text style={styles.hint}>
                Average error when the rest of the house is estimated from that many
                sensors. Lower is better. Tap a row to choose it.
              </Text>

              <View style={styles.thead}>
                <Text style={[styles.th, { flex: 0.7 }]}>N</Text>
                {METHODS.map(m => (
                  <Text key={m.key} style={[styles.th, styles.thNum, m.hero && styles.thHero]}
                    numberOfLines={1}>{m.label}</Text>
                ))}
                <Text style={[styles.th, styles.thNum]}>Cost</Text>
              </View>

              {plan.curve.map(row => {
                const on = row.sensors === picked;
                return (
                  <TouchableOpacity key={row.sensors} activeOpacity={0.7}
                    onPress={() => setPicked(row.sensors)}
                    style={[styles.tr, on && styles.trOn]}>
                    <Text style={[styles.td, styles.tdN, { flex: 0.7 }, on && styles.tdOn]}>
                      {row.sensors}
                    </Text>
                    {METHODS.map(m => (
                      <Text key={m.key}
                        style={[styles.td, styles.tdNum, m.hero && styles.tdHero, on && styles.tdOn]}>
                        {row[m.key] == null ? '—' : row[m.key].toFixed(2)}
                      </Text>
                    ))}
                    <Text style={[styles.td, styles.tdNum, on && styles.tdOn]}>
                      {(row.costLkr / 1000).toFixed(1)}k
                    </Text>
                  </TouchableOpacity>
                );
              })}

              <Text style={styles.tnote}>
                Error in °C, measured by rebuilding weather the placement never saw.
                Placement uses PySensors; the other rows are the baselines it is
                measured against. Recommended: {plan.recommendedSensors} — after
                that, one more sensor changes the estimate by less than 5%.
              </Text>
            </View>

            {/* ── 4. the map ─────────────────────────────────────────── */}
            <Text style={styles.step}>4 · Where they go</Text>
            <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
              {!!placedBy && (
                <Text style={styles.winner}>
                  {picked} sensors, placed by{' '}
                  {METHODS.find(m => m.key === placedBy)?.label || placedBy}
                </Text>
              )}
              {!!bestScore && bestScore !== placedBy && (
                <Text style={styles.caveat}>
                  {METHODS.find(m => m.key === bestScore)?.label || bestScore} scored
                  lower at this count — see the table above.
                </Text>
              )}
              {/* The blueprint, not a white box with dots on it. Scale, grid,
                  sun edge and plant rows are all things a farmer needs in order
                  to walk into the house and find these positions. */}
              <DigitalTwin
                width={width}
                length={length}
                plantRows={4}
                showPipes={false}
                nodes={positions.map((p, i) => ({
                  id: `S${i + 1}`,
                  short: String(i + 1),
                  x: p.x, y: p.y,
                  // Nothing is installed yet, so every marker is a SUGGESTION.
                  // Drawing these the same green as a measuring sensor would
                  // claim hardware that does not exist.
                  kind: 'planned',
                }))} />

              <View style={styles.coords}>
                {positions.map((p, i) => (
                  <Text key={i} style={styles.coord}>
                    S{i + 1}  ({p.x}, {p.y}) m
                  </Text>
                ))}
              </View>
            </View>

            {/* ── 5. create ──────────────────────────────────────────── */}
            <TouchableOpacity style={[styles.primary, saving && { opacity: 0.6 }]}
              onPress={save} disabled={saving} activeOpacity={0.85}>
              {saving ? <ActivityIndicator color="#FFF" />
                      : <Text style={styles.primaryTxt}>
                          Create house with {positions.length} sections
                        </Text>}
            </TouchableOpacity>
            <Text style={styles.foot}>
              Each section is created with its position already set, so estimates for
              the zones without a node start as soon as the nodes are online.
            </Text>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.lg, paddingBottom: SPACE.xl * 3 },

  step: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '800',
          letterSpacing: 0.4, textTransform: 'uppercase',
          marginTop: SPACE.xl, marginBottom: SPACE.sm },

  card:  { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },
  lbl:   { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700',
           marginBottom: 4, marginTop: SPACE.sm },
  input: { backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm, borderWidth: 1,
           borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm,
           color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  row:   { flexDirection: 'row', gap: SPACE.md },
  hint:  { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17,
           marginBottom: SPACE.sm },

  chips:    { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: 4 },
  chip:     { paddingHorizontal: SPACE.md, paddingVertical: 7, borderRadius: RADIUS.full,
              backgroundColor: COLORS.bgCardAlt },
  chipOn:   { backgroundColor: COLORS.primary },
  chipTxt:  { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },
  chipTxtOn:{ color: '#FFF' },

  primary:    { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center', marginTop: SPACE.lg },
  primaryTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },

  thead:  { flexDirection: 'row', alignItems: 'flex-end', gap: 4,
            borderBottomWidth: 1.5, borderBottomColor: COLORS.textSecondary,
            paddingBottom: 5, marginTop: SPACE.sm },
  th:     { color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '800',
            letterSpacing: 0.2, flex: 1 },
  thNum:  { textAlign: 'right' },
  thHero: { color: COLORS.estimated },

  tr:    { flexDirection: 'row', alignItems: 'center', gap: 4,
           paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: COLORS.borderLight,
           borderRadius: 4 },
  trOn:  { backgroundColor: COLORS.primaryDim },
  td:    { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1 },
  tdNum: { textAlign: 'right', fontVariant: ['tabular-nums'] },
  tdN:   { fontWeight: '800', color: COLORS.text },
  tdHero:{ color: COLORS.estimated, fontWeight: '700' },
  tdOn:  { color: COLORS.text, fontWeight: '700' },
  tnote: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.md },

  winner:  { color: COLORS.estimated, fontSize: FONT.xs, fontWeight: '800',
             marginBottom: 2 },
  caveat:  { color: COLORS.warning, fontSize: 11, fontWeight: '600',
             marginBottom: SPACE.sm, textAlign: 'center' },
  coords:  { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm,
             marginTop: SPACE.md, justifyContent: 'center' },
  coord:   { color: COLORS.textSecondary, fontSize: 11, fontWeight: '600',
             fontVariant: ['tabular-nums'] },

  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
          marginTop: SPACE.sm, textAlign: 'center' },
});
