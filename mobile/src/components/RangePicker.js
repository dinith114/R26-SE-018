/**
 * The chart's range menu.
 *
 * "Last 24 Hours" used to be a fixed heading, so the farmer could not look back
 * across a hot spell or compare this week with last. This turns it into the
 * control it looked like it should be.
 *
 * Implemented as a Modal list rather than a native picker so it looks and
 * behaves identically on Android and iOS, and so the options can carry a tick
 * for the current choice.
 */
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACE, RADIUS, SHADOW } from '../config/theme';

export default function RangePicker({ options = [], value, onChange, disabled }) {
  const [open, setOpen] = useState(false);
  const current = options.find(o => o.hours === value) || options[0];

  return (
    <>
      <TouchableOpacity
        style={[s.btn, disabled && { opacity: 0.5 }]}
        onPress={() => setOpen(true)}
        disabled={disabled}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityLabel={`Time range: ${current?.label}. Tap to change.`}>
        <Text style={s.btnText}>{current?.label}</Text>
        <Ionicons name="chevron-down" size={15} color={COLORS.primary} />
      </TouchableOpacity>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={s.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={[s.sheet, SHADOW.lg]} onPress={e => e.stopPropagation()}>
            <Text style={s.title} accessibilityRole="header">Show readings from</Text>
            {options.map(o => {
              const on = o.hours === value;
              return (
                <TouchableOpacity
                  key={o.hours}
                  style={[s.opt, on && s.optOn]}
                  onPress={() => { onChange(o); setOpen(false); }}
                  activeOpacity={0.7}
                  accessibilityRole="menuitem"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={o.label}>
                  <Text style={[s.optText, on && s.optTextOn]}>{o.label}</Text>
                  {on && <Ionicons name="checkmark" size={19} color={COLORS.primary} />}
                </TouchableOpacity>
              );
            })}
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const s = StyleSheet.create({
  btn:     { flexDirection: 'row', alignItems: 'center', gap: 4,
             paddingVertical: 6, paddingHorizontal: SPACE.md,
             borderRadius: RADIUS.full, backgroundColor: COLORS.primaryDim },
  btnText: { color: COLORS.primary, fontSize: 13, fontWeight: '700' },

  backdrop: { flex: 1, backgroundColor: 'rgba(28,25,23,0.45)',
              alignItems: 'center', justifyContent: 'center', padding: SPACE.xl },
  sheet:    { width: '100%', maxWidth: 380, backgroundColor: COLORS.bgCard,
              borderRadius: RADIUS.lg, padding: SPACE.lg },
  title:    { fontSize: 16, fontWeight: '800', color: COLORS.text, marginBottom: SPACE.md },
  opt:      { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
              paddingVertical: SPACE.md + 2, paddingHorizontal: SPACE.md,
              borderRadius: RADIUS.md },
  optOn:    { backgroundColor: COLORS.primaryDim },
  optText:  { fontSize: 16, color: COLORS.text },
  optTextOn:{ color: COLORS.primary, fontWeight: '800' },
});
