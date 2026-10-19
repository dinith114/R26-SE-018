/**
 * DiseaseReviewScreen — where an orchid expert decides whether a contributed
 * photo counts.
 *
 * Nothing a grower sends counts toward adding a new disease until it has been
 * approved here. The Disease hub shows this screen only to accounts on the
 * server's expert list, and the server checks that list again on every
 * request, so a phone opening this screen can never grant itself anything.
 *
 * Three decisions:
 *   Approve   the grower's labels are right
 *   Correct   right photo, wrong label: fix the disease, part or severity
 *   Reject    not usable, with a reason the grower will see
 *
 * Every decision is appended to a log on the server and never edited. The
 * Decisions tab shows it: who decided what, and when.
 */

import React, { useState, useCallback, useEffect } from 'react';
import {
  View, Text, Image, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, RefreshControl, KeyboardAvoidingView, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import {
  getReviewQueue, getReviewItem, submitReview, getReviewLog, ApiError,
} from '../services/diseaseApi';

const TABS = [
  { key: 'pending', label: 'Waiting' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Not accepted' },
  { key: 'log', label: 'Decisions' },
];
const PARTS = ['leaf', 'stem', 'flower'];
const GRADES = ['mild', 'moderate', 'severe'];

const STATUS = {
  pending: { color: COLORS.warning, dim: COLORS.warningDim, icon: 'hourglass-outline' },
  approved: { color: COLORS.success, dim: COLORS.successDim, icon: 'checkmark-circle' },
  corrected: { color: COLORS.success, dim: COLORS.successDim, icon: 'create-outline' },
  rejected: { color: COLORS.danger, dim: COLORS.dangerDim, icon: 'close-circle' },
};
const DECISION = { approve: 'Approved', correct: 'Corrected', reject: 'Not accepted' };

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');
const words = (slug) => (slug || '').replace(/_/g, ' ');

function stamp(iso, withTime = false) {
  const d = iso ? new Date(iso) : null;
  if (!d || isNaN(d)) return '';
  const date = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  return withTime
    ? `${date}, ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
    : date;
}

const Flag = ({ icon, text, color, dim }) => (
  <View style={[styles.flag, { backgroundColor: dim }]}>
    <Ionicons name={icon} size={12} color={color} />
    <Text style={[styles.flagText, { color }]} numberOfLines={1}>{text}</Text>
  </View>
);

const Choice = ({ label, on, onPress, color = COLORS.primary }) => (
  <TouchableOpacity
    style={[styles.choice, on && { backgroundColor: color, borderColor: color }]}
    onPress={onPress}
    accessibilityRole="button"
    accessibilityState={{ selected: on }}
  >
    <Text style={[styles.choiceText, on && styles.choiceTextOn]}>{label}</Text>
  </TouchableOpacity>
);

/* -------------------------------------------------------------------------- */
/* One photo, and the decision about it                                        */
/* -------------------------------------------------------------------------- */

const ReviewDetail = ({ imageId, onDone }) => {
  const [item, setItem] = useState(null);
  const [reasons, setReasons] = useState({});
  const [loadError, setLoadError] = useState(null);

  const [action, setAction] = useState(null);           // 'approve' | 'correct' | 'reject'
  const [disease, setDisease] = useState('');
  const [part, setPart] = useState(null);
  const [grade, setGrade] = useState(null);
  const [reason, setReason] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    getReviewItem(imageId)
      .then((body) => {
        if (!active) return;
        setItem(body.item);
        setReasons(body.reject_reasons || {});
        setDisease(body.item.final_display_name);
        setPart(body.item.final_plant_part);
        setGrade(body.item.final_severity);
      })
      .catch((err) => active && setLoadError(err));
    return () => { active = false; };
  }, [imageId]);

  if (loadError) {
    return (
      <View style={styles.errorCard}>
        <Ionicons name="alert-circle" size={20} color={COLORS.danger} />
        <Text style={[styles.errorText, { flex: 1 }]}>{loadError.message}</Text>
      </View>
    );
  }
  if (!item) return <ActivityIndicator style={styles.spinner} color={COLORS.primary} />;

  const s = STATUS[item.status] || STATUS.pending;
  const canConfirm = !busy && action && (action !== 'reject' || reason)
    && (action !== 'correct' || disease.trim());

  const confirm = async () => {
    if (!canConfirm) return;
    setBusy(true);
    setError(null);
    const body = { decision: action, note: note.trim() };
    if (action === 'reject') body.reason = reason;
    if (action === 'correct') Object.assign(body, { disease: disease.trim(), plant_part: part, severity: grade });
    try {
      const res = await submitReview(imageId, body);
      onDone(`${DECISION[action]}: ${imageId}`, res.item);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Could not save the decision.'));
      setBusy(false);
    }
  };

  return (
    <>
      {item.photo ? (
        <Image source={{ uri: item.photo }} style={styles.photo} resizeMode="contain" />
      ) : null}

      <View style={[styles.card, SHADOW.sm]}>
        <Text style={styles.title}>{item.display_name}</Text>
        <Text style={styles.meta}>
          Grower says: {cap(item.plant_part)} · {cap(item.severity)}
        </Text>
        <View style={[styles.pill, { backgroundColor: s.dim }]}>
          <Ionicons name={s.icon} size={13} color={s.color} />
          <Text style={[styles.pillText, { color: s.color }]}>{item.status_text}</Text>
        </View>

        <View style={styles.facts}>
          <Text style={styles.fact}>
            <Text style={styles.factKey}>Sent by  </Text>
            {item.grower} · {item.grower_photos} photo{item.grower_photos === 1 ? '' : 's'} in total,
            {' '}{item.grower_photos_this_disease} of this disease
          </Text>
          <Text style={styles.fact}>
            <Text style={styles.factKey}>Sent  </Text>{stamp(item.submitted_at, true)}
          </Text>
          {item.claimed_confirmed_by ? (
            <Text style={styles.fact}>
              <Text style={styles.factKey}>Says identified by  </Text>{item.claimed_confirmed_by}
            </Text>
          ) : null}
          {item.notes ? (
            <Text style={styles.fact}>
              <Text style={styles.factKey}>Grower's notes  </Text>{item.notes}
            </Text>
          ) : null}
          {item.quality?.width ? (
            <Text style={styles.fact}>
              <Text style={styles.factKey}>Photo  </Text>
              {item.quality.width} × {item.quality.height} px · brightness {item.quality.brightness}
              {' '}· sharpness {item.quality.sharpness}
            </Text>
          ) : null}
          {item.model_check?.text ? (
            <Text style={styles.fact}>
              <Text style={styles.factKey}>Model check  </Text>{item.model_check.text}
            </Text>
          ) : null}
          {item.reviewed_by ? (
            <Text style={styles.fact}>
              <Text style={styles.factKey}>Last decision  </Text>
              {item.reviewed_by}, {stamp(item.reviewed_at, true)}
            </Text>
          ) : null}
        </View>
      </View>

      {item.possible_copies?.length > 0 && (
        <View style={[styles.card, styles.copyCard]}>
          <View style={styles.copyHead}>
            <Ionicons name="copy-outline" size={16} color={COLORS.warning} />
            <Text style={styles.copyTitle}>Possible copies</Text>
          </View>
          {item.possible_copies.map((c) => (
            <View key={c.image_id} style={styles.copyRow}>
              {c.thumbnail ? <Image source={{ uri: c.thumbnail }} style={styles.copyThumb} /> : null}
              <Text style={styles.copyText}>
                {c.image_id} · {c.status} · {c.bits} of 64 fingerprint bits differ
              </Text>
            </View>
          ))}
          <Text style={styles.hint}>
            Near-identical photos count once. If this one adds nothing, reject it as
            "Same plant already sent".
          </Text>
        </View>
      )}

      <Text style={styles.sectionLabel}>YOUR DECISION</Text>
      <View style={styles.actionRow}>
        {[
          ['approve', 'Approve', 'checkmark', COLORS.success],
          ['correct', 'Correct', 'create-outline', COLORS.info],
          ['reject', 'Reject', 'close', COLORS.danger],
        ].map(([key, label, icon, color]) => {
          const on = action === key;
          return (
            <TouchableOpacity
              key={key}
              style={[styles.actionBtn, { borderColor: color }, on && { backgroundColor: color }]}
              onPress={() => { setAction(key); setError(null); }}
              accessibilityRole="button"
              accessibilityState={{ selected: on }}
            >
              <Ionicons name={icon} size={16} color={on ? COLORS.textInverse : color} />
              <Text style={[styles.actionText, { color: on ? COLORS.textInverse : color }]}>
                {label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {action && (
        <View style={[styles.card, SHADOW.sm]}>
          {action === 'approve' && (
            <Text style={styles.panelText}>
              Approve as {item.display_name}, {item.plant_part}, {item.severity}. It
              will count toward adding this condition.
            </Text>
          )}

          {action === 'correct' && (
            <>
              <Text style={styles.panelLabel}>Disease</Text>
              <TextInput style={styles.input} value={disease} onChangeText={setDisease}
                placeholder="Correct disease name" placeholderTextColor={COLORS.textTertiary} />
              <Text style={styles.panelLabel}>Part</Text>
              <View style={styles.choiceRow}>
                {PARTS.map((p) => (
                  <Choice key={p} label={cap(p)} on={part === p} onPress={() => setPart(p)} />
                ))}
              </View>
              <Text style={styles.panelLabel}>Severity</Text>
              <View style={styles.choiceRow}>
                {GRADES.map((g) => (
                  <Choice key={g} label={cap(g)} on={grade === g} onPress={() => setGrade(g)} />
                ))}
              </View>
            </>
          )}

          {action === 'reject' && (
            <>
              <Text style={styles.panelLabel}>Why is it not accepted?</Text>
              <View style={styles.reasonWrap}>
                {Object.entries(reasons).map(([key, label]) => (
                  <Choice key={key} label={label} on={reason === key}
                    onPress={() => setReason(key)} color={COLORS.danger} />
                ))}
              </View>
            </>
          )}

          <Text style={styles.panelLabel}>Note to the grower (optional)</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            value={note}
            onChangeText={setNote}
            placeholder="e.g. This is sunburn, not a disease"
            placeholderTextColor={COLORS.textTertiary}
            multiline
          />

          {error && (
            <View style={[styles.errorCard, { marginTop: SPACE.md, marginBottom: 0 }]}>
              <Ionicons name="alert-circle" size={18} color={COLORS.danger} />
              <Text style={[styles.errorText, { flex: 1 }]}>{error.message}</Text>
            </View>
          )}

          <TouchableOpacity
            style={[styles.primaryBtn, !canConfirm && styles.btnDisabled]}
            onPress={confirm}
            disabled={!canConfirm}
          >
            {busy ? <ActivityIndicator color={COLORS.textInverse} /> : (
              <Text style={styles.primaryBtnText}>
                {action === 'approve' ? 'Approve photo'
                  : action === 'correct' ? 'Save correction' : 'Reject photo'}
              </Text>
            )}
          </TouchableOpacity>
        </View>
      )}

      {item.history?.length > 0 && (
        <>
          <Text style={styles.sectionLabel}>EARLIER DECISIONS</Text>
          {item.history.map((e) => (
            <LogRow key={`${e.at}-${e.decision}`} entry={e} reasons={reasons} />
          ))}
        </>
      )}
    </>
  );
};

/* -------------------------------------------------------------------------- */
/* The decision log                                                            */
/* -------------------------------------------------------------------------- */

const LogRow = ({ entry, reasons }) => {
  const b = entry.before || {};
  const a = entry.after || {};
  const changes = [
    ['final_disease', words], ['final_plant_part', (x) => x], ['final_severity', (x) => x],
  ].filter(([k]) => b[k] !== a[k] && b[k]).map(([k, f]) => `${f(b[k])} → ${f(a[k])}`);
  return (
    <View style={styles.logRow}>
      <Text style={styles.logTop}>
        {DECISION[entry.decision] || entry.decision} · {entry.image_id}
      </Text>
      <Text style={styles.logMeta}>
        {stamp(entry.at, true)} · {entry.expert_email || entry.expert_uid}
      </Text>
      {changes.length > 0 && <Text style={styles.logText}>{changes.join(' · ')}</Text>}
      {entry.reason ? (
        <Text style={styles.logText}>Reason: {reasons[entry.reason] || entry.reason}</Text>
      ) : null}
      {entry.note ? <Text style={styles.logText}>Note: {entry.note}</Text> : null}
    </View>
  );
};

/* -------------------------------------------------------------------------- */
/* The screen                                                                  */
/* -------------------------------------------------------------------------- */

const DiseaseReviewScreen = ({ navigation }) => {
  const [tab, setTab] = useState('pending');
  const [items, setItems] = useState(null);
  const [log, setLog] = useState(null);
  const [reasons, setReasons] = useState({});
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState(null);
  const [banner, setBanner] = useState(null);

  const load = useCallback(async (which) => {
    setError(null);
    try {
      if (which === 'log') {
        const body = await getReviewLog(100);
        setLog(body.decisions || []);
      } else {
        const body = await getReviewQueue(which);
        setItems(body.items || []);
        setReasons(body.reject_reasons || {});
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Could not load the review list.'));
    }
  }, []);

  useFocusEffect(useCallback(() => {
    if (!selected) load(tab);
  }, [tab, selected, load]));

  // Back, from the header or the phone's own button, closes an open photo
  // before it leaves the screen.
  useEffect(() => navigation.addListener('beforeRemove', (e) => {
    if (!selected) return;
    e.preventDefault();
    setSelected(null);
  }), [navigation, selected]);

  const headerNav = selected
    ? { navigate: (...a) => navigation.navigate(...a), goBack: () => setSelected(null) }
    : navigation;

  const switchTab = (key) => {
    setTab(key);
    setItems(null);
    setBanner(null);
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await load(tab);
    setRefreshing(false);
  };

  // Closing the photo re-runs the focus effect above, which reloads the list.
  const done = (message) => {
    setSelected(null);
    setBanner(message);
  };

  const forbidden = error?.status === 403;

  return (
    <KeyboardAvoidingView style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScreenHeader
        title={selected ? 'Review photo' : 'Expert review'}
        subtitle={selected ? selected : 'Photos count only once you approve them'}
        navigation={headerNav}
        showBack
      />

      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
        refreshControl={selected ? undefined
          : <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {selected ? (
          <ReviewDetail imageId={selected} onDone={done} />
        ) : (
          <>
            <View style={styles.tabs}>
              {TABS.map((t) => (
                <TouchableOpacity
                  key={t.key}
                  style={[styles.tab, tab === t.key && styles.tabOn]}
                  onPress={() => switchTab(t.key)}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: tab === t.key }}
                >
                  <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>{t.label}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {banner && (
              <View style={styles.banner}>
                <Ionicons name="checkmark-circle" size={16} color={COLORS.success} />
                <Text style={styles.bannerText}>{banner}</Text>
              </View>
            )}

            {forbidden ? (
              <View style={[styles.card, styles.empty]}>
                <Ionicons name="lock-closed-outline" size={30} color={COLORS.textTertiary} />
                <Text style={styles.emptyTitle}>For orchid experts only</Text>
                <Text style={styles.emptyText}>{error.message}</Text>
              </View>
            ) : error ? (
              <View style={styles.errorCard}>
                <Ionicons name="alert-circle" size={20} color={COLORS.danger} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.errorText}>{error.message}</Text>
                  <TouchableOpacity onPress={() => load(tab)} style={styles.retryBtn}>
                    <Text style={styles.retryText}>Try again</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : tab === 'log' ? (
              log === null ? <ActivityIndicator style={styles.spinner} color={COLORS.primary} />
                : log.length === 0 ? (
                  <Text style={styles.emptyLine}>No decisions yet.</Text>
                ) : log.map((e) => (
                  <LogRow key={`${e.at}-${e.image_id}-${e.decision}`} entry={e} reasons={reasons} />
                ))
            ) : items === null ? (
              <ActivityIndicator style={styles.spinner} color={COLORS.primary} />
            ) : items.length === 0 ? (
              <Text style={styles.emptyLine}>
                {tab === 'pending' ? 'Nothing is waiting for review.' : 'None yet.'}
              </Text>
            ) : items.map((it) => {
              const s = STATUS[it.status] || STATUS.pending;
              return (
                <TouchableOpacity
                  key={it.image_id}
                  style={[styles.card, SHADOW.sm]}
                  onPress={() => { setBanner(null); setSelected(it.image_id); }}
                  accessibilityRole="button"
                  accessibilityLabel={`Review ${it.image_id}, ${it.display_name}`}
                >
                  <View style={styles.rowTop}>
                    {it.thumbnail ? (
                      <Image source={{ uri: it.thumbnail }} style={styles.thumb} />
                    ) : (
                      <View style={[styles.thumb, styles.thumbEmpty]}>
                        <Ionicons name="image-outline" size={22} color={COLORS.textTertiary} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name}>{it.final_display_name}</Text>
                      <Text style={styles.meta}>
                        {cap(it.final_plant_part)} · {cap(it.final_severity)} · {it.grower}
                        {' '}· {stamp(it.submitted_at)}
                      </Text>
                      <View style={styles.flags}>
                        {it.status !== 'pending' && (
                          <Flag icon={s.icon} text={it.status_text} color={s.color} dim={s.dim} />
                        )}
                        {it.possible_copies?.length > 0 && (
                          <Flag icon="copy-outline" text="Possible copy"
                            color={COLORS.warning} dim={COLORS.warningDim} />
                        )}
                        {it.model_check?.status === 'sent_anyway' && (
                          <Flag icon="alert-circle-outline" text="Model: looks like a known disease"
                            color={COLORS.warning} dim={COLORS.warningDim} />
                        )}
                        {it.model_check?.status === 'note' && (
                          <Flag icon="information-circle-outline" text="Unlike orchid leaf photos"
                            color={COLORS.info} dim={COLORS.infoDim} />
                        )}
                        {it.model_check?.status === 'not_checked' && (
                          <Flag icon="remove-circle-outline" text="Not checked by the model"
                            color={COLORS.textSecondary} dim={COLORS.bgCardAlt} />
                        )}
                        {it.claimed_confirmed_by ? (
                          <Flag icon="ribbon-outline" text={`Says: ${it.claimed_confirmed_by}`}
                            color={COLORS.info} dim={COLORS.infoDim} />
                        ) : null}
                        {it.grower_photos_this_disease > 1 && (
                          <Flag icon="person-outline"
                            text={`${it.grower_photos_this_disease} from this grower`}
                            color={COLORS.textSecondary} dim={COLORS.bgCardAlt} />
                        )}
                      </View>
                    </View>
                    <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
                  </View>
                </TouchableOpacity>
              );
            })}
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xxxl * 2 },
  spinner: { marginTop: SPACE.xxl },

  tabs: {
    flexDirection: 'row', backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
    padding: 3, marginBottom: SPACE.md,
  },
  tab: { flex: 1, paddingVertical: SPACE.sm, borderRadius: RADIUS.sm, alignItems: 'center' },
  tabOn: { backgroundColor: COLORS.bgCard },
  tabText: { fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary },
  tabTextOn: { color: COLORS.primary },

  banner: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.successDim, borderRadius: RADIUS.md,
    padding: SPACE.sm, marginBottom: SPACE.md,
  },
  bannerText: { flex: 1, fontSize: FONT.sm, color: COLORS.success, fontWeight: '600' },

  card: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg, padding: SPACE.md,
    borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACE.md,
  },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  thumb: { width: 64, height: 64, borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  meta: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: 2 },
  flags: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.xs, marginTop: SPACE.sm },
  flag: {
    flexDirection: 'row', alignItems: 'center', gap: 3, maxWidth: '100%',
    paddingHorizontal: SPACE.sm, paddingVertical: 2, borderRadius: RADIUS.full,
  },
  flagText: { fontSize: FONT.xs, fontWeight: '700', flexShrink: 1 },

  photo: {
    width: '100%', height: 300, borderRadius: RADIUS.lg,
    backgroundColor: COLORS.bgCardAlt, marginBottom: SPACE.md,
  },
  title: { fontSize: FONT.lg, fontWeight: '700', color: COLORS.text },
  pill: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: SPACE.xs,
    paddingHorizontal: SPACE.sm, paddingVertical: 3, borderRadius: RADIUS.full,
    marginTop: SPACE.sm, maxWidth: '100%',
  },
  pillText: { fontSize: FONT.xs, fontWeight: '700', flexShrink: 1 },
  facts: { marginTop: SPACE.md, gap: SPACE.xs },
  fact: { fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 19 },
  factKey: { fontWeight: '700', color: COLORS.text },

  copyCard: { borderColor: COLORS.warning, backgroundColor: COLORS.warningDim },
  copyHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.xs, marginBottom: SPACE.sm },
  copyTitle: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.warning },
  copyRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.xs },
  copyThumb: { width: 40, height: 40, borderRadius: RADIUS.sm },
  copyText: { flex: 1, fontSize: FONT.xs, color: COLORS.textSecondary },
  hint: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: SPACE.sm, lineHeight: 16 },

  sectionLabel: {
    fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary,
    letterSpacing: 0.8, marginBottom: SPACE.sm, marginTop: SPACE.sm,
  },
  actionRow: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.md },
  actionBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.xs,
    paddingVertical: SPACE.md, borderRadius: RADIUS.md, borderWidth: 1.5,
    backgroundColor: COLORS.bgCard,
  },
  actionText: { fontSize: FONT.sm, fontWeight: '700' },

  panelText: { fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 19 },
  panelLabel: {
    fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary,
    marginTop: SPACE.md, marginBottom: SPACE.xs,
  },
  input: {
    backgroundColor: COLORS.bgInput, borderRadius: RADIUS.md,
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm,
    fontSize: FONT.md, color: COLORS.text,
  },
  textarea: { minHeight: 64, textAlignVertical: 'top' },
  choiceRow: { flexDirection: 'row', gap: SPACE.sm },
  reasonWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  choice: {
    paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bgCard,
  },
  choiceText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.textSecondary },
  choiceTextOn: { color: COLORS.textInverse },

  primaryBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    backgroundColor: COLORS.primary, paddingVertical: SPACE.md,
    borderRadius: RADIUS.full, marginTop: SPACE.lg,
  },
  primaryBtnText: { color: COLORS.textInverse, fontWeight: '700', fontSize: FONT.md },
  btnDisabled: { opacity: 0.45 },

  logRow: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.md,
    borderWidth: 1, borderColor: COLORS.borderLight, marginBottom: SPACE.sm,
  },
  logTop: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.text },
  logMeta: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: 2 },
  logText: { fontSize: FONT.sm, color: COLORS.textSecondary, marginTop: SPACE.xs },

  empty: { alignItems: 'center', padding: SPACE.xl, gap: SPACE.sm },
  emptyTitle: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  emptyText: { fontSize: FONT.sm, color: COLORS.textTertiary, textAlign: 'center', lineHeight: 18 },
  emptyLine: {
    fontSize: FONT.sm, color: COLORS.textTertiary, textAlign: 'center', marginTop: SPACE.xl,
  },

  errorCard: {
    flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.dangerDim,
    borderRadius: RADIUS.md, padding: SPACE.md, marginBottom: SPACE.md,
  },
  errorText: { fontSize: FONT.sm, color: COLORS.danger, fontWeight: '600' },
  retryBtn: { marginTop: SPACE.sm, alignSelf: 'flex-start' },
  retryText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.primary },
});

export default DiseaseReviewScreen;
