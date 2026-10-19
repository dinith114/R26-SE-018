/**
 * "Set your farm's location", on Home and My Farm until it is set.
 *
 * Asked for by the grower on 19 Oct 2026: the location had to be required, and
 * it was easy to skip. Without it the backend uses the weather at Peradeniya
 * (forecast.farm_location), so each section's "Expected today" forecast is
 * worked out from somewhere else's weather, and nothing on any screen looks
 * wrong. That forecast is the only thing in the app the location feeds today,
 * and the banner claims no more than that.
 *
 * It cannot be dismissed. It goes away when the location is saved.
 *
 * Only an admin may set it (perms.js mirrors require_role on the server).
 * Anybody else is told who can, rather than offered a button that would fail.
 */
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import { useCan } from '../config/auth';
import { setFarmLocation } from '../services/careV2';
import LocationPicker from './LocationPicker';

export const hasFarmLocation = (farm) =>
  farm?.latitude != null && farm?.longitude != null
  && Number.isFinite(Number(farm.latitude)) && Number.isFinite(Number(farm.longitude));

export default function FarmLocationBanner({ farm, onSaved, style }) {
  const can = useCan();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // Hides the banner the moment the server says yes; the reload then confirms it.
  const [saved, setSaved] = useState(false);

  if (saved || hasFarmLocation(farm)) return null;
  const allowed = can('setFarmLocation');

  const save = async ({ latitude, longitude }) => {
    setSaving(true);
    try {
      await setFarmLocation(latitude, longitude);
      setOpen(false);
      setSaved(true);
      onSaved?.();
    } catch (e) {
      Alert.alert('Could not save the location', e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[s.card, style]} accessibilityRole="alert">
      <View style={s.top}>
        <View style={s.icon}>
          <Ionicons name="location-outline" size={20} color={COLORS.warning} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Set your farm's location</Text>
          <Text style={s.body}>
            Until it is set, the app uses the weather at Peradeniya instead of at your
            farm. That changes each section's Expected today forecast.
          </Text>
        </View>
      </View>
      {allowed ? (
        <TouchableOpacity style={s.btn} onPress={() => setOpen(true)} activeOpacity={0.8}
          accessibilityRole="button" accessibilityLabel="Set the farm's location">
          <Ionicons name="map-outline" size={18} color="#FFF" />
          <Text style={s.btnTxt}>Set location</Text>
        </TouchableOpacity>
      ) : (
        <Text style={s.who}>Only the farm's admin can set it, in Settings.</Text>
      )}
      {allowed ? (
        <LocationPicker visible={open} initial={null} saving={saving}
          onCancel={() => setOpen(false)} onPick={save} />
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card:  { backgroundColor: COLORS.warningDim, borderRadius: RADIUS.md, padding: SPACE.lg,
           gap: SPACE.md, marginBottom: SPACE.lg, borderWidth: 1, borderColor: `${COLORS.warning}33` },
  top:   { flexDirection: 'row', gap: SPACE.md, alignItems: 'flex-start' },
  icon:  { width: 34, height: 34, borderRadius: 17, backgroundColor: COLORS.bgCard,
           alignItems: 'center', justifyContent: 'center' },
  title: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  body:  { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, marginTop: 2 },
  btn:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm,
           backgroundColor: COLORS.warning, borderRadius: RADIUS.md, paddingVertical: SPACE.md },
  btnTxt:{ color: '#FFF', fontSize: FONT.md, fontWeight: '800' },
  who:   { color: COLORS.textSecondary, fontSize: FONT.sm, fontStyle: 'italic' },
});
