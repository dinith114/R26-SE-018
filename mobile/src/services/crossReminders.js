/**
 * Reminders for an open cross.
 *
 * A Vanda capsule takes about nine months. Nobody remembers an unmarked
 * capsule eight months later, and a logbook nobody is prompted to update is a
 * logbook with one entry per cross and no outcome — exactly the shape of data
 * that cannot answer anything. The reminders are what turn this from a form
 * into a record.
 *
 * These are LOCAL scheduled notifications, not push. Expo Go dropped remote
 * push in SDK 53; on-device scheduling still works, so this runs in Expo Go
 * as well as in a build.
 *
 * Every function here swallows its errors on purpose. A notification that
 * could not be scheduled is a small loss; a save that failed because of one
 * is the grower's record gone. Scheduling must never be able to fail a save.
 */
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

/* When to ask, counted from pollination, and what to ask.
   The gaps follow the biology rather than a round number: the pod either
   sets or drops inside three weeks, then nothing visible happens for months,
   then the capsule has to be caught before it splits and scatters. */
const SCHEDULE = [
  { days: 14,  title: 'Did the pod set?',
    body: 'Check {id} — {cross}. Has the ovary started to swell?' },
  { days: 45,  title: 'Capsule still holding?',
    body: '{id} — {cross}. Is the capsule green and still attached?' },
  { days: 150, title: 'Halfway check',
    body: '{id} — {cross}. Around five months in. Still developing?' },
  { days: 240, title: 'Ripening soon',
    body: '{id} — {cross} is near maturity. Check weekly — a split capsule '
        + 'scatters the seed and the cross is lost.' },
];

let configured = false;

/** Ask once, and only when something is actually being scheduled. */
const ensurePermission = async () => {
  if (!configured) {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true, shouldPlaySound: false, shouldSetBadge: false,
      }),
    });
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('crosses', {
        name: 'Cross reminders',
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }
    configured = true;
  }

  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  const asked = await Notifications.requestPermissionsAsync();
  return Boolean(asked.granted);
};

/**
 * Schedule the check-ins for one newly logged cross.
 *
 * Returns the identifiers so they could be cancelled when the cross closes;
 * resolves to an empty list on any failure rather than throwing.
 */
export const scheduleCrossReminders = async (cross) => {
  try {
    if (!(await ensurePermission())) return [];

    const names = `${cross.podName} × ${cross.pollenName}`;
    const ids = [];

    for (const step of SCHEDULE) {
      const id = await Notifications.scheduleNotificationAsync({
        content: {
          title: step.title,
          body: step.body.replace('{id}', cross.crossId).replace('{cross}', names),
          data: { crossId: cross.crossId },
        },
        trigger: {
          type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
          seconds: step.days * 24 * 60 * 60,
          channelId: 'crosses',
        },
      });
      ids.push(id);
    }
    return ids;
  } catch (error) {
    // Expo Go, a denied permission, a platform quirk — none of it is worth
    // failing a save over.
    console.log('Cross reminders not scheduled:', error?.message);
    return [];
  }
};

/** Fire one immediately, so a demo can show what the grower will receive. */
export const previewCrossReminder = async (cross) => {
  try {
    if (!(await ensurePermission())) return false;
    await Notifications.scheduleNotificationAsync({
      content: {
        title: 'Did the pod set?',
        body: `Check ${cross.crossId} — ${cross.podName} × ${cross.pollenName}. `
            + 'Has the ovary started to swell?',
        data: { crossId: cross.crossId },
      },
      trigger: {
        type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL,
        seconds: 5,
        channelId: 'crosses',
      },
    });
    return true;
  } catch (error) {
    console.log('Preview reminder not scheduled:', error?.message);
    return false;
  }
};
