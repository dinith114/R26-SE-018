# Native Android sources (alarm lock-screen takeover)

These files are **not** built from this folder. They are the repo's copy of code
that has to live inside the prebuilt Android project at `C:\orchid`, which is not
itself in version control.

They exist so the work is not lost. `C:\orchid\android` is generated, and the one
command that would regenerate it — `expo prebuild` — is **banned on this project**
(it wipes `android:usesCleartextTraffic` from the native manifest and breaks all
network access with no diagnostic).

## Where each file goes

| File | Destination under `C:\orchid\android\app\src\main\` |
|---|---|
| `AlarmActivity.kt` | `java/lk/ac/sliit/r26se018/orchidcare/` |
| `OrchidMessagingService.kt` | `java/lk/ac/sliit/r26se018/orchidcare/` |
| `activity_alarm.xml` | `res/layout/` |

## The manifest and gradle changes that go with them

Copying the files alone is not enough. `AndroidManifest.xml` also needs:

- permissions `USE_FULL_SCREEN_INTENT`, `WAKE_LOCK`, `DISABLE_KEYGUARD`
- an `<activity android:name=".AlarmActivity">` with `showOnLockScreen`,
  `turnScreenOn`, `excludeFromRecents`, a distinct
  `taskAffinity="lk.ac.sliit.r26se018.orchidcare.alarm"`, and **critically**
  `android:process=":alarm"`

  The separate process is not optional. Sharing one with React Native means
  sharing a main thread, and if RN is busy the alarm window cannot take focus —
  Android kills it with *"Input dispatching timed out (Application does not have
  a focused window)"*. That is exactly what happened on the first build.
- a `<service android:name=".OrchidMessagingService">` with an intent-filter for
  `com.google.firebase.MESSAGING_EVENT` at the **default** priority — Expo
  declares its own at `-1` so an app can take precedence.

And `app/build.gradle` needs:

```gradle
implementation("com.google.firebase:firebase-messaging:24.0.1")
implementation("androidx.core:core-ktx:1.13.1")
```

Without the first, the build fails with *Unresolved reference 'RemoteMessage'*:
expo-notifications declares firebase-messaging as `implementation`, so it is on
the runtime classpath but not on ours at compile time. Pin it to the version
expo-notifications already resolves so only one copy is present.

## The backend half

`OrchidMessagingService` only ever runs for **data-only** messages. A message
carrying a `notification` block is drawn by the system and `onMessageReceived` is
never called while the app is backgrounded or dead — which is exactly when an
alarm matters. `automation.py` sends alarms with `_send_push(..., alarm=True)`,
which drops the notification block and moves title/body into the data payload.

**These two halves must move together.** Native side present but `alarm=True`
removed → alarms go back to ordinary notifications (harmless). `alarm=True`
present but native side missing → **alarms are silent**, because nothing handles
a data-only message.

Test the path with `POST /api/v2/auto/push/test?alarm=true`.
