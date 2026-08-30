import React, { useRef, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated, ActivityIndicator, Alert, Image, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { ref, set } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import CompatibilityTab from '../components/CompatibilityTab';
import { assessSuitability, getGuidance, getKnownParents, getApiBaseUrl } from '../services/api';

const HybridPollinationScreen = ({ navigation }) => {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scrollViewRef = useRef(null);
  
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  // ── State ──────────────────────────────────
  const [selectedImage, setSelectedImage] = useState(null);
  const [traits, setTraits] = useState({
    leaf_condition: null,
    plant_strength: null,
    disease_visible: null,
    flower_condition: null,
  });
  const [result, setResult] = useState(null);
  // Set when the input gate refuses the photograph as not an orchid.
  const [rejection, setRejection] = useState(null);
  // Corrections start folded: the photograph answers all four traits,
  // so showing empty inputs first is what made the system look input-driven.
  const [showCorrections, setShowCorrections] = useState(false);
  const [loading, setLoading] = useState(false);
  const [guidanceData, setGuidanceData] = useState(null);
  const [activeTab, setActiveTab] = useState('assess'); // 'assess' | 'cross' | 'varieties'

  // ── Trait Options ──────────────────────────
  const traitOptions = {
    leaf_condition: ['healthy', 'moderate', 'weak'],
    plant_strength: ['strong', 'moderate', 'weak'],
    disease_visible: ['no', 'yes'],
    flower_condition: ['good', 'moderate', 'weak', 'unknown'],
  };

  const traitLabels = {
    leaf_condition: 'Leaf Condition',
    plant_strength: 'Plant Strength',
    disease_visible: 'Disease Visible',
    flower_condition: 'Flower Condition',
  };

  const traitIcons = {
    leaf_condition: 'leaf-outline',
    plant_strength: 'fitness-outline',
    disease_visible: 'bug-outline',
    flower_condition: 'flower-outline',
  };

  // ── Image Picker ──────────────────────────
  const pickImage = async () => {
    const permResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permResult.granted) {
      Alert.alert('Permission needed', 'Please allow access to your photo library.');
      return;
    }

    const pickerResult = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.8,
      allowsEditing: true,
    });

    if (!pickerResult.canceled && pickerResult.assets?.[0]) {
      setSelectedImage(pickerResult.assets[0].uri);
      setResult(null);
      setRejection(null);
      setTraits({
        leaf_condition: null,
        plant_strength: null,
        disease_visible: null,
        flower_condition: null,
      });
    }
  };

  const takePhoto = async () => {
    const permResult = await ImagePicker.requestCameraPermissionsAsync();
    if (!permResult.granted) {
      Alert.alert('Permission needed', 'Please allow access to your camera.');
      return;
    }

    const pickerResult = await ImagePicker.launchCameraAsync({
      quality: 0.8,
      allowsEditing: true,
    });

    if (!pickerResult.canceled && pickerResult.assets?.[0]) {
      setSelectedImage(pickerResult.assets[0].uri);
      setResult(null);
      setRejection(null);
      setTraits({
        leaf_condition: null,
        plant_strength: null,
        disease_visible: null,
        flower_condition: null,
      });
    }
  };

  // ── Predict ───────────────────────────────
  const handlePredict = async () => {
    if (!selectedImage) {
      Alert.alert('No Image', 'Please select or capture an orchid plant image first.');
      return;
    }

    setLoading(true);
    setResult(null);
    setRejection(null);

    try {
      const response = await assessSuitability(selectedImage, traits);
      setResult(response);

      // Auto-fetch guidance
      const guide = await getGuidance(response.suitability);
      setGuidanceData(guide.guidance);

      // Auto-scroll to results after they render
      setTimeout(() => {
        scrollViewRef.current?.scrollToEnd({ animated: true });
      }, 200);

      // Send to Firebase for Notifications
      try {
        set(ref(database, 'hybridPrediction'), {
          label: response.suitability,
          confidence: response.confidence * 100,
          timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC',
        });
      } catch (e) {
        console.log('Firebase error', e);
      }
    } catch (error) {
      // A refused image is a real answer from the input gate, not a crash, so
      // it gets its own card explaining why rather than a generic error popup.
      if (error.notAnOrchid) {
        setRejection({
          message: error.message,
          check: error.inputCheck || null,
        });
        setTimeout(() => {
          scrollViewRef.current?.scrollToEnd({ animated: true });
        }, 200);
      } else {
        Alert.alert('Could not reach the server', error.message || 'Unknown error');
      }
    } finally {
      setLoading(false);
    }
  };

  // ── Suitability Color ─────────────────────
  const getSuitabilityColor = (label) => {
    if (label === 'Suitable') return COLORS.success;
    if (label === 'Moderate') return COLORS.warning;
    return COLORS.danger;
  };

  const getSuitabilityIcon = (label) => {
    if (label === 'Suitable') return 'checkmark-circle';
    if (label === 'Moderate') return 'alert-circle';
    return 'close-circle';
  };

  // ── Documented species, for the notes shown beside a name ─────────────
  // Only these four carry a hand-written note. Every OTHER name in the list
  // comes from the register and is shown without embellishment, because
  // inventing a trait description for a grex we have not studied would be
  // presenting a guess as a record.
  const SPECIES_NOTES = {
    'V. coerulea':    { trait: 'Blue pigment', origin: 'Thailand', color: '#457B9D' },
    'V. sanderiana':  { trait: 'Large bloom', origin: 'Philippines', color: '#C1666B' },
    'V. tessellata':  { trait: 'Fragrance', origin: 'Sri Lanka', color: '#7B4F8A' },
    'V. tricolor':    { trait: 'Patterned', origin: 'Java', color: '#C9A227' },
  };

  // Every parent name the compatibility engine can find evidence for. Loaded
  // from the API rather than hard-coded, so this list and the type-ahead on the
  // Cross tab can never drift apart.
  const [parentNames, setParentNames] = useState([]);
  const [parentSearch, setParentSearch] = useState('');
  const [crossPrefill, setCrossPrefill] = useState(null);

  useEffect(() => {
    getKnownParents()
      .then((data) => setParentNames(data.parents || []))
      .catch(() => setParentNames([]));
  }, []);

  const visibleParents = parentNames.filter((n) =>
    n.toLowerCase().includes(parentSearch.trim().toLowerCase())
  );

  // Send a name straight into the Cross tab, so a grower who does not know any
  // orchid names can still use Level 2: browse, tap, check.
  const useParentAs = (name, role) => {
    setCrossPrefill({ name, role, at: Date.now() });
    setActiveTab('cross');
  };

  // ── Render Tab Content ────────────────────
  const renderAssessTab = () => (
    <>
      {/* Image Selection */}
      <Text style={styles.sectionTitle}>Plant Image</Text>
      <View style={[styles.imageCard, SHADOW.sm]}>
        {selectedImage ? (
          <Image source={{ uri: selectedImage }} style={styles.previewImage} />
        ) : (
          <View style={styles.imagePlaceholder}>
            <Ionicons name="camera-outline" size={36} color={COLORS.textTertiary} />
            <Text style={styles.placeholderText}>Upload or capture a plant image</Text>
          </View>
        )}
        <View style={styles.imageActions}>
          <TouchableOpacity style={styles.imageBtn} onPress={pickImage}>
            <Ionicons name="images-outline" size={16} color={COLORS.primary} />
            <Text style={styles.imageBtnText}>Gallery</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.imageBtn} onPress={takePhoto}>
            <Ionicons name="camera-outline" size={16} color={COLORS.primary} />
            <Text style={styles.imageBtnText}>Camera</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Trait Selection */}
      {/* Collapsed by default, and that is the point.
          The review asked whether user input was necessary. It is not - all
          four traits are read from the photograph. Keeping the fields visible
          and open invited the grower to fill them in, which is what made the
          system look input-driven. Kept but folded away: available to whoever
          disagrees with a reading, invisible to everyone else. */}
      <TouchableOpacity
        style={styles.correctionsToggle}
        onPress={() => setShowCorrections((v) => !v)}
        activeOpacity={0.7}
      >
        <Ionicons
          name={showCorrections ? 'chevron-down' : 'chevron-forward'}
          size={15}
          color={COLORS.textSecondary}
        />
        <Text style={styles.correctionsToggleText}>
          Disagree with a reading? Correct it
        </Text>
        <Text style={styles.correctionsOptional}>optional</Text>
      </TouchableOpacity>

      {showCorrections && (
      <View style={[styles.traitsCard, SHADOW.sm]}>
        {Object.entries(traitOptions).map(([key, options]) => (
          <View key={key} style={styles.traitRow}>
            <View style={styles.traitLabelRow}>
              <Ionicons name={traitIcons[key]} size={14} color={COLORS.textSecondary} />
              <Text style={styles.traitLabel}>{traitLabels[key]}</Text>
            </View>
            <View style={styles.traitChips}>
              {options.map((opt) => (
                <TouchableOpacity
                  key={opt}
                  style={[
                    styles.traitChip,
                    traits[key] === opt && styles.traitChipActive
                  ]}
                  onPress={() => setTraits(prev => ({
                    ...prev,
                    [key]: prev[key] === opt ? null : opt
                  }))}
                >
                  <Text style={[
                    styles.traitChipText,
                    traits[key] === opt && styles.traitChipTextActive
                  ]}>{opt}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ))}
      </View>
      )}

      {/* Assess Button */}
      <TouchableOpacity
        style={[styles.assessBtn, SHADOW.md, !selectedImage && styles.assessBtnDisabled]}
        onPress={handlePredict}
        disabled={!selectedImage || loading}
      >
        {loading ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <>
            <Ionicons name="analytics-outline" size={18} color="#fff" />
            <Text style={styles.assessBtnText}>Assess Suitability</Text>
          </>
        )}
      </TouchableOpacity>

      {/* Refused input — the photograph is not an orchid, so nothing was assessed */}
      {rejection && (
        <View style={[styles.rejectCard, SHADOW.md]}>
          <View style={styles.resultHeader}>
            <Ionicons name="close-circle" size={28} color={COLORS.danger} />
            <View style={styles.resultHeaderText}>
              <Text style={[styles.resultLabel, { color: COLORS.danger }]}>
                Not an orchid
              </Text>
              <Text style={styles.resultConf}>No assessment was made</Text>
            </View>
          </View>

          <Text style={styles.resultRec}>{rejection.message}</Text>

          {rejection.check && rejection.check.vegetation != null && (
            <Text style={styles.rejectDetail}>
              Plant tissue in frame: {(rejection.check.vegetation * 100).toFixed(1)}%
              {'  ·  '}novelty {rejection.check.distance} (limit {rejection.check.threshold})
              {rejection.check.orchid_probability != null
                ? `  ·  orchid likelihood ${(rejection.check.orchid_probability * 100).toFixed(0)}%`
                : ''}
            </Text>
          )}

          <Text style={styles.rejectHint}>
            Photograph one Vanda plant, filling most of the frame, in daylight.
          </Text>
        </View>
      )}

      {/* Results */}
      {result && (
        <View style={[styles.resultCard, SHADOW.md, { borderLeftColor: getSuitabilityColor(result.suitability) }]}>
          <View style={styles.resultHeader}>
            <Ionicons name={getSuitabilityIcon(result.suitability)} size={28} color={getSuitabilityColor(result.suitability)} />
            <View style={styles.resultHeaderText}>
              <Text style={[styles.resultLabel, { color: getSuitabilityColor(result.suitability) }]}>
                {result.suitability}
              </Text>
              <Text style={styles.resultConf}>
                Confidence: {(result.confidence * 100).toFixed(1)}%
              </Text>
            </View>
          </View>

          {/* Probability Bars */}
          <View style={styles.probSection}>
            {result.probabilities && Object.entries(result.probabilities).map(([cls, prob]) => (
              <View key={cls} style={styles.probRow}>
                <Text style={styles.probLabel}>{cls}</Text>
                <View style={styles.probBarBg}>
                  <View style={[styles.probBar, {
                    width: `${prob * 100}%`,
                    backgroundColor: getSuitabilityColor(cls)
                  }]} />
                </View>
                <Text style={styles.probVal}>{(prob * 100).toFixed(0)}%</Text>
              </View>
            ))}
          </View>

          {/* Recommendation */}
          <Text style={styles.resultRec}>{result.recommendation}</Text>
        </View>
      )}

      {/* What was read from the photograph.
          This is the direct answer to the review comment "is it necessary to get
          user inputs, like disease, with the uploaded image". Every trait below
          carries where its value came from, so a grower who typed nothing can
          see that nothing was required of them. */}
      {result?.trait_resolution && (
        <View style={[styles.traitReadCard, SHADOW.sm]}>
          <Text style={styles.traitReadTitle}>
            <Ionicons name="eye-outline" size={14} color={COLORS.primary} /> Read from your photo
          </Text>

          {/* Keyed on whether the grower actually supplied anything, NOT on
              `fully_automatic` - that flag is false whenever any trait is still
              unresolved, which would wrongly imply the grower had typed something. */}
          <Text style={styles.traitReadIntro}>
            {Object.values(result.trait_resolution.traits || {})
              .some((t) => t.source === 'user')
              ? 'Values you chose are marked below; the rest were measured from the image.'
              : 'You entered nothing. Every value below came from the photograph alone.'}
          </Text>

          {Object.entries(result.trait_resolution.traits || {}).map(([key, t]) => {
            const measured = t.source === 'measured';
            const known = t.value && t.value !== 'unknown';
            const tone = t.source === 'user'
              ? COLORS.primary
              : (measured ? COLORS.success : COLORS.textTertiary);

            return (
              <View key={key} style={styles.traitReadRow}>
                <View style={styles.traitReadHead}>
                  <Ionicons name={traitIcons[key] || 'ellipse-outline'} size={13} color={COLORS.textSecondary} />
                  <Text style={styles.traitReadName}>{traitLabels[key] || key}</Text>
                  <Text style={[styles.traitReadValue, { color: tone }]}>
                    {known ? t.value : 'not determined'}
                  </Text>
                </View>

                <Text style={styles.traitReadSource}>
                  {t.source === 'user' ? 'you entered this'
                    : measured ? `measured from image · ${(t.confidence * 100).toFixed(0)}% confidence`
                    : 'could not be measured'}
                  {t.needs_user_input ? ' · please confirm' : ''}
                </Text>

                {t.explanation ? (
                  <Text style={styles.traitReadWhy}>{t.explanation}</Text>
                ) : null}
              </View>
            );
          })}

          {result.trait_resolution.asked_for?.length > 0 && (
            <Text style={styles.traitReadAsk}>
              Still unknown: {result.trait_resolution.asked_for
                .map((k) => traitLabels[k] || k).join(', ')}.
              A close-up photo of one leaf improves the disease reading.
            </Text>
          )}
        </View>
      )}

      {/* Guidance */}
      {guidanceData && result && (
        <View style={[styles.guideCard, SHADOW.sm]}>
          <Text style={styles.guideTitle}>
            <Ionicons name="book-outline" size={14} color={COLORS.primary} /> Pollination Guidance
          </Text>
          <Text style={styles.guideStatus}>{guidanceData.status}</Text>
          {guidanceData.steps?.map((step, i) => (
            <Text key={i} style={styles.guideStep}>{step}</Text>
          ))}
          {guidanceData.tips?.length > 0 && (
            <View style={styles.tipsBox}>
              <Text style={styles.tipsTitle}>Tips</Text>
              {guidanceData.tips.map((tip, i) => (
                <Text key={i} style={styles.tipText}>• {tip}</Text>
              ))}
            </View>
          )}
        </View>
      )}
    </>
  );

  const renderVarietiesTab = () => (
    <>
      <Text style={styles.sectionTitle}>Parent Varieties</Text>
      <Text style={styles.varietyIntro}>
        Every parent the compatibility engine has evidence for: {parentNames.length} names
        taken from the registered crosses in the RHS orchid register plus the species
        documented for this project. Tap one to use it in a cross.
      </Text>

      <View style={[styles.searchBox, SHADOW.sm]}>
        <Ionicons name="search-outline" size={14} color={COLORS.textTertiary} />
        <TextInput
          style={styles.searchInput}
          placeholder="Search names"
          placeholderTextColor={COLORS.textTertiary}
          value={parentSearch}
          onChangeText={setParentSearch}
          autoCapitalize="none"
        />
        {parentSearch.length > 0 && (
          <TouchableOpacity onPress={() => setParentSearch('')}>
            <Ionicons name="close-circle" size={16} color={COLORS.textTertiary} />
          </TouchableOpacity>
        )}
      </View>

      {parentNames.length === 0 && (
        <Text style={styles.varietyEmpty}>
          Could not load the name list. Check that the backend is running.
        </Text>
      )}

      {visibleParents.map((name) => {
        const note = SPECIES_NOTES[name];
        return (
          <View key={name} style={[styles.varietyCardFull, SHADOW.sm]}>
            <View style={[styles.varietyLine, { backgroundColor: note?.color || COLORS.border }]} />
            <View style={{ flex: 1 }}>
              <Text style={styles.varietyName}>{name}</Text>
              {note ? (
                <>
                  <Text style={styles.varietyTrait}>{note.trait}</Text>
                  <View style={styles.originRow}>
                    <Ionicons name="location-outline" size={10} color={COLORS.textTertiary} />
                    <Text style={styles.varietyOrigin}>{note.origin}</Text>
                  </View>
                </>
              ) : (
                <Text style={styles.varietyTrait}>In the register</Text>
              )}

              <View style={styles.useRow}>
                <TouchableOpacity style={styles.useBtn} onPress={() => useParentAs(name, 'pod')}>
                  <Text style={styles.useBtnText}>Use as pod parent</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.useBtn} onPress={() => useParentAs(name, 'pollen')}>
                  <Text style={styles.useBtnText}>Use as pollen parent</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        );
      })}
    </>
  );

  return (
    <View style={styles.container}>
      <ScreenHeader title="Hybrid Pollination" subtitle="Readiness & Compatibility" navigation={navigation} />

      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {[
          { key: 'assess', label: 'Assess', icon: 'scan-outline' },
          { key: 'cross', label: 'Cross', icon: 'git-compare-outline' },
          { key: 'varieties', label: 'Varieties', icon: 'flower-outline' },
        ].map(tab => (
          <TouchableOpacity
            key={tab.key}
            style={[styles.tab, activeTab === tab.key && styles.tabActive]}
            onPress={() => setActiveTab(tab.key)}
          >
            <Ionicons name={tab.icon} size={14} color={activeTab === tab.key ? COLORS.primary : COLORS.textTertiary} />
            <Text style={[styles.tabText, activeTab === tab.key && styles.tabTextActive]}>{tab.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView 
        ref={scrollViewRef}
        contentContainerStyle={styles.scroll} 
        showsVerticalScrollIndicator={false}
      >
        <Animated.View style={{ opacity: fadeAnim }}>
          {activeTab === 'assess' && renderAssessTab()}
          {activeTab === 'cross' && (
            <CompatibilityTab
              level1Result={result}
              level1Image={selectedImage}
              prefill={crossPrefill}
            />
          )}
          {activeTab === 'varieties' && renderVarietiesTab()}
        </Animated.View>
        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.md },

  // Tab Bar
  tabBar: { flexDirection: 'row', paddingHorizontal: SPACE.xl, paddingTop: SPACE.sm, gap: SPACE.xs, backgroundColor: COLORS.bg },
  tab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.sm, borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCard, gap: 4 },
  tabActive: { backgroundColor: COLORS.primaryDim },
  tabText: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },
  tabTextActive: { color: COLORS.primary },

  // Image Upload
  imageCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, overflow: 'hidden', marginBottom: SPACE.md },
  previewImage: { width: '100%', height: 200, resizeMode: 'cover' },
  imagePlaceholder: { height: 160, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.bgCardAlt },
  placeholderText: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: SPACE.sm },
  imageActions: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  imageBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md, gap: 6 },
  imageBtnText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },

  // Traits
  traitsCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.lg },
  traitRow: { marginBottom: SPACE.md },
  traitLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: SPACE.xs },
  traitLabel: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  traitChips: { flexDirection: 'row', gap: SPACE.xs, flexWrap: 'wrap' },
  traitChip: { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs, borderRadius: RADIUS.full, backgroundColor: COLORS.bgCardAlt, borderWidth: 1, borderColor: COLORS.border },
  traitChipActive: { backgroundColor: COLORS.primaryDim, borderColor: COLORS.primary },
  traitChipText: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '600', textTransform: 'capitalize' },
  traitChipTextActive: { color: COLORS.primary },

  // Assess Button
  assessBtn: { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, marginBottom: SPACE.xl },
  assessBtnDisabled: { opacity: 0.5 },
  assessBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  // Results
  resultCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md, borderLeftWidth: 4 },
  correctionsToggle: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, paddingVertical: SPACE.md, marginBottom: SPACE.sm },
  correctionsToggleText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  correctionsOptional: { color: COLORS.textTertiary, fontSize: FONT.xs },
  traitsIntro: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17, marginBottom: SPACE.sm, marginTop: -SPACE.xs },
  traitReadCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md },
  traitReadTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.sm },
  traitReadIntro: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17, marginBottom: SPACE.md },
  traitReadRow: { marginBottom: SPACE.md, paddingBottom: SPACE.sm, borderBottomWidth: 1, borderBottomColor: COLORS.bgCardAlt },
  traitReadHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  traitReadName: { flex: 1, color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  traitReadValue: { fontSize: FONT.sm, fontWeight: '800' },
  traitReadSource: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 3, fontVariant: ['tabular-nums'] },
  traitReadWhy: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16, marginTop: 4 },
  traitReadAsk: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17, fontStyle: 'italic' },
  varietyIntro: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 18, marginBottom: SPACE.md },
  varietyEmpty: { color: COLORS.textTertiary, fontSize: FONT.xs, fontStyle: 'italic', marginBottom: SPACE.md },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm, marginBottom: SPACE.md },
  searchInput: { flex: 1, color: COLORS.text, fontSize: FONT.sm, paddingVertical: 4 },
  useRow: { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.sm, flexWrap: 'wrap' },
  useBtn: { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.md, paddingVertical: 6 },
  useBtnText: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '600' },
  rejectCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md, borderLeftWidth: 4, borderLeftColor: COLORS.danger },
  rejectDetail: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: SPACE.md, fontVariant: ['tabular-nums'] },
  rejectHint: { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: SPACE.sm, fontStyle: 'italic' },
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.lg },
  resultHeaderText: { flex: 1 },
  resultLabel: { fontSize: FONT.xl, fontWeight: '800' },
  resultConf: { color: COLORS.textSecondary, fontSize: FONT.sm },
  probSection: { marginBottom: SPACE.lg },
  probRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.sm },
  probLabel: { width: 90, color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '600' },
  probBarBg: { flex: 1, height: 6, backgroundColor: COLORS.bgCardAlt, borderRadius: 3, marginHorizontal: SPACE.sm, overflow: 'hidden' },
  probBar: { height: '100%', borderRadius: 3 },
  probVal: { width: 36, color: COLORS.text, fontSize: FONT.xs, fontWeight: '700', textAlign: 'right' },
  resultRec: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },

  // Guidance
  guideCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md },
  guideTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.xs },
  guideStatus: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600', marginBottom: SPACE.md },
  guideStep: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20, marginBottom: SPACE.xs },
  tipsBox: { marginTop: SPACE.md, backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md },
  tipsTitle: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700', marginBottom: SPACE.xs },
  tipText: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 18, marginBottom: 2 },

  // Varieties
  varietyCardFull: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm, flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  varietyLine: { width: 4, height: 40, borderRadius: 2 },
  varietyName: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 2 },
  varietyTrait: { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: SPACE.xs },
  originRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  varietyOrigin: { color: COLORS.textTertiary, fontSize: 9 },
});

export default HybridPollinationScreen;
