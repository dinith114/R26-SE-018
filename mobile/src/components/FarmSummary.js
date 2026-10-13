/**
 * The three-tile farm summary.
 *
 * The first version was three white boxes with grey labels, which read as dead
 * even when the farm was perfectly healthy. Two changes fix that:
 *
 *   1. Each tile carries its own tinted background and a filled icon chip, so
 *      the strip has colour whatever the numbers are.
 *   2. The third tile is semantic rather than a raw count — "All clear" with a
 *      green tick beats a grey "0", and it turns red the moment it matters.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACE, RADIUS, SHADOW } from '../config/theme';

function Tile({ icon, tint, value, label, sub }) {
  return (
    <View
      style={[s.tile, SHADOW.sm, { backgroundColor: `${tint}14` }]}
      accessible
      accessibilityLabel={`${value} ${label}${sub ? '. ' + sub : ''}`}>
      <View style={[s.chip, { backgroundColor: `${tint}26` }]}>
        <Ionicons name={icon} size={16} color={tint} />
      </View>
      <Text style={[s.value, { color: tint }]} numberOfLines={1}>{value}</Text>
      <Text style={s.label} numberOfLines={1}>{label}</Text>
    </View>
  );
}

export default function FarmSummary({ total = 0, reporting = 0, filling = 0, attention = 0 }) {
  const allReporting = total > 0 && reporting === total;

  return (
    <View style={s.row}>
      <Tile
        icon={allReporting ? 'leaf' : 'leaf-outline'}
        tint={allReporting ? COLORS.success : COLORS.warning}
        value={`${reporting}/${total}`}
        label="reporting"
      />
      <Tile
        icon={filling > 0 ? 'water' : 'water-outline'}
        tint={filling > 0 ? COLORS.info : COLORS.humidity}
        value={filling > 0 ? String(filling) : '-'}
        label={filling === 1 ? 'tray filling' : 'trays filling'}
      />
      <Tile
        icon={attention > 0 ? 'alert-circle' : 'checkmark-circle'}
        tint={attention > 0 ? COLORS.danger : COLORS.success}
        value={attention > 0 ? String(attention) : 'OK'}
        label={attention > 0 ? 'to do' : 'all clear'}
      />
    </View>
  );
}

const s = StyleSheet.create({
  row:   { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.lg },
  tile:  { flex: 1, alignItems: 'center', gap: 3, borderRadius: RADIUS.md,
           paddingVertical: SPACE.lg, paddingHorizontal: SPACE.xs },
  chip:  { width: 30, height: 30, borderRadius: 15,
           alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
  value: { fontSize: 20, fontWeight: '900', fontVariant: ['tabular-nums'] },
  label: { color: COLORS.textSecondary, fontSize: 11, fontWeight: '600' },
});
