/**
 * diseaseHistory.js — local record of past disease analyses.
 *
 * WHERE THIS LIVES, AND WHY IT MATTERS
 * ------------------------------------
 * History is stored with AsyncStorage, which is a small key-value store INSIDE
 * the app, on ONE device. It is not a server and not a database.
 *
 *   survives closing the app      yes
 *   survives restarting the phone yes
 *   survives uninstalling         NO
 *   visible on another device     NO
 *
 * That is an honest limitation to state rather than hide: making history follow
 * a user across devices needs a backend and a database, which is future work.
 * For a single grower checking their own plants it is the right size of
 * solution and it works with no network at all.
 *
 * WHAT IS STORED, AND WHAT IS NOT
 * -------------------------------
 * The photograph itself is NOT copied. Only its local file path is saved,
 * because AsyncStorage is meant for small values and phone photos are ~2 MB
 * each — a handful would exhaust it.
 *
 * The consequence: Android and iOS may clear the image picker's cache to
 * reclaim space, and an older entry's thumbnail then points at a file that no
 * longer exists. The screen shows a placeholder in that case; the diagnosis,
 * severity and treatment are unaffected because they are stored as data, not
 * as pictures. Keeping images permanently would need expo-file-system.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = '@orchid/disease_history/v1';

/** Newest first. Older entries beyond this are dropped. */
const MAX_ENTRIES = 100;

/**
 * Everything one row of the history table needs.
 *
 * The full treatment object is stored alongside the diagnosis so the Treatment
 * modal opens instantly and works offline. It is a few kilobytes of text.
 */
function toEntry(result, imageUri) {
  const treatment = result.treatment || {};
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    analysedAt: new Date().toISOString(),
    imageUri: imageUri || null,

    disease: result.disease,
    displayName: treatment.display_name || result.disease,
    confidence: result.confidence,
    confident: result.confident !== false,

    severity: result.severity || null,
    severityConfidence: result.severity_confidence || null,

    // Kept so a row can explain itself without another network call.
    explanation: result.explanation || '',
    treatment,
  };
}

/** Read the whole history, newest first. Never throws. */
export async function loadHistory() {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // A corrupt or unreadable store must not break the screen. An empty
    // history is a survivable outcome; a crash on open is not.
    return [];
  }
}

/**
 * Record one analysis. Returns the saved entry, or null if saving failed.
 *
 * Deliberately swallows its errors: a failure to write history must never stop
 * the user from seeing the diagnosis they just asked for.
 */
export async function addToHistory(result, imageUri) {
  try {
    const entry = toEntry(result, imageUri);
    const existing = await loadHistory();
    const next = [entry, ...existing].slice(0, MAX_ENTRIES);
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    return entry;
  } catch {
    return null;
  }
}

/** Remove one entry by id. Returns the remaining list. */
export async function deleteEntry(id) {
  const remaining = (await loadHistory()).filter((e) => e.id !== id);
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(remaining));
  } catch {
    /* keep the in-memory list usable even if the write failed */
  }
  return remaining;
}

/** Wipe everything. Used by the "Clear history" action. */
export async function clearHistory() {
  try {
    await AsyncStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing useful to do */
  }
  return [];
}

/** Small counts for the hub card: total, and how many found a disease. */
export async function historySummary() {
  const entries = await loadHistory();
  const diseased = entries.filter(
    (e) => e.confident && e.disease !== 'healthy' && e.disease !== 'unidentified'
  ).length;
  return {
    total: entries.length,
    diseased,
    lastAt: entries.length ? entries[0].analysedAt : null,
  };
}
