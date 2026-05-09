import React from 'react';
import { View, Text, StyleSheet, Dimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

const { width } = Dimensions.get('window');

const SensorCard = ({ title, value, unit, color, iconName }) => {
  return (
    <View style={[styles.card, SHADOW.sm]}>
      <View style={styles.topRow}>
        <Ionicons name={iconName} size={16} color={color} />
        <Text style={styles.title}>{title}</Text>
      </View>
      <View style={styles.valueRow}>
        <Text style={[styles.value, { color }]}>{value}</Text>
        <Text style={styles.unit}>{unit}</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    width: (width - 56) / 2,
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    padding: SPACE.lg,
    marginBottom: SPACE.sm,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginBottom: SPACE.md,
  },
  title: {
    color: COLORS.textTertiary,
    fontSize: FONT.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  value: {
    fontSize: 24,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  unit: {
    fontSize: FONT.sm,
    color: COLORS.textTertiary,
    marginLeft: 2,
    fontWeight: '500',
  },
});

export default SensorCard;
