/**
 * A read interval of the farmer's own: a number, seconds or minutes.
 *
 * Centred like RenameDialog, not a bottom sheet: a text box at the bottom of
 * the screen is exactly where the keyboard opens. The limits (5 s to 60 min)
 * are the firmware's and the server's; the rules live in services/readInterval.js.
 */
import React, { useEffect, useState } from 'react';
import {
  Modal, View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from 'react-native';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { formatInterval, parseCustom, splitForEdit } from '../services/readInterval';

export default function IntervalDialog({ visible, initialMs, busy, onCancel, onSave }) {
  const [text, setText] = useState('');
  const [unit, setUnit] = useState('min');
  const [error, setError] = useState(null);

  // Re-seed each time it opens, from the value the node has now.
  useEffect(() => {
    if (!visible) return;
    const seed = splitForEdit(initialMs);
    setText(seed.text);
    setUnit(seed.unit);
    setError(null);
  }, [visible]);

  const parsed = parseCustom(text, unit);
  const save = () => {
    if (parsed.error) { setError(parsed.error); return; }
    onSave(parsed.ms);
  };

  return (
    <Modal visible={!!visible} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView style={s.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[s.card, SHADOW.lg]} accessibilityViewIsModal>
          <Text style={s.title} accessibilityRole="header">Custom interval</Text>
          <Text style={s.label}>Wait between readings (5 seconds to 60 minutes)</Text>

          <View style={s.row}>
            <TextInput
              style={[s.input, error && { borderColor: COLORS.danger }]}
              value={text}
              onChangeText={(t) => { setText(t); setError(null); }}
              keyboardType="decimal-pad"
              placeholder={unit === 's' ? '90' : '2'}
              placeholderTextColor={COLORS.textTertiary}
              maxLength={6}
              autoFocus
              selectTextOnFocus
              returnKeyType="done"
              onSubmitEditing={save}
              editable={!busy}
              accessibilityLabel={`Interval in ${unit === 's' ? 'seconds' : 'minutes'}`} />
            <View style={s.units} accessibilityRole="radiogroup">
              {[['s', 'seconds'], ['min', 'minutes']].map(([u, label]) => {
                const on = unit === u;
                return (
                  <TouchableOpacity key={u} style={[s.unit, on && s.unitOn]}
                    onPress={() => { setUnit(u); setError(null); }}
                    accessibilityRole="radio" accessibilityState={{ checked: on }}>
                    <Text style={[s.unitTxt, on && s.unitTxtOn]}>{label}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>

          <Text style={error ? s.err : s.hint}>
            {error || (parsed.ms ? `Reads every ${formatInterval(parsed.ms)}.` : ' ')}
          </Text>

          <View style={s.btnRow}>
            <TouchableOpacity style={[s.btn, s.btnGhost]} onPress={onCancel} disabled={busy}
              accessibilityRole="button">
              <Text style={[s.btnTxt, { color: COLORS.textSecondary }]}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.btn, s.btnSave, busy && { opacity: 0.5 }]}
              onPress={save} disabled={busy} accessibilityRole="button"
              accessibilityLabel={parsed.ms ? `Save, every ${formatInterval(parsed.ms)}` : 'Save'}>
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
  title:    { fontSize: 19, fontWeight: '800', color: COLORS.text, marginBottom: SPACE.sm },
  label:    { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary, marginBottom: SPACE.md,
              lineHeight: 18 },
  row:      { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  input:    { flex: 1, minHeight: 50, borderWidth: 1.5, borderColor: COLORS.border,
              borderRadius: RADIUS.md, paddingHorizontal: SPACE.md, color: COLORS.text,
              fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  units:    { flex: 1.4, flexDirection: 'row', padding: 3, borderRadius: RADIUS.md,
              backgroundColor: COLORS.bgCardAlt },
  unit:     { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
              borderRadius: RADIUS.sm },
  unitOn:   { backgroundColor: COLORS.bgCard },
  // stretched across the segment: sized to its word it clips with Bold text on
  unitTxt:  { alignSelf: 'stretch', textAlign: 'center', color: COLORS.textSecondary,
              fontSize: FONT.sm, fontWeight: '700' },
  unitTxtOn:{ color: COLORS.primary, fontWeight: '800' },
  hint:     { minHeight: 20, marginTop: SPACE.sm, color: COLORS.textSecondary, fontSize: FONT.sm },
  err:      { minHeight: 20, marginTop: SPACE.sm, color: COLORS.danger, fontSize: FONT.sm },
  btnRow:   { flexDirection: 'row', gap: SPACE.md, marginTop: SPACE.lg },
  btn:      { flex: 1, minHeight: 48, borderRadius: RADIUS.md, alignItems: 'center',
              justifyContent: 'center' },
  btnGhost: { backgroundColor: COLORS.bgCardAlt },
  btnSave:  { backgroundColor: COLORS.primary },
  btnTxt:   { alignSelf: 'stretch', textAlign: 'center', fontSize: 16, fontWeight: '800' },
});
