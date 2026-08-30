/**
 * Boot screen.
 *
 * Three surfaces have to agree or the app flashes on launch:
 *
 *   1. the NATIVE splash   android/app/src/main/res/values/colors.xml
 *                          -> splashscreen_background = #FAFAF9
 *   2. this screen         COLORS.bg                  = #FAFAF9
 *   3. the app itself      COLORS.bg                  = #FAFAF9
 *
 * They are the same colour on purpose, so the handover from the system splash
 * to React and then to the navigator is invisible. Note that `splash` in
 * app.json says #1C591D and is IGNORED - the native resources are the real
 * ones, and `expo prebuild` must never be run to regenerate them (it wipes the
 * cleartext-traffic fix). If you restyle this screen, change colors.xml too.
 *
 * `assets/icon.png` is the launcher artwork: a pale orchid over a solid
 * #1C591D field, measured at every edge. It is clipped to a squircle here so it
 * reads as the app's own tile rather than a picture dropped on the page.
 *
 * ANIMATION CONSTRAINT: every driver here is useNativeDriver:false. Mixing
 * native and non-native drivers on one animated node crashes the app, and the
 * progress bar animates width (a layout property) which native cannot do.
 * Do not "optimise" any of these to true.
 *
 * No LinearGradient here on purpose either: this screen gates the whole app,
 * so it stays free of native modules that could fail and leave a dead screen.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo, Animated, Easing, Image, StyleSheet, Text, View,
} from 'react-native';
import { COLORS, FONT, RADIUS, SPACE } from '../config/theme';

const TILE = 128;
const GLOW = TILE + 84;

export default function SplashScreen({ onFinish }) {
  const tileScale = useRef(new Animated.Value(0.86)).current;
  const tileFade  = useRef(new Animated.Value(0)).current;
  const glowFade  = useRef(new Animated.Value(0)).current;
  const textFade  = useRef(new Animated.Value(0)).current;
  const textRise  = useRef(new Animated.Value(18)).current;
  const metaFade  = useRef(new Animated.Value(0)).current;
  const barGrow   = useRef(new Animated.Value(0)).current;

  const [tagline, setTagline] = useState('Starting up');

  useEffect(() => {
    let cancelled = false;
    const done = () => { if (!cancelled) { cancelled = true; onFinish?.(); } };

    // The splash gates the entire app: if an animation callback is ever missed
    // the farmer is left on a dead screen with no way forward. This guarantees
    // the app opens regardless of what the animation does.
    const failsafe = setTimeout(done, 6000);

    AccessibilityInfo.isReduceMotionEnabled().then((reduce) => {
      if (cancelled) return;

      if (reduce) {
        // Respect the system setting: show the finished frame, do not animate.
        tileScale.setValue(1); tileFade.setValue(1); glowFade.setValue(0.3);
        textFade.setValue(1);  textRise.setValue(0); metaFade.setValue(1);
        barGrow.setValue(1);
        setTagline('Smart care for Vanda orchids');
        setTimeout(done, 900);
        return;
      }

      Animated.sequence([
        // 1. the tile settles in, with the glow blooming underneath it
        Animated.parallel([
          Animated.timing(tileFade,  { toValue: 1, duration: 260, useNativeDriver: false }),
          Animated.spring(tileScale, { toValue: 1, tension: 46, friction: 7, useNativeDriver: false }),
          Animated.sequence([
            Animated.timing(glowFade, { toValue: 0.5,  duration: 420, useNativeDriver: false }),
            Animated.timing(glowFade, { toValue: 0.28, duration: 460, useNativeDriver: false }),
          ]),
        ]),

        // 2. wordmark rises
        Animated.parallel([
          Animated.timing(textFade, { toValue: 1, duration: 300, useNativeDriver: false }),
          Animated.timing(textRise, {
            toValue: 0, duration: 420, easing: Easing.out(Easing.cubic), useNativeDriver: false,
          }),
        ]),

        // 3. tagline, then the progress bar
        Animated.timing(metaFade, { toValue: 1, duration: 260, useNativeDriver: false }),
        Animated.timing(barGrow, {
          toValue: 1, duration: 780, easing: Easing.inOut(Easing.quad), useNativeDriver: false,
        }),
        Animated.delay(240),
      ]).start(done);

      // Swapped once the wordmark is up, so the line reads as a caption to the
      // name rather than a status message floating on its own.
      setTimeout(() => { if (!cancelled) setTagline('Smart care for Vanda orchids'); }, 900);
    }).catch(() => setTimeout(done, 1200));

    return () => { cancelled = true; clearTimeout(failsafe); };
  }, []);

  return (
    <View style={s.root} accessible accessibilityLabel="Orchid Care is starting">
      <View style={s.centre}>
        <View style={s.tileWrap}>
          <Animated.View style={[s.glow, { opacity: glowFade }]} />
          <Animated.View
            style={[s.tile, { opacity: tileFade, transform: [{ scale: tileScale }] }]}>
            <Image source={require('../../assets/icon.png')} style={s.icon} resizeMode="cover" />
          </Animated.View>
        </View>

        <Animated.View
          style={[s.words, { opacity: textFade, transform: [{ translateY: textRise }] }]}>
          <Text style={s.title}>
            Orchid<Text style={s.titleAccent}> Care</Text>
          </Text>
        </Animated.View>

        <Animated.View style={[s.meta, { opacity: metaFade }]}>
          <Text style={s.tagline}>{tagline}</Text>
          <View style={s.track}>
            <Animated.View
              style={[s.fill, {
                width: barGrow.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }),
              }]}
            />
          </View>
        </Animated.View>
      </View>

      <Text style={s.footer}>R26-SE-018  ·  SLIIT</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  centre: { alignItems: 'center' },

  tileWrap: { alignItems: 'center', justifyContent: 'center' },
  // Soft emerald bloom behind the tile. This is what stops a flat page from
  // reading as an unstyled loading screen.
  glow: {
    position: 'absolute',
    width: GLOW, height: GLOW, borderRadius: GLOW / 2,
    backgroundColor: COLORS.primaryLight,
  },
  tile: {
    width: TILE, height: TILE,
    borderRadius: 30,           // ~0.23 of the side, matching Android's icon mask
    overflow: 'hidden',         // artwork is a hard-edged square, so it must be clipped
    backgroundColor: '#1C591D', // the icon's own field colour, measured at every edge
    shadowColor: COLORS.primaryDark,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.26,
    shadowRadius: 22,
    elevation: 12,
  },
  icon: { width: '100%', height: '100%' },

  words: { marginTop: SPACE.xxl },
  title: {
    fontSize: 33,
    fontWeight: '800',
    color: COLORS.text,
    letterSpacing: -0.9,
  },
  titleAccent: { color: COLORS.primary },

  meta: { alignItems: 'center', marginTop: SPACE.md, width: 208 },
  tagline: {
    fontSize: FONT.sm,
    color: COLORS.textTertiary,
    marginBottom: SPACE.lg,
    textAlign: 'center',
  },
  track: {
    width: '100%',
    height: 3,
    backgroundColor: COLORS.border,
    borderRadius: RADIUS.full,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.full,
  },

  // left/right + textAlign rather than letting the absolute box size to its
  // content: with letterSpacing set, Android measures the text narrower than it
  // draws it and clips the last word ("SLIIT" went missing on a Pixel 5).
  footer: {
    position: 'absolute',
    bottom: 44,
    left: 0,
    right: 0,
    textAlign: 'center',
    fontSize: FONT.xs,
    color: COLORS.textTertiary,
    letterSpacing: 2,
  },
});
