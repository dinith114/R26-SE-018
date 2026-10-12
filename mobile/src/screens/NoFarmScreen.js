/**
 * Signed in to Firebase, but the account belongs to no farm.
 *
 * This is the state that is easy to leave out and miserable to land in. The
 * sign-in succeeds, so the app looks like it worked, and then every request
 * comes back 401 because verify_bearer refuses a token with no tenantId claim.
 * Without this screen the app sits on a dashboard that never loads, with no
 * message and no way out but reinstalling.
 *
 * It happens for two real reasons: an account created directly in Firebase
 * rather than through the Team screen, so nobody ever stamped its claims; or
 * provisioning that failed after creating the auth user and before writing them.
 * Neither is fixable from the phone, and signing in again will not help - which
 * is why the only action here is to sign out and use a different account.
 */
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useAuth } from '../config/auth';

export default function NoFarmScreen() {
  const { email, signOut } = useAuth();

  return (
    <View style={styles.wrap}>
      <View style={styles.card}>
        <Text style={styles.title}>This account is not set up for a farm</Text>
        <Text style={styles.body}>
          {email ? `${email} signed in, but ` : 'You are signed in, but '}
          no farm has been linked to it. An admin has to add the account to a
          farm before it can see anything.
        </Text>
        <Text style={styles.body}>
          Signing in again will not change this.
        </Text>

        <TouchableOpacity
          style={styles.button}
          onPress={signOut}
          accessibilityRole="button"
        >
          <Text style={styles.buttonText}>Sign out</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: COLORS.bg,
    justifyContent: 'center',
    padding: SPACE.xl,
  },
  card: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.lg,
    padding: SPACE.xl,
    ...SHADOW.md,
  },
  title: {
    fontSize: FONT.xl,
    fontWeight: '700',
    color: COLORS.text,
    marginBottom: SPACE.lg,
  },
  body: {
    fontSize: FONT.lg,
    color: COLORS.textSecondary,
    lineHeight: 24,
    marginBottom: SPACE.md,
  },
  button: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingVertical: SPACE.lg,
    alignItems: 'center',
    marginTop: SPACE.lg,
  },
  buttonText: {
    color: COLORS.textInverse,
    fontSize: FONT.lg,
    fontWeight: '700',
  },
});
