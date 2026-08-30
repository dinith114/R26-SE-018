/**
 * The Digital Twin as the monitoring surface for an active house.
 *
 * The list of sections tells a farmer what each one reads. It cannot tell them
 * that the two hot sections are both at the sun-facing end, or that the section
 * furthest from the pump is the one whose tray keeps running dry. Those are
 * spatial facts and they need a spatial view.
 *
 * The distinction this screen exists to make visible: which readings were
 * MEASURED and which were INFERRED. A farmer acting on 31.2 °C should know
 * whether a sensor recorded it or whether it was interpolated from neighbours
 * three metres away, so estimated sections are purple and carry their error.
 */
import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import Toast from '../components/Toast';
import { getHouse } from '../services/careV2';

/* Beyond this an estimate is describing weather that has moved on. Matches the
   backend's own rule so the two cannot disagree on screen. */
const ESTIMATE_MAX_MIN = 60;

const FIELDS = [
  { key: 'temperature', label: 'Temperature', unit: '°C', sd: 'temperatureSd' },
  { key: 'humidity',    label: 'Humidity',    unit: '%',  sd: 'humiditySd' },
];

export default function HouseMapScreen({ route, navigation }) {
  const houseId = route.params?.houseId;

  const [house,   setHouse]   = useState(null);
  const [field,   setField]   = useState('temperature');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(false);
  const [toast,   setToast]   = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await getHouse(houseId);
      setHouse(r?.house || null);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setLoading(false);
      setRefresh(false);
    }
  }, [houseId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const meta = house?.meta || {};
  const sections = house?.sections || {};
  const spec = FIELDS.find((f) => f.key === field) || FIELDS[0];

  /* Measured wins over estimated, always. A section with its own reading is
     never drawn as an estimate even when a fresher estimate exists - the
     measurement is the thing that happened. */
  const nodes = Object.entries(sections)
    .filter(([, sec]) => sec?.meta?.x != null && sec?.meta?.y != null)
    .map(([id, sec]) => {
      const measured = sec.latest || {};
      const est = sec.estimated || null;
      const estAge = est?.timestampMs ? (Date.now() - est.timestampMs) / 60000 : null;
      const estOk = est && estAge != null && estAge >= 0 && estAge <= ESTIMATE_MAX_MIN;

      const isMaster = meta.masterMac
        && (sec.node?.mac === meta.masterMac || sec.meta?.deviceMac === meta.masterMac);

      let kind = 'offline';
      let value = null;
      let sd = null;

      if (measured[spec.key] != null) {
        kind = isMaster ? 'master' : 'real';
        value = Number(measured[spec.key]).toFixed(1);
      } else if (estOk) {
        kind = 'estimated';
        value = Number(est[spec.key]).toFixed(1);
        sd = est[spec.sd] != null ? Number(est[spec.sd]).toFixed(1) : null;
      }

      return {
        id,
        short: String(id).replace(/^S/, ''),
        x: Number(sec.meta.x),
        y: Number(sec.meta.y),
        kind, value, sd, unit: spec.unit,
      };
    });

  const unplaced = Object.keys(sections).length - nodes.length;
  const nEst = nodes.filter((n) => n.kind === 'estimated').length;

  if (loading) {
    return (
      <View style={styles.container}>
        <ScreenHeader title="Map" navigation={navigation} showBack />
        <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScreenHeader title={meta.name || houseId} subtitle="Digital twin"
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refresh}
          onRefresh={() => { setRefresh(true); load(); }} tintColor={COLORS.primary} />}>

        <View style={styles.tabs}>
          {FIELDS.map((f) => (
            <TouchableOpacity key={f.key} onPress={() => setField(f.key)}
              style={[styles.tab, field === f.key && styles.tabOn]} activeOpacity={0.7}>
              <Text style={[styles.tabTxt, field === f.key && styles.tabTxtOn]}>
                {f.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
          {meta.width && meta.length ? (
            <DigitalTwin
              width={meta.width}
              length={meta.length}
              nodes={nodes}
              plantRows={4}
              pump={meta.pumpX != null && meta.pumpY != null
                ? { x: meta.pumpX, y: meta.pumpY } : null}
              onPressNode={(n) => navigation.navigate('SectionDetail',
                { houseId, sectionId: n.id })} />
          ) : (
            <View style={styles.noDims}>
              <Ionicons name="resize-outline" size={20} color={COLORS.textTertiary} />
              <Text style={styles.noDimsTxt}>
                This house has no width and length recorded, so it cannot be drawn
                to scale. Houses created before the planner existed have none —
                set them and the map appears.
              </Text>
            </View>
          )}
        </View>

        {/* The claim this screen is here to make, said in words as well as
            colour. Colour alone fails anyone who cannot distinguish it. */}
        {nEst > 0 && (
          <View style={[styles.card, styles.estCard, SHADOW.sm]}>
            <Ionicons name="analytics-outline" size={15} color={COLORS.estimated} />
            <Text style={styles.estTxt}>
              {nEst} section{nEst > 1 ? 's have' : ' has'} no sensor. Those readings
              are estimated from the sections that do, and carry the margin of
              error they were calculated with.
            </Text>
          </View>
        )}

        {/* Putting hardware back is the natural next thought while looking at a
            map of zones that have none, so the way to do it lives here rather
            than somewhere the farmer has to go and find. */}
        <TouchableOpacity style={[styles.addBtn, SHADOW.sm]} activeOpacity={0.85}
          accessibilityRole="button"
          accessibilityLabel="Add a sensor to one of these zones"
          onPress={() => navigation.navigate('AddSensor', { houseId })}>
          <Ionicons name="add-circle-outline" size={18} color={COLORS.primary} />
          <Text style={styles.addBtnTxt}>Put a sensor in one of these zones</Text>
        </TouchableOpacity>

        {unplaced > 0 && (
          <View style={[styles.card, styles.warnCard, SHADOW.sm]}>
            <Ionicons name="location-outline" size={15} color={COLORS.warning} />
            <Text style={styles.warnTxt}>
              {unplaced} section{unplaced > 1 ? 's are' : ' is'} not on the map —
              no position set. Add one in that section's Setup tab.
            </Text>
          </View>
        )}

        <Text style={styles.foot}>Tap a section to open it.</Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center:    { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll:    { padding: SPACE.lg, paddingBottom: SPACE.xl * 2 },

  tabs:    { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.md },
  tab:     { flex: 1, alignItems: 'center', paddingVertical: 8,
             borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCardAlt },
  tabOn:   { backgroundColor: COLORS.primary },
  tabTxt:  { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },
  tabTxtOn:{ color: '#FFF' },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },

  noDims:    { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start' },
  noDimsTxt: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17 },

  estCard:  { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
              backgroundColor: COLORS.estimatedDim, marginTop: SPACE.md },
  estTxt:   { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  addBtn:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
               padding: SPACE.lg, marginTop: SPACE.md,
               borderWidth: 1, borderColor: COLORS.primaryDim },
  addBtnTxt: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },
  warnCard: { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
              backgroundColor: COLORS.warningDim, marginTop: SPACE.md },
  warnTxt:  { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: SPACE.lg,
          textAlign: 'center' },
});
