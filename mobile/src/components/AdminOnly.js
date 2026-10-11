/**
 * A whole screen that only an admin can use.
 *
 * Five screens in this app are admin workflows end to end - the setup wizard,
 * the house planner, adding a sensor, calibration, and applying a placement.
 * There is nothing on them for an operator to read, so gating their individual
 * buttons would leave a page of dead furniture. They get this instead.
 *
 * It is a second line, not the line. The entry points that lead here are gated
 * too, and the server refuses every one of these actions to a non-admin
 * whatever the app does. This exists because entry points are easy to miss -
 * a screen can be reached from a notification, a deep link, or a card added
 * later by someone who did not know the rule - and a screen that guards itself
 * cannot be reached the wrong way.
 */
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useIsAdmin } from '../config/auth';

export default function AdminOnly({ children, what, navigation }) {
  const isAdmin = useIsAdmin();
  if (isAdmin) return children;

  return (
    <View style={styles.wrap}>
      <View style={[styles.card, SHADOW.sm]}>
        <Ionicons name="lock-closed-outline" size={30} color={COLORS.textTertiary} />
        <Text style={styles.title}>Admin only</Text>
        <Text style={styles.body}>
          {what || 'This part of the app'} can only be changed by an admin
          account. Ask whoever manages this farm.
        </Text>
        {navigation ? (
          <TouchableOpacity style={styles.btn} onPress={() => navigation.goBack()}
            accessibilityRole="button">
            <Text style={styles.btnText}>Go back</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: COLORS.bg, justifyContent: 'center', padding: SPACE.xl },
  card: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
    padding: SPACE.xl, alignItems: 'center', gap: SPACE.md,
  },
  title: { fontSize: FONT.xl, fontWeight: '700', color: COLORS.text },
  body: {
    fontSize: FONT.lg, color: COLORS.textSecondary,
    textAlign: 'center', lineHeight: 24,
  },
  btn: {
    backgroundColor: COLORS.primary, borderRadius: RADIUS.md,
    paddingVertical: SPACE.md, paddingHorizontal: SPACE.xl, marginTop: SPACE.sm,
  },
  btnText: { color: COLORS.textInverse, fontSize: FONT.lg, fontWeight: '700' },
});
