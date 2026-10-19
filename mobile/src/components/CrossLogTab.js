import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Image, ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import {
  getLogReference, getCrosses, getLogStats, logCross, updateCrossStage,
  registerPlant, uploadLogPhoto, logPhotoUrl, deleteCross,
} from '../services/crossLog';
import AppDialog from './AppDialog';
import { scheduleCrossReminders } from '../services/crossReminders';

/**
 * The grower's own crossing logbook.
 *
 * WHY IT EXISTS
 * The RHS register lists hybrids that were made and registered. Nobody
 * registers "I tried this and got no pod", so the register has no
 * denominator and no honest success rate can come out of it. This screen
 * collects the other half: what was actually attempted and what actually
 * happened, failures included.
 *
 * It predicts nothing. On the day it ships it is empty, and it says so.
 *
 * THREE FAILURES, NOT ONE
 * A cross can stop at three different gates and they mean different things -
 * no pod set is usually technique or dead pollen, an aborted capsule is
 * usually the pod parent's condition, an empty capsule is where genetic
 * incompatibility actually shows. A single success/failure flag would throw
 * away the only signal worth collecting, so a closed record always names the
 * gate it stopped at.
 *
 * "Lost track" is deliberately NOT a failure. A record whose label went
 * missing is censored data; counting it as a failure would bias every number
 * on this screen.
 *
 * NAMES ARE OPTIONAL
 * Half the plants in a working collection have an unreadable tag. A plant
 * logged without a name gets an id - P-004 - that the grower can write on a
 * new label, and the name can be filled in later.
 */

const TONE = {
  open:    { fg: COLORS.primary, bg: COLORS.primaryDim },
  due:     { fg: COLORS.warning, bg: COLORS.warningDim },
  success: { fg: COLORS.success, bg: COLORS.successDim },
  failed:  { fg: COLORS.danger,  bg: COLORS.dangerDim },
  lost:    { fg: COLORS.textTertiary, bg: COLORS.bgCardAlt },
};

const BLANK_PARENT = { uri: null, name: '', busy: false };

const CrossLogTab = ({ level1Result = null, level1Image = null,
                       crossParents = null }) => {
  const [reference, setReference] = useState(null);
  const [crosses, setCrosses] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [composing, setComposing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pod, setPod] = useState(BLANK_PARENT);
  const [pollen, setPollen] = useState(BLANK_PARENT);
  const [flowerAge, setFlowerAge] = useState('');
  const [pollenFresh, setPollenFresh] = useState(true);
  const [notes, setNotes] = useState('');

  const [expanded, setExpanded] = useState(null);
  const [working, setWorking] = useState(null);

  /* Everything the screen has to say goes through one themed dialog rather
     than Alert.alert. The platform alert is a white box with blue system
     text; in a green app it reads as an error from somewhere else, and the
     first grower to see one thought the app had crashed. */
  const [dialog, setDialog] = useState(null);
  const say = (d) => setDialog(d);
  const closeDialog = () => setDialog(null);

  /** The ⓘ affordance: explain one stage, in the grower's words. */
  const explainStage = (stageKey) => {
    const s = stageList.find((x) => x.key === stageKey);
    if (!s) return;
    say({
      tone: 'info', title: s.label, message: s.detail,
      sections: [
        { label: 'Where to look', text: s.look_for },
        { label: 'How long', text: s.timing },
      ],
    });
  };

  /** The ⓘ affordance for an outcome — what it means and how it is counted. */
  const explainExit = (exitKey) => {
    const e = exits[exitKey];
    if (!e) return;
    say({
      tone: exitKey === 'lost' ? 'info' : 'warn',
      title: e.label, message: `${e.means}

${e.detail}`,
      sections: [{ label: 'How it is counted', text: e.counts_as }],
    });
  };

  /** The ⓘ affordance for a field in the composer. */
  const explainField = (key) => {
    const f = fieldHelp[key];
    if (!f) return;
    say({ tone: 'info', title: f.label, message: `${f.short}

${f.detail}` });
  };

  const refresh = useCallback(async () => {
    try {
      const [list, counts] = await Promise.all([getCrosses(), getLogStats()]);
      setCrosses(list);
      setStats(counts);
      setError('');
    } catch (e) {
      setError(e.message || 'Could not load the logbook.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    getLogReference().then(setReference).catch(() => setReference(null));
    refresh();
  }, [refresh]);

  const stageList = reference?.stages || [];
  const exits = reference?.exits || {};
  const fieldHelp = reference?.fieldHelp || {};
  const stageAt = (key) => stageList.findIndex((s) => s.key === key);

  /** The stage that comes after this one, or null at the end of the pipeline. */
  const nextStage = (key) => {
    const i = stageAt(key);
    return i >= 0 && i + 1 < stageList.length ? stageList[i + 1] : null;
  };

  /** The exit that belongs at this stage, if the grower is closing it here. */
  const exitAt = (key) =>
    Object.entries(exits).find(([, v]) => v.after === key) || null;

  // ── composing a new cross ─────────────────
  const pickPhoto = async (which, fromCamera) => {
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      say({
        tone: 'warn', title: 'Permission needed',
        message: fromCamera
          ? 'The app needs camera access to photograph this parent.'
          : 'The app needs photo access to pick an image for this parent.',
      });
      return;
    }

    const picked = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.7, allowsEditing: true })
      : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'], quality: 0.7, allowsEditing: true,
        });
    if (picked.canceled || !picked.assets?.[0]) return;

    const setter = which === 'pod' ? setPod : setPollen;
    setter((p) => ({ ...p, uri: picked.assets[0].uri }));
  };

  const openComposer = () => {
    /* Start from whatever has already been photographed, so nothing is asked
       for twice. The Cross tab is the better source when it has been used,
       because by then BOTH parents have been photographed there; the Assess
       tab only ever describes one plant. Either can be cleared or replaced
       like any other. */
    const podUri = crossParents?.pod?.uri || level1Image;
    const pollenUri = crossParents?.pollen?.uri || null;
    setPod(podUri ? { ...BLANK_PARENT, uri: podUri } : BLANK_PARENT);
    setPollen(pollenUri ? { ...BLANK_PARENT, uri: pollenUri } : BLANK_PARENT);
    setFlowerAge('');
    setPollenFresh(true);
    setNotes('');
    setComposing(true);
  };

  const saveCross = async () => {
    if (!pod.uri && !pod.name.trim()) {
      say({
        tone: 'warn', title: 'Pod parent needed',
        message: 'Add a photograph or a name for the plant that will carry '
               + 'the capsule. Either one on its own is enough.',
      });
      return;
    }
    if (!pollen.uri && !pollen.name.trim()) {
      say({
        tone: 'warn', title: 'Pollen parent needed',
        message: 'Add a photograph or a name for the plant donating the '
               + 'pollinia. Either one on its own is enough.',
      });
      return;
    }

    setSaving(true);
    try {
      // Register both plants first: a plant record binds the photograph and
      // the name together, which is the one thing the Cross tab cannot do
      // when the two are typed and photographed independently.
      const [podPhoto, pollenPhoto] = await Promise.all([
        pod.uri ? uploadLogPhoto(pod.uri) : Promise.resolve(''),
        pollen.uri ? uploadLogPhoto(pollen.uri) : Promise.resolve(''),
      ]);

      const [podPlant, pollenPlant] = await Promise.all([
        registerPlant({ name: pod.name.trim(), photo: podPhoto }),
        registerPlant({ name: pollen.name.trim(), photo: pollenPhoto }),
      ]);

      const age = parseInt(flowerAge, 10);
      const cross = await logCross({
        pod_plant_id: podPlant.plantId,
        pollen_plant_id: pollenPlant.plantId,
        // Only the pod parent's reading is carried across, and only when the
        // grower kept the Assess photo for that slot.
        pod_health: (level1Result && pod.uri === level1Image)
          ? { suitability: level1Result.suitability, confidence: level1Result.confidence }
          : null,
        flower_age_days: Number.isFinite(age) ? age : null,
        pollen_source: pollenFresh ? 'fresh' : 'stored',
        notes: notes.trim(),
      });

      // Nine months is far longer than anyone remembers an unmarked capsule.
      // A failure to schedule must never fail the save, so it is swallowed.
      scheduleCrossReminders(cross).catch(() => {});

      setComposing(false);
      await refresh();
      say({
        tone: 'success',
        title: `Logged as ${cross.crossId}`,
        message: `${cross.podName} × ${cross.pollenName}`,
        sections: [
          { label: 'Do this now',
            text: `Write ${cross.crossId} on a tag and tie it to the `
                + 'pollinated flower. In nine months that label is the only '
                + 'thing that tells this capsule apart from any other.' },
          { label: 'Next check',
            text: 'In about two weeks, look at the short green stalk just '
                + 'behind the flower. If it has thickened, the cross has '
                + 'taken. The app will remind you.' },
        ],
      });
    } catch (e) {
      say({ tone: 'warn', title: 'Could not save',
            message: e.message || 'Please try again.' });
    } finally {
      setSaving(false);
    }
  };

  // ── moving a cross along ──────────────────
  const advance = async (cross, stageKey) => {
    setWorking(cross.crossId);
    try {
      await updateCrossStage(cross.crossId, { stage: stageKey });
      await refresh();
    } catch (e) {
      say({ tone: 'warn', title: 'Could not update',
            message: e.message || 'Please try again.' });
    } finally {
      setWorking(null);
    }
  };

  /**
   * Close a cross at the gate it stopped at.
   *
   * The dialog explains the outcome before asking, not after. A grower
   * choosing "No pod set" should already know that it usually means the
   * timing or the pollen rather than the two plants being incompatible -
   * otherwise the record is accurate and the conclusion drawn from it is not.
   */
  const close = (cross, outcomeKey) => {
    const exit = exits[outcomeKey] || {};
    say({
      tone: outcomeKey === 'lost' ? 'info' : 'warn',
      title: exit.label || 'Close this cross',
      message: exit.means || '',
      sections: [
        { label: 'What this usually means', text: exit.detail },
        { label: 'How it is counted', text: exit.counts_as },
      ],
      actions: [
        { label: 'Cancel', style: 'quiet' },
        {
          label: `Record as ${exit.label}`,
          style: 'primary',
          onPress: async () => {
            setWorking(cross.crossId);
            try {
              await updateCrossStage(cross.crossId, { outcome: outcomeKey });
              await refresh();
            } catch (e) {
              say({ tone: 'warn', title: 'Could not update',
                    message: e.message || 'Please try again.' });
            } finally {
              setWorking(null);
            }
          },
        },
      ],
    });
  };

  /**
   * Remove a record entirely.
   *
   * This has to exist - anyone learning the app makes test entries and
   * duplicates, and a logbook full of junk is one the grower stops trusting.
   *
   * It is also the one button that can quietly undo the point of the whole
   * feature. Delete every cross that failed and what remains is a book of
   * successes: the exact bias the RHS register already has and this logbook
   * exists to correct. So a recorded failure is not removed behind the same
   * question as a mistake - the dialog names what is being thrown away and
   * offers the alternative first.
   */
  const remove = (cross) => {
    const isRecordedFailure = cross.closed && cross.outcome !== 'lost';

    say({
      tone: 'danger',
      title: isRecordedFailure ? 'Remove a recorded failure?' : 'Remove this record?',
      message: isRecordedFailure
        ? `${cross.crossId} is a cross you recorded as "${cross.outcomeLabel}". `
          + 'Failures are the half of the picture no register keeps, and this '
          + 'logbook exists to hold them.'
        : `${cross.crossId} — ${cross.podName} × ${cross.pollenName}. This `
          + 'cannot be undone.',
      sections: isRecordedFailure
        ? [{ label: 'Before you do',
             text: 'Remove it only if it was a test entry or a duplicate. If '
                 + 'the cross really did fail, keeping it is what makes every '
                 + 'count on this screen honest - a book of successes only is '
                 + 'the problem, not the record of a failure.' }]
        : [{ label: 'If the cross failed',
             text: 'Close it with the matching outcome instead of removing '
                 + 'it. A failure that was recorded is useful; one that was '
                 + 'deleted is just a gap.' }],
      actions: [
        { label: 'Keep it', style: 'quiet' },
        {
          label: 'Remove',
          style: 'danger',
          onPress: async () => {
            setWorking(cross.crossId);
            try {
              await deleteCross(cross.crossId);
              setExpanded(null);
              await refresh();
            } catch (e) {
              say({ tone: 'warn', title: 'Could not remove',
                    message: e.message || 'Please try again.' });
            } finally {
              setWorking(null);
            }
          },
        },
      ],
    });
  };

  const toneFor = (cross) => {
    if (cross.outcome === 'lost') return TONE.lost;
    if (cross.outcome) return TONE.failed;
    if (cross.stage === 'bloomed') return TONE.success;
    if (cross.overdue) return TONE.due;
    return TONE.open;
  };

  // ── parent block in the composer ──────────
  const renderParentInput = (which, meta) => {
    const value = which === 'pod' ? pod : pollen;
    const setter = which === 'pod' ? setPod : setPollen;

    return (
      <View style={styles.parentBlock}>
        <View style={styles.parentHead}>
          <View style={styles.ordinal}>
            <Text style={styles.ordinalText}>{meta.n}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.parentTitle}>{meta.title}</Text>
            <Text style={styles.parentSub}>{meta.sub}</Text>
          </View>
        </View>

        <View style={styles.photoRow}>
          {value.uri ? (
            <Image source={{ uri: value.uri }} style={styles.photo} />
          ) : (
            <View style={[styles.photo, styles.photoEmpty]}>
              <Ionicons name="camera-outline" size={20} color={COLORS.textTertiary} />
            </View>
          )}

          <View style={{ flex: 1, gap: SPACE.sm }}>
            <View style={styles.btnRow}>
              <TouchableOpacity style={styles.smallBtn} onPress={() => pickPhoto(which, true)}>
                <Ionicons name="camera" size={13} color={COLORS.primary} />
                <Text style={styles.smallBtnText}>Camera</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.smallBtn} onPress={() => pickPhoto(which, false)}>
                <Ionicons name="images" size={13} color={COLORS.primary} />
                <Text style={styles.smallBtnText}>Gallery</Text>
              </TouchableOpacity>
              {value.uri && (
                <TouchableOpacity
                  style={styles.smallBtn}
                  onPress={() => setter((p) => ({ ...p, uri: null }))}
                >
                  <Ionicons name="close" size={13} color={COLORS.textTertiary} />
                  <Text style={[styles.smallBtnText, { color: COLORS.textTertiary }]}>
                    Clear
                  </Text>
                </TouchableOpacity>
              )}
            </View>

            <TextInput
              style={styles.input}
              value={value.name}
              onChangeText={(t) => setter((p) => ({ ...p, name: t }))}
              placeholder="Name on the tag — leave blank if unknown"
              placeholderTextColor={COLORS.textTertiary}
              autoCapitalize="words"
              autoCorrect={false}
            />
          </View>
        </View>

        {!value.name.trim() && value.uri && (
          <Text style={styles.idNote}>
            No name — filed under an id you can write on a new tag.
          </Text>
        )}
      </View>
    );
  };

  // ── one logged cross ──────────────────────
  const renderCross = (cross) => {
    const tone = toneFor(cross);
    const isOpen = expanded === cross.crossId;
    const busy = working === cross.crossId;
    const next = cross.closed ? null : nextStage(cross.stage);
    const exit = cross.closed ? null : exitAt(cross.stage);
    const podPhoto = logPhotoUrl(cross.photos?.pod);
    const pollenPhoto = logPhotoUrl(cross.photos?.pollen);

    return (
      <View key={cross.crossId} style={[styles.crossCard, SHADOW.sm]}>
        <TouchableOpacity
          style={styles.crossHead}
          onPress={() => setExpanded(isOpen ? null : cross.crossId)}
          activeOpacity={0.7}
        >
          <View style={styles.thumbPair}>
            {podPhoto ? <Image source={{ uri: podPhoto }} style={styles.thumb} />
                      : <View style={[styles.thumb, styles.photoEmpty]} />}
            {pollenPhoto ? <Image source={{ uri: pollenPhoto }} style={[styles.thumb, styles.thumbBack]} />
                         : <View style={[styles.thumb, styles.thumbBack, styles.photoEmpty]} />}
          </View>

          <View style={{ flex: 1 }}>
            <Text style={styles.crossId}>{cross.crossId}</Text>
            <Text style={styles.crossNames} numberOfLines={2}>
              {cross.podName}  ×  {cross.pollenName}
            </Text>
            <View style={styles.badgeRow}>
              <View style={[styles.badge, { backgroundColor: tone.bg }]}>
                <Text style={[styles.badgeText, { color: tone.fg }]}>
                  {cross.closed ? cross.outcomeLabel : cross.stageLabel}
                </Text>
              </View>
              <Text style={styles.dayText}>
                day {cross.dayCount}
                {!cross.closed && cross.dueInDays !== null
                  ? (cross.overdue
                      ? '  ·  check now'
                      : `  ·  check in ${cross.dueInDays}d`)
                  : ''}
              </Text>
            </View>
          </View>

          <Ionicons
            name={isOpen ? 'chevron-up' : 'chevron-down'}
            size={16}
            color={COLORS.textTertiary}
          />
        </TouchableOpacity>

        {isOpen && (
          <View style={styles.crossBody}>
            {/* The pipeline, with where this record has reached.
                Each step is tappable: "Capsule developing" means nothing to
                someone who has not bred orchids before, and a stage nobody
                understands is a stage nobody updates honestly. */}
            <Text style={styles.blockLabel}>Progress — tap any step to see what it means</Text>
            {stageList.filter((s) => s.phase === 'plant' || stageAt(cross.stage) >= stageAt('sown'))
              .map((s) => {
                const reached = stageAt(cross.stage) >= stageAt(s.key);
                const current = cross.stage === s.key && !cross.closed;
                return (
                  <TouchableOpacity
                    key={s.key}
                    style={styles.stepRow}
                    onPress={() => explainStage(s.key)}
                    activeOpacity={0.6}
                  >
                    <Ionicons
                      name={reached ? 'checkmark-circle' : 'ellipse-outline'}
                      size={15}
                      color={reached ? COLORS.success : COLORS.border}
                    />
                    <Text style={[styles.stepText,
                      reached && { color: COLORS.text },
                      current && { fontWeight: '800' }]}>
                      {s.label}
                    </Text>
                    {current ? <Text style={styles.stepNow}>you are here</Text> : null}
                    <Ionicons name="information-circle-outline" size={13}
                      color={COLORS.textTertiary} />
                  </TouchableOpacity>
                );
              })}

            {cross.closed ? (
              <View style={[styles.outcomeBox, { backgroundColor: tone.bg }]}>
                <Text style={[styles.outcomeTitle, { color: tone.fg }]}>
                  {cross.outcomeLabel}
                </Text>
                <Text style={styles.outcomeText}>
                  {exits[cross.outcome]?.means || ''}
                </Text>
              </View>
            ) : (
              <>
                {/* The question, and immediately under it the answer to
                    "how would I know?". Asking a grower whether the ovary
                    swelled without saying where the ovary is was the single
                    worst thing on this screen. */}
                {cross.gateQuestion ? (
                  <TouchableOpacity
                    style={styles.gateBox}
                    onPress={() => explainStage(cross.stage)}
                    activeOpacity={0.7}
                  >
                    <Ionicons name="help-circle" size={15} color={COLORS.primary} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.gateText}>{cross.gateQuestion}</Text>
                      <Text style={styles.gateLookFor} numberOfLines={3}>
                        {stageList.find((s) => s.key === cross.stage)?.look_for || ''}
                      </Text>
                      <Text style={styles.gateMore}>Tap for the full explanation</Text>
                    </View>
                  </TouchableOpacity>
                ) : null}

                {busy ? (
                  <ActivityIndicator color={COLORS.primary} style={{ marginTop: SPACE.md }} />
                ) : (
                  <View style={styles.actionRow}>
                    {next && (
                      <TouchableOpacity
                        style={[styles.actionBtn, styles.actionYes]}
                        onPress={() => advance(cross, next.key)}
                      >
                        <Ionicons name="checkmark" size={14} color="#fff" />
                        <Text style={styles.actionYesText}>{next.label}</Text>
                      </TouchableOpacity>
                    )}

                    {exit && (
                      <TouchableOpacity
                        style={[styles.actionBtn, styles.actionNo]}
                        onPress={() => close(cross, exit[0])}
                      >
                        <Ionicons name="close" size={14} color={COLORS.danger} />
                        <Text style={styles.actionNoText}>{exit[1].label}</Text>
                      </TouchableOpacity>
                    )}

                    <TouchableOpacity
                      style={[styles.actionBtn, styles.actionMuted]}
                      onPress={() => close(cross, 'lost')}
                    >
                      <Ionicons name="help-outline" size={14} color={COLORS.textTertiary} />
                      <Text style={styles.actionMutedText}>Lost track</Text>
                    </TouchableOpacity>
                  </View>
                )}

                {/* What each of those three buttons actually records. Without
                    this the grower is picking between words, not outcomes. */}
                <View style={styles.legend}>
                  {[next && ['checkmark-circle', COLORS.success, next.label,
                             'The cross moved on to this stage.'],
                    exit && ['close-circle', COLORS.danger, exit[1].label,
                             exit[1].means],
                    ['help-circle', COLORS.textTertiary, 'Lost track',
                     'Outcome unknown. Not counted as a failure.'],
                  ].filter(Boolean).map(([icon, colour, label, text], i) => (
                    <TouchableOpacity
                      key={label + i}
                      style={styles.legendRow}
                      onPress={() => {
                        if (label === 'Lost track') return explainExit('lost');
                        if (exit && label === exit[1].label) return explainExit(exit[0]);
                        return explainStage(next ? next.key : cross.stage);
                      }}
                      activeOpacity={0.6}
                    >
                      <Ionicons name={icon} size={12} color={colour} />
                      <Text style={styles.legendText}>
                        <Text style={{ fontWeight: '700', color: COLORS.textSecondary }}>
                          {label}
                        </Text>
                        {'  '}{text}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            )}

            {/* The covariates. A failure with none of these recorded cannot
                be told apart from a careless one. */}
            <Text style={[styles.blockLabel, { marginTop: SPACE.md }]}>Recorded</Text>
            <Text style={styles.metaText}>
              Pollinated {new Date(cross.pollinatedAt).toLocaleDateString()}
              {cross.flowerAgeDays != null ? `  ·  flower ${cross.flowerAgeDays}d old` : ''}
              {cross.pollenSource ? `  ·  ${cross.pollenSource} pollen` : ''}
            </Text>
            {cross.podHealth?.suitability ? (
              <Text style={styles.metaText}>
                Pod parent read as {cross.podHealth.suitability} on the day
              </Text>
            ) : null}
            {cross.notes ? <Text style={styles.metaText}>“{cross.notes}”</Text> : null}

            {/* Last, smallest, and deliberately not beside the outcome
                buttons: removing a record should never be the easy mis-tap
                next to "No pod set". */}
            <TouchableOpacity
              style={styles.removeBtn}
              onPress={() => remove(cross)}
              disabled={busy}
            >
              <Ionicons name="trash-outline" size={12} color={COLORS.textTertiary} />
              <Text style={styles.removeText}>Remove this record</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    );
  };

  // ── render ────────────────────────────────
  if (loading) {
    return (
      <View style={styles.centre}>
        <ActivityIndicator color={COLORS.primary} />
        <Text style={styles.muted}>Loading the logbook…</Text>
      </View>
    );
  }

  return (
    <View>
      <View style={styles.sectionHead}>
        <View style={styles.sectionRule} />
        <Ionicons name="book-outline" size={16} color={COLORS.primary} />
        <Text style={styles.sectionTitle}>Crossing Logbook</Text>
      </View>
      <Text style={styles.intro}>
        The register lists only crosses that worked. Your own attempts go
        here — failures included.
      </Text>

      {error ? (
        <View style={styles.errorBox}>
          <Ionicons name="cloud-offline-outline" size={15} color={COLORS.warning} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      {/* Counts, never rates. */}
      {stats && (
        <View style={[styles.statsCard, SHADOW.sm]}>
          <View style={styles.statsRow}>
            {[['Logged', stats.total, COLORS.text],
              ['In progress', stats.open, COLORS.primary],
              ['Lost track', stats.lost, COLORS.textTertiary]]
              .map(([label, value, tone], i) => (
                <React.Fragment key={label}>
                  {i > 0 && <View style={styles.statDivider} />}
                  <View style={styles.statCell}>
                    <Text style={[styles.statValue, { color: tone }]}>{value}</Text>
                    <Text style={styles.statLabel}>{label}</Text>
                  </View>
                </React.Fragment>
              ))}
          </View>

          <Text style={styles.gatesHead}>How far attempts have reached</Text>

          {stats.gates?.map((g) => (
            <View key={g.key} style={styles.gateRow}>
              <View style={styles.gateTop}>
                <Text style={styles.gateLabel}>{g.label}</Text>
                <Text style={[styles.gateValue, g.n === 0 && styles.gateValueEmpty]}>
                  {g.rate !== null
                    ? `${Math.round(g.rate * 100)}%`
                    : g.n > 0 ? `${g.passed} of ${g.n}` : 'none yet'}
                </Text>
              </View>
              {g.n > 0 && (
                <View style={styles.gateBarBg}>
                  <View style={[styles.gateBar, { width: `${(g.passed / g.n) * 100}%` }]} />
                </View>
              )}
            </View>
          ))}

          <Text style={styles.statsNote}>{stats.note}</Text>
        </View>
      )}

      {!composing && (
        <TouchableOpacity style={[styles.newBtn, SHADOW.md]} onPress={openComposer}>
          <Ionicons name="add-circle-outline" size={18} color="#fff" />
          <Text style={styles.newBtnText}>Log a cross</Text>
        </TouchableOpacity>
      )}

      {composing && (
        <View style={[styles.composer, SHADOW.md]}>
          <View style={styles.composerHead}>
            <Text style={styles.composerTitle}>New cross</Text>
            <TouchableOpacity onPress={() => setComposing(false)} disabled={saving}>
              <Ionicons name="close" size={20} color={COLORS.textTertiary} />
            </TouchableOpacity>
          </View>
          <Text style={styles.composerIntro}>
            Pod parent first. A name is optional.
          </Text>

          {renderParentInput('pod', {
            n: '1', title: 'Pod parent', sub: 'carries the capsule',
          })}
          {renderParentInput('pollen', {
            n: '2', title: 'Pollen parent', sub: 'donates the pollinia',
          })}

          <View style={styles.divider} />

          <Text style={styles.blockLabel}>Conditions at pollination</Text>
          <Text style={styles.fieldHint}>
            Both optional, but they are what makes a later failure readable.
            Tap a label to see why.
          </Text>

          <TouchableOpacity
            style={styles.helpRow}
            onPress={() => explainField('flower_age_days')}
            activeOpacity={0.6}
          >
            <Text style={styles.helpLabel}>Flower age</Text>
            <Ionicons name="information-circle-outline" size={13} color={COLORS.primary} />
            <Text style={styles.helpHint}>
              {fieldHelp.flower_age_days?.short || 'Days the flower had been open.'}
            </Text>
          </TouchableOpacity>

          <View style={styles.inlineRow}>
            <TextInput
              style={[styles.input, { flex: 1 }]}
              value={flowerAge}
              onChangeText={setFlowerAge}
              placeholder="e.g. 4 — leave blank if unsure"
              placeholderTextColor={COLORS.textTertiary}
              keyboardType="number-pad"
            />
          </View>

          <TouchableOpacity
            style={styles.helpRow}
            onPress={() => explainField('pollen_source')}
            activeOpacity={0.6}
          >
            <Text style={styles.helpLabel}>Pollen</Text>
            <Ionicons name="information-circle-outline" size={13} color={COLORS.primary} />
            <Text style={styles.helpHint}>
              {fieldHelp.pollen_source?.short || 'Fresh today, or kept in a fridge.'}
            </Text>
          </TouchableOpacity>

          <View style={styles.toggleRow}>
            {[[true, 'Fresh pollen'], [false, 'Stored pollen']].map(([v, label]) => (
              <TouchableOpacity
                key={label}
                style={[styles.toggle, pollenFresh === v && styles.toggleOn]}
                onPress={() => setPollenFresh(v)}
              >
                <Text style={[styles.toggleText, pollenFresh === v && styles.toggleTextOn]}>
                  {label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <TextInput
            style={[styles.input, styles.notesInput]}
            value={notes}
            onChangeText={setNotes}
            placeholder="Notes (optional)"
            placeholderTextColor={COLORS.textTertiary}
            multiline
          />

          <TouchableOpacity
            style={[styles.saveBtn, saving && { opacity: 0.6 }]}
            onPress={saveCross}
            disabled={saving}
          >
            {saving ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <>
                <Ionicons name="save-outline" size={17} color="#fff" />
                <Text style={styles.saveBtnText}>Save to logbook</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      )}

      {crosses.length === 0 && !composing ? (
        <View style={styles.emptyBox}>
          <Ionicons name="book-outline" size={26} color={COLORS.textTertiary} />
          <Text style={styles.emptyTitle}>Nothing logged yet</Text>
          <Text style={styles.emptyText}>
            Log a cross and the app will ask you about it in two weeks.
          </Text>
        </View>
      ) : (
        crosses.map(renderCross)
      )}

      <View style={{ height: 40 }} />

      {/* One dialog for the whole tab. Everything the screen says — a
          confirmation, an explanation, a failure — comes out of here looking
          like the app rather than like the operating system. */}
      <AppDialog
        visible={Boolean(dialog)}
        tone={dialog?.tone}
        title={dialog?.title}
        message={dialog?.message}
        sections={dialog?.sections || []}
        actions={dialog?.actions}
        onDismiss={closeDialog}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  centre: { alignItems: 'center', paddingVertical: SPACE.xxl, gap: SPACE.sm },
  muted: { color: COLORS.textSecondary, fontSize: FONT.md },

  sectionHead: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    marginTop: SPACE.lg, marginBottom: SPACE.md,
  },
  sectionRule: { width: 3, height: 16, borderRadius: 2, backgroundColor: COLORS.primary },
  sectionTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  intro: { color: COLORS.textSecondary, fontSize: FONT.md, lineHeight: 23, marginBottom: SPACE.md },

  errorBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    backgroundColor: COLORS.warningDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginBottom: SPACE.md,
  },
  errorText: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  // counts
  statsCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    padding: SPACE.lg, marginBottom: SPACE.md,
    borderWidth: 1, borderColor: COLORS.border,
  },
  statsRow: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.lg },
  /* `alignItems: center` alone let each label size itself to its own content
     and then clip against the next cell - on a 426px screen "Logged" rendered
     as "Logge" and "In progress" as "In". The cell now fills its share of the
     row and the label is centred inside it with room to wrap. */
  statCell: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 2 },
  statDivider: { width: 1, height: 30, backgroundColor: COLORS.borderLight },
  statValue: { fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  statLabel: {
    color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2,
    textAlign: 'center', alignSelf: 'stretch',
  },
  gatesHead: {
    color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '700',
    marginBottom: SPACE.sm,
  },
  gateRow: { marginBottom: SPACE.md },
  gateTop: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline',
    marginBottom: 4,
  },
  gateLabel: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  gateValue: {
    color: COLORS.text, fontSize: FONT.sm, fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  gateValueEmpty: { color: COLORS.textTertiary, fontWeight: '400', fontStyle: 'italic' },
  gateBarBg: {
    height: 4, borderRadius: 2, backgroundColor: COLORS.bgCardAlt, overflow: 'hidden',
  },
  gateBar: { height: '100%', borderRadius: 2, backgroundColor: COLORS.primary },
  statsNote: {
    color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17,
    marginTop: SPACE.sm, paddingTop: SPACE.sm,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },

  newBtn: {
    backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, marginBottom: SPACE.lg,
  },
  newBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  // composer
  composer: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg,
    marginBottom: SPACE.lg, borderWidth: 1, borderColor: COLORS.primary,
  },
  composerHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  composerTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  composerIntro: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19, marginTop: 2, marginBottom: SPACE.md },

  parentBlock: { marginBottom: SPACE.lg },
  parentHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.sm },
  ordinal: {
    width: 20, height: 20, borderRadius: 10, backgroundColor: COLORS.primaryDim,
    alignItems: 'center', justifyContent: 'center',
  },
  ordinalText: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '800' },
  parentTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  parentSub: { color: COLORS.textTertiary, fontSize: FONT.sm },

  photoRow: { flexDirection: 'row', gap: SPACE.md, alignItems: 'flex-start' },
  photo: { width: 62, height: 62, borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCardAlt },
  photoEmpty: {
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: COLORS.borderLight, borderStyle: 'dashed',
  },

  btnRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  smallBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: SPACE.md, paddingVertical: 6,
    borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.borderLight,
    backgroundColor: COLORS.bgCardAlt,
  },
  smallBtnText: { fontSize: FONT.sm, color: COLORS.primary, fontWeight: '600' },

  input: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
    borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
    color: COLORS.text, fontSize: FONT.md,
  },
  notesInput: { minHeight: 60, textAlignVertical: 'top', marginTop: SPACE.sm },
  idNote: { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18, marginTop: SPACE.sm, fontStyle: 'italic' },

  divider: { height: 1, backgroundColor: COLORS.borderLight, marginBottom: SPACE.md },
  blockLabel: {
    color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700',
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: SPACE.xs,
  },
  fieldHint: { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 19, marginBottom: SPACE.sm },
  inlineRow: { flexDirection: 'row', gap: SPACE.sm },

  toggleRow: { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.sm },
  toggle: {
    flex: 1, alignItems: 'center', paddingVertical: SPACE.sm,
    borderRadius: RADIUS.sm, borderWidth: 1, borderColor: COLORS.border,
    backgroundColor: COLORS.bgCardAlt,
  },
  toggleOn: { borderColor: COLORS.primary, backgroundColor: COLORS.primaryDim },
  toggleText: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  toggleTextOn: { color: COLORS.primary, fontWeight: '800' },

  saveBtn: {
    backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.md,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.sm, marginTop: SPACE.md,
  },
  saveBtnText: { color: '#fff', fontSize: FONT.md, fontWeight: '700' },

  // logged crosses
  crossCard: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    marginBottom: SPACE.md, borderWidth: 1, borderColor: COLORS.border,
    overflow: 'hidden',
  },
  crossHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, padding: SPACE.md },
  thumbPair: { width: 56, height: 44, justifyContent: 'center' },
  thumb: {
    width: 36, height: 36, borderRadius: RADIUS.sm,
    backgroundColor: COLORS.bgCardAlt, position: 'absolute', left: 0,
  },
  thumbBack: {
    left: 18, borderWidth: 2, borderColor: COLORS.bgCard,
  },
  crossId: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '800', letterSpacing: 0.6 },
  crossNames: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', lineHeight: 20 },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginTop: 4, flexWrap: 'wrap' },
  badge: { borderRadius: RADIUS.full, paddingHorizontal: SPACE.sm, paddingVertical: 2 },
  badgeText: { fontSize: FONT.sm, fontWeight: '800' },
  dayText: { color: COLORS.textTertiary, fontSize: FONT.sm },

  crossBody: {
    paddingHorizontal: SPACE.md, paddingBottom: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight, paddingTop: SPACE.md,
  },
  stepRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, paddingVertical: 4 },
  stepText: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.sm },
  stepNow: {
    color: COLORS.primary, fontSize: FONT.xs, fontWeight: '800',
    textTransform: 'uppercase', letterSpacing: 0.4,
  },

  gateBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm,
    padding: SPACE.md, marginTop: SPACE.md,
  },
  gateText: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', lineHeight: 18 },
  gateLookFor: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19, marginTop: 4 },
  gateMore: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700', marginTop: 5 },

  // What each outcome button actually records
  legend: {
    marginTop: SPACE.md, gap: 5, paddingTop: SPACE.sm,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },
  legendRow: { flexDirection: 'row', gap: 6, alignItems: 'flex-start' },
  legendText: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18 },

  // Field help in the composer
  helpRow: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    marginTop: SPACE.md, marginBottom: 4, flexWrap: 'wrap',
  },
  helpLabel: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  helpHint: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 17, minWidth: 140 },

  removeBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5,
    marginTop: SPACE.md, paddingTop: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.borderLight,
  },
  removeText: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },

  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: SPACE.md },
  actionBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm, borderRadius: RADIUS.sm,
  },
  actionYes: { backgroundColor: COLORS.primary },
  actionYesText: { color: '#fff', fontSize: FONT.sm, fontWeight: '700' },
  actionNo: { borderWidth: 1, borderColor: COLORS.danger, backgroundColor: COLORS.dangerDim },
  actionNoText: { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '700' },
  actionMuted: { borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bgCardAlt },
  actionMutedText: { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '600' },

  outcomeBox: { borderRadius: RADIUS.sm, padding: SPACE.md, marginTop: SPACE.md },
  outcomeTitle: { fontSize: FONT.md, fontWeight: '800', marginBottom: 4 },
  outcomeText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },

  metaText: { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 20 },

  emptyBox: {
    alignItems: 'center', gap: SPACE.sm, paddingVertical: SPACE.xl,
    paddingHorizontal: SPACE.lg,
  },
  emptyTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  emptyText: { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 20, textAlign: 'center' },
});

export default CrossLogTab;
