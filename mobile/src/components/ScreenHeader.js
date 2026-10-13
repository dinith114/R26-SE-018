import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS } from '../config/theme';

/**
 * The one header every screen uses. Do not fork it per screen — a header that
 * differs on one tab makes the app feel broken rather than customised.
 *
 * `alertCount` is optional:
 *   - a number  -> shows that many alerts, or nothing at all when 0
 *   - undefined -> keeps the old always-on dot, so screens that do not yet
 *                  count their alerts look exactly as they did before
 * `showSettings` adds the gear beside the bell. It is rendered HERE rather than
 * passed in as a node so every screen that shows it gets the identical button.
 */
const ScreenHeader = ({
  title, subtitle, navigation, showBack = false, showNotification = true,
  alertCount, showSettings = false,
}) => {
  const hasCount = typeof alertCount === 'number';

  return (
    <View style={styles.header}>
      <View style={styles.row}>
        {/* Left: Back, or Settings on the top-level tabs.
            Settings sits opposite the bell rather than beside it, so the header
            stays balanced and the two controls cannot be mistaken for each
            other. A pushed screen shows Back here instead; Back always wins. */}
        <View style={styles.left}>
          {showBack ? (
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => navigation.goBack()}
              activeOpacity={0.6}
              accessibilityRole="button"
              accessibilityLabel="Go back"
            >
              <Ionicons name="chevron-back" size={22} color={COLORS.headerIcon} />
            </TouchableOpacity>
          ) : showSettings ? (
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => navigation.navigate('Settings')}
              activeOpacity={0.6}
              accessibilityRole="button"
              accessibilityLabel="Settings"
            >
              <Ionicons name="settings-outline" size={20} color={COLORS.headerIcon} />
            </TouchableOpacity>
          ) : (
            <View style={styles.iconBtnPlaceholder} />
          )}
        </View>

        {/* Center: Title */}
        <View style={styles.center}>
          {subtitle && <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text>}
          <Text style={styles.title} numberOfLines={1} accessibilityRole="header">{title}</Text>
        </View>

        {/* Right: Notification only */}
        <View style={styles.right}>
          {showNotification ? (
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => navigation.navigate('Notifications')}
              activeOpacity={0.6}
              accessibilityRole="button"
              accessibilityLabel={
                hasCount
                  ? (alertCount > 0
                      ? `Alerts, ${alertCount} needing attention`
                      : 'Alerts, nothing needs attention')
                  : 'Alerts'
              }
            >
              <Ionicons name="notifications-outline" size={20} color={COLORS.headerIcon} />
              {!hasCount && <View style={styles.notifDot} />}
              {hasCount && alertCount > 0 && (
                <View style={styles.notifBadge}>
                  <Text style={styles.notifBadgeText}>{alertCount > 9 ? '9+' : alertCount}</Text>
                </View>
              )}
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
  rightWide: {
    width: 92,
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: SPACE.sm,
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
  notifBadge: {
    position: 'absolute',
    top: 2,
    right: 2,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: COLORS.danger,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: COLORS.headerBg,
  },
  notifBadgeText: {
    color: '#FFF',
    fontSize: 10,
    fontWeight: '800',
  },
});

export default ScreenHeader;
