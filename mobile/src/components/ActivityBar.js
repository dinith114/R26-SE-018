/**
 * The live status strip: what is pouring, waiting or just finished.
 *
 * Shown on the Dashboard, My Farm and each section, so a pour started anywhere -
 * by the farmer on any screen, as a whole-house run, or by Automatic care with
 * nobody watching - stays visible until it is done, and for three minutes after.
 * Compact on purpose: one line and a sub-line per pour, a thin bar while water
 * moves, and Stop for those allowed to stop it. Renders nothing when idle.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useIsFocused } from '@react-navigation/native';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import { useCan } from '../config/auth';
import useActivity, { refreshActivity } from '../hooks/useActivity';
import { describe, forPlace } from '../services/activityText';
import { stopSection } from '../services/careV2';

const TONE = {
  info:    { c: COLORS.info,    bg: COLORS.infoDim },
  success: { c: COLORS.success, bg: COLORS.successDim },
  warning: { c: COLORS.warning, bg: COLORS.warningDim },
  danger:  { c: COLORS.danger,  bg: COLORS.dangerDim },
};

export default function ActivityBar({ houseId, sectionId, navigation, max = 3, style }) {
  const can = useCan();
  const focused = useIsFocused();
  const snap = useActivity();
  const [, setTick] = useState(0);
  const [stopping, setStopping] = useState(null);
  const items = forPlace(snap.items, houseId, sectionId);
  const running = items.some((i) => i.state === 'running');

  // Coming back to a screen asks at once, rather than waiting out the idle poll.
  useEffect(() => { if (focused) refreshActivity(); }, [focused]);
  // Between polls, the countdown moves every second from the server's figure.
  useEffect(() => {
    if (!running || !focused) return undefined;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [running, focused]);

  if (!items.length) return null;
  const elapsed = snap.at ? (Date.now() - snap.at) / 1000 : 0;

  const stop = async (it) => {
    setStopping(it.id);
    try {
      await stopSection(it.houseId, it.lead);
    } catch (_) {
      // Shown by the next poll: still running, or stopped.
    } finally {
      setStopping(null);
      refreshActivity();
    }
  };

  return (
    <View style={[styles.wrap, style]}>
      {items.slice(0, max).map((it) => {
        const d = describe(it, { elapsed, sectionId, nowSec: snap.serverNowSec });
        const t = TONE[d.tone] || TONE.info;
        // Tapping opens the section - except on that section's own screen. Not a
        // disabled button there: a disabled touchable around Stop could swallow it.
        const openable = !!navigation && !sectionId;
        const Row = openable ? TouchableOpacity : View;
        const rowProps = openable
          ? { activeOpacity: 0.8, accessibilityRole: 'button',
              onPress: () => navigation.navigate('SectionDetail', { houseId: it.houseId, sectionId: it.lead }) }
          : {};
        return (
          <Row key={it.id} style={[styles.row, { backgroundColor: t.bg }]} {...rowProps}
            accessibilityLabel={`${d.title}. ${d.sub}`}>
            <Ionicons name={d.icon} size={18} color={t.c} />
            <View style={styles.body}>
              <Text style={[styles.title, { color: t.c }]} numberOfLines={1}>{d.title}</Text>
              <Text style={styles.sub} numberOfLines={1}>{d.sub}</Text>
              {d.progress != null && (
                <View style={styles.track}>
                  <View style={[styles.fill, { width: `${Math.round(d.progress * 100)}%`, backgroundColor: t.c }]} />
                </View>
              )}
            </View>
            {d.canStop && can('stopSection') && (
              <TouchableOpacity style={styles.stop} onPress={() => stop(it)} disabled={stopping === it.id}
                accessibilityRole="button" accessibilityLabel={`Stop: ${d.title}`}>
                {stopping === it.id
                  ? <ActivityIndicator size="small" color={COLORS.danger} />
                  : <Text style={styles.stopTxt}>Stop</Text>}
              </TouchableOpacity>
            )}
          </Row>
        );
      })}
      {items.length > max && <Text style={styles.more}>+{items.length - max} more</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap:  { gap: SPACE.xs, marginBottom: SPACE.md },
  row:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
           borderRadius: RADIUS.sm, paddingVertical: SPACE.sm, paddingHorizontal: SPACE.md },
  body:  { flex: 1, minWidth: 0 },
  title: { fontSize: FONT.sm, fontWeight: '800' },
  sub:   { fontSize: FONT.xs, color: COLORS.textSecondary, marginTop: 1 },
  track: { height: 3, borderRadius: 2, backgroundColor: COLORS.border, marginTop: 5, overflow: 'hidden' },
  fill:  { height: 3, borderRadius: 2 },
  stop:  { paddingHorizontal: SPACE.md, paddingVertical: 6, borderRadius: RADIUS.sm,
           borderWidth: 1, borderColor: COLORS.danger, minWidth: 54, alignItems: 'center' },
  stopTxt: { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '800' },
  more:  { fontSize: FONT.xs, color: COLORS.textTertiary, textAlign: 'right' },
});
