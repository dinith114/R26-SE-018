/**
 * Simple mode — the default view, built for elderly, non-technical growers.
 *
 * Design rules this screen obeys (each one fixes a real defect found in review):
 *
 *  1. A BUTTON'S POSITION NEVER CHANGES ITS MEANING. The old screen had one big
 *     button that filled trays when something was dry and re-checked when it was
 *     not — same place, same colour, different consequence. Now "Fill trays" is
 *     always "Fill trays" (disabled, with a reason, when nothing is dry) and
 *     "Check now" is always "Check now".
 *
 *  2. NO NUMBER WITHOUT ITS AGE. Nodes run on battery with no mains supply, so
 *     they die silently. Every reading carries a freshness badge, and untrusted
 *     sections are called out before the farmer reads their values.
 *
 *  3. IRRIGATION IS ALWAYS SCOPED. Anything that moves water names exactly which
 *     sections it will affect, and how many.
 *
 *  4. ACTIONS LEAVE A VISIBLE TRACE. A dismissed pop-up is not feedback; a
 *     running job shows a banner until the next poll confirms it.
 */
import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useLiveData, { LIVE_MS } from '../hooks/useLiveData';
import ScreenHeader from '../components/ScreenHeader';
import ModeToggle from '../components/ModeToggle';
import AutoControls from '../components/AutoControls';
import { FarmSkeleton } from '../components/Skeleton';
import { FreshnessBadge, FarmStaleBanner } from '../components/Freshness';
import { confirmScoped, listNames } from '../utils/confirm';
import { COLORS, SPACE, RADIUS, SHADOW } from '../config/theme';
import {
  getOverview, planAll, trayCheckAll, waterSection, fillTray,
  fertilizeSection, getAlarms, RH_LOW,
} from '../services/careV2';

const F = { huge: 34, big: 22, mid: 18, body: 16, small: 14 };

/** Plain words instead of numbers — the whole point of Simple mode. */
function dryness(sec) {
  const rh = sec.latest?.humidity;
  const tray = sec.tray || {};

  if (sec.freshness && !sec.freshness.trusted) {
    return { word: 'No signal', color: COLORS.danger, icon: 'battery-dead-outline',
             note: sec.freshness.label };
  }
  if (tray.status === 'cooldown') {
    return { word: 'Watered', color: COLORS.info, icon: 'checkmark-done-circle',
             note: `Tray filled ${tray.hoursSinceFill ?? 0}h ago` };
  }
  if (rh == null)  return { word: 'No data',  color: COLORS.textTertiary, icon: 'help-circle' };
  if (rh < 45)     return { word: 'Very dry', color: COLORS.danger,  icon: 'alert-circle' };
  if (rh < RH_LOW) return { word: 'Dry',      color: COLORS.warning, icon: 'water-outline' };
  if (rh > 85)     return { word: 'Very wet', color: COLORS.info,    icon: 'rainy-outline' };
  return             { word: 'Normal',    color: COLORS.success, icon: 'checkmark-circle' };
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

/** "71 seconds" is engineer-speak. Farmers think in minutes. */
function plainDuration(sec) {
  if (!sec) return '';
  if (sec < 60) return 'less than a minute';
  const m = Math.round(sec / 60);
  return m === 1 ? 'about 1 minute' : `about ${m} minutes`;
}

export default function TodayScreen({ navigation }) {
  const [busy, setBusy]         = useState(false);
  const [activity, setActivity] = useState(null);  // persistent "job running" banner

  const { data, loading, error, refreshing: refresh, refresh: pullRefresh, reload } =
    useLiveData(getOverview, LIVE_MS);
  // the farm's Auto switch + how many things are waiting on the farmer
  const { data: auto, reload: refreshAuto } = useLiveData(() => getAlarms(1), LIVE_MS);

  /** Runs a job, keeps a visible trace of it, then refreshes. */
  const run = useCallback(async (label, fn) => {
    setBusy(true);
    setActivity({ label, at: Date.now() });
    try {
      await fn();
      await reload();
      // leave the banner up briefly so the farmer sees that something happened
      setTimeout(() => setActivity(null), 6000);
    } catch (e) {
      setActivity(null);
      Alert.alert('Could not do that', e.message);
    } finally {
      setBusy(false);
    }
  }, [reload]);

  const sections = (data?.houses || []).flatMap(h =>
    (h.sections || []).map(s => ({ ...s, houseId: h.houseId, houseName: h.meta?.name })));

  const dry      = sections.filter(s => s.tray?.status === 'fill');
  const atLimit  = sections.filter(s => s.tray?.trayAtLimit);
  const plan     = sections.find(s => s.plan?.waterTime)?.plan;
  const fertDue  = sections.filter(s => s.fertilizer?.due);
  const anyFert  = sections.some(s => s.fertilizer && 'due' in s.fertilizer);
  const untrusted= sections.filter(s => s.freshness && !s.freshness.trusted);
  const allOk    = sections.length > 0 && dry.length === 0 && untrusted.length === 0;

  /* ── Action 1: fill trays. ALWAYS fills trays, never anything else. ── */
  const doFillTrays = () => confirmScoped({
    verb: 'Fill the trays in',
    targets: dry,
    detail: 'Each tray gets a short burst of water. The water evaporates to raise '
          + 'the humidity around the plants, it does not touch the roots.',
    onConfirm: () => run(
      `Filling ${dry.length} tray${dry.length !== 1 ? 's' : ''}`,
      () => Promise.all(dry.map(s => fillTray(s.houseId, s.sectionId, s.tray?.fillSeconds || 15))),
    ),
  });

  /* ── Action 2: re-check. ALWAYS re-checks, never moves water. ── */
  const doCheck = () => run('Checking every section', async () => {
    await Promise.all([planAll(), trayCheckAll()]);
  });

  /* ── Emergency override: waters the roots. Scoped and cautioned. ── */
  const doWaterNow = () => confirmScoped({
    verb: 'Water',
    targets: sections,
    detail: `The pump will run for ${plainDuration(plan?.durationSec || 45)} in each section, `
          + 'straight away, instead of waiting for the planned time.',
    caution: 'Vanda roots rot if they are watered too often. Only do this if the '
           + 'plants clearly need it and the planned watering is a long way off.',
    onConfirm: () => run(
      `Watering ${sections.length} section${sections.length !== 1 ? 's' : ''}`,
      () => Promise.all(sections.map(s =>
        waterSection(s.houseId, s.sectionId, s.plan?.durationSec || 45, false))),
    ),
  });

  /* ── Feed now: plant food goes in WITH the water, never onto dry roots. ── */
  const doFertilize = () => confirmScoped({
    verb: 'Feed',
    targets: fertDue.length ? fertDue : sections,
    detail: `Plant food (${fertDue[0]?.fertilizer?.npkType || 'the right mix'}) will be `
          + 'mixed into a watering that starts straight away. It is never put on dry roots.',
    caution: fertDue.length ? null
      : 'None of these sections are due for feeding yet. Feeding too often burns '
      + 'the roots, so only do this if you are sure.',
    onConfirm: () => run(
      'Feeding the plants',
      () => Promise.all((fertDue.length ? fertDue : sections).map(x =>
        fertilizeSection(x.houseId, x.sectionId, x.plan?.durationSec || 45))),
    ),
  });

  const alertCount = dry.length + fertDue.length + untrusted.length;

  return (
    <View style={s.container}>
    {/* the SAME header every other tab uses, never forked for this screen */}
    <ScreenHeader
      title={data?.farm?.farmName || 'My Farm'}
      subtitle={greeting()}
      navigation={navigation}
      alertCount={alertCount}
      showSettings
    />
    <ScrollView
      contentContainerStyle={s.scroll}
      refreshControl={
        <RefreshControl refreshing={refresh} tintColor={COLORS.primary} onRefresh={pullRefresh} />
      }>

      <ModeToggle />

      {/* a job is running, stays put until the next poll confirms it */}
      {activity && (
        <View style={[s.activity, SHADOW.sm]} accessibilityRole="alert"
          accessibilityLabel={`${activity.label} now`}>
          <ActivityIndicator color={COLORS.primary} />
          <Text style={s.activityText}>{activity.label} now…</Text>
        </View>
      )}

      {loading ? (
        <FarmSkeleton />
      ) : error ? (
        <View style={[s.card, { backgroundColor: COLORS.dangerDim }]} accessibilityRole="alert">
          <Ionicons name="cloud-offline" size={40} color={COLORS.danger} />
          <Text style={[s.statusBig, { color: COLORS.danger }]}>Cannot connect</Text>
          <Text style={s.statusSub}>Check that the system is switched on.</Text>
        </View>
      ) : sections.length === 0 ? (
        <TouchableOpacity style={[s.card, SHADOW.sm]} activeOpacity={0.8}
          accessibilityRole="button" accessibilityLabel="Set up your farm"
          onPress={() => navigation.navigate('FarmSetup')}>
          <Ionicons name="add-circle" size={44} color={COLORS.primary} />
          <Text style={s.statusBig}>Set up your farm</Text>
          <Text style={s.statusSub}>Tap here to add your greenhouse.</Text>
        </TouchableOpacity>
      ) : (
        <>
          {/* devices that stopped reporting come FIRST, everything below them is suspect */}
          <FarmStaleBanner sections={sections} />

          {/* headline status */}
          <View
            style={[s.card, SHADOW.md, {
              backgroundColor: allOk ? COLORS.successDim : COLORS.warningDim,
            }]}
            accessibilityRole="header"
            accessibilityLabel={
              allOk
                ? `All ${sections.length} sections healthy`
                : `${dry.length} sections need water`
            }>
            <Ionicons name={allOk ? 'checkmark-circle' : 'water'} size={58}
              color={allOk ? COLORS.success : COLORS.warning} />
            <Text style={[s.statusBig, { color: allOk ? COLORS.success : COLORS.warning }]}>
              {allOk
                ? `All ${sections.length} section${sections.length !== 1 ? 's' : ''} healthy`
                : `${dry.length} section${dry.length !== 1 ? 's' : ''} need water`}
            </Text>
            <Text style={s.statusSub}>
              {allOk ? 'Your plants are fine right now.'
                     : `${listNames(dry.map(x => x.meta?.name || x.sectionId))}, tap “Fill trays”.`}
            </Text>
          </View>

          {/* TWO buttons, fixed meanings, fixed positions */}
          <View style={s.btnRow}>
            <TouchableOpacity
              style={[s.actBtn, SHADOW.sm,
                      { backgroundColor: dry.length ? COLORS.primary : COLORS.bgCardAlt },
                      busy && { opacity: 0.6 }]}
              onPress={dry.length ? doFillTrays : undefined}
              disabled={busy || dry.length === 0}
              activeOpacity={0.85}
              accessibilityRole="button"
              accessibilityState={{ disabled: busy || dry.length === 0 }}
              accessibilityLabel={
                dry.length
                  ? `Fill trays in ${dry.length} sections`
                  : 'Fill trays. Disabled, because no tray needs water.'
              }>
              <Ionicons name="water" size={24}
                color={dry.length ? '#FFF' : COLORS.textTertiary} />
              <Text style={[s.actText, { color: dry.length ? '#FFF' : COLORS.textTertiary }]}>
                Fill trays
              </Text>
              <Text style={[s.actSub, { color: dry.length ? 'rgba(255,255,255,0.85)' : COLORS.textTertiary }]}>
                {dry.length ? `${dry.length} need${dry.length === 1 ? 's' : ''} water` : 'None needed'}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[s.actBtn, SHADOW.sm, { backgroundColor: COLORS.bgCard },
                      busy && { opacity: 0.6 }]}
              onPress={doCheck} disabled={busy} activeOpacity={0.85}
              accessibilityRole="button"
              accessibilityState={{ disabled: busy }}
              accessibilityLabel="Check now. Re-reads every sensor, updates today's plan, and fills any tray that is low.">
              <Ionicons name="refresh" size={24} color={COLORS.primary} />
              <Text style={[s.actText, { color: COLORS.primary }]}>Check now</Text>
              {/* This button calls trayCheckAll, which ISSUES tray commands when
                  the section is in auto mode. It previously said "No water
                  moved", which was simply untrue. */}
              <Text style={[s.actSub, { color: COLORS.textTertiary }]}>Fills low trays</Text>
            </TouchableOpacity>
          </View>

          {/* today's watering time */}
          {plan?.waterTime && (
            <View style={[s.timeCard, SHADOW.sm]} accessible
              accessibilityLabel={`Watering today at ${plan.waterTime}, for ${plainDuration(plan.durationSec)}`}>
              <Ionicons name="alarm-outline" size={30} color={COLORS.primary} />
              <View style={{ flex: 1 }}>
                <Text style={s.timeLabel}>Watering today at</Text>
                <Text style={s.timeBig}>{plan.waterTime}</Text>
                <Text style={s.timeSub}>{plainDuration(plan.durationSec)}</Text>
              </View>
            </View>
          )}
          {plan?.secondSession && (
            <View style={[s.hotCard, SHADOW.sm]} accessibilityRole="alert">
              <Ionicons name="flame" size={24} color={COLORS.danger} />
              <Text style={s.hotText}>
                Very hot today, the plants will get water again at {plan.secondTime}.
              </Text>
            </View>
          )}

          {/* plant food */}
          {fertDue.length > 0 ? (
            <View style={[s.fertCard, SHADOW.sm]} accessible
              accessibilityLabel={`Plant food is due for ${fertDue.length} sections`}>
              <View style={s.fertHead}>
                <Ionicons name="leaf" size={28} color={COLORS.fertilizer} />
                <View style={{ flex: 1 }}>
                  <Text style={s.fertTitle}>Plant food is due</Text>
                  <Text style={s.fertSub}>
                    {fertDue.length === 1 ? '1 section needs' : `${fertDue.length} sections need`} feeding:
                    {' '}{fertDue[0].fertilizer?.npkType} at
                    {' '}{Math.round((fertDue[0].fertilizer?.strength ?? 0.5) * 100)}% strength.
                  </Text>
                  <Text style={s.fertNote}>
                    It goes in with the water automatically, never on dry roots.
                  </Text>
                </View>
              </View>
              <TouchableOpacity style={s.fertBtn} onPress={doFertilize} disabled={busy}
                activeOpacity={0.85} accessibilityRole="button"
                accessibilityLabel={`Feed the plants now in ${fertDue.length} sections`}>
                <Ionicons name="leaf" size={18} color="#FFF" />
                <Text style={s.fertBtnText}>Feed the plants now</Text>
              </TouchableOpacity>
            </View>
          ) : anyFert ? (
            <View style={[s.fertOkCard, SHADOW.sm]}>
              <Ionicons name="flask-outline" size={24} color={COLORS.success} />
              <Text style={s.fertOkText}>Plant food not needed today.</Text>
            </View>
          ) : null}

          {atLimit.length > 0 && (
            <View style={[s.infoCard, SHADOW.sm]}>
              <Ionicons name="information-circle" size={24} color={COLORS.info} />
              <Text style={s.infoText}>
                {atLimit.length === 1 ? 'One section' : `${atLimit.length} sections`} already got
                water recently. The air is just very dry today, no need to add more.
              </Text>
            </View>
          )}

          {/* sections, grouped by house */}
          {(data?.houses || []).map(house => (
            <View key={house.houseId} style={[s.houseCard, SHADOW.sm]}>
              <Text style={s.houseName}>{house.meta?.name || house.houseId}</Text>

              {(house.sections || []).map(sec => {
                const full = { ...sec, houseId: house.houseId, houseName: house.meta?.name };
                const d = dryness(full);
                const t = sec.latest || {};
                return (
                  <TouchableOpacity key={sec.sectionId}
                    style={[s.row, { borderLeftColor: d.color }]} activeOpacity={0.7}
                    accessibilityRole="button"
                    accessibilityLabel={
                      `${sec.meta?.name || sec.sectionId}. ${d.word}. ` +
                      (sec.freshness?.trusted
                        ? `${t.temperature ?? '--'} degrees, ${t.humidity ?? '--'} percent humidity, ${sec.freshness?.label ?? ''}.`
                        : `Readings are ${sec.freshness?.label ?? 'old'} and not trustworthy.`)
                    }
                    onPress={() => navigation.navigate('SectionDetail', {
                      houseId: house.houseId, sectionId: sec.sectionId,
                      houseName: house.meta?.name,
                    })}>
                    <Ionicons name={d.icon} size={28} color={d.color} />
                    <View style={{ flex: 1 }}>
                      <View style={s.rowTop}>
                        <Text style={s.rowName}>{sec.meta?.name || sec.sectionId}</Text>
                        <FreshnessBadge freshness={sec.freshness} />
                      </View>
                      <Text style={[s.rowSub, !sec.freshness?.trusted && s.rowSubStale]}>
                        {sec.freshness?.trusted
                          ? `${t.temperature ?? '--'}°C · ${t.humidity ?? '--'}%${d.note ? ' · ' + d.note : ''}`
                          : 'Readings are old, do not trust these numbers'}
                      </Text>
                    </View>
                    <Text style={[s.rowWord, { color: d.color }]}>{d.word}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
          ))}

          {/* master switches, the farmer expects these here, not per section */}
          <AutoControls autoMode={auto?.autoMode} pendingAction={auto?.pendingAction || 0}
              onChanged={refreshAuto} />

          {/* emergency override, deliberately quiet */}
          <TouchableOpacity style={s.linkBtn} onPress={doWaterNow} disabled={busy}
            accessibilityRole="button"
            accessibilityLabel={`Water all ${sections.length} sections right now. Asks for confirmation first.`}>
            <Ionicons name="rainy-outline" size={20} color={COLORS.textSecondary} />
            <Text style={s.linkText}>
              Water all {sections.length} section{sections.length !== 1 ? 's' : ''} right now
            </Text>
          </TouchableOpacity>
        </>
      )}
      <View style={{ height: 110 }} />
    </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center:    { alignItems: 'center', justifyContent: 'center', gap: SPACE.md },
  // ScreenHeader sits above the ScrollView, so no extra top padding
  scroll:    { padding: SPACE.xl },
  loadingText: { fontSize: F.body, color: COLORS.textSecondary },

  activity:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
                  backgroundColor: COLORS.primaryLight, borderRadius: RADIUS.md,
                  padding: SPACE.lg, marginBottom: SPACE.md },
  activityText: { fontSize: F.body, fontWeight: '700', color: COLORS.primaryDark, flex: 1 },

  card:      { alignItems: 'center', gap: SPACE.sm, borderRadius: RADIUS.md,
               padding: SPACE.xl, marginBottom: SPACE.lg },
  statusBig: { fontSize: F.huge, fontWeight: '900', textAlign: 'center', color: COLORS.text },
  statusSub: { fontSize: F.body, color: COLORS.textSecondary, textAlign: 'center' },

  btnRow: { flexDirection: 'row', gap: SPACE.md, marginBottom: SPACE.xl },
  actBtn: { flex: 1, alignItems: 'center', gap: 2, borderRadius: RADIUS.md,
            paddingVertical: SPACE.xl },
  actText:{ fontSize: F.mid, fontWeight: '800' },
  actSub: { fontSize: 12, fontWeight: '600' },

  timeCard:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.lg,
               backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
               padding: SPACE.lg, marginBottom: SPACE.md },
  timeLabel: { fontSize: F.small, color: COLORS.textTertiary },
  timeBig:   { fontSize: F.huge, fontWeight: '900', color: COLORS.primary,
               fontVariant: ['tabular-nums'] },
  timeSub:   { fontSize: F.body, color: COLORS.textSecondary },

  hotCard: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
             backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.md,
             padding: SPACE.lg, marginBottom: SPACE.md },
  hotText: { flex: 1, fontSize: F.body, color: COLORS.danger, fontWeight: '600', lineHeight: 22 },

  fertCard:  { backgroundColor: `${COLORS.fertilizer}14`, borderRadius: RADIUS.md,
               padding: SPACE.lg, marginBottom: SPACE.md },
  fertHead:  { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.md },
  fertBtn:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: SPACE.sm, backgroundColor: COLORS.fertilizer, borderRadius: RADIUS.md,
               paddingVertical: SPACE.md + 2, marginTop: SPACE.md },
  fertBtnText: { color: '#FFF', fontSize: F.body, fontWeight: '800' },
  fertTitle: { fontSize: F.mid, fontWeight: '800', color: COLORS.fertilizer },
  fertSub:   { fontSize: F.body, color: COLORS.text, marginTop: 2, lineHeight: 21 },
  fertNote:  { fontSize: F.small, color: COLORS.textSecondary, marginTop: 4, lineHeight: 18 },
  fertOkCard:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
               backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
               padding: SPACE.lg, marginBottom: SPACE.md },
  fertOkText:{ fontSize: F.body, color: COLORS.textSecondary, flex: 1 },

  infoCard: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              backgroundColor: COLORS.infoDim, borderRadius: RADIUS.md,
              padding: SPACE.lg, marginBottom: SPACE.md },
  infoText: { flex: 1, fontSize: F.body, color: COLORS.textSecondary, lineHeight: 22 },

  // same nesting as Expert: house = big card, sections = sub-cards inside it
  houseCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
               padding: SPACE.lg, marginBottom: SPACE.md },
  houseName: { fontSize: F.mid, fontWeight: '800', color: COLORS.text, marginBottom: SPACE.md },

  row:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
             backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
             borderLeftWidth: 4, padding: SPACE.md, marginBottom: SPACE.sm },
  rowTop:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, flexWrap: 'wrap' },
  rowName: { fontSize: F.body, fontWeight: '700', color: COLORS.text },
  rowSub:  { fontSize: F.small, color: COLORS.textTertiary, marginTop: 3 },
  rowSubStale: { color: COLORS.danger, fontWeight: '600' },
  rowWord: { fontSize: F.small, fontWeight: '800' },

  linkBtn:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
              gap: SPACE.sm, paddingVertical: SPACE.lg, marginTop: SPACE.md },
  linkText: { fontSize: F.body, color: COLORS.textSecondary, fontWeight: '600' },
});
