/**
 * Why the alarm rang.
 *
 * A notification that only says "Water the plants now" leaves the farmer to
 * open the app, find the section, and work out whether it is still true. This
 * screen answers the question the alarm raised — which zone, what the sensors
 * say, how overdue it is — and puts the two things worth doing on it.
 *
 * ACKNOWLEDGE IS NOT COSMETIC. An unacknowledged action alarm is re-pushed
 * every few minutes; this button is what stops it. So it has to be here, and it
 * has to be obvious, or the farmer's only way to silence a repeating alarm is
 * to do the watering.
 *
 * Reached by tapping the alarm, and shown automatically if an alarm arrives
 * while the app is already open.
 */
import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import * as Notifications from 'expo-notifications';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useCan } from '../config/auth';
import ScreenHeader from '../components/ScreenHeader';
import { LIVE_MS } from '../hooks/useLiveData';
import ConfirmSheet from '../components/ConfirmSheet';
import Toast from '../components/Toast';
import {
  getAlarms, ackAlarm, getHouse, waterSection, fillTray,
  humidityStatus, vpdStatus,
} from '../services/careV2';

const ACTION = {
  water: {
    icon: 'rainy', tint: COLORS.primary,
    heading: 'Water the plants now',
    button: 'Water now',
  },
  'fill-tray': {
    icon: 'water', tint: COLORS.info,
    heading: 'Fill the humidity tray now',
    button: 'Fill tray',
  },
  /* A hardware fault (backend app/services/device_health.py). There is
     NOTHING to send to the node: the fix is a person checking a wire or a
     battery. So no action button at all - only "open the section" and
     Acknowledge. Before this entry existed, an unknown action fell back to
     `water`, and the act button's else-branch FILLED THE TRAY: a sensor-fault
     alarm would have offered "Water now" and opened the tray valve. */
  'check-device': {
    icon: 'hardware-chip-outline', tint: COLORS.warning,
    heading: 'A sensor node needs checking',
    button: null,
  },
};

/* When the alarm was raised, on the phone's clock. createdAt is stored as
   "YYYY-MM-DD HH:MM:SS UTC"; the header used to print the UTC hour, so a 21:06
   alarm read "15:36 UTC" above a message that said "since 20:55". */
function raisedAt(createdAt) {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(createdAt || '');
  if (!m) return undefined;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return d.toDateString() === new Date().toDateString()
    ? `Raised at ${hm}` : `Raised ${d.getDate()}/${d.getMonth() + 1} at ${hm}`;
}

function todayYMD() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const titleCase = (t) => (t ? t.charAt(0) + t.slice(1).toLowerCase() : t);

/* Only these two actions ever move water. Anything else - check-device, or an
   action a newer server sends that this build does not know - must never reach
   waterSection or fillTray. */
const MOVES_WATER = new Set(['water', 'fill-tray']);

export default function AlarmScreen({ route, navigation }) {
  /* What this account may do. The server refuses the rest whatever
     happens here; this only stops the screen offering a control that
     would come back 403. */
  const can = useCan();
  const focusIds = route?.params?.alarmIds || null;

  const [alarms, setAlarms]   = useState([]);
  const [section, setSection] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy]       = useState(null);
  /* { kind: 'ack' | 'act', alarm } - the alarm the sheet was OPENED for.
     It used to be a bare 'ack'/'act' and the sheet read whatever alarm was
     first in the list when Confirm was tapped. The list reloads every 30 s, so
     a newer alarm could slide under an open "Water now in Section 1?" sheet and
     Confirm acted on that one instead - or, for a check-device alarm, quietly
     did nothing while the farmer believed Section 1 was watered. Found in review. */
  const [sheet, setSheet]     = useState(null);
  const [toast, setToast]     = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await getAlarms(50);
      const all = r.alarms || r.items || [];
      // Only ACTION alarms need a person. Info alarms are history, and putting
      // them here would bury the one thing that actually needs doing.
      let live = all.filter((a) => a.kind === 'action' && !a.acknowledged);
      if (focusIds?.length) {
        const wanted = live.filter((a) => focusIds.includes(a.id));
        if (wanted.length) live = wanted;
      }
      setAlarms(live);

      const first = live[0];
      if (first?.houseId) {
        try {
          const h = await getHouse(first.houseId);
          setSection(h?.house?.sections?.[first.sectionId] || null);
        } catch (_) { setSection(null); }
      }
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setLoading(false); }
  }, [focusIds]);

  useFocusEffect(useCallback(() => {
    load();
    const t = setInterval(load, LIVE_MS);
    return () => clearInterval(t);
  }, [load]));

  const primary = alarms[0] || null;
  // An action this build does not know is shown as a check, never as watering.
  const cfg = ACTION[primary?.action] || ACTION['check-device'];
  const actable = MOVES_WATER.has(primary?.action);
  // The sheet only stays open while the alarm it was opened for is still listed.
  const sheetAlive = !!(sheet && sheet.alarm && alarms.some((a) => a.id === sheet.alarm.id));
  const sheetCfg = ACTION[sheet?.alarm?.action] || ACTION['check-device'];

  /* The farmer is in the app and has dealt with it, so the alarm's own
     notification is stale. The full-screen one stays pinned as a heads-up
     banner while the app is open: on 9 Oct a "Still waiting - fill the tray"
     banner sat over every screen for 14 minutes after the tray was filled.
     Anything still waiting is pushed again by the next repeat. */
  const clearShade = () => {
    Notifications.dismissAllNotificationsAsync().catch(() => {});
  };

  const doAck = async (a) => {
    setSheet(null);
    setBusy('ack');
    try {
      await ackAlarm(a.id);
      clearShade();
      setToast({ text: 'Acknowledged. It will stop reminding you.', kind: 'success' });
      await load();
      // Nothing left needing a person: this screen has no reason to exist.
      const r = await getAlarms(50);
      const left = (r.alarms || r.items || [])
        .filter((x) => x.kind === 'action' && !x.acknowledged);
      if (!left.length) navigation.goBack();
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setBusy(null); }
  };

  const doAct = async (a) => {
    setSheet(null);
    if (!MOVES_WATER.has(a.action)) return;          // see ACTION['check-device']
    setBusy('act');
    try {
      if (a.action === 'water') {
        await waterSection(a.houseId, a.sectionId,
          section?.plan?.durationSec || 45, !!section?.fertilizer?.due);
      } else if (a.action === 'fill-tray') {
        await fillTray(a.houseId, a.sectionId, section?.tray?.fillSeconds || 15);
      }
      // Doing the thing is the strongest possible acknowledgement.
      await ackAlarm(a.id);
      clearShade();
      setToast({ text: 'Sent to the node. It runs within about a minute.', kind: 'success' });
      await load();
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setBusy(null); }
  };

  if (loading) {
    return (
      <View style={[s.screen, s.centre]}>
        <ActivityIndicator color={COLORS.primary} size="large" />
      </View>
    );
  }

  if (!primary) {
    return (
      <View style={s.screen}>
        <ScreenHeader title="Nothing needs you" navigation={navigation} showBack />
        <View style={[s.centre, { flex: 1, padding: SPACE.xl }]}>
          <Ionicons name="checkmark-circle" size={56} color={COLORS.success} />
          <Text style={s.clearTitle}>All clear</Text>
          <Text style={s.clearBody}>
            No alarm is waiting for you. Anything the system did by itself is in
            your notifications.
          </Text>
        </View>
      </View>
    );
  }

  const latest = section?.latest || {};
  const rh = humidityStatus(latest.humidity);
  const vp = vpdStatus(latest.vpd);
  const others = alarms.slice(1);

  return (
    <View style={s.screen}>
      <ScreenHeader title="Alarm" subtitle={raisedAt(primary.createdAt)}
        navigation={navigation} showBack />
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        <View style={[s.hero, { borderColor: cfg.tint }, SHADOW.md]}>
          <View style={[s.heroIcon, { backgroundColor: `${cfg.tint}18` }]}>
            <Ionicons name={cfg.icon} size={34} color={cfg.tint} />
          </View>
          <Text style={s.heroTitle}>{cfg.heading}</Text>
          <Text style={s.heroWhere}>
            {section?.meta?.name || primary.sectionId}
            {primary.houseId ? ` · ${primary.houseId}` : ''}
          </Text>
          <Text style={s.heroWhy}>{primary.message}</Text>
        </View>

        {/* The readings that justify the alarm, so it can be judged rather than
            simply obeyed. */}
        <Text style={s.h}>Right now</Text>
        <View style={[s.grid, SHADOW.sm]}>
          {[
            ['thermometer-outline', COLORS.temperature,
             latest.temperature?.toFixed?.(1) ?? '--', '°C', 'Temperature', null],
            ['water-outline', rh.color,
             latest.humidity?.toFixed?.(0) ?? '--', '%', 'Humidity', titleCase(rh.label)],
            ['speedometer-outline', vp.color,
             latest.vpd ?? '--', 'kPa', 'Drying', vp.label],
          ].map(([ic, c, v, u, l, st], i) => (
            <View key={i} style={s.cell}>
              <Ionicons name={ic} size={16} color={c} />
              <Text style={[s.cellVal, { color: c }]}>{v}<Text style={s.cellUnit}>{u}</Text></Text>
              {/* Name and status on their own lines, across the whole cell. As
                  one centred line ("Humidity · HUMID") Android measured it short
                  at a large font size and cut it to "Humidity ·" (9 Oct). */}
              <Text style={s.cellLbl}>{l}</Text>
              {st ? <Text style={s.cellLbl}>{st}</Text> : null}
            </View>
          ))}
        </View>

        {section?.plan?.waterTime && section.plan.date === todayYMD() && (
          <Text style={s.note}>
            Today's plan: water at {section.plan.waterTime} for {section.plan.durationSec} seconds.
          </Text>
        )}

        {others.length > 0 && (
          <>
            <Text style={s.h}>Also waiting</Text>
            {others.map((a) => (
              <View key={a.id} style={s.otherRow}>
                <Ionicons name={(ACTION[a.action] || ACTION['check-device']).icon}
                  size={16} color={COLORS.textTertiary} />
                <Text style={s.otherTxt}>
                  {a.title}{a.sectionId ? ` · ${a.houseId ? `${a.houseId} ` : ''}${a.sectionId}` : ''}
                </Text>
              </View>
            ))}
          </>
        )}

        <View style={{ height: SPACE.xxl }} />
      </ScrollView>

      <View style={s.footer}>
        <TouchableOpacity
          style={[s.btn, s.ackBtn]}
          disabled={!can('ackAlarm')}
          onPress={can('ackAlarm') ? () => setSheet({ kind: 'ack', alarm: primary }) : undefined}
          disabled={!!busy}
          activeOpacity={0.85}
          accessibilityRole="button"
          accessibilityLabel="Acknowledge. Stops the alarm repeating, without watering.">
          {busy === 'ack' ? <ActivityIndicator color={COLORS.textSecondary} size="small" />
                          : <Text style={s.ackTxt}>Acknowledge</Text>}
        </TouchableOpacity>

        {actable ? (
          <TouchableOpacity
            style={[s.btn, { backgroundColor: cfg.tint }]}
            disabled={!can('waterSection')}
            onPress={can('waterSection') ? () => setSheet({ kind: 'act', alarm: primary }) : undefined}
            disabled={!!busy}
            activeOpacity={0.85}
            accessibilityRole="button"
            accessibilityLabel={`${cfg.button} in ${section?.meta?.name || primary.sectionId}`}>
            {busy === 'act' ? <ActivityIndicator color="#FFF" size="small" />
                            : <Text style={s.actTxt}>{cfg.button}</Text>}
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={[s.btn, { backgroundColor: cfg.tint }]}
            disabled={!primary.houseId || !primary.sectionId}
            onPress={() => navigation.navigate('SectionDetail', {
              houseId: primary.houseId, sectionId: primary.sectionId })}
            activeOpacity={0.85}
            accessibilityRole="button"
            accessibilityLabel={`Open ${section?.meta?.name || primary.sectionId}`}>
            <Text style={s.actTxt}>Open the section</Text>
          </TouchableOpacity>
        )}
      </View>

      <ConfirmSheet
        visible={sheetAlive && sheet.kind === 'ack'}
        icon="notifications-off-outline"
        title="Stop reminding me?"
        body={'The alarm stops repeating. The plants are NOT watered — do that '
            + 'yourself, or use the other button.'}
        confirmLabel="Acknowledge"
        onCancel={() => setSheet(null)}
        onConfirm={() => doAck(sheet.alarm)}
      />

      <ConfirmSheet
        visible={sheetAlive && sheet.kind === 'act' && MOVES_WATER.has(sheet.alarm.action)}
        icon={sheetCfg.icon}
        title={`${sheetCfg.button} in ${sheet?.alarm?.sectionId || ''}?`}
        body={sheet?.alarm?.action === 'water'
          ? `The pump runs for ${section?.plan?.durationSec || 45} seconds.`
          : `The valve opens for ${section?.tray?.fillSeconds || 15} seconds.`}
        confirmLabel={sheetCfg.button || 'Confirm'}
        onCancel={() => setSheet(null)}
        onConfirm={() => doAct(sheet.alarm)}
      />
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  centre: { alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: SPACE.xl },

  hero: {
    alignItems: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
    borderWidth: 2, padding: SPACE.xl,
  },
  heroIcon: {
    width: 68, height: 68, borderRadius: 34,
    alignItems: 'center', justifyContent: 'center', marginBottom: SPACE.xs,
  },
  heroTitle: {
    color: COLORS.text, fontSize: 23, fontWeight: '800',
    letterSpacing: -0.4, textAlign: 'center',
  },
  heroWhere: { color: COLORS.textSecondary, fontSize: FONT.md, fontWeight: '600' },
  heroWhy: {
    color: COLORS.textSecondary, fontSize: FONT.lg - 1, lineHeight: 22,
    textAlign: 'center', marginTop: SPACE.sm,
  },

  h: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700',
       marginTop: SPACE.xl, marginBottom: SPACE.md },
  grid: {
    flexDirection: 'row', backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm, paddingVertical: SPACE.lg,
  },
  cell: { flex: 1, alignItems: 'center', gap: 3 },
  cellVal: { fontSize: 20, fontWeight: '800', fontVariant: ['tabular-nums'] },
  cellUnit: { fontSize: FONT.xs, fontWeight: '600' },
  cellLbl: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center', alignSelf: 'stretch' },

  note: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: SPACE.md },

  otherRow: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    paddingVertical: SPACE.sm,
  },
  // flex: 1, or a long line runs off the right edge instead of wrapping.
  otherTxt: { color: COLORS.textSecondary, fontSize: FONT.md, flex: 1 },

  clearTitle: { color: COLORS.text, fontSize: 22, fontWeight: '700', marginTop: SPACE.lg },
  clearBody: {
    color: COLORS.textSecondary, fontSize: FONT.lg - 1, lineHeight: 22,
    textAlign: 'center', marginTop: SPACE.sm, maxWidth: 300,
  },

  footer: {
    flexDirection: 'row', gap: SPACE.sm,
    padding: SPACE.xl, paddingTop: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.border,
    backgroundColor: COLORS.bgCard,
  },
  btn: {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    paddingVertical: SPACE.md + 3, borderRadius: RADIUS.md, minHeight: 52,
  },
  ackBtn: { backgroundColor: COLORS.bgCardAlt },
  ackTxt: { color: COLORS.textSecondary, fontSize: FONT.lg - 1, fontWeight: '700' },
  actTxt: { color: '#FFF', fontSize: FONT.lg - 1, fontWeight: '700' },
});
