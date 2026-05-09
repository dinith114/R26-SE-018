import React, { useRef, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';

const SettingsScreen = ({ navigation }) => {
  const fadeAnim = useRef(new Animated.Value(0)).current;
  useEffect(() => { Animated.timing(fadeAnim, { toValue: 1, duration: 400, useNativeDriver: true }).start(); }, []);

  const sections = [
    {
      title: 'HARDWARE',
      items: [
        { icon: 'hardware-chip', label: 'ESP32 Connection', value: 'Connected', color: COLORS.success },
        { icon: 'pulse', label: 'Sensor Array', value: 'Active', color: COLORS.success },
        { icon: 'timer-outline', label: 'Data Interval', value: '10s' },
      ],
    },
    {
      title: 'CLOUD',
      items: [
        { icon: 'cloud-outline', label: 'Firebase RTDB', value: 'Online', color: COLORS.success },
        { icon: 'sparkles-outline', label: 'ML Server', value: 'Running', color: COLORS.success },
        { icon: 'bar-chart-outline', label: 'Stored Readings', value: '1,247' },
      ],
    },
    {
      title: 'NOTIFICATIONS',
      items: [
        { icon: 'water-outline', label: 'Watering Alerts', value: 'Enabled', color: COLORS.primary },
        { icon: 'flask-outline', label: 'Fertilizer Alerts', value: 'Enabled', color: COLORS.primary },
        { icon: 'alert-circle-outline', label: 'Disease Warnings', value: 'Enabled', color: COLORS.primary },
      ],
    },
    {
      title: 'SYSTEM',
      items: [
        { icon: 'information-circle-outline', label: 'Version', value: 'v1.0.0' },
        { icon: 'school-outline', label: 'Project', value: 'R26-SE-018' },
        { icon: 'ribbon-outline', label: 'Module', value: 'SE4010 · SLIIT' },
      ],
    },
  ];

  return (
    <View style={styles.container}>
      <ScreenHeader title="Settings" subtitle="Configuration" navigation={navigation} showBack />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        <Animated.View style={{ opacity: fadeAnim }}>
          {sections.map((section, si) => (
            <View key={si} style={styles.section}>
              <Text style={styles.sectionLabel}>{section.title}</Text>
              <View style={[styles.card, SHADOW.sm]}>
                {section.items.map((item, ii) => (
                  <TouchableOpacity key={ii} style={[styles.row, ii < section.items.length - 1 && styles.rowBorder]} activeOpacity={0.6}>
                    <View style={styles.rowLeft}>
                      <View style={[styles.rowIcon, { backgroundColor: `${(item.color || COLORS.textTertiary)}10` }]}>
                        <Ionicons name={item.icon} size={17} color={item.color || COLORS.textSecondary} />
                      </View>
                      <Text style={styles.rowLabel}>{item.label}</Text>
                    </View>
                    <View style={styles.rowRight}>
                      {item.color && <View style={[styles.statusDot, { backgroundColor: item.color }]} />}
                      <Text style={[styles.rowValue, item.color && { color: item.color }]}>{item.value}</Text>
                      <Ionicons name="chevron-forward" size={16} color={COLORS.textTertiary} />
                    </View>
                  </TouchableOpacity>
                ))}
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
  section: { marginBottom: SPACE.xl },
  sectionLabel: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', letterSpacing: 1.5, marginBottom: SPACE.sm, marginLeft: SPACE.xs },
  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, overflow: 'hidden' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: SPACE.lg },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: COLORS.borderLight },
  rowLeft: { flexDirection: 'row', alignItems: 'center' },
  rowIcon: { width: 32, height: 32, borderRadius: RADIUS.sm - 2, alignItems: 'center', justifyContent: 'center', marginRight: SPACE.md },
  rowLabel: { color: COLORS.text, fontSize: FONT.md },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  statusDot: { width: 5, height: 5, borderRadius: 3 },
  rowValue: { color: COLORS.textTertiary, fontSize: FONT.sm },
});

export default SettingsScreen;
