import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import useLiveData from '../hooks/useLiveData';
import useNotifications from '../hooks/useNotifications';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { getAlarms } from '../services/careV2';

const LEVEL = {
  urgent:  { c: COLORS.danger,  bg: COLORS.dangerDim,  tag: 'URGENT' },
  action:  { c: COLORS.warning, bg: COLORS.warningDim, tag: 'ACTION' },
  warning: { c: COLORS.warning, bg: COLORS.warningDim, tag: 'CHECK'  },
  info:    { c: COLORS.info,    bg: COLORS.infoDim,    tag: 'INFO'   },
};

/* Notifications can be cleared, one or all (15 Oct 2026: the farmer had no way
   to get rid of one). The server works the list out from the farm every time,
   so clearing hides an item on this phone while its problem lasts; see
   services/notifyRules.js for exactly when it comes back. */
const NotificationsScreen = ({ navigation }) => {
  const n = useNotifications(20000);
  const [showCleared, setShowCleared] = useState(false);

  const items = n.shown;
  const problems = items.filter((a) => a.level !== 'info').length;

  /* Alarms are a different list from these notifications, and the Alarm screen
     used to be reachable only by tapping a push. Dismiss the push and the
     alarm kept repeating with no way to it from inside the app. Alarms are
     not clearable here: they repeat until somebody deals with the cause. */
  const alarmsLive = useLiveData(getAlarms);
  const waiting = (alarmsLive.data?.alarms || alarmsLive.data?.items || [])
    .filter(a => a.kind === 'action' && !a.acknowledged).length;

  return (
    <View style={styles.container}>
      <ScreenHeader title="Notifications" subtitle="Live from your farm"
        navigation={navigation} showBack showNotification={false} />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={n.refreshing} tintColor={COLORS.primary}
          onRefresh={n.refresh} />}>

        {n.loading ? (
          <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
        ) : n.error && !n.data ? (
          <View style={styles.err}>
            <Ionicons name="cloud-offline-outline" size={20} color={COLORS.danger} />
            <Text style={styles.errTxt}>{n.error}{'\n'}Is the backend running?</Text>
          </View>
        ) : (
          <>
            <View style={styles.topRow}>
              <View style={[styles.summary, {
                backgroundColor: problems ? COLORS.warningDim : COLORS.successDim }]}>
                <Ionicons name={problems ? 'alert-circle' : 'checkmark-circle'} size={18}
                  color={problems ? COLORS.warning : COLORS.success} />
                <Text style={[styles.summaryTxt, { color: problems ? COLORS.warning : COLORS.success }]}>
                  {problems
                    ? `${problems} ${problems === 1 ? 'needs' : 'need'} attention`
                    : 'Nothing needs you'}
                </Text>
              </View>
              {items.length > 0 && (
                <TouchableOpacity style={styles.clearAll} onPress={n.clearAll}
                  activeOpacity={0.7} accessibilityRole="button"
                  accessibilityLabel={`Clear all ${items.length} notifications`}>
                  <Ionicons name="checkmark-done" size={16} color={COLORS.primary} />
                  <Text style={styles.clearAllTxt}>Clear all</Text>
                </TouchableOpacity>
              )}
            </View>

            {waiting > 0 && (
              <TouchableOpacity activeOpacity={0.75}
                style={[styles.card, SHADOW.sm, { borderLeftColor: COLORS.danger }]}
                onPress={() => navigation.navigate('Alarm')}>
                <View style={[styles.icon, { backgroundColor: COLORS.dangerDim }]}>
                  <Ionicons name="alarm" size={17} color={COLORS.danger} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>
                    {waiting === 1 ? '1 alarm is waiting' : `${waiting} alarms are waiting`}
                  </Text>
                  <Text style={styles.msg}>They repeat until someone deals with them. Tap to see what needs doing.</Text>
                </View>
                <Ionicons name="chevron-forward" size={15} color={COLORS.textTertiary} />
              </TouchableOpacity>
            )}

            {items.length === 0 && (
              <View style={styles.empty}>
                <Ionicons name="notifications-off-outline" size={34} color={COLORS.textTertiary} />
                <Text style={styles.emptyTxt}>
                  {n.hidden.length
                    ? 'All clear. Anything new will show here.'
                    : 'Nothing to tell you right now.'}
                </Text>
              </View>
            )}

            {items.map(a => (
              <AlertCard key={a.id} a={a} navigation={navigation}
                onClear={() => n.clear(a)} />
            ))}

            {n.hidden.length > 0 && (
              <View style={styles.clearedBox}>
                <TouchableOpacity style={styles.clearedHead} activeOpacity={0.7}
                  onPress={() => setShowCleared((v) => !v)}
                  accessibilityRole="button"
                  accessibilityState={{ expanded: showCleared }}>
                  <Text style={styles.clearedHeadTxt}>
                    {showCleared ? 'Hide cleared' : `Show cleared (${n.hidden.length})`}
                  </Text>
                  <Ionicons name={showCleared ? 'chevron-up' : 'chevron-down'} size={16}
                    color={COLORS.textSecondary} />
                </TouchableOpacity>
                {showCleared && (
                  <>
                    {n.hidden.map(a => (
                      <AlertCard key={`c-${a.id}`} a={a} navigation={navigation} cleared
                        onRestore={() => n.restore(a)} />
                    ))}
                    <TouchableOpacity style={styles.restoreAll} onPress={n.restoreAll}
                      accessibilityRole="button">
                      <Text style={styles.restoreAllTxt}>Bring them all back</Text>
                    </TouchableOpacity>
                  </>
                )}
              </View>
            )}

            {n.data?.generatedAt && <Text style={styles.stamp}>Updated {n.data.generatedAt}</Text>}
          </>
        )}
        <View style={{ height: 60 }} />
      </ScrollView>
    </View>
  );
};

/* One notification. The card opens its section; the button on the right clears
   it (or, in the cleared list, brings it back) and is its own tap target, so a
   farmer clearing one never lands on the section by accident. */
function AlertCard({ a, navigation, onClear, onRestore, cleared }) {
  const lv = LEVEL[a.level] || LEVEL.info;
  const tappable = !!(a.houseId && a.sectionId);
  const Body = tappable ? TouchableOpacity : View;
  return (
    <View style={[styles.card, !cleared && SHADOW.sm, { borderLeftColor: lv.c },
                  cleared && styles.cardCleared]}>
      <Body style={styles.cardBody}
        {...(tappable ? {
          activeOpacity: 0.75,
          onPress: () => navigation.navigate('SectionDetail',
            { houseId: a.houseId, sectionId: a.sectionId }),
        } : {})}>
        <View style={[styles.icon, { backgroundColor: lv.bg }]}>
          <Ionicons name={a.icon || 'notifications-outline'} size={17} color={lv.c} />
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
      </Body>
      {cleared ? (
        <TouchableOpacity style={styles.sideBtn} onPress={onRestore}
          hitSlop={{ top: 10, bottom: 10, left: 6, right: 10 }}
          accessibilityRole="button" accessibilityLabel={`Bring back: ${a.title}`}>
          <Ionicons name="arrow-undo-outline" size={18} color={COLORS.primary} />
        </TouchableOpacity>
      ) : (
        <TouchableOpacity style={styles.sideBtn} onPress={onClear}
          hitSlop={{ top: 10, bottom: 10, left: 6, right: 10 }}
          accessibilityRole="button" accessibilityLabel={`Clear: ${a.title}`}>
          <Ionicons name="close" size={19} color={COLORS.textTertiary} />
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll:    { padding: SPACE.xl },
  center:    { paddingTop: 60, alignItems: 'center' },

  err:    { flexDirection: 'row', gap: SPACE.md, backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm, padding: SPACE.lg },
  errTxt: { color: COLORS.danger, fontSize: FONT.sm, flex: 1, lineHeight: 18 },

  topRow:     { flexDirection: 'row', alignItems: 'stretch', gap: SPACE.sm, marginBottom: SPACE.lg },
  // No shadow: on Android a shadow under a see-through tint shows through it
  // as a grey box (the "needs a master controller" card, 15 Oct).
  summary:    { flex: 1, flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
                paddingVertical: SPACE.md, paddingHorizontal: SPACE.md, borderRadius: RADIUS.md },
  summaryTxt: { fontSize: FONT.md, fontWeight: '700', flex: 1 },
  clearAll:   { width: 112, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
                gap: 6, borderRadius: RADIUS.md, backgroundColor: COLORS.bgCard,
                borderWidth: 1, borderColor: COLORS.border },
  clearAllTxt:{ color: COLORS.primary, fontSize: FONT.md, fontWeight: '800' },

  empty:    { alignItems: 'center', gap: SPACE.md, paddingVertical: 40 },
  emptyTxt: { color: COLORS.textTertiary, fontSize: FONT.sm, textAlign: 'center', lineHeight: 19 },

  card:  { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.bgCard,
           borderRadius: RADIUS.sm, marginBottom: SPACE.sm, borderLeftWidth: 3 },
  cardCleared: { opacity: 0.7, borderWidth: 1, borderColor: COLORS.border },
  cardBody: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              paddingVertical: SPACE.md, paddingLeft: SPACE.md },
  sideBtn: { width: 44, alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center' },
  icon:  { width: 34, height: 34, borderRadius: RADIUS.sm, alignItems: 'center', justifyContent: 'center' },
  head:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginBottom: 2 },
  title: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', flex: 1 },
  tag:   { paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.full },
  tagTxt:{ fontSize: 8, fontWeight: '800', letterSpacing: 0.4 },
  msg:   { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16 },

  clearedBox:  { marginTop: SPACE.md },
  // The label takes the row's width rather than its own: sized to itself it
  // clips on a phone with Bold text on (see LineChart, 15 Oct).
  clearedHead: { flexDirection: 'row', alignItems: 'center', gap: 6,
                 paddingVertical: SPACE.md, paddingLeft: 22, marginBottom: SPACE.sm },
  clearedHeadTxt: { flex: 1, textAlign: 'center', color: COLORS.textSecondary,
                    fontSize: FONT.sm, fontWeight: '700' },
  restoreAll:  { alignItems: 'center', paddingVertical: SPACE.md },
  restoreAllTxt: { alignSelf: 'stretch', textAlign: 'center', color: COLORS.primary,
                   fontSize: FONT.sm, fontWeight: '700' },

  stamp: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center', marginTop: SPACE.lg },
});

export default NotificationsScreen;
