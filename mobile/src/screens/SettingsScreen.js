import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  Animated, Alert, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import LocationPicker from '../components/LocationPicker';
import { hasFarmLocation } from '../components/FarmLocationBanner';
import { useCan, useAuth, useIsAdmin } from '../config/auth';
import { getOverview, setFarmLocation, setPourDefaults } from '../services/careV2';
import Sheet from '../components/Sheet';
import DurationPicker from '../components/DurationPicker';
import { DEFAULT_POUR_SEC, pourLabel } from '../services/pourLength';

/* This screen used to read the LEGACY v1 paths at the Firebase root - /latest,
   /prediction and /history - which nothing else in the v2 app touches. They
   still hold seed data from the old firmware: on 24 Aug 2026 /latest reported
   30.1 C, 42 % RH and 680 lux with timestamp 5583302 (a 1970 date), while the
   real node was reading 31.4 C, 78.2 % RH and 3 lux. Every green "OK" badge on
   this page was therefore derived from fabricated data, and "ESP32 Live" could
   read Live while the actual board sat unplugged.

   Everything here now comes from the same v2 API the rest of the app uses, so a
   status shown on this page is a status the hardware really has.

   There is no tray probe: it was removed on 10 Oct 2026. The grower sets how
   long a tray fill runs (a section's Pour lengths) and the models decide when.

   19 Oct 2026, at the grower's request, this page keeps only what a farm user
   needs: where the farm is, who is signed in, and the app version. Removed:
   a fixed "My Vanda Orchid" profile card whose edit button promised a future
   release; a readings strip and a HARDWARE card that both described ONE
   sensor board (the first one online) on farms that have several; a CLOUD
   card in developer words; four alert switches that were saved on the phone
   and read by nothing else in the app; and the university project rows.
   Board health is on My Farm (its status line) and each section's Setup tab. */

// ─── Small helpers ─────────────────────────────────────────────────────────────
const Divider = () => <View style={s.divider} />;

const Row = ({ icon, iconColor, label, value, hint, right, onPress }) => (
  <TouchableOpacity style={s.row} activeOpacity={onPress ? 0.6 : 1} onPress={onPress}>
    <View style={[s.rowIcon, { backgroundColor: `${iconColor || COLORS.textTertiary}14` }]}>
      <Ionicons name={icon} size={17} color={iconColor || COLORS.textSecondary} />
    </View>
    <View style={{ flex: 1 }}>
      <Text style={s.rowLabel}>{label}</Text>
      {hint && <Text style={s.rowHint}>{hint}</Text>}
    </View>
    {right ?? (
      <Text style={s.rowValue}>{value}</Text>
    )}
  </TouchableOpacity>
);

// ─── Main screen ───────────────────────────────────────────────────────────────
export default function SettingsScreen({ navigation }) {
  /* What this account may do. The server refuses the rest whatever
     happens here; this only stops the screen offering a control that
     would come back 403. */
  const can = useCan();
  const isAdmin = useIsAdmin();
  const { email: authEmail, signOut } = useAuth();
  const [farm,    setFarm]    = useState(null);   // /farm/meta, incl. coordinates
  const [farmErr, setFarmErr] = useState(false);  // could not load it at all
  const [locOpen, setLocOpen] = useState(false);  // the map picker
  const [locSaving, setLocSaving] = useState(false);
  // The farm's default lengths, being edited: { waterSec, traySec } or null.
  const [lenEdit, setLenEdit] = useState(null);
  const [lenSaving, setLenSaving] = useState(false);

  const fadeAnim = useRef(new Animated.Value(0)).current;

  /* Save the position the farmer put the pin on.

     No parsing and no range check here any more: a pin dropped on a map cannot
     be out of range, and cannot be a typo. The backend still validates, because
     it is a public endpoint and not only this screen calls it. */
  const saveLocation = async ({ latitude, longitude }) => {
    try {
      setLocSaving(true);
      const res = await setFarmLocation(latitude, longitude);
      setFarm(res.farm || { ...(farm || {}), latitude, longitude });
      setLocOpen(false);
    } catch (e) {
      Alert.alert('Could not save', e.message);
    } finally {
      setLocSaving(false);
    }
  };

  /* Save the farm's default lengths; the server rewrites every section that
     uses them, so today's plans change at once rather than at the next dawn. */
  const saveLengths = async () => {
    try {
      setLenSaving(true);
      const res = await setPourDefaults(lenEdit.waterSec, lenEdit.traySec);
      setFarm({ ...(farm || {}), pourDefaults: res.pourDefaults || lenEdit });
      setLenEdit(null);
    } catch (e) {
      Alert.alert('Could not save', e.message);
    } finally {
      setLenSaving(false);
    }
  };

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();

    let alive = true;
    getOverview()
      // {} rather than null once loaded, so "nothing saved" and "still
      // loading" read differently.
      .then((ov) => { if (alive) { setFarm(ov.farm || {}); setFarmErr(false); } })
      .catch(() => { if (alive) setFarmErr(true); });
    return () => { alive = false; };
  }, []);

  const located = hasFarmLocation(farm);
  const mayMove = can('setFarmLocation');

  return (
    <View style={s.screen}>
      <ScreenHeader title="Settings" subtitle="Configuration" navigation={navigation} showBack />

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>

          {/* ── FARM LOCATION ────────────────────────────────────────────
              Which place the outdoor weather forecast is downloaded for. Asked
              during setup, and required since 19 Oct 2026: while it is unset,
              Home and My Farm carry a banner and this row says what it costs. */}
          <Text style={s.sectionLabel}>FARM LOCATION</Text>
          <View style={[s.card, SHADOW.sm]}>
            {/* The coordinates stay readable - they explain which weather
                forecast the models are using. Only moving the pin is admin. */}
            <TouchableOpacity
              style={s.locView}
              disabled={!mayMove || farmErr}
              onPress={mayMove && !farmErr ? () => setLocOpen(true) : undefined}
              activeOpacity={0.7}
              accessibilityRole="button"
              accessibilityLabel="Change where the farm is on the map">
              <Ionicons name={located ? 'location' : 'location-outline'} size={22}
                color={farm && !located && !farmErr ? COLORS.warning : COLORS.primary} />
              <View style={{ flex: 1 }}>
                <Text style={[s.locValue, farm && !located && !farmErr && { color: COLORS.warning }]}>
                  {farmErr ? 'Could not load'
                    : located
                      ? `${Number(farm.latitude).toFixed(4)}, ${Number(farm.longitude).toFixed(4)}`
                      : farm ? 'Not set yet' : 'Loading…'}
                </Text>
                <Text style={s.locSub}>
                  {farmErr ? 'Check the internet connection and open Settings again.'
                    : located || !farm ? 'Used for the weather forecast.'
                      : 'Until it is set, the app uses the weather at Peradeniya.'}
                  {!mayMove && !farmErr ? ' Only the farm’s admin can change it.' : ''}
                </Text>
              </View>
              {locSaving
                ? <ActivityIndicator size="small" color={COLORS.primary} />
                : mayMove && !farmErr
                  ? <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
                  : null}
            </TouchableOpacity>
          </View>

          {/* ── WATERING AND TRAY ──────────────────────────────────────
              How long automatic care waters and fills a tray (19 Oct 2026). The
              models decide WHEN; these say how long, for every section that has
              no length of its own (a section's Pour lengths card overrides
              them). They are also where a hand-pressed Water Now or Fill Tray
              starts, and the farmer can change it there each time. */}
          <Text style={s.sectionLabel}>WATERING AND TRAY</Text>
          <View style={[s.card, SHADOW.sm]}>
            <TouchableOpacity
              style={s.locView}
              disabled={!can('setPourDefaults') || !farm}
              onPress={can('setPourDefaults') && farm ? () => setLenEdit({
                waterSec: farm?.pourDefaults?.waterSec ?? DEFAULT_POUR_SEC,
                traySec: farm?.pourDefaults?.traySec ?? DEFAULT_POUR_SEC,
              }) : undefined}
              activeOpacity={0.7}
              accessibilityRole="button"
              accessibilityLabel="Change the default watering and tray fill lengths">
              <Ionicons name="timer-outline" size={22} color={COLORS.primary} />
              <View style={{ flex: 1 }}>
                <Text style={s.locValue}>
                  Watering {pourLabel(farm?.pourDefaults?.waterSec ?? DEFAULT_POUR_SEC)}
                  {'  ·  '}Tray fill {pourLabel(farm?.pourDefaults?.traySec ?? DEFAULT_POUR_SEC)}
                </Text>
                <Text style={s.locSub}>
                  Used in automatic care for every section without its own lengths, and as
                  the starting length when you water or fill by hand.
                  {!can('setPourDefaults') ? ' Only the farm\u2019s admin can change them.' : ''}
                </Text>
              </View>
              {can('setPourDefaults')
                ? <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
                : null}
            </TouchableOpacity>
          </View>

          {/* ── ACCOUNT ──────────────────────────────────────────────
              Who is signed in, and the two things they can do about it. The
              email is shown because a farm phone gets handed around, and
              "which account am I on" has no other answer in the app. */}
          <Text style={s.sectionLabel}>ACCOUNT</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="person-circle-outline" iconColor={COLORS.primary}
              label="Signed in as" value={authEmail || '--'} />
            {isAdmin && (<>
              <Divider />
              <Row
                icon="people-outline"
                iconColor={COLORS.info}
                label="Team"
                hint="Who can use this farm"
                onPress={() => navigation.navigate('Team')}
                right={<Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />}
              />
            </>)}
            <Divider />
            <Row
              icon="log-out-outline"
              iconColor={COLORS.danger}
              label="Sign out"
              /* Confirmed, because on a farm phone this is a slip that costs
                 somebody their alarms until they remember the password. */
              onPress={() => Alert.alert(
                'Sign out?',
                'You will need your email and password to sign in again, and '
                + 'this phone will stop receiving alarms for the farm.',
                [{ text: 'Stay signed in', style: 'cancel' },
                 { text: 'Sign out', style: 'destructive', onPress: () => signOut() }],
              )}
              right={<Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />}
            />
          </View>

          <Text style={s.sectionLabel}>ABOUT</Text>
          <View style={[s.card, SHADOW.sm]}>
            <Row icon="leaf"                  iconColor={COLORS.primary}   label="System"        value="Smart Orchid Care" />
            <Divider />
            {/* Matches app.json and android/app/build.gradle (1.0.0, 19 Oct 2026). */}
            <Row icon="git-branch-outline"    iconColor={COLORS.textSecondary} label="Version"   value="v1.0.0" />
            <Divider />
            <Row
              icon="document-text-outline"
              iconColor={COLORS.info}
              label="Acknowledgements"
              hint="Libraries & data sources"
              onPress={() => Alert.alert(
                'Acknowledgements',
                'Firebase RTDB · scikit-learn · React Native · Expo · BH1750 library · DHT Adafruit · Christopher Laws'
              )}
              right={<Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />}
            />
          </View>

        </Animated.View>
        <View style={{ height: 40 }} />
      </ScrollView>

      <Sheet visible={!!lenEdit} title="Watering and tray fill"
        subtitle="How long each runs in automatic care"
        onClose={lenSaving ? undefined : () => setLenEdit(null)}
        footer={
          <TouchableOpacity style={s.lenSave} disabled={lenSaving} onPress={saveLengths}
            accessibilityRole="button">
            {lenSaving ? <ActivityIndicator color="#FFF" size="small" />
                       : <Text style={s.lenSaveTxt}>Save</Text>}
          </TouchableOpacity>
        }>
        {lenEdit && (
          <>
            <DurationPicker label="Watering" value={lenEdit.waterSec}
              onChange={(v) => setLenEdit({ ...lenEdit, waterSec: v })} />
            <DurationPicker label="Tray fill" value={lenEdit.traySec}
              onChange={(v) => setLenEdit({ ...lenEdit, traySec: v })} />
          </>
        )}
      </Sheet>

      <LocationPicker
        visible={locOpen}
        initial={farm}
        saving={locSaving}
        onCancel={() => setLocOpen(false)}
        onPick={saveLocation}
      />
    </View>
  );
}

// ─── Styles ────────────────────────────────────────────────────────────────────
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl, paddingTop: SPACE.lg },

  // Section
  locView:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
               paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md + 2 },
  locValue:  { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  locSub:    { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },
  sectionLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 1.5, marginBottom: SPACE.sm, marginLeft: 2, marginTop: 4 },
  card:         { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, overflow: 'hidden', marginBottom: SPACE.xl },
  divider:      { height: 1, backgroundColor: COLORS.borderLight, marginLeft: 56 },

  // Row
  row:      { flexDirection: 'row', alignItems: 'center', paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md + 2, gap: SPACE.md },
  rowIcon:  { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  rowLabel: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  rowHint:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  rowValue: { color: COLORS.textTertiary, fontSize: FONT.sm, maxWidth: 160, textAlign: 'right' },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  lenSave:  { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md + 2,
              borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  lenSaveTxt: { color: '#FFF', fontSize: FONT.md, fontWeight: '800' },
});
