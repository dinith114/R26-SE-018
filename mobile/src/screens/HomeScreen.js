import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Dimensions, Animated
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import SensorCard from '../components/SensorCard';
import PredictionBanner from '../components/PredictionBanner';

const { width } = Dimensions.get('window');

const HomeScreen = ({ navigation }) => {
  const [sensorData, setSensorData] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
    const latestRef = ref(database, 'latest');
    const unsubLatest = onValue(latestRef, (snapshot) => {
      const val = snapshot.val();
      if (val) { setSensorData(val); setLastUpdated(new Date()); }
    });
    const predRef = ref(database, 'prediction');
    const unsubPred = onValue(predRef, (snapshot) => {
      const val = snapshot.val();
      if (val) setPrediction(val);
    });
    return () => { unsubLatest(); unsubPred(); };
  }, []);

  const onRefresh = () => { setRefreshing(true); setTimeout(() => setRefreshing(false), 800); };
  const isLive = lastUpdated && (Date.now() - lastUpdated.getTime()) < 120000;

  return (
    <View style={styles.container}>
      <ScreenHeader title="Dashboard" subtitle="Overview" navigation={navigation} />

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.primary} />}
      >
        <Animated.View style={{ opacity: fadeAnim }}>
          {/* Status + Settings row */}
          <View style={styles.statusRow}>
            <View style={[styles.badge, { backgroundColor: isLive ? COLORS.successDim : COLORS.dangerDim }]}>
              <View style={[styles.dot, { backgroundColor: isLive ? COLORS.success : COLORS.danger }]} />
              <Text style={[styles.badgeText, { color: isLive ? COLORS.success : COLORS.danger }]}>
                {isLive ? 'SENSORS LIVE' : 'OFFLINE'}
              </Text>
            </View>
            <TouchableOpacity
              style={[styles.settingsBtn, SHADOW.sm]}
              onPress={() => navigation.navigate('Settings')}
              activeOpacity={0.6}
            >
              <Ionicons name="settings-outline" size={20} color={COLORS.textSecondary} />
              <Text style={styles.settingsBtnText}>Settings</Text>
              <Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />
            </TouchableOpacity>
          </View>

          {/* Quick Nav */}
          <View style={styles.navRow}>
            {[
              { label: 'Watering', icon: 'water-outline', route: 'Care', color: COLORS.primary },
              { label: 'Detection', icon: 'search-outline', route: 'Disease', color: COLORS.info },
              { label: 'Hybrid', icon: 'git-merge-outline', route: 'Hybrid', color: COLORS.warning },
              { label: 'Growth', icon: 'leaf-outline', route: 'Growth', color: COLORS.fertilizer },
            ].map((item, i) => (
              <TouchableOpacity
                key={i}
                style={[styles.navCard, SHADOW.sm]}
                activeOpacity={0.6}
                onPress={() => navigation.navigate(item.route)}
              >
                <View style={[styles.navIcon, { backgroundColor: `${item.color}12` }]}>
                  <Ionicons name={item.icon} size={18} color={item.color} />
                </View>
                <Text style={styles.navLabel}>{item.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Sensors */}
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>Sensors</Text>
            {lastUpdated && <Text style={styles.timestamp}>{lastUpdated.toLocaleTimeString()}</Text>}
          </View>
          <View style={styles.grid}>
            <SensorCard title="Temp" value={sensorData?.temperature?.toFixed(1) ?? '--'} unit="°C" color={COLORS.temperature} iconName="thermometer-outline" />
            <SensorCard title="Humidity" value={sensorData?.humidity?.toFixed(1) ?? '--'} unit="%" color={COLORS.humidity} iconName="water-outline" />
            <SensorCard title="Light" value={sensorData?.light === -999 ? 'N/A' : (sensorData?.light?.toFixed(0) ?? '--')} unit="lux" color={COLORS.light} iconName="sunny-outline" />
            <SensorCard title="Root" value={sensorData?.rootMoisturePct?.toFixed(1) ?? '--'} unit="%" color={COLORS.soil} iconName="leaf-outline" />
          </View>

          {/* Prediction */}
          <Text style={styles.sectionTitle}>AI Prediction</Text>
          {prediction ? (
            <PredictionBanner
              waterNeeded={prediction.waterNeeded}
              fertilizerNeeded={prediction.fertilizerNeeded || 'No'}
              confidence={prediction.confidence}
            />
          ) : (
            <View style={[styles.emptyCard, SHADOW.sm]}>
              <Ionicons name="hourglass-outline" size={18} color={COLORS.textTertiary} />
              <Text style={styles.emptyText}>Waiting for prediction server</Text>
            </View>
          )}
        </Animated.View>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },
  statusRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.xl },
  badge: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingVertical: 5, borderRadius: RADIUS.full },
  dot: { width: 5, height: 5, borderRadius: 3, marginRight: 5 },
  badgeText: { fontSize: 9, fontWeight: '700', letterSpacing: 0.8 },
  settingsBtn: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.full, paddingHorizontal: SPACE.lg, paddingVertical: SPACE.sm + 2 },
  settingsBtnText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  navRow: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.xl },
  navCard: { flex: 1, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, alignItems: 'center' },
  navIcon: { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center', marginBottom: SPACE.xs },
  navLabel: { color: COLORS.textSecondary, fontSize: 10, fontWeight: '600' },
  sectionRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  timestamp: { color: COLORS.textTertiary, fontSize: FONT.xs, fontVariant: ['tabular-nums'] },
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', marginBottom: SPACE.xl },
  emptyCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xl, alignItems: 'center', flexDirection: 'row', justifyContent: 'center', gap: SPACE.sm },
  emptyText: { color: COLORS.textTertiary, fontSize: FONT.sm },
});

export default HomeScreen;
