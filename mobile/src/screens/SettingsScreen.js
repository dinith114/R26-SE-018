import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  Switch, Animated, Alert,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { LIVE_MS } from '../hooks/useLiveData';
import { usePrefs } from '../config/prefs';
import {
  getDevices, getOverview, getModelInfo, intervalLabel, lastSeenLabel, signalLabel,
} from '../services/careV2';

/* This screen used to read the LEGACY v1 paths at the Firebase root - /latest,
   /prediction and /history - which nothing else in the v2 app touches. They
   still hold seed data from the old firmware: on 24 Aug 2026 /latest reported
   30.1 C, 42 % RH and 680 lux with timestamp 5583302 (a 1970 date), while the
   real node was reading 31.4 C, 78.2 % RH and 3 lux. Every green "OK" badge on
   this page was therefore derived from fabricated data, and "ESP32 Live" could
   read Live while the actual board sat unplugged.

   Everything here now comes from the same v2 API the rest of the app uses, so a
   status shown on this page is a status the hardware really has.

   The probe calibration below is likewise the MEASURED pair from
   sensor_node_validate.ino, not the datasheet numbers that used to be here. */
const SOIL_DRY_ADC = 2600;   // measured in open air, 23 Aug 2026
const SOIL_WET_ADC = 1100;   // measured with the blade in water to the printed line

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
  const { expert, setExpert } = usePrefs();
  const [device,  setDevice]  = useState(null);   // the physical node
  const [section, setSection] = useState(null);   // the section it reports for
  const [models,  setModels]  = useState(null);   // live /model-info
  const [online,  setOnline]  = useState(null);   // is the backend reachable at all

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

    let alive = true;
    const load = async () => {
      try {
        const [devs, ov] = await Promise.all([getDevices(), getOverview()]);
        if (!alive) return;
        setOnline(true);

        // The node heard from most recently. With one board on the bench this is
        // simply "the node"; with four it is the one worth showing a status for.
        const list = devs.devices || [];
        const dev = list.find((d) => d.online) || list[0] || null;
        setDevice(dev);

        // Its section, so the sensor rows describe the readings THAT node sent
        // rather than whatever was last written anywhere on the farm.
        let sec = null;
        (ov.houses || []).forEach((h) => {
          (h.sections || []).forEach((x) => {
            if (dev && dev.assignedTo === h.houseId + '/' + x.sectionId) sec = x;
          });
        });
        setSection(sec);
      } catch (_) {
        if (alive) setOnline(false);
      }
      try { const m = await getModelInfo(); if (alive) setModels(m); }
      catch (_) { if (alive) setModels(null); }
    };

    load();
    const t = setInterval(load, LIVE_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const toggleAlert = async key => {
    const next = { ...alerts, [key]: !alerts[key] };
    setAlerts(next);
    await AsyncStorage.setItem('alerts', JSON.stringify(next));
  };

  // ── Live status, all of it from the v2 API ──────────────────────────────────────────────────
  const latest = section?.latest || null;
  // The node reports -999 for a sensor it could not read, and the backend clamps
  // that to a safe default before the models see it. So a plain truthiness check
  // here would call a dead sensor healthy - ask the node's own fault flag too.
  const bad = (v) => v == null || v === -999;

  const isESP32Live  = !!device?.online;
  const isDHT22OK    = !!latest && !bad(latest.temperature) && !bad(latest.humidity);
  const isBH1750OK   = !!latest && !bad(latest.light) && latest.sensorFault !== true;
  const isMoisOK     = !!latest && latest.soilRaw != null;
  const isFirebaseOK = online === true;
  const mlOK         = !!models;

  const sig          = signalLabel(device?.rssi);
  const lastSeenStr  = section?.freshness?.label ?? (device ? lastSeenLabel(device.lastSeenSec) : '-');
  const intervalStr  = device ? intervalLabel(device.readIntervalMs) : '-';
  const rawStr       = latest?.soilRaw != null ? String(latest.soilRaw) : '-';

  const wm = models?.watering?.metrics;
  const tm = models?.tray?.metrics;
  const waterStr = wm
    ? 'MAE ' + Math.round(wm.hour?.mae_minutes ?? 0) + ' min · R² ' + (wm.hour?.r2 ?? 0).toFixed(3)
    : '…';
  const trayStr = tm
    ? 'MAE ' + (tm.mae_seconds ?? tm.mae ?? 0).toFixed(2) + ' s'
    : '…';
  const planStr = section?.plan?.waterTime
    ? section.plan.waterTime + ' for ' + section.plan.durationSec + 's'
    : 'not planned yet';

  return (
    <View style={s.screen}>
      <ScreenHeader title="Settings" subtitle="Configuration" navigation={navigation} showBack />

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>

          {/* ── Display mode: Simple (default) vs Expert ──────────────── */}
          <View style={[s.modeCard, SHADOW.sm]}>
            <View style={s.modeRow}>
              <Ionicons name={expert ? 'construct-outline' : 'happy-outline'}
                size={26} color={expert ? COLORS.info : COLORS.primary} />
              <View style={{ flex: 1 }}>
                <Text style={s.modeTitle}>{expert ? 'Expert view' : 'Simple view'}</Text>
                <Text style={s.modeDesc}>
                  {expert
                    ? 'Showing full technical detail, sensor values, drying power (VPD), charts and every control.'
                    : 'Big text and plain words. Just what to do today.'}
                </Text>
              </View>
              <Switch
                value={expert}
                onValueChange={setExpert}
                trackColor={{ false: COLORS.border, true: `${COLORS.info}40` }}
                thumbColor={expert ? COLORS.info : COLORS.textTertiary}
              />
            </View>
          </View>

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
              { label: 'Temp',  value: isDHT22OK  ? `${latest.temperature.toFixed(1)}°` : '-',  color: COLORS.temperature },
              { label: 'Humid', value: isDHT22OK  ? `${latest.humidity.toFixed(0)}%`     : '-',  color: COLORS.humidity    },
              { label: 'Light', value: isBH1750OK ? `${latest.light.toFixed(0)} lx`      : 'N/A', color: COLORS.light      },
              { label: 'Tray',  value: latest?.sampleMoisture != null ? `${latest.sampleMoisture.toFixed(0)}%` : '-', color: COLORS.soil },
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
            <Row icon="leaf-outline"         iconColor={COLORS.soil}        label="Tray Water Probe"      right={<StatusBadge ok={isMoisOK}    label={isMoisOK    ? 'OK'   : 'Error'}   />} />
            <Divider />
            <Row icon="wifi-outline"         iconColor={COLORS.info}        label="Wi-Fi Signal"          value={sig.label} hint={device?.ip || undefined} />
            <Divider />
            <Row icon="time-outline"         iconColor={COLORS.textSecondary} label="Last Reading"        value={lastSeenStr} />
            <Divider />
            <Row icon="reload-circle-outline" iconColor={COLORS.textSecondary} label="Read Interval"
                 value={intervalStr} hint="Change it on the section's Sensor node card" />
          </View>

          {/* ── CLOUD ────────────────────────────────────────────────── */}
          <Text style={s.sectionLabel}>CLOUD</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="cloud-outline"     iconColor={COLORS.info}    label="Firebase RTDB"    right={<StatusBadge ok={isFirebaseOK} label={isFirebaseOK ? 'Online' : 'Offline'} />} />
            <Divider />
            <Row icon="sparkles-outline"  iconColor={COLORS.warning} label="ML Backend"       right={<StatusBadge ok={mlOK}         label={mlOK         ? 'Running' : 'No data'} />} />
            <Divider />
            <Row icon="analytics-outline" iconColor={COLORS.primary} label="Today's Plan"     value={planStr} />
            <Divider />
            <Row icon="layers-outline"    iconColor={COLORS.info}    label="Watering Model"   value={waterStr}
                 hint="Random Forest regressor · decides the hour from dawn conditions" />
            <Divider />
            <Row icon="water-outline"     iconColor={COLORS.humidity} label="Tray Model"      value={trayStr}
                 hint="Random Forest regressor · valve seconds" />
            <Divider />
            <Row icon="flask-outline"     iconColor={COLORS.fertilizer} label="Fertilizer" value="Encoded schedule"
                 hint="A deterministic rule, not a learned model — reported honestly" />
          </View>

          {/* ── SENSOR CALIBRATION ───────────────────────────────────── */}
          <Text style={s.sectionLabel}>SENSOR CALIBRATION</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="options-outline" iconColor={COLORS.textSecondary} label="Probe Dry Value (ADC)" value={String(SOIL_DRY_ADC)} hint="Measured in open air" />
            <Divider />
            <Row icon="water"           iconColor={COLORS.humidity}      label="Probe Wet Value (ADC)" value={String(SOIL_WET_ADC)} hint="Blade in water to the printed line" />
            <Divider />
            <Row icon="pulse"           iconColor={COLORS.soil}          label="Current Raw Reading"   value={rawStr} hint="Falls as the tray fills" />
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
            <Row icon="bulb-outline"          iconColor={COLORS.textSecondary} label="Component" value="3, Watering & Fertilization" />
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
  modeCard:  { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg, marginBottom: SPACE.lg },
  modeRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  modeTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  modeDesc:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },
});
