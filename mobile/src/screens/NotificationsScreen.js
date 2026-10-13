import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useLiveData from '../hooks/useLiveData';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { getAlerts } from '../services/careV2';

const LEVEL = {
  urgent:  { c: COLORS.danger,  bg: COLORS.dangerDim,  tag: 'URGENT' },
  action:  { c: COLORS.warning, bg: COLORS.warningDim, tag: 'ACTION' },
  warning: { c: COLORS.warning, bg: COLORS.warningDim, tag: 'CHECK'  },
  info:    { c: COLORS.info,    bg: COLORS.infoDim,    tag: 'INFO'   },
};

const NotificationsScreen = ({ navigation }) => {
  const { data, loading, error, refreshing: refresh, refresh: pullRefresh } =
    useLiveData(getAlerts, 20000);

  const items  = data?.alerts || [];
  const urgent = data?.urgent || 0;

  return (
    <View style={styles.container}>
      <ScreenHeader title="Notifications" subtitle="Live from your farm"
        navigation={navigation} showBack showNotification={false} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refresh} tintColor={COLORS.primary}
          onRefresh={pullRefresh} />}>

        {loading ? (
          <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
        ) : error ? (
          <View style={[styles.err, SHADOW.sm]}>
            <Ionicons name="cloud-offline-outline" size={20} color={COLORS.danger} />
            <Text style={styles.errTxt}>{error}{'\n'}Is the backend running?</Text>
          </View>
        ) : (
          <>
            <View style={[styles.summary, SHADOW.sm, {
              backgroundColor: urgent ? COLORS.warningDim : COLORS.successDim }]}>
              <Ionicons name={urgent ? 'alert-circle' : 'checkmark-circle'} size={20}
                color={urgent ? COLORS.warning : COLORS.success} />
              <Text style={[styles.summaryTxt, { color: urgent ? COLORS.warning : COLORS.success }]}>
                {urgent ? `${urgent} item${urgent !== 1 ? 's' : ''} need attention`
                        : 'Everything is running normally'}
              </Text>
            </View>

            {items.length === 0 && (
              <View style={styles.empty}>
                <Ionicons name="notifications-off-outline" size={34} color={COLORS.textTertiary} />
                <Text style={styles.emptyTxt}>
                  No notifications yet.{'\n'}Run "Today's Plan" on the My Farm screen.
                </Text>
              </View>
            )}

            {items.map(a => {
              const lv = LEVEL[a.level] || LEVEL.info;
              const tappable = !!(a.houseId && a.sectionId);
              return tappable ? (
                <TouchableOpacity key={a.id} activeOpacity={0.75}
                  style={[styles.card, SHADOW.sm, { borderLeftColor: lv.c }]}
                  onPress={() => navigation.navigate('SectionDetail',
                    { houseId: a.houseId, sectionId: a.sectionId })}>
                  <AlertBody a={a} lv={lv} chevron />
                </TouchableOpacity>
              ) : (
                <View key={a.id} style={[styles.card, SHADOW.sm, { borderLeftColor: lv.c }]}>
                  <AlertBody a={a} lv={lv} />
                </View>
              );
            })}

            {data?.generatedAt && <Text style={styles.stamp}>Updated {data.generatedAt}</Text>}
          </>
        )}
        <View style={{ height: 60 }} />
      </ScrollView>
    </View>
  );
};

function AlertBody({ a, lv, chevron }) {
  return (
    <>
      <View style={[styles.icon, { backgroundColor: lv.bg }]}>
        <Ionicons name={a.icon} size={17} color={lv.c} />
      </View>
      <View style={{ flex: 1 }}>
        <View style={styles.head}>
          <Text style={styles.title}>{a.title}</Text>
          <View style={[styles.tag, { backgroundColor: lv.bg }]}>
            <Text style={[styles.tagTxt, { color: lv.c }]}>{lv.tag}</Text>
          </View>
        </View>
        <Text style={styles.msg}>{a.message}</Text>
      </View>
      {chevron && <Ionicons name="chevron-forward" size={15} color={COLORS.textTertiary} />}
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.xl },
  center:    { paddingTop: 60, alignItems: 'center' },

  err:    { flexDirection: 'row', gap: SPACE.md, backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm, padding: SPACE.lg },
  errTxt: { color: COLORS.danger, fontSize: FONT.sm, flex: 1, lineHeight: 18 },

  summary:    { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, padding: SPACE.lg, borderRadius: RADIUS.sm, marginBottom: SPACE.lg },
  summaryTxt: { fontSize: FONT.md, fontWeight: '700', flex: 1 },

  empty:    { alignItems: 'center', gap: SPACE.md, paddingVertical: 40 },
  emptyTxt: { color: COLORS.textTertiary, fontSize: FONT.sm, textAlign: 'center', lineHeight: 19 },

  card:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.sm, borderLeftWidth: 3 },
  icon:  { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  head:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: 2 },
  title: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', flex: 1 },
  tag:   { paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.full },
  tagTxt:{ fontSize: 8, fontWeight: '800', letterSpacing: 0.4 },
  msg:   { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16 },

  stamp: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center', marginTop: SPACE.lg },
});

export default NotificationsScreen;
