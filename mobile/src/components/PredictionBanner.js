import React, { useRef, useEffect } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

const PredictionBanner = ({ waterNeeded, fertilizerNeeded, confidence }) => {
  const slideAnim = useRef(new Animated.Value(15)).current;
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slideAnim, { toValue: 0, tension: 60, friction: 10, useNativeDriver: true }),
      Animated.timing(fadeAnim, { toValue: 1, duration: 300, useNativeDriver: true }),
    ]).start();
  }, [waterNeeded, fertilizerNeeded]);

  const needsWater = waterNeeded === 'Yes';
  const needsFert = fertilizerNeeded === 'Yes';
  const hasAction = needsWater || needsFert;
  const statusColor = hasAction ? COLORS.warning : COLORS.success;

  let statusText = 'All systems optimal';
  if (needsWater && needsFert) statusText = 'Water + Fertilizer needed';
  else if (needsWater) statusText = 'Watering recommended';
  else if (needsFert) statusText = 'Fertilizing recommended';

  return (
    <Animated.View style={[styles.container, SHADOW.sm, { transform: [{ translateY: slideAnim }], opacity: fadeAnim }]}>
      <View style={styles.header}>
        <View style={styles.labelRow}>
          <Ionicons name="analytics-outline" size={14} color={statusColor} />
          <Text style={styles.label}>AI PREDICTION</Text>
        </View>
        {confidence > 0 && <Text style={[styles.confidence, { color: statusColor }]}>{confidence.toFixed(0)}%</Text>}
      </View>
      <Text style={[styles.status, { color: statusColor }]}>{statusText}</Text>
      {confidence > 0 && (
        <View style={styles.barBg}>
          <View style={[styles.barFill, { width: `${Math.min(confidence, 100)}%`, backgroundColor: statusColor }]} />
        </View>
      )}
      <View style={styles.chipRow}>
        <View style={[styles.chip, { backgroundColor: needsWater ? COLORS.warningDim : COLORS.successDim }]}>
          <Ionicons name={needsWater ? 'water' : 'checkmark-circle'} size={13} color={needsWater ? COLORS.warning : COLORS.success} />
          <Text style={[styles.chipText, { color: needsWater ? COLORS.warning : COLORS.success }]}>Water: {needsWater ? 'Needed' : 'OK'}</Text>
        </View>
        <View style={[styles.chip, { backgroundColor: needsFert ? COLORS.warningDim : COLORS.successDim }]}>
          <Ionicons name={needsFert ? 'flask' : 'checkmark-circle'} size={13} color={needsFert ? COLORS.warning : COLORS.success} />
          <Text style={[styles.chipText, { color: needsFert ? COLORS.warning : COLORS.success }]}>Fert: {needsFert ? 'Needed' : 'OK'}</Text>
        </View>
      </View>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  container: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xl },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.xs },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  label: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 1.2 },
  confidence: { fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  status: { fontSize: FONT.lg, fontWeight: '700', marginBottom: SPACE.md },
  barBg: { width: '100%', height: 3, backgroundColor: COLORS.bgCardAlt, borderRadius: 2, overflow: 'hidden', marginBottom: SPACE.md },
  barFill: { height: '100%', borderRadius: 2 },
  chipRow: { flexDirection: 'row', gap: SPACE.sm },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm, borderRadius: RADIUS.full, flex: 1, justifyContent: 'center' },
  chipText: { fontSize: FONT.xs, fontWeight: '700' },
});

export default PredictionBanner;
