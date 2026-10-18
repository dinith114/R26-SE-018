/**
 * Put another sensor into a house — decide WHERE, then which board.
 *
 * One screen for what were going to be two. "Add a sensor from the house map"
 * and "add a section from the dashboard" are the same question asked from two
 * places: a house planned by the planner already has all its sections, so
 * nothing is being created. What is missing is hardware in one of them, and the
 * only real decision is which zone stops being estimated.
 *
 * THE SUGGESTION IS A SUGGESTION.
 * The placement analysis is re-run against what the sections actually recorded
 * and asked where an (n+1)th sensor would go. That zone is highlighted and
 * named — and any other zone without a node is still selectable. The farmer
 * knows things the variogram does not: where the power point is, which corner
 * floods, which bench they can actually reach. An app that only allowed the
 * computed answer would be wrong more often than it was right, and would feel
 * wrong every time.
 *
 * The analysis is also allowed to FAIL without taking the screen with it. It
 * needs overlapping history from every placed section and returns 409 when it
 * has none; that is a missing suggestion, not a missing feature, so the map
 * still works and simply offers no recommendation.
 */
import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, TouchableOpacity,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import NodePicker from '../components/NodePicker';
import Toast from '../components/Toast';
import { getHouse, analyzePlacement, assignDevice, addSection } from '../services/careV2';
import { useCan } from '../config/auth';
import { usePrefs } from '../config/prefs';
import { formatLength } from '../services/lengthUnits';
import { furthestPoint } from '../services/placementHint';

export default function AddSensorScreen({ route, navigation }) {
  const houseId = route.params?.houseId;

  const [house,   setHouse]   = useState(null);
  const [suggest, setSuggest] = useState(null);   // { sectionId, from } or null
  const [why,     setWhy]     = useState(null);   // why there is no suggestion
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(null);   // sectionId awaiting a board
  // { sectionId, short } while a link is in flight - see CalibrationScreen
  const [linking, setLinking] = useState(null);
  const [toast,   setToast]   = useState(null);
  // A NEW spot (18 Oct 2026): { x, y } metres, chosen by tapping the plan.
  const [spot,     setSpot]     = useState(null);
  const [creating, setCreating] = useState(false);
  const can = useCan();
  const { lengthUnit } = usePrefs();

  const load = useCallback(async () => {
    try {
      const r = await getHouse(houseId);
      const h = r?.house || null;
      setHouse(h);

      const secs = h?.sections || {};
      const wired = new Set(
        Object.keys(secs).filter((id) => (secs[id]?.node || {}).mac));

      /* Ask for the placement one sensor larger than what is installed. The
         answer names every position that layout would use; the one worth
         showing is whichever of them has no board yet. */
      try {
        const res = await analyzePlacement(houseId, Math.min(10, Object.keys(secs).length - 1));
        const want = wired.size + 1;
        const pos = res?.positions?.[String(want)] || res?.positions?.[want] || [];
        const pick = pos.map((p) => p.sectionId).find((id) => !wired.has(id));
        if (pick) setSuggest({ sectionId: pick, from: want });
        else setWhy(`The analysis does not place a ${want}th sensor differently — `
                  + 'any zone below is a reasonable choice.');
      } catch (e) {
        setWhy(e.message);
      }
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setLoading(false);
    }
  }, [houseId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const linkNode = async (dev) => {
    const sectionId = picking;
    const short = dev.shortId || dev.mac.slice(-4);
    setPicking(null);
    setLinking({ sectionId, short });
    try {
      await assignDevice(dev.mac, houseId, sectionId);
      setToast({ text: `Node ${short} is now in ${sectionId}`, kind: 'success' });
      await load();
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setLinking(null); }
  };

  const meta = house?.meta || {};
  const sections = house?.sections || {};

  /* Green where a board already sits, blue for the suggestion, grey for a zone
     that could take one. Anything without coordinates cannot be drawn at all
     and is listed underneath instead of being silently dropped. */
  const nodes = Object.entries(sections)
    .filter(([, s]) => s?.meta?.x != null && s?.meta?.y != null)
    .map(([id, s]) => {
      const wired = !!(s.node || {}).mac;
      return {
        id,
        short: String(id).replace(/^S/, ''),
        x: Number(s.meta.x),
        y: Number(s.meta.y),
        kind: wired ? 'real' : (suggest?.sectionId === id ? 'planned' : 'nonode'),
      };
    });

  const openIds = Object.keys(sections)
    .filter((id) => !(sections[id]?.node || {}).mac)
    .sort();

  /* A NEW SPOT, not one of the zones above (18 Oct 2026). "Add a sensor" used to
     mean only "put a board into a zone that has none", so in a house where every
     zone already had one there was nothing to offer. Here the farmer taps the
     plan (or takes the suggestion), the section is created at that spot, and the
     board picker opens for it straight away. */
  const sized = Number(meta.width) > 0 && Number(meta.length) > 0;
  const hint = sized ? furthestPoint(meta.width, meta.length,
    Object.values(sections).filter((s) => (s?.node || {}).mac && s?.meta?.x != null && s?.meta?.y != null)
      .map((s) => ({ x: Number(s.meta.x), y: Number(s.meta.y) }))) : null;
  const target = spot || hint;
  const nextName = () => {
    let n = 1;
    while (sections[`S${n}`]) n += 1;
    return `Section ${n}`;
  };
  const createAtSpot = async () => {
    if (!target) return;
    setCreating(true);
    try {
      const r = await addSection(houseId, { name: nextName(), x: target.x, y: target.y });
      setSpot(null);
      await load();
      setToast({ text: `${r.sectionId} added at ${formatLength(target.x, lengthUnit)}, `
                     + `${formatLength(target.y, lengthUnit)}. Now pick its board.`, kind: 'success' });
      setPicking(r.sectionId);
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setCreating(false); }
  };
  const spotNodes = [
    ...Object.entries(sections)
      .filter(([, s]) => s?.meta?.x != null && s?.meta?.y != null)
      .map(([id, s]) => ({ id, short: String(id).replace(/^S/, ''), x: Number(s.meta.x), y: Number(s.meta.y),
                           kind: (s.node || {}).mac ? 'real' : 'nonode' })),
    ...(hint && !spot ? [{ id: 'suggested', short: '+', x: hint.x, y: hint.y, kind: 'planned' }] : []),
    ...(spot ? [{ id: 'chosen', short: '+', x: spot.x, y: spot.y, kind: 'here' }] : []),
  ];

  if (picking) {
    return (
      <View style={styles.container}>
        <ScreenHeader title={`Sensor for ${picking}`}
          subtitle="Boards that are powered on and unclaimed"
          navigation={navigation} showBack />
        <NodePicker onSelect={linkNode} onSkip={() => setPicking(null)} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScreenHeader title="Add a sensor" subtitle={meta.name || houseId}
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={COLORS.primary} />
          <Text style={styles.loadTxt}>Working out where it would help most…</Text>
        </View>
      ) : !house ? (
        <View style={styles.center}>
          <Text style={styles.loadTxt}>Could not load this house.</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.scroll}>
          {suggest ? (
            <View style={[styles.card, styles.tipCard, SHADOW.sm]}>
              <View style={styles.tipHead}>
                <Ionicons name="bulb-outline" size={17} color={COLORS.info} />
                <Text style={styles.tipTitle}>
                  {sections[suggest.sectionId]?.meta?.name || suggest.sectionId} would
                  {' '}help most
                </Text>
              </View>
              <Text style={styles.tipTxt}>
                Measured from what these sections actually recorded: with
                {' '}{suggest.from} sensors, that is where the analysis puts one.
                {'\n\n'}
                It is only a suggestion — pick any zone below. You know things the
                maths does not, like where there is power and which bench you can
                reach.
              </Text>
            </View>
          ) : (
            <View style={[styles.card, SHADOW.sm]}>
              <Text style={styles.tipTxt}>
                <Text style={{ fontWeight: '800' }}>No recommendation. </Text>
                {why || 'The placement analysis could not run.'}
                {'\n\n'}Choose whichever zone you want a sensor in.
              </Text>
            </View>
          )}

          <Text style={styles.h}>Tap a zone with no sensor</Text>
          <View style={[styles.card, SHADOW.sm]}>
            {nodes.length ? (
              <DigitalTwin
                width={meta.width} length={meta.length} nodes={nodes}
                plantRows={0} showPipes={false}
                onPressNode={(n) => {
                  if ((sections[n.id]?.node || {}).mac) {
                    setToast({ text: `${n.id} already has a sensor.`, kind: 'info' });
                    return;
                  }
                  setPicking(n.id);
                }} />
            ) : (
              <Text style={styles.tipTxt}>
                No section has a position yet, so there is no map to show. Set them
                in each section's Setup tab.
              </Text>
            )}
          </View>

          {/* The map needs coordinates; this list does not, so a house that was
              never given positions can still have sensors added. */}
          <Text style={styles.h}>Zones without a sensor</Text>
          <View style={[styles.card, SHADOW.sm]}>
            {openIds.length ? openIds.map((id) => (
              linking && linking.sectionId === id ? (
                <View key={id} style={styles.row}>
                  <ActivityIndicator size="small" color={COLORS.info} />
                  <Text style={styles.rowName}>
                    {sections[id]?.meta?.name || id}
                    <Text style={styles.rowTag}>   adding {linking.short}…</Text>
                  </Text>
                </View>
              ) : (
              <TouchableOpacity key={id} style={styles.row} activeOpacity={0.7}
                disabled={!!linking}
                accessibilityRole="button"
                accessibilityLabel={`Put a sensor in ${sections[id]?.meta?.name || id}`}
                onPress={() => setPicking(id)}>
                <Ionicons
                  name={suggest?.sectionId === id ? 'bulb' : 'add-circle-outline'}
                  size={17}
                  color={suggest?.sectionId === id ? COLORS.info : COLORS.textTertiary} />
                <Text style={styles.rowName}>
                  {sections[id]?.meta?.name || id}
                  {suggest?.sectionId === id && (
                    <Text style={styles.rowTag}>   suggested</Text>
                  )}
                </Text>
                <Ionicons name="chevron-forward" size={15} color={COLORS.textTertiary} />
              </TouchableOpacity>
              )
            )) : (
              <Text style={styles.tipTxt}>
                Every section in this house already has its own sensor.
              </Text>
            )}
          </View>

          {can('addSection') ? (
            <>
              <Text style={styles.h}>Or a new spot</Text>
              <View style={[styles.card, SHADOW.sm]}>
                {sized ? (
                  <>
                    <Text style={styles.tipTxt}>
                      Tap the plan where the new sensor will go.
                      {hint && hint.distance != null
                        ? ` The blue ring is the spot furthest from every working sensor `
                          + `(${formatLength(hint.distance, lengthUnit)} from the nearest), where `
                          + 'the estimates for this house know the least. Only a suggestion.'
                        : ''}
                    </Text>
                    <View style={{ marginTop: SPACE.md }}>
                      <DigitalTwin width={meta.width} length={meta.length} nodes={spotNodes}
                        plantRows={0} showPipes={false} onPressMap={setSpot} />
                    </View>
                    <TouchableOpacity
                      style={[styles.spotBtn, (!target || creating) && { opacity: 0.5 }]}
                      disabled={!target || creating || !!linking} activeOpacity={0.85}
                      accessibilityRole="button"
                      accessibilityLabel="Add a section at this spot and pick its board"
                      onPress={createAtSpot}>
                      {creating
                        ? <ActivityIndicator size="small" color="#FFF" />
                        : <Ionicons name="add-circle" size={18} color="#FFF" />}
                      <Text style={styles.spotBtnTxt}>
                        {target
                          ? `${spot ? 'Add a section here' : 'Use the suggested spot'} `
                            + `(${formatLength(target.x, lengthUnit)}, ${formatLength(target.y, lengthUnit)})`
                          : 'Tap the plan first'}
                      </Text>
                    </TouchableOpacity>
                  </>
                ) : (
                  <Text style={styles.tipTxt}>
                    Set this house's size first (My Farm, the house's menu, House size),
                    so a spot can be picked on the plan.
                  </Text>
                )}
              </View>
            </>
          ) : null}
          <View style={{ height: 60 }} />
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center:    { flex: 1, alignItems: 'center', justifyContent: 'center', gap: SPACE.md,
               padding: SPACE.xl },
  loadTxt:   { color: COLORS.textSecondary, fontSize: FONT.sm, textAlign: 'center' },
  scroll:    { padding: SPACE.xl },

  h:      { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '800',
            letterSpacing: 0.6, textTransform: 'uppercase',
            marginBottom: SPACE.md, marginTop: SPACE.lg },
  card:   { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg, padding: SPACE.lg },
  tipCard:{ backgroundColor: COLORS.infoDim },
  tipHead:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
            marginBottom: SPACE.sm },
  tipTitle:{ flex: 1, color: COLORS.info, fontSize: FONT.md, fontWeight: '800' },
  tipTxt: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  row:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
             paddingVertical: SPACE.md, borderTopWidth: 1,
             borderTopColor: COLORS.borderLight },
  rowName: { flex: 1, color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  rowTag:  { color: COLORS.info, fontSize: FONT.xs, fontWeight: '800' },

  // Stretched to the card's width, not sized to its text: the phone's Bold
  // text setting clips self-sized labels (orchid-project-gotchas).
  spotBtn:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                gap: SPACE.sm, alignSelf: 'stretch', marginTop: SPACE.md,
                backgroundColor: COLORS.primary, borderRadius: RADIUS.md,
                paddingVertical: SPACE.md, paddingHorizontal: SPACE.md },
  spotBtnTxt: { flexShrink: 1, color: '#FFF', fontSize: FONT.sm, fontWeight: '800',
                textAlign: 'center' },
});
