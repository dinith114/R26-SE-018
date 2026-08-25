import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Dimensions, Platform,
} from 'react-native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const { width: SCREEN_W } = Dimensions.get('window');
const BASE_URL  = Platform.OS === 'web' ? 'http://localhost:8000' : 'http://192.168.1.129:8000';
const GRID_RES  = 0.5;
const WALLS     = ['north', 'south', 'east', 'west'];
const WALL_COLOR = { north: COLORS.info, south: COLORS.warning, east: COLORS.primary, west: COLORS.fertilizer };
const WALL_ICON  = { north: 'arrow-up-outline', south: 'arrow-down-outline', east: 'arrow-forward-outline', west: 'arrow-back-outline' };

function buildQuickHTML(farmData) {
  const dataJson = JSON.stringify(farmData);
  return `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>*{margin:0;padding:0}body{background:#1a1e2e;overflow:hidden;width:100vw;height:100vh}
#hint{position:absolute;bottom:8px;left:0;right:0;text-align:center;color:rgba(255,255,255,0.35);font-size:10px;font-family:sans-serif;pointer-events:none}</style>
</head><body>
<div id="hint">Drag to rotate Â· Pinch to zoom</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
var FARM=${dataJson};var GRID_RES=${GRID_RES};var SCALE=20;
var W=FARM.farm_width,L=FARM.farm_length,H=FARM.farm_height;
function fx(x){return x-W/2;} function fz(y){return y-L/2;}
var renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
renderer.setSize(window.innerWidth,window.innerHeight);
document.body.appendChild(renderer.domElement);
var scene=new THREE.Scene(); scene.background=new THREE.Color(0x1a1e2e);
var camera=new THREE.PerspectiveCamera(55,window.innerWidth/window.innerHeight,0.1,200);
camera.position.set(W*1.3,H*3.2,L*1.6); camera.lookAt(0,0,0);
var controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true; controls.dampingFactor=0.08;
scene.add(new THREE.AmbientLight(0xffffff,0.7));
var sun=new THREE.DirectionalLight(0xfff5e0,0.9); sun.position.set(W,H*3,L); scene.add(sun);
var zMap={};
for(var i=0;i<FARM.sensor_positions.length;i++){zMap[FARM.sensor_positions[i].zone_id]=FARM.sensor_positions[i].zone_color;}
var fc=document.createElement('canvas');
fc.width=Math.ceil(W*SCALE); fc.height=Math.ceil(L*SCALE);
var ctx=fc.getContext('2d'); ctx.fillStyle='#1e2235'; ctx.fillRect(0,0,fc.width,fc.height);
var rpx=GRID_RES*SCALE;
for(var i=0;i<FARM.grid_cells.length;i++){
  var c=FARM.grid_cells[i]; ctx.fillStyle=(zMap[c.zone_id]||'#444')+'bb';
  ctx.fillRect(c.x*SCALE-rpx/2,c.y*SCALE-rpx/2,rpx,rpx);
}
var floor=new THREE.Mesh(new THREE.PlaneGeometry(W,L),new THREE.MeshLambertMaterial({map:new THREE.CanvasTexture(fc)}));
floor.rotation.x=-Math.PI/2; scene.add(floor);
var edges=new THREE.EdgesGeometry(new THREE.BoxGeometry(W,H,L));
var walls=new THREE.LineSegments(edges,new THREE.LineBasicMaterial({color:0x3a5068}));
walls.position.set(0,H/2,0); scene.add(walls);
for(var i=0;i<FARM.sensor_positions.length;i++){
  var s=FARM.sensor_positions[i];
  var col=new THREE.Color(s.zone_color);
  var sx=fx(s.x),sz=fz(s.y),sh=s.height;
  var pole=new THREE.Mesh(new THREE.CylinderGeometry(0.04,0.04,sh,8),new THREE.MeshLambertMaterial({color:0x708090}));
  pole.position.set(sx,sh/2,sz); scene.add(pole);
  var sph=new THREE.Mesh(new THREE.SphereGeometry(0.22,16,12),new THREE.MeshLambertMaterial({color:col}));
  sph.position.set(sx,sh+0.22,sz); scene.add(sph);
  var ring=new THREE.Mesh(new THREE.RingGeometry(0.35,0.55,32),
    new THREE.MeshBasicMaterial({color:col,side:THREE.DoubleSide,transparent:true,opacity:0.5}));
  ring.rotation.x=-Math.PI/2; ring.position.set(sx,0.01,sz); scene.add(ring);
  var lc=document.createElement('canvas'); lc.width=64; lc.height=32;
  var lctx=lc.getContext('2d'); lctx.fillStyle=s.zone_color; lctx.fillRect(2,2,60,28);
  lctx.fillStyle='#fff'; lctx.font='bold 16px sans-serif'; lctx.textAlign='center'; lctx.textBaseline='middle';
  lctx.fillText('Z'+(s.zone_id+1),32,16);
  var spr=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(lc),depthTest:false}));
  spr.position.set(sx,sh+0.9,sz); spr.scale.set(1.0,0.5,1); scene.add(spr);
}
window.addEventListener('resize',function(){camera.aspect=window.innerWidth/window.innerHeight;camera.updateProjectionMatrix();renderer.setSize(window.innerWidth,window.innerHeight);});
function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}
animate();
</script></body></html>`;
}

// â”€â”€â”€ Entry screen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const FarmPlannerScreen = ({ navigation }) => {
  const [starting, setStarting] = useState(false);

  const startFullSurvey = async () => {
    setStarting(true);
    try {
      const res  = await fetch(`${BASE_URL}/api/v1/farm/new-session`, { method: 'POST' });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      navigation.navigate('FarmScan', { sessionId: data.session_id });
    } catch (err) {
      Alert.alert('Could not start session', `${err.message}\n\nMake sure the backend server is running.`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Farm Planner" subtitle="Sensor Placement Optimizer" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        <Text style={styles.intro}>
          Choose how to plan your sensor deployment. The Full Survey collects real
          environmental data before recommending final positions.
        </Text>

        {/* Full Survey */}
        <TouchableOpacity
          style={[styles.modeCard, styles.modeCardPrimary, SHADOW.md, starting && { opacity: 0.7 }]}
          activeOpacity={0.85}
          disabled={starting}
          onPress={startFullSurvey}
        >
          <View style={styles.modeIconWrap}>
            {starting
              ? <ActivityIndicator color="#FFF" size="small" />
              : <Ionicons name="scan-outline" size={32} color="#FFF" />}
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.modeTitleWhite}>Full Farm Survey</Text>
            <Text style={styles.modeSubWhite}>{starting ? 'Starting sessionâ€¦' : 'Recommended'}</Text>
            <View style={{ height: SPACE.sm }} />
            {[
              'Sample light & environment at several spots',
              'Place sensor node at trial positions (1â€“2 days)',
              'Real data analysis â†’ optimized final placement',
              'Tells you how many sensor devices this house needs',
            ].map((s, i) => (
              <View key={i} style={styles.featureRow}>
                <Ionicons name="checkmark-circle" size={14} color="rgba(255,255,255,0.8)" />
                <Text style={styles.featureText}>{s}</Text>
              </View>
            ))}
          </View>
        </TouchableOpacity>

        {/* Quick Analysis */}
        <TouchableOpacity
          style={[styles.modeCard, SHADOW.sm]}
          activeOpacity={0.85}
          onPress={() => navigation.navigate('FarmQuick')}
        >
          <View style={[styles.modeIconWrap, { backgroundColor: COLORS.primaryDim }]}>
            <Ionicons name="flash-outline" size={32} color={COLORS.primary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.modeTitle}>Quick Analysis</Text>
            <Text style={styles.modeSub}>Instant estimate, no data collection</Text>
            <View style={{ height: SPACE.sm }} />
            {[
              'Enter greenhouse dimensions manually',
              'Light simulation from window positions',
              'K-means zone clustering',
              '3D visualisation in seconds',
            ].map((s, i) => (
              <View key={i} style={styles.featureRow}>
                <Ionicons name="checkmark-circle" size={14} color={COLORS.primary} />
                <Text style={[styles.featureText, { color: COLORS.textSecondary }]}>{s}</Text>
              </View>
            ))}
          </View>
        </TouchableOpacity>

        {/* Device Calculator */}
        <TouchableOpacity
          style={[styles.modeCard, SHADOW.sm]}
          activeOpacity={0.85}
          onPress={() => navigation.navigate('DeviceCalculator')}
        >
          <View style={[styles.modeIconWrap, { backgroundColor: COLORS.infoDim }]}>
            <Ionicons name="calculator-outline" size={32} color={COLORS.info} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.modeTitle}>Sensor Device Calculator</Text>
            <Text style={styles.modeSub}>How many devices does a house need?</Text>
            <View style={{ height: SPACE.sm }} />
            {[
              'Enter readings from a few survey spots',
              'Groups spots into microclimate zones',
              'One sensor device per zone',
              'Answers "how many devices" with real data',
            ].map((s, i) => (
              <View key={i} style={styles.featureRow}>
                <Ionicons name="checkmark-circle" size={14} color={COLORS.info} />
                <Text style={[styles.featureText, { color: COLORS.textSecondary }]}>{s}</Text>
              </View>
            ))}
          </View>
        </TouchableOpacity>

        <View style={[styles.compareCard, SHADOW.sm]}>
          <Text style={styles.compareTitle}>Which should I use?</Text>
          <View style={styles.compareRow}>
            <View style={styles.compareCol}>
              <Text style={[styles.compareHead, { color: COLORS.primary }]}>Quick</Text>
              <Text style={styles.compareItem}>Ready in 1 min</Text>
              <Text style={styles.compareItem}>Simulation-based</Text>
              <Text style={styles.compareItem}>Good for planning</Text>
            </View>
            <View style={styles.compareDivider} />
            <View style={styles.compareCol}>
              <Text style={[styles.compareHead, { color: COLORS.warning }]}>Full Survey</Text>
              <Text style={styles.compareItem}>Takes 1â€“2 days</Text>
              <Text style={styles.compareItem}>Real sensor data</Text>
              <Text style={styles.compareItem}>Best accuracy</Text>
            </View>
          </View>
        </View>

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

// â”€â”€â”€ Quick Analysis sub-screen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export const FarmQuickScreen = ({ navigation }) => {
  const [width,   setWidth]   = useState('10');
  const [length,  setLength]  = useState('20');
  const [height,  setHeight]  = useState('3');
  const [zones,   setZones]   = useState('4');
  const [hour,    setHour]    = useState('10');
  const [windows, setWindows] = useState([
    { wall: 'south', position: 0.5, width: 2.0 },
    { wall: 'east',  position: 0.5, width: 1.5 },
  ]);
  const [loading,   setLoading]   = useState(false);
  const [results,   setResults]   = useState(null);
  const [threeHtml, setThreeHtml] = useState('');

  const addWindow = () => {
    if (windows.length >= 4) return;
    setWindows(prev => [...prev, { wall: 'north', position: 0.5, width: 1.5 }]);
  };

  const analyze = async () => {
    const w = parseFloat(width), l = parseFloat(length), h = parseFloat(height);
    if (!w || !l || !h) { Alert.alert('Enter all dimensions'); return; }
    setLoading(true);
    try {
      const body = {
        width: w, length: l, height: h,
        target_zones: parseInt(zones) || 4,
        hour_of_day: parseFloat(hour) || 10,
        grid_resolution: GRID_RES,
        windows: windows,
        obstacles: [], plant_rows: [],
      };
      const res  = await fetch(`${BASE_URL}/api/v1/farm/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json();
      setResults(data);
      setThreeHtml(buildQuickHTML(data));
    } catch (err) {
      Alert.alert('Analysis failed', err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Quick Analysis" subtitle="Simulation-based placement" navigation={navigation} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        <Text style={styles.sectionTitle}>Greenhouse Dimensions</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <View style={styles.row3}>
            {[['Width', width, setWidth], ['Length', length, setLength], ['Height', height, setHeight]].map(([lbl, val, set]) => (
              <View key={lbl} style={styles.dimField}>
                <Text style={styles.dimLabel}>{lbl} (m)</Text>
                <TextInput style={styles.dimInput} value={val} onChangeText={set}
                  keyboardType="decimal-pad" placeholder="0" placeholderTextColor={COLORS.textTertiary} />
              </View>
            ))}
          </View>
        </View>

        <View style={styles.row2}>
          <View style={[styles.halfCard, SHADOW.sm]}>
            <Text style={styles.dimLabel}>Zones</Text>
            <View style={styles.stepRow}>
              <TouchableOpacity onPress={() => setZones(v => String(Math.max(1, parseInt(v||1)-1)))} style={styles.stepBtn}>
                <Ionicons name="remove" size={18} color={COLORS.primary} />
              </TouchableOpacity>
              <Text style={styles.stepVal}>{zones}</Text>
              <TouchableOpacity onPress={() => setZones(v => String(Math.min(8, parseInt(v||1)+1)))} style={styles.stepBtn}>
                <Ionicons name="add" size={18} color={COLORS.primary} />
              </TouchableOpacity>
            </View>
          </View>
          <View style={[styles.halfCard, SHADOW.sm]}>
            <Text style={styles.dimLabel}>Sun time</Text>
            <View style={styles.stepRow}>
              {[['6','Dawn'],['10','Morn'],['14','Noon'],['17','Eve']].map(([h, lbl]) => (
                <TouchableOpacity key={h} onPress={() => setHour(h)}
                  style={[styles.hourChip, hour === h && styles.hourChipActive]}>
                  <Text style={[styles.hourText, hour === h && styles.hourTextActive]}>{lbl}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </View>

        <View style={styles.sectionRow}>
          <Text style={styles.sectionTitle}>Windows</Text>
          {windows.length < 4 && (
            <TouchableOpacity onPress={addWindow} style={styles.addBtn}>
              <Ionicons name="add-circle-outline" size={18} color={COLORS.primary} />
              <Text style={styles.addText}>Add</Text>
            </TouchableOpacity>
          )}
        </View>
        {windows.map((win, idx) => (
          <View key={idx} style={[styles.windowRow, SHADOW.sm]}>
            <TouchableOpacity onPress={() => setWindows(prev => prev.map((w,i)=>i!==idx?w:{...w,wall:WALLS[(WALLS.indexOf(w.wall)+1)%4]}))}
              style={[styles.wallChip, { backgroundColor: `${WALL_COLOR[win.wall]}18` }]}>
              <Ionicons name={WALL_ICON[win.wall]} size={14} color={WALL_COLOR[win.wall]} />
              <Text style={[styles.wallText, { color: WALL_COLOR[win.wall] }]}>{win.wall.toUpperCase()}</Text>
            </TouchableOpacity>
            <Text style={{ flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, marginLeft: SPACE.sm }}>
              {win.position === 0.25 ? 'Left' : win.position === 0.75 ? 'Right' : 'Centre'}
            </Text>
            <TouchableOpacity onPress={() => setWindows(prev => prev.filter((_,i)=>i!==idx))}>
              <Ionicons name="close-circle-outline" size={22} color={COLORS.textTertiary} />
            </TouchableOpacity>
          </View>
        ))}

        <TouchableOpacity style={[styles.analyzeBtn, SHADOW.md, loading && { opacity: 0.6 }]}
          onPress={analyze} disabled={loading} activeOpacity={0.85}>
          {loading ? <ActivityIndicator color="#FFF" size="small" /> : <Ionicons name="analytics-outline" size={20} color="#FFF" />}
          <Text style={styles.analyzeBtnText}>{loading ? 'Analysingâ€¦' : 'Analyse'}</Text>
        </TouchableOpacity>

        {results && (
          <>
            <Text style={styles.sectionTitle}>3D Farm View</Text>
            <View style={[styles.viewerContainer, SHADOW.md]}>
              <WebView source={{ html: threeHtml }} style={styles.webview}
                scrollEnabled={false} javaScriptEnabled originWhitelist={['*']} />
            </View>
            <View style={[styles.summaryBanner, SHADOW.sm]}>
              <Ionicons name="checkmark-circle" size={20} color={COLORS.primary} />
              <Text style={styles.summaryText}>{results.coverage_summary}</Text>
            </View>
            <Text style={styles.sectionTitle}>Sensor Positions</Text>
            {results.sensor_positions.map(s => (
              <View key={s.zone_id} style={[styles.sensorCard, SHADOW.sm]}>
                <View style={[styles.zoneTag, { backgroundColor: s.zone_color }]}>
                  <Text style={styles.zoneTagText}>Z{s.zone_id + 1}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.sensorTitle}>Zone {s.zone_id + 1}</Text>
                  <Text style={styles.sensorCoords}>X:{s.x}m Â· Y:{s.y}m Â· H:{s.height}m</Text>
                </View>
                <Text style={[styles.coverageText, { color: s.zone_color }]}>{s.coverage_pct}%</Text>
              </View>
            ))}
          </>
        )}
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container:    { flex: 1, backgroundColor: COLORS.bg },
  scroll:       { padding: SPACE.xl },
  intro:        { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20, marginBottom: SPACE.xl },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md },
  sectionRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACE.md },

  modeCard:        { flexDirection: 'row', gap: SPACE.lg, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.xl, marginBottom: SPACE.lg },
  modeCardPrimary: { backgroundColor: COLORS.primary },
  modeIconWrap:    { width: 56, height: 56, borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  modeTitleWhite:  { color: '#FFF', fontSize: FONT.lg, fontWeight: '800' },
  modeSubWhite:    { color: 'rgba(255,255,255,0.7)', fontSize: FONT.xs, marginTop: 2 },
  modeTitle:       { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800' },
  modeSub:         { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2 },
  featureRow:      { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  featureText:     { color: 'rgba(255,255,255,0.85)', fontSize: FONT.xs, flex: 1 },

  compareCard:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },
  compareTitle:   { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', marginBottom: SPACE.md, textAlign: 'center' },
  compareRow:     { flexDirection: 'row' },
  compareCol:     { flex: 1, alignItems: 'center' },
  compareDivider: { width: 1, backgroundColor: COLORS.border, marginHorizontal: SPACE.md },
  compareHead:    { fontSize: FONT.sm, fontWeight: '800', marginBottom: SPACE.sm },
  compareItem:    { color: COLORS.textSecondary, fontSize: FONT.xs, marginBottom: 4, textAlign: 'center' },

  card:     { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.xl },
  row3:     { flexDirection: 'row', gap: SPACE.sm },
  row2:     { flexDirection: 'row', gap: SPACE.md, marginBottom: SPACE.xl },
  dimField: { flex: 1 },
  dimLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '600', marginBottom: 4 },
  dimInput: { backgroundColor: COLORS.bgInput, borderRadius: RADIUS.sm-2, padding: SPACE.md, color: COLORS.text, fontSize: FONT.md, fontWeight: '600', textAlign: 'center' },
  halfCard: { flex: 1, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md },
  stepRow:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', marginTop: SPACE.xs, flexWrap: 'wrap', gap: 4 },
  stepBtn:  { width: 32, height: 32, borderRadius: 8, backgroundColor: COLORS.primaryDim, alignItems: 'center', justifyContent: 'center' },
  stepVal:  { fontSize: FONT.xl, fontWeight: '700', color: COLORS.text, marginHorizontal: SPACE.sm },
  hourChip:       { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 5, backgroundColor: COLORS.bgInput },
  hourChipActive: { backgroundColor: COLORS.primary },
  hourText:       { fontSize: 9, color: COLORS.textTertiary, fontWeight: '600' },
  hourTextActive: { color: '#FFF' },
  addBtn:         { flexDirection: 'row', alignItems: 'center', gap: 4 },
  addText:        { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },
  windowRow:      { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm },
  wallChip:       { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 5, borderRadius: 6 },
  wallText:       { fontSize: FONT.xs, fontWeight: '700' },
  analyzeBtn:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, padding: SPACE.lg, marginVertical: SPACE.lg },
  analyzeBtnText: { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  viewerContainer:{ height: 300, borderRadius: RADIUS.md, overflow: 'hidden', backgroundColor: '#1a1e2e', marginBottom: SPACE.lg },
  webview:        { flex: 1, backgroundColor: 'transparent' },
  summaryBanner:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xl },
  summaryText:    { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600', flex: 1 },
  sensorCard:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm },
  zoneTag:        { width: 40, height: 40, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  zoneTagText:    { color: '#FFF', fontWeight: '800', fontSize: FONT.sm },
  sensorTitle:    { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  sensorCoords:   { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 2, fontVariant: ['tabular-nums'] },
  coverageText:   { fontSize: FONT.sm, fontWeight: '700', fontVariant: ['tabular-nums'] },
});

export default FarmPlannerScreen;
