/**
 * ReviewerHomeScreen — the first screen an orchid expert from the research
 * institute sees, instead of the farm tabs.
 *
 * A reviewer signs in with the institute's own account, which has no
 * greenhouses, so the farm screens would only offer "Set up your farm". App.js
 * asks the server once whether this account is on the reviewer list and opens
 * this screen for reviewers. That answer only decides what is SHOWN: the server
 * checks the list again on every review request.
 *
 * Everything here comes from endpoints that already exist:
 *   - how many photos are waiting, and the way in to review them
 *   - each disease being collected: approved photos out of 30 and growers out
 *     of 3, with "Ready for training" once both are met, so the expert can tell
 *     the system's maintainers
 *   - the latest decisions, from the log that is never edited
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { useAuth } from '../config/auth';
import { getPendingCounts, getReviewLog, ApiError } from '../services/diseaseApi';

const DECISION = {
  approve: { label: 'Approved', icon: 'checkmark-circle', color: COLORS.success },
  correct: { label: 'Corrected', icon: 'create-outline', color: COLORS.success },
  reject: { label: 'Not accepted', icon: 'close-circle', color: COLORS.danger },
};

// The server's reasons, in the words the review screen shows.
const REASON = {
  wrong_disease: 'Not this disease',
  unclear: 'Too unclear to judge',
  not_orchid: 'Not an orchid',
  duplicate: 'Same plant already sent',
  other: 'Other reason',
};

function day(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d)
    ? d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
    : '';
}

const ReviewerHomeScreen = ({ navigation }) => {
  const { email, signOut } = useAuth();
  const [counts, setCounts] = useState(null);
  const [recent, setRecent] = useState(undefined);   // undefined loading, null failed
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setCounts(await getPendingCounts());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Could not load the review summary.'));
    }
    // The decision list is an extra: if it cannot load, the rest still works.
    try {
      const body = await getReviewLog(5);
      setRecent(body.decisions || []);
    } catch (_) {
      setRecent(null);
    }
  }, []);

  // On focus, so the counts are fresh when the expert comes back from reviewing.
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const confirmSignOut = () => {
    Alert.alert('Sign out?', 'You will need your password to sign in again.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: () => { signOut(); } },
    ]);
  };

  const all = counts?.diseases || [];
  const waiting = all.reduce((n, d) => n + (d.waiting || 0), 0);
  const minPhotos = counts?.minimum_required || 30;
  const minGrowers = counts?.minimum_growers || 3;
  // Only diseases with something in them: an approved photo or one waiting.
  // Ready ones first, then the furthest along.
  const diseases = all
    .filter((d) => (d.approved_unique || 0) > 0 || (d.waiting || 0) > 0)
    .sort((a, b) => (Number(!!b.ready_for_training) - Number(!!a.ready_for_training))
      || ((b.approved_unique || 0) - (a.approved_unique || 0)));

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="Expert review"
        subtitle={email || 'Orchid expert'}
        navigation={navigation}
        showNotification={false}
      />

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
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

        {!counts && !error && (
          <ActivityIndicator style={styles.spinner} color={COLORS.primary} />
        )}

        {counts && (
          <>
            <View style={[styles.card, styles.waitCard]}>
              <Text style={styles.waitCount}>{waiting}</Text>
              <Text style={styles.waitLabel}>
                {waiting === 1 ? 'photo waiting for review' : 'photos waiting for review'}
              </Text>
              <TouchableOpacity
                style={styles.primaryBtn}
                onPress={() => navigation.navigate('DiseaseReview')}
                accessibilityRole="button"
              >
                <Ionicons name="shield-checkmark" size={18} color={COLORS.textInverse} />
                <Text style={styles.primaryBtnText}>Review photos</Text>
              </TouchableOpacity>
            </View>

            <Text style={styles.sectionLabel}>DISEASES BEING COLLECTED</Text>
            {diseases.length === 0 ? (
              <View style={styles.card}>
                <Text style={styles.emptyText}>No photos approved or waiting yet.</Text>
              </View>
            ) : diseases.map((d) => {
              const approved = d.approved_unique || 0;
              const pct = Math.min(100, Math.round((approved / minPhotos) * 100));
              return (
                <View key={d.disease} style={styles.card}>
                  <View style={styles.rowTop}>
                    <Text style={styles.name}>{d.display_name}</Text>
                    <Text style={styles.count}>{approved} / {minPhotos} approved</Text>
                  </View>
                  <View style={styles.track}>
                    <View style={[styles.fill, { width: `${Math.max(2, pct)}%` }]} />
                  </View>
                  <Text style={styles.meta}>
                    {d.growers || 0} of {minGrowers} growers
                    {d.waiting ? ` · ${d.waiting} waiting` : ''}
                  </Text>
                  {d.ready_for_training ? (
                    <View style={styles.readyRow}>
                      <View style={styles.readyPill}>
                        <Ionicons name="checkmark-circle" size={14} color={COLORS.success} />
                        <Text style={styles.readyText}>Ready for training</Text>
                      </View>
                      <Text style={styles.readyNote}>
                        Tell the system's maintainers they can retrain the model.
                      </Text>
                    </View>
                  ) : null}
                </View>
              );
            })}

            <Text style={styles.sectionLabel}>RECENT DECISIONS</Text>
            <View style={styles.card}>
              {recent === undefined ? (
                <ActivityIndicator color={COLORS.primary} />
              ) : recent === null ? (
                <Text style={styles.emptyText}>Could not load the decisions.</Text>
              ) : recent.length === 0 ? (
                <Text style={styles.emptyText}>No decisions yet.</Text>
              ) : recent.map((r, i) => {
                const look = DECISION[r.decision] || DECISION.approve;
                return (
                  <View
                    key={`${r.image_id}-${r.at}-${i}`}
                    style={[styles.decisionRow, i > 0 && styles.decisionDivider]}
                  >
                    <Ionicons name={look.icon} size={16} color={look.color} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.decisionText}>{look.label} · {r.image_id}</Text>
                      <Text style={styles.meta}>
                        {day(r.at)}{REASON[r.reason] ? ` · ${REASON[r.reason]}` : ''}
                      </Text>
                    </View>
                  </View>
                );
              })}
            </View>
          </>
        )}

        <TouchableOpacity style={styles.signOutBtn} onPress={confirmSignOut} accessibilityRole="button">
          <Ionicons name="log-out-outline" size={18} color={COLORS.danger} />
          <Text style={styles.signOutText}>Sign out</Text>
        </TouchableOpacity>
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
  waitCard: { alignItems: 'center', paddingVertical: SPACE.xl },
  waitCount: { fontSize: FONT.hero, fontWeight: '800', color: COLORS.primary },
  waitLabel: { fontSize: FONT.md, color: COLORS.textSecondary, marginTop: SPACE.xs },

  sectionLabel: {
    fontSize: FONT.xs, fontWeight: '700', color: COLORS.textTertiary,
    letterSpacing: 0.8, marginBottom: SPACE.sm, marginTop: SPACE.md,
  },
  rowTop: { flexDirection: 'row', alignItems: 'baseline', gap: SPACE.sm },
  name: { flex: 1, fontSize: FONT.md, fontWeight: '700', color: COLORS.text },
  count: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.primary },
  track: {
    height: 6, backgroundColor: COLORS.bgCardAlt, borderRadius: 3,
    overflow: 'hidden', marginTop: SPACE.sm,
  },
  fill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 3 },
  meta: { fontSize: FONT.xs, color: COLORS.textTertiary, marginTop: SPACE.xs },

  readyRow: { marginTop: SPACE.sm, gap: SPACE.xs },
  readyPill: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: SPACE.xs,
    backgroundColor: COLORS.successDim, paddingHorizontal: SPACE.sm, paddingVertical: 3,
    borderRadius: RADIUS.full,
  },
  readyText: { fontSize: FONT.xs, fontWeight: '700', color: COLORS.success },
  readyNote: { fontSize: FONT.xs, color: COLORS.textSecondary },

  decisionRow: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm, paddingVertical: SPACE.sm },
  decisionDivider: { borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  decisionText: { fontSize: FONT.sm, fontWeight: '600', color: COLORS.text },
  emptyText: { fontSize: FONT.sm, color: COLORS.textTertiary, textAlign: 'center', paddingVertical: SPACE.sm },

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
    borderRadius: RADIUS.full, marginTop: SPACE.lg, alignSelf: 'stretch',
  },
  primaryBtnText: { color: COLORS.textInverse, fontWeight: '700', fontSize: FONT.md },

  signOutBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACE.sm,
    paddingVertical: SPACE.md, marginTop: SPACE.lg,
  },
  signOutText: { fontSize: FONT.md, fontWeight: '700', color: COLORS.danger },
});

export default ReviewerHomeScreen;
