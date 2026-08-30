/**
 * Choosing from a list — one option, or several.
 *
 * Does four jobs that used to need four different controls: the read-interval
 * chips, the three-way control mode, "which house", and "which sections". They
 * are the same interaction, so they are the same component.
 *
 * Single select commits on tap, because picking one thing and then pressing
 * Confirm is a wasted tap. Multi select waits for Confirm, because the farmer
 * is building a set and a stray tap must not fire an irrigation run.
 *
 * `confirmOnSelect={false}` forces the single-select case to wait too, which is
 * what the read interval and the control mode use: those change how the system
 * behaves, so they get an explicit confirmation step.
 */
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import Sheet from './Sheet';

export default function SelectSheet({
  visible,
  title,
  subtitle,
  options = [],           // [{ key, label, sub, disabled, disabledNote }]
  emptyText = null,       // shown instead of the list when there is nothing to pick
  value = null,           // single select: the selected key
  values = [],            // multi select: selected keys
  multi = false,
  confirmOnSelect = true, // single select only
  confirmLabel = 'Confirm',
  busy = false,
  onCancel,
  onConfirm,              // (keyOrKeys) => void
}) {
  const [picked, setPicked] = useState(multi ? values : value);

  // Re-seed whenever the sheet opens, so a cancelled edit does not persist
  // into the next time it is shown.
  useEffect(() => {
    if (visible) setPicked(multi ? values : value);
  }, [visible]);

  const usable = options.filter((o) => !o.disabled);
  const allOn = multi && usable.length > 0 &&
                usable.every((o) => (picked || []).includes(o.key));

  const toggle = (o) => {
    if (o.disabled) return;
    if (!multi) {
      setPicked(o.key);
      if (confirmOnSelect) onConfirm?.(o.key);
      return;
    }
    const cur = picked || [];
    setPicked(cur.includes(o.key) ? cur.filter((k) => k !== o.key) : [...cur, o.key]);
  };

  const nothingPicked = multi ? !(picked || []).length : picked == null;
  const showFooter = multi || !confirmOnSelect;

  return (
    <Sheet
      visible={visible}
      title={title}
      subtitle={subtitle}
      onClose={busy ? undefined : onCancel}
      footer={showFooter ? (
        <>
          <TouchableOpacity style={[s.btn, s.cancel]} onPress={onCancel} disabled={busy}
            activeOpacity={0.8} accessibilityRole="button" accessibilityLabel="Cancel">
            <Text style={s.cancelTxt}>Cancel</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[s.btn, { backgroundColor: COLORS.primary },
                    (nothingPicked || busy) && { opacity: 0.45 }]}
            onPress={() => onConfirm?.(picked)}
            disabled={nothingPicked || busy}
            activeOpacity={0.85}
            accessibilityRole="button"
            accessibilityState={{ disabled: nothingPicked || busy }}
            accessibilityLabel={confirmLabel}>
            {busy ? <ActivityIndicator color="#FFF" size="small" />
                  : <Text style={s.confirmTxt}>{confirmLabel}</Text>}
          </TouchableOpacity>
        </>
      ) : null}>

      {multi && usable.length > 1 && (
        <TouchableOpacity
          style={s.allRow}
          onPress={() => setPicked(allOn ? [] : usable.map((o) => o.key))}
          activeOpacity={0.7}
          accessibilityRole="button"
          accessibilityLabel={allOn ? 'Clear all' : 'Select all'}>
          <Text style={s.allTxt}>{allOn ? 'Clear all' : 'Select all'}</Text>
        </TouchableOpacity>
      )}

      {options.length === 0 && !!emptyText && (
        <View style={s.empty}>
          <Ionicons name="information-circle-outline" size={20} color={COLORS.textTertiary} />
          <Text style={s.emptyTxt}>{emptyText}</Text>
        </View>
      )}

      {options.map((o) => {
        const on = multi ? (picked || []).includes(o.key) : picked === o.key;
        return (
          <TouchableOpacity
            key={o.key}
            style={[s.row, on && s.rowOn, o.disabled && s.rowOff]}
            onPress={() => toggle(o)}
            disabled={o.disabled}
            activeOpacity={0.75}
            accessibilityRole={multi ? 'checkbox' : 'radio'}
            accessibilityState={{ checked: on, disabled: !!o.disabled }}
            accessibilityLabel={`${o.label}${o.sub ? '. ' + o.sub : ''}`}>

            <View style={[
              multi ? s.box : s.dot,
              on && { borderColor: COLORS.primary, backgroundColor: COLORS.primary },
              o.disabled && { borderColor: COLORS.border },
            ]}>
              {on && <Ionicons name={multi ? 'checkmark' : 'ellipse'}
                       size={multi ? 14 : 8} color="#FFF" />}
            </View>

            <View style={{ flex: 1 }}>
              <Text style={[s.label, o.disabled && s.labelOff]}>{o.label}</Text>
              {!!(o.disabled ? o.disabledNote || o.sub : o.sub) && (
                <Text style={s.sub}>{o.disabled ? (o.disabledNote || o.sub) : o.sub}</Text>
              )}
            </View>
          </TouchableOpacity>
        );
      })}
    </Sheet>
  );
}

const s = StyleSheet.create({
  empty: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm,
           backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
           padding: SPACE.lg, marginBottom: SPACE.sm },
  emptyTxt: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  allRow: { alignSelf: 'flex-end', paddingVertical: SPACE.sm, paddingHorizontal: 2 },
  allTxt: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACE.md,
    paddingVertical: SPACE.md + 2,
    paddingHorizontal: SPACE.md,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.border,
    backgroundColor: COLORS.bgCard,
    marginBottom: SPACE.sm,
  },
  rowOn:  { borderColor: COLORS.primary, backgroundColor: COLORS.primaryDim, borderWidth: 1.5 },
  rowOff: { opacity: 0.5 },

  box: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 1.5, borderColor: COLORS.border,
    alignItems: 'center', justifyContent: 'center',
  },
  dot: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 1.5, borderColor: COLORS.border,
    alignItems: 'center', justifyContent: 'center',
  },

  label:    { color: COLORS.text, fontSize: FONT.lg - 1, fontWeight: '600' },
  labelOff: { color: COLORS.textTertiary },
  sub:      { color: COLORS.textTertiary, fontSize: FONT.md, marginTop: 2 },

  btn: {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    paddingVertical: SPACE.md + 2, borderRadius: RADIUS.md, minHeight: 50,
  },
  cancel: { backgroundColor: COLORS.bgCardAlt },
  cancelTxt:  { color: COLORS.textSecondary, fontSize: FONT.lg - 1, fontWeight: '700' },
  confirmTxt: { color: '#FFF', fontSize: FONT.lg - 1, fontWeight: '700' },
});
