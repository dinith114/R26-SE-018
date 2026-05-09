import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ref, onValue } from 'firebase/database';
import { database } from '../config/firebase';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const NotificationsScreen = ({ navigation }) => {
  const [prediction, setPrediction] = useState(null);
  const fadeAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start();
    const predRef = ref(database, 'prediction');
    const unsub = onValue(predRef, (snapshot) => {
      const val = snapshot.val();
      if (val) setPrediction(val);
    });
    return () => unsub();
  }, []);

  const needsWater = prediction?.waterNeeded === 'Yes';
  const needsFert = (prediction?.fertilizerNeeded || 'No') === 'Yes';
  const now = new Date();

  // Build notification list
  const notifications = [];

  if (needsWater) {
    notifications.push({
      id: 'water_alert',
      type: 'urgent',
      icon: 'water',
      color: COLORS.primary,
      title: 'Watering Required',
      message: `Soil moisture is low. The ML model recommends watering now with ${prediction?.confidence?.toFixed(0) || '--'}% confidence.`,
      time: prediction?.timestamp || 'Just now',
      action: 'Go to Care',
      route: 'Care',
    });
  }

  if (needsFert) {
    notifications.push({
      id: 'fert_alert',
      type: 'urgent',
      icon: 'flask',
      color: COLORS.fertilizer,
      title: 'Fertilizing Required',
      message: 'Nutrient levels are depleted based on soil moisture, temperature, and time since last application.',
      time: prediction?.timestamp || 'Just now',
      action: 'Go to Care',
      route: 'Care',
    });
  }

  // Always show these informational ones
  notifications.push(
    {
      id: 'schedule_water',
      type: 'info',
      icon: 'time-outline',
      color: COLORS.primary,
      title: 'Next Irrigation: 06:00',
      message: 'Morning irrigation cycle scheduled. Auto-mode will trigger if ML confirms.',
      time: 'Scheduled',
    },
    {
      id: 'schedule_fert',
      type: 'info',
      icon: 'time-outline',
      color: COLORS.fertilizer,
      title: 'Next Fertilizer: Sunday 07:00',
      message: 'Weekly NPK 20-20-20 application scheduled.',
      time: 'Scheduled',
    },
    {
      id: 'sensor_ok',
      type: 'success',
      icon: 'hardware-chip-outline',
      color: COLORS.success,
      title: 'All Sensors Active',
      message: 'DHT22, BH1750, and Soil Moisture sensors are reporting normally.',
      time: '5 min ago',
    },
    {
      id: 'ml_update',
      type: 'info',
      icon: 'analytics-outline',
      color: COLORS.info,
      title: 'ML Prediction Updated',
      message: `Latest prediction: Water ${prediction?.waterNeeded || '--'}, Fertilizer ${prediction?.fertilizerNeeded || '--'} (${prediction?.confidence?.toFixed(0) || '--'}% confidence)`,
      time: prediction?.timestamp || '--',
    },
  );

  if (!needsWater && !needsFert) {
    notifications.unshift({
      id: 'all_good',
      type: 'success',
      icon: 'checkmark-circle',
      color: COLORS.success,
      title: 'All Optimal',
      message: 'No watering or fertilizing action required at this time. All conditions are within optimal ranges.',
      time: 'Now',
    });
  }

  const getBorderColor = (type) => {
    if (type === 'urgent') return COLORS.warning;
    if (type === 'success') return COLORS.success;
    return COLORS.border;
  };

  return (
    <View style={styles.container}>
      <ScreenHeader
        title="Notifications"
        subtitle="Alerts & Updates"
        navigation={navigation}
        showBack
        showNotification={false}
      />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          {/* Summary */}
          <View style={styles.summaryRow}>
            <View style={[styles.summaryCard, SHADOW.sm, {
              backgroundColor: (needsWater || needsFert) ? COLORS.warningDim : COLORS.successDim,
            }]}>
              <Ionicons
                name={(needsWater || needsFert) ? 'alert-circle' : 'checkmark-circle'}
                size={20}
                color={(needsWater || needsFert) ? COLORS.warning : COLORS.success}
              />
              <Text style={[styles.summaryText, {
                color: (needsWater || needsFert) ? COLORS.warning : COLORS.success,
              }]}>
                {(needsWater || needsFert)
                  ? `${[needsWater && 'Watering', needsFert && 'Fertilizing'].filter(Boolean).join(' & ')} needed`
                  : 'All systems optimal'}
              </Text>
            </View>
          </View>

          {/* Notification list */}
          {notifications.map((notif) => (
            <View
              key={notif.id}
              style={[styles.notifCard, SHADOW.sm, {
                borderLeftColor: getBorderColor(notif.type),
                borderLeftWidth: 3,
              }]}
            >
              <View style={styles.notifRow}>
                <View style={[styles.notifIcon, { backgroundColor: `${notif.color}12` }]}>
                  <Ionicons name={notif.icon} size={18} color={notif.color} />
                </View>
                <View style={styles.notifContent}>
                  <View style={styles.notifHeader}>
                    <Text style={styles.notifTitle}>{notif.title}</Text>
                    {notif.type === 'urgent' && (
                      <View style={styles.urgentBadge}>
                        <Text style={styles.urgentText}>ACTION</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.notifMessage}>{notif.message}</Text>
                  <View style={styles.notifFooter}>
                    <Text style={styles.notifTime}>{notif.time}</Text>
                    {notif.action && (
                      <TouchableOpacity
                        style={styles.notifAction}
                        onPress={() => navigation.navigate(notif.route)}
                        activeOpacity={0.6}
                      >
                        <Text style={[styles.notifActionText, { color: notif.color }]}>{notif.action}</Text>
                        <Ionicons name="arrow-forward" size={12} color={notif.color} />
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              </View>
            </View>
          ))}
        </Animated.View>
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.xl },
  summaryRow: { marginBottom: SPACE.xl },
  summaryCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACE.sm,
    padding: SPACE.lg,
    borderRadius: RADIUS.sm,
  },
  summaryText: { fontSize: FONT.md, fontWeight: '700' },
  notifCard: {
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.sm,
    padding: SPACE.lg,
    marginBottom: SPACE.sm,
  },
  notifRow: { flexDirection: 'row' },
  notifIcon: {
    width: 36,
    height: 36,
    borderRadius: RADIUS.sm,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: SPACE.md,
    marginTop: 2,
  },
  notifContent: { flex: 1 },
  notifHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: SPACE.xs,
  },
  notifTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', flex: 1 },
  urgentBadge: {
    backgroundColor: COLORS.warningDim,
    paddingHorizontal: SPACE.sm,
    paddingVertical: 2,
    borderRadius: RADIUS.full,
  },
  urgentText: { color: COLORS.warning, fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  notifMessage: {
    color: COLORS.textSecondary,
    fontSize: FONT.sm,
    lineHeight: 19,
    marginBottom: SPACE.sm,
  },
  notifFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  notifTime: { color: COLORS.textTertiary, fontSize: FONT.xs },
  notifAction: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  notifActionText: { fontSize: FONT.xs, fontWeight: '700' },
});

export default NotificationsScreen;
