import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const BASE_URL = Platform.OS === 'web' ? 'http://localhost:8000' : 'http://192.168.1.129:8000';

const ZONE_COLORS = ['#4CAF50', '#2196F3', '#FF9800', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722', '#607D8B'];

// A blank survey spot. The grower places the sensor pack here, reads the values, types them in.
const blankSpot = (n) => ({ name: `Spot ${n}`, light: '', temp: '', humidity: '', drying: '' });

export default function DeviceCalculatorScreen({ navigation }) {
  const [spots,   setSpots]   = useState([blankSpot(1), blankSpot(2)]);
  const [plants,  setPlants]  = useState('');
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);

  const addSpot = () => spots.length < 8 && setSpots(prev => [...prev, blankSpot(prev.length + 1)]);
  const removeSpot = (i) => setSpots(prev => prev.filter((_, idx) => idx !== i));
  const setField = (i, key, val) =>
    setSpots(prev => prev.map((s, idx) => idx === i ? { ...s, [key]: val } : s));

  const calculate = async () => {
    // Validate: every spot needs light, temp, humidity at minimum
    const ready = spots.filter(s => s.light !== '' && s.temp !== '' && s.humidity !== '');
    if (ready.length < 2) {
      Alert.alert('Need at least 2 spots', 'Enter light, temperature and humidity for at least two survey spots.');
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const body = {
        spots: ready.map((s, i) => ({
          spot_id: s.name || `S${i + 1}`,
          features: {
            peak_light:    parseFloat(s.light) || 0,
            light_range:   0,
            mean_temp:     parseFloat(s.temp) || 0,
            mean_humidity: parseFloat(s.humidity) || 0,
            drying_rate:   parseFloat(s.drying) || 0,
          },
        })),
        plant_count: parseInt(plants) || null,
      };
      const res  = await fetch(`${BASE_URL}/api/v1/farm/zone-analyze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setResult(await res.json());
    } catch (err) {
      Alert.alert('Calculation failed', `${err.message}\n\nIs the backend running?`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Sensor Device Calculator" subtitle="How many devices does this house need?" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        <View style={[styles.infoBox, SHADOW.sm]}>
          <Ionicons name="bulb-outline" size={16} color={COLORS.info} />
          <Text style={styles.infoText}>
            Place the sensor pack at a few spots in the house, a bright edge, a shaded corner, the
            centre, near a wall/opening, and type each spot's readings. The app groups spots with
            similar conditions into microclimate zones. You need <Text style={styles.bold}>one device
            per zone</Text>, so plants in a different microclimate never get the wrong watering.
          </Text>
        </View>

        {/* Survey spots */}
        <View style={styles.sectionRow}>
          <Text style={styles.sectionTitle}>Survey Spots</Text>
          {spots.length < 8 && (
            <TouchableOpacity onPress={addSpot} style={styles.addBtn}>
              <Ionicons name="add-circle-outline" size={18} color={COLORS.primary} />
              <Text style={styles.addText}>Add spot</Text>
            </TouchableOpacity>
          )}
        </View>

        {spots.map((s, i) => (
          <View key={i} style={[styles.spotCard, SHADOW.sm]}>
            <View style={styles.spotHeader}>
              <View style={[styles.spotDot, { backgroundColor: ZONE_COLORS[i % ZONE_COLORS.length] }]} />
              <TextInput
                style={styles.spotName}
                value={s.name}
                onChangeText={(v) => setField(i, 'name', v)}
                placeholder={`Spot ${i + 1}`}
                placeholderTextColor={COLORS.textTertiary}
              />
              {spots.length > 2 && (
                <TouchableOpacity onPress={() => removeSpot(i)}>
                  <Ionicons name="close-circle-outline" size={20} color={COLORS.textTertiary} />
                </TouchableOpacity>
              )}
            </View>
            <View style={styles.fieldRow}>
              {[
                ['Light', 'lux', 'light'],
                ['Temp', '°C', 'temp'],
                ['Humidity', '%', 'humidity'],
                ['Drying', '%/h', 'drying'],
              ].map(([label, unit, key]) => (
                <View key={key} style={styles.field}>
                  <Text style={styles.fieldLabel}>{label}</Text>
                  <TextInput
                    style={styles.fieldInput}
                    value={s[key]}
                    onChangeText={(v) => setField(i, key, v)}
                    keyboardType="decimal-pad"
                    placeholder="0"
                    placeholderTextColor={COLORS.textTertiary}
                  />
                  <Text style={styles.fieldUnit}>{unit}</Text>
                </View>
              ))}
            </View>
          </View>
        ))}

        <Text style={styles.hint}>
          Drying = root-moisture % lost per hour (optional). Leave 0 if unknown, light, temp and
          humidity already separate most microclimates.
        </Text>

        {/* Plant count (optional) */}
        <View style={[styles.plantRow, SHADOW.sm]}>
          <Ionicons name="leaf-outline" size={18} color="#6fae3d" />
          <Text style={styles.plantLabel}>Plants in this house (optional)</Text>
          <TextInput
            style={styles.plantInput}
            value={plants}
            onChangeText={setPlants}
            keyboardType="number-pad"
            placeholder="-"
            placeholderTextColor={COLORS.textTertiary}
          />
        </View>

        <TouchableOpacity
          style={[styles.calcBtn, SHADOW.md, loading && { opacity: 0.6 }]}
          onPress={calculate}
          disabled={loading}
          activeOpacity={0.85}
        >
          {loading
            ? <ActivityIndicator color="#FFF" size="small" />
            : <Ionicons name="calculator-outline" size={20} color="#FFF" />}
          <Text style={styles.calcBtnText}>{loading ? 'Calculating…' : 'Calculate Devices Needed'}</Text>
        </TouchableOpacity>

        {/* Result */}
        {result && (
          <>
            <View style={[styles.resultBanner, SHADOW.md]}>
              <Text style={styles.resultNum}>{result.device_count}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.resultTitle}>
                  sensor device{result.device_count !== 1 ? 's' : ''} needed
                </Text>
                <Text style={styles.resultSub}>
                  {result.surveyed_spots} spot{result.surveyed_spots !== 1 ? 's' : ''} → {result.device_count} microclimate zone{result.device_count !== 1 ? 's' : ''}
                  {result.plants_per_device ? ` · ~${result.plants_per_device} plants/device` : ''}
                </Text>
              </View>
            </View>

            <Text style={styles.sectionTitle}>Zones (one device each)</Text>
            {result.zones?.map((z) => (
              <View key={z.zone_id} style={[styles.zoneCard, SHADOW.sm]}>
                <View style={[styles.zoneTag, { backgroundColor: ZONE_COLORS[z.zone_id % ZONE_COLORS.length] }]}>
                  <Text style={styles.zoneTagText}>Z{z.zone_id + 1}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.zoneSpots}>{z.spot_ids.join(', ')}</Text>
                  <Text style={styles.zoneMeta}>
                    Light {z.mean.peak_light} lux · {z.mean.mean_temp}°C · {z.mean.mean_humidity}% RH
                  </Text>
                  <Text style={styles.zonePlace}>📍 Place device at: {z.representative.spot_id}</Text>
                </View>
              </View>
            ))}

            <View style={[styles.noteBox, SHADOW.sm]}>
              <Ionicons name="information-circle-outline" size={15} color={COLORS.info} />
              <Text style={styles.noteText}>{result.reasoning}</Text>
            </View>
          </>
        )}

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: COLORS.bg },
  scroll:       { padding: SPACE.xl },
  bold:         { fontWeight: '800', color: COLORS.text },

  infoBox:  { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start', backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl },
  infoText: { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 18 },

  sectionRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.sm },
  addBtn:       { flexDirection: 'row', alignItems: 'center', gap: 4 },
  addText:      { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },

  spotCard:   { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  spotHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.md },
  spotDot:    { width: 12, height: 12, borderRadius: 6 },
  spotName:   { flex: 1, color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', padding: 0 },

  fieldRow:   { flexDirection: 'row', gap: SPACE.sm },
  field:      { flex: 1, alignItems: 'center' },
  fieldLabel: { color: COLORS.textTertiary, fontSize: 9, fontWeight: '600', marginBottom: 3, textTransform: 'uppercase' },
  fieldInput: { width: '100%', backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm - 2, paddingVertical: SPACE.sm, color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', textAlign: 'center' },
  fieldUnit:  { color: COLORS.textTertiary, fontSize: 9, marginTop: 2 },

  hint: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.sm, marginBottom: SPACE.lg },

  plantRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.lg },
  plantLabel: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm },
  plantInput: { width: 70, backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm - 2, padding: SPACE.sm, color: COLORS.text, fontSize: FONT.md, fontWeight: '700', textAlign: 'center' },

  calcBtn:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  calcBtnText: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },

  resultBanner: { flexDirection: 'row', alignItems: 'center', gap: SPACE.lg, backgroundColor: COLORS.primary, borderRadius: RADIUS.md, padding: SPACE.lg, marginBottom: SPACE.xl },
  resultNum:    { color: '#FFF', fontSize: 44, fontWeight: '800', fontVariant: ['tabular-nums'] },
  resultTitle:  { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  resultSub:    { color: 'rgba(255,255,255,0.8)', fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },

  zoneCard:    { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  zoneTag:     { width: 40, height: 40, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  zoneTagText: { color: '#FFF', fontWeight: '800', fontSize: FONT.sm },
  zoneSpots:   { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  zoneMeta:    { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  zonePlace:   { color: COLORS.primary, fontSize: FONT.xs, marginTop: 2, fontWeight: '600' },

  noteBox:  { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start', backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginTop: SPACE.md },
  noteText: { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 16 },
});
