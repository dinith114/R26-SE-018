/**
 * DiseaseHubScreen — the landing screen for Component 1.
 *
 * The Detect tab used to open the analysis screen directly. It now opens here,
 * because the component does several separate jobs and a tab that silently does
 * one of them hides the others.
 *
 *   1  Check a plant      -> DiseaseDetection
 *   2  History            -> DiseaseHistory
 *   3  Contribute         -> DiseaseContribute
 *   4  My photos          -> DiseaseSubmissions
 *   5  Expert review      -> DiseaseReview      (experts only)
 *
 * Card 3 collects photographs of conditions the classifier does not know. It
 * does not change the model: every photo waits for an orchid expert, and a
 * class needs 30 approved photos from at least 3 growers before it can be
 * trained at all. Card 5 appears only when the server says this account is on
 * its expert list, and the server checks that list again on every review.
 */

import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from '@react-navigation/native';

import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { historySummary } from '../services/diseaseHistory';
import {
  getMyContributions, getExpertStatus, getPendingCounts,
} from '../services/diseaseApi';

const DiseaseHubScreen = ({ navigation }) => {
  const [summary, setSummary] = useState({ total: 0, diseased: 0, lastAt: null });
  const [mine, setMine] = useState(null);
  const [expert, setExpert] = useState(false);
  const [waitingReview, setWaitingReview] = useState(0);

  // useFocusEffect, not useEffect: the counts must refresh when the user comes
  // BACK from analysing a plant, not only when the screen first mounts. The
  // network counts are optional extras: offline, the cards still work.
  useFocusEffect(
    useCallback(() => {
      let active = true;
      historySummary().then((s) => {
        if (active) setSummary(s);
      });
      getMyContributions()
        .then((b) => active && setMine(b.contributions || []))
        .catch(() => active && setMine(null));
      getExpertStatus().then((isExpert) => {
        if (!active) return;
        setExpert(isExpert);
        if (isExpert) {
          getPendingCounts()
            .then((c) => active && setWaitingReview(
              (c.diseases || []).reduce((n, d) => n + (d.waiting || 0), 0)))
            .catch(() => {});
        }
      });
      return () => {
        active = false;
      };
    }, [])
  );

  const mineSubtitle = !mine
    ? 'Your contributions and their review'
    : mine.length === 0
      ? 'No photos sent yet'
      : `${mine.length} sent · ${mine.filter((m) => m.status === 'pending').length} waiting` +
        ` · ${mine.filter((m) => m.counts).length} approved`;

  const historySubtitle = summary.total
    ? `${summary.total} check${summary.total === 1 ? '' : 's'}` +
      (summary.diseased ? ` · ${summary.diseased} with disease` : '')
    : 'No checks yet';

  const Card = ({ icon, tint, dim, title, subtitle, body, onPress, disabled, badge }) => (
    <TouchableOpacity
      style={[styles.card, SHADOW.sm, disabled && styles.cardDisabled]}
      onPress={onPress}
      activeOpacity={disabled ? 1 : 0.8}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      accessibilityLabel={`${title}. ${subtitle}`}
    >
      <View style={styles.cardTop}>
        <View style={[styles.iconWrap, { backgroundColor: disabled ? COLORS.bgCardAlt : dim }]}>
          <Ionicons name={icon} size={24} color={disabled ? COLORS.textTertiary : tint} />
        </View>
        <View style={styles.cardHeadText}>
          <View style={styles.titleRow}>
            <Text style={[styles.cardTitle, disabled && styles.mutedText]}>{title}</Text>
            {badge ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{badge}</Text>
              </View>
            ) : null}
          </View>
          <Text style={[styles.cardSubtitle, disabled && styles.mutedText]}>{subtitle}</Text>
        </View>
        {!disabled && (
          <Ionicons name="chevron-forward" size={20} color={COLORS.textTertiary} />
        )}
      </View>
      <Text style={[styles.cardBody, disabled && styles.mutedText]}>{body}</Text>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="Disease Detection"
        subtitle="Identify · Grade · Treat"
        navigation={navigation}
        showSettings
      />

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.intro}>
          Photograph an orchid leaf to identify the disease, how far it has
          progressed, and what to do about it.
        </Text>

        <Card
          icon="camera"
          tint={COLORS.primary}
          dim={COLORS.primaryDim}
          title="Check a plant"
          subtitle="Upload a photo for diagnosis"
          body="Find the disease, how bad it is, and what to do."
          onPress={() => navigation.navigate('DiseaseDetection')}
        />

        <Card
          icon="time"
          tint={COLORS.info}
          dim={COLORS.infoDim}
          title="History"
          subtitle={historySubtitle}
          body="Your past checks on this phone."
          onPress={() => navigation.navigate('DiseaseHistory')}
        />

        <Card
          icon="add-circle"
          tint={COLORS.fertilizer}
          dim={COLORS.fertilizerDim}
          title="Contribute an image"
          subtitle="Help extend the system"
          body="Send a photo of a problem the app can't name yet."
          onPress={() => navigation.navigate('DiseaseContribute')}
        />

        <Card
          icon="images"
          tint={COLORS.success}
          dim={COLORS.successDim}
          title="My photos"
          subtitle={mineSubtitle}
          body="See what the expert decided about each photo."
          onPress={() => navigation.navigate('DiseaseSubmissions')}
        />

        {expert && (
          <Card
            icon="shield-checkmark"
            tint={COLORS.warning}
            dim={COLORS.warningDim}
            title="Expert review"
            subtitle={waitingReview ? `${waitingReview} waiting for review` : 'Nothing waiting'}
            body="Approve, correct or reject photos sent by growers."
            badge={waitingReview ? String(waitingReview) : null}
            onPress={() => navigation.navigate('DiseaseReview')}
          />
        )}

        <View style={styles.noteBox}>
          <Ionicons name="information-circle-outline" size={16} color={COLORS.textTertiary} />
          <Text style={styles.noteText}>
            {'The app knows two leaf diseases and healthy leaves. Anything else ' +
              'is shown as "Not sure", with advice to ask an expert.'}
          </Text>
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xxxl * 2 },

  intro: {
    fontSize: FONT.md,
    color: COLORS.textSecondary,
    lineHeight: 21,
    marginBottom: SPACE.lg,
  },

  card: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.lg,
    padding: SPACE.lg,
    marginBottom: SPACE.md,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  cardDisabled: { backgroundColor: COLORS.bgCardAlt, borderColor: COLORS.borderLight },

  cardTop: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.sm },
  iconWrap: {
    width: 46, height: 46, borderRadius: RADIUS.md,
    alignItems: 'center', justifyContent: 'center', marginRight: SPACE.md,
  },
  cardHeadText: { flex: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  cardTitle: { fontSize: FONT.lg, fontWeight: '700', color: COLORS.text },
  cardSubtitle: { fontSize: FONT.sm, color: COLORS.textSecondary, marginTop: 2 },
  cardBody: {
    fontSize: FONT.sm,
    color: COLORS.textTertiary,
    lineHeight: 18,
  },
  mutedText: { color: COLORS.textTertiary },

  badge: {
    backgroundColor: COLORS.fertilizerDim,
    paddingHorizontal: SPACE.sm,
    paddingVertical: 2,
    borderRadius: RADIUS.full,
  },
  badgeText: {
    fontSize: FONT.xs,
    fontWeight: '700',
    color: COLORS.fertilizer,
    letterSpacing: 0.5,
  },

  noteBox: {
    flexDirection: 'row',
    gap: SPACE.sm,
    backgroundColor: COLORS.bgCardAlt,
    borderRadius: RADIUS.md,
    padding: SPACE.md,
    marginTop: SPACE.sm,
  },
  noteText: {
    flex: 1,
    fontSize: FONT.sm,
    color: COLORS.textTertiary,
    lineHeight: 18,
  },
});

export default DiseaseHubScreen;
