/**
 * Loading placeholders.
 *
 * A bare spinner tells the farmer "something is happening" but not what, and on
 * a 2-second load it reads as a hang. These render the SHAPE of the content
 * that is coming, so the screen looks like it is filling in rather than stuck.
 *
 * The shimmer is a single looped Animated value driving opacity — cheap enough
 * to run on the low-end Android phones this app targets, and useNativeDriver
 * keeps it off the JS thread so it stays smooth while data is being fetched.
 */
import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated, Easing } from 'react-native';
import { COLORS, SPACE, RADIUS } from '../config/theme';

/** One shimmering grey block. */
export function Bone({ w = '100%', h = 14, r = RADIUS.sm, style }) {
  const pulse = useRef(new Animated.Value(0.4)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 750, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.4, duration: 750, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);

  return (
    <Animated.View
      style={[{ width: w, height: h, borderRadius: r, backgroundColor: COLORS.bgCardAlt, opacity: pulse }, style]}
    />
  );
}

/** Placeholder for one section row / sub-card. */
function SectionBone() {
  return (
    <View style={s.secBone}>
      <Bone w={30} h={30} r={15} />
      <View style={{ flex: 1, gap: 7 }}>
        <Bone w="55%" h={14} />
        <Bone w="80%" h={11} />
      </View>
      <Bone w={44} h={18} r={RADIUS.full} />
    </View>
  );
}

/** My Farm, both modes: summary tiles + one house card of sections. */
export function FarmSkeleton({ sections = 4 }) {
  return (
    <View accessible accessibilityLabel="Loading your farm">
      <View style={s.row}>
        {[0, 1, 2].map(i => (
          <View key={i} style={s.tile}>
            <Bone w={30} h={30} r={15} />
            <Bone w={40} h={18} />
            <Bone w={54} h={10} />
          </View>
        ))}
      </View>

      <View style={s.row}>
        <Bone w="48%" h={50} r={RADIUS.md} />
        <Bone w="48%" h={50} r={RADIUS.md} />
      </View>

      <View style={s.card}>
        <View style={s.houseHead}>
          <Bone w={38} h={38} r={RADIUS.md} />
          <View style={{ flex: 1, gap: 6 }}>
            <Bone w="60%" h={15} />
            <Bone w="40%" h={10} />
          </View>
        </View>
        {Array.from({ length: sections }).map((_, i) => <SectionBone key={i} />)}
      </View>
    </View>
  );
}

/** Section Detail: four reading tiles, a chart block, then the plan card. */
export function SectionSkeleton() {
  return (
    <View accessible accessibilityLabel="Loading this section">
      <View style={s.grid}>
        {[0, 1, 2, 3].map(i => (
          <View key={i} style={s.gridTile}>
            <Bone w={26} h={26} r={13} />
            <Bone w={64} h={26} />
            <Bone w={78} h={11} />
          </View>
        ))}
      </View>

      <Bone w={120} h={16} style={{ marginBottom: SPACE.md }} />
      <View style={s.card}><Bone w="100%" h={110} r={RADIUS.md} /></View>

      <Bone w={150} h={16} style={{ marginBottom: SPACE.md }} />
      <View style={s.card}>
        <View style={{ gap: 10 }}>
          <Bone w="45%" h={30} />
          <Bone w="70%" h={12} />
          <Bone w="60%" h={12} />
        </View>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  row:  { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.lg, justifyContent: 'space-between' },
  tile: { flex: 1, alignItems: 'center', gap: 6, backgroundColor: COLORS.bgCard,
          borderRadius: RADIUS.md, paddingVertical: SPACE.lg },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.lg,
          padding: SPACE.lg, marginBottom: SPACE.lg },

  houseHead: { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.md },
  secBone:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
               backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
               padding: SPACE.md, marginBottom: SPACE.sm },

  grid:     { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.md, marginBottom: SPACE.lg },
  gridTile: { width: '47%', flexGrow: 1, alignItems: 'center', gap: 8,
              backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, paddingVertical: SPACE.xl },
});

export default FarmSkeleton;
