import React, { useState, useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, ScrollView, Image,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { assessCompatibility, assessSuitability, getKnownParents } from '../services/api';

/**
 * Level 2 — Parent A × Parent B compatibility.
 *
 * Four things about this screen are deliberate and should not be "improved"
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
 *
 * 3. A cross involves two plants, so BOTH parents get an identical card: a
 *    photograph and the name from the tag, side by side. The cards are built
 *    by one renderer rather than written out twice, so the two sides cannot
 *    drift apart - the asymmetry was the whole of the original complaint.
 *
 *    The same readiness model is used for both plants. It measures whole-plant
 *    condition, which is what the pod parent needs; it does NOT measure pollen
 *    viability, which lives under the anther cap and would need close-ups and
 *    new labels. The difference between the roles is in the THRESHOLD, not the
 *    measurement: Moderate blocks nothing on the pollen side and advises a
 *    reversal on the pod side.
 *
 * 4. The photograph and the name answer different questions and the card says
 *    so in as many words. The model reads CONDITION; it was never trained to
 *    identify a variety, and a grower who assumes the photo filled in the name
 *    would be trusting an identification that was never made.
 */

const TIER_STYLE = {
  registered:     { color: 'success', icon: 'checkmark-circle', short: 'Registered' },
  genus_proven:   { color: 'primary', icon: 'git-compare',      short: 'Proven combination' },
  undemonstrated: { color: 'warning', icon: 'help-circle',      short: 'No precedent' },
  blocked:        { color: 'danger',  icon: 'close-circle',     short: 'Not advised' },
};

const VERDICT_COLOR = {
  'Suitable': 'success',
  'Moderate': 'warning',
  'Not Suitable': 'danger',
};

/* Genus prefixes the engine recognises, for the hint shown while typing.
 *
 * This mirrors GENUS_ABBREV in ml-models/hybrid_pollination/src/cross_notation.py
 * and is deliberately only a HINT: the authoritative reading comes back on the
 * response as `name_check`, which also says whether the genus was stated,
 * looked up, or assumed. Duplicating the list here avoids a round trip on
 * every keystroke; if the two ever disagree, the response wins. */
const KNOWN_GENERA = [
  'v', 'van', 'vanda', 'asctm', 'ascocentrum', 'ascda', 'ascocenda',
  'aer', 'aerides', 'arach', 'arachnis', 'ren', 'renanthera',
  'rhy', 'rhynchostylis', 'phal', 'phalaenopsis', 'papilionanthe', 'pda',
  'luisia', 'vandopsis', 'trichoglottis', 'sarcochilus', 'paraphalaenopsis',
  'aranda', 'mokara', 'renantanda', 'kagawara', 'aeridovanda',
  'papilionanda', 'luisanda', 'paravanda', 'renanopsis', 'renvanvanda',
  'taprobanea',
  // Outside the Vanda alliance - recognised so they can be ruled out
  'cattleya', 'c', 'catt', 'laelia', 'lc', 'laeliocattleya', 'brassavola',
  'epidendrum', 'epi', 'dendrobium', 'den', 'oncidium', 'onc', 'cymbidium',
  'cym', 'paphiopedilum', 'paph', 'miltonia', 'bulbophyllum', 'coelogyne',
  'spathoglottis', 'arundina', 'eria',
];

const BLANK_SHOT = { image: null, result: null, loading: false, refused: null };

const ROLE = {
  pod: {
    key: 'pod',
    ordinal: '1',
    title: 'Pod parent',
    sub: 'carries the seed pod · written first',
    icon: 'ellipse-outline',
    hint: 'Written first — carries the seed pod',
  },
  pollen: {
    key: 'pollen',
    ordinal: '2',
    title: 'Pollen parent',
    sub: 'donates the pollinia · written second',
    icon: 'flower-outline',
    hint: 'Written second — donates the pollen',
  },
};

const CompatibilityTab = ({ level1Result = null, level1Image = null, prefill = null,
                            onParentsChange = null }) => {
  const [podParent, setPodParent] = useState('');
  const [pollenParent, setPollenParent] = useState('');
  const [result, setResult] = useState(null);
  // The half of the verdict that two photographs can carry on their own. The
  // register is indexed by name and cannot be searched without one, but the
  // condition gate never needed a name - withholding it until both tags were
  // typed turned a finished answer into a greyed-out button.
  const [conditionOnly, setConditionOnly] = useState(null);
  const [loading, setLoading] = useState(false);
  const [knownParents, setKnownParents] = useState([]);
  /* The grower's own plants, from the crossing logbook, kept apart from the
     register list. A plant they registered themselves should be offerable
     here - otherwise a name they have already entered once has to be typed
     again from memory - but it is not a register name and the list says so,
     because the app has only ever been told that plant exists. */
  const [myPlants, setMyPlants] = useState([]);
  const [activeField, setActiveField] = useState(null);
  /* The evidence - reasoning, precedents, expected offspring - starts folded.
     Open, the card ran to three screens of register detail under a one-line
     verdict, and the grower it is written for had to scroll past all of it to
     reach the one part they can act on. Folded, the card is the verdict, any
     warning, and the next step; the evidence is one tap away for whoever
     wants to check the reasoning. */
  const [showEvidence, setShowEvidence] = useState(false);
  const [useAssessResult, setUseAssessResult] = useState(true);
  const scrollRef = useRef(null);

  // One shot per parent, same shape, same handlers. A cross is between two
  // plants and the screen that decides it now reads both the same way.
  const [podShot, setPodShot] = useState(BLANK_SHOT);
  const [pollenShot, setPollenShot] = useState(BLANK_SHOT);

  const shotFor = (role) => (role === 'pod' ? podShot : pollenShot);
  const setShotFor = (role, next) =>
    (role === 'pod' ? setPodShot : setPollenShot)(next);

  /* What the system actually knows about each plant's condition.
   *
   * A photo taken on this screen wins over the one carried from the Assess
   * tab, because it is the more recent deliberate act. The Assess tab's
   * result still comes across - that handoff is the point of the two tabs -
   * but it can be switched off, and then nothing is sent for that parent. */
  const podReading = podShot.result
    ? { ...podShot.result, origin: 'here' }
    : (level1Result && useAssessResult)
      ? { ...level1Result, origin: 'assess' }
      : null;

  const pollenReading = pollenShot.result
    ? { ...pollenShot.result, origin: 'here' }
    : null;

  const podImage = podShot.image || (useAssessResult ? level1Image : null);
  const pollenImage = pollenShot.image;

  const healthOf = (reading) =>
    reading ? { suitability: reading.suitability, confidence: reading.confidence } : null;

  const podHealth = healthOf(podReading);
  const pollenHealth = healthOf(pollenReading);

  /* Any change to a photograph or a name invalidates both verdicts, so they
     are always cleared together. Leaving one of them on screen next to edited
     inputs is the worst of the three states: it looks current. */
  const clearVerdicts = () => {
    setResult(null);
    setConditionOnly(null);
  };

  // What there is enough evidence to answer right now. These are separate
  // questions with separate requirements, which is the whole reason the
  // button is no longer a single all-or-nothing gate.
  const haveNames = Boolean(podParent.trim() && pollenParent.trim());
  const haveAnyReading = Boolean(podReading || pollenReading);

  /* Report both parents upward so the logbook composer can start from what
     was already photographed here.
     Without this a grower who assessed two plants on this tab opened the Log
     tab and was asked to photograph both again - the pod parent arrived from
     the Assess tab, the pollen parent arrived from nowhere.

     Two things are kept out of the dependency list on purpose, and both would
     otherwise spin this forever. `onParentsChange` is recreated on every
     render of the parent. And `podReading` is a fresh object on every render
     of THIS component, so depending on it would fire the effect, set state in
     the parent, re-render, build another podReading, and fire again - the
     deps below are the state it is derived from, which are stable. */
  useEffect(() => {
    onParentsChange?.({
      pod: { uri: podImage, result: podReading },
      pollen: { uri: pollenShot.image, result: pollenShot.result },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [podImage, podShot.result, level1Result, useAssessResult,
      pollenShot.image, pollenShot.result]);

  useEffect(() => {
    getKnownParents()
      .then((data) => {
        setKnownParents(data.parents || []);
        setMyPlants(data.mine || []);
      })
      .catch(() => setKnownParents([]));   // Suggestions are optional
  }, []);

  /* A fresh assessment on the Assess tab describes a new plant, so it takes
   * the pod slot back.
   *
   * Without this, "Clear" and "Swap roles" - both of which switch the handoff
   * off, because after either one it no longer describes the pod parent -
   * would switch it off permanently, and a grower who went back and assessed
   * another plant would find the new reading never arrived. The effect keys on
   * the prop's identity, which changes only when a new assessment is made. */
  useEffect(() => {
    if (!level1Result) return;
    setUseAssessResult(true);
    setPodShot(BLANK_SHOT);
    clearVerdicts();
  }, [level1Result]);

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

  /**
   * Photograph one parent and assess its condition.
   *
   * `role` picks which card the result lands in; everything else is identical
   * for the two, which is the reason this is one function. A refused image is
   * kept as its own state rather than thrown as an error, for the same reason
   * the Assess tab does it: the gate declining a photograph is an answer, and
   * presenting it as a failure teaches the grower to retry until something
   * comes back.
   */
  const capture = async (role, fromCamera) => {
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('Permission needed',
        fromCamera ? 'Please allow camera access.' : 'Please allow photo access.');
      return;
    }

    const picked = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.8, allowsEditing: true })
      : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'],
          quality: 0.8,
          allowsEditing: true,
        });
    if (picked.canceled || !picked.assets?.[0]) return;

    const uri = picked.assets[0].uri;
    setShotFor(role, { image: uri, result: null, loading: true, refused: null });
    clearVerdicts();           // the pairing must be re-checked

    try {
      // No traits are passed: the point of this screen is that the grower
      // photographs the plant and the system reads it, not the reverse.
      const response = await assessSuitability(uri, {}, null);
      setShotFor(role, { image: uri, result: response, loading: false, refused: null });
    } catch (error) {
      if (error.notAnOrchid) {
        setShotFor(role, {
          image: uri, result: null, loading: false,
          refused: error.message || 'That does not look like an orchid plant.',
        });
      } else {
        Alert.alert('Could not assess', error.message || 'Please try another photograph.');
        setShotFor(role, BLANK_SHOT);
      }
    }
  };

  const clearShot = (role) => {
    setShotFor(role, BLANK_SHOT);
    // Clearing the pod card also drops the Assess tab's result, otherwise
    // "Clear" would appear to do nothing while that one is still in play.
    if (role === 'pod') setUseAssessResult(false);
    clearVerdicts();
  };

  const tierColor = (tier) => {
    const key = TIER_STYLE[tier]?.color || 'textSecondary';
    return COLORS[key] || COLORS.textSecondary;
  };

  const verdictColor = (suitability) =>
    COLORS[VERDICT_COLOR[suitability] || 'textSecondary'] || COLORS.textSecondary;

  /* Suggestions for whichever field is focused.
   *
   * An empty focused field offers names rather than nothing. "Which names
   * does this thing actually accept?" is the question a grower has BEFORE
   * they have typed anything, and a type-ahead that waits for two characters
   * never answers it - it just lets them finish typing something the engine
   * has never heard of. */
  const suggestionsFor = (value) => {
    const q = value.trim().toLowerCase();
    const tag = (list, source) => list.map((name) => ({ name, source }));
    // The grower's own plants first: a name they entered themselves is the one
    // they are most likely reaching for, and it is the only list that can
    // contain an unregistered seedling.
    const all = [...tag(myPlants, 'mine'), ...tag(knownParents, 'register')];
    if (!q) return all.slice(0, 6);
    return all
      .filter((s) => s.name.toLowerCase().includes(q) && s.name.toLowerCase() !== q)
      .slice(0, 6);
  };

  /**
   * How a typed name is likely to be read, shown under the field as it is
   * entered. The definitive answer arrives on the response; this only exists
   * so the grower is not left wondering until after the check.
   */
  const nameStatus = (value) => {
    const v = value.trim();
    if (!v) return null;

    if (knownParents.some((n) => n.toLowerCase() === v.toLowerCase())) {
      return { kind: 'known', icon: 'checkmark-circle', text: 'In the register' };
    }

    if (myPlants.some((n) => n.toLowerCase() === v.toLowerCase())) {
      return { kind: 'genus', icon: 'leaf-outline', text: 'One of your plants' };
    }

    const first = v.split(/[\s.]+/)[0].toLowerCase();
    if (KNOWN_GENERA.includes(first)) {
      return { kind: 'genus', icon: 'information-circle',
               text: 'Genus recognised' };
    }

    return { kind: 'unknown', icon: 'alert-circle',
             text: 'No genus given — read as a Vanda' };
  };

  /**
   * One sentence on the two plants together.
   *
   * The panel's objection to the earlier version was that a screen about
   * crossing two plants only ever reported on one. This is the line that
   * answers it, and it is deliberately visible BEFORE the compatibility
   * check: the readiness of the pair is a fact about the plants, not a
   * consequence of the names typed under them.
   */
  const pairReadiness = () => {
    if (!podReading && !pollenReading) return null;

    const blocked = [
      podReading?.suitability === 'Not Suitable' && 'pod parent',
      pollenReading?.suitability === 'Not Suitable' && 'pollen parent',
    ].filter(Boolean);

    if (blocked.length) {
      return {
        tone: 'danger',
        icon: 'close-circle',
        text: `The ${blocked.join(' and the ')} ${blocked.length > 1 ? 'were' : 'was'} `
            + 'assessed Not Suitable. This cross will be blocked on plant condition.',
      };
    }

    if (!podReading || !pollenReading) {
      const missing = podReading ? 'pollen parent' : 'pod parent';
      return {
        tone: 'neutral',
        icon: 'camera-outline',
        text: `Only one plant has been photographed. Add a photo of the ${missing} `
            + 'for a reading on both halves of the cross.',
      };
    }

    if (podReading.suitability === 'Moderate') {
      return {
        tone: 'warning',
        icon: 'alert-circle',
        text: 'Both plants were read. The pod parent is only Moderate — carrying a '
            + 'capsule for nine months is the harder job, so consider swapping the roles.',
      };
    }

    if (pollenReading.suitability === 'Moderate') {
      return {
        tone: 'success',
        icon: 'checkmark-circle',
        text: 'Both plants were read. The pollen parent is Moderate, which is '
            + 'acceptable in that role — a donor only has to supply pollinia.',
      };
    }

    return {
      tone: 'success',
      icon: 'checkmark-circle',
      text: 'Both plants were read as Suitable. Neither one blocks the cross on condition.',
    };
  };

  /**
   * The verdict two photographs can carry without any name at all.
   *
   * The condition gate asks whether a plant is fit to be bred from. That
   * question never needed to know what the plant is: a plant in poor
   * condition should not be asked to carry a capsule for nine months
   * whatever its tag turns out to say. Only the register half - precedents,
   * genus, expected offspring - needs the name, because the register is
   * indexed by name and there is nothing in this system that reads a name
   * off a photograph.
   *
   * Separating the two is what lets a grower with an unlabelled plant get a
   * real answer instead of a disabled button.
   */
  const buildConditionVerdict = () => {
    // The button is disabled in this state, so this is a guard rather than a
    // path - but the one-plant branch below dereferences a reading, and a
    // crash in front of the panel is not worth saving five lines over.
    if (!podReading && !pollenReading) {
      return {
        tone: 'neutral',
        icon: 'information-circle',
        title: 'Nothing to go on yet',
        body: 'Neither plant has been photographed and neither has been named.',
        next: 'Photograph a plant, or type both names from the tags.',
      };
    }

    const blocked = [
      podReading?.suitability === 'Not Suitable' && 'pod parent',
      pollenReading?.suitability === 'Not Suitable' && 'pollen parent',
    ].filter(Boolean);

    if (blocked.length) {
      return {
        tone: 'danger',
        icon: 'close-circle',
        title: 'Not advised — plant condition',
        body: `The ${blocked.join(' and the ')} `
            + `${blocked.length > 1 ? 'were' : 'was'} assessed Not Suitable. `
            + 'This verdict does not depend on the names: a plant in this '
            + 'condition should not be bred from whatever its tag turns out to say.',
        next: 'Treat and recover the plant, then photograph it again. A Vanda '
            + 'seed pod takes about nine months to mature, so a weak parent is '
            + 'an expensive gamble.',
      };
    }

    if (!podReading || !pollenReading) {
      const read = podReading ? 'pod parent' : 'pollen parent';
      const other = podReading ? 'pollen parent' : 'pod parent';
      const reading = podReading || pollenReading;
      return {
        tone: 'neutral',
        icon: 'information-circle',
        title: 'One plant read, one still unknown',
        body: `The ${read} was read as ${reading.suitability}, which does not `
            + `rule it out. The ${other} has neither a photograph nor a name, `
            + 'so nothing can be said about the pair yet.',
        next: `Photograph the ${other}, or type both names to search the register.`,
      };
    }

    return {
      tone: 'success',
      icon: 'checkmark-circle',
      title: 'Neither plant blocks the cross',
      body: 'Both plants were read as fit to breed from. That is as far as two '
          + 'photographs can go. Whether these two in particular can be crossed '
          + 'depends on what they are, and the register is indexed by name — no '
          + 'model here reads a variety off a picture.',
      next: 'Type both names from the plant tags above, then run the full check '
          + 'to search the register for precedents.',
    };
  };

  const handleCheck = async () => {
    setActiveField(null);

    // No names: answer the half that does not need them rather than refusing.
    if (!haveNames) {
      clearVerdicts();
      setConditionOnly(buildConditionVerdict());
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 200);
      return;
    }

    setLoading(true);
    clearVerdicts();

    try {
      const response = await assessCompatibility(
        podParent.trim(), pollenParent.trim(), podHealth, pollenHealth
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
    // The photograph belongs to the plant, not to the role, so it travels with
    // the name. Swapping the names alone would re-pair each verdict with the
    // other plant and quietly invert both readings.
    //
    // The pod side can be reading from the Assess tab rather than from a shot
    // of its own, so that reading is first written into a shot. After the swap
    // it describes the plant now sitting in the pollen role, and there is no
    // longer anything for the Assess handoff to point at.
    const podAsShot = (podShot.image || podShot.result)
      ? podShot
      : (level1Result && useAssessResult)
        ? { image: level1Image, result: level1Result, loading: false, refused: null }
        : BLANK_SHOT;

    setPodParent(pollenParent);
    setPollenParent(podParent);
    setPodShot(pollenShot);
    setPollenShot(podAsShot);
    setUseAssessResult(false);
    clearVerdicts();   // The reversed cross is a different question
  };

  /**
   * One parent, whole: its photograph, what the photograph said, and the name
   * from its tag. Both roles are drawn by this, so they cannot diverge.
   */
  /* `part` splits this card in two.
     Photograph and name answer different questions - one reads the plant's
     CONDITION, the other names its VARIETY - and nothing connects them: the
     model has never been trained to tell one Vanda hybrid from another. Shown
     in one card they looked like two halves of a single check, which is what
     made "both parents Suitable" sitting above "low compatibility" read as a
     contradiction. It is not one; they are separate answers. So they are now
     laid out as separate steps, each usable on its own. */
  const renderParentCard = (role, part = 'both') => {
    const meta = ROLE[role];
    const shot = shotFor(role);
    const reading = role === 'pod' ? podReading : pollenReading;
    const image = role === 'pod' ? podImage : pollenImage;
    const value = role === 'pod' ? podParent : pollenParent;
    const setValue = role === 'pod' ? setPodParent : setPollenParent;
    const status = nameStatus(value);
    const suggestions = activeField === role ? suggestionsFor(value) : [];

    return (
      <View style={[styles.parentCard, SHADOW.sm, reading && styles.parentCardRead]}>
        <View style={styles.parentHead}>
          <View style={styles.ordinal}>
            <Text style={styles.ordinalText}>{meta.ordinal}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.parentTitle}>{meta.title}</Text>
            <Text style={styles.parentSub}>{meta.sub}</Text>
          </View>
        </View>

        {/* ---- condition, from a photograph ---- */}
        {part !== 'name' && (
        <View style={styles.photoRow}>
          {image ? (
            <Image source={{ uri: image }} style={styles.photo} />
          ) : (
            <View style={[styles.photo, styles.photoEmpty]}>
              <Ionicons name="camera-outline" size={22} color={COLORS.textTertiary} />
            </View>
          )}

          <View style={{ flex: 1 }}>
            <Text style={styles.blockLabel}>Condition</Text>

            {shot.loading ? (
              <View style={styles.busyRow}>
                <ActivityIndicator size="small" color={COLORS.primary} />
                <Text style={styles.muted}>Reading the photograph…</Text>
              </View>
            ) : shot.refused ? (
              <Text style={[styles.verdictNote, { color: COLORS.warning }]}>
                {shot.refused}
              </Text>
            ) : reading ? (
              <>
                <View style={styles.verdictRow}>
                  <View style={[styles.dot, { backgroundColor: verdictColor(reading.suitability) }]} />
                  <Text style={[styles.verdict, { color: verdictColor(reading.suitability) }]}>
                    {reading.suitability}
                  </Text>

                </View>
                <Text style={styles.verdictNote}>
                  {reading.origin === 'assess'
                    ? 'Carried over from the Assess tab.'
                    : 'Read from the photograph above.'}
                  {reading.suitability === 'Not Suitable'
                    ? ' This blocks the cross.'
                    : reading.suitability === 'Moderate'
                      ? (role === 'pod'
                          ? ' Workable, but the lighter role suits it better.'
                          : ' Acceptable for a pollen donor.')
                      : ''}
                </Text>
              </>
            ) : (
              <Text style={styles.verdictNote}>
                Not photographed yet.
              </Text>
            )}

            <View style={styles.btnRow}>
              <TouchableOpacity
                style={styles.smallBtn}
                onPress={() => capture(role, true)}
                disabled={shot.loading}
              >
                <Ionicons name="camera" size={13} color={COLORS.primary} />
                <Text style={styles.smallBtnText}>Camera</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.smallBtn}
                onPress={() => capture(role, false)}
                disabled={shot.loading}
              >
                <Ionicons name="images" size={13} color={COLORS.primary} />
                <Text style={styles.smallBtnText}>Gallery</Text>
              </TouchableOpacity>

              {(image || reading) && (
                <TouchableOpacity
                  style={styles.smallBtn}
                  onPress={() => clearShot(role)}
                  disabled={shot.loading}
                >
                  <Ionicons name="close" size={13} color={COLORS.textTertiary} />
                  <Text style={[styles.smallBtnText, { color: COLORS.textTertiary }]}>
                    Clear
                  </Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        </View>

        )}

        {part === 'both' && <View style={styles.divider} />}

        {/* ---- identity, from the tag ---- */}
        {part !== 'photo' && (
        <>
        <Text style={styles.blockLabel}>Name on the tag</Text>
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={(t) => { setValue(t); clearVerdicts(); }}
          onFocus={() => setActiveField(role)}
          placeholder="e.g. V. tessellata"
          placeholderTextColor={COLORS.textTertiary}
          autoCapitalize="words"
          autoCorrect={false}
        />

        {suggestions.length > 0 && (
          <View style={styles.suggestBox}>
            <Text style={styles.suggestHead}>
              {value.trim()
                ? 'Matches'
                : `${myPlants.length} of your plants, ${knownParents.length} in the register — browse them all on the Varieties tab`}
            </Text>
            {suggestions.map((sug) => (
              <TouchableOpacity
                key={`${sug.source}:${sug.name}`}
                style={styles.suggestItem}
                onPress={() => { setValue(sug.name); setActiveField(null); }}
              >
                <Ionicons
                  name={sug.source === 'mine' ? 'leaf-outline' : 'library-outline'}
                  size={12}
                  color={sug.source === 'mine' ? COLORS.primary : COLORS.textTertiary}
                />
                <Text style={styles.suggestText}>{sug.name}</Text>
                <Text style={styles.suggestSource}>
                  {sug.source === 'mine' ? 'your plant' : 'register'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        )}

        {status && (
          <View style={styles.statusRow}>
            <Ionicons
              name={status.icon}
              size={12}
              color={status.kind === 'known' ? COLORS.success
                   : status.kind === 'genus' ? COLORS.textTertiary
                   : COLORS.warning}
            />
            <Text style={[styles.statusText,
              status.kind === 'known' && { color: COLORS.success },
              status.kind === 'unknown' && { color: COLORS.warning }]}>
              {status.text}
            </Text>
          </View>
        )}

        {/* The sentence that stops a grower assuming the photograph filled
            this in, and - once they have typed something - the one that stops
            them assuming the app checked it. The model reads condition; it
            has never been trained to tell one Vanda hybrid from another. */}
        <Text style={styles.roleNote}>
          {value.trim()
            ? 'Checked against the register by genus, not by variety.'
            : 'No tag? Skip this step - the condition check does not need a name.'}
        </Text>
        </>
        )}
      </View>
    );
  };

  const readiness = pairReadiness();
  const readinessTone = {
    success: { bg: COLORS.successDim, fg: COLORS.success },
    warning: { bg: COLORS.warningDim, fg: COLORS.warning },
    danger:  { bg: COLORS.dangerDim,  fg: COLORS.danger },
    neutral: { bg: COLORS.bgCardAlt,  fg: COLORS.textSecondary },
  };

  return (
    <ScrollView
      ref={scrollRef}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.sectionTitle}>Check a Cross</Text>
      <Text style={styles.intro}>
        Two checks — do either, or both.
      </Text>

      {/* ---------- STEP 1: the plants ---------- */}
      <View style={styles.stepHead}>
        <Text style={styles.stepNum}>STEP 1</Text>
        <Text style={styles.stepTitle}>The plants</Text>
      </View>
      <Text style={styles.stepIntro}>
        Photograph each one to read its condition.
      </Text>

      {renderParentCard('pod', 'photo')}

      {renderParentCard('pollen', 'photo')}

      {/* The pair, as a pair. */}
      {readiness && (
        <View style={[styles.pairBox, { backgroundColor: readinessTone[readiness.tone].bg }]}>
          <Ionicons
            name={readiness.icon}
            size={16}
            color={readinessTone[readiness.tone].fg}
          />
          <View style={{ flex: 1 }}>
            <Text style={[styles.pairTitle, { color: readinessTone[readiness.tone].fg }]}>
              Both parents
            </Text>
            <Text style={styles.pairText}>{readiness.text}</Text>
          </View>
        </View>
      )}

      {/* ---------- STEP 2: the varieties ---------- */}
      <View style={styles.stepHead}>
        <Text style={styles.stepNum}>STEP 2</Text>
        <Text style={styles.stepTitle}>The varieties</Text>
      </View>
      <Text style={styles.stepIntro}>
        Type what is written on each tag. This searches the register for
        whether these two <Text style={{ fontWeight: '700' }}>genera</Text> have
        been crossed before — Vanda with Vanda, Vanda with Aerides, and so on.
        It does not judge the individual varieties, and it does not look at the
        photographs.
      </Text>

      {renderParentCard('pod', 'name')}
      {renderParentCard('pollen', 'name')}

      {/* The swap lives here rather than beside the photographs.
          A plant's CONDITION is the same whichever role it takes - the model
          reads the plant, not the job - so beside the photos the button looked
          like it did nothing, which is what the grower reported. What the role
          actually changes is the pairing: order is part of the cross (A x B is
          not B x A), and a Moderate plant is questioned as a pod parent while
          being perfectly acceptable as a pollen donor. Both of those are
          decisions about the PAIR, so the control belongs with the pair. */}
      <TouchableOpacity style={styles.swapBtn} onPress={handleSwap}>
        <Ionicons name="swap-vertical" size={15} color={COLORS.primary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.swapText}>Swap roles</Text>
          <Text style={styles.swapNote}>
            Order is part of the cross. The pod parent carries the capsule for
            about nine months, so the stronger plant belongs in that role.
          </Text>
        </View>
      </TouchableOpacity>

      {/* Enabled as soon as there is anything to report.
          It used to require both names, so a grower who had photographed two
          plants and been told both were Suitable then hit a dead button - the
          screen had an answer and was refusing to show it. */}
      <TouchableOpacity
        style={[styles.checkBtn, SHADOW.md,
          !(haveNames || haveAnyReading) && styles.checkBtnDisabled,
          !haveNames && haveAnyReading && styles.checkBtnPartial]}
        onPress={handleCheck}
        disabled={loading || !(haveNames || haveAnyReading)}
      >
        {loading ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <>
            <Ionicons
              name={haveNames ? 'git-compare-outline' : 'leaf-outline'}
              size={18}
              color="#fff"
            />
            <Text style={styles.checkBtnText}>
              {haveNames ? 'Check Compatibility' : 'Check condition only'}
            </Text>
          </>
        )}
      </TouchableOpacity>

      <Text style={styles.btnNote}>
        {haveNames
          ? 'Searches the register and applies both photo readings.'
          : haveAnyReading
            ? 'No names yet — the register needs them. The condition check does not.'
            : 'Photograph a plant, or type both names, to get a verdict.'}
      </Text>

      {/* Half a verdict, labelled as half a verdict. */}
      {conditionOnly && (
        <View style={[styles.resultCard, SHADOW.md,
          { borderLeftColor: readinessTone[conditionOnly.tone].fg }]}>
          <View style={styles.resultHeader}>
            <Ionicons
              name={conditionOnly.icon}
              size={26}
              color={readinessTone[conditionOnly.tone].fg}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.tierLabel, { color: readinessTone[conditionOnly.tone].fg }]}>
                {conditionOnly.title}
              </Text>
              <Text style={styles.crossLine}>From the photographs alone</Text>
            </View>
          </View>

          <Text style={styles.headline}>{conditionOnly.body}</Text>

          <View style={styles.nextBox}>
            <Text style={styles.nextTitle}>Next step</Text>
            <Text style={styles.nextText}>{conditionOnly.next}</Text>
          </View>

          <Text style={styles.methodNote}>
            This is the condition half of the check only. The register half —
            registered precedents, cross type, expected offspring — is indexed
            by name and cannot be searched from a photograph.
          </Text>
        </View>
      )}

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

          {/* The grower's OWN attempts at this pairing, above the register.
              For someone deciding whether to commit a flowering plant for
              nine months, three of their own attempts outrank a stranger's
              single registration from 1963 - and unlike the register, their
              record contains the failures. It is also the only block here
              that survives an unrecognised name: the register cannot look up
              "Yellow Vanda", but the logbook knows what happened when this
              grower crossed it. */}
          {result.your_history?.attempts > 0 && (
            <View style={styles.historyBox}>
              <View style={styles.historyHead}>
                <Ionicons name="book-outline" size={14} color={COLORS.primary} />
                <Text style={styles.historyTitle}>Your own record</Text>
                {result.your_history.rate != null && (
                  <Text style={styles.historyRate}>
                    {Math.round(result.your_history.rate * 100)}% set a pod
                  </Text>
                )}
              </View>
              <Text style={styles.historyText}>{result.your_history.statement}</Text>
              {result.your_history.furthest ? (
                <Text style={styles.historyFurthest}>
                  Furthest reached: {result.your_history.furthest}
                </Text>
              ) : null}
            </View>
          )}

          {/* Every piece of evidence behind the verdict, and where it came
              from.
              Two separate things feed this result and they are gathered in
              completely different ways: a photograph the model read, and a
              name a person typed. Nothing in this system reads a name off a
              picture, so the two cannot be checked against each other - and a
              grower who photographs one plant while typing another plant's
              tag gets a confident verdict about a plant that does not exist.
              That limitation is real and cannot be engineered away here, so
              it is stated instead of left for the panel to find. */}
          <View style={styles.readBlock}>
            <Text style={styles.readTitle}>Where this verdict comes from</Text>

            {['pod', 'pollen'].map((role) => {
              const nc = result.name_check?.[role];
              const health = role === 'pod' ? podHealth : pollenHealth;
              const assumed = nc?.genus_source === 'assumed';

              return (
                <View key={role} style={styles.readLine}>
                  <Text style={styles.readRole}>{ROLE[role].title}</Text>

                  <Text style={styles.readText}>
                    <Text style={styles.readKey}>condition </Text>
                    {health ? (
                      <Text style={{
                        color: health.suitability === 'Not Suitable' ? COLORS.danger
                             : health.suitability === 'Moderate' ? COLORS.warning
                             : COLORS.success,
                        fontWeight: '700',
                      }}>
                        {health.suitability}
                      </Text>
                    ) : (
                      <Text style={styles.readMissing}>not photographed</Text>
                    )}
                    {health ? ' — read from your photograph' : ''}
                  </Text>

                  {nc && (
                    <Text style={styles.readText}>
                      <Text style={styles.readKey}>identity </Text>
                      <Text style={[styles.readGenus, assumed && { color: COLORS.warning }]}>
                        {nc.genus}
                      </Text>
                      {nc.genus_source === 'stated' ? ' — written on the name you typed'
                        : nc.genus_source === 'matched' ? ' — found in the register'
                        : ' — assumed, no genus was given'}
                    </Text>
                  )}
                </View>
              );
            })}

            <Text style={styles.readCaveat}>
              Nothing here identifies a variety from a picture, so the app
              cannot confirm the plant you photographed is the one you named.
            </Text>
          </View>

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

          {(result.reasoning?.length > 0 || result.precedents?.length > 0) && (
            <TouchableOpacity
              style={styles.evidenceToggle}
              onPress={() => setShowEvidence((v) => !v)}
              activeOpacity={0.7}
            >
              <Ionicons
                name={showEvidence ? 'chevron-down' : 'chevron-forward'}
                size={15}
                color={COLORS.primary}
              />
              <Text style={styles.evidenceToggleText}>
                {showEvidence ? 'Hide the evidence' : 'Where this comes from'}
              </Text>
              {result.precedents?.length > 0 && !showEvidence && (
                <Text style={styles.evidenceCount}>
                  {result.precedents.length} registered
                </Text>
              )}
            </TouchableOpacity>
          )}

          {showEvidence && result.reasoning?.length > 0 && (
            <View style={styles.block}>
              {result.reasoning.map((r, i) => (
                <Text key={i} style={styles.reasonText}>• {r}</Text>
              ))}
            </View>
          )}

          {showEvidence && result.precedents?.length > 0 && (
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

          {showEvidence && result.expected_offspring?.known && (
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
            No success percentage: the register holds only crosses that worked,
            so it cannot say how often attempts fail.
          </Text>
        </View>
      )}

      <View style={{ height: 60 }} />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginTop: SPACE.md, marginBottom: SPACE.xs },
  intro: { color: COLORS.textSecondary, fontSize: FONT.md, lineHeight: 23, marginBottom: SPACE.md },

  // ── One parent, whole ──────────────────────
  parentCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg,
    borderWidth: 1, borderColor: COLORS.border,
  },
  parentCardRead: { borderColor: COLORS.primary },

  parentHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.md },
  ordinal: {
    width: 22, height: 22, borderRadius: 11, backgroundColor: COLORS.primaryDim,
    alignItems: 'center', justifyContent: 'center',
  },
  ordinalText: { color: COLORS.primary, fontSize: 11, fontWeight: '800' },
  parentTitle: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '700' },
  parentSub: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2 },

  photoRow: { flexDirection: 'row', gap: SPACE.md, alignItems: 'flex-start' },
  photo: { width: 68, height: 68, borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCardAlt },
  photoEmpty: {
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: COLORS.borderLight, borderStyle: 'dashed',
  },

  blockLabel: {
    color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: SPACE.xs,
  },

  busyRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  muted: { color: COLORS.textSecondary, fontSize: FONT.md },

  verdictRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 2 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  verdict: { fontSize: FONT.xl, fontWeight: '800' },
  historyBox: {
    backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginTop: SPACE.md,
    borderLeftWidth: 3, borderLeftColor: COLORS.primary,
  },
  historyHead: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 },
  historyTitle: { flex: 1, color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  historyRate: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  historyText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  historyFurthest: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 4 },
  suggestSource: { color: COLORS.textTertiary, fontSize: FONT.sm },
  evidenceToggle: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    paddingVertical: SPACE.md,
  },
  evidenceToggleText: { flex: 1, color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  evidenceCount: { color: COLORS.textTertiary, fontSize: FONT.sm },
  verdictNote: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  btnRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: SPACE.sm },
  smallBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: SPACE.md, paddingVertical: 6,
    borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.borderLight,
    backgroundColor: COLORS.bgCardAlt,
  },
  smallBtnText: { fontSize: FONT.sm, color: COLORS.primary, fontWeight: '600' },

  divider: {
    height: 1, backgroundColor: COLORS.borderLight,
    marginVertical: SPACE.md,
  },

  input: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
    borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
    color: COLORS.text, fontSize: FONT.md,
  },

  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 6 },
  statusText: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18 },

  roleNote: {
    color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18,
    marginTop: SPACE.sm, fontStyle: 'italic',
  },

  suggestBox: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
    borderColor: COLORS.borderLight, marginTop: 4, overflow: 'hidden',
  },
  suggestHead: {
    color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700',
    textTransform: 'uppercase', letterSpacing: 0.4, lineHeight: 16,
    paddingHorizontal: SPACE.md, paddingTop: SPACE.sm, paddingBottom: 4,
  },
  suggestItem: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm,
    borderBottomWidth: 1, borderBottomColor: COLORS.borderLight,
  },
  suggestText: { color: COLORS.textSecondary, fontSize: FONT.md },

  swapNote: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 1 },
  stepHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginTop: SPACE.lg, marginBottom: 2 },
  stepNum: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800', letterSpacing: 0.6 },
  stepTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  stepIntro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19, marginBottom: SPACE.md },
  swapBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, paddingVertical: SPACE.md,
  },
  swapText: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },

  // ── The pair, as a pair ────────────────────
  pairBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    borderRadius: RADIUS.sm, padding: SPACE.md,
    marginTop: SPACE.md, marginBottom: SPACE.md,
  },
  pairTitle: {
    fontSize: FONT.sm, fontWeight: '800',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3,
  },
  pairText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },

  checkBtn: {
    backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, marginBottom: SPACE.lg, marginTop: SPACE.xs,
  },
  checkBtnDisabled: { opacity: 0.5 },
  // A real action, but only half the check - it should not look like the full one.
  checkBtnPartial: { backgroundColor: COLORS.textSecondary },
  checkBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  // ── Result ─────────────────────────────────
  resultCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg,
    borderLeftWidth: 4, marginBottom: SPACE.md,
  },
  resultHeader: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.md },
  tierLabel: { fontSize: FONT.lg, fontWeight: '800' },
  crossLine: { color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: 3 },
  headline: { color: COLORS.text, fontSize: FONT.md, fontWeight: '600', lineHeight: 22, marginBottom: SPACE.sm },

  classBadge: {
    alignSelf: 'flex-start', borderRadius: RADIUS.full,
    paddingHorizontal: SPACE.md, paddingVertical: 3, marginBottom: SPACE.sm,
  },
  classBadgeText: { fontSize: FONT.sm, fontWeight: '800', letterSpacing: 0.3 },

  readBlock: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.md,
    borderWidth: 1, borderColor: COLORS.borderLight,
  },
  readTitle: {
    color: COLORS.text, fontSize: FONT.xs, fontWeight: '700',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: SPACE.sm,
  },
  readLine: { marginBottom: SPACE.sm },
  readRole: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: 3 },
  readText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },
  readKey: { color: COLORS.textTertiary },
  readGenus: { fontWeight: '700', color: COLORS.text },
  readMissing: { color: COLORS.textTertiary, fontStyle: 'italic' },
  readCaveat: {
    color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17,
    marginTop: SPACE.xs, paddingTop: SPACE.sm,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },

  btnNote: {
    color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 19,
    textAlign: 'center', marginTop: -SPACE.md, marginBottom: SPACE.lg,
    paddingHorizontal: SPACE.md,
  },

  chipRow: { flexDirection: 'row', gap: SPACE.xs, flexWrap: 'wrap', marginBottom: SPACE.md },
  chip: { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.full, paddingHorizontal: SPACE.md, paddingVertical: 3 },
  chipText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },

  block: { marginBottom: SPACE.md },
  blockTitle: { color: COLORS.text, fontSize: FONT.xs, fontWeight: '700', marginBottom: SPACE.xs, textTransform: 'uppercase', letterSpacing: 0.5 },
  reasonText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 21, marginBottom: 4 },
  precedentText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 21, marginBottom: 4, fontStyle: 'italic' },
  caveatText: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17, marginTop: SPACE.xs },

  warnBox: {
    flexDirection: 'row', gap: 6, backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.xs,
  },
  warnText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  nextBox: { backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginTop: SPACE.xs },
  nextTitle: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700', marginBottom: 4 },
  nextText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 21 },

  methodNote: {
    color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17,
    marginTop: SPACE.md, paddingTop: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },
});

export default CompatibilityTab;
