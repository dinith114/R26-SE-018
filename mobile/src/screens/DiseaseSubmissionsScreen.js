/**
 * DiseaseSubmissionsScreen — the photos this grower has contributed, and what
 * the orchid expert decided about each.
 *
 * Closes the loop: a grower sees that a photo arrived, then whether the expert
 * approved it, corrected its label, or did not accept it and why. Without this
 * a contribution disappears into a queue and nobody learns what makes a useful
 * photo.
 *
 * Only this account's photos are listed. The server filters by the signed-in
 * account, not by the phone, so they follow the grower to a new phone and
 * nobody else's appear here.
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, Image, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { getMyContributions, ApiError } from '../services/diseaseApi';

const STATUS = {
  pending: { icon: 'hourglass-outline', color: COLORS.warning, dim: COLORS.warningDim },
  approved: { icon: 'checkmark-circle', color: COLORS.success, dim: COLORS.successDim },
  corrected: { icon: 'create-outline', color: COLORS.success, dim: COLORS.successDim },
  rejected: { icon: 'close-circle', color: COLORS.danger, dim: COLORS.dangerDim },
};

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');

function day(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d)
    ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : '';
}

const DiseaseSubmissionsScreen = ({ navigation }) => {
  const [items, setItems] = useState(null);
  const [rules, setRules] = useState([]);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await getMyContributions();
      setItems(body.contributions || []);
      setRules(body.rules || []);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Could not load your photos.'));
    }
  }, []);

  // On focus, so a photo sent a moment ago, or a decision made since, shows.
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const tally = (items || []).reduce((acc, it) => {
    const key = it.status === 'corrected' ? 'approved' : it.status;
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});

  return (
    <View style={styles.container}>
      <ScreenHeader title="My photos" subtitle="Contributions and their review"
        navigation={navigation} showBack />

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {items === null && !error && (
          <ActivityIndicator style={styles.spinner} color={COLORS.primary} />
        )}

        {error && (
          <View style={styles.errorCard}>
            <Ionicons name="alert-circle" size={20} color={COLORS.danger} />
            <View style={{ flex: 1 }}>
              <Text style={styles.errorText}>{error.message}</Text>
              {error.hint ? <Text style={styles.errorHint}>{error.hint}</Text> : null}
              <TouchableOpacity onPress={load} style={styles.retryBtn}>
                <Text style={styles.retryText}>Try again</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {items && items.length === 0 && (
          <View style={[styles.card, styles.empty, SHADOW.sm]}>
            <Ionicons name="images-outline" size={34} color={COLORS.textTertiary} />
            <Text style={styles.emptyTitle}>No photos sent yet</Text>
            <Text style={styles.emptyText}>
              Photos of conditions the system cannot identify help add them in a
              future version.
            </Text>
            <TouchableOpacity style={styles.primaryBtn}
              onPress={() => navigation.navigate('DiseaseContribute')}>
              <Ionicons name="add" size={18} color={COLORS.textInverse} />
              <Text style={styles.primaryBtnText}>Contribute a photo</Text>
            </TouchableOpacity>
          </View>
        )}

        {items && items.length > 0 && (
          <>
            <View style={styles.tallyRow}>
              {[
                ['pending', 'Waiting'],
                ['approved', 'Approved'],
                ['rejected', 'Not accepted'],
              ].map(([key, label]) => (
                <View key={key} style={[styles.tally, { backgroundColor: STATUS[key].dim }]}>
                  <Text style={[styles.tallyCount, { color: STATUS[key].color }]}>
                    {tally[key] || 0}
                  </Text>
                  <Text style={styles.tallyLabel}>{label}</Text>
                </View>
              ))}
            </View>

            {items.map((it) => {
              const s = STATUS[it.status] || STATUS.pending;
              return (
                <View key={it.image_id} style={[styles.card, SHADOW.sm]}>
                  <View style={styles.rowTop}>
                    {it.thumbnail ? (
                      <Image source={{ uri: it.thumbnail }} style={styles.thumb} />
                    ) : (
                      <View style={[styles.thumb, styles.thumbEmpty]}>
                        <Ionicons name="image-outline" size={22} color={COLORS.textTertiary} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.name}>{it.display_name}</Text>
                      <Text style={styles.meta}>
                        {cap(it.plant_part)} · {cap(it.severity)} · sent {day(it.submitted_at)}
                      </Text>
                      <View style={[styles.pill, { backgroundColor: s.dim }]}>
                        <Ionicons name={s.icon} size={13} color={s.color} />
                        <Text style={[styles.pillText, { color: s.color }]}>{it.status_text}</Text>
                      </View>
                    </View>
                  </View>
                  {it.review_note ? (
                    <View style={styles.noteBox}>
                      <Text style={styles.noteLabel}>Expert's note</Text>
                      <Text style={styles.noteText}>{it.review_note}</Text>
                    </View>
                  ) : null}
                </View>
              );
            })}
          </>
        )}

        {rules.length > 0 && (
          <View style={styles.rulesBox}>
            <Text style={styles.rulesTitle}>HOW PHOTOS COUNT</Text>
            {rules.map((r) => (
              <View key={r} style={styles.ruleRow}>
                <Ionicons name="checkmark" size={14} color={COLORS.textTertiary} />
                <Text style={styles.ruleText}>{r}</Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xxxl * 2 },
  spinner: { marginTop: SPACE.xxl },

  card: {
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg, padding: SPACE.md,
    borderWidth: 1, borderColor: COLORS.border, marginBottom: SPACE.md,
  },
  rowTop: { flexDirection: 'row', gap: SPACE.md },
  thumb: { width: 64, height: 64, borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt },
  thumbEmpty: { alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  meta: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: 2 },
  pill: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: SPACE.xs,
    paddingHorizontal: SPACE.sm, paddingVertical: 3, borderRadius: RADIUS.full,
    marginTop: SPACE.sm, maxWidth: '100%',
  },
  pillText: { fontSize: FONT.xs, fontWeight: '700', flexShrink: 1 },

  noteBox: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
    padding: SPACE.sm, marginTop: SPACE.md,
  },
  noteLabel: { fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary },
  noteText: { fontSize: FONT.sm, color: COLORS.textSecondary, marginTop: 2, lineHeight: 18 },

  tallyRow: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.md },
  tally: { flex: 1, borderRadius: RADIUS.md, paddingVertical: SPACE.sm, alignItems: 'center' },
  tallyCount: { fontSize: FONT.xl, fontWeight: '800' },
  tallyLabel: { fontSize: FONT.xs, color: COLORS.textSecondary, fontWeight: '600' },

  empty: { alignItems: 'center', padding: SPACE.xl, gap: SPACE.sm },
  emptyTitle: { fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  emptyText: { fontSize: FONT.sm, color: COLORS.textTertiary, textAlign: 'center', lineHeight: 18 },

  rulesBox: {
    backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
    padding: SPACE.md, marginTop: SPACE.sm,
  },
  rulesTitle: {
    fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary,
    letterSpacing: 0.8, marginBottom: SPACE.sm,
  },
  ruleRow: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.xs },
  ruleText: { flex: 1, fontSize: FONT.sm, color: COLORS.textSecondary, lineHeight: 18 },

  errorCard: {
    flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.dangerDim,
    borderRadius: RADIUS.md, padding: SPACE.md, marginBottom: SPACE.md,
  },
  errorText: { fontSize: FONT.sm, color: COLORS.danger, fontWeight: '600' },
  errorHint: { fontSize: FONT.xs, color: COLORS.textSecondary, marginTop: SPACE.xs, lineHeight: 16 },
  retryBtn: { marginTop: SPACE.sm, alignSelf: 'flex-start' },
  retryText: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.primary },

  primaryBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.primary, paddingVertical: SPACE.md, paddingHorizontal: SPACE.xl,
    borderRadius: RADIUS.full, marginTop: SPACE.md,
  },
  primaryBtnText: { color: COLORS.textInverse, fontWeight: '700', fontSize: FONT.md },
});

export default DiseaseSubmissionsScreen;
