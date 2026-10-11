/**
 * DiseaseContributeScreen — submit a photograph of a condition the system
 * cannot yet identify.
 *
 * WHY THIS EXISTS
 * The classifier knows two leaf diseases and healthy. It has no stem or flower
 * training data at all. This screen collects those images so the system can be
 * extended later. It does NOT extend it today, and the screen says so plainly
 * rather than implying a submitted photo improves anything now.
 *
 * FIVE THINGS THIS SCREEN DELIBERATELY DOES
 *
 * 1. Asks which plant part it is rather than predicting it. With no stem or
 *    flower training images, a prediction would be fabrication.
 *
 * 2. Asks WHO confirmed the diagnosis, not merely whether. The server stores
 *    `verification_source`, so if a role system is added later, admin-reviewed
 *    entries can outrank self-attested ones without migrating any data. There
 *    are no user roles today by design -- user management is out of scope for
 *    this component, so any user may contribute and attestation carries the
 *    responsibility.
 *
 * 3. Treats the "8 / 30" counter as a GATE and explains it. A class trained on
 *    a handful of images has a decision boundary drawn from almost no evidence
 *    and steals predictions from classes that already work.
 *
 * 4. Never claims the model has learned anything. The confirmation screen says
 *    how many more images are needed.
 *
 * 5. Catches every failure. A network problem, a rejected form or an unreadable
 *    file all surface as a readable message rather than a crash.
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, Image, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Switch, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { contributeImage, getPendingCounts, ApiError } from '../services/diseaseApi';

const PARTS = [
  { key: 'leaf', label: 'Leaf', icon: 'leaf-outline' },
  { key: 'stem', label: 'Stem', icon: 'git-commit-outline' },
  { key: 'flower', label: 'Flower', icon: 'flower-outline' },
];

const SEVERITIES = [
  { key: 'mild', label: 'Mild', note: 'under 10%', color: COLORS.success },
  { key: 'moderate', label: 'Moderate', note: '10–40%', color: COLORS.warning },
  { key: 'severe', label: 'Severe', note: 'over 40%', color: COLORS.danger },
];

const DiseaseContributeScreen = ({ navigation }) => {
  const [asset, setAsset] = useState(null);
  const [disease, setDisease] = useState('');
  const [plantPart, setPlantPart] = useState(null);
  const [severity, setSeverity] = useState(null);
  const [verified, setVerified] = useState(false);
  const [verifiedBy, setVerifiedBy] = useState('');
  const [notes, setNotes] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [counts, setCounts] = useState(null);

  // Refreshed on focus so a contribution made elsewhere is reflected too. The
  // counters are optional: a failure here must not block the form.
  useFocusEffect(
    useCallback(() => {
      let active = true;
      getPendingCounts()
        .then((c) => active && setCounts(c))
        .catch(() => active && setCounts(null));
      return () => { active = false; };
    }, [result])
  );


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
      setAsset(a);
      setError(null);
      setResult(null);
    } catch (err) {
      setError({
        message: 'Could not open the camera.',
        hint: err?.message || 'Try choosing a photo from your gallery instead.',
      });
    }
  };

  const pickImage = async () => {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Permission needed',
          'Allow photo access so the app can read the picture you choose.');
        return;
      }
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'], quality: 0.9, allowsEditing: false,
      });
      if (picked.canceled) return;
      const a = picked.assets?.[0];
      if (a?.uri) {
        setAsset(a);
        setError(null);
        setResult(null);
      }
    } catch (err) {
      setError({ message: 'Could not open your photo library.', hint: err?.message });
    }
  };

  const missing = [];
  if (!asset) missing.push('a photograph');
  if (!disease.trim()) missing.push('the disease name');
  if (!plantPart) missing.push('the plant part');
  if (!severity) missing.push('the severity');
  if (verified && !verifiedBy.trim()) missing.push('who confirmed it');
  const canSubmit = missing.length === 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await contributeImage(asset, {
        disease: disease.trim(),
        plantPart,
        severity,
        verified,
        verifiedBy: verifiedBy.trim(),
        notes: notes.trim(),
      });
      setResult(r);
    } catch (err) {
      setError(err instanceof ApiError
        ? { message: err.message, hint: err.hint }
        : { message: 'Could not submit the photograph.', hint: err?.message });
    } finally {
      // finally, so the spinner always stops even if something above threw.
      setSubmitting(false);
    }
  };

  const startAnother = () => {
    setAsset(null); setDisease(''); setPlantPart(null); setSeverity(null);
    setVerified(false); setVerifiedBy(''); setNotes('');
    setResult(null); setError(null);
  };

  /* ------------------------------------------------------------------ */
  /* confirmation                                                        */
  /* ------------------------------------------------------------------ */

  if (result) {
    const pct = Math.min(100, Math.round(
      (result.count_verified / result.minimum_required) * 100));
    return (
      <View style={styles.container}>
        <ScreenHeader title="Thank you" subtitle="Contribution received"
          navigation={navigation} showBack />
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={[styles.card, SHADOW.md]}>
            <View style={styles.doneIcon}>
              <Ionicons name="checkmark-circle" size={40} color={COLORS.success} />
            </View>
            <Text style={styles.doneTitle}>Photograph stored</Text>
            <Text style={styles.doneSub}>
              Saved as {result.image_id} under {result.disease.replace(/_/g, ' ')}.
            </Text>

            <View style={styles.progressBox}>
              <View style={styles.progressTop}>
                <Text style={styles.progressLabel}>
                  {result.disease.replace(/_/g, ' ')}
                </Text>
                <Text style={styles.progressCount}>
                  {result.count_verified} / {result.minimum_required}
                </Text>
              </View>
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, { width: `${Math.max(2, pct)}%` }]} />
              </View>
              <Text style={styles.progressNote}>
                {result.ready_for_training
                  ? 'Enough images have been collected. A researcher can now retrain the model — the new version replaces the current one only if accuracy does not get worse.'
                  : `${result.needed} more confirmed image${result.needed === 1 ? '' : 's'} needed before this condition can be added.`}
              </Text>
            </View>

            {!result.verified && (
              <View style={styles.warnBox}>
                <Ionicons name="alert-circle-outline" size={16} color={COLORS.warning} />
                <Text style={styles.warnText}>
                  This image was not confirmed by an institute, so it is stored
                  but will not be used for training.
                </Text>
              </View>
            )}

            <Text style={styles.doneFoot}>
              The system has not changed. Your photograph joins a collection a
              researcher reviews before any retraining happens.
            </Text>

            <TouchableOpacity style={styles.primaryBtn} onPress={startAnother}>
              <Ionicons name="add" size={18} color={COLORS.textInverse} />
              <Text style={styles.primaryBtnText}>Contribute another</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.secondaryBtn} onPress={() => navigation.goBack()}>
              <Text style={styles.secondaryBtnText}>Done</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </View>
    );
  }

  /* ------------------------------------------------------------------ */
  /* the form                                                            */
  /* ------------------------------------------------------------------ */

  return (
    <KeyboardAvoidingView style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScreenHeader title="Contribute" subtitle="Help extend the system"
        navigation={navigation} showBack />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

        <View style={styles.introCard}>
          <Ionicons name="information-circle-outline" size={18} color={COLORS.info} />
          <Text style={styles.introText}>
            The system currently recognises two leaf diseases. If you have a
            photograph of a condition it cannot identify — including stems and
            flowers — submitting it here helps it be added in a future version.
          </Text>
        </View>

        <Text style={styles.sectionLabel}>PHOTOGRAPH</Text>
        {asset ? (
          <View style={[styles.card, SHADOW.sm]}>
            <Image source={{ uri: asset.uri }} style={styles.preview} resizeMode="cover" />
            <TouchableOpacity
              style={styles.changeBtn}
              onPress={() => {
                if (Platform.OS === 'web') { pickImage(); return; }
                Alert.alert('Replace photo', 'Where should the new photo come from?', [
                  { text: 'Camera', onPress: takePhoto },
                  { text: 'Gallery', onPress: pickImage },
                  { text: 'Cancel', style: 'cancel' },
                ]);
              }}
            >
              <Ionicons name="swap-horizontal" size={16} color={COLORS.primary} />
              <Text style={styles.changeBtnText}>Change photo</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View style={[styles.uploadCard, SHADOW.sm]}>
            <Ionicons name="images-outline" size={34} color={COLORS.primary} />
            <Text style={styles.uploadTitle}>Add a photograph</Text>
            <Text style={styles.uploadHint}>
              Fill the frame with the affected part, in daylight or bright shade
            </Text>

            <View style={styles.pickRow}>
              {/* Native only: launchCameraAsync does not work in a browser. */}
              {Platform.OS !== 'web' && (
                <TouchableOpacity style={styles.pickBtn} onPress={takePhoto}>
                  <Ionicons name="camera-outline" size={16} color={COLORS.textInverse} />
                  <Text style={styles.pickBtnText}>Camera</Text>
                </TouchableOpacity>
              )}
              <TouchableOpacity
                style={Platform.OS === 'web' ? styles.pickBtn : styles.pickBtnAlt}
                onPress={pickImage}
              >
                <Ionicons
                  name="images-outline"
                  size={16}
                  color={Platform.OS === 'web' ? COLORS.textInverse : COLORS.primary}
                />
                <Text
                  style={Platform.OS === 'web' ? styles.pickBtnText : styles.pickBtnAltText}
                >
                  Gallery
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        <Text style={styles.sectionLabel}>WHAT IS THE CONDITION?</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <TextInput
            style={styles.input}
            placeholder="e.g. Anthracnose"
            placeholderTextColor={COLORS.textTertiary}
            value={disease}
            onChangeText={setDisease}
            autoCapitalize="words"
          />
          <Text style={styles.fieldHint}>The name as given by an expert, if you have one.</Text>
        </View>

        <Text style={styles.sectionLabel}>WHICH PART?</Text>
        <View style={styles.chipRow}>
          {PARTS.map((p) => {
            const on = plantPart === p.key;
            return (
              <TouchableOpacity key={p.key}
                style={[styles.choice, on && styles.choiceOn]}
                onPress={() => setPlantPart(p.key)}>
                <Ionicons name={p.icon} size={18}
                  color={on ? COLORS.textInverse : COLORS.textSecondary} />
                <Text style={[styles.choiceText, on && styles.choiceTextOn]}>{p.label}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <Text style={styles.underHint}>
          You choose this — the system cannot detect the plant part, because it
          has no stem or flower training images.
        </Text>

        <Text style={styles.sectionLabel}>HOW MUCH IS AFFECTED?</Text>
        <View style={styles.chipRow}>
          {SEVERITIES.map((s) => {
            const on = severity === s.key;
            return (
              <TouchableOpacity key={s.key}
                style={[styles.choice, on && { backgroundColor: s.color, borderColor: s.color }]}
                onPress={() => setSeverity(s.key)}>
                <Text style={[styles.choiceText, on && styles.choiceTextOn]}>{s.label}</Text>
                <Text style={[styles.choiceNote, on && styles.choiceTextOn]}>{s.note}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <Text style={styles.underHint}>
          Judged by percentage of the part's area showing symptoms.
        </Text>

        <Text style={styles.sectionLabel}>CONFIRMATION</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <View style={styles.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.switchLabel}>
                Confirmed by an orchid research institute
              </Text>
              <Text style={styles.fieldHint}>
                Only confirmed images count toward training.
              </Text>
            </View>
            <Switch value={verified} onValueChange={setVerified}
              trackColor={{ true: COLORS.primary, false: COLORS.border }}
              thumbColor={COLORS.bgCard} />
          </View>
          {verified && (
            <TextInput
              style={[styles.input, { marginTop: SPACE.md }]}
              placeholder="Which institute or expert?"
              placeholderTextColor={COLORS.textTertiary}
              value={verifiedBy}
              onChangeText={setVerifiedBy}
            />
          )}
        </View>

        <Text style={styles.sectionLabel}>NOTES (OPTIONAL)</Text>
        <View style={[styles.card, SHADOW.sm]}>
          <TextInput
            style={[styles.input, styles.textarea]}
            placeholder="Anything an expert should know"
            placeholderTextColor={COLORS.textTertiary}
            value={notes}
            onChangeText={setNotes}
            multiline
          />
        </View>

        {counts?.diseases?.length > 0 && (
          <>
            <Text style={styles.sectionLabel}>COLLECTED SO FAR</Text>
            <View style={[styles.card, SHADOW.sm]}>
              {counts.diseases.map((d) => (
                <View key={d.disease} style={styles.countRow}>
                  <Text style={styles.countName}>{d.display_name}</Text>
                  <Text style={styles.countValue}>
                    {d.verified} / {counts.minimum_required}
                  </Text>
                </View>
              ))}
              <Text style={styles.fieldHint}>
                A condition needs {counts.minimum_required} confirmed images from
                different plants before it can be added. Fewer would produce an
                unreliable class that degrades the diseases already working.
              </Text>
            </View>
          </>
        )}

        {error && (
          <View style={styles.errorCard}>
            <Ionicons name="alert-circle" size={20} color={COLORS.danger} />
            <View style={{ flex: 1 }}>
              <Text style={styles.errorText}>{error.message}</Text>
              {error.hint ? <Text style={styles.errorHint}>{error.hint}</Text> : null}
            </View>
          </View>
        )}

        <TouchableOpacity
          style={[styles.primaryBtn, !canSubmit && styles.btnDisabled]}
          onPress={submit}
          disabled={!canSubmit}>
          {submitting ? (
            <ActivityIndicator color={COLORS.textInverse} />
          ) : (
            <>
              <Ionicons name="cloud-upload-outline" size={18} color={COLORS.textInverse} />
              <Text style={styles.primaryBtnText}>Submit photograph</Text>
            </>
          )}
        </TouchableOpacity>

        {missing.length > 0 && (
          <Text style={styles.missingText}>Still needed: {missing.join(', ')}</Text>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xxxl * 2 },

  introCard: {
    flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.infoDim,
    borderRadius: RADIUS.md, padding: SPACE.md, marginBottom: SPACE.lg,
  },
  introText: { flex: 1, fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 19 },

  sectionLabel: {
    fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary,
    letterSpacing: 0.8, marginBottom: SPACE.sm, marginTop: SPACE.md,
  },
  card: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
    padding: SPACE.md, borderWidth: 1, borderColor: COLORS.border,
  },

  uploadCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg, padding: SPACE.xl,
    alignItems: 'center', gap: SPACE.sm, borderWidth: 1,
    borderColor: COLORS.border, borderStyle: 'dashed',
  },
  uploadTitle: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  pickRow: { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.md },
  pickBtn: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.xs,
    paddingHorizontal: SPACE.lg, paddingVertical: SPACE.sm,
    backgroundColor: COLORS.primary, borderRadius: RADIUS.full,
  },
  pickBtnText: { color: COLORS.textInverse, fontSize: FONT.sm, fontWeight: '700' },
  pickBtnAlt: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.xs,
    paddingHorizontal: SPACE.lg, paddingVertical: SPACE.sm,
    backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.full,
  },
  pickBtnAltText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  uploadHint: {
    fontSize: FONT.sm, color: COLORS.textTertiary,
    textAlign: 'center', lineHeight: 18,
  },

  preview: {
    width: '100%', height: 200, borderRadius: RADIUS.md,
    backgroundColor: COLORS.bgCardAlt,
  },
  changeBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.xs, marginTop: SPACE.md, paddingVertical: SPACE.sm,
    backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.md,
  },
  changeBtnText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.primary },

  input: {
    backgroundColor: COLORS.bgInput, borderRadius: RADIUS.md,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
    fontSize: FONT.md, color: COLORS.text,
  },
  textarea: { minHeight: 76, textAlignVertical: 'top' },
  fieldHint: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: SPACE.sm, lineHeight: 16 },
  underHint: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: SPACE.sm, lineHeight: 16 },

  chipRow: { flexDirection: 'row', gap: SPACE.sm },
  choice: {
    flex: 1, alignItems: 'center', gap: 2, paddingVertical: SPACE.md,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.border,
  },
  choiceOn: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  choiceText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.textSecondary },
  choiceNote: { fontSize: FONT.xs, color: COLORS.textTertiary },
  choiceTextOn: { color: COLORS.textInverse },

  switchRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  switchLabel: { fontSize: FONT.md, fontWeight: '600', color: COLORS.text },

  countRow: {
    flexDirection: 'row', justifyContent: 'space-between',
    paddingVertical: SPACE.sm, borderBottomWidth: 1, borderBottomColor: COLORS.borderLight,
  },
  countName: { fontSize: FONT.sm, color: COLORS.text, fontWeight: '600' },
  countValue: { fontSize: FONT.sm, color: COLORS.primary, fontWeight: '700' },

  errorCard: {
    flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.dangerDim,
    borderRadius: RADIUS.md, padding: SPACE.md, marginTop: SPACE.lg,
  },
  errorText: { fontSize: FONT.sm, color: COLORS.danger, fontWeight: '600' },
  errorHint: { fontSize: FONT.xs, color: COLORS.textSecondary, marginTop: SPACE.xs, lineHeight: 16 },

  primaryBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, backgroundColor: COLORS.primary, paddingVertical: SPACE.md,
    borderRadius: RADIUS.full, marginTop: SPACE.xl,
  },
  primaryBtnText: { color: COLORS.textInverse, fontWeight: '700', fontSize: FONT.md },
  btnDisabled: { opacity: 0.45 },
  secondaryBtn: { alignItems: 'center', paddingVertical: SPACE.md, marginTop: SPACE.sm },
  secondaryBtnText: { color: COLORS.textSecondary, fontWeight: '600', fontSize: FONT.md },
  missingText: {
    fontSize: FONT.xs, color: COLORS.textTertiary,
    textAlign: 'center', marginTop: SPACE.sm,
  },

  doneIcon: { alignItems: 'center', marginBottom: SPACE.sm },
  doneTitle: { fontSize: FONT.xl, fontWeight: '700', color: COLORS.text, textAlign: 'center' },
  doneSub: {
    fontSize: FONT.sm, color: COLORS.textSecondary,
    textAlign: 'center', marginTop: SPACE.xs,
  },
  progressBox: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
    padding: SPACE.md, marginTop: SPACE.lg,
  },
  progressTop: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: SPACE.sm },
  progressLabel: {
    fontSize: FONT.md, fontWeight: '700', color: COLORS.text,
    textTransform: 'capitalize',
  },
  progressCount: { fontSize: FONT.md, fontWeight: '700', color: COLORS.primary },
  progressTrack: { height: 8, backgroundColor: COLORS.border, borderRadius: 4, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 4 },
  progressNote: { fontSize: FONT.sm, color: COLORS.textSecondary, marginTop: SPACE.sm, lineHeight: 18 },

  warnBox: {
    flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.warningDim,
    borderRadius: RADIUS.md, padding: SPACE.md, marginTop: SPACE.md,
  },
  warnText: { flex: 1, fontSize: FONT.sm, color: COLORS.warning, lineHeight: 18 },
  doneFoot: {
    fontSize: FONT.sm, color: COLORS.textTertiary,
    textAlign: 'center', marginTop: SPACE.lg, lineHeight: 18,
  },
});

export default DiseaseContributeScreen;
