import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Dimensions, Image } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE } from '../config/theme';

const { width } = Dimensions.get('window');

const SplashScreen = ({ onFinish }) => {
  const fadeIn = useRef(new Animated.Value(0)).current;
  const slideUp = useRef(new Animated.Value(30)).current;
  const flowerScale = useRef(new Animated.Value(0.3)).current;
  const flowerRotate = useRef(new Animated.Value(0)).current;
  const barWidth = useRef(new Animated.Value(0)).current;
  const subFade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.sequence([
      // Flower blooms in
      Animated.parallel([
        Animated.spring(flowerScale, { toValue: 1, tension: 40, friction: 5, useNativeDriver: true }),
        Animated.timing(flowerRotate, { toValue: 1, duration: 800, useNativeDriver: true }),
        Animated.timing(fadeIn, { toValue: 1, duration: 600, useNativeDriver: true }),
        Animated.spring(slideUp, { toValue: 0, tension: 50, friction: 8, useNativeDriver: true }),
      ]),
      // Subtitle + bar
      Animated.timing(subFade, { toValue: 1, duration: 400, useNativeDriver: true }),
      Animated.timing(barWidth, { toValue: 1, duration: 1000, useNativeDriver: false }),
      Animated.delay(400),
    ]).start(() => onFinish?.());
  }, []);

  const spin = flowerRotate.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  return (
    <View style={styles.container}>
      {/* Orchid flower */}
      <Animated.View style={[styles.flowerWrap, {
        transform: [{ scale: flowerScale }, { rotate: spin }],
        opacity: fadeIn,
      }]}>
        <Image
          source={require('../../assets/orchid_flower.png')}
          style={styles.flowerImg}
          resizeMode="contain"
        />
      </Animated.View>

      {/* Text */}
      <Animated.View style={[styles.textWrap, {
        opacity: fadeIn,
        transform: [{ translateY: slideUp }],
      }]}>
        <Text style={styles.title}>Orchid</Text>
        <Text style={styles.accent}>Smart Care</Text>
      </Animated.View>

      {/* Bottom */}
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
  flowerWrap: {
    marginBottom: SPACE.xl,
  },
  flowerImg: {
    width: 140,
    height: 140,
  },
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
