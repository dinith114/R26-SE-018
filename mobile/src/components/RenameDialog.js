/**
 * Rename dialog.
 *
 * Built as a real Modal rather than Alert.prompt, because Alert.prompt is
 * iOS-only — on Android it silently does nothing, which would have made the
 * rename feature look broken on exactly the phones these farmers use.
 *
 * Usage:
 *   const [open, setOpen] = useState(false);
 *   <RenameDialog visible={open} title="Rename section" value={name}
 *                 onCancel={() => setOpen(false)} onSave={async (n) => {...}} />
 */
import React, { useState, useEffect } from 'react';
import {
  Modal, View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, SPACE, RADIUS, SHADOW } from '../config/theme';

const MAX = 40;

export default function RenameDialog({
  visible, title = 'Rename', label = 'Name', value = '',
  placeholder = 'Enter a name', onCancel, onSave,
}) {
  const [text, setText]   = useState(value);
  const [busy, setBusy]   = useState(false);
  const [error, setError] = useState(null);

  // reset each time it opens, so a cancelled edit is not remembered
  useEffect(() => {
    if (visible) { setText(value); setError(null); setBusy(false); }
  }, [visible, value]);

  const trimmed = text.trim();
  const invalid = trimmed.length === 0 || trimmed.length > MAX;

  const save = async () => {
    if (invalid || busy) return;
    setBusy(true); setError(null);
    try {
      await onSave(trimmed);
    } catch (e) {
      setError(e.message || 'Could not save that name');
      setBusy(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView
        style={s.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[s.card, SHADOW.lg]} accessibilityViewIsModal accessibilityRole="none">
          <Text style={s.title} accessibilityRole="header">{title}</Text>

          <Text style={s.label}>{label}</Text>
          <TextInput
            style={[s.input, error && { borderColor: COLORS.danger }]}
            value={text}
            onChangeText={(t) => { setText(t); setError(null); }}
            placeholder={placeholder}
            placeholderTextColor={COLORS.textTertiary}
            autoFocus
            selectTextOnFocus
            maxLength={MAX}
            returnKeyType="done"
            onSubmitEditing={save}
            editable={!busy}
            accessibilityLabel={label}
          />

          <View style={s.metaRow}>
            {error ? (
              <View style={s.errRow}>
                <Ionicons name="alert-circle" size={14} color={COLORS.danger} />
                <Text style={s.err}>{error}</Text>
              </View>
            ) : (
              <Text style={s.count}>{trimmed.length}/{MAX}</Text>
            )}
          </View>

          <View style={s.btnRow}>
            <TouchableOpacity
              style={[s.btn, s.btnGhost]} onPress={onCancel} disabled={busy}
              accessibilityRole="button" accessibilityLabel="Cancel renaming">
              <Text style={s.btnGhostText}>Cancel</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[s.btn, s.btnSave, (invalid || busy) && { opacity: 0.5 }]}
              onPress={save} disabled={invalid || busy}
              accessibilityRole="button"
              accessibilityState={{ disabled: invalid || busy }}
              accessibilityLabel="Save the new name">
              {busy
                ? <ActivityIndicator color="#FFF" size="small" />
                : <Text style={s.btnSaveText}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(28,25,23,0.45)',
              alignItems: 'center', justifyContent: 'center', padding: SPACE.xl },
  card:     { width: '100%', maxWidth: 400, backgroundColor: COLORS.bgCard,
              borderRadius: RADIUS.lg, padding: SPACE.xl },
  title:    { fontSize: 19, fontWeight: '800', color: COLORS.text, marginBottom: SPACE.lg },
  label:    { fontSize: 13, fontWeight: '700', color: COLORS.textSecondary, marginBottom: 6 },
  input:    { borderWidth: 1.5, borderColor: COLORS.border, borderRadius: RADIUS.md,
              paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md,
              fontSize: 17, color: COLORS.text, backgroundColor: COLORS.bgCardAlt },
  metaRow:  { minHeight: 22, justifyContent: 'center', marginTop: 6 },
  count:    { fontSize: 12, color: COLORS.textTertiary, textAlign: 'right' },
  errRow:   { flexDirection: 'row', alignItems: 'center', gap: 5 },
  err:      { fontSize: 12, color: COLORS.danger, flex: 1 },
  btnRow:   { flexDirection: 'row', gap: SPACE.md, marginTop: SPACE.lg },
  btn:      { flex: 1, alignItems: 'center', justifyContent: 'center',
              paddingVertical: SPACE.md + 2, borderRadius: RADIUS.md },
  btnGhost: { backgroundColor: COLORS.bgCardAlt },
  btnGhostText: { fontSize: 16, fontWeight: '700', color: COLORS.textSecondary },
  btnSave:  { backgroundColor: COLORS.primary },
  btnSaveText:  { fontSize: 16, fontWeight: '800', color: '#FFF' },
});
