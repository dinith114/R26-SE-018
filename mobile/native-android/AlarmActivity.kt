package lk.ac.sliit.r26se018.orchidcare

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView

/**
 * The screen a farm alarm puts in front of you, even on a locked phone.
 *
 * Why this is native rather than the React Native AlarmScreen: to take over a
 * locked device the window flags have to be set before the activity is drawn,
 * and the activity has to be launchable from a full-screen intent while the app
 * is not running at all. A JS screen cannot do either — by the time the bridge
 * is up the moment has passed, and if the app was killed there is no bridge.
 *
 * This deliberately does NOT replace the React Native AlarmScreen. That screen
 * is still where the detail and the acknowledge action live; this one wakes the
 * phone, says what is wrong in one line, and hands over to it. Keeping them
 * separate means a fault here cannot break the notification path that already
 * works.
 */
class AlarmActivity : Activity() {

  companion object {
    const val EXTRA_TITLE = "orchid_alarm_title"
    const val EXTRA_BODY = "orchid_alarm_body"
    const val EXTRA_IDS = "orchid_alarm_ids"
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    showOverLockScreen()
    setContentView(R.layout.activity_alarm)

    val title = intent?.getStringExtra(EXTRA_TITLE) ?: "Orchid Farm needs you"
    val body = intent?.getStringExtra(EXTRA_BODY) ?: "Open the app to see what is waiting."

    findViewById<TextView>(R.id.alarm_title).text = title
    findViewById<TextView>(R.id.alarm_body).text = body

    findViewById<Button>(R.id.alarm_open).setOnClickListener {
      // Hand over to the app, which has the section detail and the acknowledge
      // button. Launching by package keeps this working if MainActivity moves.
      val open = packageManager.getLaunchIntentForPackage(packageName)
      open?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
      open?.putExtra(EXTRA_IDS, intent?.getStringExtra(EXTRA_IDS))
      if (open != null) startActivity(open)
      finish()
    }

    findViewById<Button>(R.id.alarm_dismiss).setOnClickListener {
      /* Dismisses the SCREEN only.
         The alarm itself stays unacknowledged on the server and will be sent
         again — the backend repeats every 5 minutes, up to 6 times. Silencing a
         plant that still needs water by swiping a screen away would be the
         wrong behaviour, so this button says "Not now" rather than "Done". */
      finish()
    }
  }

  /** Wake the screen and show OVER the keyguard. Order matters: these must be
   *  applied before the first draw, which is why they sit above setContentView.
   *
   *  Note what is deliberately NOT here: `requestDismissKeyguard`. Asking the
   *  system to take the lock screen down starts a transition, and on the bench
   *  that fought with this activity's own launch - the task was pushed behind
   *  the launcher twice in two seconds and never got a focused window, which
   *  Android then reported as "Input dispatching timed out (Application does not
   *  have a focused window)" and killed the app with an ANR.
   *
   *  A real alarm clock shows over the lock screen and leaves you to unlock
   *  afterwards. That is both more robust and the behaviour people expect. */
  private fun showOverLockScreen() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
      setShowWhenLocked(true)
      setTurnScreenOn(true)
    } else {
      @Suppress("DEPRECATION")
      window.addFlags(
        WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
          or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
      )
    }
    window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
  }
}
