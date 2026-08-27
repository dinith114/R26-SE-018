import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Alert, Platform, Animated,
} from 'react-native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { buildGreenhouseHTML } from '../utils/greenhouse3d';

import BASE_URL from '../config/backend';
const POLL_MS  = 15000;

const ZONE_COLORS = ['#4CAF50','#2196F3','#FF9800','#E91E63','#9C27B0','#00BCD4','#FF5722','#607D8B'];

const STATUS_COLOR  = { pending: COLORS.textTertiary, active: COLORS.warning, done: COLORS.success };
const STATUS_ICON   = { pending: 'ellipse-outline', active: 'radio-button-on', done: 'checkmark-circle' };
const STATUS_LABEL  = { pending: 'Waiting', active: 'Collectingâ€¦', done: 'Done' };

// Map trial positions â†’ normalized 3D markers (grey pending / orange active / green done).
const TRIAL_STATUS_COL = { pending: '#8a93a6', active: '#FF9800', done: '#4CAF50' };

function positionsToMarkers(positions) {
  return (positions || []).map((p) => ({
    x: p.x,
    y: p.y,
    color: TRIAL_STATUS_COL[p.status] || '#8a93a6',
    label: `P${p.id}`,
    pole: true,
    coverage: p.status === 'active' ? 2.5 : 0,
    cross: false,
    ground: false,
  }));
}

const TRIAL_LEGEND = [
  { color: '#9c4dcc', text: 'Orchid plant' },
  { color: '#8a93a6', text: 'Spot â€” waiting' },
  { color: '#FF9800', text: 'Spot â€” collecting now' },
  { color: '#4CAF50', text: 'Spot â€” done' },
];

export default function FarmTrialScreen({ route, navigation }) {
  const { sessionId, trialPositions: initPositions, model, hoursPerPosition, instruction } = route.params;

  const [positions, setPositions] = useState(initPositions || []);
  const [analyzing, setAnalyzing]  = useState(false);
  const [htmlKey,   setHtmlKey]    = useState(0);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  const activePos  = positions.find(p => p.status === 'active');
  const doneCount  = positions.filter(p => p.status === 'done').length;
  const nextPos    = positions.find(p => p.status === 'pending');
  const allDone    = doneCount === positions.length;
  const pct        = Math.round(100 * doneCount / Math.max(positions.length, 1));

  // Pulse animation for active sensor indicator
  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulseAnim, { toValue: 1.3, duration: 800, useNativeDriver: true }),
      Animated.timing(pulseAnim, { toValue: 1.0, duration: 800, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, []);

  // Poll backend for status updates
  const poll = useCallback(async () => {
    try {
      const res  = await fetch(`${BASE_URL}/api/v1/farm/trial-status/${sessionId}`);
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      if (!Array.isArray(data.positions)) throw new Error('Malformed trial status');
      setPositions(data.positions);
      setHtmlKey(k => k + 1);
    } catch (_) {}
  }, [sessionId]);

  useEffect(() => {
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const startPosition = async (posId) => {
    try {
      const res  = await fetch(`${BASE_URL}/api/v1/farm/trial-start/${sessionId}/${posId}`, { method: 'POST' });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setPositions(prev => prev.map(p =>
        p.id === posId    ? { ...p, status: 'active', start_time: new Date().toISOString() } :
        p.status === 'active' ? { ...p, status: 'done' } : p
      ));
      setHtmlKey(k => k + 1);
      Alert.alert(
        `Position ${posId} active`,
        `Leave your sensor here for ~${hoursPerPosition}h, then tap "Done & Move".`
      );
    } catch (err) {
      Alert.alert('Error', err.message);
    }
  };

  const donePosition = async (posId) => {
    Alert.alert(
      'Mark position done?',
      'Confirm you have collected enough readings here and are ready to move the sensor.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Yes, move sensor',
          onPress: async () => {
            try {
              const doneRes = await fetch(`${BASE_URL}/api/v1/farm/trial-done/${sessionId}/${posId}?reading_count=0`, { method: 'POST' });
              if (!doneRes.ok) throw new Error(`Server error ${doneRes.status}`);
              setPositions(prev => prev.map(p =>
                p.id === posId ? { ...p, status: 'done', end_time: new Date().toISOString() } : p
              ));
              setHtmlKey(k => k + 1);
            } catch (err) {
              Alert.alert('Error', err.message);
            }
          },
        },
      ]
    );
  };

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const res  = await fetch(`${BASE_URL}/api/v1/farm/analyze-trial/${sessionId}`, { method: 'POST' });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      navigation.replace('FarmResults', { sessionId, model, analysis: data, positions });
    } catch (err) {
      Alert.alert('Analysis failed', err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const threeHtml = buildGreenhouseHTML({
    model,
    plants:    model?.plant_positions || [],
    markers:   positionsToMarkers(positions),
    legend:    TRIAL_LEGEND,
    showDimensions: true,
  });

  return (
    <View style={styles.container}>
      <ScreenHeader title="Trial Placement" subtitle="Step 3 of 4 â€” Data Collection" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        {/* 3D farm view */}
        <View style={[styles.viewerBox, SHADOW.md]}>
          <WebView key={htmlKey} source={{ html: threeHtml }} style={styles.webview}
            scrollEnabled={false} javaScriptEnabled originWhitelist={['*']} />
        </View>

        {/* Progress bar */}
        <View style={[styles.progressCard, SHADOW.sm]}>
          <View style={styles.progressHeader}>
            <Text style={styles.progressTitle}>Collection Progress</Text>
            <Text style={styles.progressPct}>{pct}%</Text>
          </View>
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${pct}%` }]} />
          </View>
          <Text style={styles.progressSub}>
            {doneCount} of {positions.length} positions complete
          </Text>
        </View>

        {/* Instruction banner */}
        {instruction && (
          <View style={[styles.instructBanner, SHADOW.sm]}>
            <Ionicons name="bulb-outline" size={18} color={COLORS.warning} />
            <Text style={styles.instructText}>{instruction}</Text>
          </View>
        )}

        {/* Active position card */}
        {activePos && (
          <View style={[styles.activeCard, SHADOW.md]}>
            <View style={styles.activeHeader}>
              <Animated.View style={[styles.activeDot, { transform: [{ scale: pulseAnim }] }]} />
              <Text style={styles.activeTitle}>Sensor currently at Position {activePos.id}</Text>
            </View>
            <Text style={styles.activeCoords}>
              X: {activePos.x}m Â· Y: {activePos.y}m Â· Height: {activePos.height}m
            </Text>
            <Text style={styles.activeSince}>
              Started: {activePos.start_time
                ? new Date(activePos.start_time).toLocaleTimeString()
                : 'just now'}
              {' Â· '}Leave here for ~{hoursPerPosition}h
            </Text>
            <TouchableOpacity style={[styles.doneBtn, SHADOW.sm]} onPress={() => donePosition(activePos.id)}>
              <Ionicons name="checkmark-circle-outline" size={18} color="#FFF" />
              <Text style={styles.doneBtnText}>Done here â€” move sensor to next position</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Position list */}
        <Text style={styles.sectionTitle}>All Positions</Text>
        {positions.map(pos => (
          <View key={pos.id} style={[styles.posCard, SHADOW.sm]}>
            <View style={[styles.posNum, { backgroundColor: ZONE_COLORS[(pos.id - 1) % ZONE_COLORS.length] }]}>
              <Text style={styles.posNumText}>{pos.id}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.posLabel}>{pos.label}</Text>
              <Text style={styles.posCoords}>X: {pos.x}m Â· Y: {pos.y}m</Text>
              {pos.status === 'done' && pos.end_time && (
                <Text style={styles.posTime}>
                  Collected until {new Date(pos.end_time).toLocaleTimeString()}
                </Text>
              )}
            </View>
            <View style={styles.posRight}>
              <Ionicons name={STATUS_ICON[pos.status]} size={20} color={STATUS_COLOR[pos.status]} />
              <Text style={[styles.posStatus, { color: STATUS_COLOR[pos.status] }]}>
                {STATUS_LABEL[pos.status]}
              </Text>
              {pos.status === 'pending' && !activePos && (
                <TouchableOpacity style={styles.startBtn} onPress={() => startPosition(pos.id)}>
                  <Text style={styles.startBtnText}>Start</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        ))}

        {/* Analyze button â€” shown when all done or user forces early */}
        <TouchableOpacity
          style={[styles.analyzeBtn, SHADOW.md, !allDone && styles.analyzeBtnSoft, analyzing && { opacity: 0.6 }]}
          onPress={allDone ? runAnalysis : () =>
            Alert.alert(
              'Run early analysis?',
              'Not all positions are done. Analysis will work but may miss some zones.',
              [{ text: 'Cancel', style: 'cancel' }, { text: 'Analyze anyway', onPress: runAnalysis }]
            )}
          disabled={analyzing}
          activeOpacity={0.85}
        >
          {analyzing
            ? <ActivityIndicator color="#FFF" size="small" />
            : <Ionicons name="analytics-outline" size={20} color="#FFF" />}
          <View>
            <Text style={styles.analyzeBtnText}>
              {allDone ? 'Analyze & Get Final Placement' : 'Analyze Early'}
            </Text>
            {!allDone && (
              <Text style={styles.analyzeBtnSub}>{positions.length - doneCount} position(s) remaining</Text>
            )}
          </View>
        </TouchableOpacity>

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: COLORS.bg },
  scroll:       { padding: SPACE.xl },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.sm },

  viewerBox: { height: 260, borderRadius: RADIUS.md, overflow: 'hidden', backgroundColor: '#1a1e2e', marginBottom: SPACE.xl },
  webview:   { flex: 1, backgroundColor: 'transparent' },

  progressCard:   { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  progressHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: SPACE.sm },
  progressTitle:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  progressPct:    { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  progressTrack:  { height: 6, backgroundColor: COLORS.border, borderRadius: 3, overflow: 'hidden', marginBottom: SPACE.sm },
  progressFill:   { height: '100%', backgroundColor: COLORS.primary, borderRadius: 3 },
  progressSub:    { color: COLORS.textTertiary, fontSize: FONT.xs },

  instructBanner: {
    flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm,
    backgroundColor: COLORS.warningDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.xl,
  },
  instructText: { color: COLORS.text, fontSize: FONT.sm, flex: 1, lineHeight: 18 },

  activeCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
    padding: SPACE.lg, marginBottom: SPACE.xl,
    borderLeftWidth: 3, borderLeftColor: COLORS.warning,
  },
  activeHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.sm },
  activeDot:    { width: 12, height: 12, borderRadius: 6, backgroundColor: COLORS.warning },
  activeTitle:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  activeCoords: { color: COLORS.textSecondary, fontSize: FONT.xs, fontVariant: ['tabular-nums'] },
  activeSince:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, marginBottom: SPACE.md },
  doneBtn:      { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.success, borderRadius: RADIUS.sm, padding: SPACE.md },
  doneBtnText:  { color: '#FFF', fontSize: FONT.sm, fontWeight: '700', flex: 1 },

  posCard:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm },
  posNum:    { width: 36, height: 36, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  posNumText:{ color: '#FFF', fontWeight: '800', fontSize: FONT.sm },
  posLabel:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  posCoords: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1, fontVariant: ['tabular-nums'] },
  posTime:   { color: COLORS.success, fontSize: FONT.xs, marginTop: 1 },
  posRight:  { alignItems: 'flex-end', gap: 4 },
  posStatus: { fontSize: FONT.xs, fontWeight: '600' },
  startBtn:  { backgroundColor: COLORS.primary, borderRadius: 6, paddingHorizontal: 10, paddingVertical: 4, marginTop: 2 },
  startBtnText: { color: '#FFF', fontSize: FONT.xs, fontWeight: '700' },

  analyzeBtn:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.md, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.xl },
  analyzeBtnSoft: { backgroundColor: COLORS.textSecondary },
  analyzeBtnText: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  analyzeBtnSub:  { color: 'rgba(255,255,255,0.7)', fontSize: FONT.xs, textAlign: 'center' },
});
