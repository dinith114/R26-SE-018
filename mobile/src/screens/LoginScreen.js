/**
 * Sign in.
 *
 * One deliberate omission: there is no "create account" here, and there should
 * not be. Accounts are made by a farm's admin on the Team screen, which is how
 * a new account gets the tenantId and role claims that make it able to see
 * anything at all. A self-registered account would sign in successfully and
 * then find no farm - a worse experience than not being offered the button.
 */
import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ActivityIndicator, ScrollView,
} from 'react-native';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useAuth } from '../config/auth';

/**
 * Firebase's own codes are never shown.
 *
 * auth/user-not-found and auth/wrong-password are different messages, and
 * showing the difference tells anyone with the app which email addresses have
 * accounts on this farm. They collapse into one sentence. The rest map to what
 * a person can actually do about it.
 */
function humanError(e) {
  const code = (e && e.code) || '';
  if (code === 'auth/invalid-email') return 'That does not look like an email address.';
  if (code === 'auth/too-many-requests')
    return 'Too many attempts. Wait a few minutes and try again.';
  if (code === 'auth/network-request-failed')
    return 'No connection. Check the phone is on the network and try again.';
  if (code === 'auth/user-disabled') return 'This account has been turned off.';
  if (code === 'auth/configuration-not-found' || code === 'auth/operation-not-allowed')
    /* Not the person's fault and not something they can fix, so say who can.
       This is what shows if Firebase Authentication has not been enabled on the
       project - which, as of 4 Sep 2026, it has not. */
    return 'Sign-in is not switched on for this farm yet. Contact whoever set it up.';
  return 'That email and password do not match an account.';
}

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [busy,     setBusy]     = useState(false);
  const [error,    setError]    = useState(null);

  const canSubmit = email.trim().length > 0 && password.length > 0 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
      /* No navigation here. App.js swaps the tree when the auth state changes,
         so this screen simply stops existing. */
    } catch (e) {
      setError(humanError(e));
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.card}>
          <Text style={styles.title}>Orchid Care</Text>
          <Text style={styles.subtitle}>Sign in to your farm</Text>

          <Text style={styles.label}>Email</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={(v) => { setEmail(v); if (error) setError(null); }}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            textContentType="username"
            placeholder="you@example.com"
            placeholderTextColor={COLORS.textTertiary}
            editable={!busy}
          />

          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={(v) => { setPassword(v); if (error) setError(null); }}
            secureTextEntry
            autoCapitalize="none"
            textContentType="password"
            placeholder="Your password"
            placeholderTextColor={COLORS.textTertiary}
            editable={!busy}
            onSubmitEditing={submit}
            returnKeyType="go"
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity
            style={[styles.button, !canSubmit && styles.buttonOff]}
            onPress={submit}
            disabled={!canSubmit}
            accessibilityRole="button"
          >
            {busy
              ? <ActivityIndicator color={COLORS.textInverse} />
              : <Text style={styles.buttonText}>Sign in</Text>}
          </TouchableOpacity>

          <Text style={styles.note}>
            Accounts are created by your farm's admin.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex:   { flex: 1, backgroundColor: COLORS.bg },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: SPACE.xl },
  card: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.lg,
    padding: SPACE.xl,
    ...SHADOW.md,
  },
  title: {
    fontSize: FONT.xxl,
    fontWeight: '700',
    color: COLORS.text,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: FONT.md,
    color: COLORS.textSecondary,
    textAlign: 'center',
    marginTop: SPACE.xs,
    marginBottom: SPACE.xl,
  },
  label: {
    fontSize: FONT.sm,
    fontWeight: '600',
    color: COLORS.textSecondary,
    marginBottom: SPACE.xs,
  },
  input: {
    backgroundColor: COLORS.bgInput,
    borderRadius: RADIUS.md,
    paddingHorizontal: SPACE.md,
    paddingVertical: SPACE.md,
    fontSize: FONT.lg,
    color: COLORS.text,
    marginBottom: SPACE.lg,
  },
  error: {
    fontSize: FONT.md,
    color: COLORS.danger,
    marginBottom: SPACE.md,
  },
  button: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.md,
    paddingVertical: SPACE.lg,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 52,
  },
  buttonOff: { opacity: 0.5 },
  buttonText: {
    color: COLORS.textInverse,
    fontSize: FONT.lg,
    fontWeight: '700',
  },
  note: {
    fontSize: FONT.sm,
    color: COLORS.textTertiary,
    textAlign: 'center',
    marginTop: SPACE.lg,
  },
});
