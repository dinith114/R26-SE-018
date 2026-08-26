/**
 * Where the backend lives. THE ONLY PLACE THIS IS WRITTEN DOWN.
 *
 * It used to be copied into ten files — three service modules and seven screens,
 * each with its own `http://192.168.1.129:8000`. Moving the laptop to a
 * different network meant editing all ten, and missing one produced the worst
 * kind of bug: a single screen failing silently while everything else worked.
 *
 * Change `HOST` here and the whole app follows.
 *
 * `node preflight.js` prints this machine's current IPv4.
 */
import { Platform } from 'react-native';

/* The laptop's address on the farm Wi-Fi, or a public hostname once the backend
   is hosted. Include the scheme and port; no trailing slash.
     LAN      →  'http://192.168.1.129:8000'
     hosted   →  'https://api.example.com'      (port implied by https)
     USB      →  'http://localhost:8000'        (needs: adb reverse tcp:8000 tcp:8000) */
const HOST = 'https://orchidfarm.duckdns.org';

/* localhost on a phone means the phone, so it is only ever right for the web
   build — or over an adb reverse tunnel, which is what HOST would say. */
const WEB_HOST = 'http://localhost:8000';

export const BASE_URL = Platform.OS === 'web' ? WEB_HOST : HOST;

/** True once the backend is reached over TLS. The native manifest still carries
 *  `android:usesCleartextTraffic` purely because HOST is plain http on a LAN
 *  address; when this is true that exception can be removed. */
export const IS_SECURE = BASE_URL.startsWith('https://');

export default BASE_URL;
