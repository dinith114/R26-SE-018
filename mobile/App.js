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

  const onSplashFinish = useCallback(() => setIsLoading(false), []);

  /* Registers this phone for alarms and routes a tapped notification straight
     to the thing that needs doing, rather than dumping the farmer on the home
     screen to hunt for it. Safe to call before navigation is ready: the ref is
     null until then and the tap is simply ignored. */
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
        navRef.current?.navigate('Alarm', { alarmIds: ids });
      } else if (data?.houseId && data?.sectionId) {
        navRef.current?.navigate('SectionDetail', {
          houseId: data.houseId, sectionId: data.sectionId,
        });
      } else {
        navRef.current?.navigate('Notifications');
      }
    }, []),
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
        <AppNavigator navRef={navRef} />
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
