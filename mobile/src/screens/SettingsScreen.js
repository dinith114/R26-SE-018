import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  Switch, Animated, Alert,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue, get } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

// ─── Small helpers ─────────────────────────────────────────────────────────────
const Divider = () => <View style={s.divider} />;

const StatusBadge = ({ ok, label }) => (
  <View style={[s.badge, { backgroundColor: ok ? COLORS.successDim : COLORS.dangerDim }]}>
    <View style={[s.badgeDot, { backgroundColor: ok ? COLORS.success : COLORS.danger }]} />
    <Text style={[s.badgeText, { color: ok ? COLORS.success : COLORS.danger }]}>{label}</Text>
  </View>
);

const Row = ({ icon, iconColor, label, value, hint, right, onPress }) => (
  <TouchableOpacity style={s.row} activeOpacity={onPress ? 0.6 : 1} onPress={onPress}>
    <View style={[s.rowIcon, { backgroundColor: `${iconColor || COLORS.textTertiary}14` }]}>
      <Ionicons name={icon} size={17} color={iconColor || COLORS.textSecondary} />
    </View>
    <View style={{ flex: 1 }}>
      <Text style={s.rowLabel}>{label}</Text>
      {hint && <Text style={s.rowHint}>{hint}</Text>}
    </View>
    {right ?? (
      <Text style={s.rowValue}>{value}</Text>
    )}
  </TouchableOpacity>
);

const ToggleRow = ({ icon, iconColor, label, sub, value, onToggle }) => (
  <View style={s.row}>
    <View style={[s.rowIcon, { backgroundColor: `${iconColor || COLORS.primary}14` }]}>
      <Ionicons name={icon} size={17} color={iconColor || COLORS.primary} />
    </View>
    <View style={{ flex: 1 }}>
      <Text style={s.rowLabel}>{label}</Text>
      {sub && <Text style={s.rowHint}>{sub}</Text>}
    </View>
    <Switch
      value={value}
      onValueChange={onToggle}
      trackColor={{ false: COLORS.border, true: `${iconColor || COLORS.primary}55` }}
      thumbColor={value ? (iconColor || COLORS.primary) : '#CCC'}
    />
  </View>
);

// ─── Main screen ───────────────────────────────────────────────────────────────
export default function SettingsScreen({ navigation }) {
  const [sensorData,   setSensorData]   = useState(null);
  const [prediction,   setPrediction]   = useState(null);
  const [historyCount, setHistoryCount] = useState(null);
  const [lastSeen,     setLastSeen]     = useState(null);

  const [alerts, setAlerts] = useState({
    watering:      true,
    fertilizer:    true,
    disease:       true,
    sensorOffline: true,
  });

  const [profile] = useState({
    name:    'My Vanda Orchid',
    species: 'Vanda',
    pot:     'Basket (Aerial Roots)',
  });

  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();

    AsyncStorage.getItem('alerts').then(v => { if (v) setAlerts(JSON.parse(v)); });

    const u1 = onValue(ref(database, 'latest'), snap => {
      const v = snap.val();
      if (v) { setSensorData(v); setLastSeen(new Date()); }
    });
    const u2 = onValue(ref(database, 'prediction'), snap => {
      const v = snap.val(); if (v) setPrediction(v);
    });
    get(ref(database, 'history')).then(snap => {
      if (snap.exists()) setHistoryCount(Object.keys(snap.val()).length);
    }).catch(() => {});

    return () => { u1(); u2(); };
  }, []);

  const toggleAlert = async key => {
    const next = { ...alerts, [key]: !alerts[key] };
    setAlerts(next);
    await AsyncStorage.setItem('alerts', JSON.stringify(next));
  };

  // ── Live status derivations ──────────────────────────────────────────────────
  const isESP32Live  = !!lastSeen && Date.now() - lastSeen.getTime() < 120_000;
  const isDHT22OK    = sensorData?.temperature !== -999 && sensorData?.humidity !== -999 && sensorData?.temperature != null;
  const isBH1750OK   = sensorData != null && sensorData.light !== -999;
  const isMoisOK     = sensorData?.rootMoisturePct != null;
  const isFirebaseOK = sensorData !== null;

  const lastSeenStr  = lastSeen ? lastSeen.toLocaleTimeString() : '—';
  const countStr     = historyCount !== null ? historyCount.toLocaleString() : '…';
  const predTime     = prediction?.timestamp?.split(' ')[1] ?? '—';
  const mlOK         = !!prediction;

  return (
    <View style={s.screen}>
      <ScreenHeader title="Settings" subtitle="Configuration" navigation={navigation} showBack />

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>

          {/* ── Orchid Profile card ───────────────────────────────────── */}
          <LinearGradient
            colors={[COLORS.primary, COLORS.primaryDark]}
            start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
            style={[s.profileCard, SHADOW.md]}
          >
            <View style={s.profileAvatar}>
              <Ionicons name="flower-outline" size={30} color="#FFF" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.profileName}>{profile.name}</Text>
              <Text style={s.profileSub}>{profile.species} · {profile.pot}</Text>
            </View>
            <TouchableOpacity
              style={s.profileEdit}
              onPress={() => Alert.alert('Edit Profile', 'Profile editing will be added in the next release.')}
            >
              <Ionicons name="pencil-outline" size={16} color="rgba(255,255,255,0.85)" />
            </TouchableOpacity>
          </LinearGradient>

          {/* ── Live snapshot strip ───────────────────────────────────── */}
          <View style={[s.snapRow, SHADOW.sm]}>
            {[
              { label: 'Temp',  value: sensorData?.temperature != null ? `${sensorData.temperature.toFixed(1)}°` : '—', color: COLORS.temperature },
              { label: 'Humid', value: sensorData?.humidity    != null ? `${sensorData.humidity.toFixed(0)}%`    : '—', color: COLORS.humidity    },
              { label: 'Light', value: isBH1750OK ? `${sensorData.light.toFixed(0)} lx` : 'N/A',                       color: COLORS.light       },
              { label: 'Root',  value: sensorData?.rootMoisturePct != null ? `${sensorData.rootMoisturePct.toFixed(0)}%` : '—', color: COLORS.soil },
            ].map((item, i, arr) => (
              <React.Fragment key={i}>
                <View style={s.snapCell}>
                  <Text style={[s.snapValue, { color: item.color }]}>{item.value}</Text>
                  <Text style={s.snapLabel}>{item.label}</Text>
                </View>
                {i < arr.length - 1 && <View style={s.snapSep} />}
              </React.Fragment>
            ))}
          </View>

          {/* ── HARDWARE ─────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>HARDWARE</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="hardware-chip"        iconColor={COLORS.primary}     label="ESP32 Controller"      right={<StatusBadge ok={isESP32Live} label={isESP32Live ? 'Live' : 'Offline'} />} />
            <Divider />
            <Row icon="thermometer-outline"  iconColor={COLORS.temperature} label="DHT22 (Temp/Humidity)" right={<StatusBadge ok={isDHT22OK}   label={isDHT22OK   ? 'OK'   : 'Error'}   />} />
            <Divider />
            <Row icon="sunny-outline"        iconColor={COLORS.light}       label="BH1750 Light Sensor"   right={<StatusBadge ok={isBH1750OK}  label={isBH1750OK  ? 'OK'   : 'Error'}   />} />
            <Divider />
            <Row icon="leaf-outline"         iconColor={COLORS.soil}        label="Root Moisture Sensor"  right={<StatusBadge ok={isMoisOK}    label={isMoisOK    ? 'OK'   : 'Error'}   />} />
            <Divider />
            <Row icon="time-outline"         iconColor={COLORS.textSecondary} label="Last Reading"        value={lastSeenStr} />
            <Divider />
            <Row icon="reload-circle-outline" iconColor={COLORS.textSecondary} label="Read Interval"      value="10 s (testing)" hint="Change to 300 s for production" />
          </View>

          {/* ── CLOUD ────────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>CLOUD</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="cloud-outline"     iconColor={COLORS.info}    label="Firebase RTDB"    right={<StatusBadge ok={isFirebaseOK} label={isFirebaseOK ? 'Online' : 'Offline'} />} />
            <Divider />
            <Row icon="sparkles-outline"  iconColor={COLORS.warning} label="ML Backend"       right={<StatusBadge ok={mlOK}         label={mlOK         ? 'Running' : 'No data'} />} />
            <Divider />
            <Row icon="bar-chart-outline" iconColor={COLORS.primary} label="Stored Readings"  value={countStr} />
            <Divider />
            <Row icon="analytics-outline" iconColor={COLORS.primary} label="Last Prediction"  value={predTime} />
            <Divider />
            <Row icon="layers-outline"    iconColor={COLORS.info}    label="Watering Model"   value="Random Forest · F1 0.75" hint="8-feature classifier" />
            <Divider />
            <Row icon="flask-outline"     iconColor={COLORS.fertilizer} label="Fertilization Model" value="Decision Tree · F1 1.00" hint="6-feature classifier" />
          </View>

          {/* ── SENSOR CALIBRATION ───────────────────────────────────── */}
          <Text style={s.sectionLabel}>SENSOR CALIBRATION</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="options-outline" iconColor={COLORS.textSecondary} label="Root Dry Value (ADC)"  value="4095" hint="Sensor in dry air" />
            <Divider />
            <Row icon="water"           iconColor={COLORS.humidity}      label="Root Wet Value (ADC)"  value="1500" hint="Pressed on wet roots" />
            <Divider />
            <Row icon="pulse"           iconColor={COLORS.soil}          label="Current Raw Reading"   value={sensorData?.rootMoistureRaw?.toString() ?? '—'} />
            <Divider />
            <Row
              icon="construct-outline"
              iconColor={COLORS.warning}
              label="Recalibrate Sensor"
              hint="Tap to start calibration wizard"
              onPress={() => Alert.alert('Calibration', 'Point the sensor at dry air, then wet roots as prompted.\n\nCalibration wizard coming soon.')}
              right={<Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />}
            />
          </View>

          {/* ── ALERTS ───────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>ALERTS & NOTIFICATIONS</Text>
          <View style={[s.card, SHADOW.sm]}>
            <ToggleRow icon="water-outline"   iconColor={COLORS.primary}    label="Watering Alerts"        sub="Notify when roots need water"       value={alerts.watering}      onToggle={() => toggleAlert('watering')}      />
            <Divider />
            <ToggleRow icon="flask-outline"   iconColor={COLORS.fertilizer} label="Fertilizer Alerts"      sub="Notify when fertilizing is due"     value={alerts.fertilizer}    onToggle={() => toggleAlert('fertilizer')}    />
            <Divider />
            <ToggleRow icon="search-outline"  iconColor={COLORS.danger}     label="Disease Warnings"       sub="Alert on disease detection result"  value={alerts.disease}       onToggle={() => toggleAlert('disease')}       />
            <Divider />
            <ToggleRow icon="wifi-outline"    iconColor={COLORS.warning}    label="Sensor Offline Warning" sub="Alert when ESP32 disconnects"       value={alerts.sensorOffline} onToggle={() => toggleAlert('sensorOffline')} />
          </View>

          {/* ── ABOUT ────────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>ABOUT</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="leaf"                  iconColor={COLORS.primary}   label="System"        value="Smart Orchid Care" />
            <Divider />
            <Row icon="git-branch-outline"    iconColor={COLORS.textSecondary} label="Version"   value="v1.0.0" />
            <Divider />
            <Row icon="school-outline"        iconColor={COLORS.textSecondary} label="Project"   value="R26-SE-018" />
            <Divider />
            <Row icon="ribbon-outline"        iconColor={COLORS.textSecondary} label="Module"    value="SE4010 · SLIIT" />
            <Divider />
            <Row icon="bulb-outline"          iconColor={COLORS.textSecondary} label="Component" value="3 — Watering & Fertilization" />
            <Divider />
            <Row
              icon="document-text-outline"
              iconColor={COLORS.info}
              label="Acknowledgements"
              hint="Libraries & data sources"
              onPress={() => Alert.alert(
                'Acknowledgements',
                'Firebase RTDB · scikit-learn · React Native · Expo · BH1750 library · DHT Adafruit · Christopher Laws'
              )}
              right={<Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />}
            />
          </View>

        </Animated.View>
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

// ─── Styles ────────────────────────────────────────────────────────────────────
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl, paddingTop: SPACE.lg },

  // Profile
  profileCard:   { flexDirection: 'row', alignItems: 'center', borderRadius: RADIUS.lg, padding: SPACE.xl, marginBottom: SPACE.xl, gap: SPACE.lg },
  profileAvatar: { width: 52, height: 52, borderRadius: RADIUS.md, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  profileName:   { color: '#FFF', fontSize: FONT.lg, fontWeight: '800' },
  profileSub:    { color: 'rgba(255,255,255,0.75)', fontSize: FONT.sm, marginTop: 3 },
  profileEdit:   { width: 34, height: 34, borderRadius: RADIUS.full, backgroundColor: 'rgba(255,255,255,0.18)', alignItems: 'center', justifyContent: 'center' },

  // Snapshot strip
  snapRow:  { flexDirection: 'row', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg, marginBottom: SPACE.xl },
  snapCell: { flex: 1, alignItems: 'center' },
  snapValue:{ fontSize: FONT.md, fontWeight: '800', fontVariant: ['tabular-nums'] },
  snapLabel:{ color: COLORS.textTertiary, fontSize: 9, fontWeight: '600', letterSpacing: 0.8, marginTop: 3 },
  snapSep:  { width: 1, backgroundColor: COLORS.borderLight, marginVertical: 4 },

  // Section
  sectionLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 1.5, marginBottom: SPACE.sm, marginLeft: 2, marginTop: 4 },
  card:         { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, overflow: 'hidden', marginBottom: SPACE.xl },
  divider:      { height: 1, backgroundColor: COLORS.borderLight, marginLeft: 56 },

  // Row
  row:      { flexDirection: 'row', alignItems: 'center', paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md + 2, gap: SPACE.md },
  rowIcon:  { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  rowLabel: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  rowHint:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  rowValue: { color: COLORS.textTertiary, fontSize: FONT.sm, maxWidth: 160, textAlign: 'right' },

  // Badge
  badge:    { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 4, borderRadius: RADIUS.full, gap: 5 },
  badgeDot: { width: 6, height: 6, borderRadius: 3 },
  badgeText:{ fontSize: FONT.xs, fontWeight: '700' },
});
