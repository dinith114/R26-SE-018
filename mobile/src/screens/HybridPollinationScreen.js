import React, { useRef, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated, ActivityIndicator, Alert, Image } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { ref, set } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { assessSuitability, getGuidance } from '../services/api';

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
  const [loading, setLoading] = useState(false);
  const [guidanceData, setGuidanceData] = useState(null);
  const [activeTab, setActiveTab] = useState('assess'); // 'assess' | 'guide' | 'varieties'

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
      Alert.alert('Error', 'Could not assess suitability. Make sure the backend server is running.');
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

  // ── Static Varieties Data ─────────────────
  const varieties = [
    { id: 1, name: 'V. coerulea', trait: 'Blue pigment', origin: 'Thailand', color: '#457B9D' },
    { id: 2, name: 'V. sanderiana', trait: 'Large bloom', origin: 'Philippines', color: '#C1666B' },
    { id: 3, name: 'V. tessellata', trait: 'Fragrance', origin: 'Sri Lanka', color: '#7B4F8A' },
    { id: 4, name: 'V. tricolor', trait: 'Patterned', origin: 'Java', color: '#C9A227' },
  ];

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
      <Text style={styles.sectionTitle}>Plant Traits (Optional)</Text>
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
      {varieties.map((v) => (
        <View key={v.id} style={[styles.varietyCardFull, SHADOW.sm]}>
          <View style={[styles.varietyLine, { backgroundColor: v.color }]} />
          <View style={{ flex: 1 }}>
            <Text style={styles.varietyName}>{v.name}</Text>
            <Text style={styles.varietyTrait}>{v.trait}</Text>
            <View style={styles.originRow}>
              <Ionicons name="location-outline" size={10} color={COLORS.textTertiary} />
              <Text style={styles.varietyOrigin}>{v.origin}</Text>
            </View>
          </View>
        </View>
      ))}
    </>
  );

  return (
    <View style={styles.container}>
      <ScreenHeader title="Hybrid Pollination" subtitle="Suitability Assessment" navigation={navigation} />

      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {[
          { key: 'assess', label: 'Assess', icon: 'scan-outline' },
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
