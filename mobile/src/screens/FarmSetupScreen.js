import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { setupFarm, addHouse, addSection, assignDevice, getOverview } from '../services/careV2';
import LocationPicker from '../components/LocationPicker';
import NodePicker from '../components/NodePicker';

const HOUSE_TYPES = ['shade-net', 'shade-cloth', 'poly-tunnel', 'double-shade'];
const STAGES      = ['Active', 'Flowering', 'Dormant'];
const EXPOSURES   = [
  { v: 1.0,  label: 'Very bright' },
  { v: 0.75, label: 'Bright' },
  { v: 0.5,  label: 'Part shade' },
  { v: 0.3,  label: 'Deep shade' },
];

/* The name starts EMPTY, not pre-filled with "Section 1".
   A pre-filled value invites the farmer to clear it and type their own, and
   anything left half-typed used to be saved silently as "Section". An empty
   field with a placeholder shows exactly what will be saved. */
const newSection = () => ({
  name: '', label: '', plantCount: '', growthStage: 'Active', lightExposure: 0.75,
});

export default function FarmSetupScreen({ route, navigation }) {
  const addToHouse = route.params?.addToHouse;      // set => "add section" mode

  const [houseName,setHouseName]= useState('');
  const [houseType,setHouseType]= useState('shade-net');
  const [sections, setSections] = useState([newSection(), newSection()]);
  const [saving,   setSaving]   = useState(false);
  /* Where the farm is. Asked once, here, because it decides which place the
     weather forecast is downloaded for - and that forecast feeds every watering
     decision. Before this the question was never asked and every farm silently
     used the coordinates the models were trained at. */
  const [loc,      setLoc]      = useState(null);   // { latitude, longitude }
  const [locOpen,  setLocOpen]  = useState(false);

  // Set once a section has been created and we are on the "link a node" step.
  const [linkFor, setLinkFor] = useState(null);   // { house, section, name }
  const [linking, setLinking] = useState(false);

  /* Binding a node to the section just created.
     A 409 is the backend's one-to-one rule refusing the change, not a failure -
     it means the board is already claimed elsewhere. The farmer is offered the
     move rather than shown an error, because wanting to move a node between
     zones is a normal thing to do. */
  const linkNode = async (device, force = false) => {
    setLinking(true);
    try {
      await assignDevice(device.mac, linkFor.house, linkFor.section, force);
      Alert.alert(
        'Node linked',
        `Node ${device.shortId} now reports for ${linkFor.name}.\n\n` +
        'It picks this up within about 15 seconds.',
        [{ text: 'OK', onPress: () => navigation.goBack() }]);
    } catch (e) {
      if (e.status === 409 && !force) {
        Alert.alert('Already linked', e.message, [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Move it here', style: 'destructive',
            onPress: () => linkNode(device, true) },
        ]);
      } else {
        Alert.alert('Could not link', e.message);
      }
    } finally { setLinking(false); }
  };

  const setSec = (i, k, v) => setSections(p => p.map((s, j) => j === i ? { ...s, [k]: v } : s));
  const addSec = () => sections.length < 8 && setSections(p => [...p, newSection()]);
  const delSec = (i) => sections.length > 1 && setSections(p => p.filter((_, j) => j !== i));

  const payloadSections = () => sections.map(s => ({
    name: s.name.trim(),          // validated before we get here - never substituted
    label: s.label.trim(),
    plantCount: parseInt(s.plantCount) || 0,
    growthStage: s.growthStage,
    lightExposure: s.lightExposure,
  }));

  const save = async () => {
    // A section with no name is a mistake, not a default. Say so.
    const visible = addToHouse ? sections.slice(0, 1) : sections;
    const blank = visible.findIndex(s => !s.name.trim());
    if (blank >= 0) {
      Alert.alert('Name needed',
        visible.length > 1
          ? `Please give section ${blank + 1} a name.`
          : 'Please give this section a name.');
      return;
    }

    if (addToHouse) {
      const s = payloadSections()[0];
      setSaving(true);
      try {
        const r = await addSection(addToHouse, s);
        // The section exists now. Linking hardware is the next step rather than
        // part of the same write: a section with no node yet is a valid state,
        // so creation must never depend on a board being powered on.
        const sectionId = r.sectionId || r.id || r.deviceId;
        setLinkFor({ house: addToHouse, section: sectionId, name: s.name });
      } catch (e) { Alert.alert('Failed', e.message); }
      finally { setSaving(false); }
      return;
    }

    if (!houseName.trim()) { Alert.alert('Enter a house name'); return; }
    setSaving(true);
    try {
      const house = {
        name: houseName.trim(), type: houseType,
        plantCount: payloadSections().reduce((n, s) => n + s.plantCount, 0),
        sections: payloadSections(),
      };
      /* Which call to make used to be decided by whether the farmer had typed a
         farm name, which is a strange thing to hang it on and stopped working
         the moment that field was removed. Ask the server instead: no houses
         means this is the first run. */
      let firstRun = true;
      try {
        const ov = await getOverview();
        firstRun = !(ov.houses || []).length;
      } catch (_) { /* unreachable backend: setupFarm is the safe assumption */ }

      if (firstRun) await setupFarm({ houses: [house], ...(loc || {}) });
      else          await addHouse(house);
      Alert.alert('Saved', `${house.name} created with ${house.sections.length} sections.\n\nFlash each device with its ID (shown on the dashboard).`,
        [{ text: 'OK', onPress: () => navigation.goBack() }]);
    } catch (e) { Alert.alert('Failed', e.message); }
    finally { setSaving(false); }
  };

  /* Step 2 of adding a section: the section already exists, so this screen now
     only decides which physical node reports for it. Skipping leaves the section
     showing "No device" until hardware is available, which is a supported state
     rather than an incomplete one. */
  if (linkFor) {
    return (
      <View style={styles.container}>
        <ScreenHeader
          title="Link a node"
          subtitle={`for ${linkFor.name}`}
          navigation={navigation} />
        {linking
          ? <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
              <ActivityIndicator color={COLORS.primary} />
              <Text style={{ marginTop: 10, color: COLORS.textSecondary }}>Linking…</Text>
            </View>
          : <NodePicker
              onSelect={(d) => linkNode(d, false)}
              onSkip={() => {
                Alert.alert(
                  'Section created',
                  `${linkFor.name} was created without a node and will show "No device".\n\n` +
                  'You can link one from the section any time.',
                  [{ text: 'OK', onPress: () => navigation.goBack() }]);
              }} />}
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScreenHeader
        title={addToHouse ? 'Add Section' : 'Set Up Farm'}
        subtitle={addToHouse ? `to ${addToHouse}` : 'Farm → houses → sections'}
        navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        <View style={[styles.info, SHADOW.sm]}>
          <Ionicons name="information-circle-outline" size={16} color={COLORS.info} />
          <Text style={styles.infoText}>
            A <Text style={styles.b}>section</Text> is one area of a house that has its own
            conditions, a sunny edge, a shaded corner. Each section gets <Text style={styles.b}>one
            sensor device</Text> and its own humidity tray. You can add more any time.
          </Text>
        </View>

        {!addToHouse && (
          <>
            {/* The farm name and owner used to be asked for here, before a
                farmer could do anything else. Neither earned it: the owner name
                was written to Firebase and read by NOTHING, and the farm name is
                only a screen title that already falls back to "My Farm". It can
                still be set later from the dashboard, by anyone who wants one. */}
            <Text style={styles.h}>Greenhouse</Text>
            <View style={[styles.card, SHADOW.sm]}>
              <Field label="House name" value={houseName} onChange={setHouseName} placeholder="e.g. House 1, Main Vanda" />
              <Text style={styles.lbl}>Type</Text>
              <View style={styles.chips}>
                {HOUSE_TYPES.map(t => (
                  <TouchableOpacity key={t} onPress={() => setHouseType(t)}
                    style={[styles.chip, houseType === t && styles.chipOn]}>
                    <Text style={[styles.chipTxt, houseType === t && styles.chipTxtOn]}>{t}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* Asked once, at setup. It decides which place the weather forecast
                is downloaded for, and that forecast feeds every watering time.
                A map, not two number fields: nobody knows their coordinates. */}
            <Text style={styles.h}>Where is it?</Text>
            <View style={[styles.card, SHADOW.sm]}>
              <TouchableOpacity style={styles.locRow} onPress={() => setLocOpen(true)}
                activeOpacity={0.7} accessibilityRole="button"
                accessibilityLabel="Choose the farm location on a map">
                <Ionicons name={loc ? 'location' : 'map-outline'} size={22}
                  color={loc ? COLORS.primary : COLORS.textTertiary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.locTitle}>
                    {loc ? `${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)}` : 'Choose on the map'}
                  </Text>
                  <Text style={styles.locSub}>
                    {loc ? 'Weather forecasts will be downloaded for this position.'
                         : 'Search your town or tap the map. Used for the weather forecast.'}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
              </TouchableOpacity>
            </View>
          </>
        )}

        <View style={styles.hRow}>
          <Text style={styles.h}>{addToHouse ? 'New Section' : 'Sections'}</Text>
          {!addToHouse && sections.length < 8 && (
            <TouchableOpacity onPress={addSec} style={styles.addBtn}>
              <Ionicons name="add-circle-outline" size={18} color={COLORS.primary} />
              <Text style={styles.addTxt}>Add</Text>
            </TouchableOpacity>
          )}
        </View>

        {(addToHouse ? sections.slice(0, 1) : sections).map((s, i) => (
          <View key={i} style={[styles.card, SHADOW.sm, { marginBottom: SPACE.md }]}>
            <View style={styles.secHead}>
              <View style={styles.secNum}><Text style={styles.secNumTxt}>{i + 1}</Text></View>
              <Text style={styles.secHeadTxt}>Section {i + 1}</Text>
              {!addToHouse && sections.length > 1 && (
                <TouchableOpacity onPress={() => delSec(i)}>
                  <Ionicons name="close-circle-outline" size={20} color={COLORS.textTertiary} />
                </TouchableOpacity>
              )}
            </View>

            {/* The name used to sit unstyled inside the header row, where it read
                as a heading rather than something you could type into. It is a
                normal labelled field now, and the first one on the card. */}
            <Field label="Name this section" value={s.name}
              onChange={v => setSec(i, 'name', v)} placeholder="e.g. East Corner" />
            <Field label="Describe it (helps you remember)" value={s.label}
              onChange={v => setSec(i, 'label', v)} placeholder="e.g. bright south edge" />
            <Field label="Plants in this section" value={s.plantCount}
              onChange={v => setSec(i, 'plantCount', v)} placeholder="0" numeric />

            <Text style={styles.lbl}>How much light does it get?</Text>
            <View style={styles.chips}>
              {EXPOSURES.map(e => (
                <TouchableOpacity key={e.v} onPress={() => setSec(i, 'lightExposure', e.v)}
                  style={[styles.chip, s.lightExposure === e.v && styles.chipOn]}>
                  <Text style={[styles.chipTxt, s.lightExposure === e.v && styles.chipTxtOn]}>{e.label}</Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.lbl}>Growth stage</Text>
            <View style={styles.chips}>
              {STAGES.map(g => (
                <TouchableOpacity key={g} onPress={() => setSec(i, 'growthStage', g)}
                  style={[styles.chip, s.growthStage === g && styles.chipOn]}>
                  <Text style={[styles.chipTxt, s.growthStage === g && styles.chipTxtOn]}>{g}</Text>
                </TouchableOpacity>
              ))}
            </View>
            {s.growthStage === 'Dormant' && (
              <Text style={styles.warn}>Dormant plants are never fertilized, the system enforces this.</Text>
            )}
          </View>
        ))}

        <TouchableOpacity style={[styles.save, SHADOW.md, saving && { opacity: 0.6 }]}
          onPress={save} disabled={saving} activeOpacity={0.85}>
          {saving ? <ActivityIndicator color="#FFF" size="small" />
                  : <Ionicons name="checkmark-circle-outline" size={20} color="#FFF" />}
          <Text style={styles.saveTxt}>{saving ? 'Saving…' : addToHouse ? 'Add Section' : 'Save Farm Setup'}</Text>
        </TouchableOpacity>

        <View style={{ height: 100 }} />
      </ScrollView>

      <LocationPicker
        visible={locOpen}
        initial={loc ? { latitude: loc.latitude, longitude: loc.longitude } : null}
        onCancel={() => setLocOpen(false)}
        onPick={(p) => { setLoc(p); setLocOpen(false); }}
      />
    </View>
  );
}

function Field({ label, value, onChange, placeholder, numeric }) {
  return (
    <View style={{ marginBottom: SPACE.md }}>
      <Text style={styles.lbl}>{label}</Text>
      <TextInput style={styles.input} value={value} onChangeText={onChange}
        placeholder={placeholder} placeholderTextColor={COLORS.textTertiary}
        keyboardType={numeric ? 'number-pad' : 'default'} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.xl },
  b:         { fontWeight: '800', color: COLORS.text },

  info:     { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start', backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl },
  infoText: { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 18 },

  h:    { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 4, marginTop: SPACE.sm },
  hint: { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: SPACE.md },
  hRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md, marginTop: SPACE.lg },
  addBtn:{ flexDirection: 'row', alignItems: 'center', gap: 4 },
  addTxt:{ color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },

  card:  { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.lg },
  lbl:   { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '600', marginBottom: 5 },
  input: { backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm - 2, padding: SPACE.md, color: COLORS.text, fontSize: FONT.sm },

  locRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  locTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  locSub:   { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },
  chips:    { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: SPACE.md },
  chip:     { paddingHorizontal: 11, paddingVertical: 6, borderRadius: RADIUS.full, backgroundColor: COLORS.bgInput },
  chipOn:   { backgroundColor: COLORS.primary },
  chipTxt:  { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '600' },
  chipTxtOn:{ color: '#FFF' },

  secHead:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.md },
  secNum:   { width: 26, height: 26, borderRadius: 13, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  secNumTxt:{ color: '#FFF', fontSize: FONT.xs, fontWeight: '800' },
  secHeadTxt: { flex: 1, color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },

  warn: { color: COLORS.warning, fontSize: FONT.xs, marginTop: -SPACE.sm, lineHeight: 16 },

  save:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.md },
  saveTxt: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
});
