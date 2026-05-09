import React, { useRef, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const DiseaseDetectionScreen = ({ navigation }) => {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  const diseases = [
    { name: 'Black Rot', risk: 'High', color: COLORS.danger, icon: 'alert-circle', desc: 'Fungal — black lesions on leaves' },
    { name: 'Root Rot', risk: 'Medium', color: COLORS.warning, icon: 'warning', desc: 'Overwatering — root decay' },
    { name: 'Leaf Spot', risk: 'Low', color: COLORS.info, icon: 'information-circle', desc: 'Bacterial — surface spots' },
    { name: 'Crown Rot', risk: 'Medium', color: COLORS.warning, icon: 'warning', desc: 'Water accumulation in crown' },
  ];

  return (
    <View style={styles.container}>
      <ScreenHeader title="Disease Detection" subtitle="AI Diagnosis" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          <TouchableOpacity activeOpacity={0.7} style={[styles.captureCard, SHADOW.md]}>
            <View style={styles.captureIcon}>
              <Ionicons name="camera" size={28} color={COLORS.info} />
            </View>
            <Text style={styles.captureTitle}>Capture Image</Text>
            <Text style={styles.captureDesc}>Take a photo of the affected area for AI analysis</Text>
            <View style={styles.captureBtn}>
              <Ionicons name="camera-outline" size={16} color="#FFF" />
              <Text style={styles.captureBtnText}>Open Camera</Text>
            </View>
          </TouchableOpacity>

          <View style={[styles.card, SHADOW.sm]}>
            <View style={styles.healthRow}>
              <View>
                <Text style={styles.cardTitle}>Plant Health</Text>
                <Text style={styles.cardSub}>Last scan: 2 hours ago</Text>
              </View>
              <View style={styles.scoreCircle}>
                <Text style={styles.scoreText}>85</Text>
              </View>
            </View>
            <View style={styles.healthBar}>
              <View style={[styles.healthFill, { width: '85%' }]} />
            </View>
          </View>

          <Text style={styles.sectionTitle}>Disease Library</Text>
          {diseases.map((d, i) => (
            <TouchableOpacity key={i} style={[styles.diseaseRow, SHADOW.sm]} activeOpacity={0.7}>
              <View style={[styles.diseaseIcon, { backgroundColor: `${d.color}10` }]}>
                <Ionicons name={d.icon} size={18} color={d.color} />
              </View>
              <View style={styles.diseaseInfo}>
                <Text style={styles.diseaseName}>{d.name}</Text>
                <Text style={styles.diseaseDesc}>{d.desc}</Text>
              </View>
              <View style={[styles.riskBadge, { backgroundColor: `${d.color}10` }]}>
                <Text style={[styles.riskText, { color: d.color }]}>{d.risk}</Text>
              </View>
            </TouchableOpacity>
          ))}

          <View style={[styles.tipsCard, SHADOW.sm]}>
            <View style={styles.tipsHeader}>
              <Ionicons name="bulb-outline" size={16} color={COLORS.warning} />
              <Text style={styles.tipsTitle}>Prevention Tips</Text>
            </View>
            {['Ensure good air circulation around root system', 'Avoid water pooling in leaf crown', 'Sterilize cutting tools between use', 'Quarantine new orchids for 14 days'].map((tip, i) => (
              <View key={i} style={styles.tipRow}>
                <Ionicons name="checkmark" size={14} color={COLORS.success} />
                <Text style={styles.tipText}>{tip}</Text>
              </View>
            ))}
          </View>
        </Animated.View>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },
  captureCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xxl, alignItems: 'center', marginBottom: SPACE.xl },
  captureIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: COLORS.infoDim, alignItems: 'center', justifyContent: 'center', marginBottom: SPACE.md },
  captureTitle: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '700', marginBottom: SPACE.xs },
  captureDesc: { color: COLORS.textTertiary, fontSize: FONT.sm, textAlign: 'center', marginBottom: SPACE.lg },
  captureBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.info, paddingHorizontal: SPACE.xl, paddingVertical: SPACE.md, borderRadius: RADIUS.full },
  captureBtnText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },
  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  healthRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md },
  cardTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  cardSub: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  scoreCircle: { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.successDim, alignItems: 'center', justifyContent: 'center' },
  scoreText: { color: COLORS.success, fontSize: FONT.xl, fontWeight: '800' },
  healthBar: { height: 4, backgroundColor: COLORS.bgCardAlt, borderRadius: 2, overflow: 'hidden' },
  healthFill: { height: '100%', backgroundColor: COLORS.success, borderRadius: 2 },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  diseaseRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm },
  diseaseIcon: { width: 38, height: 38, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center', marginRight: SPACE.md },
  diseaseInfo: { flex: 1 },
  diseaseName: { color: COLORS.text, fontSize: FONT.md, fontWeight: '600' },
  diseaseDesc: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  riskBadge: { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs, borderRadius: RADIUS.full },
  riskText: { fontSize: FONT.xs, fontWeight: '700' },
  tipsCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.md },
  tipsHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.md },
  tipsTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  tipRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm, marginBottom: SPACE.sm },
  tipText: { color: COLORS.textSecondary, fontSize: FONT.sm, flex: 1, lineHeight: 20 },
});

export default DiseaseDetectionScreen;
