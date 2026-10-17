/**
 * Metres or feet, for any screen where a length is typed.
 *
 * One choice for the whole app (config/prefs.js): a farmer who measured in feet
 * switches once. `onChange(from, to)` lets a form re-express what is already
 * typed, so the box keeps meaning the same length.
 */
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { COLORS, FONT, RADIUS } from '../config/theme';
import { usePrefs } from '../config/prefs';

const LABELS = { m: 'metres', ft: 'feet' };

export default function UnitToggle({ onChange, style }) {
  const { lengthUnit, setLengthUnit } = usePrefs();
  return (
    <View style={[s.wrap, style]} accessibilityRole="radiogroup" accessibilityLabel="Length unit">
      {['m', 'ft'].map((u) => {
        const on = u === lengthUnit;
        return (
          <TouchableOpacity key={u} style={[s.seg, on && s.segOn]} activeOpacity={0.75}
            onPress={() => {
              if (on) return;
              onChange?.(lengthUnit, u);
              setLengthUnit(u);
            }}
            accessibilityRole="radio" accessibilityState={{ checked: on }}
            accessibilityLabel={LABELS[u]}>
            <Text style={[s.txt, on && s.txtOn]}>{LABELS[u]}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  wrap:  { flexDirection: 'row', padding: 3, borderRadius: RADIUS.md,
           backgroundColor: COLORS.bgCardAlt, alignSelf: 'stretch' },
  seg:   { flex: 1, minHeight: 36, alignItems: 'center', justifyContent: 'center',
           borderRadius: RADIUS.sm },
  segOn: { backgroundColor: COLORS.bgCard },
  // stretched across the segment: sized to its word it clips with Bold text on
  txt:   { alignSelf: 'stretch', textAlign: 'center', color: COLORS.textSecondary,
           fontSize: FONT.sm, fontWeight: '700' },
  txtOn: { color: COLORS.primary, fontWeight: '800' },
});
