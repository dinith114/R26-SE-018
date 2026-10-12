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
import { LIVE_MS } from '../hooks/useLiveData';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import Toast from '../components/Toast';
import NodePicker from '../components/NodePicker';
import {
  getCalibration, getHouse, analyzePlacement, assignDevice, setColocation,
  getHouseHealth,
} from '../services/careV2';
import { sectionIssues, checksStarted, farmClock } from '../services/deviceHealth';
import { farmTime } from '../services/placementFlow';

/* The server refuses an 'end' sooner than this (house_planner.py), because
   under 40 minutes there are not three whole ten-minute periods with every
   node side by side, and the offsets cannot be measured. */
const MIN_COLOCATION_MINUTES = 40;
/* Readings this soon after 'end' are skipped by the analysis - the nodes are
   in somebody's hands, on the way to their sections. Matches SETTLE_MINUTES. */
const SETTLE_MINUTES = 15;

/* Long enough that a node which has genuinely stopped is obvious, short enough
   that ordinary Wi-Fi hiccups do not raise an alarm. Matches the backend. */
const SILENT_MINUTES = 120;

export default function CalibrationScreen({ route, navigation }) {
  const houseId = route.params?.houseId;

  const [cal,     setCal]     = useState(null);
  // Hardware checks (a sensor not answering, a node gone quiet). Allowed to
  // fail on its own: an older server without /health still shows the screen.
  const [health,  setHealth]  = useState(null);
  const [house,   setHouse]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [refresh, setRefresh] = useState(false);
  const [busy,    setBusy]    = useState(false);
  const [toast,   setToast]   = useState(null);
  /* Which section is waiting for a board, or null. Linking used to mean opening
     each section's own screen in turn: twelve sections meant twelve round trips
     through the dashboard, and this is the screen that already knows which ones
     are missing hardware. NodePicker is a FlatList, so it replaces the whole
     screen rather than sitting in a sheet - nesting a FlatList inside a
     ScrollView breaks its scrolling, which SectionDetailScreen learned first. */
  const [picking, setPicking] = useState(null);
  // { sectionId, short } while a link is in flight, else null
  const [linking, setLinking] = useState(null);
  // The phone's clock when the server's was read, so elapsed time between
  // refreshes is the server's plus how long the phone has waited since.
  const [loadedAt, setLoadedAt] = useState(Date.now());
  const [coBusy, setCoBusy] = useState(false);
  const [confirmRedo, setConfirmRedo] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, h, hl] = await Promise.all([
        getCalibration(houseId),
        getHouse(houseId).catch(() => null),
        getHouseHealth(houseId).catch(() => null),
      ]);
      setCal(c);
      setHealth(hl);
      setLoadedAt(Date.now());
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

  /* Refresh while the screen is OPEN, not only when it is opened.
     This screen is watched for minutes at a time while nodes are linked and
     readings arrive - it is the one screen a farmer sits on waiting for a
     number to move. It only ever loaded on focus and on pull-to-refresh, so a
     section that started reporting thirty seconds ago still read "never" until
     the screen was left and re-entered. Same interval the dashboard uses. */
  /* Twice the dashboard's interval, on purpose. Calibration is a THREE-DAY
     process; nothing on this screen changes meaningfully inside a minute, and
     each call asks Firebase for a key listing per section. At 30 s that was
     measured at 90 MB an hour of database egress and it is what pushed this
     project past the free 360 MB/day quota. The endpoint got cheaper too, but
     polling a three-day bar twice a minute was never the right rate. */
  useFocusEffect(useCallback(() => {
    load();
    const t = setInterval(load, LIVE_MS * 2);
    return () => clearInterval(t);
  }, [load]));

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

  /* Co-location: every node in the same air, so each sensor's own offset can
     be measured and removed before the nodes are spread out. The times are the
     server's - the button only says "now". */
  const colocate = async (action) => {
    setCoBusy(true);
    try {
      await setColocation(houseId, action);
      setConfirmRedo(false);
      await load();
      setToast({
        text: action === 'start' ? 'Started. Leave every node together for at least 40 minutes.'
          : action === 'end' ? 'Offsets can now be measured. Carry each node to its section.'
          : 'Co-location cleared.',
        kind: 'success',
      });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setCoBusy(false);
    }
  };

  /* WHICH section is being linked, not just THAT one is.
     Picking a node closed the picker instantly and then spent two round trips
     to the server - assign, then reload - with the OLD data still on screen. So
     the row the farmer had just acted on went on saying "Add node" for five to
     ten seconds, which reads as "it did not work", and the natural response is
     to press it again. Naming the row lets that one row say what is happening
     while the rest of the screen stays live. */
  const linkNode = async (dev) => {
    const sectionId = picking;
    const short = dev.shortId || dev.mac.slice(-4);
    setPicking(null);
    setLinking({ sectionId, short });
    try {
      await assignDevice(dev.mac, houseId, sectionId);
      await load();
      setToast({ text: `Node ${short} linked to ${sectionId}`, kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setLinking(null); }
  };

  /* Positions come from the house, readiness from the calibration endpoint.
     Joined here so a section that is silent is drawn differently on the map -
     seeing WHERE the gap is in the house is the point of having a map at all. */
  const sections = house?.sections || {};
  /* Whether a BOARD is linked, which is a different question from whether
     readings have arrived. Without this the map painted a section that has no
     hardware exactly like one whose node had died, so a house nobody had wired
     up yet looked like a farm full of dead sensors - and the two need opposite
     actions from the farmer. */
  const hasNode = (id) => !!((sections[id] || {}).node || {}).mac;
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
        kind: !hasNode(row.id) ? 'nonode' : silent ? 'offline' : 'real',
      };
    })
    .filter(Boolean);
  const missing = (cal?.sections || []).filter((r) => !hasNode(r.id)).length;

  const placed = nodes.length;
  const total = (cal?.sections || []).length;
  const ready = !!cal?.ready;
  // Allowed before the full window once every section has its readings and a
  // whole day is in - labelled as early everywhere it shows.
  const canRun = ready || !!cal?.canAnalyse;
  const early = !ready && !!cal?.early;
  const co = cal?.colocation || null;
  const serverNow = (cal?.serverNowMs || Date.now()) + (Date.now() - loadedAt);
  const coMinutes = co?.startMs && !co?.endMs ? (serverNow - co.startMs) / 60000 : null;
  const pct = cal ? Math.min(100, Math.round((cal.daysElapsed / cal.targetDays) * 100)) : 0;

  if (loading) {
    return (
      <View style={styles.container}>
        <ScreenHeader title="Calibrating" navigation={navigation} showBack />
        <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
      </View>
    );
  }

  /* Picking takes over the screen, the same way Add Section does. */
  if (picking) {
    return (
      <View style={styles.container}>
        <ScreenHeader title={`Node for ${picking}`}
          subtitle="Boards that are powered on and unclaimed"
          navigation={navigation} showBack />
        <NodePicker onSelect={linkNode} onSkip={() => setPicking(null)} />
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

        {/* co-location - before the nodes are spread out */}
        <Text style={styles.h}>First: each sensor's own offset</Text>
        <View style={[styles.card, SHADOW.sm]}>
          {!co?.startMs ? (
            <>
              <Text style={styles.coTxt}>
                Put every node side by side — same table, same shade — and press Start.
                Leave them at least {MIN_COLOCATION_MINUTES} minutes, press Done, then carry
                each one to its section. Two sensors in the same air rarely read the same;
                this measures by how much, so it is not mistaken for a warm spot.
              </Text>
              {missing > 0 && (
                <Text style={styles.coWarn}>
                  Link every node first. An unlinked node uploads nothing, so it would
                  miss this.
                </Text>
              )}
              {/* The analysis keeps only readings from after co-location, so
                  doing it late throws the days already recorded away. Said
                  before the button, not discovered after three days. */}
              {cal.daysElapsed >= 0.25 && (
                <Text style={styles.coWarn}>
                  Calibration has been running {cal.daysElapsed.toFixed(1)} days. Starting
                  this now restarts the count: only readings from after it are used.
                </Text>
              )}
              <TouchableOpacity style={[styles.coBtn, coBusy && styles.primaryOff]}
                onPress={() => colocate('start')} disabled={coBusy} activeOpacity={0.85}>
                {coBusy ? <ActivityIndicator color="#FFF" size="small" />
                        : <Text style={styles.coBtnTxt}>Start — the nodes are together</Text>}
              </TouchableOpacity>
            </>
          ) : !co.endMs ? (
            <>
              <View style={styles.coRow}>
                <Ionicons name="people-outline" size={16} color={COLORS.info} />
                <Text style={styles.coState}>
                  Together since {farmTime(co.startMs, false)} · {Math.floor(coMinutes)} min
                </Text>
              </View>
              <Text style={styles.coTxt}>
                {coMinutes >= MIN_COLOCATION_MINUTES
                  ? 'Long enough. Press Done, then carry each node to its own section.'
                  : `${Math.ceil(MIN_COLOCATION_MINUTES - coMinutes)} more minutes before Done. `
                    + 'Keep them out of direct sun and do not move them.'}
              </Text>
              <View style={styles.coBtns}>
                <TouchableOpacity
                  style={[styles.coBtn, { flex: 1 },
                          (coBusy || coMinutes < MIN_COLOCATION_MINUTES) && styles.primaryOff]}
                  onPress={() => colocate('end')}
                  disabled={coBusy || coMinutes < MIN_COLOCATION_MINUTES} activeOpacity={0.85}>
                  {coBusy ? <ActivityIndicator color="#FFF" size="small" />
                          : <Text style={styles.coBtnTxt}>Done — spreading them out</Text>}
                </TouchableOpacity>
                <TouchableOpacity style={styles.coGhost} onPress={() => colocate('clear')}
                  disabled={coBusy} activeOpacity={0.7}>
                  <Text style={styles.coGhostTxt}>Cancel</Text>
                </TouchableOpacity>
              </View>
            </>
          ) : (
            <>
              <View style={styles.coRow}>
                <Ionicons name="checkmark-circle" size={16} color={COLORS.primary} />
                <Text style={styles.coState}>
                  Together {farmTime(co.startMs, false)}–{farmTime(co.endMs, false)}
                  {' '}({Math.round((co.endMs - co.startMs) / 60000)} min)
                </Text>
              </View>
              <Text style={styles.coTxt}>
                Readings from the {SETTLE_MINUTES} minutes after are skipped while the nodes
                are carried. Everything after that is the house.
              </Text>
              <TouchableOpacity style={styles.coLink} disabled={coBusy} activeOpacity={0.7}
                onPress={() => (confirmRedo ? colocate('clear') : setConfirmRedo(true))}>
                <Text style={[styles.coGhostTxt, confirmRedo && { color: COLORS.danger }]}>
                  {confirmRedo ? 'Tap again to clear it and start over' : 'Redo'}
                </Text>
              </TouchableOpacity>
            </>
          )}
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
        {!!health && !checksStarted(health) && (
          <Text style={styles.missingNote}>
            Sensor checks start a few minutes after the server restarts.
          </Text>
        )}
        {missing > 0 && (
          <Text style={styles.missingNote}>
            {missing} of {total} section{total === 1 ? '' : 's'} still {missing === 1 ? 'has' : 'have'} no
            node. Link them here — calibration cannot finish until every section
            is recording, because the analysis only uses moments they all
            contributed to.
          </Text>
        )}
        <View style={[styles.card, SHADOW.sm]}>
          {(cal.sections || []).map((row) => {
            const silent = row.lastSeenMinAgo == null || row.lastSeenMinAgo > SILENT_MINUTES;
            const frac = Math.min(1, row.readings / Math.max(1, row.needed));
            const node = (sections[row.id] || {}).node;
            const wired = !!(node || {}).mac;
            return (
              <View key={row.id} style={styles.secRow}>
                {/* Grey for "no board yet", red only for a board that has gone
                    quiet. A section nobody has wired up is not a fault. */}
                <View style={[styles.secDot, {
                  backgroundColor: !wired ? COLORS.textTertiary
                    : row.ok ? COLORS.primary
                    : silent ? COLORS.danger : COLORS.warning,
                }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.secName}>{row.name}</Text>
                  {/* The first standing hardware problem, in the words the
                      push used. A dead sensor during calibration is a hole in
                      the data the analysis cannot fill, so it is said here,
                      where the farmer is already looking. */}
                  {sectionIssues(health, row.id).slice(0, 1).map((i) => (
                    <Text key={i.kind} style={styles.secIssue} numberOfLines={2}>
                      {i.title}{i.sinceMs ? ` · since ${farmClock(i.sinceMs)}` : ''}
                    </Text>
                  ))}
                  {wired ? (
                    <View style={styles.secBarTrack}>
                      <View style={[styles.secBarFill, {
                        width: `${frac * 100}%`,
                        backgroundColor: row.ok ? COLORS.primary : COLORS.warning,
                      }]} />
                    </View>
                  ) : (
                    <Text style={styles.secNoNode}>No node linked</Text>
                  )}
                </View>

                {wired ? (
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={styles.secCount}>{row.readings}/{row.needed}</Text>
                    <Text style={[styles.secSeen, silent && { color: COLORS.danger }]}>
                      {row.lastSeenMinAgo == null ? 'never'
                        : row.lastSeenMinAgo < 60 ? `${Math.round(row.lastSeenMinAgo)}m ago`
                        : `${(row.lastSeenMinAgo / 60).toFixed(0)}h ago`}
                    </Text>
                  </View>
                ) : linking && linking.sectionId === row.id ? (
                  <View style={[styles.linkBtn, styles.linkBusy]}>
                    <ActivityIndicator size="small" color={COLORS.primary} />
                    <Text style={styles.linkBtnTxt}>Adding {linking.short}…</Text>
                  </View>
                ) : (
                  <TouchableOpacity
                    style={styles.linkBtn}
                    onPress={() => setPicking(row.id)}
                    disabled={!!linking}
                    activeOpacity={0.8}
                    accessibilityRole="button"
                    accessibilityLabel={`Link a sensor node to ${row.name}`}>
                    <Ionicons name="add" size={15} color={COLORS.primary} />
                    <Text style={styles.linkBtnTxt}>Add node</Text>
                  </TouchableOpacity>
                )}
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
          style={[styles.primary, (!canRun || busy || !placed) && styles.primaryOff]}
          onPress={analyse} disabled={!canRun || busy || !placed} activeOpacity={0.85}>
          {busy ? <ActivityIndicator color="#FFF" />
                : <Text style={styles.primaryTxt}>
                    {early ? `Analyse now · ${cal.daysElapsed.toFixed(1)} of ${cal.targetDays} days`
                           : 'Analyse placement'}
                  </Text>}
        </TouchableOpacity>
        <Text style={styles.foot}>
          {ready
            ? 'Temperature, humidity and VPD from these sections. Three placement '
              + 'methods are compared, and scored on later readings none of them saw.'
            : early
              ? `An early run, on ${cal.daysElapsed.toFixed(1)} days instead of `
                + `${cal.targetDays}. The full result is steadier; the dates used are shown `
                + 'with it. Takes ten to twenty seconds.'
              : 'Available once every section has enough data and a full day has '
                + 'passed. Leave the sensors where they are until then.'}
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
  secNoNode:{ color: COLORS.textTertiary, fontSize: 11, marginTop: 3 },
  secIssue: { color: COLORS.danger, fontSize: 11, fontWeight: '700', marginTop: 3 },

  linkBtn:   { flexDirection: 'row', alignItems: 'center', gap: 2,
               backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.full,
               paddingHorizontal: SPACE.md, paddingVertical: 6 },
  linkBtnTxt:{ color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  linkBusy:  { opacity: 0.75 },

  missingNote: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18,
                 marginBottom: SPACE.md, marginTop: -SPACE.xs },

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

  coTxt:   { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },
  coWarn:  { color: COLORS.warning, fontSize: FONT.xs, lineHeight: 17, marginTop: SPACE.sm,
             fontWeight: '700' },
  coRow:   { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 },
  coState: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '800',
             fontVariant: ['tabular-nums'] },
  coBtns:  { flexDirection: 'row', gap: SPACE.sm, alignItems: 'center' },
  coBtn:   { backgroundColor: COLORS.info, borderRadius: RADIUS.sm, paddingVertical: SPACE.md,
             alignItems: 'center', marginTop: SPACE.md, paddingHorizontal: SPACE.md },
  coBtnTxt:{ color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  coGhost: { paddingVertical: SPACE.md, paddingHorizontal: SPACE.md, marginTop: SPACE.md },
  coGhostTxt: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  coLink:  { alignSelf: 'center', paddingVertical: SPACE.sm, marginTop: SPACE.sm },
});
