import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';

const ScreenHeader = ({ title, subtitle, navigation, showBack = false, showNotification = true }) => {
  return (
    <View style={styles.header}>
      <View style={styles.row}>
        {/* Left: Back button */}
        <View style={styles.left}>
          {showBack ? (
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => navigation.goBack()}
              activeOpacity={0.6}
            >
              <Ionicons name="chevron-back" size={22} color={COLORS.headerIcon} />
            </TouchableOpacity>
          ) : (
            <View style={styles.iconBtnPlaceholder} />
          )}
        </View>

        {/* Center: Title */}
        <View style={styles.center}>
          {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
        </View>

        {/* Right: Notification */}
        <View style={styles.right}>
          {showNotification ? (
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => navigation.navigate('Notifications')}
              activeOpacity={0.6}
            >
              <Ionicons name="notifications-outline" size={20} color={COLORS.headerIcon} />
              <View style={styles.notifDot} />
            </TouchableOpacity>
          ) : (
            <View style={styles.iconBtnPlaceholder} />
          )}
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  header: {
    backgroundColor: COLORS.headerBg,
    paddingTop: Platform.OS === 'ios' ? 56 : 42,
    paddingBottom: SPACE.lg + 4,
    paddingHorizontal: SPACE.lg,
    borderBottomLeftRadius: RADIUS.lg,
    borderBottomRightRadius: RADIUS.lg,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  left: {
    width: 44,
  },
  center: {
    flex: 1,
    alignItems: 'center',
  },
  right: {
    width: 44,
    alignItems: 'flex-end',
  },
  iconBtn: {
    width: 40,
    height: 40,
    borderRadius: RADIUS.md,
    backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconBtnPlaceholder: {
    width: 40,
    height: 40,
  },
  subtitle: {
    color: COLORS.headerSub,
    fontSize: FONT.sm,
    fontWeight: '600',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  title: {
    color: COLORS.headerText,
    fontSize: FONT.xl,
    fontWeight: '700',
  },
  notifDot: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: COLORS.notifDot,
    borderWidth: 2,
    borderColor: COLORS.headerBg,
  },
});

export default ScreenHeader;
