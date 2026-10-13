/**
 * DiseaseHistoryScreen — every plant checked on this device.
 *
 * One row per analysis: thumbnail, disease, severity, and a Treatment button
 * that opens the full recommendation in a modal.
 *
 * Two details worth knowing:
 *
 * 1. The treatment is read from the STORED entry, not fetched again. Each
 *    history record keeps the whole treatment object, so the modal opens
 *    instantly and works with no network and no backend running. That matters:
 *    a grower looking up what to spray should not need the laptop switched on.
 *
 * 2. A thumbnail may be missing. Only the image PATH is stored, and the phone
 *    may clear its picker cache — see services/diseaseHistory.js. The row then
 *    shows a placeholder icon. The diagnosis and treatment are unaffected
 *    because they are stored as data rather than as a picture.
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, Image, StyleSheet, ScrollView, TouchableOpacity,
  Modal, Alert, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { loadHistory, deleteEntry, clearHistory } from '../services/diseaseHistory';

const SEVERITY_STYLE = {
  mild: { color: COLORS.success, dim: COLORS.successDim, label: 'Mild' },
  moderate: { color: COLORS.warning, dim: COLORS.warningDim, label: 'Moderate' },
  severe: { color: COLORS.danger, dim: COLORS.dangerDim, label: 'Severe' },
};

/** "30 Aug, 14:22" — short enough for a table row. */
function shortDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) +
      ', ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

const DiseaseHistoryScreen = ({ navigation }) => {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);   // entry shown in the modal
  const [brokenImages, setBrokenImages] = useState({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setEntries(await loadHistory());
    setLoading(false);
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const confirmDelete = (entry) => {
    Alert.alert(
      'Delete this record?',
      `${entry.displayName} — ${shortDate(entry.analysedAt)}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => setEntries(await deleteEntry(entry.id)),
        },
      ]
    );
  };

  const confirmClear = () => {
    Alert.alert(
      'Clear all history?',
      'This removes every record on this device and cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear all',
          style: 'destructive',
          onPress: async () => setEntries(await clearHistory()),
        },
      ]
    );
  };

  /* ------------------------------------------------------------------ */
  /* one row                                                             */
  /* ------------------------------------------------------------------ */

  const Row = ({ entry }) => {
    const isHealthy = entry.disease === 'healthy';
    const isUnknown = entry.disease === 'unidentified' || !entry.confident;
    const sev = entry.severity ? SEVERITY_STYLE[entry.severity] : null;

    const tint = isHealthy ? COLORS.success : isUnknown ? COLORS.warning : COLORS.danger;
    const dim = isHealthy ? COLORS.successDim : isUnknown ? COLORS.warningDim : COLORS.dangerDim;

    const showImage = entry.imageUri && !brokenImages[entry.id];

    return (
      <View style={[styles.row, SHADOW.sm]}>
        <View style={styles.rowTop}>
          {showImage ? (
            <Image
              source={{ uri: entry.imageUri }}
              style={styles.thumb}
              // The picker cache may have been cleared; fall back to an icon
              // rather than showing a broken image box.
              onError={() => setBrokenImages((b) => ({ ...b, [entry.id]: true }))}
            />
          ) : (
            <View style={[styles.thumb, styles.thumbMissing]}>
              <Ionicons name="image-outline" size={20} color={COLORS.textTertiary} />
            </View>
          )}

          <View style={styles.rowMain}>
            <Text style={styles.rowTitle} numberOfLines={1}>
              {isUnknown ? 'Unidentified condition' : entry.displayName}
            </Text>
            <Text style={styles.rowMeta}>
              {shortDate(entry.analysedAt)}
              {entry.confidence != null &&
                ` · ${(entry.confidence * 100).toFixed(0)}% confident`}
            </Text>

            <View style={styles.chipRow}>
              <View style={[styles.chip, { backgroundColor: dim }]}>
                <View style={[styles.dot, { backgroundColor: tint }]} />
                <Text style={[styles.chipText, { color: tint }]}>
                  {isHealthy ? 'Healthy' : isUnknown ? 'Needs an expert' : 'Disease found'}
                </Text>
              </View>

              {sev && (
                <View style={[styles.chip, { backgroundColor: sev.dim }]}>
                  <Text style={[styles.chipText, { color: sev.color }]}>{sev.label}</Text>
                </View>
              )}
            </View>
          </View>

          <TouchableOpacity
            onPress={() => confirmDelete(entry)}
            hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
            accessibilityLabel="Delete this record"
          >
            <Ionicons name="trash-outline" size={18} color={COLORS.textTertiary} />
          </TouchableOpacity>
        </View>

        <TouchableOpacity
          style={styles.treatmentBtn}
          onPress={() => setSelected(entry)}
          accessibilityRole="button"
        >
          <Ionicons name="medkit-outline" size={16} color={COLORS.primary} />
          <Text style={styles.treatmentBtnText}>Treatment</Text>
          <Ionicons name="chevron-forward" size={15} color={COLORS.primary} />
        </TouchableOpacity>
      </View>
    );
  };

  /* ------------------------------------------------------------------ */
  /* treatment modal                                                     */
  /* ------------------------------------------------------------------ */

  const Bullets = ({ title, icon, items, tint }) => {
    if (!items || items.length === 0) return null;
    return (
      <View style={styles.block}>
        <View style={styles.blockHead}>
          <Ionicons name={icon} size={15} color={tint} />
          <Text style={styles.blockTitle}>{title}</Text>
        </View>
        {items.map((line, i) => (
          <View key={i} style={styles.bullet}>
            <View style={[styles.bulletDot, { backgroundColor: tint }]} />
            <Text style={styles.bulletText}>{line}</Text>
          </View>
        ))}
      </View>
    );
  };

  const TreatmentModal = () => {
    if (!selected) return null;
    const t = selected.treatment || {};
    const chem = t.chemical_control || {};
    const sev = selected.severity ? SEVERITY_STYLE[selected.severity] : null;

    return (
      <Modal
        visible
        animationType="slide"
        transparent
        onRequestClose={() => setSelected(null)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHead}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle} numberOfLines={2}>
                  {t.display_name || selected.displayName}
                </Text>
                {sev && (
                  <Text style={[styles.modalSeverity, { color: sev.color }]}>
                    {sev.label} severity
                  </Text>
                )}
              </View>
              <TouchableOpacity
                onPress={() => setSelected(null)}
                hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
                accessibilityLabel="Close"
              >
                <Ionicons name="close" size={24} color={COLORS.textSecondary} />
              </TouchableOpacity>
            </View>

            <ScrollView
              style={styles.modalBody}
              contentContainerStyle={{ paddingBottom: SPACE.xl }}
              showsVerticalScrollIndicator={false}
            >
              {t.summary ? <Text style={styles.summary}>{t.summary}</Text> : null}

              <Bullets
                title="Do now"
                icon="flash-outline"
                items={t.immediate_actions}
                tint={COLORS.danger}
              />
              <Bullets
                title="Growing conditions"
                icon="leaf-outline"
                items={t.cultural_control}
                tint={COLORS.primary}
              />

              {chem.options && chem.options.length > 0 && (
                <View style={styles.block}>
                  <View style={styles.blockHead}>
                    <Ionicons name="flask-outline" size={15} color={COLORS.fertilizer} />
                    <Text style={styles.blockTitle}>
                      Chemical treatment{chem.recommended ? '' : ' — not recommended'}
                    </Text>
                  </View>
                  {chem.rationale ? (
                    <Text style={styles.rationale}>{chem.rationale}</Text>
                  ) : null}
                  {chem.options.map((o, i) => (
                    <View key={i} style={styles.chem}>
                      <Text style={styles.chemName}>{o.active_ingredient}</Text>
                      {o.frac_group ? (
                        <Text style={styles.chemFrac}>FRAC {o.frac_group}</Text>
                      ) : null}
                      {/* An unverified rate is replaced by a referral message on
                          the server. Never show a number the backend withheld. */}
                      <Text style={[styles.chemDose, !o.show_dose && styles.chemDoseWarn]}>
                        {o.dose}
                      </Text>
                      {o.notes ? <Text style={styles.chemNote}>{o.notes}</Text> : null}
                    </View>
                  ))}
                </View>
              )}

              {!chem.options?.length && chem.rationale ? (
                <View style={styles.block}>
                  <View style={styles.blockHead}>
                    <Ionicons name="flask-outline" size={15} color={COLORS.textTertiary} />
                    <Text style={styles.blockTitle}>Chemical treatment — not recommended</Text>
                  </View>
                  <Text style={styles.rationale}>{chem.rationale}</Text>
                </View>
              ) : null}

              {t.monitoring ? (
                <View style={styles.block}>
                  <View style={styles.blockHead}>
                    <Ionicons name="eye-outline" size={15} color={COLORS.info} />
                    <Text style={styles.blockTitle}>Monitoring</Text>
                  </View>
                  <Text style={styles.rationale}>{t.monitoring}</Text>
                </View>
              ) : null}

              {t.escalate_to_expert && (
                <View style={styles.expertBox}>
                  <Ionicons name="alert-circle" size={17} color={COLORS.danger} />
                  <Text style={styles.expertText}>
                    {t.escalation_reason || 'Refer this plant to an expert.'}
                  </Text>
                </View>
              )}

              <Bullets
                title="Safety"
                icon="shield-checkmark-outline"
                items={t.safety}
                tint={COLORS.textSecondary}
              />
            </ScrollView>
          </View>
        </View>
      </Modal>
    );
  };

  /* ------------------------------------------------------------------ */

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="History"
        subtitle="Past checks on this device"
        navigation={navigation}
        showBack
      />

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} />}
        showsVerticalScrollIndicator={false}
      >
        {entries.length === 0 && !loading ? (
          <View style={styles.empty}>
            <Ionicons name="time-outline" size={44} color={COLORS.textTertiary} />
            <Text style={styles.emptyTitle}>No checks yet</Text>
            <Text style={styles.emptyText}>
              Analyse a plant and it will appear here with its diagnosis,
              severity and treatment.
            </Text>
            <TouchableOpacity
              style={styles.emptyBtn}
              onPress={() => navigation.navigate('DiseaseDetection')}
            >
              <Ionicons name="camera" size={17} color={COLORS.textInverse} />
              <Text style={styles.emptyBtnText}>Check a plant</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            <View style={styles.listHead}>
              <Text style={styles.listCount}>
                {entries.length} record{entries.length === 1 ? '' : 's'}
              </Text>
              <TouchableOpacity onPress={confirmClear}>
                <Text style={styles.clearLink}>Clear all</Text>
              </TouchableOpacity>
            </View>

            {entries.map((e) => (
              <Row key={e.id} entry={e} />
            ))}

            <Text style={styles.footnote}>
              History is stored on this device only. Uninstalling the app or
              switching phones will not carry it across.
            </Text>
          </>
        )}
      </ScrollView>

      <TreatmentModal />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xxxl * 2 },

  listHead: {
    flexDirection: 'row', justifyContent: 'space-between',
    alignItems: 'center', marginBottom: SPACE.md,
  },
  listCount: { fontSize: FONT.sm, color: COLORS.textTertiary },
  clearLink: { fontSize: FONT.sm, color: COLORS.danger, fontWeight: '600' },

  /* row */
  row: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.lg,
    padding: SPACE.md,
    marginBottom: SPACE.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  rowTop: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.md },
  thumb: { width: 58, height: 58, borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt },
  thumbMissing: { alignItems: 'center', justifyContent: 'center' },
  rowMain: { flex: 1 },
  rowTitle: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  rowMeta: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: 2 },

  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.xs, marginTop: SPACE.sm },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.xs,
    paddingHorizontal: SPACE.sm, paddingVertical: 3, borderRadius: RADIUS.full,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  chipText: { fontSize: FONT.xs, fontWeight: '700' },

  treatmentBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACE.xs, marginTop: SPACE.md, paddingVertical: SPACE.sm,
    backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.md,
  },
  treatmentBtnText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.primary },

  /* empty state */
  empty: { alignItems: 'center', paddingVertical: SPACE.xxxl, gap: SPACE.md },
  emptyTitle: { fontSize: FONT.lg, fontWeight: '700', color: COLORS.text },
  emptyText: {
    fontSize: FONT.sm, color: COLORS.textTertiary,
    textAlign: 'center', lineHeight: 19, paddingHorizontal: SPACE.xl,
  },
  emptyBtn: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.primary, paddingHorizontal: SPACE.xl,
    paddingVertical: SPACE.md, borderRadius: RADIUS.full, marginTop: SPACE.sm,
  },
  emptyBtnText: { color: COLORS.textInverse, fontWeight: '700', fontSize: FONT.md },

  footnote: {
    fontSize: FONT.xs, color: COLORS.textTertiary,
    textAlign: 'center', marginTop: SPACE.md, lineHeight: 16,
  },

  /* modal */
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: COLORS.bgCard,
    borderTopLeftRadius: RADIUS.xl, borderTopRightRadius: RADIUS.xl,
    maxHeight: '86%', paddingTop: SPACE.lg,
  },
  modalHead: {
    flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.md,
    paddingHorizontal: SPACE.lg, paddingBottom: SPACE.md,
    borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  modalTitle: { fontSize: FONT.xl, fontWeight: '700', color: COLORS.text },
  modalSeverity: { fontSize: FONT.sm, fontWeight: '600', marginTop: 2 },
  modalBody: { paddingHorizontal: SPACE.lg, paddingTop: SPACE.md },

  summary: {
    fontSize: FONT.md, color: COLORS.textSecondary,
    lineHeight: 21, marginBottom: SPACE.lg,
  },
  block: { marginBottom: SPACE.lg },
  blockHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: SPACE.sm },
  blockTitle: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.text },
  bullet: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.sm },
  bulletDot: { width: 5, height: 5, borderRadius: 3, marginTop: 7 },
  bulletText: { flex: 1, fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 19 },
  rationale: { fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 19 },

  chem: {
    backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.md, padding: SPACE.md, marginTop: SPACE.sm,
  },
  chemName: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  chemFrac: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: 1 },
  chemDose: { fontSize: FONT.sm, color: COLORS.textSecondary, marginTop: SPACE.sm, lineHeight: 18 },
  chemDoseWarn: { color: COLORS.warning, fontStyle: 'italic' },
  chemNote: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: SPACE.xs, lineHeight: 16 },

  expertBox: {
    flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
    backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.md,
    padding: SPACE.md, marginBottom: SPACE.lg,
  },
  expertText: { flex: 1, fontSize: FONT.sm, color: COLORS.danger, lineHeight: 19, fontWeight: '600' },
});

export default DiseaseHistoryScreen;
