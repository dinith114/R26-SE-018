/**
 * Reading-freshness UI.
 *
 * The farm has Wi-Fi but no mains power, so every node runs off a battery and
 * can stop reporting silently. Before this existed the app happily showed a
 * three-day-old humidity reading as if it were current.
 *
 * Rule enforced by these components: a sensor number is never shown without
 * saying how old it is.
 *
 * `freshness` comes from the backend (/overview -> sections[].freshness) and is
 * shaped { state, ageMinutes, label, trusted, message }, where state is one of
 * 'live' | 'delayed' | 'stale' | 'never' | 'future' | 'nonode' | 'estimated'.
 *
 * 'estimated' is the one state not produced by the backend's freshness logic.
 * The section screen synthesises it when a zone has no hardware of its own but
 * carries a recent kriged estimate from its neighbours. It is listed here
 * because STATE_STYLE falls back to `never` for an unknown state, so a state
 * added anywhere else would render as a grey "Never" and quietly misreport a
 * working feature as a dead sensor.
 *
 * 'future' means the reading is stamped ahead of real time - a wrong device
 * clock, or simulated data. It is reported separately from 'stale' because the
 * device IS reporting; it is the timestamp that cannot be believed, and telling
 * a farmer to check the battery would send them after the wrong fault.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACE, RADIUS } from '../config/theme';

export const STATE_STYLE = {
  live:    { color: COLORS.success,      icon: 'ellipse',              word: 'Live' },
  // 'delayed' and 'stale' both mean the node stopped reporting; they differ
  // only in for how long, which the message says. The farmer needs one word,
  // and 'Late' read as a minor delay while the numbers sat there in colour.
  delayed: { color: COLORS.warning,      icon: 'alert-circle-outline', word: 'No signal' },
  stale:   { color: COLORS.danger,       icon: 'battery-dead-outline', word: 'No signal' },
  never:   { color: COLORS.textTertiary, icon: 'help-circle-outline',  word: 'Never' },
  future:  { color: COLORS.warning,      icon: 'alert-circle-outline', word: 'Clock wrong' },
  // No node is LINKED at all - different from a node that has gone quiet, and
  // the fix is different too: link one, rather than check the battery.
  nonode:  { color: COLORS.textTertiary, icon: 'hardware-chip-outline', word: 'No node' },
  // Not measured here. Interpolated from sections that ARE measured, which is
  // a different claim from both "fresh" and "stale" and needs its own word: a
  // farmer must never mistake a neighbour's reading for this zone's own.
  estimated: { color: COLORS.estimated, icon: 'git-network-outline', word: 'Estimated' },
};

export const isTrusted = (f) => f?.trusted !== false;

/** The node is keeping its promise. The only state in which a reading may be
 *  shown in colour, or an action button left pressable. */
export const isLive = (f) => f?.state === 'live';

/** Interpolated from neighbours rather than measured here. Deliberately NOT
 *  folded into isLive: the two carry different confidence, and every caller
 *  should have to decide which it will accept. */
export const isEstimated = (f) => f?.state === 'estimated';

/** Small inline badge — sits next to a reading. */
export function FreshnessBadge({ freshness, style }) {
  if (!freshness) return null;
  const st = STATE_STYLE[freshness.state] || STATE_STYLE.never;
  /* Always the LABEL, which is a time - "just now", "8 min ago".
     This used to collapse to the word "Live" whenever a reading was current,
     so the one number a farmer actually wants - how old is this? - was hidden
     precisely when the badge had room to show it. "Live" also said nothing
     about whether that meant four seconds or four minutes. */
  const text = freshness.label;

  return (
    <View
      style={[s.badge, { backgroundColor: `${st.color}1A` }, style]}
      accessible
      accessibilityRole="text"
      accessibilityLabel={
        freshness.state === 'live'
          ? 'Reading is live'
          : `Reading is ${freshness.label}${freshness.trusted ? '' : '. Not trustworthy.'}`
      }>
      <Ionicons name={st.icon} size={freshness.state === 'live' ? 8 : 12} color={st.color} />
      <Text style={[s.badgeText, { color: st.color }]}>{text}</Text>
    </View>
  );
}

/**
 * Full-width warning shown ABOVE the numbers it applies to, so the farmer reads
 * the caveat before the value. Renders nothing while data is trustworthy.
 */
export function StaleWarning({ freshness, name, style }) {
  if (!freshness || freshness.trusted) return null;
  const st = STATE_STYLE[freshness.state] || STATE_STYLE.never;

  return (
    <View
      style={[s.warn, { backgroundColor: `${st.color}14`, borderLeftColor: st.color }, style]}
      accessible
      accessibilityRole="alert"
      accessibilityLabel={`Warning. ${name ? name + '. ' : ''}${freshness.message}`}>
      <Ionicons name={st.icon} size={22} color={st.color} />
      <View style={{ flex: 1 }}>
        <Text style={[s.warnTitle, { color: st.color }]}>
          {freshness.state === 'future'
            ? (name ? `${name}'s clock is wrong` : 'Device clock is wrong')
            : freshness.state === 'nonode'
              ? (name ? `${name} has no sensor node` : 'No sensor node')
              : (name ? `${name} is not reporting` : 'Device is not reporting')}
        </Text>
        <Text style={s.warnBody}>{freshness.message}</Text>
      </View>
    </View>
  );
}

/**
 * Farm-wide banner: "2 of 4 devices stopped reporting".
 * `sections` is the flattened section list from /overview.
 */
export function FarmStaleBanner({ sections = [], style }) {
  const bad = sections.filter((x) => x.freshness && !x.freshness.trusted);
  if (bad.length === 0) return null;
  const names = bad.map((x) => x.meta?.name || x.sectionId).join(', ');
  // A wrong clock is not a flat battery. If any bad section is future-dated the
  // headline has to stay neutral, or it sends the farmer after the wrong fault.
  const anyFuture = bad.some((x) => x.freshness.state === 'future'
                                 || x.freshness.state === 'nonode');
  const headline = anyFuture
    ? (bad.length === 1 ? '1 device needs attention' : `${bad.length} devices need attention`)
    : (bad.length === 1 ? '1 device stopped reporting' : `${bad.length} devices stopped reporting`);

  return (
    <View
      style={[s.warn, { backgroundColor: COLORS.dangerDim, borderLeftColor: COLORS.danger }, style]}
      accessible
      accessibilityRole="alert"
      accessibilityLabel={`Warning. ${bad.length} of ${sections.length} devices stopped reporting: ${names}. Readings shown for them are old.`}>
      <Ionicons name="battery-dead-outline" size={24} color={COLORS.danger} />
      <View style={{ flex: 1 }}>
        <Text style={[s.warnTitle, { color: COLORS.danger }]}>{headline}</Text>
        <Text style={s.warnBody}>
          {names}. The readings shown for {bad.length === 1 ? 'it' : 'them'} cannot be
          trusted{anyFuture ? '.' : ', check the battery and Wi-Fi.'}
        </Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  badge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: SPACE.sm, paddingVertical: 3,
    borderRadius: RADIUS.full, alignSelf: 'flex-start',
  },
  badgeText: { fontSize: 11, fontWeight: '700' },

  warn: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
    borderRadius: RADIUS.md, borderLeftWidth: 4,
    padding: SPACE.lg, marginBottom: SPACE.md,
  },
  warnTitle: { fontSize: 15, fontWeight: '800' },
  warnBody:  { fontSize: 14, color: COLORS.textSecondary, marginTop: 2, lineHeight: 20 },
});

export default FreshnessBadge;
