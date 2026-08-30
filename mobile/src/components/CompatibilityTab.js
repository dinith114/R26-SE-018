import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, ScrollView, Image,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { assessCompatibility, getKnownParents } from '../services/api';

/**
 * Level 2 — Parent A × Parent B compatibility.
 *
 * Two things about this screen are deliberate and should not be "improved"
 * without understanding why:
 *
 * 1. The two fields are NOT interchangeable. The pod (seed) parent is named
 *    first and the pollen donor second, following breeding convention. The
 *    swap button exists precisely because the reversed cross is a DIFFERENT
 *    attempt, not a cosmetic reordering.
 *
 * 2. There is no percentage anywhere. The orchid register records only crosses
 *    that succeeded, so it has no denominator and no success rate can be
 *    derived from it. The screen shows an evidence tier and the registered
 *    precedents behind it instead.
 */

const TIER_STYLE = {
  registered:     { color: 'success', icon: 'checkmark-circle', short: 'Registered' },
  genus_proven:   { color: 'primary', icon: 'git-compare',      short: 'Proven combination' },
  undemonstrated: { color: 'warning', icon: 'help-circle',      short: 'No precedent' },
  blocked:        { color: 'danger',  icon: 'close-circle',     short: 'Not advised' },
};

const CompatibilityTab = ({ level1Result = null, level1Image = null, prefill = null }) => {
  const [podParent, setPodParent] = useState('');
  const [pollenParent, setPollenParent] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [knownParents, setKnownParents] = useState([]);
  const [activeField, setActiveField] = useState(null);
  const [usePhotoResult, setUsePhotoResult] = useState(true);
  const scrollRef = useRef(null);

  // A Level 1 photo assessment of the pod parent, if the grower ran one on the
  // Assess tab. Sent with the cross check so a plant in poor condition blocks
  // the pairing rather than being silently ignored.
  const podHealth = (level1Result && usePhotoResult)
    ? { suitability: level1Result.suitability, confidence: level1Result.confidence }
    : null;

  useEffect(() => {
    getKnownParents()
      .then((data) => setKnownParents(data.parents || []))
      .catch(() => setKnownParents([]));   // Suggestions are optional
  }, []);

  // A name tapped on the Varieties tab. `at` is a timestamp, so tapping the
  // same name twice still fires - without it the effect would not re-run and
  // the second tap would appear to do nothing.
  useEffect(() => {
    if (!prefill || !prefill.name) return;
    if (prefill.role === 'pollen') {
      setPollenParent(prefill.name);
    } else {
      setPodParent(prefill.name);
    }
  }, [prefill?.name, prefill?.role, prefill?.at]);

  const tierColor = (tier) => {
    const key = TIER_STYLE[tier]?.color || 'textSecondary';
    return COLORS[key] || COLORS.textSecondary;
  };

  // Suggestions for whichever field is focused
  const suggestionsFor = (value) => {
    const q = value.trim().toLowerCase();
    if (q.length < 2) return [];
    return knownParents
      .filter((n) => n.toLowerCase().includes(q) && n.toLowerCase() !== q)
      .slice(0, 5);
  };

  const handleCheck = async () => {
    if (!podParent.trim() || !pollenParent.trim()) {
      Alert.alert('Two parents needed', 'Enter both the pod parent and the pollen parent.');
      return;
    }

    setLoading(true);
    setResult(null);
    setActiveField(null);

    try {
      const response = await assessCompatibility(
        podParent.trim(), pollenParent.trim(), podHealth
      );
      setResult(response);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 200);
    } catch (error) {
      Alert.alert('Error', error.message || 'Could not check this pairing.');
    } finally {
      setLoading(false);
    }
  };

  const handleSwap = () => {
    setPodParent(pollenParent);
    setPollenParent(podParent);
    setResult(null);   // The reversed cross is a different question
  };

  const renderField = (label, hint, value, setValue, fieldKey, icon) => (
    <View style={styles.fieldBlock}>
      <View style={styles.fieldLabelRow}>
        <Ionicons name={icon} size={13} color={COLORS.textSecondary} />
        <Text style={styles.fieldLabel}>{label}</Text>
      </View>
      <Text style={styles.fieldHint}>{hint}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={(t) => { setValue(t); setResult(null); }}
        onFocus={() => setActiveField(fieldKey)}
        placeholder="e.g. V. tessellata"
        placeholderTextColor={COLORS.textTertiary}
        autoCapitalize="words"
        autoCorrect={false}
      />
      {activeField === fieldKey && suggestionsFor(value).length > 0 && (
        <View style={styles.suggestBox}>
          {suggestionsFor(value).map((name) => (
            <TouchableOpacity
              key={name}
              style={styles.suggestItem}
              onPress={() => { setValue(name); setActiveField(null); }}
            >
              <Ionicons name="search-outline" size={12} color={COLORS.textTertiary} />
              <Text style={styles.suggestText}>{name}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );

  return (
    <ScrollView
      ref={scrollRef}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.sectionTitle}>Check a Cross</Text>
      <Text style={styles.intro}>
        Order matters. The pod parent carries the seed; the pollen parent donates.
        Reversing them is a different cross.
      </Text>

      {level1Result ? (
        <TouchableOpacity
          style={[styles.linkCard, usePhotoResult && styles.linkCardActive]}
          onPress={() => setUsePhotoResult(v => !v)}
        >
          <Ionicons
            name={usePhotoResult ? 'checkbox' : 'square-outline'}
            size={17}
            color={usePhotoResult ? COLORS.primary : COLORS.textTertiary}
          />
          {/* The photograph the verdict came from. Without it the grower has to
              take on trust that the right plant was carried across. */}
          {level1Image && (
            <Image source={{ uri: level1Image }} style={styles.linkThumb} />
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.linkTitle}>
              Use photo assessment for the pod parent
            </Text>
            <Text style={styles.linkBody}>
              From the Assess tab: {level1Result.suitability}
              {level1Result.confidence
                ? ` (${(level1Result.confidence * 100).toFixed(0)}%)` : ''}
              . A plant assessed Not Suitable will block the cross.
            </Text>
          </View>
        </TouchableOpacity>
      ) : (
        <View style={styles.linkCard}>
          <Ionicons name="information-circle-outline" size={17} color={COLORS.textTertiary} />
          <Text style={styles.linkBody}>
            Assess a plant photo on the Assess tab first and its condition will be
            applied here automatically.
          </Text>
        </View>
      )}

      <View style={[styles.card, SHADOW.sm]}>
        {renderField(
          'Pod parent (seed)', 'Written first — carries the seed pod',
          podParent, setPodParent, 'pod', 'ellipse-outline'
        )}

        <TouchableOpacity style={styles.swapBtn} onPress={handleSwap}>
          <Ionicons name="swap-vertical" size={15} color={COLORS.primary} />
          <Text style={styles.swapText}>Swap roles</Text>
        </TouchableOpacity>

        {renderField(
          'Pollen parent', 'Written second — donates the pollen',
          pollenParent, setPollenParent, 'pollen', 'flower-outline'
        )}
      </View>

      <TouchableOpacity
        style={[styles.checkBtn, SHADOW.md,
          (!podParent.trim() || !pollenParent.trim()) && styles.checkBtnDisabled]}
        onPress={handleCheck}
        disabled={loading || !podParent.trim() || !pollenParent.trim()}
      >
        {loading ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <>
            <Ionicons name="git-compare-outline" size={18} color="#fff" />
            <Text style={styles.checkBtnText}>Check Compatibility</Text>
          </>
        )}
      </TouchableOpacity>

      {result && (
        <View style={[styles.resultCard, SHADOW.md, { borderLeftColor: tierColor(result.tier) }]}>
          <View style={styles.resultHeader}>
            <Ionicons
              name={TIER_STYLE[result.tier]?.icon || 'help-circle'}
              size={26}
              color={tierColor(result.tier)}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.tierLabel, { color: tierColor(result.tier) }]}>
                {result.tier_label}
              </Text>
              <Text style={styles.crossLine}>
                {result.pod_parent}  ×  {result.pollen_parent}
              </Text>
            </View>
          </View>

          {result.compatibility_class ? (
            <View style={[styles.classBadge, { backgroundColor: tierColor(result.tier) + '22' }]}>
              <Text style={[styles.classBadgeText, { color: tierColor(result.tier) }]}>
                {result.compatibility_class}
              </Text>
            </View>
          ) : null}

          <Text style={styles.headline}>{result.headline}</Text>

          {result.health_used ? (
            <Text style={styles.healthNote}>
              Photo assessment of the pod parent was applied to this result.
            </Text>
          ) : null}

          {result.cross_type ? (
            <View style={styles.chipRow}>
              <View style={styles.chip}>
                <Text style={styles.chipText}>{result.cross_type}</Text>
              </View>
              <View style={styles.chip}>
                <Text style={styles.chipText}>
                  {result.pod_genus} × {result.pollen_genus}
                </Text>
              </View>
            </View>
          ) : null}

          {result.reasoning?.length > 0 && (
            <View style={styles.block}>
              {result.reasoning.map((r, i) => (
                <Text key={i} style={styles.reasonText}>• {r}</Text>
              ))}
            </View>
          )}

          {result.precedents?.length > 0 && (
            <View style={styles.block}>
              <Text style={styles.blockTitle}>Registered precedents</Text>
              {result.precedents.map((p, i) => (
                <Text key={i} style={styles.precedentText}>
                  {p.seed_parent} × {p.pollen_parent} = {p.grex}
                  {p.year ? `  (${p.year})` : ''}
                </Text>
              ))}
            </View>
          )}

          {result.expected_offspring?.known && (
            <View style={styles.block}>
              <Text style={styles.blockTitle}>Expected offspring</Text>
              {result.expected_offspring.flower_size && (
                <Text style={styles.reasonText}>
                  • Flower size: {result.expected_offspring.flower_size}
                </Text>
              )}
              {result.expected_offspring.colour_influences && (
                <Text style={styles.reasonText}>
                  • Colour from: {result.expected_offspring.colour_influences.join(' + ')}
                </Text>
              )}
              {result.expected_offspring.fragrance && (
                <Text style={styles.reasonText}>
                  • {result.expected_offspring.fragrance}
                </Text>
              )}
              {result.expected_offspring.caveat && (
                <Text style={styles.caveatText}>{result.expected_offspring.caveat}</Text>
              )}
            </View>
          )}

          {result.warnings?.map((w, i) => (
            <View key={i} style={styles.warnBox}>
              <Ionicons name="alert-circle-outline" size={13} color={COLORS.warning} />
              <Text style={styles.warnText}>{w}</Text>
            </View>
          ))}

          {result.suggestion ? (
            <View style={styles.nextBox}>
              <Text style={styles.nextTitle}>Next step</Text>
              <Text style={styles.nextText}>{result.suggestion}</Text>
            </View>
          ) : null}

          {/* Explains the absence of a percentage before anyone asks for one. */}
          <Text style={styles.methodNote}>
            No success percentage is shown. The orchid register records only crosses
            that worked, so it cannot say how often attempts fail.
          </Text>
        </View>
      )}

      <View style={{ height: 60 }} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginTop: SPACE.md, marginBottom: SPACE.xs },
  intro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19, marginBottom: SPACE.md },

  linkCard: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md,
    marginBottom: SPACE.md, borderWidth: 1, borderColor: COLORS.border,
  },
  linkCardActive: { borderColor: COLORS.primary, backgroundColor: COLORS.primaryDim },
  linkTitle: { color: COLORS.text, fontSize: FONT.xs, fontWeight: '700', marginBottom: 2 },
  linkBody: { flex: 1, color: COLORS.textSecondary, fontSize: 11, lineHeight: 16 },

  classBadge: {
    alignSelf: 'flex-start', borderRadius: RADIUS.full,
    paddingHorizontal: SPACE.md, paddingVertical: 3, marginBottom: SPACE.sm,
  },
  classBadgeText: { fontSize: FONT.xs, fontWeight: '800', letterSpacing: 0.3 },
  healthNote: {
    color: COLORS.primary, fontSize: 11, fontStyle: 'italic', marginBottom: SPACE.sm,
  },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg, marginBottom: SPACE.lg },

  fieldBlock: { marginBottom: SPACE.xs },
  fieldLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 2 },
  fieldLabel: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  fieldHint: { color: COLORS.textTertiary, fontSize: FONT.xs, marginBottom: SPACE.xs },
  input: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
    borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
    color: COLORS.text, fontSize: FONT.sm,
  },

  linkThumb: { width: 44, height: 44, borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCardAlt },
  suggestBox: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
    borderColor: COLORS.borderLight, marginTop: 4, overflow: 'hidden',
  },
  suggestItem: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm,
    borderBottomWidth: 1, borderBottomColor: COLORS.borderLight,
  },
  suggestText: { color: COLORS.textSecondary, fontSize: FONT.xs },

  swapBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, paddingVertical: SPACE.sm, marginVertical: SPACE.xs,
  },
  swapText: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '700' },

  checkBtn: {
    backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, marginBottom: SPACE.lg,
  },
  checkBtnDisabled: { opacity: 0.5 },
  checkBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  resultCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg,
    borderLeftWidth: 4, marginBottom: SPACE.md,
  },
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.md },
  tierLabel: { fontSize: FONT.lg, fontWeight: '800' },
  crossLine: { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 2 },
  headline: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600', lineHeight: 20, marginBottom: SPACE.sm },

  chipRow: { flexDirection: 'row', gap: SPACE.xs, flexWrap: 'wrap', marginBottom: SPACE.md },
  chip: { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.full, paddingHorizontal: SPACE.md, paddingVertical: 3 },
  chipText: { color: COLORS.textSecondary, fontSize: 10, fontWeight: '600' },

  block: { marginBottom: SPACE.md },
  blockTitle: { color: COLORS.text, fontSize: FONT.xs, fontWeight: '700', marginBottom: SPACE.xs, textTransform: 'uppercase', letterSpacing: 0.5 },
  reasonText: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 18, marginBottom: 3 },
  precedentText: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 18, marginBottom: 3, fontStyle: 'italic' },
  caveatText: { color: COLORS.textTertiary, fontSize: 10, lineHeight: 15, marginTop: SPACE.xs },

  warnBox: {
    flexDirection: 'row', gap: 6, backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xs,
  },
  warnText: { flex: 1, color: COLORS.textSecondary, fontSize: 11, lineHeight: 16 },

  nextBox: { backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginTop: SPACE.xs },
  nextTitle: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '700', marginBottom: 3 },
  nextText: { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 18 },

  methodNote: {
    color: COLORS.textTertiary, fontSize: 10, lineHeight: 15,
    marginTop: SPACE.md, paddingTop: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },
});

export default CompatibilityTab;
