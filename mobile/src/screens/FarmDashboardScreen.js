import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useLiveData, { LIVE_MS } from '../hooks/useLiveData';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import ModeToggle from '../components/ModeToggle';
import FarmSummary from '../components/FarmSummary';
import AutoControls from '../components/AutoControls';
import { FarmSkeleton } from '../components/Skeleton';
import { FreshnessBadge, FarmStaleBanner, STATE_STYLE } from '../components/Freshness';
import RenameDialog from '../components/RenameDialog';
import SelectSheet from '../components/SelectSheet';
import ConfirmSheet from '../components/ConfirmSheet';
import Toast from '../components/Toast';
import {
  getOverview, deleteHouse,
  renameFarm, renameHouse, getAlarms, humidityStatus, vpdStatus,
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

export default function FarmDashboardScreen({ navigation }) {
  const [busy, setBusy] = useState(null);
  // { kind: 'farm' } or { kind: 'house', id, name } — null when nothing is open
  const [renaming, setRenaming] = useState(null);
  // houseId -> true when the farmer has folded that house away
  const [collapsed, setCollapsed] = useState({});
  const toggleHouse = (id) => setCollapsed(c => ({ ...c, [id]: !c[id] }));
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
  const [toast, setToast] = useState(null);

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
  const flat     = houses.flatMap(h => (h.sections || []).map(s => ({ ...s, houseId: h.houseId })));
  const sections = flat.length;
  const offline  = flat.filter(s => !s.online).length;
  const filling  = flat.filter(s => s.tray?.status === 'fill').length;
  const fertDue  = flat.filter(s => s.fertilizer?.due).length;
  const alertCount = filling + fertDue + flat.filter(s => s.freshness && !s.freshness.trusted).length;

  return (
    <View style={styles.container}>
      {/* the SAME header every other tab uses, never forked for this screen */}
      <ScreenHeader
        title={data?.farm?.farmName || 'My Farm'}
        subtitle={`${houses.length} house${houses.length !== 1 ? 's' : ''} · ${sections} section${sections !== 1 ? 's' : ''}`}
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
        <ModeToggle />
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

            <FarmSummary
              total={sections}
              reporting={sections - offline}
              filling={filling}
              attention={offline + fertDue}
            />

            {/* actions */}
            <View style={styles.actRow}>
              {/* These two look like siblings but are not: "Work out plan"
                  only calculates, while "Check & fill trays" can open a valve.
                  The labels have to carry that difference. */}
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

            {/* houses */}
            <AutoControls autoMode={auto?.autoMode} pendingAction={auto?.pendingAction || 0}
              onChanged={refreshAuto} />

            {houses.map(h => (
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
                    accessibilityState={{ expanded: !collapsed[h.houseId] }}
                    accessibilityLabel={
                      `${h.meta?.name || h.houseId}, ${h.sections?.length || 0} sections. `
                      + `${collapsed[h.houseId] ? 'Collapsed. Tap to expand.' : 'Expanded. Tap to collapse.'}`
                    }>
                    <View style={styles.houseIcon}>
                      <Ionicons name={TYPE_ICON[h.meta?.type] || 'home-outline'} size={19} color={COLORS.primary} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <View style={styles.houseNameRow}>
                        <Text style={styles.houseName} numberOfLines={1}>
                          {h.meta?.name || h.houseId}
                        </Text>
                        {/* A house still collecting its calibration data behaves
                            differently from an active one - it is not watering
                            to a plan yet - so the list has to say which it is.
                            Absent means active, which is every house that
                            predates the calibration flow. */}
                        {h.meta?.lifecycle === 'calibrating' && (
                          <View style={styles.calBadge}>
                            <Ionicons name="hourglass-outline" size={9} color={COLORS.warning} />
                            <Text style={styles.calBadgeTxt}>Calibrating</Text>
                          </View>
                        )}
                      </View>
                      <Text style={styles.houseMeta}>
                        {h.meta?.type || 'house'} · {h.sections?.length || 0} sections
                        {h.meta?.plantCount ? ` · ${h.meta.plantCount} plants` : ''}
                      </Text>
                    </View>
                    <Ionicons
                      name={collapsed[h.houseId] ? 'chevron-down' : 'chevron-up'}
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

                {collapsed[h.houseId] ? (
                  <Text style={styles.collapsedNote}>
                    {(() => {
                      const secs = h.sections || [];
                      const need = secs.filter(z => z.tray?.status === 'fill').length;
                      const bad  = secs.filter(z => z.freshness && !z.freshness.trusted).length;
                      const bits = [];
                      if (bad)  bits.push(`${bad} not reporting`);
                      if (need) bits.push(`${need} need water`);
                      return bits.length ? bits.join(', ') : 'All sections are fine';
                    })()}
                  </Text>
                ) : (<>
                {(h.sections || []).map(s => {
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
                  const tone = good ? rh.color : fst.color;
                  /* The whole card is tinted, not just the left rail - a 4px
                     line is easy to miss when scanning seven sections.

                     The tint tracks CONNECTION, never the humidity band: keying
                     it off `tone` would wash a perfectly healthy section red
                     just because it was reading dry, which is the same mistake
                     that made a section with no node draw itself green. */
                  const wash = fx?.state === 'nonode' ? COLORS.bgCardAlt
                             : good ? COLORS.successDim : COLORS.dangerDim;
                  return (
                    <TouchableOpacity key={s.sectionId}
                      style={[styles.secCard,
                              { borderLeftColor: tone, backgroundColor: wash }]}
                      onPress={() => navigation.navigate('SectionDetail',
                        { houseId: h.houseId, sectionId: s.sectionId, houseName: h.meta?.name })}
                      activeOpacity={0.7}>
                      <View style={styles.secHead}>
                        <View style={[styles.secDot, { backgroundColor: tone }]} />
                        <Text style={styles.secName} numberOfLines={1}>{s.meta?.name || s.sectionId}</Text>
                        <View style={[styles.badge, { backgroundColor: `${tone}1F` }]}>
                          <Text style={[styles.badgeText, { color: tone }]}>
                            {good ? titleCase(rh.label) : fst.word}
                          </Text>
                        </View>
                      </View>

                      <View style={styles.secSubHead}>
                        {s.meta?.label ? <Text style={styles.secLabel} numberOfLines={1}>{s.meta.label}</Text> : null}
                        <FreshnessBadge freshness={s.freshness} />
                      </View>

                      {/* Readings as labelled columns. As one long line they ran
                          together ("Light 13022VPD 2.007") and were unreadable. */}
                      <View style={styles.envGrid}>
                        {[
                          [`${s.latest?.temperature?.toFixed?.(1) ?? '--'}°`, 'Temp',     COLORS.temperature],
                          [`${s.latest?.humidity?.toFixed?.(0) ?? '--'}%`,    'Humidity', rh.color],
                          [`${s.latest?.light?.toFixed?.(0) ?? '--'}`,        'Light',    COLORS.light],
                          [`${s.latest?.vpd ?? '--'}`,                        'Drying',   vp.color],
                        ].map(([val, lbl, col], i) => (
                          <View key={i} style={styles.envCell}>
                            {/* Grey rather than faded: 0.4 opacity made old
                                numbers hard to read while still colour-coded,
                                so they kept signalling good or bad. */}
                            <Text style={[styles.envVal, { color: good ? col : COLORS.textTertiary }]}
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

                <TouchableOpacity style={styles.addSec}
                  onPress={() => navigation.navigate('FarmSetup', { addToHouse: h.houseId })}>
                  <Ionicons name="add" size={16} color={COLORS.primary} />
                  <Text style={styles.addSecText}>Add section to {h.meta?.name || h.houseId}</Text>
                </TouchableOpacity>
                </>)}
              </View>
            ))}

            <TouchableOpacity style={[styles.addHouse, SHADOW.sm]}
              onPress={() => navigation.navigate('FarmSetup')} activeOpacity={0.8}
              accessibilityRole="button" accessibilityLabel="Add another house">
              <Ionicons name="add-circle-outline" size={19} color={COLORS.primary} />
              <Text style={styles.addHouseText}>Add another house</Text>
            </TouchableOpacity>

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

      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

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

  actRow:  { flexDirection: 'row', gap: SPACE.md, marginBottom: SPACE.xl },
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
  houseNameRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
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

  /* The card was cramped because four rows of content sat inside 12px padding
     with 8px between cards. Roomier padding, a clear gap between the identity
     row, the readings and the plan, and readings laid out as labelled columns
     instead of one run-on line that produced "Light 13022VPD 2.007". */
  secCard:  { borderRadius: RADIUS.md,
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

  addHouse:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg, borderWidth: 1, borderColor: COLORS.primaryDim },
  addHouseText: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },

  renameFarm:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                    gap: 6, paddingVertical: SPACE.lg, marginTop: SPACE.xs },
  renameFarmText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
});
