import React, { useRef, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated, ActivityIndicator, Alert, Image, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { ref, set } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import CompatibilityTab from '../components/CompatibilityTab';
import CrossLogTab from '../components/CrossLogTab';
import { getVarieties, varietyPhotoUrl } from '../services/crossLog';
import AppDialog from '../components/AppDialog';
import { assessSuitability, getGuidance, getKnownParents, getApiBaseUrl } from '../services/api';

const HybridPollinationScreen = ({ navigation }) => {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  const scrollViewRef = useRef(null);
  
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  // ── State ──────────────────────────────────
  const [selectedImage, setSelectedImage] = useState(null);
  const [result, setResult] = useState(null);
  // Set when the input gate refuses the photograph as not an orchid.
  const [rejection, setRejection] = useState(null);
  /* The leaf close-up is optional and folded away by default, for the same
     reason the corrections are: an open card the size of the main photo one
     reads as a second required step. */
  const [showCloseup, setShowCloseup] = useState(false);

  /* Detail that used to be printed under every trait now opens here instead.
     Keeping the raw confidence figure on screen filled the card with numbers
     a grower cannot act on; one tap away it is still there for anyone who
     wants it. */
  const [dialog, setDialog] = useState(null);
  const say = (d) => setDialog(d);
  // Optional close-up of ONE leaf. Disease cannot be read from a whole-plant
  // frame - measured at AUC 0.51 - so this is the image that actually goes to
  // Component 1's disease model.
  const [closeupImage, setCloseupImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [guidanceData, setGuidanceData] = useState(null);
  const [activeTab, setActiveTab] = useState('assess'); // 'assess' | 'cross' | 'varieties'

  // ── Trait Display Names ──────────────
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
      mediaTypes: ['images'],
      quality: 0.8,
      allowsEditing: true,
    });

    if (!pickerResult.canceled && pickerResult.assets?.[0]) {
      setSelectedImage(pickerResult.assets[0].uri);
      setResult(null);
      setRejection(null);
    }
  };

  const pickCloseup = async () => {
    const permResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permResult.granted) {
      Alert.alert('Permission needed', 'Please allow access to your photo library.');
      return;
    }
    const pickerResult = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.8,
      allowsEditing: true,
    });
    if (!pickerResult.canceled && pickerResult.assets?.[0]) {
      setCloseupImage(pickerResult.assets[0].uri);
      setResult(null);
      setRejection(null);
    }
  };

  const captureCloseup = async () => {
    const permResult = await ImagePicker.requestCameraPermissionsAsync();
    if (!permResult.granted) {
      Alert.alert('Permission needed', 'Please allow access to your camera.');
      return;
    }
    const pickerResult = await ImagePicker.launchCameraAsync({
      quality: 0.8, allowsEditing: true,
    });
    if (!pickerResult.canceled && pickerResult.assets?.[0]) {
      setCloseupImage(pickerResult.assets[0].uri);
      setResult(null);
      setRejection(null);
    }
  };

  /**
   * Empty the Assess tab.
   *
   * Everything downstream reads from `selectedImage` and `result`, so
   * clearing those two clears the Cross tab's pod parent and the logbook
   * composer's prefill with them. That is the point: a photograph the grower
   * has removed should not still be carried into a cross on another tab.
   *
   * The close-up goes too. It belongs to the plant that was just removed, and
   * leaving it behind would attach one plant's leaf to the next plant's
   * assessment.
   */
  const clearPlantImage = () => {
    setSelectedImage(null);
    setResult(null);
    setRejection(null);
    setCloseupImage(null);
    setGuidanceData(null);
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
      const response = await assessSuitability(selectedImage, {}, closeupImage);
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
  /* The Varieties tab's two lists. Loaded together because they are one
     answer to one question - what can this grower breed from - split only so
     that what they own is not confused with what the register knows. */
  const [varieties, setVarieties] = useState(null);
  /* What the Cross tab currently has photographed, so the logbook composer
     can start from it. Held here rather than in either tab because it has to
     cross between them, and the screen is the only thing that sees both. */
  const [crossParents, setCrossParents] = useState(null);
  const [parentSearch, setParentSearch] = useState('');
  const [crossPrefill, setCrossPrefill] = useState(null);

  /* The Varieties tab's own data. Separate from getKnownParents, which still
     feeds the type-ahead on the Cross tab: that one wants a flat list of
     names the engine can find evidence for, this one wants the grower's
     plants and the register kept apart. */
  useEffect(() => {
    getVarieties().then(setVarieties).catch(() => setVarieties(null));
  }, []);

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
      <View style={styles.sectionHead}>
        <View style={styles.sectionRule} />
        <Ionicons name="image-outline" size={16} color={COLORS.primary} />
        <Text style={styles.sectionTitle}>Plant Image</Text>
      </View>
      <View style={[styles.imageCard, SHADOW.sm]}>
        {selectedImage ? (
          <Image source={{ uri: selectedImage }} style={styles.previewImage} />
        ) : (
          /* The placeholder is the obvious thing to tap and it used to do
             nothing, so a grower who tapped the camera icon got no camera. */
          <TouchableOpacity
            style={styles.imagePlaceholder}
            onPress={takePhoto}
            activeOpacity={0.7}
          >
            <Ionicons name="camera-outline" size={36} color={COLORS.textTertiary} />
            <Text style={styles.placeholderText}>Tap to photograph a plant</Text>
            <Text style={styles.placeholderHint}>or choose one from the gallery below</Text>
          </TouchableOpacity>
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
          {/* Every other photo card in this component has a Clear; this one
              did not, so the only way back to an empty Assess tab was to pick
              another image or restart the app. */}
          {selectedImage && (
            <TouchableOpacity style={styles.imageBtn} onPress={clearPlantImage}>
              <Ionicons name="close-outline" size={16} color={COLORS.textTertiary} />
              <Text style={[styles.imageBtnText, { color: COLORS.textTertiary }]}>
                Clear
              </Text>
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* Trait Selection */}
      {/* Optional leaf close-up.
          Disease was measured at AUC 0.51 from a whole-plant frame - lesions
          span 1-3 px at that distance. Component 1's model is trained on
          leaves, so this is the image that actually reaches it. Optional
          because the rest of the assessment works without it. */}
      {/* Folded away, because it is optional.
          It has to stay - disease measured AUC 0.51 from a whole-plant frame,
          so without this image the disease half of the reading is not
          evidence. But it is optional, and an open photo card the size of the
          main one read as a second required step. One line, opened by whoever
          wants it. */}
      <TouchableOpacity
        style={styles.correctionsToggle}
        onPress={() => setShowCloseup((v) => !v)}
        activeOpacity={0.7}
      >
        <Ionicons
          name={showCloseup ? 'chevron-down' : 'chevron-forward'}
          size={16}
          color={COLORS.primary}
        />
        <Text style={styles.correctionsToggleText}>
          {closeupImage ? 'Leaf close-up added' : 'Checking for disease? Add a leaf close-up'}
        </Text>
        <Text style={styles.correctionsOptional}>
          {closeupImage ? 'added' : 'optional'}
        </Text>
      </TouchableOpacity>

      {showCloseup && (
        <>
          <Text style={styles.traitsIntro}>
            Disease cannot be read from a whole-plant photo — a leaf spot is a
            millimetre or two across, which is one or two pixels from a metre
            away. A close-up of a single leaf goes to the disease model
            instead. Everything else works without it.
          </Text>
          <View style={[styles.imageCard, SHADOW.sm]}>
            {closeupImage ? (
              <Image source={{ uri: closeupImage }} style={styles.previewImage} />
            ) : (
              <View style={styles.imagePlaceholder}>
                <Ionicons name="leaf-outline" size={30} color={COLORS.textTertiary} />
                <Text style={styles.placeholderText}>No close-up added</Text>
              </View>
            )}
            <View style={styles.imageActions}>
              <TouchableOpacity style={styles.imageBtn} onPress={pickCloseup}>
                <Ionicons name="images-outline" size={16} color={COLORS.primary} />
                <Text style={styles.imageBtnText}>Gallery</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.imageBtn} onPress={captureCloseup}>
                <Ionicons name="camera-outline" size={16} color={COLORS.primary} />
                <Text style={styles.imageBtnText}>Camera</Text>
              </TouchableOpacity>
              {closeupImage && (
                <TouchableOpacity style={styles.imageBtn} onPress={() => setCloseupImage(null)}>
                  <Ionicons name="close-outline" size={16} color={COLORS.textTertiary} />
                  <Text style={[styles.imageBtnText, { color: COLORS.textTertiary }]}>Remove</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        </>
      )}

      {/* The trait input card used to sit here.
          Progress Presentation 1 asked the question that removed it: if you
          upload an image to get a result, why does the system need user
          input? It does not. All four traits are read from the photograph,
          and a weak reading now holds the verdict at Not Suitable on its own,
          so there is nothing the grower has to type for the assessment to
          reach the right answer. */}

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
              {/* Two different numbers used to appear here under names that
                  looked like the same thing: "Confidence 49.2%" in the header
                  and "Suitable 98%" on the bar below it. 98 is what the model
                  scored; 49 is what is left after the cross-checks cut it. A
                  reader seeing both could only conclude one was wrong, and
                  reasonably read 49% as "under half, so not suitable". */}
              {/* No percentage when the verdict was vetoed. `confidence` is
                  then the classifier's score for the label that was
                  OVERRIDDEN, so printing it beside the new headline would be
                  the same mismatch in a new place. The veto is a rule, not a
                  probability, and the box below says which rule. */}
              <Text style={styles.resultConf}>
                {result.vetoed_by
                  ? 'Held by image analysis'
                  : result.confidence_reduced_because?.length > 0
                  ? 'Read with less certainty — see below'
                  : 'Read clearly from your photo'}
              </Text>
            </View>
          </View>

          {/* When image analysis overrode the classifier, say so plainly and
              name the reason. The screen previously showed "weak" traits
              beside a Suitable headline and left the grower to reconcile
              them. */}
          {result.vetoed_by ? (
            <View style={styles.vetoBox}>
              <Ionicons name="hand-left-outline" size={15} color={COLORS.danger} />
              <View style={{ flex: 1 }}>
                <Text style={styles.vetoTitle}>Held at Not Suitable</Text>
                <Text style={styles.vetoText}>{result.vetoed_by}</Text>
              </View>
            </View>
          ) : result.confidence_reduced_because?.length > 0 ? (
            <View style={styles.dampBox}>
              <Ionicons name="alert-circle-outline" size={14} color={COLORS.warning} />
              {/* Two percentages and the phrase "unlike the training set"
                  used to sit here. The warning is worth keeping - this
                  verdict IS less reliable and the grower should know - but
                  the mechanism behind it is not theirs to carry, and a pair
                  of numbers in one sentence only raises the question of which
                  one describes the plant. Neither does. `model_score` and
                  `confidence_reduced_because` are still in the API response
                  for the evaluation chapter. */}
              <Text style={styles.dampText}>
                This photo is harder than usual to read. Take the verdict as a
                guide and look at the plant yourself before acting on it.
              </Text>
            </View>
          ) : null}

          {/* Probability Bars */}
          {/* The three class-probability bars were here.
              Removed, for the reason the grower gave: after a veto the bar
              that filled furthest was still "Suitable", under a headline
              reading Not Suitable. That is the contradiction this whole
              change set out to remove, reappearing one row lower.

              Fading the overruled bar was the first attempt and it was not
              enough. The bars are the classifier's raw scores, and no reading
              of them tells a grower anything they can act on - the plant is
              either worth pollinating or it is not. The numbers are not lost:
              `probabilities` and `model_score` are still in the API response
              for the evaluation chapter, and the hold notice above states the
              model's own score in words whenever a verdict was overridden. */}

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
              ? 'Your values are marked. Tap any row for detail.'
              : 'You typed nothing — every reading came from the photo. Tap a row for detail.'}
          </Text>

          {/* Two lines per trait, not five.
              Every one of these used to print its own paragraph plus a raw
              confidence figure - "26% confidence", "model accuracy on unseen
              plants was 56% (baseline 50%)". All of it true, none of it what a
              grower standing over the plant needs: they need to know whether
              to trust the reading. The number means something to an examiner,
              so it is kept, one tap away, rather than thrown out. */}
          {Object.entries(result.trait_resolution.traits || {})
            /* flower_condition is not shown.
               The bloom detector's recall on a whole-plant frame is 1% at the
               shipped threshold (MIN_FLOWER_FRACTION, flower_analysis.py), so
               on the photographs growers actually take it answers "none"
               almost every time - including for a plant in full bloom. A row
               that is wrong that often is worse than no row: it reads as the
               system failing to see what the grower can plainly see. The
               value is still measured and still goes to the model as a
               feature; it is only withheld from the screen. */
            .filter(([key]) => key !== 'flower_condition')
            .map(([key, t]) => {
            const measured = t.source === 'measured';
            const known = t.value && t.value !== 'unknown';
            const tone = t.source === 'user'
              ? COLORS.primary
              : (measured ? COLORS.success : COLORS.textTertiary);

            // A percentage is not an instruction. These words are.
            const c = t.confidence || 0;
            const summary = t.source === 'user' ? 'you entered this'
              : !measured ? 'could not be measured from this photo'
              : c >= 0.7 ? 'read clearly from the photo'
              : c >= 0.4 ? 'fairly confident — worth a glance'
              : 'low confidence — please check this one';

            return (
              <TouchableOpacity
                key={key}
                style={styles.traitReadRow}
                onPress={() => say({
                  tone: measured && c >= 0.7 ? 'info' : 'warn',
                  title: traitLabels[key] || key,
                  message: t.explanation || summary,
                  sections: [
                    measured && c < 0.7 && {
                      label: 'How clear was it',
                      text: c >= 0.4
                        ? 'Readable, but not beyond doubt.'
                        : 'Hard to read from this photo.',
                    },
                    t.needs_user_input && {
                      label: 'Worth confirming',
                      text: 'This reading is too weak to rely on. Look at the '
                          + 'plant itself before acting on the verdict.',
                    },
                  ].filter(Boolean),
                })}
                activeOpacity={0.6}
              >
                <View style={styles.traitReadHead}>
                  <Ionicons name={traitIcons[key] || 'ellipse-outline'} size={14}
                    color={COLORS.textSecondary} />
                  <Text style={styles.traitReadName}>{traitLabels[key] || key}</Text>
                  <Text style={[styles.traitReadValue, { color: tone }]}>
                    {known ? t.value : 'not determined'}
                  </Text>
                  <Ionicons name="information-circle-outline" size={14}
                    color={COLORS.textTertiary} />
                </View>
                <Text style={styles.traitReadSource}>{summary}</Text>
              </TouchableOpacity>
            );
          })}

          {/* "Still unknown: Leaf Condition, Plant Strength" used to print
              here. It restated what each row above already says in its own
              second line, and listed traits that HAD been read - `asked_for`
              means the reading was weak enough to be worth confirming, not
              that nothing was found. Two different meanings under one word. */}
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

  /**
   * Two lists, kept apart because they answer different questions.
   *
   * MY PLANTS is what the grower actually has, with photographs. It is seeded
   * with the collection this project was built on and grows every time a plant
   * is registered through the logbook, so a grower who logs a cross does not
   * have to enter those plants again to see them here.
   *
   * IN THE REGISTER is what the knowledge base has evidence for, names only.
   * It is also an honest statement of coverage - a grower can see exactly how
   * much the register knows before relying on it, which is the same reason the
   * input gate refuses rather than guesses.
   *
   * Every name carries a tier, because a name typed by a grower is not the
   * same kind of fact as a name in the register. A mistyped name shows up as
   * "tag name" where it misleads nobody.
   */
  const TIER = {
    register: { icon: 'checkmark-circle', colour: COLORS.success,
                text: 'In the register' },
    named:    { icon: 'pricetag-outline', colour: COLORS.textTertiary,
                text: 'Tag name \u00b7 not in the register' },
    unnamed:  { icon: 'help-circle-outline', colour: COLORS.warning,
                text: 'No name yet \u00b7 identified later' },
  };

  const matchesSearch = (name) =>
    name.toLowerCase().includes(parentSearch.trim().toLowerCase());

  const renderUseRow = (name) => (
    <View style={styles.useRow}>
      <TouchableOpacity style={styles.useBtn} onPress={() => useParentAs(name, 'pod')}>
        <Text style={styles.useBtnText}>Use as pod parent</Text>
      </TouchableOpacity>
      <TouchableOpacity style={styles.useBtn} onPress={() => useParentAs(name, 'pollen')}>
        <Text style={styles.useBtnText}>Use as pollen parent</Text>
      </TouchableOpacity>
    </View>
  );

  const renderVarietiesTab = () => {
    const mine = (varieties?.mine || []).filter((p) => matchesSearch(p.name));
    const reg = (varieties?.register || []).filter((p) => matchesSearch(p.name));
    const counts = varieties?.counts || {};

    return (
      <>
        <View style={styles.sectionHead}>
          <View style={styles.sectionRule} />
          <Ionicons name="flower-outline" size={16} color={COLORS.primary} />
          <Text style={styles.sectionTitle}>Varieties</Text>
        </View>

        <View style={[styles.searchBox, SHADOW.sm]}>
          <Ionicons name="search-outline" size={14} color={COLORS.textTertiary} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search your plants and the register"
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

        {!varieties && (
          <Text style={styles.varietyEmpty}>
            Could not load the varieties. Check that the backend is running.
          </Text>
        )}

        {/* ── the grower's own plants ────────────────────── */}
        <Text style={styles.groupHead}>
          MY PLANTS{counts.mine ? `  \u00b7  ${counts.mine}` : ''}
        </Text>
        <Text style={styles.groupNote}>
          Plants in this collection. A tag name is what is written on the
          label, not a claim that the plant is the registered variety of that
          name.
        </Text>

        {mine.length === 0 && varieties ? (
          <Text style={styles.varietyEmpty}>
            {parentSearch
              ? 'No plant of yours matches that.'
              : 'None yet. Log a cross and both parents are registered here.'}
          </Text>
        ) : null}

        {mine.map((p) => {
          const tier = TIER[p.tier] || TIER.named;
          const uri = varietyPhotoUrl(p.photo);
          const parents = p.seed_parent && p.pollen_parent
            ? `${p.seed_parent} \u00d7 ${p.pollen_parent}` : '';
          return (
            <View key={p.name + p.photo} style={[styles.plantCard, SHADOW.sm]}>
              {uri ? (
                <Image source={{ uri }} style={styles.plantPhoto} />
              ) : (
                <View style={[styles.plantPhoto, styles.plantPhotoEmpty]}>
                  <Ionicons name="leaf-outline" size={20} color={COLORS.textTertiary} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={styles.varietyName}>{p.name}</Text>
                <View style={styles.tierRow}>
                  <Ionicons name={tier.icon} size={12} color={tier.colour} />
                  <Text style={[styles.tierText, { color: tier.colour }]}>
                    {tier.text}
                  </Text>
                </View>
                {parents ? (
                  <Text style={styles.varietyTrait}>from {parents}</Text>
                ) : null}
                {p.colour ? (
                  <Text style={styles.varietyTrait}>
                    {p.colour}{p.pattern ? `, ${p.pattern}` : ''}
                  </Text>
                ) : null}
                {renderUseRow(p.name)}
              </View>
            </View>
          );
        })}

        {/* ── what the knowledge base knows ──────────────── */}
        <Text style={[styles.groupHead, { marginTop: SPACE.xl }]}>
          IN THE REGISTER{counts.register ? `  \u00b7  ${counts.register}` : ''}
        </Text>
        <Text style={styles.groupNote}>
          Every name the compatibility engine has evidence for, drawn from
          {counts.registered_crosses ? ` ${counts.registered_crosses}` : ''} registered
          crosses. This is the whole knowledge base, not a selection of it, and
          a cross between names it does not hold can only be answered at genus
          level.
        </Text>

        {reg.map((p) => {
          const note = SPECIES_NOTES[p.name];
          return (
            <View key={p.name} style={[styles.varietyCardFull, SHADOW.sm]}>
              <View style={[styles.varietyLine,
                { backgroundColor: note?.color || COLORS.border }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.varietyName}>{p.name}</Text>
                {note ? (
                  <>
                    <Text style={styles.varietyTrait}>{note.trait}</Text>
                    <View style={styles.originRow}>
                      <Ionicons name="location-outline" size={10} color={COLORS.textTertiary} />
                      <Text style={styles.varietyOrigin}>{note.origin}</Text>
                    </View>
                  </>
                ) : null}
                <Text style={styles.varietyTrait}>
                  {p.crosses
                    ? `cited by ${p.crosses} registered cross${p.crosses > 1 ? 'es' : ''}`
                    : 'named in the register'}
                </Text>
                {renderUseRow(p.name)}
              </View>
            </View>
          );
        })}
      </>
    );
  };

  return (
    <View style={styles.container}>
      <ScreenHeader title="Hybrid Pollination" subtitle="Readiness & Compatibility" navigation={navigation} showSettings />

      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {[
          { key: 'assess', label: 'Assess', icon: 'scan-outline' },
          { key: 'cross', label: 'Cross', icon: 'git-compare-outline' },
          { key: 'varieties', label: 'Varieties', icon: 'flower-outline' },
          { key: 'log', label: 'Log', icon: 'book-outline' },
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

          {/* Hidden rather than unmounted.
              The cross tab holds two photographs, two assessments and two
              typed names - several minutes of a grower's work. Unmounting it
              on a tab switch threw all of that away, so stepping back to
              Assess to re-check one plant silently cleared the other one's
              photo. The other two tabs keep nothing worth preserving and stay
              conditional. */}
          <View style={activeTab === 'cross' ? null : styles.tabHidden}>
            <CompatibilityTab
              level1Result={result}
              level1Image={selectedImage}
              prefill={crossPrefill}
              onParentsChange={setCrossParents}
            />
          </View>

          {activeTab === 'varieties' && renderVarietiesTab()}

          {/* One dialog for the whole screen, in the app's own styling. */}
          <AppDialog
            visible={Boolean(dialog)}
            tone={dialog?.tone}
            title={dialog?.title}
            message={dialog?.message}
            sections={dialog?.sections || []}
            actions={dialog?.actions}
            onDismiss={() => setDialog(null)}
          />

          {/* The grower's own record of what they attempted and what
              happened. The register holds successes only; this is where
              the failures go, which is the half nothing else collects. */}
          {activeTab === 'log' && (
            <CrossLogTab
              level1Result={result}
              level1Image={selectedImage}
              crossParents={crossParents}
            />
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
  tabHidden: { display: 'none' },
  sectionHead: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    marginTop: SPACE.lg, marginBottom: SPACE.md,
  },
  sectionRule: {
    width: 3, height: 16, borderRadius: 2, backgroundColor: COLORS.primary,
  },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },

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
  placeholderHint: {
    color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2,
  },
  placeholderText: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: SPACE.sm },
  imageActions: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  imageBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md, gap: 6 },
  imageBtnText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },

  // Traits

  // Assess Button
  assessBtn: { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm, marginBottom: SPACE.xl },
  assessBtnDisabled: { opacity: 0.5 },
  assessBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  // Results
  resultCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md, borderLeftWidth: 4 },
  correctionsToggle: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, paddingVertical: SPACE.md, marginBottom: SPACE.sm },
  correctionsToggleText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  correctionsOptional: { color: COLORS.textTertiary, fontSize: FONT.sm },
  traitsIntro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 17, marginBottom: SPACE.sm, marginTop: -SPACE.xs },
  traitReadCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md },
  traitReadTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.sm },
  traitReadIntro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 17, marginBottom: SPACE.md },
  traitReadRow: { marginBottom: SPACE.md, paddingBottom: SPACE.sm, borderBottomWidth: 1, borderBottomColor: COLORS.bgCardAlt },
  traitReadHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  traitReadName: { flex: 1, color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  traitReadValue: { fontSize: FONT.sm, fontWeight: '800' },
  traitReadSource: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 3, fontVariant: ['tabular-nums'] },
  traitReadWhy: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 16, marginTop: 4 },
  varietyIntro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, marginBottom: SPACE.md },
  varietyEmpty: { color: COLORS.textTertiary, fontSize: FONT.sm, fontStyle: 'italic', marginBottom: SPACE.md },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm, marginBottom: SPACE.md },
  searchInput: { flex: 1, color: COLORS.text, fontSize: FONT.sm, paddingVertical: 4 },
  useRow: { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.sm, flexWrap: 'wrap' },
  useBtn: { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, paddingHorizontal: SPACE.md, paddingVertical: 6 },
  useBtnText: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600' },
  rejectCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md, borderLeftWidth: 4, borderLeftColor: COLORS.danger },
  rejectHint: { color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: SPACE.sm, fontStyle: 'italic' },
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.lg },
  resultHeaderText: { flex: 1 },
  resultLabel: { fontSize: FONT.xl, fontWeight: '800' },
  resultConf: { color: COLORS.textSecondary, fontSize: FONT.sm },
  dampBox: {
    flexDirection: 'row', gap: 6, alignItems: 'flex-start',
    backgroundColor: COLORS.warningDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.md,
  },
  dampText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  vetoBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.md,
    borderLeftWidth: 3, borderLeftColor: COLORS.danger,
  },
  vetoTitle: { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '800', marginBottom: 2 },
  vetoText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  resultRec: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },

  // Guidance
  guideCard: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.md },
  guideTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.xs },
  guideStatus: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '600', marginBottom: SPACE.md },
  guideStep: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20, marginBottom: SPACE.xs },
  tipsBox: { marginTop: SPACE.md, backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md },
  tipsTitle: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700', marginBottom: SPACE.xs },
  tipText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, marginBottom: 2 },

  // Varieties
  groupHead: {
    color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '800',
    letterSpacing: 0.8, marginTop: SPACE.lg, marginBottom: 4,
  },
  groupNote: {
    color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18,
    marginBottom: SPACE.md,
  },
  plantCard: {
    flexDirection: 'row', gap: SPACE.md, alignItems: 'flex-start',
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    padding: SPACE.md, marginBottom: SPACE.md,
    borderWidth: 1, borderColor: COLORS.border,
  },
  plantPhoto: {
    width: 84, height: 84, borderRadius: RADIUS.sm,
    backgroundColor: COLORS.bgCardAlt,
  },
  plantPhotoEmpty: {
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: COLORS.borderLight, borderStyle: 'dashed',
  },
  tierRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2, marginBottom: 2 },
  tierText: { fontSize: FONT.sm, fontWeight: '600', flex: 1 },
  varietyCardFull: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.sm, flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  varietyLine: { width: 4, height: 40, borderRadius: 2 },
  varietyName: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 2 },
  varietyTrait: { color: COLORS.textTertiary, fontSize: FONT.sm, marginBottom: SPACE.xs },
  originRow: { flexDirection: 'row', alignItems: 'center', gap: 3 },
  varietyOrigin: { color: COLORS.textTertiary, fontSize: FONT.xs },
});

export default HybridPollinationScreen;
