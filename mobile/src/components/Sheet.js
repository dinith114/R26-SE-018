/**
 * Bottom sheet — the base every dialog in this app is built on.
 *
 * Everything used to call `Alert.alert()`, which is the operating system's own
 * dialog: it cannot be styled, it looks like a system error rather than part of
 * the app, and it cannot show a list, a value or anything but text and buttons.
 * That is why the confirmations looked like stock Android.
 *
 * This is deliberately a SHEET rather than a centred box. A dialog that rises
 * from the bottom lands under the thumb, which matters when the farmer is
 * holding the phone one-handed next to a plant.
 *
 * Dismissing: tapping the backdrop and the Android back button both cancel, so
 * there is always a way out that is not the action.
 */
import React from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableWithoutFeedback, ScrollView,
} from 'react-native';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';

export default function Sheet({
  visible,
  title,
  subtitle,
  onClose,
  children,
  footer,
  maxHeight = '82%',
}) {
  return (
    <Modal
      visible={!!visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent>
      {/* Backdrop. Only the backdrop cancels — a tap inside must not fall
          through and dismiss the sheet mid-decision. */}
      <TouchableWithoutFeedback onPress={onClose} accessible={false}>
        <View style={s.backdrop} />
      </TouchableWithoutFeedback>

      <View style={s.dock} pointerEvents="box-none">
        <View style={[s.sheet, { maxHeight }]}>
          <View style={s.grip} />

          {!!title && (
            <View style={s.head}>
              <Text style={s.title} accessibilityRole="header">{title}</Text>
              {!!subtitle && <Text style={s.sub}>{subtitle}</Text>}
            </View>
          )}

          <ScrollView
            style={s.bodyScroll}
            contentContainerStyle={s.body}
            showsVerticalScrollIndicator={false}
            bounces={false}>
            {children}
          </ScrollView>

          {!!footer && <View style={s.footer}>{footer}</View>}
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(21, 25, 22, 0.45)',
  },
  dock: { flex: 1, justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: COLORS.bgCard,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    paddingBottom: SPACE.xl,
  },
  grip: {
    alignSelf: 'center',
    width: 38,
    height: 4,
    borderRadius: 2,
    backgroundColor: COLORS.border,
    marginTop: SPACE.md,
    marginBottom: SPACE.sm,
  },
  head: { paddingHorizontal: SPACE.xl, paddingTop: SPACE.sm, paddingBottom: SPACE.md },
  title: {
    color: COLORS.text,
    fontSize: 20,
    fontWeight: '700',
    letterSpacing: -0.3,
  },
  sub: {
    color: COLORS.textSecondary,
    fontSize: FONT.md,
    lineHeight: 20,
    marginTop: 5,
  },
  bodyScroll: { flexGrow: 0 },
  body: { paddingHorizontal: SPACE.xl },
  footer: {
    flexDirection: 'row',
    gap: SPACE.sm,
    paddingHorizontal: SPACE.xl,
    paddingTop: SPACE.lg,
    marginTop: SPACE.sm,
    borderTopWidth: 1,
    borderTopColor: COLORS.borderLight,
  },
});
