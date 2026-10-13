package lk.ac.sliit.r26se018.orchidcare

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.RemoteMessage
import expo.modules.notifications.service.ExpoFirebaseMessagingService

/**
 * Intercepts farm ALARMS so they can take over a locked screen, and leaves
 * every other notification to Expo untouched.
 *
 * Two things make this necessary:
 *
 *  1. A full-screen intent can only be attached by the code that builds the
 *     notification, and expo-notifications does not expose it.
 *  2. FCM only calls onMessageReceived for a *data-only* message while the app
 *     is backgrounded or dead. A message carrying a `notification` block is
 *     drawn by the system and this class never runs — which is exactly the
 *     state a farmer is in at 6am. So the backend sends alarms as data-only and
 *     the notification is built here.
 *
 * Expo declares its own service at intent-filter priority -1 specifically so an
 * app can put itself in front; this one takes the default priority and calls
 * super for anything that is not an alarm, so the ordinary notification path is
 * unchanged.
 */
class OrchidMessagingService : ExpoFirebaseMessagingService() {

  companion object {
    private const val CHANNEL_ID = "farm-alarm-v3"   // must match usePushAlarms.js
    private const val NOTIF_ID = 4610
  }

  override fun onMessageReceived(remoteMessage: RemoteMessage) {
    val data = remoteMessage.data
    if (data["alarm"] != "1") {
      super.onMessageReceived(remoteMessage)         // business as usual
      return
    }
    showAlarm(
      title = data["title"] ?: "Orchid Farm needs you",
      body = data["body"] ?: "Open the app to see what is waiting.",
      ids = data["alarmIds"] ?: "",
    )
  }

  private fun showAlarm(title: String, body: String, ids: String) {
    ensureChannel()

    val full = Intent(this, AlarmActivity::class.java).apply {
      /* NEW_TASK only. CLEAR_TASK was tearing the task down and rebuilding it
         as the activity was trying to take focus, which contributed to the ANR
         described in AlarmActivity. singleTop in the manifest already stops a
         repeat alarm from stacking copies. */
      addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      putExtra(AlarmActivity.EXTRA_TITLE, title)
      putExtra(AlarmActivity.EXTRA_BODY, body)
      putExtra(AlarmActivity.EXTRA_IDS, ids)
    }
    val pending = PendingIntent.getActivity(
      this, 0, full,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    val n = NotificationCompat.Builder(this, CHANNEL_ID)
      .setSmallIcon(R.mipmap.ic_launcher)
      .setContentTitle(title)
      .setContentText(body)
      .setStyle(NotificationCompat.BigTextStyle().bigText(body))
      .setPriority(NotificationCompat.PRIORITY_MAX)
      .setCategory(NotificationCompat.CATEGORY_ALARM)
      .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
      .setAutoCancel(true)
      .setContentIntent(pending)
      /* The whole point. On a locked or sleeping phone Android launches the
         activity; on an unlocked one it falls back to a heads-up notification,
         which is the behaviour that already worked. `true` marks it as a
         genuine high-priority alert. */
      .setFullScreenIntent(pending, true)
      .build()

    (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
      .notify(NOTIF_ID, n)
  }

  /** The JS side normally creates this channel, but it has only run if the app
   *  has been opened since install. A channel that does not exist means a
   *  notification that is silently dropped, so it is created here too. Android
   *  ignores the second creation, and settings are frozen at the first — which
   *  is why the id carries a version. */
  private fun ensureChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    if (mgr.getNotificationChannel(CHANNEL_ID) != null) return

    val channel = NotificationChannel(
      CHANNEL_ID, "Farm alarms", NotificationManager.IMPORTANCE_HIGH,
    ).apply {
      description = "Watering and tray alerts that need you to act"
      enableVibration(true)
      vibrationPattern = longArrayOf(0, 500, 250, 500, 250, 500, 250, 500)
      setBypassDnd(true)
      lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
      setSound(
        Uri.parse("android.resource://$packageName/raw/farm_alarm"),
        AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_ALARM)
          .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
          .build(),
      )
    }
    mgr.createNotificationChannel(channel)
  }
}
