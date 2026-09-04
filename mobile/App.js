import React, { useState, useCallback, useRef } from 'react';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import SplashScreen from './src/screens/SplashScreen';
import AppNavigator from './src/navigation/AppNavigator';
import LoginScreen from './src/screens/LoginScreen';
import NoFarmScreen from './src/screens/NoFarmScreen';
import { PrefsProvider } from './src/config/prefs';
import { AuthProvider, useAuth } from './src/config/auth';
import usePushAlarms from './src/hooks/usePushAlarms';
import { COLORS } from './src/config/theme';

export default function App() {
  /* AuthProvider wraps the splash too, so restoring the stored sign-in runs
     alongside the splash animation instead of after it. On a normal cold start
     the read from AsyncStorage finishes long before the animation does, and the
     "waiting for auth" branch below is never seen. */
  return (
    <AuthProvider>
      <PrefsProvider>
        <Root />
      </PrefsProvider>
    </AuthProvider>
  );
}

/**
 * Registers this phone for alarms and routes a tapped notification to the thing
 * that needs doing.
 *
 * A component rather than a hook call in Root, because it must run ONLY for a
 * signed-in member of a farm, and a hook cannot be called conditionally.
 * Registering the token needs a bearer token; doing it from the login screen
 * would 401, and would also mean a phone that never signed in was subscribed to
 * alarms it has no right to see.
 */
function PushAlarms({ go }) {
  usePushAlarms(
    useCallback((data) => {
      /* An ALARM is a different thing from a notification. It was raised
         because something needs doing, it is repeating until acknowledged, and
         the farmer's first question on being woken by it is "why". So it opens
         the Alarm screen, which answers that and carries the two buttons that
         end it - do the thing, or acknowledge.

         Anything else keeps the old behaviour: straight to the section it is
         about, or the notification list. */
      if (data?.action) {
        // Sent as a JSON string, because FCM data values are always strings.
        let ids = null;
        try { ids = data.alarmIds ? JSON.parse(data.alarmIds) : null; }
        catch (_) { ids = null; }
        go('Alarm', { alarmIds: ids });
      } else if (data?.houseId && data?.sectionId) {
        go('SectionDetail', { houseId: data.houseId, sectionId: data.sectionId });
      } else {
        go('Notifications');
      }
    }, [go]),
  );
  return null;
}

function Root() {
  const [isLoading, setIsLoading] = useState(true);
  const { user, tenantId, ready } = useAuth();
  const navRef = useRef(null);
  const pendingNav = useRef(null);

  const onSplashFinish = useCallback(() => setIsLoading(false), []);

  /* Navigate, even if the tap arrived before there was anything to navigate.

     On a cold start the splash screen is up and AppNavigator is not mounted at
     all, so a notification tapped from a killed app has nowhere to go yet.
     Dropping it is not acceptable - that tap is the farmer answering an alarm.
     So it is remembered and replayed the moment navigation reports ready.

     The previous comment here claimed dropping the tap was safe because the ref
     was null "until navigation is ready". It was null ALWAYS: AppNavigator took
     no props and never attached the ref, so this dropped every tap forever. */
  const go = useCallback((name, params) => {
    if (navRef.current?.isReady()) navRef.current.navigate(name, params);
    else pendingNav.current = { name, params };
  }, []);

  const onNavReady = useCallback(() => {
    const p = pendingNav.current;
    pendingNav.current = null;
    if (p) navRef.current?.navigate(p.name, p.params);
  }, []);

  if (isLoading) {
    return (
      <View style={styles.container}>
        <SplashScreen onFinish={onSplashFinish} />
        <StatusBar style="dark" />
      </View>
    );
  }

  /* Four states, not two.

     `ready` false is the rare case where the splash finished before the stored
     sign-in was read back. Showing the login screen for that frame would flash
     it at somebody who is already signed in, so hold the empty background.

     `user && !tenantId` is the one that is easy to forget: a real Firebase
     account whose claims were never stamped. It signs in fine and then 401s on
     everything, so it needs a dead end, not the dashboard. */
  if (!ready) {
    return (
      <View style={styles.container}>
        <StatusBar style="dark" />
      </View>
    );
  }

  if (!user) {
    return (
      <View style={styles.container}>
        <LoginScreen />
        <StatusBar style="dark" />
      </View>
    );
  }

  if (!tenantId) {
    return (
      <View style={styles.container}>
        <NoFarmScreen />
        <StatusBar style="dark" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <PushAlarms go={go} />
      <AppNavigator navRef={navRef} onReady={onNavReady} />
      <StatusBar style="dark" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },
});
