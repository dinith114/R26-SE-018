/**
 * Phase 1: create a house and start it calibrating.
 *
 * This screen used to show an error table and "the best placement" the moment
 * the dimensions were typed in, before a single sensor existed. Those numbers
 * came from a microclimate field GENERATED out of the house's geometry - an
 * assumption about where the sun falls, presented as a result. A farmer could
 * install to that recommendation and never learn it was a guess.
 *
 * So there is no table here. The sections go on an even grid, which is the
 * honest answer before any data exists: spread the sensors out and let the house
 * say where it is actually different. The table, and the placement worth acting
 * on, come from PlacementResultScreen after the calibration window - computed
 * from what those sensors recorded.
 *
 * The one number that matters here is how many sections to divide the house
 * into, because calibration needs a sensor in every one of them.
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
import { addHouse, setSectionPosition, setLifecycle } from '../services/careV2';

const HOUSE_TYPES = ['shade-net', 'greenhouse', 'open'];
const SECTION_CHOICES = [4, 6, 8, 9, 12, 16, 20];
const NODE_COST_LKR = 2350;

/* Sections on an even grid, kept clear of the walls.
 *
 * Deliberately the simplest possible layout. Anything cleverer would be
 * inventing structure from assumptions, and the entire point of the calibration
 * window is that the house is about to tell us its real structure. Even spacing
 * is also what "spread your sensors out" means to somebody standing in a shade
 * house holding one.
 */
function evenGrid(width, length, n) {
  const cols = Math.max(1, Math.round(Math.sqrt((n * width) / Math.max(length, 0.1))));
  const rows = Math.ceil(n / cols);
  const out = [];
  for (let r = 0; r < rows && out.length < n; r++) {
    for (let c = 0; c < cols && out.length < n; c++) {
      out.push({
        x: Number((((c + 0.5) * width) / cols).toFixed(2)),
        y: Number((((r + 0.5) * length) / rows).toFixed(2)),
      });
    }
  }
  return out;
}

export default function HousePlannerScreen({ navigation }) {
  const [name,     setName]     = useState('');
  const [type,     setType]     = useState('shade-net');
  const [w,        setW]        = useState('10');
  const [l,        setL]        = useState('14');
  const [sections, setSections] = useState(9);
  const [saving,   setSaving]   = useState(false);
  const [toast,    setToast]    = useState(null);

  const width  = parseFloat(w);
  const length = parseFloat(l);
  const sizeOk = width > 1 && length > 1 && width <= 200 && length <= 200;

  const grid = sizeOk ? evenGrid(width, length, sections) : [];

  const create = async () => {
    if (!name.trim()) {
      setToast({ text: 'Give the house a name first.', kind: 'error' });
      return;
    }
    if (!sizeOk) {
      setToast({ text: 'Enter a width and length in metres, both above 1.', kind: 'error' });
      return;
    }
    try {
      setSaving(true);
      const r = await addHouse({
        name: name.trim(), type, plantCount: 0, width, length,
        sections: grid.map((_, i) => ({
          name: `Section ${i + 1}`, label: '', plantCount: 0,
          growthStage: 'Active', lightExposure: 0.75,
        })),
      });
      const houseId = r.houseId || r.id;

      /* Positions written per section after creation - /houses does not accept
         coordinates, and adding them there would mean two places deciding what
         a section's x,y is. One failing leaves that section unplaced, which its
         Setup tab shows and the farmer can fix; it does not lose the house. */
      let placed = 0;
      for (let i = 0; i < grid.length; i++) {
        try {
          await setSectionPosition(houseId, `S${i + 1}`, grid[i].x, grid[i].y);
          placed += 1;
        } catch (_) { /* reported in the summary below */ }
      }

      await setLifecycle(houseId, 'calibrating');

      setToast({
        text: placed === grid.length
          ? `${name.trim()} created. Calibration has started.`
          : `${name.trim()} created, but only ${placed} of ${grid.length} sections `
            + 'were placed. Set the rest in their Setup tabs.',
        kind: placed === grid.length ? 'success' : 'info',
      });
      setTimeout(() => navigation.replace('Calibration', { houseId }), 1200);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="New house" subtitle="Set it up, then calibrate"
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

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

        <Text style={styles.step}>2 · How many sections</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <Text style={styles.hint}>
            The house is divided into this many zones. Calibration needs a sensor
            in every one, so this is how many you need to start with — you will
            take some out at the end.
          </Text>
          <View style={styles.chips}>
            {SECTION_CHOICES.map(n => (
              <TouchableOpacity key={n} onPress={() => setSections(n)}
                style={[styles.chip, sections === n && styles.chipOn]}>
                <Text style={[styles.chipTxt, sections === n && styles.chipTxtOn]}>{n}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <View style={styles.costRow}>
            <Ionicons name="pricetag-outline" size={14} color={COLORS.textTertiary} />
            <Text style={styles.costTxt}>
              {sections} sensors to calibrate ≈ LKR{' '}
              {(sections * NODE_COST_LKR).toLocaleString()}. You keep fewer than
              this afterwards.
            </Text>
          </View>
        </View>

        <Text style={styles.step}>3 · Where to put them for now</Text>
        <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
          <DigitalTwin
            width={sizeOk ? width : 0}
            length={sizeOk ? length : 0}
            plantRows={4}
            showPipes={false}
            nodes={grid.map((p, i) => ({
              id: `S${i + 1}`, short: String(i + 1),
              x: p.x, y: p.y, kind: 'planned',
            }))} />

          {/* Said where the farmer is looking at it. An even grid is not an
              optimisation and must not be allowed to look like one. */}
          <View style={styles.noteBox}>
            <Ionicons name="information-circle-outline" size={15} color={COLORS.info} />
            <Text style={styles.noteTxt}>
              An even spread — not an optimised placement. Nothing is known about
              this house yet. After three days of readings the app works out which
              of these positions actually matter, and which sensors you can remove.
            </Text>
          </View>
        </View>

        <TouchableOpacity style={[styles.primary, saving && { opacity: 0.6 }]}
          onPress={create} disabled={saving} activeOpacity={0.85}>
          {saving ? <ActivityIndicator color="#FFF" />
                  : <Text style={styles.primaryTxt}>Create and start calibrating</Text>}
        </TouchableOpacity>
        <Text style={styles.foot}>
          Put one sensor in each section and leave them there. The app will tell you
          when it has enough data.
        </Text>
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
           borderColor: COLORS.border, paddingHorizontal: SPACE.md,
           paddingVertical: SPACE.sm, color: COLORS.text, fontSize: FONT.md,
           fontWeight: '700' },
  row:   { flexDirection: 'row', gap: SPACE.md },
  hint:  { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17,
           marginBottom: SPACE.sm },

  chips:    { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: 4 },
  chip:     { paddingHorizontal: SPACE.md, paddingVertical: 7,
              borderRadius: RADIUS.full, backgroundColor: COLORS.bgCardAlt },
  chipOn:   { backgroundColor: COLORS.primary },
  chipTxt:  { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },
  chipTxtOn:{ color: '#FFF' },

  costRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6,
             marginTop: SPACE.md },
  costTxt: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16 },

  noteBox: { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
             backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm,
             padding: SPACE.md, marginTop: SPACE.md },
  noteTxt: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  primary:    { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center', marginTop: SPACE.xl },
  primaryTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
          marginTop: SPACE.sm, textAlign: 'center' },
});
