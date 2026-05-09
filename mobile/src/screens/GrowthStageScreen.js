import React, { useState, useRef, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Dimensions, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const { width } = Dimensions.get('window');

const GrowthStageScreen = ({ navigation }) => {
  const [currentStage, setCurrentStage] = useState(2);
  const fadeAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  const stages = [
    { name: 'Seedling', duration: '0-6 mo' }, { name: 'Juvenile', duration: '6-18 mo' },
    { name: 'Mature', duration: '18-36 mo' }, { name: 'Blooming', duration: 'Seasonal' },
    { name: 'Dormant', duration: 'Post-bloom' },
  ];

  const careData = [
    { water: 'Mist 2x/day', light: '2-5k lux', temp: '24-28°C', fert: '1/4 str.' },
    { water: 'Daily soak', light: '5-10k lux', temp: '24-30°C', fert: '1/2 str.' },
    { water: 'Soak when dry', light: '10-15k lux', temp: '22-32°C', fert: 'Full str.' },
    { water: 'Regular soak', light: '10-15k lux', temp: '20-30°C', fert: '1/2 str.' },
    { water: 'Reduce freq.', light: '5-8k lux', temp: '18-28°C', fert: 'Suspend' },
  ];

  const care = careData[currentStage];

  return (
    <View style={styles.container}>
      <ScreenHeader title="Growth Stage" subtitle="Lifecycle" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          <View style={[styles.timelineCard, SHADOW.sm]}>
            <View style={styles.timeline}>
              {stages.map((stage, i) => (
                <TouchableOpacity key={i} onPress={() => setCurrentStage(i)} style={styles.step}>
                  <View style={[styles.dot, i < currentStage && styles.dotDone, i === currentStage && styles.dotCurrent]}>
                    {i < currentStage && <Ionicons name="checkmark" size={12} color="#FFF" />}
                    {i === currentStage && <View style={styles.dotInner} />}
                  </View>
                  {i < stages.length - 1 && <View style={[styles.line, i < currentStage && styles.lineDone]} />}
                  <Text style={[styles.dotLabel, i === currentStage && styles.dotLabelActive]}>{stage.name}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          <View style={[styles.stageCard, SHADOW.sm]}>
            <View style={styles.stageRow}>
              <View><Text style={styles.stageName}>{stages[currentStage].name}</Text><Text style={styles.stageDur}>{stages[currentStage].duration}</Text></View>
              <View style={styles.stageNum}><Text style={styles.stageNumText}>{currentStage + 1}/5</Text></View>
            </View>
          </View>

          <Text style={styles.sectionTitle}>Care Protocol</Text>
          <View style={[styles.careCard, SHADOW.sm]}>
            {[
              { label: 'Irrigation', value: care.water, icon: 'water', color: COLORS.primary },
              { label: 'Light', value: care.light, icon: 'sunny', color: COLORS.light },
              { label: 'Temperature', value: care.temp, icon: 'thermometer', color: COLORS.temperature },
              { label: 'Fertilizer', value: care.fert, icon: 'flask', color: COLORS.fertilizer },
            ].map((row, i) => (
              <View key={i} style={[styles.careRow, i < 3 && styles.careRowBorder]}>
                <View style={styles.careLeft}>
                  <View style={[styles.careIcon, { backgroundColor: `${row.color}10` }]}><Ionicons name={row.icon} size={15} color={row.color} /></View>
                  <Text style={styles.careLabel}>{row.label}</Text>
                </View>
                <Text style={[styles.careValue, { color: row.color }]}>{row.value}</Text>
              </View>
            ))}
          </View>

          <Text style={styles.sectionTitle}>Milestones</Text>
          {[
            { date: 'Apr 01', event: 'Mounted on substrate', done: true },
            { date: 'Apr 10', event: 'New root tip observed', done: true },
            { date: 'Apr 20', event: 'New leaf emergence', done: true },
            { date: 'May 05', event: 'Root system established', done: false },
            { date: 'May 15', event: 'Flower spike expected', done: false },
          ].map((m, i) => (
            <View key={i} style={styles.milestoneRow}>
              <Text style={styles.milestoneDate}>{m.date}</Text>
              <View style={[styles.milestoneDot, { backgroundColor: m.done ? COLORS.success : COLORS.border }]}>
                {m.done && <Ionicons name="checkmark" size={10} color="#FFF" />}
              </View>
              <Text style={[styles.milestoneText, !m.done && { color: COLORS.textTertiary }]}>{m.event}</Text>
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
  timelineCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xl, marginBottom: SPACE.xl },
  timeline: { flexDirection: 'row', justifyContent: 'space-between' },
  step: { alignItems: 'center', flex: 1 },
  dot: { width: 26, height: 26, borderRadius: 13, borderWidth: 2, borderColor: COLORS.border, alignItems: 'center', justifyContent: 'center', marginBottom: SPACE.sm, backgroundColor: COLORS.bgCard },
  dotDone: { borderColor: COLORS.success, backgroundColor: COLORS.success },
  dotCurrent: { borderColor: COLORS.primary, backgroundColor: COLORS.primaryDim },
  dotInner: { width: 8, height: 8, borderRadius: 4, backgroundColor: COLORS.primary },
  line: { position: 'absolute', top: 13, left: '60%', right: '-40%', height: 2, backgroundColor: COLORS.border, zIndex: -1 },
  lineDone: { backgroundColor: COLORS.success },
  dotLabel: { color: COLORS.textTertiary, fontSize: 9, fontWeight: '600', textAlign: 'center' },
  dotLabelActive: { color: COLORS.primary, fontWeight: '700' },
  stageCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xl, marginBottom: SPACE.xl },
  stageRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  stageName: { color: COLORS.text, fontSize: FONT.xl, fontWeight: '700' },
  stageDur: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2 },
  stageNum: { backgroundColor: COLORS.primaryDim, paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs, borderRadius: RADIUS.full },
  stageNumText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  careCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, overflow: 'hidden', marginBottom: SPACE.xl },
  careRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: SPACE.lg },
  careRowBorder: { borderBottomWidth: 1, borderBottomColor: COLORS.borderLight },
  careLeft: { flexDirection: 'row', alignItems: 'center' },
  careIcon: { width: 30, height: 30, borderRadius: RADIUS.sm - 2, alignItems: 'center', justifyContent: 'center', marginRight: SPACE.md },
  careLabel: { color: COLORS.textSecondary, fontSize: FONT.sm },
  careValue: { fontSize: FONT.sm, fontWeight: '700' },
  milestoneRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.md },
  milestoneDate: { color: COLORS.textTertiary, fontSize: FONT.xs, width: 44, fontVariant: ['tabular-nums'] },
  milestoneDot: { width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center', marginHorizontal: SPACE.sm },
  milestoneText: { color: COLORS.text, fontSize: FONT.sm, flex: 1 },
});

export default GrowthStageScreen;
