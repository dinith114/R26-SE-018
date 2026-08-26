import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity,
  Dimensions, Platform, Animated, Alert,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

const { width: SW, height: SH } = Dimensions.get('window');
import BASE_URL from '../config/backend';

// â”€â”€ Farm diagram: where to stand for each position â”€â”€
//   Positions 1-8 around the perimeter (clockwise from south)
//   Rendered as a small overhead map
const POS_MAP = [
  { id: 1, bx: 0.5,  by: 1.0,  label: 'S'  },
  { id: 2, bx: 1.0,  by: 1.0,  label: 'SE' },
  { id: 3, bx: 1.0,  by: 0.5,  label: 'E'  },
  { id: 4, bx: 1.0,  by: 0.0,  label: 'NE' },
  { id: 5, bx: 0.5,  by: 0.0,  label: 'N'  },
  { id: 6, bx: 0.0,  by: 0.0,  label: 'NW' },
  { id: 7, bx: 0.0,  by: 0.5,  label: 'W'  },
  { id: 8, bx: 0.0,  by: 1.0,  label: 'SW' },
];

const QUALITY_COLOR = { good: COLORS.success, ok: COLORS.warning, poor: COLORS.danger, error: COLORS.danger };
const QUALITY_ICON  = { good: 'checkmark-circle', ok: 'alert-circle', poor: 'close-circle', error: 'close-circle' };

export default function FarmScanScreen({ route, navigation }) {
  const { sessionId } = route.params;

  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef(null);

  const [currentPos, setCurrentPos]   = useState(1);
  const [captured,   setCaptured]     = useState({});   // pos â†’ analysis
  const [capturing,  setCapturing]    = useState(false);
  const [flash,      setFlash]        = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const pendingPhoto = useRef(null);
  const flashAnim = useRef(new Animated.Value(0)).current;

  const position    = POS_MAP[currentPos - 1];
  const scanPos     = { id: currentPos, stand: `Stand at the ${position.label} position`, face: 'Aim camera to capture walls, floor, and ceiling.' };
  const allCaptured = Object.keys(captured).length >= 8;

  useEffect(() => {
    if (!permission?.granted) requestPermission();
  }, []);

  const triggerFlash = () => {
    setFlash(true);
    Animated.sequence([
      Animated.timing(flashAnim, { toValue: 1, duration: 80,  useNativeDriver: true }),
      Animated.timing(flashAnim, { toValue: 0, duration: 300, useNativeDriver: true }),
    ]).start(() => setFlash(false));
  };

  const doUpload = async (photo, pos) => {
    const form = new FormData();
    form.append('file', { uri: photo.uri, name: 'scan.jpg', type: 'image/jpeg' });
    form.append('session_id', sessionId);
    form.append('position', String(pos));
    const res = await fetch(`${BASE_URL}/api/v1/farm/scan-photo`, { method: 'POST', body: form });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    return res.json();
  };

  const handleResult = (data) => {
    setCaptured(prev => ({ ...prev, [currentPos]: data.analysis }));
    pendingPhoto.current = null;
    setUploadError(null);
    if (data.scan_complete) {
      navigation.replace('FarmModelConfirm', { sessionId });
    } else {
      setCurrentPos(prev => prev < 8 ? prev + 1 : prev);
    }
  };

  const takePhoto = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    setUploadError(null);
    triggerFlash();
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.6, base64: false });
      pendingPhoto.current = { photo, pos: currentPos };
      const data = await doUpload(photo, currentPos);
      handleResult(data);
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setCapturing(false);
    }
  };

  const retryUpload = async () => {
    if (!pendingPhoto.current) return;
    setCapturing(true);
    setUploadError(null);
    try {
      const { photo, pos } = pendingPhoto.current;
      const data = await doUpload(photo, pos);
      handleResult(data);
    } catch (err) {
      setUploadError(err.message);
    } finally {
      setCapturing(false);
    }
  };

  const skipToConfirm = () => {
    Alert.alert(
      'Skip remaining photos?',
      'You can continue with fewer photos â€” dimension accuracy may be lower.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Skip', onPress: () => navigation.replace('FarmModelConfirm', { sessionId }) },
      ]
    );
  };

  if (!permission) return <View style={styles.container} />;

  if (!permission.granted) {
    return (
      <View style={[styles.container, styles.center]}>
        <Ionicons name="camera-outline" size={64} color={COLORS.textTertiary} />
        <Text style={styles.permTitle}>Camera Access Needed</Text>
        <Text style={styles.permSub}>We need camera access to scan your greenhouse.</Text>
        <TouchableOpacity style={styles.permBtn} onPress={requestPermission}>
          <Text style={styles.permBtnText}>Grant Permission</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const MAP_W = 120, MAP_H = 80;

  return (
    <View style={styles.container}>
      {/* â”€â”€ Camera â”€â”€ */}
      <CameraView ref={cameraRef} style={StyleSheet.absoluteFill} facing="back" />

      {/* Flash overlay */}
      <Animated.View pointerEvents="none"
        style={[StyleSheet.absoluteFill, styles.flashOverlay, { opacity: flashAnim }]} />

      {/* â”€â”€ Top HUD â”€â”€ */}
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Ionicons name="arrow-back" size={22} color="#FFF" />
        </TouchableOpacity>
        <View style={styles.progressPill}>
          <Text style={styles.progressText}>
            {Object.keys(captured).length} / 8 captured
          </Text>
        </View>
        {Object.keys(captured).length > 2 && (
          <TouchableOpacity onPress={skipToConfirm} style={styles.skipBtn}>
            <Text style={styles.skipText}>Skip</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* â”€â”€ Overhead map â”€â”€ */}
      <View style={[styles.mapContainer, SHADOW.md]}>
        <View style={[styles.mapBox, { width: MAP_W, height: MAP_H }]}>
          {/* Farm outline */}
          <View style={styles.mapFarm} />
          {/* Position dots */}
          {POS_MAP.map(p => {
            const isCurrent = p.id === currentPos;
            const isDone    = !!captured[p.id];
            return (
              <View key={p.id} style={[styles.mapDot, {
                left:  p.bx * (MAP_W - 16),
                top:   p.by * (MAP_H - 16),
                backgroundColor: isDone ? COLORS.success : isCurrent ? COLORS.warning : 'rgba(255,255,255,0.3)',
                transform: [{ scale: isCurrent ? 1.4 : 1 }],
              }]}>
                {isCurrent && <View style={styles.mapDotPulse} />}
              </View>
            );
          })}
        </View>
        <Text style={styles.mapLabel}>You are here</Text>
      </View>

      {/* â”€â”€ Guide overlay lines â”€â”€ */}
      <View pointerEvents="none" style={styles.guideOverlay}>
        <View style={styles.guideH} />
        <View style={styles.guideV} />
        <View style={styles.guideCornerTL} />
        <View style={styles.guideCornerTR} />
        <View style={styles.guideCornerBL} />
        <View style={styles.guideCornerBR} />
      </View>

      {/* â”€â”€ Instruction card â”€â”€ */}
      <View style={[styles.instructCard, SHADOW.lg]}>
        <View style={styles.instructHeader}>
          <View style={styles.posNumBadge}>
            <Text style={styles.posNum}>{currentPos}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.instructTitle}>Position {currentPos} of 8</Text>
            <Text style={styles.instructLabel}>{position.label} â€” {
              currentPos <= 2 ? 'South area' :
              currentPos <= 4 ? 'East area'  :
              currentPos <= 6 ? 'North area' : 'West area'
            }</Text>
          </View>
        </View>

        <Text style={styles.instructStand}>
          ðŸ“ Stand at the <Text style={styles.bold}>{position.label}</Text> position
        </Text>
        <Text style={styles.instructFace}>
          ðŸ“· Aim camera to capture <Text style={styles.bold}>both walls, floor, and ceiling</Text>
        </Text>

        {/* Done positions */}
        <View style={styles.doneRow}>
          {POS_MAP.map(p => (
            <View key={p.id} style={[
              styles.doneDot,
              captured[p.id] ? styles.doneDotFilled : p.id === currentPos ? styles.doneDotActive : null,
            ]}>
              {captured[p.id] && (
                <Ionicons name={QUALITY_ICON[captured[p.id]?.quality] || 'checkmark'}
                  size={8} color="#FFF" />
              )}
            </View>
          ))}
        </View>
      </View>

      {/* â”€â”€ Capture button â”€â”€ */}
      <View style={styles.captureArea}>
        {uploadError ? (
          <View style={styles.errorBanner}>
            <Ionicons name="wifi-outline" size={14} color="#FF5722" />
            <Text style={styles.errorText}>Upload failed â€” photo saved</Text>
            <TouchableOpacity onPress={retryUpload} style={styles.retryBtn} disabled={capturing}>
              <Text style={styles.retryText}>{capturing ? 'â€¦' : 'Retry'}</Text>
            </TouchableOpacity>
          </View>
        ) : captured[currentPos] ? (
          <View style={styles.capturedBadge}>
            <Ionicons
              name={QUALITY_ICON[captured[currentPos]?.quality]}
              size={16}
              color={QUALITY_COLOR[captured[currentPos]?.quality]}
            />
            <Text style={[styles.capturedText, { color: QUALITY_COLOR[captured[currentPos]?.quality] }]}>
              {captured[currentPos]?.quality === 'good' ? 'Photo OK â€” move to next' :
               captured[currentPos]?.quality === 'ok'   ? 'Accepted â€” retake or continue' :
               'Poor quality â€” please retake'}
            </Text>
          </View>
        ) : null}
        <TouchableOpacity
          onPress={takePhoto}
          disabled={capturing}
          style={[styles.captureBtn, capturing && styles.captureBtnDisabled]}
          activeOpacity={0.8}
        >
          <View style={styles.captureBtnInner} />
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center:    { alignItems: 'center', justifyContent: 'center', padding: SPACE.xl },

  flashOverlay: { backgroundColor: '#FFF' },

  topBar: {
    position: 'absolute', top: 52, left: 0, right: 0,
    flexDirection: 'row', alignItems: 'center',
    paddingHorizontal: SPACE.xl, gap: SPACE.md,
  },
  backBtn:      { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(0,0,0,0.4)', alignItems: 'center', justifyContent: 'center' },
  progressPill: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', borderRadius: RADIUS.full, paddingHorizontal: SPACE.lg, paddingVertical: 6, alignItems: 'center' },
  progressText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },
  skipBtn:      { paddingHorizontal: SPACE.md, paddingVertical: 6, backgroundColor: 'rgba(255,255,255,0.2)', borderRadius: RADIUS.full },
  skipText:     { color: '#FFF', fontSize: FONT.sm, fontWeight: '600' },

  mapContainer: { position: 'absolute', top: 108, right: SPACE.xl, alignItems: 'center' },
  mapBox:       { borderRadius: RADIUS.sm, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.3)', overflow: 'hidden', backgroundColor: 'rgba(0,0,0,0.5)' },
  mapFarm:      { position: 'absolute', inset: 6, borderWidth: 1, borderColor: 'rgba(255,255,255,0.4)' },
  mapDot:       { position: 'absolute', width: 14, height: 14, borderRadius: 7 },
  mapDotPulse:  { position: 'absolute', inset: -3, borderRadius: 10, borderWidth: 2, borderColor: COLORS.warning, opacity: 0.6 },
  mapLabel:     { color: 'rgba(255,255,255,0.6)', fontSize: 9, marginTop: 3, fontWeight: '600' },

  guideOverlay: { position: 'absolute', inset: 0, alignItems: 'center', justifyContent: 'center' },
  guideH:       { position: 'absolute', width: '70%', height: 1, backgroundColor: 'rgba(255,255,255,0.25)' },
  guideV:       { position: 'absolute', height: '70%', width: 1, backgroundColor: 'rgba(255,255,255,0.25)' },
  guideCornerTL: { position: 'absolute', top: SW*0.15, left: SW*0.15, width: 24, height: 24, borderTopWidth: 2, borderLeftWidth: 2, borderColor: 'rgba(255,255,255,0.7)' },
  guideCornerTR: { position: 'absolute', top: SW*0.15, right: SW*0.15, width: 24, height: 24, borderTopWidth: 2, borderRightWidth: 2, borderColor: 'rgba(255,255,255,0.7)' },
  guideCornerBL: { position: 'absolute', bottom: SW*0.45, left: SW*0.15, width: 24, height: 24, borderBottomWidth: 2, borderLeftWidth: 2, borderColor: 'rgba(255,255,255,0.7)' },
  guideCornerBR: { position: 'absolute', bottom: SW*0.45, right: SW*0.15, width: 24, height: 24, borderBottomWidth: 2, borderRightWidth: 2, borderColor: 'rgba(255,255,255,0.7)' },

  instructCard: {
    position: 'absolute', bottom: 170, left: SPACE.xl, right: SPACE.xl,
    backgroundColor: 'rgba(10,12,20,0.88)', borderRadius: RADIUS.md, padding: SPACE.lg,
  },
  instructHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.md },
  posNumBadge:    { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
  posNum:         { color: '#FFF', fontSize: FONT.lg, fontWeight: '800' },
  instructTitle:  { color: '#FFF', fontSize: FONT.md, fontWeight: '700' },
  instructLabel:  { color: 'rgba(255,255,255,0.5)', fontSize: FONT.xs, marginTop: 1 },
  instructStand:  { color: 'rgba(255,255,255,0.9)', fontSize: FONT.sm, marginBottom: 4 },
  instructFace:   { color: 'rgba(255,255,255,0.7)', fontSize: FONT.sm, marginBottom: SPACE.md },
  bold:           { fontWeight: '700', color: '#FFF' },

  doneRow: { flexDirection: 'row', gap: 6 },
  doneDot: { width: 20, height: 20, borderRadius: 10, backgroundColor: 'rgba(255,255,255,0.15)', alignItems: 'center', justifyContent: 'center' },
  doneDotFilled: { backgroundColor: COLORS.success },
  doneDotActive: { backgroundColor: COLORS.warning, borderWidth: 2, borderColor: '#FFF' },

  captureArea:   { position: 'absolute', bottom: 52, left: 0, right: 0, alignItems: 'center' },
  capturedBadge: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: RADIUS.full, paddingHorizontal: SPACE.lg, paddingVertical: 6, marginBottom: SPACE.lg },
  capturedText:  { fontSize: FONT.xs, fontWeight: '600' },
  errorBanner:   { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: 'rgba(180,30,0,0.85)', borderRadius: RADIUS.full, paddingHorizontal: SPACE.lg, paddingVertical: 8, marginBottom: SPACE.lg },
  errorText:     { color: '#FFF', fontSize: FONT.xs, fontWeight: '600', flex: 1 },
  retryBtn:      { backgroundColor: '#FF5722', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 4 },
  retryText:     { color: '#FFF', fontSize: FONT.xs, fontWeight: '800' },
  captureBtn:        { width: 76, height: 76, borderRadius: 38, borderWidth: 4, borderColor: '#FFF', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.15)' },
  captureBtnDisabled:{ opacity: 0.5 },
  captureBtnInner:   { width: 58, height: 58, borderRadius: 29, backgroundColor: '#FFF' },

  permTitle: { color: COLORS.text, fontSize: FONT.xl, fontWeight: '700', marginTop: SPACE.xl, textAlign: 'center' },
  permSub:   { color: COLORS.textTertiary, fontSize: FONT.sm, textAlign: 'center', marginTop: SPACE.sm, marginBottom: SPACE.xl },
  permBtn:   { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.xl, paddingVertical: SPACE.md },
  permBtnText: { color: '#FFF', fontWeight: '700', fontSize: FONT.md },
});
