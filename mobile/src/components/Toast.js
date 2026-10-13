/**
 * "3 sections watered" — the confirmation after something finished.
 *
 * This is an IN-APP banner, not a phone notification, and that is a current
 * limitation rather than a design choice: push has never worked on this build
 * because `google-services.json` is absent, so no device has ever been issued a
 * push token. When that is fixed these same messages can also go out as real
 * notifications; until then a banner is the honest option, because it only
 * claims to tell you something while you are looking at the app.
 *
 * Auto-hides, but stays long enough to read a sentence. Tapping dismisses it
 * early. Errors do not auto-hide as fast, because a failure the farmer misses
 * is a plant that did not get watered.
 */
import React, { useEffect, useRef } from 'react';
import { Animated, Text, StyleSheet, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

const KIND = {
  success: { icon: 'checkmark-circle', tint: COLORS.success, ms: 3200 },
  info:    { icon: 'information-circle', tint: COLORS.info,  ms: 3200 },
  error:   { icon: 'alert-circle',      tint: COLORS.danger, ms: 5200 },
};

export default function Toast({ text, kind = 'success', onDone }) {
  // Both properties are native-drivable, so the driver stays consistent on this
  // node. Never mix native and non-native on one animated node.
  const slide = useRef(new Animated.Value(-90)).current;
  const fade  = useRef(new Animated.Value(0)).current;
  const timer = useRef(null);

  const style = KIND[kind] || KIND.success;

  const hide = () => {
    clearTimeout(timer.current);
    Animated.parallel([
      Animated.timing(slide, { toValue: -90, duration: 220, useNativeDriver: true }),
      Animated.timing(fade,  { toValue: 0,   duration: 200, useNativeDriver: true }),
    ]).start(() => onDone?.());
  };

  useEffect(() => {
    if (!text) return undefined;
    slide.setValue(-90);
    fade.setValue(0);
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, tension: 60, friction: 9, useNativeDriver: true }),
      Animated.timing(fade,  { toValue: 1, duration: 200, useNativeDriver: true }),
    ]).start();

    timer.current = setTimeout(hide, style.ms);
    return () => clearTimeout(timer.current);
  }, [text, kind]);

  if (!text) return null;

  return (
    <Animated.View
      style={[s.wrap, SHADOW.lg, { opacity: fade, transform: [{ translateY: slide }] }]}
      pointerEvents="box-none">
      <TouchableOpacity
        style={[s.card, { borderLeftColor: style.tint }]}
        onPress={hide}
        activeOpacity={0.9}
        accessibilityRole="alert"
        accessibilityLabel={text}>
        <Ionicons name={style.icon} size={21} color={style.tint} />
        <Text style={s.text} numberOfLines={3}>{text}</Text>
        <View style={s.close}>
          <Ionicons name="close" size={16} color={COLORS.textTertiary} />
        </View>
      </TouchableOpacity>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: {
    position: 'absolute',
    top: 0, left: 0, right: 0,
    paddingTop: 46,          // clear of the status bar
    paddingHorizontal: SPACE.lg,
    zIndex: 100,
  },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: SPACE.md,
    backgroundColor: COLORS.bgCard,
    borderRadius: RADIUS.md,
    borderLeftWidth: 4,
    paddingVertical: SPACE.md + 2,
    paddingHorizontal: SPACE.lg,
  },
  text: {
    flex: 1,
    color: COLORS.text,
    fontSize: FONT.md + 1,
    fontWeight: '600',
    lineHeight: 20,
  },
  close: { opacity: 0.7 },
});
