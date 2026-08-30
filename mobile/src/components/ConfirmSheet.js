/**
 * Confirmation before something happens.
 *
 * Used for every action that moves water, and for the destructive ones. The
 * rule inherited from utils/confirm.js still holds and matters more here: a
 * dialog that triggers irrigation must say exactly WHAT it will affect. An old
 * "water the plants right now" dialog watered the entire farm while saying only
 * "this waters the plants straight away".
 *
 * So `body` is for what physically happens, and `caution` is for the reason a
 * farmer might not want it. Overwatering is the failure this whole project
 * exists to prevent, and the caution line is where that gets said out loud.
 */
import React from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import Sheet from './Sheet';

export default function ConfirmSheet({
  visible,
  title,
  body,
  caution,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  busy = false,
  icon,
  onCancel,
  onConfirm,
  // Extra controls shown between the body and the caution — a choice the
  // farmer makes as part of confirming, not a separate screen.
  children,
}) {
  const tint = destructive ? COLORS.danger : COLORS.primary;

  return (
    <Sheet visible={visible} title={title} onClose={busy ? undefined : onCancel}
      footer={
        <>
          <TouchableOpacity
            style={[s.btn, s.cancel]}
            onPress={onCancel}
            disabled={busy}
            activeOpacity={0.8}
            accessibilityRole="button"
            accessibilityLabel={cancelLabel}>
            <Text style={s.cancelTxt}>{cancelLabel}</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[s.btn, { backgroundColor: tint }, busy && { opacity: 0.7 }]}
            onPress={onConfirm}
            disabled={busy}
            activeOpacity={0.85}
            accessibilityRole="button"
            accessibilityLabel={confirmLabel}>
            {busy
              ? <ActivityIndicator color="#FFF" size="small" />
              : <Text style={s.confirmTxt}>{confirmLabel}</Text>}
          </TouchableOpacity>
        </>
      }>

      {!!icon && (
        <View style={[s.iconWrap, { backgroundColor: `${tint}14` }]}>
          <Ionicons name={icon} size={26} color={tint} />
        </View>
      )}

      {!!body && <Text style={s.body}>{body}</Text>}

      {children}

      {!!caution && (
        <View style={s.caution} accessibilityRole="alert">
          <Ionicons name="alert-circle-outline" size={18} color={COLORS.warning} />
          <Text style={s.cautionTxt}>{caution}</Text>
        </View>
      )}
    </Sheet>
  );
}

const s = StyleSheet.create({
  iconWrap: {
    width: 52, height: 52, borderRadius: 26,
    alignItems: 'center', justifyContent: 'center',
    marginBottom: SPACE.md,
  },
  body: {
    color: COLORS.textSecondary,
    fontSize: FONT.lg - 1,
    lineHeight: 23,
  },
  caution: {
    flexDirection: 'row',
    gap: SPACE.sm,
    alignItems: 'flex-start',
    backgroundColor: COLORS.warningDim,
    borderRadius: RADIUS.md,
    padding: SPACE.md,
    marginTop: SPACE.lg,
  },
  cautionTxt: {
    flex: 1,
    color: COLORS.warning,
    fontSize: FONT.md,
    lineHeight: 19,
    fontWeight: '500',
  },
  btn: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: SPACE.md + 2,
    borderRadius: RADIUS.md,
    minHeight: 50,
  },
  cancel: { backgroundColor: COLORS.bgCardAlt },
  cancelTxt: { color: COLORS.textSecondary, fontSize: FONT.lg - 1, fontWeight: '700' },
  confirmTxt: { color: '#FFF', fontSize: FONT.lg - 1, fontWeight: '700' },
});
