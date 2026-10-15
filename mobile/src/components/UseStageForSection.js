/**
 * "Use this for the section", shown on the Growth screen when a section's Setup
 * tab opened it to check the growth stage with a photo.
 *
 * The Growth screen belongs to the growth-stage component; this card belongs to
 * smart watering and fertilization, and is all that screen needs to know about
 * sections (one prop in, one card out). The photo model names six stages and
 * plant food knows three, so the card PROPOSES which one the photo counts as
 * (services/growthStage.js) and the farmer confirms or changes it before
 * anything is saved. Nothing is written without that tap.
 */
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useCan } from '../config/auth';
import { setGrowthStage } from '../services/careV2';
import { FEED_STAGES, feedStageFor, photoKey, photoName } from '../services/growthStage';

export default function UseStageForSection({ forSection, prediction, navigation }) {
  const can = useCan();
  const data = prediction?.data || {};
  const key = photoKey(data.stage_key || data.stage || data.stage_label || '');
  let conf = Number(data.confidence);
  if (Number.isFinite(conf) && conf > 1) conf /= 100;          // a percentage, not a fraction
  const proposed = feedStageFor(key);
  const [stage, setStage] = useState(proposed);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // A new photo gives a new proposal; the farmer's earlier tap was for the old one.
  useEffect(() => { setStage(proposed); setError(null); }, [key]);

  if (!forSection) return null;
  const name = forSection.name || forSection.sectionId;

  if (!prediction) {
    return (
      <View style={[s.card, s.intro]}>
        <Ionicons name="leaf-outline" size={18} color={COLORS.fertilizer} />
        <Text style={s.introTxt}>
          Checking the growth stage for <Text style={s.strong}>{name}</Text>. Take or choose a
          photo of its plants; you can then use the stage it finds for this section's plant food.
        </Text>
      </View>
    );
  }

  if (!key) {
    return (
      <View style={[s.card, s.intro]}>
        <Ionicons name="help-circle-outline" size={18} color={COLORS.warning} />
        <Text style={s.introTxt}>
          This result cannot be matched to a feeding stage. Try another photo, or choose the
          stage by hand from the section's Setup tab.
        </Text>
      </View>
    );
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await setGrowthStage(forSection.houseId, forSection.sectionId, {
        stage, by: 'photo', photoStage: key,
        photoConfidence: Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : null,
      });
      navigation.goBack();                       // the section reloads on focus
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  };

  const pct = Number.isFinite(conf) ? `${Math.round(conf * 100)}%` : null;
  return (
    <View style={[s.card, SHADOW.sm]}>
      <Text style={s.kicker}>For {name}</Text>
      <Text style={s.lead}>
        The photo shows <Text style={s.strong}>{photoName(key)}</Text>
        {pct ? ` (${pct} sure)` : ''}. For plant food that counts as:
      </Text>
      {Number.isFinite(conf) && conf < 0.5 && (
        <Text style={s.warn}>The model is not sure about this photo. Check the stage before you use it.</Text>
      )}

      <View style={s.chips} accessibilityRole="radiogroup">
        {FEED_STAGES.map((o) => {
          const on = o.key === stage;
          return (
            <TouchableOpacity key={o.key} style={[s.chip, on && s.chipOn]} activeOpacity={0.75}
              onPress={() => setStage(o.key)}
              accessibilityRole="radio" accessibilityState={{ checked: on }}
              accessibilityLabel={`${o.label}${o.key === proposed ? ', suggested' : ''}`}>
              <Text style={[s.chipTxt, on && s.chipTxtOn]}>{o.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <Text style={s.sub}>{(FEED_STAGES.find((o) => o.key === stage) || {}).sub}</Text>
      {stage !== proposed && (
        <Text style={s.sub}>Suggested for {photoName(key)}: {proposed}. You changed it.</Text>
      )}

      {!!error && <Text style={s.err}>{error}</Text>}
      {can('setGrowthStage') ? (
        <TouchableOpacity style={[s.btn, saving && { opacity: 0.6 }]} onPress={save}
          disabled={saving} activeOpacity={0.85} accessibilityRole="button"
          accessibilityLabel={`Use ${stage} for ${name}`}>
          {saving
            ? <ActivityIndicator color={COLORS.textInverse} />
            : <Text style={s.btnTxt}>Use {stage} for {name}</Text>}
        </TouchableOpacity>
      ) : (
        <Text style={s.sub}>Only an admin or operator can change a section's growth stage.</Text>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg,
             borderWidth: 1, borderColor: COLORS.borderLight, marginBottom: SPACE.lg },
  intro:   { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm },
  introTxt:{ flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  strong:  { color: COLORS.text, fontWeight: '800' },
  kicker:  { color: COLORS.fertilizer, fontSize: FONT.xs, fontWeight: '800', letterSpacing: 0.6,
             textTransform: 'uppercase' },
  lead:    { color: COLORS.text, fontSize: FONT.md, lineHeight: 21, marginTop: SPACE.xs },
  warn:    { color: COLORS.warning, fontSize: FONT.sm, lineHeight: 18, marginTop: SPACE.sm },
  chips:   { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.md },
  chip:    { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 40,
             paddingHorizontal: 4, borderRadius: RADIUS.full, borderWidth: 1.5,
             borderColor: COLORS.fertilizer, backgroundColor: COLORS.bgCard },
  chipOn:  { backgroundColor: COLORS.fertilizer },
  // stretched across the chip: sized to its word it clips with Bold text on
  chipTxt: { alignSelf: 'stretch', textAlign: 'center', color: COLORS.fertilizer,
             fontSize: FONT.sm, fontWeight: '800' },
  chipTxtOn: { color: COLORS.textInverse },
  sub:     { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.sm },
  err:     { color: COLORS.danger, fontSize: FONT.sm, marginTop: SPACE.sm },
  btn:     { marginTop: SPACE.md, minHeight: 48, borderRadius: RADIUS.md, alignItems: 'center',
             justifyContent: 'center', paddingHorizontal: SPACE.md, backgroundColor: COLORS.fertilizer },
  btnTxt:  { alignSelf: 'stretch', textAlign: 'center', color: COLORS.textInverse,
             fontSize: FONT.md, fontWeight: '800' },
});
