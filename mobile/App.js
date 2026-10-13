import React, { useState, useCallback, useRef } from 'react';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import SplashScreen from './src/screens/SplashScreen';
import AppNavigator from './src/navigation/AppNavigator';
import { PrefsProvider } from './src/config/prefs';
import usePushAlarms from './src/hooks/usePushAlarms';
import { COLORS } from './src/config/theme';

export default function App() {
  const [isLoading, setIsLoading] = useState(true);
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

  /* Registers this phone for alarms and routes a tapped notification straight
     to the thing that needs doing, rather than dumping the farmer on the home
     screen to hunt for it. */
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

  if (isLoading) {
    return (
      <View style={styles.container}>
        <SplashScreen onFinish={onSplashFinish} />
        <StatusBar style="dark" />
      </View>
    );
  }

  return (
    <PrefsProvider>
      <View style={styles.container}>
        <AppNavigator navRef={navRef} onReady={onNavReady} />
        <StatusBar style="dark" />
      </View>
    </PrefsProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.bg,
  },
});
