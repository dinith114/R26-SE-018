/**
 * Correct a house's width and length, in metres or feet.
 *
 * A house's size could only be typed when it was planned, so a guess (10 x 14 m
 * for the farm's 4.99 x 9.7 m house, 17 Oct 2026) stayed wrong. This edits it.
 * "Move the sections" scales every placed section with the house: right for the
 * planner's even grid, wrong for positions measured with a tape, so it is off
 * unless the farmer turns it on. Saving is the caller's (onSave gets metres).
 */
import React, { useEffect, useState } from 'react';
import {
  Modal, View, Text, TextInput, TouchableOpacity, StyleSheet, Switch,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from 'react-native';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { usePrefs } from '../config/prefs';
import UnitToggle from './UnitToggle';
import { editText, parseLength, convertText, formatLength } from '../services/lengthUnits';

const MIN_M = 1.01;    // the server takes more than 1 m
const MAX_M = 200;

export default function HouseSizeDialog({ visible, house, busy, onCancel, onSave }) {
  const { lengthUnit: unit } = usePrefs();
  const [w, setW] = useState('');
  const [l, setL] = useState('');
  const [scale, setScale] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!visible) return;
    setW(editText(house?.meta?.width, unit));
    setL(editText(house?.meta?.length, unit));
    setScale(false);
    setError(null);
  }, [visible]);

  const placed = (house?.sections || []).filter((x) => x?.meta?.x != null).length;
  const hadSize = house?.meta?.width != null && house?.meta?.length != null;

  const save = () => {
    const pw = parseLength(w, unit, { min: MIN_M, max: MAX_M, what: 'Width' });
    if (pw.error) { setError(pw.error); return; }
    const pl = parseLength(l, unit, { min: MIN_M, max: MAX_M, what: 'Length' });
    if (pl.error) { setError(pl.error); return; }
    onSave(pw.m, pl.m, scale && hadSize && placed > 0);
  };

  const field = (label, value, set) => (
    <View style={{ flex: 1 }}>
      <Text style={s.label}>{label} ({unit})</Text>
      <TextInput style={[s.input, error && { borderColor: COLORS.danger }]} value={value}
        onChangeText={(t) => { set(t); setError(null); }}
        keyboardType="decimal-pad" maxLength={7} selectTextOnFocus editable={!busy}
        accessibilityLabel={`${label} in ${unit === 'ft' ? 'feet' : 'metres'}`} />
    </View>
  );

  return (
    <Modal visible={!!visible} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView style={s.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[s.card, SHADOW.lg]} accessibilityViewIsModal>
          <Text style={s.title} accessibilityRole="header">House size</Text>
          <Text style={s.sub}>
            {house?.meta?.name || house?.houseId}
            {hadSize ? `, now ${formatLength(house.meta.width, unit)} x ${formatLength(house.meta.length, unit)}` : ''}
          </Text>

          <UnitToggle style={{ marginBottom: SPACE.md }}
            onChange={(from, to) => { setW((t) => convertText(t, from, to)); setL((t) => convertText(t, from, to)); }} />
          <View style={s.row}>
            {field('Width', w, setW)}
            {field('Length', l, setL)}
          </View>
          <Text style={error ? s.err : s.hint}>{error || ' '}</Text>

          {hadSize && placed > 0 && (
            <View style={s.scaleRow}>
              <View style={{ flex: 1 }}>
                <Text style={s.scaleTitle}>Move the sections to fit</Text>
                <Text style={s.scaleSub}>
                  Scales all {placed} placed sections with the house. Use it when they were
                  planned for the old size; leave it off for positions you measured.
                </Text>
              </View>
              <Switch value={scale} onValueChange={setScale} disabled={busy}
                trackColor={{ true: COLORS.primary, false: COLORS.border }}
                thumbColor={COLORS.bgCard}
                accessibilityLabel="Move the sections to fit the new size" />
            </View>
          )}

          <View style={s.btnRow}>
            <TouchableOpacity style={[s.btn, s.btnGhost]} onPress={onCancel} disabled={busy}
              accessibilityRole="button">
              <Text style={[s.btnTxt, { color: COLORS.textSecondary }]}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.btn, s.btnSave, busy && { opacity: 0.5 }]}
              onPress={save} disabled={busy} accessibilityRole="button">
              {busy
                ? <ActivityIndicator color={COLORS.textInverse} size="small" />
                : <Text style={[s.btnTxt, { color: COLORS.textInverse }]}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(28,25,23,0.45)', alignItems: 'center',
              justifyContent: 'center', padding: SPACE.xl },
  card:     { width: '100%', maxWidth: 400, backgroundColor: COLORS.bgCard,
              borderRadius: RADIUS.lg, padding: SPACE.xl },
  title:    { fontSize: 19, fontWeight: '800', color: COLORS.text },
  sub:      { color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: 2, marginBottom: SPACE.md },
  row:      { flexDirection: 'row', gap: SPACE.md },
  label:    { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary, marginBottom: 6 },
  input:    { minHeight: 50, borderWidth: 1.5, borderColor: COLORS.border, borderRadius: RADIUS.md,
              paddingHorizontal: SPACE.md, color: COLORS.text, fontSize: FONT.xl, fontWeight: '800',
              fontVariant: ['tabular-nums'] },
  hint:     { minHeight: 20, marginTop: SPACE.sm, color: COLORS.textSecondary, fontSize: FONT.sm },
  err:      { minHeight: 20, marginTop: SPACE.sm, color: COLORS.danger, fontSize: FONT.sm },
  scaleRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginTop: SPACE.sm,
              paddingTop: SPACE.md, borderTopWidth: 1, borderTopColor: COLORS.border },
  scaleTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  scaleSub: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: 2 },
  btnRow:   { flexDirection: 'row', gap: SPACE.md, marginTop: SPACE.lg },
  btn:      { flex: 1, minHeight: 48, borderRadius: RADIUS.md, alignItems: 'center',
              justifyContent: 'center' },
  btnGhost: { backgroundColor: COLORS.bgCardAlt },
  btnSave:  { backgroundColor: COLORS.primary },
  btnTxt:   { alignSelf: 'stretch', textAlign: 'center', fontSize: 16, fontWeight: '800' },
});
