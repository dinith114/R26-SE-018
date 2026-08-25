import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Dimensions, Image } from 'react-native';
import { COLORS, FONT, SPACE } from '../config/theme';

const { width } = Dimensions.get('window');

const FLOWER_SIZE = 140;
const STEM_H      = 64;

const SplashScreen = ({ onFinish }) => {
  // Stem
  const stemH       = useRef(new Animated.Value(0)).current;
  const stemOpacity = useRef(new Animated.Value(0)).current;

  // Flower — clip reveal (non-native: height)
  const clipH       = useRef(new Animated.Value(0)).current;
  // Flower — petal spread + fade (native)
  const petalScale  = useRef(new Animated.Value(0.65)).current;
  const petalOpacity= useRef(new Animated.Value(0)).current;

  // Glow pulse (native)
  const glowOpacity = useRef(new Animated.Value(0)).current;

  // Text (native)
  const textSlide   = useRef(new Animated.Value(36)).current;
  const textOpacity = useRef(new Animated.Value(0)).current;

  // Bottom bar (non-native: width %)
  const subFade     = useRef(new Animated.Value(0)).current;
  const barWidth    = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.sequence([
      // ── 1. Stem grows upward ──────────────────────────────
      Animated.parallel([
        Animated.timing(stemOpacity, { toValue: 1, duration: 150, useNativeDriver: true }),
        Animated.timing(stemH,       { toValue: STEM_H, duration: 450, useNativeDriver: false }),
      ]),

      // ── 2. Flower reveals bottom → top (clip container grows) ──
      Animated.parallel([
        Animated.timing(petalOpacity, { toValue: 1, duration: 200, useNativeDriver: true }),
        Animated.timing(clipH,        { toValue: FLOWER_SIZE, duration: 550, useNativeDriver: false }),
      ]),

      // ── 3. Petals spring open ─────────────────────────────
      Animated.spring(petalScale, { toValue: 1, tension: 38, friction: 5, useNativeDriver: true }),

      // ── 4. Glow flash ────────────────────────────────────
      Animated.sequence([
        Animated.timing(glowOpacity, { toValue: 0.35, duration: 220, useNativeDriver: true }),
        Animated.timing(glowOpacity, { toValue: 0,    duration: 380, useNativeDriver: true }),
      ]),

      // ── 5. Title slides up ────────────────────────────────
      Animated.parallel([
        Animated.timing(textOpacity, { toValue: 1, duration: 380, useNativeDriver: true }),
        Animated.spring(textSlide,   { toValue: 0, tension: 50, friction: 8, useNativeDriver: true }),
      ]),

      // ── 6. Subtitle + progress bar ────────────────────────
      Animated.timing(subFade,  { toValue: 1, duration: 350, useNativeDriver: true }),
      Animated.timing(barWidth, { toValue: 1, duration: 1000, useNativeDriver: false }),
      Animated.delay(400),
    ]).start(() => onFinish?.());
  }, []);

  return (
    <View style={styles.container}>

      {/* ── Bloom assembly (flower + stem, stacked column) ── */}
      <View style={styles.bloomWrap}>

        {/* Glow ring sits behind the flower */}
        <Animated.View style={[styles.glowRing, { opacity: glowOpacity }]} />

        {/* Clip container — grows 0 → FLOWER_SIZE, overflow hidden reveals bottom→top */}
        <Animated.View style={[styles.clipBox, { height: clipH }]}>
          {/* Image pinned to the bottom of the clip so it reveals from base upward */}
          <Animated.View style={[styles.flowerInner, {
            transform: [{ scale: petalScale }],
            opacity: petalOpacity,
          }]}>
            <Image
              source={require('../../assets/orchid_flower.png')}
              style={styles.flowerImg}
              resizeMode="contain"
            />
          </Animated.View>
        </Animated.View>

        {/* Stem */}
        <Animated.View style={[styles.stem, { height: stemH, opacity: stemOpacity }]} />
      </View>

      {/* Title */}
      <Animated.View style={[styles.textWrap, {
        opacity: textOpacity,
        transform: [{ translateY: textSlide }],
      }]}>
        <Text style={styles.title}>Orchid</Text>
        <Text style={styles.accent}>Smart Care</Text>
      </Animated.View>

      {/* Progress */}
      <Animated.View style={[styles.meta, { opacity: subFade }]}>
        <Text style={styles.tag}>IoT Monitoring & ML Prediction</Text>
        <View style={styles.track}>
          <Animated.View style={[styles.fill, {
            width: barWidth.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }),
          }]} />
        </View>
      </Animated.View>

      <View style={styles.footer}>
        <Text style={styles.footerText}>R26-SE-018  ·  SLIIT</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
    alignItems: 'center',
    justifyContent: 'center',
  },

  /* Bloom */
  bloomWrap: {
    alignItems: 'center',
    marginBottom: SPACE.xl,
  },
  glowRing: {
    position: 'absolute',
    top: -16,
    width: FLOWER_SIZE + 40,
    height: FLOWER_SIZE + 40,
    borderRadius: (FLOWER_SIZE + 40) / 2,
    backgroundColor: COLORS.primary,
  },
  clipBox: {
    width: FLOWER_SIZE,
    overflow: 'hidden',  // ← hides unrevealed portion of image
    justifyContent: 'flex-end', // image pinned to bottom edge
  },
  flowerInner: {
    width: FLOWER_SIZE,
    height: FLOWER_SIZE,
  },
  flowerImg: {
    width: FLOWER_SIZE,
    height: FLOWER_SIZE,
  },
  stem: {
    width: 5,
    backgroundColor: COLORS.primary,
    borderRadius: 3,
    marginTop: 2,
    opacity: 0.85,
  },

  /* Text */
  textWrap: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 38,
    fontWeight: '800',
    color: COLORS.text,
    letterSpacing: -1,
  },
  accent: {
    fontSize: 38,
    fontWeight: '800',
    color: COLORS.primary,
    letterSpacing: -1,
  },

  /* Bottom */
  meta: {
    alignItems: 'center',
    width: width * 0.45,
  },
  tag: {
    fontSize: FONT.xs,
    color: COLORS.textTertiary,
    textAlign: 'center',
    marginBottom: SPACE.xl,
  },
  track: {
    width: '100%',
    height: 3,
    backgroundColor: COLORS.border,
    borderRadius: 2,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    backgroundColor: COLORS.primary,
    borderRadius: 2,
  },
  footer: {
    position: 'absolute',
    bottom: 48,
  },
  footerText: {
    fontSize: FONT.xs,
    color: COLORS.textTertiary,
    letterSpacing: 2,
  },
});

export default SplashScreen;
