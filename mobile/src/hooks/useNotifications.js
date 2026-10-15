/**
 * The farm's notifications, minus the ones this person cleared.
 *
 * One store for the whole app, so clearing on the Notifications screen takes
 * the number off the bell on My Farm at once, not at its next poll. The cleared
 * keys live on this phone (AsyncStorage): the server works the list out fresh
 * every time and keeps nothing to delete. The rules are in
 * services/notifyRules.js, which is tested without a device.
 */
import { useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import useLiveData from './useLiveData';
import { getAlerts } from '../services/careV2';
import {
  splitAlerts, badgeCount, clearOne, clearAll, restoreOne, refreshSeen,
} from '../services/notifyRules';

const KEY = 'clearedNotifications.v1';

let cleared = {};
let loaded = false;
const subs = new Set();

function publish(next, persist = true) {
  cleared = next;
  subs.forEach((fn) => fn(next));
  if (persist) AsyncStorage.setItem(KEY, JSON.stringify(next)).catch(() => {});
}

const ready = AsyncStorage.getItem(KEY)
  .then((v) => { if (v) publish(JSON.parse(v) || {}, false); })
  .catch(() => {})
  .finally(() => { loaded = true; });

export default function useNotifications(intervalMs = 20000) {
  const live = useLiveData(getAlerts, intervalMs);
  const [mine, setMine] = useState(cleared);

  useEffect(() => {
    subs.add(setMine);
    setMine(cleared);
    return () => { subs.delete(setMine); };
  }, []);

  const alerts = live.data?.alerts || [];

  // Keep the cleared list honest against what the server still says. Waits
  // for storage, or a first fetch could forget keys it has not read yet.
  useEffect(() => {
    if (!live.data) return;
    ready.then(() => {
      const next = refreshSeen(cleared, live.data.alerts || [], Date.now());
      if (next !== cleared) publish(next);
    });
  }, [live.data]);

  const { shown, hidden } = splitAlerts(alerts, mine);
  return {
    ...live,
    alerts,
    shown,
    hidden,
    // No number until both the list and the cleared keys are in, rather than a
    // count that drops a moment later. 0, not undefined: undefined makes the
    // header draw its old always-on dot.
    badge: live.data && loaded ? badgeCount(alerts, mine) : 0,
    clear: (a) => publish(clearOne(cleared, a, Date.now())),
    clearAll: () => publish(clearAll(cleared, alerts, Date.now())),
    restore: (a) => publish(restoreOne(cleared, a)),
    restoreAll: () => publish(hidden.reduce((c, a) => restoreOne(c, a), cleared)),
  };
}
