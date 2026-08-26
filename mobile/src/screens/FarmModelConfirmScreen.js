import React, { useState, useEffect, useMemo } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Platform,
} from 'react-native';
import { WebView } from 'react-native-webview';
import * as ImagePicker from 'expo-image-picker';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { buildGreenhouseHTML } from '../utils/greenhouse3d';

import BASE_URL from '../config/backend';

const WALLS = ['north', 'south', 'east', 'west'];
const WALL_COLOR = { north: COLORS.info, south: COLORS.warning, east: COLORS.primary, west: COLORS.fertilizer };

export default function FarmModelConfirmScreen({ route, navigation }) {
  const { sessionId } = route.params;

  const [summary,  setSummary]  = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [saving,   setSaving]   = useState(false);

  const [width,        setWidth]       = useState('10');
  const [length,       setLength]      = useState('20');
  const [height,       setHeight]      = useState('3');
  const [zones,        setZones]       = useState('4');
  const [duration,     setDuration]    = useState('24');
  const [windows,      setWindows]     = useState([
    { wall: 'south', position: 0.5, width: 2.0 },
  ]);
  const [plantRows,    setPlantRows]   = useState('5');
  const [plantsPerRow, setPlantsPerRow] = useState('10');

  const [detectedPlants, setDetectedPlants] = useState(null);   // array | null
  const [detectInfo,     setDetectInfo]     = useState(null);   // {count, avg_health, green_cover}
  const [detecting,      setDetecting]      = useState(false);

  useEffect(() => {
    fetch(`${BASE_URL}/api/v1/farm/scan-summary/${sessionId}`)
      .then(r => r.json())
      .then(data => {
        setSummary(data);
        // Pre-fill rough estimates from aspect hint
        if (data.aspect_hint && data.aspect_hint > 0) {
          const w = parseFloat(width);
          setLength(String(Math.round(w / data.aspect_hint * 10) / 10));
        }
        // Pre-fill windows from detected openings
        if (data.est_openings > 0) {
          const wins = [];
          for (let i = 0; i < Math.min(data.est_openings, 3); i++) {
            wins.push({ wall: WALLS[i % 4], position: 0.5, width: 1.5 });
          }
          setWindows(wins);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const addWindow = () => {
    if (windows.length >= 4) return;
    setWindows(prev => [...prev, { wall: 'north', position: 0.5, width: 1.5 }]);
  };

  const cycleWall = (idx) =>
    setWindows(prev => prev.map((w, i) =>
      i !== idx ? w : { ...w, wall: WALLS[(WALLS.indexOf(w.wall) + 1) % 4] }
    ));

  const removeWindow = (idx) => setWindows(prev => prev.filter((_, i) => i !== idx));

  // Detect plants from a photo (camera or gallery)
  const runDetection = async (source) => {
    try {
      let res;
      if (source === 'camera') {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) { Alert.alert('Camera permission needed'); return; }
        res = await ImagePicker.launchCameraAsync({ quality: 0.6 });
      } else {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) { Alert.alert('Photo library permission needed'); return; }
        res = await ImagePicker.launchImageLibraryAsync({ quality: 0.6 });
      }
      if (res.canceled) return;

      setDetecting(true);
      const asset = res.assets[0];
      const form  = new FormData();
      form.append('file', { uri: asset.uri, name: 'plants.jpg', type: 'image/jpeg' });
      form.append('width',  width);
      form.append('length', length);

      const r = await fetch(`${BASE_URL}/api/v1/farm/detect-plants/${sessionId}`, { method: 'POST', body: form });
      if (!r.ok) throw new Error(`Server error ${r.status}`);
      const data = await r.json();

      if (data.count > 0) {
        setDetectedPlants(data.plants);
        setDetectInfo({ count: data.count, avg_health: data.avg_health, green_cover: data.green_cover });
      } else {
        Alert.alert('No plants detected', 'Try a clearer top-down overview photo of the plant area, in good light.');
      }
    } catch (err) {
      Alert.alert('Detection failed', `${err.message}\n\nIs the backend running?`);
    } finally {
      setDetecting(false);
    }
  };

  const detectPlants = () => Alert.alert(
    'Detect plants from photo',
    'Use a top-down overview shot of the plant area for best results.',
    [
      { text: 'Take Photo',          onPress: () => runDetection('camera') },
      { text: 'Choose from Gallery', onPress: () => runDetection('gallery') },
      { text: 'Cancel', style: 'cancel' },
    ]
  );

  const clearDetection = () => { setDetectedPlants(null); setDetectInfo(null); };

  // Live 3D preview â€” rebuilt only when the parsed numbers actually change
  const previewHtml = useMemo(() => {
    const w = parseFloat(width), l = parseFloat(length), h = parseFloat(height);
    if (!w || !l || !h) return null;
    const plants = [];
    if (detectedPlants && detectedPlants.length) {
      detectedPlants.forEach(p => plants.push({ x: p.x, y: p.y }));   // real detected positions
    } else {
      const rows = parseInt(plantRows) || 0;
      const ppr  = parseInt(plantsPerRow) || 0;
      if (rows > 0 && ppr > 0) {
        const rowSp = l / (rows + 1), colSp = w / (ppr + 1);
        for (let r = 1; r <= rows; r++)
          for (let p = 1; p <= ppr; p++)
            plants.push({ x: +(p * colSp).toFixed(2), y: +(r * rowSp).toFixed(2) });
      }
    }
    return buildGreenhouseHTML({
      model: { width: w, length: l, height: h, windows },
      plants,
      markers: [],
      legend: [],
      showDimensions: true,
    });
  }, [width, length, height, plantRows, plantsPerRow, windows, detectedPlants]);

  const confirm = async () => {
    const w = parseFloat(width), l = parseFloat(length), h = parseFloat(height);
    if (!w || !l || !h) { Alert.alert('Enter all dimensions'); return; }

    setSaving(true);
    try {
      const form = new FormData();
      form.append('session_id',           sessionId);
      form.append('width',                String(w));
      form.append('length',               String(l));
      form.append('height',               String(h));
      form.append('target_zones',         String(parseInt(zones) || 4));
      form.append('trial_duration_hours', String(parseInt(duration) || 24));
      form.append('windows',              JSON.stringify(windows));
      form.append('plant_rows',           String(parseInt(plantRows)    || 5));
      form.append('plants_per_row',       String(parseInt(plantsPerRow) || 10));
      if (detectedPlants && detectedPlants.length) {
        form.append('detected_positions', JSON.stringify(detectedPlants));
      }

      const res  = await fetch(`${BASE_URL}/api/v1/farm/confirm-model`, { method: 'POST', body: form });
      const data = await res.json();

      navigation.replace('FarmTrial', {
        sessionId,
        trialPositions:   data.trial_positions,
        model:            data.model,
        hoursPerPosition: data.hours_per_position,
        instruction:      data.instruction,
      });
    } catch (err) {
      Alert.alert('Failed to confirm model', err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={[styles.container, { alignItems: 'center', justifyContent: 'center' }]}>
        <ActivityIndicator size="large" color={COLORS.primary} />
        <Text style={styles.loadingText}>Analysing your photosâ€¦</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <ScreenHeader title="Confirm Farm Model" subtitle="Step 2 of 4 â€” Dimensions" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        {/* Scan summary */}
        {summary && (
          <View style={[styles.summaryCard, SHADOW.sm]}>
            <Ionicons name="camera-outline" size={20} color={COLORS.info} />
            <View style={{ flex: 1 }}>
              <Text style={styles.summaryTitle}>
                {summary.photos_captured} photo{summary.photos_captured !== 1 ? 's' : ''} analysed
                {' Â· '}{summary.quality_ok} good
              </Text>
              <Text style={styles.summaryNote}>{summary.note}</Text>
              {summary.est_openings > 0 && (
                <Text style={styles.summaryDetect}>
                  Detected ~{summary.est_openings} window/opening(s) â€” adjust below if needed
                </Text>
              )}
            </View>
          </View>
        )}

        {/* Dimensions */}
        <Text style={styles.sectionTitle}>Greenhouse Dimensions</Text>
        <Text style={styles.sectionHint}>Use a tape measure or count your steps (1 step â‰ˆ 0.75 m)</Text>
        <View style={[styles.card, SHADOW.sm]}>
          {[
            ['Width (m)',  'eastâ€“west distance',  width,  setWidth],
            ['Length (m)', 'northâ€“south distance', length, setLength],
            ['Height (m)', 'floor to wall top (eave)', height, setHeight],
          ].map(([label, hint, val, set]) => (
            <View key={label} style={styles.dimRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.dimLabel}>{label}</Text>
                <Text style={styles.dimHint}>{hint}</Text>
              </View>
              <TextInput
                style={styles.dimInput}
                value={val}
                onChangeText={set}
                keyboardType="decimal-pad"
                placeholder="0"
                placeholderTextColor={COLORS.textTertiary}
              />
            </View>
          ))}
        </View>

        {/* Live 3D preview */}
        {previewHtml && (
          <>
            <Text style={styles.sectionTitle}>3D Model Preview</Text>
            <Text style={styles.sectionHint}>Updates live as you change the measurements above</Text>
            <View style={[styles.previewBox, SHADOW.md]}>
              <WebView
                key={`${Math.round(parseFloat(width)||0)}-${Math.round(parseFloat(length)||0)}-${Math.round(parseFloat(height)||0)}-${plantRows}-${plantsPerRow}-${windows.length}-${detectedPlants ? detectedPlants.length : 0}`}
                source={{ html: previewHtml }}
                style={styles.previewWeb}
                scrollEnabled={false}
                javaScriptEnabled
                originWhitelist={['*']}
              />
            </View>
          </>
        )}

        {/* Zones & duration */}
        <Text style={styles.sectionTitle}>Trial Settings</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <View style={styles.dimRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.dimLabel}>Sensor Zones</Text>
              <Text style={styles.dimHint}>How many sensor positions to trial</Text>
            </View>
            <View style={styles.stepRow}>
              <TouchableOpacity onPress={() => setZones(v => String(Math.max(2, parseInt(v||2)-1)))} style={styles.stepBtn}>
                <Ionicons name="remove" size={18} color={COLORS.primary} />
              </TouchableOpacity>
              <Text style={styles.stepVal}>{zones}</Text>
              <TouchableOpacity onPress={() => setZones(v => String(Math.min(8, parseInt(v||2)+1)))} style={styles.stepBtn}>
                <Ionicons name="add" size={18} color={COLORS.primary} />
              </TouchableOpacity>
            </View>
          </View>

          <View style={[styles.dimRow, { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACE.md }]}>
            <View style={{ flex: 1 }}>
              <Text style={styles.dimLabel}>Trial Duration</Text>
              <Text style={styles.dimHint}>Total hours to collect data across all positions</Text>
            </View>
            <View style={styles.durationRow}>
              {['12', '24', '48'].map(h => (
                <TouchableOpacity key={h} onPress={() => setDuration(h)}
                  style={[styles.durationChip, duration === h && styles.durationChipActive]}>
                  <Text style={[styles.durationText, duration === h && styles.durationTextActive]}>{h}h</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </View>

        {/* Windows */}
        <View style={styles.sectionRow}>
          <Text style={styles.sectionTitle}>Windows / Openings</Text>
          {windows.length < 4 && (
            <TouchableOpacity onPress={addWindow} style={styles.addBtn}>
              <Ionicons name="add-circle-outline" size={18} color={COLORS.primary} />
              <Text style={styles.addText}>Add</Text>
            </TouchableOpacity>
          )}
        </View>
        {windows.map((win, idx) => (
          <View key={idx} style={[styles.windowRow, SHADOW.sm]}>
            <TouchableOpacity onPress={() => cycleWall(idx)}
              style={[styles.wallChip, { backgroundColor: `${WALL_COLOR[win.wall]}18` }]}>
              <Text style={[styles.wallText, { color: WALL_COLOR[win.wall] }]}>
                {win.wall.toUpperCase()}
              </Text>
            </TouchableOpacity>
            <Text style={styles.windowLabel}>
              Position: {win.position === 0.25 ? 'Left' : win.position === 0.75 ? 'Right' : 'Centre'}
            </Text>
            <TouchableOpacity onPress={() => removeWindow(idx)}>
              <Ionicons name="close-circle-outline" size={22} color={COLORS.textTertiary} />
            </TouchableOpacity>
          </View>
        ))}

        {/* Detect plants from photo */}
        <Text style={styles.sectionTitle}>Plant Detection</Text>
        <Text style={styles.sectionHint}>Optional, auto-detect real plant positions from a photo</Text>

        {detectInfo ? (
          <View style={[styles.detectCard, SHADOW.sm]}>
            <View style={styles.detectRow}>
              <View style={styles.detectStat}>
                <Ionicons name="leaf" size={18} color="#6fae3d" />
                <Text style={styles.detectVal}>{detectInfo.count}</Text>
                <Text style={styles.detectLabel}>Plants found</Text>
              </View>
              <View style={styles.detectDivider} />
              <View style={styles.detectStat}>
                <Ionicons name="heart" size={18} color={detectInfo.avg_health >= 0.6 ? COLORS.success : COLORS.warning} />
                <Text style={styles.detectVal}>{Math.round(detectInfo.avg_health * 100)}%</Text>
                <Text style={styles.detectLabel}>Avg health</Text>
              </View>
              <View style={styles.detectDivider} />
              <View style={styles.detectStat}>
                <Ionicons name="color-fill" size={18} color={COLORS.info} />
                <Text style={styles.detectVal}>{Math.round(detectInfo.green_cover * 100)}%</Text>
                <Text style={styles.detectLabel}>Green cover</Text>
              </View>
            </View>
            <Text style={styles.detectNote}>
              Real plant positions are now used in the 3D model and sensor calculation.
            </Text>
            <View style={styles.detectActions}>
              <TouchableOpacity onPress={detectPlants} style={styles.detectMini} disabled={detecting}>
                <Ionicons name="camera-reverse-outline" size={15} color={COLORS.primary} />
                <Text style={styles.detectMiniText}>Re-detect</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={clearDetection} style={styles.detectMini}>
                <Ionicons name="close-outline" size={15} color={COLORS.textTertiary} />
                <Text style={[styles.detectMiniText, { color: COLORS.textTertiary }]}>Use manual layout</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <TouchableOpacity
            style={[styles.detectBtn, SHADOW.sm, detecting && { opacity: 0.6 }]}
            onPress={detectPlants}
            disabled={detecting}
            activeOpacity={0.85}
          >
            {detecting
              ? <ActivityIndicator color={COLORS.primary} size="small" />
              : <Ionicons name="scan-outline" size={20} color={COLORS.primary} />}
            <View style={{ flex: 1 }}>
              <Text style={styles.detectBtnTitle}>{detecting ? 'Detecting plants…' : 'Detect Plants from Photo'}</Text>
              <Text style={styles.detectBtnSub}>Take a top-down overview shot of your plants</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
          </TouchableOpacity>
        )}

        {/* Plant Layout */}
        {(() => {
          const w = parseFloat(width) || 10;
          const l = parseFloat(length) || 20;
          const usingDetected = !!(detectedPlants && detectedPlants.length);
          const rows = parseInt(plantRows) || 5;
          const ppr  = parseInt(plantsPerRow) || 10;
          const total = usingDetected ? detectedPlants.length : rows * ppr;
          const byPlants = Math.ceil(total / 22);
          const byArea   = Math.ceil((w * l) / 20);
          const recSensors = Math.max(byPlants, byArea, 1);
          return (
            <>
              <Text style={styles.sectionTitle}>Plant Layout</Text>
              <Text style={styles.sectionHint}>
                {usingDetected
                  ? 'Using real plant count detected from your photo'
                  : 'Used to calculate how many IoT sensor units you need'}
              </Text>
              {!usingDetected && (
              <View style={[styles.card, SHADOW.sm]}>
                <View style={styles.dimRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.dimLabel}>Plant Rows</Text>
                    <Text style={styles.dimHint}>Number of rows in the greenhouse</Text>
                  </View>
                  <View style={styles.stepRow}>
                    <TouchableOpacity onPress={() => setPlantRows(v => String(Math.max(1, parseInt(v||1)-1)))} style={styles.stepBtn}>
                      <Ionicons name="remove" size={18} color={COLORS.primary} />
                    </TouchableOpacity>
                    <Text style={styles.stepVal}>{plantRows}</Text>
                    <TouchableOpacity onPress={() => setPlantRows(v => String(Math.min(30, parseInt(v||1)+1)))} style={styles.stepBtn}>
                      <Ionicons name="add" size={18} color={COLORS.primary} />
                    </TouchableOpacity>
                  </View>
                </View>
                <View style={[styles.dimRow, { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACE.md }]}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.dimLabel}>Plants per Row</Text>
                    <Text style={styles.dimHint}>Orchid plants along each row</Text>
                  </View>
                  <View style={styles.stepRow}>
                    <TouchableOpacity onPress={() => setPlantsPerRow(v => String(Math.max(1, parseInt(v||1)-1)))} style={styles.stepBtn}>
                      <Ionicons name="remove" size={18} color={COLORS.primary} />
                    </TouchableOpacity>
                    <Text style={styles.stepVal}>{plantsPerRow}</Text>
                    <TouchableOpacity onPress={() => setPlantsPerRow(v => String(Math.min(50, parseInt(v||1)+1)))} style={styles.stepBtn}>
                      <Ionicons name="add" size={18} color={COLORS.primary} />
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
              )}

              {/* IoT Recommendation Banner */}
              <View style={[styles.recBanner, SHADOW.sm]}>
                <View style={styles.recRow}>
                  <View style={styles.recStat}>
                    <Text style={styles.recStatVal}>{total}</Text>
                    <Text style={styles.recStatLabel}>Total Plants</Text>
                  </View>
                  <View style={styles.recDivider} />
                  <View style={styles.recStat}>
                    <Text style={[styles.recStatVal, { color: COLORS.primary }]}>{recSensors}</Text>
                    <Text style={styles.recStatLabel}>Sensors Needed</Text>
                  </View>
                  <View style={styles.recDivider} />
                  <View style={styles.recStat}>
                    <Text style={styles.recStatVal}>{Math.ceil(total / recSensors)}</Text>
                    <Text style={styles.recStatLabel}>Plants/Sensor</Text>
                  </View>
                </View>
                <Text style={styles.recNote}>
                  Algorithm: 1 sensor per 22 plants or 20 mÂ², whichever requires more
                </Text>
              </View>
            </>
          );
        })()}

        {/* Info box */}
        <View style={[styles.infoBox, SHADOW.sm]}>
          <Ionicons name="information-circle-outline" size={16} color={COLORS.info} />
          <Text style={styles.infoText}>
            The app will guide your sensor node through {zones} trial positions for {duration}h total
            (~{Math.round(parseInt(duration||24) / parseInt(zones||4))}h each). Firebase will collect
            real environmental data at each location before the analysis recommends the best final placement.
          </Text>
        </View>

        <TouchableOpacity
          style={[styles.confirmBtn, SHADOW.md, saving && { opacity: 0.6 }]}
          onPress={confirm}
          disabled={saving}
          activeOpacity={0.85}
        >
          {saving
            ? <ActivityIndicator color="#FFF" size="small" />
            : <Ionicons name="checkmark-circle-outline" size={20} color="#FFF" />}
          <Text style={styles.confirmBtnText}>
            {saving ? 'Setting up trialâ€¦' : 'Confirm & Start Trial Placement'}
          </Text>
        </TouchableOpacity>

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container:   { flex: 1, backgroundColor: COLORS.bg },
  scroll:      { padding: SPACE.xl },
  loadingText: { color: COLORS.textSecondary, marginTop: SPACE.md, fontSize: FONT.sm },

  summaryCard: {
    flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.md,
    backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.xl,
  },
  summaryTitle:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  summaryNote:   { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },
  summaryDetect: { color: COLORS.info, fontSize: FONT.xs, marginTop: 4, fontWeight: '600' },

  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 4 },
  sectionHint:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: SPACE.md },

  previewBox: { height: 280, borderRadius: RADIUS.md, overflow: 'hidden', backgroundColor: '#0d1220', marginBottom: SPACE.xl },
  previewWeb: { flex: 1, backgroundColor: 'transparent' },
  sectionRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md, marginTop: SPACE.lg },

  card:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  dimRow:  { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.md },
  dimLabel:{ color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  dimHint: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  dimInput:{
    width: 80, backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm - 2,
    padding: SPACE.md, color: COLORS.text, fontSize: FONT.md,
    fontWeight: '700', textAlign: 'center',
  },

  stepRow:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  stepBtn:  { width: 32, height: 32, borderRadius: 8, backgroundColor: COLORS.primaryDim, alignItems: 'center', justifyContent: 'center' },
  stepVal:  { fontSize: FONT.xl, fontWeight: '700', color: COLORS.text, minWidth: 28, textAlign: 'center' },

  durationRow:      { flexDirection: 'row', gap: 6 },
  durationChip:     { paddingHorizontal: 12, paddingVertical: 5, borderRadius: RADIUS.full, backgroundColor: COLORS.bgInput },
  durationChipActive:{ backgroundColor: COLORS.primary },
  durationText:     { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },
  durationTextActive:{ color: '#FFF' },

  addBtn:  { flexDirection: 'row', alignItems: 'center', gap: 4 },
  addText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },

  windowRow: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.sm,
  },
  wallChip:    { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6 },
  wallText:    { fontSize: FONT.xs, fontWeight: '700' },
  windowLabel: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm },

  infoBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginTop: SPACE.sm, marginBottom: SPACE.xl,
  },
  infoText: { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 18 },

  detectBtn:      { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl, borderWidth: 1, borderColor: COLORS.primaryDim },
  detectBtnTitle: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  detectBtnSub:   { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  detectCard:     { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl, borderLeftWidth: 3, borderLeftColor: '#6fae3d' },
  detectRow:      { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.sm },
  detectStat:     { flex: 1, alignItems: 'center', gap: 3 },
  detectVal:      { color: COLORS.text, fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  detectLabel:    { color: COLORS.textTertiary, fontSize: FONT.xs },
  detectDivider:  { width: 1, height: 38, backgroundColor: COLORS.border },
  detectNote:     { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16, marginBottom: SPACE.md },
  detectActions:  { flexDirection: 'row', gap: SPACE.lg },
  detectMini:     { flexDirection: 'row', alignItems: 'center', gap: 4 },
  detectMiniText: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '600' },

  recBanner:    { backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl },
  recRow:       { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.sm },
  recStat:      { flex: 1, alignItems: 'center' },
  recStatVal:   { color: COLORS.text, fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  recStatLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  recDivider:   { width: 1, height: 36, backgroundColor: COLORS.border },
  recNote:      { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center', lineHeight: 16 },

  confirmBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, backgroundColor: COLORS.primary,
    borderRadius: RADIUS.sm, padding: SPACE.lg,
  },
  confirmBtnText: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
});
