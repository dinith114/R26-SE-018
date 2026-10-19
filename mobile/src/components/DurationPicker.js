/**
 * Choose how long a watering or a tray fill runs.
 *
 * Added 19 Oct 2026: lengths are the grower's (farm default 10 minutes, each
 * section's own Pour length), and a farmer pressing Water Now or Fill Tray
 * picks a length every time, starting from that default. Quick choices for the
 * usual lengths, minus and plus to nudge, and typed minutes and seconds for
 * anything else. When the house's master is on old firmware the server's
 * limit is shown here, before the pour, rather than discovered after it.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import {
  POUR_PRESETS, pourLabel, splitSecs, joinSecs, stepPour, litresLabel, limitNote,
} from '../services/pourLength';

export default function DurationPicker({ value, onChange, mlPerSec, limit, label }) {
  const parts = splitSecs(value);
  const [min, setMin] = useState(String(parts.min));
  const [sec, setSec] = useState(String(parts.sec));

  // Keep the boxes in step when a chip or a button changes the value.
  useEffect(() => {
    const p = splitSecs(value);
    setMin(String(p.min));
    setSec(String(p.sec));
  }, [value]);

  const typed = (m, s) => {
    setMin(m);
    setSec(s);
    const total = joinSecs(m, s);
    if (total != null) onChange(total);
  };

  const litres = litresLabel(value, mlPerSec);
  const note = limitNote(value, limit);
  const bad = joinSecs(min, sec) == null;

  return (
    <View style={s.wrap}>
      {!!label && <Text style={s.label}>{label}</Text>}

      <View style={s.valueRow}>
        <TouchableOpacity style={s.step} onPress={() => onChange(stepPour(value, -1))}
          accessibilityRole="button" accessibilityLabel="Shorter">
          <Ionicons name="remove" size={22} color={COLORS.primary} />
        </TouchableOpacity>
        <View style={s.valueBox} accessibilityLiveRegion="polite">
          <Text style={s.value}>{pourLabel(value)}</Text>
          {!!litres && <Text style={s.litres}>{litres}</Text>}
        </View>
        <TouchableOpacity style={s.step} onPress={() => onChange(stepPour(value, 1))}
          accessibilityRole="button" accessibilityLabel="Longer">
          <Ionicons name="add" size={22} color={COLORS.primary} />
        </TouchableOpacity>
      </View>

      <View style={s.chips}>
        {POUR_PRESETS.map((p) => {
          const on = p === value;
          return (
            <TouchableOpacity key={p} style={[s.chip, on && s.chipOn]} onPress={() => onChange(p)}
              accessibilityRole="button" accessibilityState={{ selected: on }}>
              <Text style={[s.chipTxt, on && s.chipTxtOn]}>{pourLabel(p)}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      <View style={s.typeRow}>
        <View style={s.typeBox}>
          <TextInput style={[s.input, bad && s.inputBad]} value={min} keyboardType="number-pad"
            onChangeText={(v) => typed(v, sec)} maxLength={2} selectTextOnFocus
            accessibilityLabel="Minutes" maxFontSizeMultiplier={1.15} />
          <Text style={s.unit}>min</Text>
        </View>
        <View style={s.typeBox}>
          <TextInput style={[s.input, bad && s.inputBad]} value={sec} keyboardType="number-pad"
            onChangeText={(v) => typed(min, v)} maxLength={2} selectTextOnFocus
            accessibilityLabel="Seconds" maxFontSizeMultiplier={1.15} />
          <Text style={s.unit}>s</Text>
        </View>
      </View>
      {bad && <Text style={s.warn}>Choose between 1 second and 60 minutes.</Text>}
      {!!note && <Text style={s.warn}>{note}</Text>}
    </View>
  );
}

const s = StyleSheet.create({
  wrap:     { gap: SPACE.sm, marginTop: SPACE.sm },
  label:    { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  valueRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  step:     { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
              backgroundColor: COLORS.primaryDim },
  valueBox: { flex: 1, alignItems: 'center' },
  value:    { color: COLORS.text, fontSize: FONT.xxl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  litres:   { color: COLORS.textTertiary, fontSize: FONT.sm },
  chips:    { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, justifyContent: 'center' },
  chip:     { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs + 2, borderRadius: RADIUS.full,
              borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bgCard },
  chipOn:   { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipTxt:  { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  chipTxtOn:{ color: '#FFF' },
  typeRow:  { flexDirection: 'row', gap: SPACE.md, justifyContent: 'center' },
  typeBox:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.xs },
  input:    { width: 56, textAlign: 'center', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
              borderWidth: 1, borderColor: COLORS.border, paddingVertical: SPACE.sm,
              color: COLORS.text, fontSize: FONT.md, fontVariant: ['tabular-nums'] },
  inputBad: { borderColor: COLORS.danger },
  unit:     { color: COLORS.textTertiary, fontSize: FONT.sm },
  warn:     { color: COLORS.warning, fontSize: FONT.sm, lineHeight: 17, textAlign: 'center' },
});
