import React from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, Pressable,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

/**
 * The app's own dialog, in place of `Alert.alert`.
 *
 * The platform alert is a white box with blue system text. Dropped into a
 * green app it does not read as part of the app at all - the first grower to
 * see one took a confirmation for an error message. Anything the app has to
 * say should look like the app saying it.
 *
 * It also fixes something the platform alert cannot do: these messages are
 * teaching. "Did the base of the flower start to swell?" is a reasonable
 * question only if the grower knows where to look, and a system alert has no
 * room for a heading, a body, and a "where to look" block underneath.
 *
 * Four tones, which set the icon and the accent only - never the whole
 * surface, so the text stays on the app's normal card colour and keeps its
 * contrast:
 *
 *   info     an explanation, one dismiss button
 *   success  something was saved
 *   warn     a choice with a consequence worth reading
 *   danger   destructive, and the confirm button says what it destroys
 */

const TONES = {
  info:    { icon: 'information-circle', color: 'primary' },
  success: { icon: 'checkmark-circle',   color: 'success' },
  warn:    { icon: 'alert-circle',       color: 'warning' },
  danger:  { icon: 'trash-outline',      color: 'danger'  },
};

const AppDialog = ({
  visible,
  tone = 'info',
  title,
  message,
  /** Optional secondary block: { label, text } — "where to look", "timing". */
  sections = [],
  /** [{ label, onPress, style: 'primary'|'danger'|'quiet' }] — defaults to one dismiss. */
  actions,
  onDismiss,
}) => {
  const t = TONES[tone] || TONES.info;
  const accent = COLORS[t.color] || COLORS.primary;
  const buttons = actions && actions.length
    ? actions
    : [{ label: 'Got it', style: 'primary', onPress: onDismiss }];

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}
      statusBarTranslucent
    >
      {/* Tapping the scrim dismisses, which is what everyone expects — but
          only when there is a single action. With a real choice on screen,
          dismissing by accident would silently pick one. */}
      <Pressable
        style={styles.scrim}
        onPress={buttons.length === 1 ? onDismiss : undefined}
      >
        <Pressable style={[styles.card, SHADOW.md]} onPress={() => {}}>
          <View style={styles.head}>
            <View style={[styles.iconWrap, { backgroundColor: accent + '1A' }]}>
              <Ionicons name={t.icon} size={20} color={accent} />
            </View>
            <Text style={styles.title}>{title}</Text>
          </View>

          <ScrollView
            style={styles.bodyScroll}
            contentContainerStyle={styles.body}
            showsVerticalScrollIndicator={false}
          >
            {message ? <Text style={styles.message}>{message}</Text> : null}

            {sections.filter((s) => s && s.text).map((s) => (
              <View key={s.label} style={styles.section}>
                <Text style={[styles.sectionLabel, { color: accent }]}>
                  {s.label}
                </Text>
                <Text style={styles.sectionText}>{s.text}</Text>
              </View>
            ))}
          </ScrollView>

          <View style={[styles.actions, buttons.length > 2 && styles.actionsStacked]}>
            {buttons.map((b) => {
              const danger = b.style === 'danger';
              const quiet = b.style === 'quiet';
              return (
                <TouchableOpacity
                  key={b.label}
                  style={[
                    styles.btn,
                    buttons.length > 2 && styles.btnFull,
                    danger && styles.btnDanger,
                    quiet && styles.btnQuiet,
                    !danger && !quiet && { backgroundColor: accent },
                  ]}
                  onPress={() => {
                    onDismiss?.();
                    b.onPress?.();
                  }}
                >
                  <Text style={[
                    styles.btnText,
                    quiet && { color: COLORS.textSecondary },
                  ]}>
                    {b.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
};

const styles = StyleSheet.create({
  scrim: {
    flex: 1, backgroundColor: 'rgba(28, 25, 23, 0.55)',
    alignItems: 'center', justifyContent: 'center', padding: SPACE.xl,
  },
  card: {
    width: '100%', maxWidth: 420, maxHeight: '82%',
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
    padding: SPACE.lg, borderWidth: 1, borderColor: COLORS.border,
  },

  head: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  iconWrap: {
    width: 38, height: 38, borderRadius: 19,
    alignItems: 'center', justifyContent: 'center',
  },
  title: { flex: 1, color: COLORS.text, fontSize: FONT.lg, fontWeight: '800', lineHeight: 23 },

  bodyScroll: { marginTop: SPACE.md },
  body: { paddingBottom: SPACE.xs },
  message: { color: COLORS.textSecondary, fontSize: FONT.md, lineHeight: 23 },

  section: {
    marginTop: SPACE.md, backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.sm, padding: SPACE.md,
  },
  sectionLabel: {
    fontSize: FONT.sm, fontWeight: '800',
    textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4,
  },
  sectionText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 21 },

  actions: {
    flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.lg,
    justifyContent: 'flex-end',
  },
  actionsStacked: { flexDirection: 'column-reverse' },
  btn: {
    paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md,
    borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center',
    minWidth: 92,
  },
  btnFull: { width: '100%' },
  btnDanger: { backgroundColor: COLORS.danger },
  btnQuiet: { backgroundColor: COLORS.bgCardAlt, borderWidth: 1, borderColor: COLORS.border },
  btnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },
});

export default AppDialog;
