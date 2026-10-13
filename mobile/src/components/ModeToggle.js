/**
 * Simple / Expert switch for the My Farm tab.
 *
 * Deliberately NOT part of ScreenHeader: every screen shares that header, and
 * only this tab has two modes. This sits in the page body instead, so My Farm
 * keeps exactly the same chrome as Detect, Hybrid and Growth.
 *
 * It stays out of Settings because it is the control users reach for most, and
 * a farmer who lands in Expert by accident needs an obvious way back.
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { usePrefs } from '../config/prefs';
import { COLORS, SPACE, RADIUS, SHADOW } from '../config/theme';

const OPTIONS = [
  { value: false, label: 'Simple', hint: 'Plain words and big text' },
  { value: true,  label: 'Expert', hint: 'Full sensor detail' },
];

export default function ModeToggle({ style }) {
  const { expert, setExpert } = usePrefs();

  return (
    <View style={[s.wrap, style]} accessibilityRole="tablist">
      {OPTIONS.map((o) => {
        const on = expert === o.value;
        return (
          <TouchableOpacity
            key={o.label}
            style={[s.btn, on && s.btnOn, on && SHADOW.sm]}
            onPress={() => setExpert(o.value)}
            activeOpacity={0.8}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            accessibilityLabel={`${o.label} view. ${o.hint}`}>
            <Text style={[s.text, on && s.textOn]}>{o.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignSelf: 'center',
    backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.full,
    padding: 4,
    marginBottom: SPACE.lg,
  },
  btn:   { paddingVertical: 8, paddingHorizontal: 26, borderRadius: RADIUS.full },
  btnOn: { backgroundColor: COLORS.bgCard },
  text:  { fontSize: 14, fontWeight: '700', color: COLORS.textTertiary },
  textOn:{ color: COLORS.primary },
});
