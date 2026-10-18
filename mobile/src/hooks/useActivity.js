/**
 * The live status of every pour on the farm, shared by every screen that shows it.
 *
 * ONE poller for the whole app, not one per screen: the Dashboard, My Farm and a
 * section can all be mounted at once in the navigation stack, and three timers
 * asking the same question would triple the server's reads for nothing. It asks
 * every 4 s while something is waiting or pouring, every 30 s otherwise, stops
 * when no screen is listening, and pauses while the app is in the background.
 *
 * Why it exists (18 Oct 2026): a pour was followed only by the screen that
 * started it. Leave that screen and the status was gone; an automatic pour was
 * never shown at all until it was history.
 */
import { useEffect, useState } from 'react';
import { AppState } from 'react-native';
import { getActivity } from '../services/careV2';
import { pollMs } from '../services/activityText';

const store = { items: [], serverNowSec: null, at: 0, error: null };
const listeners = new Set();
let timer = null;
let inFlight = false;
let appActive = true;

function schedule() {
  clearTimeout(timer);
  timer = null;
  if (!listeners.size || !appActive) return;
  timer = setTimeout(poll, pollMs(store.items));
}

async function poll() {
  if (inFlight) return;
  inFlight = true;
  try {
    const r = await getActivity();
    store.items = Array.isArray(r?.items) ? r.items : [];
    store.serverNowSec = r?.serverNowSec ?? null;
    store.at = Date.now();
    store.error = null;
  } catch (e) {
    // Keep what was last known: a dropped poll is not "nothing is running".
    store.error = e?.message || 'Could not reach the server';
  } finally {
    inFlight = false;
  }
  const snap = { ...store };
  listeners.forEach((fn) => fn(snap));
  schedule();
}

/** Ask now: after a pour is sent or stopped, or when a screen comes back into view. */
export function refreshActivity() {
  clearTimeout(timer);
  timer = null;
  poll();
}

AppState.addEventListener('change', (s) => {
  appActive = s === 'active';
  if (appActive && listeners.size) refreshActivity();
  else { clearTimeout(timer); timer = null; }
});

export default function useActivity() {
  const [snap, setSnap] = useState(() => ({ ...store }));
  useEffect(() => {
    listeners.add(setSnap);
    if (Date.now() - store.at > 2500) refreshActivity();
    else schedule();
    return () => {
      listeners.delete(setSnap);
      if (!listeners.size) { clearTimeout(timer); timer = null; }
    };
  }, []);
  return snap;
}
