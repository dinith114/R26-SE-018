/**
 * NodePicker — choose which physical sensor node a section belongs to.
 *
 * Shown inside the Add Section flow, and again later if a section was created
 * before its hardware arrived. A section may exist with no node: that is a
 * normal state, not an error, so "Skip for now" is a first-class choice rather
 * than a way out of a broken screen.
 *
 * The hard problem this screen solves is physical: four identical boxes on a
 * bench are indistinguishable in a list. Identify blinks one board's LED so the
 * farmer can walk over and see which unit they are about to claim.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text,
  TouchableOpacity, View,
} from 'react-native';
import {
  getUnassignedDevices, identifyDevice, lastSeenLabel, signalLabel,
} from '../services/careV2';

const C = {
  ink: '#1b1a20', ink2: '#4b4954', ink3: '#7c7986',
  rule: '#e4e0d9', card: '#ffffff', wash: '#f7f6f3',
  accent: '#5b3a8e', accentWash: '#f1ecf9',
  warn: '#9a4b12', warnWash: '#fbf0e6',
};

export default function NodePicker({ onSelect, onSkip, selectedMac }) {
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [blinking, setBlinking] = useState(null);

  const load = useCallback(async (isRefresh) => {
    try {
      isRefresh ? setRefreshing(true) : setLoading(true);
      const r = await getUnassignedDevices();
      setDevices(r.devices || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // A node announces every 30s, so poll at half that. Without this the farmer
  // powers a board on, sees an empty list, and assumes it is broken.
  useEffect(() => {
    load(false);
    const t = setInterval(() => load(true), 15000);
    return () => clearInterval(t);
  }, [load]);

  const blink = async (mac) => {
    try {
      setBlinking(mac);
      await identifyDevice(mac);
      // Matches the ~10s the firmware blinks for, so the button stops looking
      // busy at roughly the moment the LED stops.
      setTimeout(() => setBlinking(null), 10000);
    } catch (e) {
      setBlinking(null);
      setError(e.message);
    }
  };

  const renderDevice = ({ item }) => {
    const sig = signalLabel(item.rssi);
    const chosen = item.mac === selectedMac;
    return (
      <TouchableOpacity
        style={[styles.row, chosen && styles.rowChosen]}
        onPress={() => onSelect?.(item)}
        accessibilityRole="button"
        accessibilityLabel={`Node ${item.shortId}, signal ${sig.label}, seen ${lastSeenLabel(item.lastSeenSec)}`}
      >
        <View style={styles.rowMain}>
          <View style={styles.rowTop}>
            <Text style={styles.name}>Node {item.shortId}</Text>
            {chosen && <Text style={styles.chosenTag}>SELECTED</Text>}
          </View>
          <Text style={styles.meta}>
            {item.online ? 'Online' : 'Offline'} · seen {lastSeenLabel(item.lastSeenSec)}
          </Text>
          <View style={styles.rowBottom}>
            <View style={[styles.dot, { backgroundColor: sig.color }]} />
            <Text style={styles.metaSmall}>{sig.label} signal</Text>
            <Text style={styles.metaSmall}> · {item.ip}</Text>
          </View>
        </View>

        <TouchableOpacity
          style={[styles.blinkBtn, blinking === item.mac && styles.blinkBtnActive]}
          onPress={() => blink(item.mac)}
          disabled={blinking === item.mac}
          accessibilityRole="button"
          accessibilityLabel={`Identify node ${item.shortId} by blinking its light`}
        >
          <Text style={[styles.blinkText, blinking === item.mac && styles.blinkTextActive]}>
            {blinking === item.mac ? 'Blinking' : 'Identify'}
          </Text>
        </TouchableOpacity>
      </TouchableOpacity>
    );
  };

  if (loading) {
    return (
      <View style={styles.centre}>
        <ActivityIndicator color={C.accent} />
        <Text style={styles.meta}>Looking for nodes…</Text>
      </View>
    );
  }

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>Link a sensor node</Text>
      <Text style={styles.sub}>
        Nodes appear here about 30 seconds after they join WiFi. Tap Identify to
        blink a node's light and see which box it is.
      </Text>

      {error && (
        <View style={styles.error}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

      <FlatList
        data={devices}
        keyExtractor={(d) => d.mac}
        renderItem={renderDevice}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={C.accent} />
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>No nodes waiting</Text>
            <Text style={styles.emptyText}>
              Every node that has joined WiFi is already linked to a section, or
              none are powered on yet.{'\n\n'}
              If you have just switched one on, give it about 30 seconds and pull
              down to refresh.
            </Text>
          </View>
        }
      />

      <TouchableOpacity style={styles.skip} onPress={onSkip} accessibilityRole="button">
        <Text style={styles.skipText}>Skip for now</Text>
        <Text style={styles.skipSub}>
          The section is created without a node and shows "No device". You can
          link one later.
        </Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: C.wash, padding: 18 },
  centre: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10 },
  title: { fontSize: 21, fontWeight: '700', color: C.ink, letterSpacing: -0.3 },
  sub: { fontSize: 14, color: C.ink2, marginTop: 5, marginBottom: 16, lineHeight: 20 },

  row: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    backgroundColor: C.card, borderWidth: 1, borderColor: C.rule,
    borderRadius: 12, padding: 15, marginBottom: 10,
  },
  rowChosen: { borderColor: C.accent, backgroundColor: C.accentWash },
  rowMain: { flex: 1 },
  rowTop: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { fontSize: 16, fontWeight: '700', color: C.ink },
  chosenTag: {
    fontSize: 10, fontWeight: '800', color: C.accent, letterSpacing: 0.6,
    backgroundColor: '#fff', paddingHorizontal: 7, paddingVertical: 2, borderRadius: 10,
  },
  meta: { fontSize: 13, color: C.ink2, marginTop: 3 },
  rowBottom: { flexDirection: 'row', alignItems: 'center', marginTop: 5 },
  metaSmall: { fontSize: 12, color: C.ink3 },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },

  blinkBtn: {
    borderWidth: 1, borderColor: C.accent, borderRadius: 8,
    paddingHorizontal: 13, paddingVertical: 8,
  },
  blinkBtnActive: { backgroundColor: C.accent },
  blinkText: { fontSize: 13, fontWeight: '700', color: C.accent },
  blinkTextActive: { color: '#fff' },

  empty: { padding: 26, alignItems: 'center' },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: C.ink, marginBottom: 7 },
  emptyText: { fontSize: 14, color: C.ink2, textAlign: 'center', lineHeight: 20 },

  error: {
    backgroundColor: C.warnWash, borderLeftWidth: 3, borderLeftColor: C.warn,
    padding: 12, borderRadius: 7, marginBottom: 12,
  },
  errorText: { fontSize: 13, color: C.warn },

  skip: {
    borderTopWidth: 1, borderTopColor: C.rule, paddingTop: 15, marginTop: 6,
  },
  skipText: { fontSize: 15, fontWeight: '700', color: C.accent },
  skipSub: { fontSize: 12.5, color: C.ink3, marginTop: 3, lineHeight: 18 },
});
