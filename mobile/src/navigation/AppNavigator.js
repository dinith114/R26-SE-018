import React, { useRef, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Animated, Platform } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, SHADOW } from '../config/theme';

import HomeScreen from '../screens/HomeScreen';
import DiseaseDetectionScreen from '../screens/DiseaseDetectionScreen';
import GrowthStageScreen from '../screens/GrowthStageScreen';
import HybridPollinationScreen from '../screens/HybridPollinationScreen';
import SettingsScreen from '../screens/SettingsScreen';
import NotificationsScreen from '../screens/NotificationsScreen';
import FarmDashboardScreen from '../screens/FarmDashboardScreen';
import FarmTabScreen from '../screens/FarmTabScreen';
import SectionDetailScreen from '../screens/SectionDetailScreen';
import RunScreen from '../screens/RunScreen';
import AlarmScreen from '../screens/AlarmScreen';
import HousePlannerScreen from '../screens/HousePlannerScreen';
import FarmSetupScreen from '../screens/FarmSetupScreen';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

const TabIcon = ({ focused, iconName, iconNameOutline, label }) => {
  const scale = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    Animated.spring(scale, { toValue: focused ? 1.05 : 1, tension: 120, friction: 8, useNativeDriver: true }).start();
  }, [focused]);

  return (
    <Animated.View style={[styles.tabItem, { transform: [{ scale }] }]}>
      <Ionicons name={focused ? iconName : iconNameOutline} size={21} color={focused ? COLORS.tabActive : COLORS.tabInactive} />
      <Text style={[styles.tabLabel, focused && styles.tabLabelActive]}>{label}</Text>
    </Animated.View>
  );
};

const HomeFAB = ({ onPress, focused }) => {
  const scale = useRef(new Animated.Value(1)).current;
  const handlePress = () => {
    Animated.sequence([
      Animated.timing(scale, { toValue: 0.88, duration: 60, useNativeDriver: true }),
      Animated.spring(scale, { toValue: 1, tension: 100, friction: 6, useNativeDriver: true }),
    ]).start();
    onPress();
  };

  return (
    <TouchableOpacity onPress={handlePress} activeOpacity={0.85} style={styles.fabOuter}>
      <Animated.View style={[styles.fab, SHADOW.fab, { transform: [{ scale }] }]}>
        <Ionicons name={focused ? 'grid' : 'grid-outline'} size={22} color="#FFF" />
      </Animated.View>
    </TouchableOpacity>
  );
};

function CustomTabBar({ state, descriptors, navigation }) {
  const tabConfig = {
    Farm: { icon: 'business', outline: 'business-outline', label: 'My Farm' },
    Disease: { icon: 'search', outline: 'search-outline', label: 'Detect' },
    Home: null,
    Hybrid: { icon: 'git-merge', outline: 'git-merge-outline', label: 'Hybrid' },
    Growth: { icon: 'leaf', outline: 'leaf-outline', label: 'Growth' },
  };

  return (
    <View style={[styles.barOuter, SHADOW.lg]}>
      <View style={styles.bar}>
        {state.routes.map((route, index) => {
          const focused = state.index === index;
          const onPress = () => { if (!focused) navigation.navigate(route.name); };

          if (route.name === 'Home') {
            return <HomeFAB key={route.key} onPress={onPress} focused={focused} />;
          }
          const cfg = tabConfig[route.name];
          if (!cfg) return null;

          return (
            <TouchableOpacity key={route.key} onPress={onPress} activeOpacity={0.7} style={styles.tabBtn}>
              <TabIcon focused={focused} iconName={cfg.icon} iconNameOutline={cfg.outline} label={cfg.label} />
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

function MainTabs() {
  /* initialRouteName is explicit because a tab navigator otherwise opens on its
     FIRST declared screen, which put the app on the farm's section list. Home is
     the dashboard - today's plan, alerts and quick nav - and is the centre tab,
     so landing anywhere else made the tab bar look mis-selected on launch. The
     declaration order below is left alone: it sets the left-to-right order of
     the tabs themselves. */
  return (
    <Tab.Navigator
      initialRouteName="Home"
      tabBar={(props) => <CustomTabBar {...props} />}
      screenOptions={{ headerShown: false }}>
      <Tab.Screen name="Farm" component={FarmTabScreen} />
      <Tab.Screen name="Disease" component={DiseaseDetectionScreen} />
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Hybrid" component={HybridPollinationScreen} />
      <Tab.Screen name="Growth" component={GrowthStageScreen} />
    </Tab.Navigator>
  );
}

/* `navRef` and `onReady` come from App.js, which routes a tapped notification.
   This used to take NO props at all while App.js passed `navRef={navRef}`, so
   the ref was never attached, navRef.current stayed null forever, and every
   `navRef.current?.navigate(...)` was silently swallowed by the optional chain.
   Tapping any notification did nothing. */
export default function AppNavigator({ navRef, onReady }) {
  return (
    <NavigationContainer ref={navRef} onReady={onReady}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="MainTabs" component={MainTabs} />
        <Stack.Screen name="Settings" component={SettingsScreen} />
        <Stack.Screen name="Notifications" component={NotificationsScreen} />
        <Stack.Screen name="FarmDashboard" component={FarmDashboardScreen} />
        <Stack.Screen name="SectionDetail" component={SectionDetailScreen} />
        <Stack.Screen name="Run" component={RunScreen} />
        <Stack.Screen name="Alarm" component={AlarmScreen} />
        <Stack.Screen name="FarmSetup" component={FarmSetupScreen} />
        <Stack.Screen name="HousePlanner" component={HousePlannerScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  barOuter: { position: 'absolute', bottom: 0, left: 0, right: 0 },
  bar: {
    flexDirection: 'row', backgroundColor: COLORS.tabBg,
    height: Platform.OS === 'ios' ? 82 : 64,
    paddingBottom: Platform.OS === 'ios' ? 18 : 4, paddingTop: 8,
    alignItems: 'center', borderTopWidth: 1, borderTopColor: 'rgba(0,0,0,0.04)',
  },
  tabBtn: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  tabItem: { alignItems: 'center', justifyContent: 'center' },
  tabLabel: { fontSize: 9, color: COLORS.tabInactive, fontWeight: '600', marginTop: 2, letterSpacing: 0.3 },
  tabLabelActive: { color: COLORS.tabActive, fontWeight: '700' },
  fabOuter: { flex: 1, alignItems: 'center', justifyContent: 'center', marginTop: -24 },
  fab: { width: 52, height: 52, borderRadius: 16, backgroundColor: COLORS.primary, alignItems: 'center', justifyContent: 'center' },
});
