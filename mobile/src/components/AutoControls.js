/**
 * The one switch that decides how the farm is run.
 *
 * This replaces three overlapping flags (mode / trayEnabled / fertEnabled),
 * where turning off "watering" also silently turned off humidity control. There
 * is now a single farm-level switch, and per-section pinning lives in Section
 * Detail for the odd broken section.
 *
 * The critical thing this component has to communicate is that OFF does not
 * mean "the system stops thinking". Both states are explained in full, because
 * a farmer who believes OFF means "nothing happens" will not trust the alarms,
 * and a farmer who believes OFF means "it still waters" will lose plants.
 */
import React, { useState } from 'react';
import { View, Text, StyleSheet, Switch, Alert, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { setAutoMode } from '../services/careV2';
import { useCan } from '../config/auth';
import { COLORS, SPACE, RADIUS } from '../config/theme';

export default function AutoControls({ autoMode, pendingAction = 0, onChanged }) {
  const can = useCan();
  const [busy, setBusy] = useState(false);
  const on = autoMode !== false;
  /* The card stays for everybody. Whether the farm is running itself is the
     single most important fact on the screen - without it a viewer cannot read
     anything else correctly, because "nothing is happening" means one thing
     under Auto and the opposite under Manual. Only the switch is admin. */
  const mayFlip = can('setAutoMode');

  const flip = async (v) => {
    setBusy(true);
    try {
      await setAutoMode(v);
      await onChanged?.();
    } catch (e) {
      Alert.alert('Could not change automatic care', e.message);
    } finally {
      setBusy(false);
    }
  };

  const ask = (v) => {
    if (v) return flip(true);
    // Turning it OFF hands responsibility back to a person. Say so plainly.
    Alert.alert(
      'Turn off automatic care?',
      'The system will keep watching your plants and will still work out what '
      + 'they need. It just will not do it for you.\n\n'
      + 'When something needs doing, your phone will alert you and you press the '
      + 'button in the app.\n\n'
      + 'Daily watering is essential for Vanda, so you must act on those alerts.',
      [{ text: 'Keep it on', style: 'cancel' },
       { text: 'Turn off', style: 'destructive', onPress: () => flip(false) }],
    );
  };

  const tint = on ? COLORS.success : COLORS.warning;

  return (
    <View style={[s.card, { borderColor: `${tint}55` }]}>
      <View style={s.row}>
        <View style={[s.chip, { backgroundColor: `${tint}1F` }]}>
          {busy ? <ActivityIndicator size="small" color={tint} />
                : <Ionicons name={on ? 'shield-checkmark' : 'notifications'} size={20} color={tint} />}
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Automatic care</Text>
          <Text style={[s.state, { color: tint }]}>{on ? 'ON' : 'OFF'}</Text>
        </View>
        <Switch
          value={on}
          onValueChange={ask}
          disabled={busy || !mayFlip}
          trackColor={{ false: COLORS.border, true: `${COLORS.success}80` }}
          thumbColor={on ? COLORS.success : '#FFF'}
          accessibilityRole="switch"
          accessibilityState={{ checked: on, disabled: busy }}
          accessibilityLabel={
            on ? 'Automatic care is on. The system waters, feeds and fills trays by itself.'
               : 'Automatic care is off. The system alerts you and you do it yourself.'
          }
        />
      </View>

      <Text style={s.explain}>
        {on
          ? 'The system waters your plants, mixes in plant food when due, and fills '
            + 'the humidity trays by itself. It tells you what it did.'
          : 'The system still watches your plants and still works out what they need. '
            + 'When something must be done it alerts your phone, and you press the '
            + 'button in the app.'}
      </Text>

      {!on && pendingAction > 0 && (
        <View style={s.pending} accessibilityRole="alert"
          accessibilityLabel={`${pendingAction} things need you to act`}>
          <Ionicons name="alert-circle" size={18} color={COLORS.danger} />
          <Text style={s.pendingText}>
            {pendingAction === 1 ? '1 thing needs you' : `${pendingAction} things need you`}
            {' '}right now. Check your alerts.
          </Text>
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card:  { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg, borderWidth: 1.5,
           padding: SPACE.lg, marginBottom: SPACE.lg },
  row:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  chip:  { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 16, fontWeight: '800', color: COLORS.text },
  state: { fontSize: 13, fontWeight: '800', marginTop: 1, letterSpacing: 0.4 },
  explain: { fontSize: 13, color: COLORS.textSecondary, lineHeight: 19, marginTop: SPACE.md },
  pending: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.md,
             padding: SPACE.md, marginTop: SPACE.md },
  pendingText: { flex: 1, fontSize: 13, fontWeight: '700', color: COLORS.danger },
});
