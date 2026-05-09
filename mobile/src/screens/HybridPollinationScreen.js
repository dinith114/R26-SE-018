import React, { useRef, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const HybridPollinationScreen = ({ navigation }) => {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  const varieties = [
    { id: 1, name: 'V. coerulea', trait: 'Blue pigment', origin: 'Thailand', color: '#457B9D' },
    { id: 2, name: 'V. sanderiana', trait: 'Large bloom', origin: 'Philippines', color: '#C1666B' },
    { id: 3, name: 'V. tessellata', trait: 'Fragrance', origin: 'Sri Lanka', color: '#7B4F8A' },
    { id: 4, name: 'V. tricolor', trait: 'Patterned', origin: 'Java', color: '#C9A227' },
  ];

  const matrixLabels = ['COE', 'SAN', 'TES', 'TRI'];
  const matrixData = [['—','95','72','68'],['95','—','80','75'],['72','80','—','88'],['68','75','88','—']];

  const outcomes = [
    { cross: 'V. coerulea x V. sanderiana', result: 'V. Rothschildiana', rate: 95, trait: 'Large blue flowers' },
    { cross: 'V. tessellata x V. tricolor', result: 'V. Hybrid-T3', rate: 88, trait: 'Fragrant spotted' },
    { cross: 'V. coerulea x V. tessellata', result: 'V. Blue Mist', rate: 72, trait: 'Blue fragrant' },
  ];

  const getCellColor = (val) => { const n = parseInt(val); if (isNaN(n)) return COLORS.textTertiary; if (n >= 85) return COLORS.success; if (n >= 70) return COLORS.warning; return COLORS.danger; };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Hybrid Pollination" subtitle="Genetics" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          <Text style={styles.sectionTitle}>Parent Varieties</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: SPACE.xl }}>
            {varieties.map((v) => (
              <View key={v.id} style={[styles.varietyCard, SHADOW.sm]}>
                <View style={[styles.varietyLine, { backgroundColor: v.color }]} />
                <Text style={styles.varietyName}>{v.name}</Text>
                <Text style={styles.varietyTrait}>{v.trait}</Text>
                <View style={styles.originRow}>
                  <Ionicons name="location-outline" size={10} color={COLORS.textTertiary} />
                  <Text style={styles.varietyOrigin}>{v.origin}</Text>
                </View>
              </View>
            ))}
          </ScrollView>

          <Text style={styles.sectionTitle}>Compatibility Matrix</Text>
          <View style={[styles.matrixCard, SHADOW.sm]}>
            <View style={styles.matrixRow}><View style={styles.matrixCorner} />{matrixLabels.map((l, i) => (<Text key={i} style={styles.matrixHeader}>{l}</Text>))}</View>
            {matrixData.map((row, ri) => (
              <View key={ri} style={styles.matrixRow}>
                <Text style={styles.matrixRowLabel}>{matrixLabels[ri]}</Text>
                {row.map((val, ci) => (
                  <View key={ci} style={[styles.matrixCell, val !== '—' && { backgroundColor: `${getCellColor(val)}10` }]}>
                    <Text style={[styles.matrixVal, { color: getCellColor(val) }]}>{val}</Text>
                  </View>
                ))}
              </View>
            ))}
            <View style={styles.legend}>
              {[{ l: '85%+', c: COLORS.success }, { l: '70-84%', c: COLORS.warning }, { l: '<70%', c: COLORS.danger }].map((x, i) => (
                <View key={i} style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: x.c }]} /><Text style={styles.legendText}>{x.l}</Text></View>
              ))}
            </View>
          </View>

          <Text style={styles.sectionTitle}>Predicted Outcomes</Text>
          {outcomes.map((o, i) => (
            <View key={i} style={[styles.outcomeCard, SHADOW.sm]}>
              <View style={styles.outcomeHeader}>
                <View style={styles.crossRow}><Ionicons name="git-merge-outline" size={14} color={COLORS.textTertiary} /><Text style={styles.outcomeCross}>{o.cross}</Text></View>
                <Text style={[styles.outcomeRate, { color: getCellColor(String(o.rate)) }]}>{o.rate}%</Text>
              </View>
              <Text style={styles.outcomeResult}>{o.result}</Text>
              <Text style={styles.outcomeTrait}>Phenotype: {o.trait}</Text>
            </View>
          ))}
        </Animated.View>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  varietyCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginRight: SPACE.sm, width: 120 },
  varietyLine: { width: 18, height: 3, borderRadius: 2, marginBottom: SPACE.sm },
  varietyName: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', marginBottom: 2 },
  varietyTrait: { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: SPACE.sm },
  originRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  varietyOrigin: { color: COLORS.textTertiary, fontSize: 9 },
  matrixCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  matrixRow: { flexDirection: 'row', marginBottom: SPACE.xs },
  matrixCorner: { width: 32 },
  matrixHeader: { flex: 1, textAlign: 'center', color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 0.5, paddingVertical: SPACE.xs },
  matrixRowLabel: { width: 32, color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 0.5, alignSelf: 'center' },
  matrixCell: { flex: 1, alignItems: 'center', paddingVertical: SPACE.sm, borderRadius: RADIUS.sm - 2, marginHorizontal: 1 },
  matrixVal: { fontSize: FONT.sm, fontWeight: '700', fontVariant: ['tabular-nums'] },
  legend: { flexDirection: 'row', justifyContent: 'center', marginTop: SPACE.md, gap: SPACE.lg },
  legendItem: { flexDirection: 'row', alignItems: 'center' },
  legendDot: { width: 5, height: 5, borderRadius: 3, marginRight: 4 },
  legendText: { color: COLORS.textTertiary, fontSize: FONT.xs },
  outcomeCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm },
  outcomeHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.xs },
  crossRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  outcomeCross: { color: COLORS.textTertiary, fontSize: FONT.xs },
  outcomeRate: { fontSize: FONT.md, fontWeight: '800', fontVariant: ['tabular-nums'] },
  outcomeResult: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 2 },
  outcomeTrait: { color: COLORS.textTertiary, fontSize: FONT.xs },
});

export default HybridPollinationScreen;
