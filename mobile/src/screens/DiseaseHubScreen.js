/**
 * DiseaseHubScreen — the landing screen for Component 1.
 *
 * The Detect tab used to open the analysis screen directly. It now opens here,
 * because the component does three separate jobs and a tab that silently does
 * one of them hides the other two.
 *
 *   1  Check a plant      -> DiseaseDetection
 *   2  History            -> DiseaseHistory
 *   3  Contribute         -> DiseaseContribute
 *
 * Card 3 collects photographs of conditions the classifier does not know. It
 * does not change the model: contributions are stored, and a class needs 30
 * human-confirmed images before it can be trained at all.
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

const DiseaseHubScreen = ({ navigation }) => {
  const [summary, setSummary] = useState({ total: 0, diseased: 0, lastAt: null });

  // useFocusEffect, not useEffect: the counts must refresh when the user comes
  // BACK from analysing a plant, not only when the screen first mounts.
  useFocusEffect(
    useCallback(() => {
      let active = true;
      historySummary().then((s) => {
        if (active) setSummary(s);
      });
      return () => {
        active = false;
      };
    }, [])
  );

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
          body="Identifies Black Leaf Spot, Phyllosticta Leaf Spot or a healthy plant, grades the severity, and gives a treatment recommendation."
          onPress={() => navigation.navigate('DiseaseDetection')}
        />

        <Card
          icon="time"
          tint={COLORS.info}
          dim={COLORS.infoDim}
          title="History"
          subtitle={historySubtitle}
          body="Every plant you have checked on this device, with its diagnosis, severity and treatment."
          onPress={() => navigation.navigate('DiseaseHistory')}
        />

        <Card
          icon="add-circle"
          tint={COLORS.fertilizer}
          dim={COLORS.fertilizerDim}
          title="Contribute an image"
          subtitle="Help extend the system"
          body="Submit a photograph of a condition the system cannot identify — including stems and flowers — so it can be added once enough confirmed examples exist."
          onPress={() => navigation.navigate('DiseaseContribute')}
        />

        <View style={styles.noteBox}>
          <Ionicons name="information-circle-outline" size={16} color={COLORS.textTertiary} />
          <Text style={styles.noteText}>
            The system currently recognises two leaf diseases and healthy plants.
            Anything else is reported as an unidentified condition, with a
            recommendation to consult an expert.
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
