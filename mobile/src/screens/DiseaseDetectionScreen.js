/**
 * DiseaseDetectionScreen — Component 1 (R26-SE-018)
 *
 * Upload a photograph of an orchid leaf and get back a disease name, a severity
 * grade and a treatment recommendation.
 *
 * The screen has FOUR outcomes, and keeping them separate is the point:
 *
 *   1. healthy        green  — no disease, preventive advice only
 *   2. disease found  amber/red — name, confidence, severity, full treatment
 *   3. unidentified   amber — the photo is not healthy, and not one of the two
 *                     trained diseases. NOT a crash and NOT an error: the model
 *                     knows three classes, so anything else falls below the
 *                     confidence threshold and is referred for expert review.
 *   4. request failed red   — network down, server off, models missing, bad
 *                     file. Caught with try/catch and shown with a Retry button.
 *
 * Camera capture is deliberately not wired up yet — gallery upload first.
 */

import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  Image,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Animated,
  Alert,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { detectDisease, ApiError } from '../services/diseaseApi';
import { addToHistory } from '../services/diseaseHistory';
import { CONFIDENCE_THRESHOLD } from '../config/api';

/** Turn 'black_leaf_spot' into 'Black Leaf Spot'. */
const prettyName = (key = '') =>
  key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

const SEVERITY_STYLE = {
  mild: { color: COLORS.success, dim: COLORS.successDim, label: 'Mild', note: 'under 10% of leaf area' },
  moderate: { color: COLORS.warning, dim: COLORS.warningDim, label: 'Moderate', note: '10–40% of leaf area' },
  severe: { color: COLORS.danger, dim: COLORS.dangerDim, label: 'Severe', note: 'over 40% of leaf area' },
};

const DiseaseDetectionScreen = ({ navigation }) => {
  const [imageUri, setImageUri] = useState(null);
  // The whole picker asset is kept, not just the uri: it carries the real
  // mimeType and fileName, which the upload needs to build a multipart part
  // the server can read.
  const [imageAsset, setImageAsset] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const fadeAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
  }, []);

  /* ------------------------------------------------------------------ */
  /* picking an image                                                    */
  /* ------------------------------------------------------------------ */

  const pickImage = async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Permission needed',
          'Allow photo access so the app can read the picture you choose. ' +
            'You can enable it in your phone settings.'
        );
        return;
      }

      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        quality: 0.8, // smaller upload; the model resizes to 224px anyway
        allowsEditing: false,
      });

      if (picked.canceled) return;

      const asset = picked.assets?.[0];
      if (!asset?.uri) {
        setError({ message: 'Could not read that photo.', hint: 'Try a different image.' });
        return;
      }

      // A new photo invalidates the previous answer.
      setImageUri(asset.uri);
      setImageAsset(asset);
      setResult(null);
      setError(null);
    } catch (err) {
      setError({
        message: 'Could not open your photo library.',
        hint: err?.message || 'Try again, or restart the app.',
      });
    }
  };


  /**
   * Capture a new photograph with the device camera.
   *
   * Uses expo-image-picker's launchCameraAsync rather than expo-camera. That
   * opens the phone's own camera app, which already handles focus, exposure and
   * the shutter; expo-camera would mean building and maintaining that UI here
   * for no benefit. It also needs no extra dependency -- expo-image-picker is
   * already used for the gallery.
   *
   * Camera permission is separate from photo-library permission, so it is
   * requested separately.
   */
  const takePhoto = async () => {
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        Alert.alert(
          'Camera permission needed',
          'Allow camera access to photograph a plant. You can enable it in your phone settings.'
        );
        return;
      }

      const shot = await ImagePicker.launchCameraAsync({
        quality: 0.9,
        allowsEditing: false,
        exif: true,   // keep EXIF; the backend applies the orientation tag
      });

      if (shot.canceled) return;

      const a = shot.assets?.[0];
      if (!a?.uri) {
        setError({ message: 'Could not read that photo.', hint: 'Try taking it again.' });
        return;
      }
      setImageUri(a.uri);
      setImageAsset(a);
      setResult(null);
      setError(null);
    } catch (err) {
      setError({
        message: 'Could not open the camera.',
        hint: err?.message || 'Try choosing a photo from your gallery instead.',
      });
    }
  };

  /* ------------------------------------------------------------------ */
  /* analysing                                                           */
  /* ------------------------------------------------------------------ */

  const analyse = async () => {
    if (!imageUri || loading) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await detectDisease(imageAsset || imageUri);
      setResult(data);

      // Record it locally. addToHistory swallows its own errors and returns
      // null on failure -- a history write must never stop the user seeing the
      // diagnosis they just asked for, so it is not awaited into the try/catch
      // that reports analysis failures.
      addToHistory(data, imageUri);
    } catch (err) {
      // Everything the service could not handle arrives here as an ApiError
      // with a message written for a person, plus a practical hint.
      if (err instanceof ApiError) {
        setError({ message: err.message, hint: err.hint, kind: err.kind });
      } else {
        setError({
          message: 'Something went wrong while analysing the photo.',
          hint: err?.message || 'Please try again.',
        });
      }
    } finally {
      // finally, so the spinner always stops even if something above threw.
      setLoading(false);
    }
  };

  const reset = () => {
    setImageUri(null);
    setImageAsset(null);
    setResult(null);
    setError(null);
  };

  /* ------------------------------------------------------------------ */
  /* small pieces                                                        */
  /* ------------------------------------------------------------------ */

  const ProbabilityBar = ({ label, value, tint }) => (
    <View style={styles.probRow}>
      <Text style={styles.probLabel} numberOfLines={1}>
        {label}
      </Text>
      <View style={styles.probTrack}>
        <View
          style={[
            styles.probFill,
            { width: `${Math.max(2, Math.round(value * 100))}%`, backgroundColor: tint },
          ]}
        />
      </View>
      <Text style={styles.probValue}>{(value * 100).toFixed(1)}%</Text>
    </View>
  );

  const Bullets = ({ title, icon, items, tint }) => {
    if (!items || items.length === 0) return null;
    return (
      <View style={styles.block}>
        <View style={styles.blockHeader}>
          <Ionicons name={icon} size={16} color={tint} />
          <Text style={styles.blockTitle}>{title}</Text>
        </View>
        {items.map((line, i) => (
          <View key={i} style={styles.bulletRow}>
            <View style={[styles.bulletDot, { backgroundColor: tint }]} />
            <Text style={styles.bulletText}>{line}</Text>
          </View>
        ))}
      </View>
    );
  };

  /* ------------------------------------------------------------------ */
  /* result rendering                                                    */
  /* ------------------------------------------------------------------ */

  const renderResult = () => {
    if (!result) return null;

    // ORDER MATTERS. invalid_image also has confident === false, so it must be
    // tested BEFORE isUnidentified or it would fall through and be described as
    // "not healthy, see an expert" -- the wrong advice for a photo of lunch.
    const isInvalidImage = result.disease === 'invalid_image';
    const isUnidentified = !isInvalidImage &&
      (result.disease === 'unidentified' || !result.confident);
    const isHealthy = result.disease === 'healthy';
    const treatment = result.treatment || {};

    /* ---- outcome 0: not a Vanda orchid at all ----
       Deliberately shows NO disease name, NO "Healthy", and NO confidence
       figure. The classifier was never run: a 3-way softmax always picks one of
       its three classes, so on a photograph of food it reported healthy at
       99.9%. The validator caught it on feature distance instead. */
    if (isInvalidImage) {
      return (
        <View style={[styles.resultCard, styles.cardWarning, SHADOW.md]}>
          <View style={styles.verdictRow}>
            <View style={[styles.verdictIcon, { backgroundColor: COLORS.dangerDim }]}>
              <Ionicons name="image-outline" size={26} color={COLORS.danger} />
            </View>
            <View style={styles.verdictText}>
              <Text style={styles.verdictLabel}>NOT AN ORCHID</Text>
              <Text style={[styles.verdictName, { color: COLORS.danger }]}>
                Invalid image
              </Text>
            </View>
          </View>

          <Text style={styles.explain}>
            Please upload a clear image of a Vanda orchid leaf or stem. No
            diagnosis was attempted, because this photograph does not look like
            an orchid.
          </Text>

          <Bullets
            title="For a good photo"
            icon="camera-outline"
            items={treatment.immediate_actions}
            tint={COLORS.primary}
          />

          <TouchableOpacity style={styles.retryBtn} onPress={pickImage}>
            <Ionicons name="images-outline" size={17} color={COLORS.textInverse} />
            <Text style={styles.retryText}>Choose another photo</Text>
          </TouchableOpacity>
        </View>
      );
    }

    /* ---- outcome 3: not one of the three trained classes ---- */
    if (isUnidentified) {
      return (
        <View style={[styles.resultCard, styles.cardWarning, SHADOW.md]}>
          <View style={styles.verdictRow}>
            <View style={[styles.verdictIcon, { backgroundColor: COLORS.warningDim }]}>
              <Ionicons name="help-circle" size={26} color={COLORS.warning} />
            </View>
            <View style={styles.verdictText}>
              <Text style={styles.verdictLabel}>Not recognised</Text>
              <Text style={[styles.verdictName, { color: COLORS.warning }]}>
                Unidentified condition
              </Text>
            </View>
          </View>

          <Text style={styles.explain}>
            This plant does not look healthy, but the system is not confident enough to
            name the condition.
          </Text>

          <View style={styles.infoStrip}>
            <Ionicons name="information-circle-outline" size={15} color={COLORS.info} />
            <Text style={styles.infoStripText}>
              The system was trained on Black Leaf Spot, Phyllosticta Leaf Spot and
              healthy leaves only. Its best guess was{' '}
              <Text style={styles.bold}>{prettyName(result.raw_prediction)}</Text> at{' '}
              <Text style={styles.bold}>{(result.confidence * 100).toFixed(1)}%</Text>,
              below the {(CONFIDENCE_THRESHOLD * 100).toFixed(0)}% threshold needed to
              give a diagnosis.
            </Text>
          </View>

          <Bullets
            title="What to do"
            icon="alert-circle-outline"
            tint={COLORS.warning}
            items={treatment.immediate_actions}
          />

          <View style={styles.probSection}>
            <Text style={styles.probHeading}>How confident the system was</Text>
            {Object.entries(result.probabilities || {}).map(([k, v]) => (
              <ProbabilityBar key={k} label={prettyName(k)} value={v} tint={COLORS.textTertiary} />
            ))}
          </View>
        </View>
      );
    }

    /* ---- outcome 1: healthy ---- */
    if (isHealthy) {
      return (
        <View style={[styles.resultCard, styles.cardSuccess, SHADOW.md]}>
          <View style={styles.verdictRow}>
            <View style={[styles.verdictIcon, { backgroundColor: COLORS.successDim }]}>
              <Ionicons name="checkmark-circle" size={26} color={COLORS.success} />
            </View>
            <View style={styles.verdictText}>
              <Text style={styles.verdictLabel}>No disease detected</Text>
              <Text style={[styles.verdictName, { color: COLORS.success }]}>Healthy</Text>
            </View>
            <View style={[styles.confPill, { backgroundColor: COLORS.successDim }]}>
              <Text style={[styles.confPillText, { color: COLORS.success }]}>
                {(result.confidence * 100).toFixed(0)}%
              </Text>
            </View>
          </View>

          <Text style={styles.explain}>{result.explanation}</Text>

          <Bullets
            title="Keep it that way"
            icon="leaf-outline"
            tint={COLORS.success}
            items={treatment.cultural_control}
          />

          <View style={styles.probSection}>
            <Text style={styles.probHeading}>Confidence breakdown</Text>
            {Object.entries(result.probabilities || {}).map(([k, v]) => (
              <ProbabilityBar
                key={k}
                label={prettyName(k)}
                value={v}
                tint={k === 'healthy' ? COLORS.success : COLORS.textTertiary}
              />
            ))}
          </View>
        </View>
      );
    }

    /* ---- outcome 2: a disease was identified ---- */
    const sev = SEVERITY_STYLE[result.severity] || SEVERITY_STYLE.moderate;
    const chem = treatment.chemical_control || {};

    return (
      <View style={[styles.resultCard, styles.cardDanger, SHADOW.md]}>
        <View style={styles.verdictRow}>
          <View style={[styles.verdictIcon, { backgroundColor: COLORS.dangerDim }]}>
            <Ionicons name="bug" size={24} color={COLORS.danger} />
          </View>
          <View style={styles.verdictText}>
            <Text style={styles.verdictLabel}>Disease detected</Text>
            <Text style={[styles.verdictName, { color: COLORS.danger }]}>
              {treatment.display_name || prettyName(result.disease)}
            </Text>
          </View>
          <View style={[styles.confPill, { backgroundColor: COLORS.dangerDim }]}>
            <Text style={[styles.confPillText, { color: COLORS.danger }]}>
              {(result.confidence * 100).toFixed(0)}%
            </Text>
          </View>
        </View>

        {/* severity */}
        {result.severity && (
          <View style={[styles.severityBox, { backgroundColor: sev.dim, borderColor: sev.color }]}>
            <View style={styles.severityTop}>
              <Text style={styles.severityCaption}>Severity</Text>
              <Text style={[styles.severityValue, { color: sev.color }]}>{sev.label}</Text>
            </View>
            <Text style={styles.severityNote}>{sev.note} affected</Text>
            {result.severity_note && (
              <View style={styles.severityWarn}>
                <Ionicons name="alert-circle-outline" size={13} color={COLORS.warning} />
                <Text style={styles.severityWarnText}>{result.severity_note}</Text>
              </View>
            )}
          </View>
        )}

        <View style={styles.metaRow}>
          <View style={styles.metaItem}>
            <Text style={styles.metaLabel}>Plant part</Text>
            <Text style={styles.metaValue}>{prettyName(result.plant_part || 'leaf')}</Text>
          </View>
          <View style={styles.metaItem}>
            <Text style={styles.metaLabel}>Pathogen</Text>
            <Text style={styles.metaValue}>{treatment.pathogen_type || '—'}</Text>
          </View>
        </View>

        <Bullets
          title="Do now"
          icon="flash-outline"
          tint={COLORS.danger}
          items={treatment.immediate_actions}
        />
        <Bullets
          title="Growing conditions"
          icon="leaf-outline"
          tint={COLORS.success}
          items={treatment.cultural_control}
        />

        {/* chemical treatment */}
        <View style={styles.block}>
          <View style={styles.blockHeader}>
            <Ionicons name="flask-outline" size={16} color={COLORS.info} />
            <Text style={styles.blockTitle}>
              Chemical treatment {chem.recommended ? '' : '— not recommended'}
            </Text>
          </View>
          {!!chem.rationale && <Text style={styles.rationale}>{chem.rationale}</Text>}
          {(chem.options || []).map((opt, i) => (
            <View key={i} style={styles.chemCard}>
              <Text style={styles.chemName}>{opt.active_ingredient}</Text>
              <Text style={styles.chemMeta}>
                {opt.type} · FRAC {opt.frac_group}
              </Text>
              <View style={styles.doseBox}>
                <Ionicons
                  name={opt.show_dose ? 'checkmark-circle-outline' : 'warning-outline'}
                  size={13}
                  color={opt.show_dose ? COLORS.success : COLORS.warning}
                />
                <Text style={styles.doseText}>{opt.dose}</Text>
              </View>
            </View>
          ))}
        </View>

        {!!treatment.monitoring && (
          <View style={styles.block}>
            <View style={styles.blockHeader}>
              <Ionicons name="eye-outline" size={16} color={COLORS.info} />
              <Text style={styles.blockTitle}>Monitoring</Text>
            </View>
            <Text style={styles.bodyText}>{treatment.monitoring}</Text>
          </View>
        )}

        {treatment.escalate_to_expert && (
          <View style={styles.expertBox}>
            <Ionicons name="medkit-outline" size={16} color={COLORS.danger} />
            <Text style={styles.expertText}>
              Refer to an expert. {treatment.escalation_reason || ''}
            </Text>
          </View>
        )}

        <Bullets
          title="Safety"
          icon="shield-checkmark-outline"
          tint={COLORS.textSecondary}
          items={treatment.safety}
        />

        <View style={styles.probSection}>
          <Text style={styles.probHeading}>Confidence breakdown</Text>
          {Object.entries(result.probabilities || {}).map(([k, v]) => (
            <ProbabilityBar
              key={k}
              label={prettyName(k)}
              value={v}
              tint={k === result.disease ? COLORS.danger : COLORS.textTertiary}
            />
          ))}
          {!!result.severity_probabilities && (
            <>
              <Text style={[styles.probHeading, { marginTop: SPACE.md }]}>Severity breakdown</Text>
              {Object.entries(result.severity_probabilities).map(([k, v]) => (
                <ProbabilityBar
                  key={k}
                  label={SEVERITY_STYLE[k]?.label || prettyName(k)}
                  value={v}
                  tint={k === result.severity ? sev.color : COLORS.textTertiary}
                />
              ))}
            </>
          )}
        </View>
      </View>
    );
  };

  /* ------------------------------------------------------------------ */

  return (
    <View style={styles.container}>
      <ScreenHeader title="Check a Plant" subtitle="AI Diagnosis" navigation={navigation} showBack />

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          {/* ---------- upload ---------- */}
          {!imageUri ? (
            <View style={[styles.uploadCard, SHADOW.md]}>
              <View style={styles.uploadIcon}>
                <Ionicons name="cloud-upload-outline" size={28} color={COLORS.info} />
              </View>
              <Text style={styles.uploadTitle}>Add a photo</Text>
              <Text style={styles.uploadDesc}>
                A clear, well-lit picture of the affected leaf
              </Text>

              {/* The camera is hidden in a browser: launchCameraAsync is a
                  native-only API, and a button that always fails is worse than
                  no button. On a phone both options appear. */}
              {Platform.OS !== 'web' && (
                <TouchableOpacity
                  style={styles.uploadBtn}
                  onPress={takePhoto}
                  activeOpacity={0.7}
                >
                  <Ionicons name="camera-outline" size={16} color="#FFF" />
                  <Text style={styles.uploadBtnText}>Take a photo</Text>
                </TouchableOpacity>
              )}

              <TouchableOpacity
                style={Platform.OS === 'web' ? styles.uploadBtn : styles.uploadBtnAlt}
                onPress={pickImage}
                activeOpacity={0.7}
              >
                <Ionicons
                  name="images-outline"
                  size={16}
                  color={Platform.OS === 'web' ? '#FFF' : COLORS.primary}
                />
                <Text
                  style={
                    Platform.OS === 'web' ? styles.uploadBtnText : styles.uploadBtnAltText
                  }
                >
                  Choose from gallery
                </Text>
              </TouchableOpacity>

              {Platform.OS === 'web' && (
                <Text style={styles.uploadHint}>
                  Camera capture is available in the phone app
                </Text>
              )}
            </View>
          ) : (
            <View style={[styles.previewCard, SHADOW.md]}>
              <Image source={{ uri: imageUri }} style={styles.preview} resizeMode="cover" />
              <View style={styles.previewActions}>
                <TouchableOpacity
                  style={[styles.secondaryBtn, loading && styles.btnDisabled]}
                  onPress={() => {
                    if (Platform.OS === 'web') { pickImage(); return; }
                    Alert.alert('Replace photo', 'Where should the new photo come from?', [
                      { text: 'Camera', onPress: takePhoto },
                      { text: 'Gallery', onPress: pickImage },
                      { text: 'Cancel', style: 'cancel' },
                    ]);
                  }}
                  disabled={loading}
                  activeOpacity={0.7}
                >
                  <Ionicons name="swap-horizontal-outline" size={15} color={COLORS.primary} />
                  <Text style={styles.secondaryBtnText}>Change</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  style={[styles.primaryBtn, loading && styles.btnDisabled]}
                  onPress={analyse}
                  disabled={loading}
                  activeOpacity={0.85}
                >
                  {loading ? (
                    <>
                      <ActivityIndicator size="small" color="#FFF" />
                      <Text style={styles.primaryBtnText}>Analysing…</Text>
                    </>
                  ) : (
                    <>
                      <Ionicons name="search-outline" size={16} color="#FFF" />
                      <Text style={styles.primaryBtnText}>Analyse photo</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          )}

          {/* ---------- loading note ---------- */}
          {loading && (
            <View style={[styles.noteCard, SHADOW.sm]}>
              <ActivityIndicator size="small" color={COLORS.primary} />
              <Text style={styles.noteText}>
                Checking the leaf against the trained diseases. The first analysis after
                starting the server takes a few seconds longer.
              </Text>
            </View>
          )}

          {/* ---------- outcome 4: request failed ---------- */}
          {error && !loading && (
            <View style={[styles.resultCard, styles.cardDanger, SHADOW.md]}>
              <View style={styles.verdictRow}>
                <View style={[styles.verdictIcon, { backgroundColor: COLORS.dangerDim }]}>
                  <Ionicons name="cloud-offline-outline" size={24} color={COLORS.danger} />
                </View>
                <View style={styles.verdictText}>
                  <Text style={styles.verdictLabel}>Could not analyse</Text>
                  <Text style={[styles.verdictName, { color: COLORS.danger }]}>
                    {error.message}
                  </Text>
                </View>
              </View>

              {!!error.hint && <Text style={styles.errorHint}>{error.hint}</Text>}

              <TouchableOpacity style={styles.retryBtn} onPress={analyse} activeOpacity={0.85}>
                <Ionicons name="refresh-outline" size={15} color="#FFF" />
                <Text style={styles.retryText}>Try again</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* ---------- outcomes 1-3 ---------- */}
          {!loading && renderResult()}

          {/* ---------- start over ---------- */}
          {(result || error) && !loading && (
            <TouchableOpacity style={styles.resetBtn} onPress={reset} activeOpacity={0.7}>
              <Ionicons name="add-circle-outline" size={16} color={COLORS.primary} />
              <Text style={styles.resetText}>Analyse another photo</Text>
            </TouchableOpacity>
          )}

          {/* ---------- what the system knows ---------- */}
          {!result && !error && !loading && (
            <View style={[styles.scopeCard, SHADOW.sm]}>
              <View style={styles.blockHeader}>
                <Ionicons name="information-circle-outline" size={16} color={COLORS.info} />
                <Text style={styles.blockTitle}>What this can identify</Text>
              </View>
              {[
                { n: 'Black Leaf Spot', c: COLORS.danger },
                { n: 'Phyllosticta Leaf Spot', c: COLORS.danger },
                { n: 'Healthy leaf', c: COLORS.success },
              ].map((d, i) => (
                <View key={i} style={styles.scopeRow}>
                  <View style={[styles.bulletDot, { backgroundColor: d.c }]} />
                  <Text style={styles.scopeName}>{d.n}</Text>
                </View>
              ))}
              <Text style={styles.scopeNote}>
                Anything else is reported as an unidentified condition with a
                recommendation to seek expert advice, rather than being forced into one of
                these three.
              </Text>
            </View>
          )}
        </Animated.View>

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },

  /* upload */
  uploadCard: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    padding: SPACE.xxl,
    alignItems: 'center',
    marginBottom: SPACE.xl,
  },
  uploadIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: COLORS.infoDim,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: SPACE.md,
  },
  uploadTitle: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '700', marginBottom: SPACE.xs },
  uploadDesc: {
    color: COLORS.textTertiary,
    fontSize: FONT.sm,
    textAlign: 'center',
    marginBottom: SPACE.lg,
  },
  uploadBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: COLORS.info,
    paddingHorizontal: SPACE.xl,
    paddingVertical: SPACE.md,
    borderRadius: RADIUS.full,
  },
  uploadBtnText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },
  uploadBtnAlt: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, paddingHorizontal: SPACE.xl, paddingVertical: SPACE.md,
    borderRadius: RADIUS.full, backgroundColor: COLORS.primaryDim,
    marginTop: SPACE.sm,
  },
  uploadBtnAltText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  uploadHint: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: SPACE.md },

  /* preview */
  previewCard: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    overflow: 'hidden',
    marginBottom: SPACE.xl,
  },
  preview: { width: '100%', height: 240, backgroundColor: COLORS.bgCardAlt },
  previewActions: { flexDirection: 'row', gap: SPACE.sm, padding: SPACE.lg },
  primaryBtn: {
    flex: 2,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: COLORS.primary,
    paddingVertical: SPACE.md,
    borderRadius: RADIUS.full,
  },
  primaryBtnText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },
  secondaryBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 5,
    backgroundColor: COLORS.primaryDim,
    paddingVertical: SPACE.md,
    borderRadius: RADIUS.full,
  },
  secondaryBtnText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  btnDisabled: { opacity: 0.55 },

  /* loading */
  noteCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACE.md,
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    padding: SPACE.lg,
    marginBottom: SPACE.xl,
  },
  noteText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  /* result shell */
  resultCard: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    padding: SPACE.lg,
    marginBottom: SPACE.lg,
    borderLeftWidth: 3,
  },
  cardSuccess: { borderLeftColor: COLORS.success },
  cardWarning: { borderLeftColor: COLORS.warning },
  cardDanger: { borderLeftColor: COLORS.danger },

  verdictRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.md },
  verdictIcon: {
    width: 46,
    height: 46,
    borderRadius: 23,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: SPACE.md,
  },
  verdictText: { flex: 1 },
  verdictLabel: {
    color: COLORS.textTertiary,
    fontSize: FONT.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  verdictName: { fontSize: FONT.lg, fontWeight: '800', marginTop: 2 },
  confPill: { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs, borderRadius: RADIUS.full },
  confPillText: { fontSize: FONT.sm, fontWeight: '800' },

  explain: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20, marginBottom: SPACE.md },
  bold: { fontWeight: '700', color: COLORS.text },

  infoStrip: {
    flexDirection: 'row',
    gap: SPACE.sm,
    backgroundColor: COLORS.infoDim,
    borderRadius: RADIUS.sm,
    padding: SPACE.md,
    marginBottom: SPACE.md,
  },
  infoStripText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  /* severity */
  severityBox: { borderRadius: RADIUS.sm, borderLeftWidth: 3, padding: SPACE.md, marginBottom: SPACE.md },
  severityTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  severityCaption: {
    color: COLORS.textTertiary,
    fontSize: FONT.xs,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  severityValue: { fontSize: FONT.lg, fontWeight: '800' },
  severityNote: { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 2 },
  severityWarn: { flexDirection: 'row', gap: 5, alignItems: 'flex-start', marginTop: SPACE.sm },
  severityWarnText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16 },

  /* meta */
  metaRow: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.md },
  metaItem: { flex: 1, backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, padding: SPACE.md },
  metaLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: 2 },
  metaValue: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },

  /* blocks */
  block: { marginBottom: SPACE.lg },
  blockHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.sm },
  blockTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', flex: 1 },
  bulletRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm, marginBottom: 6 },
  bulletDot: { width: 5, height: 5, borderRadius: 3, marginTop: 7 },
  bulletText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },
  bodyText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },
  rationale: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17, marginBottom: SPACE.sm },

  /* chemicals */
  chemCard: {
    backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.sm,
    padding: SPACE.md,
    marginBottom: SPACE.sm,
  },
  chemName: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  chemMeta: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, marginBottom: SPACE.sm },
  doseBox: { flexDirection: 'row', gap: 6, alignItems: 'flex-start' },
  doseText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16 },

  /* expert */
  expertBox: {
    flexDirection: 'row',
    gap: SPACE.sm,
    alignItems: 'flex-start',
    backgroundColor: COLORS.dangerDim,
    borderRadius: RADIUS.sm,
    padding: SPACE.md,
    marginBottom: SPACE.lg,
  },
  expertText: { flex: 1, color: COLORS.text, fontSize: FONT.sm, fontWeight: '600', lineHeight: 19 },

  /* probabilities */
  probSection: { borderTopWidth: 1, borderTopColor: COLORS.borderLight, paddingTop: SPACE.md },
  probHeading: {
    color: COLORS.textTertiary,
    fontSize: FONT.xs,
    fontWeight: '700',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: SPACE.sm,
  },
  probRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: 6 },
  probLabel: { width: 128, color: COLORS.textSecondary, fontSize: FONT.xs },
  probTrack: { flex: 1, height: 6, backgroundColor: COLORS.bgCardAlt, borderRadius: 3, overflow: 'hidden' },
  probFill: { height: '100%', borderRadius: 3 },
  probValue: { width: 46, textAlign: 'right', color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '600' },

  /* error */
  errorHint: {
    color: COLORS.textSecondary,
    fontSize: FONT.sm,
    lineHeight: 20,
    backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.sm,
    padding: SPACE.md,
    marginBottom: SPACE.md,
  },
  retryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: COLORS.danger,
    paddingVertical: SPACE.md,
    borderRadius: RADIUS.full,
  },
  retryText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },

  /* reset */
  resetBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: SPACE.md,
    marginBottom: SPACE.md,
  },
  resetText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },

  /* scope */
  scopeCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },
  scopeRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: 6 },
  scopeName: { color: COLORS.textSecondary, fontSize: FONT.sm },
  scopeNote: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17, marginTop: SPACE.sm },
});

export default DiseaseDetectionScreen;
