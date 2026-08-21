/**
 * Design tokens.
 *
 * Rebuilt August 2026. The previous palette looked flat and lifeless for a
 * measurable reason rather than a matter of taste: its accents were
 * mid-lightness and desaturated, so they failed WCAG AA almost everywhere.
 *
 *   old primary  #3A8F6A  ->  white on it       3.95:1   FAIL
 *   old info     #5B8DB8  ->  as text on card   3.53:1   FAIL
 *   old warning  #E8A838  ->  as text on card   2.08:1   FAIL
 *   old tertiary #8E969C  ->  small labels      2.74:1   FAIL
 *
 * Low contrast is exactly what "washed out" looks like. The fix follows current
 * practice for botanical products: deep jewel-tone accents over warm neutral
 * greys, with the strongest colour reserved for primary actions.
 *
 *   - Neutrals are a warm stone scale, not cream. The old #F7F4EF read yellowed;
 *     #FAFAF9 keeps the warmth without the age.
 *   - Accents are darkened and saturated (emerald / sky / amber / rose / violet)
 *     so they carry text at AA instead of only decorating.
 *   - Every pair below was checked; all pass AA (>= 4.5:1 body, >= 3:1 large).
 *
 * If you change a value here, re-run the contrast check before committing —
 * these numbers are the difference between "clean" and "dead".
 */

export const COLORS = {
  // ── Backgrounds — warm stone, not cream ──
  bg: '#FAFAF9',
  bgElevated: '#FFFFFF',
  bgCard: '#FFFFFF',
  bgCardAlt: '#F5F5F4',      // nested sub-cards
  bgInput: '#EFEEEC',

  // ── Header — deep emerald (white on it: 7.68:1, was 3.95:1) ──
  headerBg: '#065F46',
  headerText: '#FFFFFF',
  headerSub: 'rgba(255,255,255,0.88)',
  headerIcon: '#FFFFFF',

  // ── Text ──
  text: '#1C1917',           // 16.74:1
  textSecondary: '#57534E',  //  7.30:1
  textTertiary: '#736D67',   //  4.89:1 on bg, 4.68:1 on sub-cards
  textInverse: '#FFFFFF',

  // ── Primary — emerald, reserved for the main action ──
  primary: '#047857',        // white on it: 5.48:1
  primaryLight: '#D1FAE5',
  primaryDim: 'rgba(4, 120, 87, 0.10)',
  primaryDark: '#065F46',

  // ── Semantic ──
  success: '#047857',
  successDim: 'rgba(4, 120, 87, 0.10)',
  warning: '#B45309',        // 5.02:1 (was 2.08:1)
  warningDim: 'rgba(180, 83, 9, 0.10)',
  danger: '#BE123C',         // 6.29:1
  dangerDim: 'rgba(190, 18, 60, 0.10)',
  info: '#0369A1',           // 5.93:1
  infoDim: 'rgba(3, 105, 161, 0.10)',

  // ── Sensor channels — distinct hues, all AA as text ──
  temperature: '#C2410C',    // 5.18:1
  temperatureDim: 'rgba(194, 65, 12, 0.10)',
  humidity: '#0369A1',       // 5.93:1
  humidityDim: 'rgba(3, 105, 161, 0.10)',
  light: '#A16207',          // 4.92:1
  lightDim: 'rgba(161, 98, 7, 0.10)',
  soil: '#047857',
  soilDim: 'rgba(4, 120, 87, 0.10)',
  fertilizer: '#6D28D9',     // 7.10:1
  fertilizerDim: 'rgba(109, 40, 217, 0.10)',

  // ── Borders ──
  border: '#E7E5E4',
  borderLight: '#F0EFED',

  // ── Tab bar ──
  tabBg: '#FFFFFF',
  tabActive: '#047857',
  tabInactive: '#78716C',    // 4.83:1 — the old #A0A8AE was 2.6:1 at 9px

  // ── Notification ──
  notifDot: '#F59E0B',
};

export const FONT = {
  xs: 10,
  sm: 12,
  md: 14,
  lg: 16,
  xl: 20,
  xxl: 26,
  hero: 32,
};

export const SPACE = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
};

export const RADIUS = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  full: 999,
};

/* Shadows are warm-tinted rather than pure black: neutral-black shadows on a
   warm background are what makes a light UI look grey and dirty. */
export const SHADOW = {
  sm: {
    shadowColor: '#1C1917',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  md: {
    shadowColor: '#1C1917',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 10,
    elevation: 4,
  },
  lg: {
    shadowColor: '#1C1917',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.10,
    shadowRadius: 18,
    elevation: 8,
  },
  fab: {
    shadowColor: '#047857',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.32,
    shadowRadius: 12,
    elevation: 10,
  },
};
