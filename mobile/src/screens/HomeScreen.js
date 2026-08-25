import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Animated, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { getOverview, getAlerts, humidityStatus, vpdStatus } from '../services/careV2';

const LEVEL = {
  urgent:  { c: COLORS.danger,  bg: COLORS.dangerDim },
  action:  { c: COLORS.warning, bg: COLORS.warningDim },
  warning: { c: COLORS.warning, bg: COLORS.warningDim },
  info:    { c: COLORS.info,    bg: COLORS.infoDim },
};

const HomeScreen = ({ navigation }) => {
  const [data,    setData]    = useState(null);
  const [alerts,  setAlerts]  = useState(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(false);
  const [error,   setError]   = useState(null);
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fade, { toValue: 1, duration: 400, useNativeDriver: true }).start();
  }, []);

  const load = useCallback(async () => {
    try {
      const [o, a] = await Promise.all([getOverview(), getAlerts()]);
      setData(o); setAlerts(a); setError(null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); setRefresh(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // farm-wide roll-up across every section
  const secs = (data?.houses || []).flatMap(h =>
    (h.sections || []).map(s => ({ ...s, houseId: h.houseId, houseName: h.meta?.name })));
  const online = secs.filter(s => s.online);
  const avg = (f) => online.length
    ? (online.reduce((n, s) => n + (s.latest?.[f] ?? 0), 0) / online.length) : null;

  const avgT   = avg('temperature');
  const avgRH  = avg('humidity');
  const avgVPD = avg('vpd');
  const hottest = online.length
    ? online.reduce((a, b) => (a.latest.temperature > b.latest.temperature ? a : b)) : null;
  const driest  = online.length
    ? online.reduce((a, b) => (a.latest.humidity < b.latest.humidity ? a : b)) : null;
  const traysFilling = secs.filter(s => s.tray?.status === 'fill').length;

  const rh = humidityStatus(avgRH);
  const vp = vpdStatus(avgVPD);
  const urgent = alerts?.alerts?.filter(a => a.level === 'urgent' || a.level === 'action') || [];

  return (
    <View style={styles.container}>
      <ScreenHeader title="Dashboard" subtitle={data?.farm?.farmName || 'Overview'} navigation={navigation} showSettings />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refresh} tintColor={COLORS.primary}
          onRefresh={() => { setRefresh(true); load(); }} />}>
        <Animated.View style={{ opacity: fade }}>

          {/* status + settings */}
          <View style={styles.statusRow}>
            <View style={[styles.badge, { backgroundColor: online.length ? COLORS.successDim : COLORS.dangerDim }]}>
              <View style={[styles.dot, { backgroundColor: online.length ? COLORS.success : COLORS.danger }]} />
              <Text style={[styles.badgeText, { color: online.length ? COLORS.success : COLORS.danger }]}>
                {online.length ? `${online.length}/${secs.length} SECTIONS LIVE` : 'NO DATA'}
              </Text>
            </View>
            <TouchableOpacity style={[styles.settingsBtn, SHADOW.sm]}
              onPress={() => navigation.navigate('Settings')} activeOpacity={0.6}>
              <Ionicons name="settings-outline" size={20} color={COLORS.textSecondary} />
              <Text style={styles.settingsBtnText}>Settings</Text>
            </TouchableOpacity>
          </View>

          {/* quick nav */}
          <View style={styles.navRow}>
            {[
              { label: 'My Farm',  icon: 'business-outline', route: 'Farm',        color: COLORS.primary },
              { label: 'Detection',icon: 'search-outline',   route: 'Disease',     color: COLORS.info },
              { label: 'Hybrid',   icon: 'git-merge-outline',route: 'Hybrid',      color: COLORS.warning },
              { label: 'Growth',   icon: 'leaf-outline',     route: 'Growth',      color: COLORS.fertilizer },
              { label: 'Devices',  icon: 'calculator-outline', route: 'DeviceCalculator', color: COLORS.temperature },
            ].map((item, i) => (
              <TouchableOpacity key={i} style={[styles.navCard, SHADOW.sm]} activeOpacity={0.6}
                onPress={() => navigation.navigate(item.route)}>
                <View style={[styles.navIcon, { backgroundColor: `${item.color}12` }]}>
                  <Ionicons name={item.icon} size={18} color={item.color} />
                </View>
                <Text style={styles.navLabel} numberOfLines={1}
                  adjustsFontSizeToFit maxFontSizeMultiplier={1.15}>{item.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {loading ? (
            <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
          ) : error ? (
            <View style={[styles.errCard, SHADOW.sm]}>
              <Ionicons name="cloud-offline-outline" size={20} color={COLORS.danger} />
              <Text style={styles.errText}>{error}{'\n'}Is the backend running?</Text>
            </View>
          ) : secs.length === 0 ? (
            <TouchableOpacity style={[styles.setupCard, SHADOW.sm]}
              onPress={() => navigation.navigate('FarmSetup')} activeOpacity={0.8}>
              <Ionicons name="add-circle-outline" size={26} color={COLORS.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.setupTitle}>Set up your farm</Text>
                <Text style={styles.setupText}>Add your greenhouses and sections to begin.</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
            </TouchableOpacity>
          ) : (
            <>
              {/* needs attention */}
              {urgent.length > 0 && (
                <>
                  <Text style={styles.sectionTitle}>Needs Attention</Text>
                  {urgent.slice(0, 3).map(a => {
                    const lv = LEVEL[a.level] || LEVEL.info;
                    return (
                      <TouchableOpacity key={a.id} style={[styles.alert, { backgroundColor: lv.bg }, SHADOW.sm]}
                        onPress={() => navigation.navigate('SectionDetail',
                          { houseId: a.houseId, sectionId: a.sectionId })} activeOpacity={0.75}>
                        <Ionicons name={a.icon} size={18} color={lv.c} />
                        <View style={{ flex: 1 }}>
                          <Text style={[styles.alertTitle, { color: lv.c }]}>{a.title}</Text>
                          <Text style={styles.alertMsg}>{a.message}</Text>
                        </View>
                        <Ionicons name="chevron-forward" size={15} color={COLORS.textTertiary} />
                      </TouchableOpacity>
                    );
                  })}
                </>
              )}

              {/* farm averages */}
              <Text style={styles.sectionTitle}>Farm Average</Text>
              <View style={styles.grid}>
                {[
                  ['thermometer-outline', COLORS.temperature, avgT?.toFixed(1) ?? '--', '°C', 'Temperature'],
                  ['water-outline',       rh.color,           avgRH?.toFixed(0) ?? '--', '%', `Humidity · ${rh.label}`],
                  ['speedometer-outline', vp.color,           avgVPD?.toFixed(2) ?? '--', 'kPa', `Drying · ${vp.label}`],
                  ['water',               COLORS.info,        `${traysFilling}`, '', 'Trays filling'],
                ].map(([ic, c, v, u, l], i) => (
                  <View key={i} style={[styles.tile, SHADOW.sm]}>
                    <Ionicons name={ic} size={16} color={c} />
                    <Text style={[styles.tileVal, { color: c }]}>{v}<Text style={styles.tileUnit}>{u}</Text></Text>
                    <Text style={styles.tileLbl} numberOfLines={1}
                      adjustsFontSizeToFit maxFontSizeMultiplier={1.15}>{l}</Text>
                  </View>
                ))}
              </View>

              {/* extremes, the core research point */}
              {hottest && driest && (
                <>
                  <Text style={styles.sectionTitle}>Section Differences</Text>
                  <View style={[styles.extremes, SHADOW.sm]}>
                    <Text style={styles.exNote}>
                      Sections in the same farm do not share conditions, this is why each one
                      is measured and watered separately.
                    </Text>
                    <View style={styles.exRow}>
                      <Ionicons name="flame-outline" size={15} color={COLORS.danger} />
                      <Text style={styles.exTxt}>
                        Hottest: <Text style={styles.b}>{hottest.meta?.name}</Text> ({hottest.houseName}), {hottest.latest.temperature}°C
                      </Text>
                    </View>
                    <View style={styles.exRow}>
                      <Ionicons name="sunny-outline" size={15} color={COLORS.warning} />
                      <Text style={styles.exTxt}>
                        Driest: <Text style={styles.b}>{driest.meta?.name}</Text> ({driest.houseName}), {driest.latest.humidity}% RH
                      </Text>
                    </View>
                  </View>
                </>
              )}

              <TouchableOpacity style={[styles.viewAll, SHADOW.sm]}
                onPress={() => navigation.navigate('Farm')} activeOpacity={0.8}>
                <Ionicons name="business-outline" size={18} color={COLORS.primary} />
                <Text style={styles.viewAllText}>
                  View all {data.houseCount} house{data.houseCount !== 1 ? 's' : ''} · {data.sectionCount} sections
                </Text>
                <Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />
              </TouchableOpacity>
            </>
          )}
        </Animated.View>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.xl },
  center:    { paddingVertical: 40, alignItems: 'center' },
  b:         { fontWeight: '800', color: COLORS.text },

  statusRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.xl },
  badge:     { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingVertical: 5, borderRadius: RADIUS.full },
  dot:       { width: 5, height: 5, borderRadius: 3, marginRight: 5 },
  badgeText: { fontSize: 9, fontWeight: '700', letterSpacing: 0.6 },
  settingsBtn:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.full, paddingHorizontal: SPACE.lg, paddingVertical: SPACE.sm + 2 },
  settingsBtnText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },

  navRow:   { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.xl },
  navCard:  { flex: 1, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, alignItems: 'center' },
  navIcon:  { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center', marginBottom: SPACE.xs },
  navLabel: { color: COLORS.textSecondary, fontSize: 10, fontWeight: '600' },

  errCard: { flexDirection: 'row', gap: SPACE.md, backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm, padding: SPACE.lg },
  errText: { color: COLORS.danger, fontSize: FONT.sm, flex: 1, lineHeight: 18 },

  setupCard:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },
  setupTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  setupText:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },

  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.sm },

  alert:      { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  alertTitle: { fontSize: FONT.sm, fontWeight: '700' },
  alertMsg:   { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 1, lineHeight: 16 },

  grid:    { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginBottom: SPACE.sm },
  tile:    { width: '47.5%', flexGrow: 1, alignItems: 'center', gap: 2, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg },
  tileVal: { fontSize: 21, fontWeight: '800', fontVariant: ['tabular-nums'] },
  tileUnit:{ fontSize: FONT.xs, fontWeight: '600' },
  tileLbl: { color: COLORS.textTertiary, fontSize: FONT.xs },

  extremes: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, gap: SPACE.sm },
  exNote:   { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginBottom: SPACE.xs },
  exRow:    { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  exTxt:    { color: COLORS.textSecondary, fontSize: FONT.sm, flex: 1 },

  viewAll:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.xl },
  viewAllText: { flex: 1, color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
});

export default HomeScreen;
