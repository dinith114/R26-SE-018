/**
 * Push alarms.
 *
 * When automatic care is OFF the system still decides everything — it just does
 * not act. Instead it raises an ACTION alarm, and this is what makes the
 * farmer's phone buzz about it, even with the app closed.
 *
 * IMPORTANT BUILD NOTE
 * --------------------
 * Remote push does not work in Expo Go on Android (Expo removed it in SDK 53,
 * and this project is on SDK 54). The app must be run as a development build:
 *
 *     npx expo run:android          (or an EAS build)
 *
 * In Expo Go the registration below fails harmlessly, is reported once, and the
 * app keeps working — the alarms are still listed in the Notifications screen,
 * they just cannot buzz the phone. Nothing else degrades.
 */
import { useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { registerPushToken } from '../services/careV2';

// Show the alarm even if the app happens to be open when it arrives.
//
// Wrapped because this runs at MODULE level: App.js imports this file, so an
// exception here happens before anything renders and takes the whole app down
// with a black screen and no JS logs to explain it. Alarms are a feature; the
// app failing to start is not an acceptable price for them.
try {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
} catch (e) {
  console.warn('[push] notification handler unavailable:', e?.message);
}

/* The channel id is VERSIONED, and that is not cosmetic.
   Android freezes a notification channel's settings at creation time: every
   later change in code — importance, sound, lockscreen visibility — is silently
   ignored for a channel that already exists. The old 'alarms' channel proved
   it, sitting on the device with mLockscreenVisibility=-1000 while this file
   had been asking for PUBLIC for months.
   So changing how an alarm behaves REQUIRES a new id. Bump this suffix if you
   ever change the settings below, or your change will do nothing on any phone
   that already has the app. */
const ALARM_CHANNEL = 'farm-alarm-v3';

async function ensureAndroidChannel() {
  if (Platform.OS !== 'android') return;
  // A high-importance channel is what lets an alarm make a sound and appear
  // as a heads-up banner rather than sitting silently in the shade.
  await Notifications.setNotificationChannelAsync(ALARM_CHANNEL, {
    name: 'Farm alarms',
    description: 'Watering and tray alarms that need you to act.',
    importance: Notifications.AndroidImportance.MAX,
    // USAGE_ALARM, not the notification stream. This is the difference between
    // a chime and an alarm: it plays at ALARM volume and is not silenced by
    // silent mode or Do Not Disturb. A farmer asleep at 6 am is exactly who
    // this has to reach.
    audioAttributes: {
      usage: Notifications.AndroidAudioUsage.ALARM,
      contentType: Notifications.AndroidAudioContentType.SONIFICATION,
    },
    /* A real alarm sound, bundled at android/app/src/main/res/raw/farm_alarm.wav.
       'default' resolves to the phone's NOTIFICATION sound - on this device a
       one-second chime called "Popcorn" - which played at alarm volume but
       still sounded like a message rather than an alarm. There is no way to
       point a channel at the system alarm ringtone from here, so the sound
       ships with the app: 9 seconds of a two-tone pulse. */
    sound: 'farm_alarm.wav',
    vibrationPattern: [0, 500, 250, 500, 250, 500, 250, 500],
    enableVibrate: true,
    bypassDnd: true,
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    showBadge: true,
  });

  // The old channel had frozen settings and would otherwise linger in the
  // phone's notification settings as a second, confusing entry.
  for (const old of ['alarms', 'farm-alarm-v2']) {
    try { await Notifications.deleteNotificationChannelAsync(old); }
    catch (_) { /* never existed on a fresh install */ }
  }
}

/**
 * Registers this phone with the backend and routes taps.
 * @param onOpenAlarm  called with the alarm payload when a notification is tapped
 */
export default function usePushAlarms(onOpenAlarm) {
  const [status, setStatus] = useState({ ready: false, token: null, reason: null });
  const tapRef = useRef();
  tapRef.current = onOpenAlarm;

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        await ensureAndroidChannel();

        if (!Device.isDevice) {
          if (!cancelled) setStatus({ ready: false, token: null,
            reason: 'Push alarms only work on a real phone, not a simulator.' });
          return;
        }

        const existing = await Notifications.getPermissionsAsync();
        let granted = existing.granted
          || existing.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL;
        if (!granted) {
          const asked = await Notifications.requestPermissionsAsync();
          granted = asked.granted;
        }
        if (!granted) {
          if (!cancelled) setStatus({ ready: false, token: null,
            reason: 'Notification permission was refused, so alarms cannot reach this phone.' });
          return;
        }

        /* The NATIVE FCM token, not an Expo push token.
           getExpoPushTokenAsync would hand back an ExponentPushToken, which
           only Expo's own relay can deliver to - and that relay needs an FCM
           service-account key uploaded to an EAS project, an extra account and
           an interactive CLI standing between a decision and this phone. The
           backend now holds the key and talks to FCM itself, so the device
           token is what it needs.

           Requires google-services.json in the native project; without it this
           throws, which is exactly why no token was ever registered before. */
        const { data: token } = await Notifications.getDevicePushTokenAsync();

        await registerPushToken(token, Platform.OS);
        if (!cancelled) setStatus({ ready: true, token, reason: null });
      } catch (e) {
        // Expo Go on Android lands here. Not fatal: the in-app alarm list still
        // works, so the farmer is never left with no way to find out.
        if (!cancelled) setStatus({ ready: false, token: null,
          reason: `${e.message}. Alarms will still show inside the app.` });
      }
    })();

    const tapSub = Notifications.addNotificationResponseReceivedListener((resp) => {
      const data = resp?.notification?.request?.content?.data || {};
      tapRef.current?.(data);
    });

    return () => { cancelled = true; tapSub.remove(); };
  }, []);

  return status;
}
