import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Switch, Dimensions, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import SensorCard from '../components/SensorCard';
import PredictionBanner from '../components/PredictionBanner';

const WateringScreen = ({ navigation }) => {
  const [sensorData, setSensorData] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [autoWater, setAutoWater] = useState(false);
  const [autoFert, setAutoFert] = useState(false);
  const [activeTab, setActiveTab] = useState('water');
  const fadeAnim = useRef(new Animated.Value(0)).current;

  const [schedules, setSchedules] = useState({
    water: [
      { id: 1, time: '06:00', label: 'Morning cycle', enabled: true },
      { id: 2, time: '18:00', label: 'Evening cycle', enabled: true },
    ],
    fertilizer: [
      { id: 1, time: '07:00', label: 'NPK 20-20-20 (weekly)', enabled: true },
      { id: 2, time: '07:00', label: 'Calcium supplement (bi-weekly)', enabled: false },
    ],
  });

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
    const latestRef = ref(database, 'latest');
    const unsubLatest = onValue(latestRef, (snapshot) => { const val = snapshot.val(); if (val) setSensorData(val); });
    const predRef = ref(database, 'prediction');
    const unsubPred = onValue(predRef, (snapshot) => { const val = snapshot.val(); if (val) setPrediction(val); });
    return () => { unsubLatest(); unsubPred(); };
  }, []);

  const toggleSchedule = (type, id) => {
    setSchedules(prev => ({ ...prev, [type]: prev[type].map(s => s.id === id ? { ...s, enabled: !s.enabled } : s) }));
  };

  const isWater = activeTab === 'water';
  const accentColor = isWater ? COLORS.primary : COLORS.fertilizer;

  return (
    <View style={styles.container}>
      <ScreenHeader title="Care Management" subtitle="Watering & Fertilizing" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          <View style={[styles.tabBar, SHADOW.sm]}>
            {['water', 'fertilizer'].map((tab) => (
              <TouchableOpacity key={tab} style={[styles.tab, activeTab === tab && styles.tabActive]} onPress={() => setActiveTab(tab)}>
                <Ionicons name={tab === 'water' ? 'water-outline' : 'flask-outline'} size={15} color={activeTab === tab ? COLORS.primary : COLORS.textTertiary} />
                <Text style={[styles.tabText, activeTab === tab && styles.tabTextActive]}>{tab === 'water' ? 'Irrigation' : 'Fertilizing'}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {prediction && <PredictionBanner waterNeeded={prediction.waterNeeded} fertilizerNeeded={prediction.fertilizerNeeded || 'No'} confidence={prediction.confidence} />}

          <TouchableOpacity activeOpacity={0.7} style={[styles.actionBtn, SHADOW.md, { backgroundColor: accentColor }]}>
            <Ionicons name={isWater ? 'water' : 'flask'} size={20} color="#FFF" />
            <View style={{ flex: 1 }}>
              <Text style={styles.actionTitle}>{isWater ? 'Start Irrigation' : 'Apply Fertilizer'}</Text>
              <Text style={styles.actionSub}>{isWater ? 'Manual · 30s burst' : 'Manual · NPK solution'}</Text>
            </View>
            <Ionicons name="arrow-forward" size={18} color="rgba(255,255,255,0.6)" />
          </TouchableOpacity>

          <View style={[styles.card, SHADOW.sm]}>
            <View style={styles.toggleRow}>
              <View style={styles.toggleLeft}>
                <Ionicons name="hardware-chip-outline" size={18} color={accentColor} />
                <View style={{ marginLeft: SPACE.md }}>
                  <Text style={styles.toggleTitle}>{isWater ? 'Auto-Irrigation' : 'Auto-Fertilizing'}</Text>
                  <Text style={styles.toggleDesc}>ML triggers automatically</Text>
                </View>
              </View>
              <Switch value={isWater ? autoWater : autoFert} onValueChange={isWater ? setAutoWater : setAutoFert}
                trackColor={{ false: COLORS.border, true: `${accentColor}40` }} thumbColor={(isWater ? autoWater : autoFert) ? accentColor : COLORS.textTertiary} />
            </View>
          </View>

          <Text style={styles.sectionTitle}>Current Conditions</Text>
          <View style={styles.grid}>
            <SensorCard title="Temp" value={sensorData?.temperature?.toFixed(1) ?? '--'} unit="°C" color={COLORS.temperature} iconName="thermometer-outline" />
            <SensorCard title="Humidity" value={sensorData?.humidity?.toFixed(1) ?? '--'} unit="%" color={COLORS.humidity} iconName="water-outline" />
            <SensorCard title="Soil" value={sensorData?.soilMoisturePct?.toFixed(1) ?? '--'} unit="%" color={COLORS.soil} iconName="leaf-outline" />
            <SensorCard title="Elapsed" value={sensorData?.hoursSinceWater?.toFixed(1) ?? '--'} unit="hrs" color={accentColor} iconName="timer-outline" />
          </View>

          <Text style={styles.sectionTitle}>{isWater ? 'Irrigation' : 'Fertilizer'} Schedule</Text>
          {schedules[activeTab].map((item) => (
            <View key={item.id} style={[styles.scheduleRow, SHADOW.sm]}>
              <View style={[styles.timeBadge, { backgroundColor: `${accentColor}10` }]}>
                <Text style={[styles.timeText, { color: accentColor }]}>{item.time}</Text>
              </View>
              <Text style={styles.scheduleLabel}>{item.label}</Text>
              <Switch value={item.enabled} onValueChange={() => toggleSchedule(activeTab, item.id)}
                trackColor={{ false: COLORS.border, true: `${COLORS.success}40` }} thumbColor={item.enabled ? COLORS.success : COLORS.textTertiary} />
            </View>
          ))}

          <Text style={styles.sectionTitle}>Activity</Text>
          {[
            { time: '2h ago', action: 'Auto-irrigated', detail: '30s · ML', icon: 'water', color: COLORS.primary },
            { time: '6h ago', action: 'Fertilizer applied', detail: 'NPK · Schedule', icon: 'flask', color: COLORS.fertilizer },
            { time: '8h ago', action: 'Manual irrigation', detail: '45s · User', icon: 'hand-left', color: COLORS.info },
          ].map((item, i) => (
            <View key={i} style={styles.logRow}>
              <View style={[styles.logIcon, { backgroundColor: `${item.color}10` }]}>
                <Ionicons name={item.icon} size={14} color={item.color} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.logAction}>{item.action}</Text>
                <Text style={styles.logDetail}>{item.detail}</Text>
              </View>
              <Text style={styles.logTime}>{item.time}</Text>
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
  tabBar: { flexDirection: 'row', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: 3, marginBottom: SPACE.xl },
  tab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, paddingVertical: SPACE.md, borderRadius: RADIUS.sm - 2 },
  tabActive: { backgroundColor: COLORS.bg },
  tabText: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },
  tabTextActive: { color: COLORS.primary, fontWeight: '700' },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, borderRadius: RADIUS.sm, padding: SPACE.lg, marginVertical: SPACE.lg },
  actionTitle: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  actionSub: { color: 'rgba(255,255,255,0.7)', fontSize: FONT.xs, marginTop: 1 },
  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  toggleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  toggleLeft: { flexDirection: 'row', alignItems: 'center' },
  toggleTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '600' },
  toggleDesc: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', marginBottom: SPACE.xl },
  scheduleRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  timeBadge: { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs, borderRadius: RADIUS.sm - 2, marginRight: SPACE.md },
  timeText: { fontSize: FONT.sm, fontWeight: '700', fontVariant: ['tabular-nums'] },
  scheduleLabel: { color: COLORS.textSecondary, fontSize: FONT.sm, flex: 1 },
  logRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.md },
  logIcon: { width: 30, height: 30, borderRadius: RADIUS.sm - 2, alignItems: 'center', justifyContent: 'center', marginRight: SPACE.md },
  logAction: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  logDetail: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  logTime: { color: COLORS.textTertiary, fontSize: FONT.xs, fontVariant: ['tabular-nums'] },
});

export default WateringScreen;
