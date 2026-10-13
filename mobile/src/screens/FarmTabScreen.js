/**
 * The "My Farm" tab.
 *
 * Simple mode (default) -> TodayScreen: big text, plain words, one button.
 *                          Built for elderly, non-technical growers.
 * Expert mode           -> FarmDashboardScreen: full technical detail
 *                          (VPD, per-section readings, ML actions).
 *
 * Toggle lives in Settings.
 */
import React from 'react';
import { usePrefs } from '../config/prefs';
import TodayScreen from './TodayScreen';
import FarmDashboardScreen from './FarmDashboardScreen';

export default function FarmTabScreen(props) {
  const { expert } = usePrefs();
  return expert ? <FarmDashboardScreen {...props} /> : <TodayScreen {...props} />;
}
