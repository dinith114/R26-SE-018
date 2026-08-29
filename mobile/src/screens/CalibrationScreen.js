/**
 * A house while it is collecting the data that decides where its sensors go.
 *
 * Calibration takes three real days. This screen exists to make that wait
 * legible rather than to disguise it: it shows what has actually been recorded,
 * per section, counted from the stored readings.
 *
 * There is no progress bar driven by elapsed time. A bar that advances while a
 * node is unplugged promises data that will not exist when the analysis runs,
 * and the farmer finds that out three days later with nothing to show for it.
 * Every number here is a count of real readings; "Analyze Placement" is refused
 * until they are all there, and the screen names the section holding it up.
 */
import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import Toast from '../components/Toast';
import { getCalibration, getHouse, analyzePlacement } from '../services/careV2';

/* Long enough that a node which has genuinely stopped is obvious, short enough
   that ordinary Wi-Fi hiccups do not raise an alarm. Matches the backend. */
const SILENT_MINUTES = 120;

export default function CalibrationScreen({ route, navigation }) {
  const houseId = route.params?.houseId;

  const [cal,     setCal]     = useState(null);
  const [house,   setHouse]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [refresh, setRefresh] = useState(false);
  const [busy,    setBusy]    = useState(false);
  const [toast,   setToast]   = useState(null);

  const load = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([
        getCalibration(houseId),
        getHouse(houseId).catch(() => null),
      ]);
      setCal(c);
      setHouse(h?.house || null);
      setError(null);
    } catch (e) {
      setError(e.message);
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setLoading(false);
      setRefresh(false);
    }
  }, [houseId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const analyse = async () => {
    try {
      setBusy(true);
      const r = await analyzePlacement(houseId, 8);
      navigation.navigate('PlacementResult', { houseId, result: r });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setBusy(false);
    }
  };

  /* Positions come from the house, readiness from the calibration endpoint.
     Joined here so a section that is silent is drawn differently on the map -
     seeing WHERE the gap is in the house is the point of having a map at all. */
  const sections = house?.sections || {};
  const nodes = (cal?.sections || [])
    .map((row) => {
      const meta = (sections[row.id] || {}).meta || {};
      if (meta.x == null || meta.y == null) return null;
      const silent = row.lastSeenMinAgo == null || row.lastSeenMinAgo > SILENT_MINUTES;
      return {
        id: row.id,
        short: String(row.id).replace(/^S/, ''),
        x: Number(meta.x),
        y: Number(meta.y),
        kind: silent ? 'offline' : 'real',
      };
    })
    .filter(Boolean);

  const placed = nodes.length;
  const total = (cal?.sections || []).length;
  const ready = !!cal?.ready;
  const pct = cal ? Math.min(100, Math.round((cal.daysElapsed / cal.targetDays) * 100)) : 0;

  if (loading) {
    return (
      <View style={styles.container}>
        <ScreenHeader title="Calibrating" navigation={navigation} showBack />
        <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
      </View>
    );
  }

  /* THE CRASH THIS GUARD EXISTS FOR.
  
     `loading` is cleared in a finally block, so it goes false whether the fetch
     succeeded or threw. With only that guard, a failed request fell straight
     into a render that reads cal.daysElapsed.toFixed(1) on null - and an
     unhandled TypeError in a release build does not show an error screen, it
     closes the app. A house with no calibration block, an offline backend or a
     404 all took that path.
  
     Showing what went wrong and a way to retry is the least this can do; dying
     silently is the worst. */
  if (!cal) {
    return (
      <View style={styles.container}>
        <ScreenHeader title="Calibrating" navigation={navigation} showBack />
        <View style={styles.center}>
          <Ionicons name="cloud-offline-outline" size={26} color={COLORS.textTertiary} />
          <Text style={styles.errTitle}>Could not load calibration</Text>
          <Text style={styles.errTxt}>{error || 'No calibration data for this house.'}</Text>
          <TouchableOpacity style={styles.retry} onPress={() => { setLoading(true); load(); }}
            activeOpacity={0.8}>
            <Text style={styles.retryTxt}>Try again</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScreenHeader title="Calibrating"
        subtitle={house?.meta?.name || houseId}
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refresh}
          onRefresh={() => { setRefresh(true); load(); }} tintColor={COLORS.primary} />}>

        {/* status */}
        <View style={[styles.card, SHADOW.sm]}>
          <View style={styles.statusRow}>
            <View style={[styles.badge, ready ? styles.badgeReady : styles.badgeWait]}>
              <Ionicons name={ready ? 'checkmark-circle' : 'hourglass-outline'}
                size={13} color={ready ? COLORS.primary : COLORS.warning} />
              <Text style={[styles.badgeTxt, { color: ready ? COLORS.primary : COLORS.warning }]}>
                {ready ? 'Ready to analyse' : 'Collecting data'}
              </Text>
            </View>
            <Text style={styles.days}>
              day {cal.daysElapsed.toFixed(1)} of {cal.targetDays}
            </Text>
          </View>

          {/* The bar tracks ELAPSED TIME only, and says so. It is not a measure
              of readiness - the section list below is. Two separate things
              drawn as one bar is how a farmer ends up trusting a number that
              was never checked. */}
          <View style={styles.barTrack}>
            <View style={[styles.barFill, { width: `${pct}%` }]} />
          </View>
          <Text style={styles.barNote}>Time elapsed. Readiness depends on the readings below.</Text>
        </View>

        {/* the house */}
        <Text style={styles.h}>Where the sensors are</Text>
        <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
          {placed ? (
            <DigitalTwin
              width={house?.meta?.width || cal?.width || 10}
              length={house?.meta?.length || cal?.length || 14}
              nodes={nodes}
              plantRows={4}
              showPipes={false} />
          ) : (
            <View style={styles.noPos}>
              <Ionicons name="location-outline" size={20} color={COLORS.textTertiary} />
              <Text style={styles.noPosTxt}>
                No section has a position yet. Set them in each section's Setup tab —
                the placement analysis needs to know where the readings came from.
              </Text>
            </View>
          )}
          {!!placed && placed < total && (
            <Text style={styles.partial}>
              {placed} of {total} sections have a position. The rest cannot be
              analysed until theirs is set.
            </Text>
          )}
        </View>

        {/* per-section reality */}
        <Text style={styles.h}>What each section has recorded</Text>
        <View style={[styles.card, SHADOW.sm]}>
          {(cal.sections || []).map((row) => {
            const silent = row.lastSeenMinAgo == null || row.lastSeenMinAgo > SILENT_MINUTES;
            const frac = Math.min(1, row.readings / Math.max(1, row.needed));
            return (
              <View key={row.id} style={styles.secRow}>
                <View style={[styles.secDot, {
                  backgroundColor: row.ok ? COLORS.primary
                    : silent ? COLORS.danger : COLORS.warning,
                }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.secName}>{row.name}</Text>
                  <View style={styles.secBarTrack}>
                    <View style={[styles.secBarFill, {
                      width: `${frac * 100}%`,
                      backgroundColor: row.ok ? COLORS.primary : COLORS.warning,
                    }]} />
                  </View>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={styles.secCount}>{row.readings}/{row.needed}</Text>
                  <Text style={[styles.secSeen, silent && { color: COLORS.danger }]}>
                    {row.lastSeenMinAgo == null ? 'never'
                      : row.lastSeenMinAgo < 60 ? `${Math.round(row.lastSeenMinAgo)}m ago`
                      : `${(row.lastSeenMinAgo / 60).toFixed(0)}h ago`}
                  </Text>
                </View>
              </View>
            );
          })}
        </View>

        {/* what is holding it up */}
        {!!(cal.blockers || []).length && (
          <View style={[styles.card, styles.blockCard, SHADOW.sm]}>
            <Text style={styles.blockHead}>Still waiting on</Text>
            {cal.blockers.map((b, i) => (
              <View key={i} style={styles.blockRow}>
                <Ionicons name="ellipse" size={5} color={COLORS.warning} />
                <Text style={styles.blockTxt}>{b}</Text>
              </View>
            ))}
          </View>
        )}

        {/* wiring faults belong here: a house can calibrate perfectly and still
            water the wrong plants */}
        {!!(cal.channelConflicts || []).length && (
          <View style={[styles.card, styles.errCard, SHADOW.sm]}>
            <Text style={[styles.blockHead, { color: COLORS.danger }]}>Wiring conflict</Text>
            {cal.channelConflicts.map((b, i) => (
              <Text key={i} style={[styles.blockTxt, { color: COLORS.danger }]}>{b}</Text>
            ))}
          </View>
        )}

        <TouchableOpacity
          style={[styles.primary, (!ready || busy || !placed) && styles.primaryOff]}
          onPress={analyse} disabled={!ready || busy || !placed} activeOpacity={0.85}>
          {busy ? <ActivityIndicator color="#FFF" />
                : <Text style={styles.primaryTxt}>Analyse placement</Text>}
        </TouchableOpacity>
        <Text style={styles.foot}>
          {ready
            ? 'PySensors will run on the readings these sections recorded.'
            : 'Available once every section has enough data. Leave the sensors '
              + 'where they are until then.'}
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center:    { flex: 1, alignItems: 'center', justifyContent: 'center',
               padding: SPACE.xl, gap: SPACE.sm },
  errTitle:  { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  errTxt:    { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center',
               lineHeight: 18 },
  retry:     { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
               paddingHorizontal: SPACE.xl, paddingVertical: SPACE.sm,
               marginTop: SPACE.sm },
  retryTxt:  { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  scroll:    { padding: SPACE.lg, paddingBottom: SPACE.xl * 3 },

  h: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '800',
       letterSpacing: 0.4, textTransform: 'uppercase',
       marginTop: SPACE.xl, marginBottom: SPACE.sm },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },

  statusRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  badge:     { flexDirection: 'row', alignItems: 'center', gap: 5,
               paddingHorizontal: 9, paddingVertical: 4, borderRadius: RADIUS.full },
  badgeReady:{ backgroundColor: COLORS.primaryDim },
  badgeWait: { backgroundColor: COLORS.warningDim },
  badgeTxt:  { fontSize: 11, fontWeight: '800' },
  days:      { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },

  barTrack: { height: 5, borderRadius: 3, backgroundColor: COLORS.bgCardAlt,
              marginTop: SPACE.md, overflow: 'hidden' },
  barFill:  { height: 5, borderRadius: 3, backgroundColor: COLORS.textTertiary },
  barNote:  { color: COLORS.textTertiary, fontSize: 10, marginTop: 5 },

  noPos:    { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start' },
  noPosTxt: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17 },
  partial:  { color: COLORS.warning, fontSize: FONT.xs, marginTop: SPACE.md,
              textAlign: 'center', lineHeight: 17 },

  secRow:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.borderLight },
  secDot:  { width: 8, height: 8, borderRadius: 4 },
  secName: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  secBarTrack: { height: 3, borderRadius: 2, backgroundColor: COLORS.bgCardAlt,
                 marginTop: 5, overflow: 'hidden' },
  secBarFill:  { height: 3, borderRadius: 2 },
  secCount: { color: COLORS.textSecondary, fontSize: 11, fontWeight: '800',
              fontVariant: ['tabular-nums'] },
  secSeen:  { color: COLORS.textTertiary, fontSize: 9.5, marginTop: 2 },

  blockCard: { backgroundColor: COLORS.warningDim, marginTop: SPACE.md },
  errCard:   { backgroundColor: COLORS.dangerDim, marginTop: SPACE.md },
  blockHead: { color: COLORS.warning, fontSize: FONT.xs, fontWeight: '800',
               marginBottom: 6, letterSpacing: 0.3 },
  blockRow:  { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 3 },
  blockTxt:  { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  primary:    { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center', marginTop: SPACE.xl },
  primaryOff: { opacity: 0.45 },
  primaryTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
          marginTop: SPACE.sm, textAlign: 'center' },
});
