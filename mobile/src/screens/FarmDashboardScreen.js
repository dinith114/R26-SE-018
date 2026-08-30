/**
 * The farm dashboard.
 *
 * REDESIGNED 30 Aug 2026, because the old screen was a report when it needed to
 * be a triage screen.
 *
 * What was wrong, counted rather than felt. Before the farmer saw a single
 * house, eight full-width blocks stacked up: the header, ModeToggle, the stale
 * banner, a four-tile FarmSummary, a five-number stat strip, a calibrating
 * strip, the action row, then AutoControls. "Sections" was stated three times
 * over (header subtitle, summary tile, stat strip) and "houses" twice. Two
 * separate automation controls sat eighty lines apart. And nothing was ranked:
 * a section that needed water rendered identically to one that was fine, so
 * finding the one that mattered meant reading all eight.
 *
 * The order now answers three questions, in the order a farmer asks them:
 *
 *   1. Does anything need me?      -> the status band, then Needs you now
 *   2. Is the system doing its job -> what is scheduled next, then Automation
 *   3. Show me the farm            -> houses, collapsed, urgent sections first
 *
 * The single biggest change is **Needs you now**: sections that want something
 * are lifted OUT of their houses to the top, with the reason written out. That
 * is what the app is opened for. Everything else on this screen is browsing.
 *
 * Colour discipline: one accent per card, derived from state. Readings are
 * neutral text and only take colour when the value is outside its band, so
 * colour means "look here" rather than "this is a temperature". The four
 * per-metric colours the old cards used made every card equally loud.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useLiveData, { LIVE_MS } from '../hooks/useLiveData';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import ModeToggle from '../components/ModeToggle';
import AutoControls from '../components/AutoControls';
import { FarmSkeleton } from '../components/Skeleton';
import { FreshnessBadge, FarmStaleBanner, STATE_STYLE } from '../components/Freshness';
import RenameDialog from '../components/RenameDialog';
import SelectSheet from '../components/SelectSheet';
import ConfirmSheet from '../components/ConfirmSheet';
import {
  getOverview, deleteHouse,
  renameFarm, renameHouse, getAlarms, humidityStatus, vpdStatus,
  getDevices, setHouseMaster,
} from '../services/careV2';

/** "GOOD" shouted at the farmer; "Good" just tells them. */
const titleCase = (t) => (t ? t.charAt(0) + t.slice(1).toLowerCase() : t);

/* A grid of nine dots said nothing about a greenhouse. These read as what the
   structure actually is: something that shades or covers the plants. */
const TYPE_ICON = {
  'shade-net':    'umbrella-outline',
  'shade-cloth':  'umbrella-outline',
  'double-shade': 'layers-outline',
  'poly-tunnel':  'partly-sunny-outline',
};

/* Why a section wants attention, and how urgent that is.
 *
 * The ranking is not cosmetic. A section that is not reporting cannot be
 * watered at all - the command is a document the node polls, and a silent node
 * never reads it - so a connection problem has to be fixed before anything
 * below it can even be attempted. Sorting by this is what lets the farmer stop
 * reading at the first row that is fine.
 *
 * TWO THINGS DELIBERATELY EXCLUDED, and both were wrong in the first draft:
 *
 * 'nonode' is NOT here. A section with no hardware is a state of the farm, not
 * a task. The whole point of the placement flow is that the farmer REMOVES the
 * sensors it finds redundant, so on a twenty-section house running four sensors
 * this list would carry sixteen permanent rows of "No node installed" - which
 * would train them to ignore the one row that matters. It is counted in the
 * band instead.
 *
 * 'future' gets its OWN row rather than being folded into "not reporting".
 * Freshness.js makes the point exactly: the device IS reporting, it is the
 * timestamp that cannot be believed, and sending a farmer to check the battery
 * would send them after the wrong fault. It is also what a simulator writing
 * bad timestamps looks like. */
function attentionOf(s) {
  const fx = s.freshness;
  if (fx?.state === 'nonode') return null;
  /* An interpolated zone is the placement decision working, not a fault. It
     carries trusted:false because these numbers are not a measurement and must
     never be shown as one - but that flag is about provenance, not health, and
     reading it as "not reporting" would put every unmonitored zone in this list
     permanently. After the analysis most of a house is estimated by design. */
  if (fx?.state === 'estimated') return null;
  if (fx?.state === 'future')
    return { rank: 0, icon: 'time-outline', tone: COLORS.warning,
             text: 'Clock wrong — readings cannot be trusted',
             fix: 'Check the device clock' };
  if (fx && !fx.trusted)
    return { rank: 1, icon: 'cloud-offline-outline', tone: COLORS.danger,
             text: 'Not reporting', fix: 'Check power and Wi-Fi' };
  if (s.tray?.status === 'fill')
    return { rank: 2, icon: 'water-outline', tone: COLORS.warning,
             text: `Tray needs ${s.tray.fillSeconds}s of water`, fix: 'Fill tray' };
  if (s.fertilizer?.due)
    return { rank: 3, icon: 'nutrition-outline', tone: COLORS.fertilizer,
             text: `Feed ${s.fertilizer.npkType || 'due'}`
                 + ` at ${Math.round((s.fertilizer.strength ?? 0.5) * 100)}%`,
             fix: 'With the next watering' };
  return null;
}

/* "06:42" against the clock. Kept as strings on purpose: the plan is a
   wall-clock time on the FARM's day, and turning it into a Date here would
   quietly reinterpret it in the phone's timezone. */
const nowHHMM = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

export default function FarmDashboardScreen({ navigation }) {
  // { kind: 'farm' } or { kind: 'house', id, name } — null when nothing is open
  const [renaming, setRenaming] = useState(null);
  // which way of adding a house the farmer is being asked to choose
  const [adding, setAdding] = useState(false);
  /* houseId -> the farmer's explicit choice for that house. UNSET means
     collapsed, not expanded.

     Every house opening at once buries the screen: with four houses of eight
     sections the farmer scrolls past thirty-two cards to reach the second
     house's name. Folded, the whole farm is one screen and they open the one
     they came for. An explicit expand is remembered for as long as the screen
     is, so this costs a tap once rather than every refresh. */
  const [expanded, setExpanded] = useState({});
  const isCollapsed = (id) => !expanded[id];
  const toggleHouse = (id) => setExpanded(c => ({ ...c, [id]: !c[id] }));
  // live: auto-refresh every 15 s while this screen is open
  const { data, loading, error, refreshing, refresh: pullRefresh, reload: load } =
    useLiveData(getOverview, LIVE_MS);
  // the farm's Auto switch + how many things are waiting on the farmer
  const { data: auto, reload: refreshAuto } = useLiveData(() => getAlarms(1), LIVE_MS);

  /* Farm-level Water Now / Fill Tray.
     These are NOT the section buttons. A section button acts on the one zone
     you are looking at; these ask which house, then which sections inside it,
     and then hand the list to the run screen so the farmer can watch each one
     go. "Work out plan" and "Check & fill trays" used to live here and were
     removed: planning already happens automatically at dawn, so a manual
     trigger for it was a button that looked like an action and moved nothing. */
  const [flow, setFlow] = useState(null);   // { kind, step, houseId, sectionIds }

  /* Choosing the house's master controller.
     { houseId, name, current, devices } — devices null while they load.

     This lived inside one section's Setup tab, which is the wrong place for it
     twice over: the master belongs to the HOUSE, not to a section, and a farmer
     looking for it had to guess which of eight sections to open. */
  const [master, setMaster] = useState(null);
  const [savingMaster, setSavingMaster] = useState(false);

  const openMaster = async (h) => {
    setMaster({ houseId: h.houseId, name: h.meta?.name || h.houseId,
                current: h.meta?.masterMac || null, devices: null });
    try {
      const r = await getDevices();
      setMaster((m) => (m && m.houseId === h.houseId
        ? { ...m, devices: r.devices || [] } : m));
    } catch (e) {
      setMaster(null);
      Alert.alert('Could not list nodes', e.message);
    }
  };

  /* Two kinds of board can run the valves, and the difference is physical.
     A node already IN this house does both jobs: it keeps reporting its
     section's readings AND drives the relay board. A spare board that belongs
     to no house can only be a controller - it is not sitting in any section, so
     anything it "measured" would describe wherever it happens to be, which is
     the one mistake this whole system exists to avoid.
     Boards belonging to a DIFFERENT house are excluded: taking one would strip
     that house of a sensor to solve this house's problem. */
  const masterOptions = () => {
    const list = master?.devices || [];
    const mine = list.filter((d) => d.house === master.houseId);
    const free = list.filter((d) => !d.assignedTo);
    const row = (d, sub) => ({
      key: d.mac,
      label: `Node ${d.shortId || d.mac.slice(-4)}${d.online ? '' : '  (offline)'}`,
      sub,
    });
    return [
      ...mine.map((d) => row(d, `In ${d.section} · keeps sensing and runs the valves`)),
      ...free.map((d) => row(d, 'Spare board · runs the valves only, gives no readings')),
      ...(master?.current ? [{ key: '__none__', label: 'No master controller',
                               sub: 'Sections without a node of their own cannot be watered.' }] : []),
    ];
  };

  const saveMaster = async (mac) => {
    const { houseId } = master;
    setMaster(null);
    setSavingMaster(true);
    try {
      await setHouseMaster(houseId, mac === '__none__' ? null : mac);
      await load();
    } catch (e) {
      Alert.alert('Could not set the master', e.message);
    } finally { setSavingMaster(false); }
  };

  const startFlow = (kind) => {
    const list = data?.houses || [];
    // One house is the normal case on this farm, so skip a step that would only
    // ever show a single row.
    if (list.length === 1) {
      setFlow({ kind, step: 'sections', houseId: list[0].houseId, sectionIds: [] });
    } else {
      setFlow({ kind, step: 'house', houseId: null, sectionIds: [] });
    }
  };

  const flowHouse = (data?.houses || []).find((h) => h.houseId === flow?.houseId);
  const flowSections = flowHouse?.sections || [];

  /* A tray in cooldown cannot take water - the backend refuses the fill - so a
     TRAY flow must not offer it, exactly as neither flow offers a section whose
     node has gone quiet. Watering the roots is a separate loop and is never
     blocked by this. Sections removed for cooldown are counted so the sheet can
     say why they are missing; a section that simply vanishes reads as a bug. */
  const isTrayFlow = flow?.kind !== 'water';
  const trayCooling = (x) =>
    x?.tray?.status === 'cooldown' && Number(x?.tray?.hoursUntilNextFill) > 0;
  const flowLive = flowSections.filter((x) => x.freshness?.state === 'live');
  const flowPickable = flowLive.filter((x) => !(isTrayFlow && trayCooling(x)));
  const coolingHidden = flowLive.length - flowPickable.length;
  const chosen = flowSections.filter((x) => (flow?.sectionIds || []).includes(x.sectionId));

  const launch = () => {
    const kind = flow.kind;
    const targets = chosen.map((x) => ({
      houseId: flow.houseId,
      sectionId: x.sectionId,
      name: x.meta?.name || x.sectionId,
      durationSec: x.plan?.durationSec || 45,
      fillSeconds: x.tray?.fillSeconds || 15,
      withFertilizer: !!x.fertilizer?.due,
    }));
    setFlow(null);
    navigation.navigate('Run', { action: kind === 'water' ? 'water' : 'tray', targets });
  };

  const houses   = data?.houses || [];
  const noFarm   = !loading && !error && houses.length === 0;
  const flat     = houses.flatMap(h => (h.sections || []).map(s => ({
    ...s, houseId: h.houseId, houseName: h.meta?.name || h.houseId,
  })));
  const sections = flat.length;

  /* One pass, every count the screen needs. The old code walked `flat` six
     separate times for numbers that were then shown in three different places. */
  const needing = flat
    .map(s => ({ s, a: attentionOf(s) }))
    .filter(x => x.a)
    .sort((x, y) => x.a.rank - y.a.rank);
  const calibrating = houses.filter(h => h.meta?.lifecycle === 'calibrating').length;
  const nodes       = flat.filter(s => s.node?.mac || s.meta?.deviceMac).length;
  /* Sections running WITHOUT hardware. After the placement flow this is the
     normal state of most of a house, not a fault, so it is reported here as a
     fact and never in the action list.

     It replaces an `estimated` count that was structurally always zero:
     /overview does not return an `estimated` field on sections at all, so
     `flat.filter(s => s.estimated)` could never match anything. A number that
     can only ever read 0 is worse than no number - it says the farm has no
     interpolated zones, which is a claim, not an absence. */
  const noNode      = flat.filter(s => s.freshness?.state === 'nonode').length;
  /* Zones being interpolated. Now real data - /overview reports the state, so
     unlike the count this replaced, this one can actually be non-zero. */
  const estimated   = flat.filter(s => s.freshness?.state === 'estimated').length;
  const urgent      = needing.filter(x => x.a.rank <= 1).length;
  const alertCount  = needing.length;

  /* The next thing the farm will do on its own. Buried in a chip inside an
     expanded section card before, which meant the single most useful fact on
     the screen took two taps to reach. */
  const t = nowHHMM();
  const upcoming = flat
    .filter(s => s.plan?.waterTime)
    .map(s => ({ at: s.plan.waterTime, secs: s.plan.durationSec,
                 name: s.meta?.name || s.sectionId,
                 houseId: s.houseId, sectionId: s.sectionId }))
    .sort((a, b) => a.at.localeCompare(b.at));
  const nextUp = upcoming.find(u => u.at > t) || upcoming[0];
  const nextIsTomorrow = !!upcoming.length && !upcoming.find(u => u.at > t);

  /* The band's tone. Danger only for things that STOP the farm working; a tray
     wanting a top-up is ordinary business and must not paint the screen red,
     or red stops meaning anything. */
  const tone = urgent ? COLORS.danger : needing.length ? COLORS.warning : COLORS.success;
  const headline = urgent
    ? `${urgent} section${urgent === 1 ? '' : 's'} need${urgent === 1 ? 's' : ''} fixing`
    : needing.length
      ? `${needing.length} section${needing.length === 1 ? '' : 's'} need${needing.length === 1 ? 's' : ''} you`
      : sections ? 'Everything is running' : 'No sections yet';

  return (
    <View style={styles.container}>
      {/* the SAME header every other tab uses, never forked for this screen.
          NO subtitle: it used to read "1 house · 8 sections", which the status
          band below states again with the nodes count beside it. Saying it
          twice, forty pixels apart, is what made the top of this screen feel
          like filler. `ownerName` was the other candidate and is dead - the
          backend notes it is "read by NOTHING". */}
      <ScreenHeader
        title={data?.farm?.farmName || 'My Farm'}
        navigation={navigation}
        alertCount={alertCount}
        showSettings
      />
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} tintColor={COLORS.primary}
          onRefresh={pullRefresh} />}
      >
        {loading ? (
          <FarmSkeleton />
        ) : error ? (
          <View style={[styles.errCard, SHADOW.sm]}>
            <Ionicons name="cloud-offline-outline" size={22} color={COLORS.danger} />
            <Text style={styles.errText}>{error}{'\n'}Check the backend is running and Firebase rules allow access.</Text>
          </View>
        ) : noFarm ? (
          <View style={[styles.emptyCard, SHADOW.sm]}>
            <Ionicons name="leaf-outline" size={44} color={COLORS.primary} />
            <Text style={styles.emptyTitle}>Welcome, let's set up your farm</Text>
            <Text style={styles.emptyText}>
              Add your greenhouses and their sections. Each section is one area with its
              own conditions and its own sensor device.
            </Text>
            <TouchableOpacity style={[styles.setupBtn, SHADOW.md]}
              onPress={() => navigation.navigate('FarmSetup')} activeOpacity={0.85}>
              <Ionicons name="add-circle-outline" size={20} color="#FFF" />
              <Text style={styles.setupBtnText}>Set Up My Farm</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {/* devices that stopped reporting, before any numbers they affect */}
            <FarmStaleBanner sections={flat} />

            {/* ── 1. Does anything need me? ─────────────────────────────── */}
            <View style={[styles.band, { borderLeftColor: tone }, SHADOW.sm]}>
              <View style={styles.bandTop}>
                <View style={[styles.bandIcon, { backgroundColor: `${tone}1A` }]}>
                  <Ionicons
                    name={urgent ? 'alert-circle' : needing.length ? 'time-outline' : 'checkmark-circle'}
                    size={22} color={tone} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.bandTitle, { color: tone }]}>{headline}</Text>
                  {/* Counts, stated ONCE. This line replaces a four-tile summary
                      and a five-number strip that between them said "sections"
                      twice and "houses" twice more than the header already did. */}
                  <Text style={styles.bandSub}>
                    {houses.length} house{houses.length === 1 ? '' : 's'}
                    {' · '}{sections} section{sections === 1 ? '' : 's'}
                    {' · '}{nodes} node{nodes === 1 ? '' : 's'}
                    {estimated > 0 ? ` · ${estimated} estimated` : ''}
                    {noNode > 0 ? ` · ${noNode} without one` : ''}
                  </Text>
                </View>
              </View>

              {calibrating > 0 && (
                <Text style={styles.bandNote}>
                  <Text style={{ fontWeight: '800' }}>{calibrating} house
                  {calibrating === 1 ? ' is' : 's are'} calibrating</Text>
                  {' — collecting data before their sensor positions are decided. '}
                  They are not watering to a plan yet.
                </Text>
              )}
            </View>

            {/* ── 2. What needs doing, lifted out of the houses ──────────── */}
            {needing.length > 0 && (
              <View style={[styles.card, SHADOW.sm]}>
                <Text style={styles.cardTitle}>Needs you now</Text>
                {needing.map(({ s, a }) => (
                  <TouchableOpacity
                    key={`${s.houseId}/${s.sectionId}`}
                    style={styles.needRow}
                    activeOpacity={0.7}
                    accessibilityRole="button"
                    accessibilityLabel={`${s.meta?.name || s.sectionId} in ${s.houseName}. ${a.text}. ${a.fix}.`}
                    onPress={() => navigation.navigate('SectionDetail', {
                      houseId: s.houseId, sectionId: s.sectionId, houseName: s.houseName })}>
                    <View style={[styles.needIcon, { backgroundColor: `${a.tone}1A` }]}>
                      <Ionicons name={a.icon} size={16} color={a.tone} />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={styles.needName} numberOfLines={1}>
                        {s.meta?.name || s.sectionId}
                        <Text style={styles.needWhere}>  {s.houseName}</Text>
                      </Text>
                      <Text style={[styles.needText, { color: a.tone }]} numberOfLines={1}>
                        {a.text}
                      </Text>
                    </View>
                    <Text style={styles.needFix} numberOfLines={1}>{a.fix}</Text>
                    <Ionicons name="chevron-forward" size={15} color={COLORS.textTertiary} />
                  </TouchableOpacity>
                ))}
              </View>
            )}

            {/* ── 3. The two actions, reachable without scrolling ────────── */}
            <View style={styles.actRow}>
              {/* These two look like siblings but are not: watering soaks the
                  roots, filling a tray only raises the air humidity around the
                  plants. The labels have to carry that difference. */}
              <TouchableOpacity style={[styles.actBtn, { backgroundColor: COLORS.primary }, SHADOW.md]}
                onPress={() => startFlow('water')} disabled={!sections} activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Water. Choose which sections, then watch each one run.">
                <Ionicons name="rainy-outline" size={17} color="#FFF" />
                <Text style={styles.actText}>Water Now</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.actBtn, { backgroundColor: COLORS.info }, SHADOW.md]}
                onPress={() => startFlow('tray')} disabled={!sections} activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Fill humidity trays. Choose which sections, then watch each one run.">
                <Ionicons name="add-circle-outline" size={17} color="#FFF" />
                <Text style={styles.actText}>Fill Tray</Text>
              </TouchableOpacity>
            </View>

            {/* ── 4. Is the system doing its job? ────────────────────────── */}
            <View style={[styles.card, SHADOW.sm]}>
              <Text style={styles.cardTitle}>Automation</Text>
              {/* ModeToggle and AutoControls used to sit eighty lines apart with
                  four unrelated blocks between them, so the farmer had to know
                  which of two switches did what. They are one control surface
                  and now read as one. */}
              <ModeToggle style={styles.modeInCard} />
              <AutoControls autoMode={auto?.autoMode} pendingAction={auto?.pendingAction || 0}
                onChanged={refreshAuto} />

              {nextUp ? (
                <TouchableOpacity
                  style={styles.nextRow}
                  activeOpacity={0.7}
                  accessibilityRole="button"
                  accessibilityLabel={`Next watering: ${nextUp.name} at ${nextUp.at} for ${nextUp.secs} seconds.`}
                  onPress={() => navigation.navigate('SectionDetail', {
                    houseId: nextUp.houseId, sectionId: nextUp.sectionId })}>
                  <Ionicons name="alarm-outline" size={15} color={COLORS.info} />
                  <Text style={styles.nextText} numberOfLines={1}>
                    Next: <Text style={styles.nextStrong}>{nextUp.name}</Text> at{' '}
                    <Text style={styles.nextStrong}>{nextUp.at}</Text>
                    {nextUp.secs ? ` for ${nextUp.secs}s` : ''}
                    {nextIsTomorrow ? ' tomorrow' : ''}
                  </Text>
                  <Ionicons name="chevron-forward" size={14} color={COLORS.textTertiary} />
                </TouchableOpacity>
              ) : (
                <Text style={styles.nextNone}>
                  No watering planned yet — the plan is worked out at dawn from that
                  morning's readings.
                </Text>
              )}
            </View>

            {/* ── 5. The farm itself ─────────────────────────────────────── */}
            {houses.map(h => {
              /* Urgent sections first, so a farmer who opens a house can stop
                 reading once the rows stop being coloured. Within a rank the
                 original order is kept, which keeps S1..S8 in order for the
                 common case where nothing is wrong. */
              const secs = [...(h.sections || [])].sort((a, b) => {
                const ra = attentionOf(a)?.rank ?? 99, rb = attentionOf(b)?.rank ?? 99;
                return ra - rb;
              });
              const bad  = secs.filter(z => z.freshness && !z.freshness.trusted).length;
              const need = secs.filter(z => z.tray?.status === 'fill').length;

              return (
              // BIG house card — sections live INSIDE it as sub-cards
              <View key={h.houseId} style={[styles.houseCard, SHADOW.md]}>
                <View style={styles.houseHead}>
                  {/* the whole title block folds the house away, so the tap
                      target is the size of the thing it collapses */}
                  <TouchableOpacity
                    style={styles.houseTitleBtn}
                    onPress={() => toggleHouse(h.houseId)}
                    activeOpacity={0.7}
                    accessibilityRole="button"
                    accessibilityState={{ expanded: !isCollapsed(h.houseId) }}
                    accessibilityLabel={
                      `${h.meta?.name || h.houseId}, ${h.sections?.length || 0} sections. `
                      + `${isCollapsed(h.houseId) ? 'Collapsed. Tap to expand.' : 'Expanded. Tap to collapse.'}`
                    }>
                    <View style={styles.houseIcon}>
                      <Ionicons name={TYPE_ICON[h.meta?.type] || 'home-outline'} size={19} color={COLORS.primary} />
                    </View>
                    <View style={{ flex: 1 }}>
                      {/* The name gets the whole line. Sharing it with a badge
                          meant "Simulated House (..." on any name of normal
                          length, and the badge, chevron and map button then
                          fought for what was left. The state belongs on the
                          detail line, where there is room for the word. */}
                      <Text style={styles.houseName} numberOfLines={1}>
                        {h.meta?.name || h.houseId}
                      </Text>
                      <View style={styles.houseMetaRow}>
                        {h.meta?.lifecycle === 'calibrating' && (
                          <View style={styles.calBadge}>
                            <Ionicons name="hourglass-outline" size={9} color={COLORS.warning} />
                            <Text style={styles.calBadgeTxt}>Calibrating</Text>
                          </View>
                        )}
                        <Text style={styles.houseMeta} numberOfLines={1}>
                          {h.meta?.type || 'house'} · {h.sections?.length || 0} sections
                          {h.meta?.plantCount ? ` · ${h.meta.plantCount} plants` : ''}
                        </Text>
                      </View>
                    </View>
                    <Ionicons
                      name={isCollapsed(h.houseId) ? 'chevron-down' : 'chevron-up'}
                      size={18} color={COLORS.textTertiary} style={{ marginRight: SPACE.sm }} />
                  </TouchableOpacity>

                  {/* Into the map, or into calibration if that is where the
                      house is. One button rather than two: which screen is
                      useful depends entirely on the lifecycle, and offering
                      both would ask the farmer a question the app can answer. */}
                  <TouchableOpacity
                    style={styles.mapBtn}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    accessibilityRole="button"
                    accessibilityLabel={h.meta?.lifecycle === 'calibrating'
                      ? `Calibration progress for ${h.meta?.name || h.houseId}`
                      : `Map view of ${h.meta?.name || h.houseId}`}
                    onPress={() => navigation.navigate(
                      h.meta?.lifecycle === 'calibrating' ? 'Calibration' : 'HouseMap',
                      { houseId: h.houseId })}>
                    <Ionicons
                      name={h.meta?.lifecycle === 'calibrating' ? 'hourglass-outline' : 'map-outline'}
                      size={17} color={COLORS.primary} />
                  </TouchableOpacity>

                  {/* The master controller belongs to the house, so it is set
                      from the house. Amber when one is named, hollow when not:
                      a house with no master cannot water any section that has
                      no node of its own, which is most of them after the
                      placement decision. */}
                  <TouchableOpacity
                    style={[styles.mapBtn,
                            h.meta?.masterMac && { backgroundColor: COLORS.warningDim }]}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    disabled={savingMaster}
                    accessibilityRole="button"
                    accessibilityLabel={h.meta?.masterMac
                      ? `Master controller for ${h.meta?.name || h.houseId} is node ${String(h.meta.masterMac).slice(-4)}. Tap to change.`
                      : `Choose a master controller for ${h.meta?.name || h.houseId}`}
                    onPress={() => openMaster(h)}>
                    <Ionicons name={h.meta?.masterMac ? 'git-network' : 'git-network-outline'}
                      size={16} color={h.meta?.masterMac ? COLORS.warning : COLORS.textTertiary} />
                  </TouchableOpacity>

                  <TouchableOpacity hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                    accessibilityRole="button"
                    accessibilityLabel={`Options for ${h.meta?.name || h.houseId}: rename or delete`}
                    onPress={() => Alert.alert(
                      h.meta?.name || h.houseId,
                      'What would you like to do with this house?',
                      [{ text: 'Cancel', style: 'cancel' },
                       { text: 'Rename house',
                         onPress: () => setRenaming({ kind: 'house', id: h.houseId,
                                                      name: h.meta?.name || h.houseId }) },
                       { text: 'Delete house', style: 'destructive', onPress: () => Alert.alert(
                          'Delete this house?',
                          `“${h.meta?.name || h.houseId}” and all ${h.sections?.length || 0} of its `
                          + 'sections will be removed. This cannot be undone.',
                          [{ text: 'Cancel', style: 'cancel' },
                           { text: 'Delete', style: 'destructive', onPress: async () => {
                              try { await deleteHouse(h.houseId); await load(); }
                              catch (e) { Alert.alert('Failed', e.message); } } }]
                       ) }]
                    )}>
                    <Ionicons name="ellipsis-horizontal" size={18} color={COLORS.textTertiary} />
                  </TouchableOpacity>
                </View>

                {isCollapsed(h.houseId) ? (
                  <Text style={styles.collapsedNote}>
                    {(() => {
                      const bits = [];
                      if (bad)  bits.push(`${bad} not reporting`);
                      if (need) bits.push(`${need} need water`);
                      return bits.length ? bits.join(', ') : 'All sections are fine';
                    })()}
                  </Text>
                ) : (<>
                {secs.map(s => {
                  const rh   = humidityStatus(s.latest?.humidity);
                  const vp   = vpdStatus(s.latest?.vpd);
                  const plan = s.plan || {};
                  const tray = s.tray || {};
                  /* The card took its colour from the HUMIDITY reading and its
                     status word from the humidity band, regardless of whether
                     that reading meant anything. A section with no node at all
                     therefore drew itself green and said GOOD, because the
                     model's 70% fallback default sits inside the ideal band.
                     Trust decides the colour now; humidity only decides it
                     once the reading is trustworthy. */
                  const fx   = s.freshness;
                  const good = fx?.trusted !== false;
                  const fst  = STATE_STYLE[fx?.state] || STATE_STYLE.never;
                  const accent = good ? rh.color : fst.color;
                  return (
                    <TouchableOpacity key={s.sectionId}
                      style={[styles.secCard, { borderLeftColor: accent }]}
                      onPress={() => navigation.navigate('SectionDetail',
                        { houseId: h.houseId, sectionId: s.sectionId, houseName: h.meta?.name })}
                      activeOpacity={0.7}>
                      <View style={styles.secHead}>
                        <View style={[styles.secDot, { backgroundColor: accent }]} />
                        <Text style={styles.secName} numberOfLines={1}>{s.meta?.name || s.sectionId}</Text>
                        <View style={[styles.badge, { backgroundColor: `${accent}1F` }]}>
                          <Text style={[styles.badgeText, { color: accent }]}>
                            {good ? titleCase(rh.label) : fst.word}
                          </Text>
                        </View>
                      </View>

                      <View style={styles.secSubHead}>
                        {s.meta?.label ? <Text style={styles.secLabel} numberOfLines={1}>{s.meta.label}</Text> : null}
                        <FreshnessBadge freshness={s.freshness} />
                      </View>

                      {/* Readings as labelled columns. As one long line they ran
                          together ("Light 13022VPD 2.007") and were unreadable.

                          Values are NEUTRAL unless they are outside their band.
                          Colouring all four by metric - temperature orange, light
                          yellow, and so on - meant every card was equally loud and
                          a genuinely dry section looked no different from a fine
                          one. Colour has to be reserved for "look at this". */}
                      <View style={styles.envGrid}>
                        {[
                          [`${s.latest?.temperature?.toFixed?.(1) ?? '--'}°`, 'Temp',     null],
                          [`${s.latest?.humidity?.toFixed?.(0) ?? '--'}%`,    'Humidity',
                            rh.label === 'GOOD' ? null : rh.color],
                          [`${s.latest?.light?.toFixed?.(0) ?? '--'}`,        'Light',    null],
                          [`${s.latest?.vpd ?? '--'}`,                        'Drying',
                            vp.label === 'normal' ? null : vp.color],
                        ].map(([val, lbl, col], i) => (
                          <View key={i} style={styles.envCell}>
                            {/* Grey rather than faded: 0.4 opacity made old
                                numbers hard to read while still colour-coded,
                                so they kept signalling good or bad. */}
                            <Text style={[styles.envVal,
                                          { color: !good ? COLORS.textTertiary
                                                 : col || COLORS.text }]}
                              numberOfLines={1}>{val}</Text>
                            <Text style={styles.envLbl} numberOfLines={1}
                              adjustsFontSizeToFit maxFontSizeMultiplier={1.15}>{lbl}</Text>
                          </View>
                        ))}
                      </View>

                      {(plan.waterTime || tray.status || s.fertilizer?.due) && (
                        <View style={styles.planRow}>
                          {plan.waterTime && (
                            <Text style={[styles.chip, { backgroundColor: COLORS.infoDim, color: COLORS.info }]}>
                              Water {plan.waterTime} · {plan.durationSec}s
                            </Text>
                          )}
                          {tray.status === 'fill' && (
                            <Text style={[styles.chip, { backgroundColor: COLORS.warningDim, color: COLORS.warning }]}>
                              Tray needs {tray.fillSeconds}s
                            </Text>
                          )}
                          {tray.status === 'cooldown' && (
                            <Text style={[styles.chip, { backgroundColor: COLORS.infoDim, color: COLORS.info }]}>
                              Tray filled {tray.hoursSinceFill}h ago
                            </Text>
                          )}
                          {s.fertilizer?.due && (
                            <Text style={[styles.chip, { backgroundColor: COLORS.fertilizerDim, color: COLORS.fertilizer }]}>
                              Food {s.fertilizer.npkType} at {Math.round((s.fertilizer.strength ?? 0.5) * 100)}%
                            </Text>
                          )}
                        </View>
                      )}
                    </TouchableOpacity>
                  );
                })}

                {/* A house that is still calibrating cannot take a new section.
                    Not a rule invented for tidiness: the placement analysis only
                    uses moments EVERY section contributed to, so a section added
                    on day two has no readings for days one and two and drags the
                    shared set down to whatever it can cover. The house would
                    then sit at "not ready" until the new section caught up,
                    with nothing on screen explaining why. Better to say so than
                    to let the farmer restart a three-day wait by accident. */}
                {h.meta?.lifecycle === 'calibrating' ? (
                  <View style={[styles.addSec, styles.addSecOff]}>
                    <Ionicons name="lock-closed-outline" size={14} color={COLORS.textTertiary} />
                    <Text style={styles.addSecOffText}>
                      Sections are fixed while this house calibrates
                    </Text>
                  </View>
                ) : (
                  <TouchableOpacity style={styles.addSec}
                    onPress={() => navigation.navigate('FarmSetup', { addToHouse: h.houseId })}>
                    <Ionicons name="add" size={16} color={COLORS.primary} />
                    <Text style={styles.addSecText}>Add section to {h.meta?.name || h.houseId}</Text>
                  </TouchableOpacity>
                )}
                </>)}
              </View>
              );
            })}

            <TouchableOpacity style={[styles.addHouse, SHADOW.sm]}
              onPress={() => setAdding(true)} activeOpacity={0.8}
              accessibilityRole="button" accessibilityLabel="Add another house">
              <Ionicons name="add-circle-outline" size={19} color={COLORS.primary} />
              <Text style={styles.addHouseText}>Add another house</Text>
            </TouchableOpacity>

            {/* Two genuinely different ways to add a house, and the difference is
                not cosmetic: one ends with sensors already placed and a calibration
                window running, the other with an empty house the farmer fills in by
                hand. Sending everyone down one path would either force a three-day
                wait on somebody who already knows their layout, or hide the whole
                placement feature from somebody who does not. */}
            <SelectSheet
              visible={adding}
              title="How do you want to set this house up?"
              subtitle="Both create a real house. They differ in who decides where the sensors go."
              options={[
                { key: 'plan',
                  label: 'Work out the best sensor positions',
                  sub: 'Sections are spread evenly, you run them for three days, then '
                     + 'the app says which positions matter and which sensors you can '
                     + 'take out. Needs a sensor in every section to start.' },
                { key: 'manual',
                  label: 'I know my layout — set it up myself',
                  sub: 'Name the sections yourself and place nodes by hand. No '
                     + 'calibration window, and no placement suggestion.' },
              ]}
              confirmOnSelect
              onCancel={() => setAdding(false)}
              onConfirm={(k) => {
                setAdding(false);
                navigation.navigate(k === 'plan' ? 'HousePlanner' : 'FarmSetup');
              }} />

            {/* the farm name was previously fixed at setup, a typo was permanent */}
            <TouchableOpacity style={styles.renameFarm} activeOpacity={0.7}
              onPress={() => setRenaming({ kind: 'farm', name: data?.farm?.farmName || '' })}
              accessibilityRole="button"
              accessibilityLabel={`Rename the farm. Currently called ${data?.farm?.farmName || 'unnamed'}.`}>
              <Ionicons name="create-outline" size={16} color={COLORS.textSecondary} />
              <Text style={styles.renameFarmText}>Rename farm</Text>
            </TouchableOpacity>
          </>
        )}
        <View style={{ height: 100 }} />
      </ScrollView>

      {/* Which board drives this house's valves. */}
      <SelectSheet
        visible={!!master}
        title="Master controller"
        subtitle={master
          ? `${master.name} · one pump, one relay board, a valve per section`
          : undefined}
        options={master?.devices ? masterOptions() : []}
        value={master?.current}
        emptyText={master?.devices
          ? 'No board is available. A master must be a node already in this house, '
            + 'or a spare that belongs to no house — taking one from another house '
            + 'would leave that house a sensor short.'
          : 'Looking for boards…'}
        confirmOnSelect
        onCancel={() => setMaster(null)}
        onConfirm={saveMaster}
      />

      {/* Step 1 — which house. Skipped automatically when there is only one. */}
      <SelectSheet
        visible={flow?.step === 'house'}
        title={flow?.kind === 'water' ? 'Water which house?' : 'Fill trays in which house?'}
        options={(data?.houses || []).map((h) => ({
          key: h.houseId,
          label: h.meta?.name || h.houseId,
          sub: `${(h.sections || []).length} section${(h.sections || []).length === 1 ? '' : 's'}`,
        }))}
        value={flow?.houseId}
        onCancel={() => setFlow(null)}
        onConfirm={(houseId) => setFlow({ ...flow, houseId, step: 'sections', sectionIds: [] })}
      />

      {/* Step 2 — which sections inside it.

          Only sections whose node is reporting are listed. A command is a
          document the node polls; one with no node, or one that has gone quiet,
          simply never reads it, so offering it produces a run that sits at
          "waiting for the node" and then reports a failure the farmer could do
          nothing about. They used to be shown greyed with a label, which still
          let them be selected. If every section in the house is offline the
          sheet says so rather than showing an empty list. */}
      <SelectSheet
        visible={flow?.step === 'sections'}
        multi
        title={flow?.kind === 'water' ? 'Water which sections?' : 'Fill which trays?'}
        subtitle={flowHouse
          ? (flowHouse.meta?.name || flowHouse.houseId)
            + (coolingHidden > 0
                ? ` · ${coolingHidden} tray${coolingHidden === 1 ? '' : 's'} still resting`
                : '')
          : undefined}
        options={flowPickable
          .map((x) => {
            const rh = humidityStatus(x.latest?.humidity);
            return {
              key: x.sectionId,
              label: x.meta?.name || x.sectionId,
              sub: `${x.latest?.temperature?.toFixed?.(1) ?? '--'}°  `
                 + `${x.latest?.humidity?.toFixed?.(0) ?? '--'}%  ${rh.label}`,
            };
          })}
        emptyText={
          coolingHidden > 0 && flowPickable.length === 0
            ? 'Every tray here was filled recently and is still resting, so none can '
              + 'take more water yet. A tray cannot dry out faster than its cooldown, '
              + 'so refilling now would overflow it rather than raise humidity.'
            : flowSections.length
            ? `None of the ${flowSections.length} section`
              + `${flowSections.length === 1 ? '' : 's'} here is reporting right now, so `
              + 'there is nothing that can be watered. Check the nodes are powered '
              + 'and on Wi-Fi.'
            : 'This house has no sections yet.'
        }
        values={flow?.sectionIds || []}
        confirmLabel="Next"
        onCancel={() => setFlow(null)}
        onConfirm={(sectionIds) => setFlow({ ...flow, sectionIds, step: 'confirm' })}
      />

      {/* Step 3 — say exactly what is about to happen, and to what. */}
      <ConfirmSheet
        visible={flow?.step === 'confirm'}
        icon={flow?.kind === 'water' ? 'rainy-outline' : 'add-circle-outline'}
        title={flow?.kind === 'water'
          ? `Water ${chosen.length} section${chosen.length === 1 ? '' : 's'}?`
          : `Fill ${chosen.length} tray${chosen.length === 1 ? '' : 's'}?`}
        body={`${chosen.map((x) => x.meta?.name || x.sectionId).join(', ')}.\n\n`
            + (flow?.kind === 'water'
                ? 'Each pump runs for its own planned duration, one section at a time.'
                : 'Each tray gets a short burst of water, one section at a time. It raises '
                  + 'humidity around the plants and does not touch the roots.')}
        caution={flow?.kind === 'water'
          ? 'Vanda roots rot if they are watered too often. Only do this if the plants clearly need it.'
          : null}
        confirmLabel={flow?.kind === 'water' ? 'Water now' : 'Fill now'}
        onCancel={() => setFlow(null)}
        onConfirm={launch}
      />

      <RenameDialog
        visible={!!renaming}
        title={renaming?.kind === 'farm' ? 'Rename farm' : 'Rename house'}
        label={renaming?.kind === 'farm' ? 'Farm name' : 'House name'}
        value={renaming?.name || ''}
        placeholder={renaming?.kind === 'farm' ? 'e.g. Vanda Orchid Farm' : 'e.g. House 1'}
        onCancel={() => setRenaming(null)}
        onSave={async (name) => {
          if (renaming.kind === 'farm') await renameFarm(name);
          else                          await renameHouse(renaming.id, name);
          setRenaming(null);
          await load();
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  // ScreenHeader sits above the ScrollView again, so no extra top padding
  scroll:    { padding: SPACE.xl },

  errCard:  { flexDirection: 'row', gap: SPACE.md, backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm, padding: SPACE.lg },
  errText:  { color: COLORS.danger, fontSize: FONT.sm, flex: 1, lineHeight: 19 },

  emptyCard:  { alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.xl, marginTop: SPACE.xl },
  emptyTitle: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800', textAlign: 'center' },
  emptyText:  { color: COLORS.textSecondary, fontSize: FONT.sm, textAlign: 'center', lineHeight: 20 },
  setupBtn:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.xl, paddingVertical: SPACE.md, marginTop: SPACE.sm },
  setupBtnText:{ color: '#FFF', fontSize: FONT.md, fontWeight: '700' },

  /* ── the status band ─────────────────────────────────────────────────
     One block where there used to be three. The left rail carries the tone so
     the sentence itself can stay near-black and readable; a fully tinted card
     would make the headline compete with its own background. */
  band:      { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
               borderLeftWidth: 4, padding: SPACE.lg, marginBottom: SPACE.lg },
  bandTop:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  bandIcon:  { width: 42, height: 42, borderRadius: RADIUS.md,
               alignItems: 'center', justifyContent: 'center' },
  bandTitle: { fontSize: FONT.lg, fontWeight: '800' },
  bandSub:   { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2 },
  bandNote:  { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18,
               marginTop: SPACE.md, paddingTop: SPACE.md,
               borderTopWidth: 1, borderTopColor: COLORS.border },

  /* ── generic section card used by Needs-you-now and Automation ─────── */
  card:      { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
               padding: SPACE.lg, marginBottom: SPACE.lg },
  cardTitle: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '800',
               letterSpacing: 0.6, textTransform: 'uppercase',
               marginBottom: SPACE.md },

  needRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
               paddingVertical: SPACE.md, borderTopWidth: 1,
               borderTopColor: COLORS.borderLight },
  needIcon:  { width: 32, height: 32, borderRadius: RADIUS.sm,
               alignItems: 'center', justifyContent: 'center' },
  needName:  { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  needWhere: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '500' },
  needText:  { fontSize: FONT.sm, fontWeight: '600', marginTop: 1 },
  needFix:   { color: COLORS.textTertiary, fontSize: FONT.xs, maxWidth: 92,
               textAlign: 'right' },

  modeInCard:{ marginBottom: SPACE.md },
  nextRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
               marginTop: SPACE.md, paddingTop: SPACE.md,
               borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  nextText:  { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm },
  nextStrong:{ color: COLORS.text, fontWeight: '800' },
  nextNone:  { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18,
               marginTop: SPACE.md, paddingTop: SPACE.md,
               borderTopWidth: 1, borderTopColor: COLORS.borderLight },

  actRow:  { flexDirection: 'row', gap: SPACE.md, marginBottom: SPACE.lg },
  actBtn:  { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, borderRadius: RADIUS.md, paddingVertical: SPACE.lg },
  actText: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },

  /* House = one big card. Sections are sub-cards nested inside it, so the
     hierarchy (house -> section) is visible instead of implied by spacing. */
  houseCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
               padding: SPACE.lg, marginBottom: SPACE.lg },
  houseHead:     { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.md },
  // the title block is the collapse control, so it owns the row's tap area
  houseTitleBtn: { flex: 1, flexDirection: 'row', alignItems: 'center',
                   gap: SPACE.md, paddingVertical: SPACE.xs },
  houseIcon: { width: 38, height: 38, borderRadius: RADIUS.md, backgroundColor: COLORS.primaryDim, alignItems: 'center', justifyContent: 'center' },

  houseMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 6,
                  marginTop: 3, flexWrap: 'wrap' },
  calBadge:  { flexDirection: 'row', alignItems: 'center', gap: 3,
               backgroundColor: COLORS.warningDim, borderRadius: RADIUS.full,
               paddingHorizontal: 6, paddingVertical: 2 },
  calBadgeTxt: { color: COLORS.warning, fontSize: 9, fontWeight: '800',
                 letterSpacing: 0.2 },
  mapBtn:    { width: 34, height: 34, borderRadius: RADIUS.sm,
               backgroundColor: COLORS.primaryDim,
               alignItems: 'center', justifyContent: 'center',
               marginRight: SPACE.sm },
  houseName: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800' },
  houseMeta: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  collapsedNote: { color: COLORS.textSecondary, fontSize: FONT.sm,
                   paddingVertical: SPACE.md, paddingHorizontal: SPACE.xs },

  /* The section card is now a WHITE card with a coloured rail, not a tinted
     block. Eight tinted blocks in a row read as eight warnings; the tint was
     also doing the same job as the rail, the dot and the badge, which is three
     more places than one signal needs. */
  secCard:  { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
              borderLeftWidth: 3, padding: SPACE.lg, marginBottom: SPACE.md },
  secHead:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  secSubHead:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
               marginTop: 4, marginBottom: SPACE.lg, flexWrap: 'wrap' },
  secDot:   { width: 8, height: 8, borderRadius: 4 },
  secName:  { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800', flexShrink: 1 },
  secLabel: { color: COLORS.textTertiary, fontSize: FONT.sm, flexShrink: 1 },
  badge:    { marginLeft: 'auto', paddingHorizontal: 9, paddingVertical: 4, borderRadius: RADIUS.full },
  badgeText:{ fontSize: 11, fontWeight: '700', letterSpacing: 0.2 },

  envGrid: { flexDirection: 'row', marginBottom: SPACE.lg },
  envCell: { flex: 1, minWidth: 0, alignItems: 'flex-start', paddingRight: 4 },
  envVal:  { fontSize: FONT.lg, fontWeight: '800', fontVariant: ['tabular-nums'] },
  envLbl:  { color: COLORS.textTertiary, fontSize: 11, marginTop: 2, flexShrink: 1 },

  planRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm,
             paddingTop: SPACE.md, borderTopWidth: 1, borderTopColor: COLORS.border },
  chip:    { fontSize: 12, fontWeight: '700', overflow: 'hidden',
             borderRadius: RADIUS.full, paddingHorizontal: 10, paddingVertical: 5 },

  // sits inside the house card, so it reads as "add to THIS house"
  addSec:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                gap: 4, paddingVertical: SPACE.md, marginTop: SPACE.xs,
                borderRadius: RADIUS.md, borderWidth: 1, borderStyle: 'dashed',
                borderColor: COLORS.border },
  addSecText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  addSecOff:     { borderStyle: 'solid', backgroundColor: COLORS.bgCardAlt,
                   borderColor: COLORS.borderLight, gap: 6 },
  addSecOffText: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },

  addHouse:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg, borderWidth: 1, borderColor: COLORS.primaryDim },
  addHouseText: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },

  renameFarm:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                    gap: 6, paddingVertical: SPACE.lg, marginTop: SPACE.xs },
  renameFarmText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
});
