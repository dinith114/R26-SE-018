import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Alert, Platform,
} from 'react-native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { buildGreenhouseHTML } from '../utils/greenhouse3d';

import BASE_URL from '../config/backend';
const ZONE_COLORS = ['#4CAF50','#2196F3','#FF9800','#E91E63','#9C27B0','#00BCD4','#FF5722','#607D8B'];

const ACTION_CONFIG = {
  keep:    { color: COLORS.success,    bg: COLORS.successDim,  icon: 'checkmark-circle',  label: 'KEEP'   },
  remove:  { color: COLORS.danger,     bg: COLORS.dangerDim,   icon: 'close-circle',       label: 'REMOVE' },
  add:     { color: COLORS.warning,    bg: COLORS.warningDim,  icon: 'add-circle',         label: 'ADD'    },
  redundant:{ color: COLORS.danger,    bg: COLORS.dangerDim,   icon: 'close-circle',       label: 'REMOVE' },
  gap:     { color: COLORS.warning,    bg: COLORS.warningDim,  icon: 'add-circle',         label: 'ADD'    },
};

// Map backend recommendations â†’ normalized 3D markers for the greenhouse builder.
function recsToMarkers(recommendations, model) {
  const zoneR = model?.sensor_recommendation?.zone_size ? 2.5 : 2.5;
  return (recommendations || []).map((rec) => {
    const isKeep   = rec.action === 'keep';
    const isRemove = rec.action === 'remove' || rec.action === 'redundant';
    const isAdd    = rec.action === 'add' || rec.action === 'gap';
    const color = isKeep ? '#4CAF50' : isRemove ? '#F44336' : '#FF9800';
    const tag   = isKeep ? 'KEEP' : isRemove ? 'REMOVE' : 'ADD';
    return {
      x: rec.x || 0,
      y: rec.y || 0,
      color,
      label: `${tag} S${rec.position_id || '?'}`,
      pole: isKeep || isRemove,
      coverage: isKeep ? 3.0 : 0,
      cross: isRemove,
      ground: isAdd,
    };
  });
}

const RESULTS_LEGEND = [
  { color: '#9c4dcc', text: 'Orchid plant' },
  { color: '#4CAF50', text: 'Keep sensor (3m coverage)' },
  { color: '#F44336', text: 'Remove (redundant)' },
  { color: '#FF9800', text: 'Add sensor here' },
  { color: '#2196F3', text: 'Pipe route' },
];

export default function FarmResultsScreen({ route, navigation }) {
  const { sessionId, model, analysis } = route.params;

  const [pipeline,  setPipeline]  = useState(null);
  const [loadingPipe, setLoadingPipe] = useState(false);
  const [tab, setTab] = useState('placement');

  const recommendations  = analysis?.recommendations || [];
  const summary          = analysis?.summary || '';
  const plantCount       = analysis?.plant_count    ?? model?.plant_count    ?? 0;
  const finalSensorCount = analysis?.final_sensor_count ?? (recommendations.filter(r => r.action === 'keep').length + recommendations.filter(r => r.action === 'add' || r.action === 'gap').length);
  const sensorRec        = analysis?.sensor_recommendation ?? model?.sensor_recommendation;

  const fetchPipeline = async () => {
    setLoadingPipe(true);
    try {
      const form = new FormData();
      form.append('session_id',      sessionId);
      form.append('water_source_x',  '0');
      form.append('water_source_y',  '0');
      form.append('plant_rows_json', '[]');

      const res  = await fetch(`${BASE_URL}/api/v1/farm/pipeline-route`, { method: 'POST', body: form });
      const data = await res.json();
      setPipeline(data);
      setTab('pipeline');
    } catch (err) {
      Alert.alert('Pipeline calculation failed', err.message);
    } finally {
      setLoadingPipe(false);
    }
  };

  const threeHtml = buildGreenhouseHTML({
    model,
    plants:    model?.plant_positions || [],
    markers:   recsToMarkers(recommendations, model),
    pipeline,
    legend:    RESULTS_LEGEND,
    showDimensions: true,
  });

  const keep   = recommendations.filter(r => r.action === 'keep');
  const remove = recommendations.filter(r => r.action === 'remove' || r.action === 'redundant');
  const add    = recommendations.filter(r => r.action === 'add'    || r.action === 'gap');

  return (
    <View style={styles.container}>
      <ScreenHeader title="Final Results" subtitle="Step 4 of 4 â€” Optimized Placement" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        {/* 3D view */}
        <View style={[styles.viewerBox, SHADOW.md]}>
          <WebView source={{ html: threeHtml }} style={styles.webview}
            scrollEnabled={false} javaScriptEnabled originWhitelist={['*']} />
        </View>

        {/* Summary banner */}
        <View style={[styles.summaryBanner, SHADOW.sm]}>
          <Ionicons name="analytics-outline" size={20} color={COLORS.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.summaryTitle}>Analysis Complete</Text>
            <Text style={styles.summaryText}>{summary}</Text>
          </View>
        </View>

        {/* Plant & Sensor stats */}
        {plantCount > 0 && (
          <View style={[styles.statsCard, SHADOW.sm]}>
            <View style={styles.statItem}>
              <Ionicons name="leaf-outline" size={18} color="#8BC34A" />
              <Text style={styles.statVal}>{plantCount}</Text>
              <Text style={styles.statLabel}>Plants</Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.statItem}>
              <Ionicons name="hardware-chip-outline" size={18} color={COLORS.primary} />
              <Text style={[styles.statVal, { color: COLORS.primary }]}>{finalSensorCount}</Text>
              <Text style={styles.statLabel}>Sensors Final</Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.statItem}>
              <Ionicons name="people-outline" size={18} color={COLORS.info} />
              <Text style={styles.statVal}>{finalSensorCount > 0 ? Math.ceil(plantCount / finalSensorCount) : 'â€”'}</Text>
              <Text style={styles.statLabel}>Plants/Unit</Text>
            </View>
          </View>
        )}
        {sensorRec?.reasoning && (
          <View style={[styles.reasonCard, SHADOW.sm]}>
            <Ionicons name="analytics-outline" size={14} color={COLORS.info} />
            <Text style={styles.reasonText}>{sensorRec.reasoning}</Text>
          </View>
        )}

        {/* Tabs */}
        <View style={[styles.tabBar, SHADOW.sm]}>
          {[['placement','Sensor Placement'], ['pipeline','Pipe Route']].map(([key, label]) => (
            <TouchableOpacity key={key} onPress={() => key === 'pipeline' && !pipeline ? fetchPipeline() : setTab(key)}
              style={[styles.tab, tab === key && styles.tabActive]}>
              {key === 'pipeline' && loadingPipe
                ? <ActivityIndicator size="small" color={COLORS.primary} />
                : <Text style={[styles.tabText, tab === key && styles.tabTextActive]}>{label}</Text>}
            </TouchableOpacity>
          ))}
        </View>

        {tab === 'placement' && (
          <>
            {/* Keep */}
            {keep.length > 0 && (
              <>
                <Text style={styles.sectionTitle}>Keep These Sensors</Text>
                {keep.map((rec, i) => <RecCard key={i} rec={rec} />)}
              </>
            )}
            {/* Remove */}
            {remove.length > 0 && (
              <>
                <Text style={styles.sectionTitle}>Remove / Relocate</Text>
                {remove.map((rec, i) => <RecCard key={i} rec={rec} />)}
              </>
            )}
            {/* Add */}
            {add.length > 0 && (
              <>
                <Text style={styles.sectionTitle}>Add Sensors Here</Text>
                {add.map((rec, i) => <RecCard key={i} rec={rec} />)}
              </>
            )}
            {recommendations.length === 0 && (
              <View style={styles.emptyCard}>
                <Text style={styles.emptyText}>No recommendations yet â€” run analysis first.</Text>
              </View>
            )}
          </>
        )}

        {tab === 'pipeline' && pipeline && (
          <>
            <View style={[styles.pipeStats, SHADOW.sm]}>
              <View style={styles.pipeStat}>
                <Text style={styles.pipeStatVal}>{pipeline.total_length_m} m</Text>
                <Text style={styles.pipeStatLabel}>Total pipe</Text>
              </View>
              <View style={styles.pipeDivider} />
              <View style={styles.pipeStat}>
                <Text style={styles.pipeStatVal}>LKR {pipeline.estimated_cost_lkr?.toLocaleString()}</Text>
                <Text style={styles.pipeStatLabel}>Est. cost (~150/m)</Text>
              </View>
              <View style={styles.pipeDivider} />
              <View style={styles.pipeStat}>
                <Text style={styles.pipeStatVal}>{pipeline.pipe_segments?.length}</Text>
                <Text style={styles.pipeStatLabel}>Segments</Text>
              </View>
            </View>

            <Text style={styles.sectionTitle}>Pipe Segments</Text>
            {pipeline.pipe_segments?.map((seg, i) => (
              <View key={i} style={[styles.segCard, SHADOW.sm]}>
                <View style={styles.segIcon}>
                  <Ionicons name="git-commit-outline" size={18} color={COLORS.info} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.segTitle}>{seg.from.label} â†’ {seg.to.label}</Text>
                  <Text style={styles.segCoords}>
                    ({seg.from.x},{seg.from.y}) â†’ ({seg.to.x},{seg.to.y})
                  </Text>
                </View>
                <Text style={styles.segLen}>{seg.length_m} m</Text>
              </View>
            ))}

            <View style={[styles.pipeNote, SHADOW.sm]}>
              <Ionicons name="information-circle-outline" size={16} color={COLORS.info} />
              <Text style={styles.pipeNoteText}>{pipeline.note}</Text>
            </View>
          </>
        )}

        {tab === 'pipeline' && !pipeline && (
          <TouchableOpacity style={[styles.calcBtn, SHADOW.md]} onPress={fetchPipeline} disabled={loadingPipe}>
            {loadingPipe
              ? <ActivityIndicator color="#FFF" size="small" />
              : <Ionicons name="git-network-outline" size={20} color="#FFF" />}
            <Text style={styles.calcBtnText}>Calculate Irrigation Route</Text>
          </TouchableOpacity>
        )}

        <TouchableOpacity style={[styles.doneBtn, SHADOW.md]} onPress={() => navigation.navigate('MainTabs')}>
          <Ionicons name="home-outline" size={20} color="#FFF" />
          <Text style={styles.doneBtnText}>Back to Dashboard</Text>
        </TouchableOpacity>

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

function RecCard({ rec }) {
  const cfg = ACTION_CONFIG[rec.action] || ACTION_CONFIG.keep;
  return (
    <View style={[styles.recCard, { borderLeftColor: cfg.color }, SHADOW.sm]}>
      <View style={[styles.recBadge, { backgroundColor: cfg.bg }]}>
        <Ionicons name={cfg.icon} size={18} color={cfg.color} />
        <Text style={[styles.recBadgeText, { color: cfg.color }]}>{cfg.label}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.recMessage}>{rec.message}</Text>
        {(rec.x != null && rec.y != null) && (
          <Text style={styles.recCoords}>Position: X={rec.x}m Â· Y={rec.y}m</Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: COLORS.bg },
  scroll:       { padding: SPACE.xl },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.lg },

  viewerBox: { height: 300, borderRadius: RADIUS.md, overflow: 'hidden', backgroundColor: '#1a1e2e', marginBottom: SPACE.xl },
  webview:   { flex: 1, backgroundColor: 'transparent' },

  summaryBanner: {
    flexDirection: 'row', gap: SPACE.md, backgroundColor: COLORS.primaryDim,
    borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl,
  },
  summaryTitle: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  summaryText:  { color: COLORS.text, fontSize: FONT.xs, marginTop: 2 },

  tabBar:       { flexDirection: 'row', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: 3, marginBottom: SPACE.xl },
  tab:          { flex: 1, alignItems: 'center', paddingVertical: SPACE.md, borderRadius: RADIUS.sm - 2 },
  tabActive:    { backgroundColor: COLORS.bg },
  tabText:      { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },
  tabTextActive:{ color: COLORS.primary, fontWeight: '700' },

  statsCard:   { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm },
  statItem:    { flex: 1, alignItems: 'center', gap: 3 },
  statVal:     { color: COLORS.text, fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  statLabel:   { color: COLORS.textTertiary, fontSize: FONT.xs },
  statDivider: { width: 1, height: 40, backgroundColor: COLORS.border },
  reasonCard:  { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start', backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl },
  reasonText:  { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 16 },

  recCard: {
    flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.md,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
    borderLeftWidth: 3, padding: SPACE.md, marginBottom: SPACE.sm,
  },
  recBadge:     { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 6, paddingVertical: 3, borderRadius: 5 },
  recBadgeText: { fontSize: 9, fontWeight: '800' },
  recMessage:   { color: COLORS.text, fontSize: FONT.sm, lineHeight: 18 },
  recCoords:    { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, fontVariant: ['tabular-nums'] },

  emptyCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.xl, alignItems: 'center' },
  emptyText: { color: COLORS.textTertiary, fontSize: FONT.sm },

  pipeStats:   { flexDirection: 'row', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  pipeStat:    { flex: 1, alignItems: 'center' },
  pipeStatVal: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800', fontVariant: ['tabular-nums'] },
  pipeStatLabel:{ color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  pipeDivider: { width: 1, backgroundColor: COLORS.border },

  segCard:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  segIcon:   { width: 32, height: 32, borderRadius: 8, backgroundColor: COLORS.infoDim, alignItems: 'center', justifyContent: 'center' },
  segTitle:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  segCoords: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1, fontVariant: ['tabular-nums'] },
  segLen:    { color: COLORS.info, fontSize: FONT.sm, fontWeight: '700', fontVariant: ['tabular-nums'] },

  pipeNote:     { flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginTop: SPACE.sm },
  pipeNoteText: { color: COLORS.textSecondary, fontSize: FONT.xs, flex: 1, lineHeight: 18 },

  calcBtn:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.md, backgroundColor: COLORS.info, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.md },
  calcBtnText:{ color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  doneBtn:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.md, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, padding: SPACE.lg, marginTop: SPACE.xl },
  doneBtnText:{ color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
});
