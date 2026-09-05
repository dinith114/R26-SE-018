/**
 * Who is using this phone.
 *
 * THE ONLY MODULE THAT IMPORTS firebase/auth. Everything else asks here, the
 * same way the backend keeps every token check inside firebase_auth.py. One
 * door means one place to look when a sign-in misbehaves, and one place that
 * has to be right.
 *
 * Identity rides on Firebase CUSTOM CLAIMS. When an admin creates an account
 * the backend stamps `tenantId` and `role` onto it with the Admin SDK, so both
 * arrive inside the signed ID token. The app never asks the server "who am I" -
 * there is no /me endpoint and there does not need to be, because the answer is
 * already in the token and cannot be edited by the phone holding it.
 *
 * A token lives one hour. Never cache one: ask for it per request and let the
 * SDK decide whether to refresh. See services/careV2.js.
 */
import {
  initializeAuth,
  getAuth,
  getReactNativePersistence,
  signInWithEmailAndPassword,
  signOut as fbSignOut,
  onAuthStateChanged,
} from 'firebase/auth';
import AsyncStorage from '@react-native-async-storage/async-storage';
import app from '../config/firebase';

/* initializeAuth, NOT getAuth.
 *
 * getAuth on React Native falls back to in-memory persistence: the sign-in
 * survives until the process dies, which on a phone is whenever Android wants
 * the memory. A grower would be asked for a password several times a day, and
 * the alarm they are being woken by is behind that password.
 *
 * getReactNativePersistence is not listed in firebase/auth's TypeScript
 * typings, which lists the web build's exports. It is present at runtime:
 * `firebase/auth` is literally `export * from '@firebase/auth'`, and
 * @firebase/auth declares a react-native condition resolving to dist/rn/index.js,
 * whose line 238 is `exports.getReactNativePersistence = ...`. Verified by
 * loading that build directly, 4 Sep 2026. This is a plain JS project so there
 * is no type error either way.
 *
 * The catch is for Fast Refresh, which re-runs this module against an app that
 * already has an auth instance. That throws auth/already-initialized, and the
 * right answer is the instance that already exists.
 */
let auth;
try {
  auth = initializeAuth(app, {
    persistence: getReactNativePersistence(AsyncStorage),
  });
} catch (e) {
  auth = getAuth(app);
}

export { auth };

/** Sign in, or throw. Callers turn the throw into one sentence for a person. */
export async function signIn(email, password) {
  const cred = await signInWithEmailAndPassword(auth, email.trim(), password);
  return cred.user;
}

export function signOutNow() {
  return fbSignOut(auth);
}

/** Fires immediately with the restored user (or null), then on every change. */
export function onAuthChange(cb) {
  return onAuthStateChanged(auth, cb);
}

/**
 * A usable ID token, or null when nobody is signed in.
 *
 * `force` re-mints it. Used exactly once, by the 401 retry: a token can be
 * rejected because it is stale, and it can be rejected because an admin revoked
 * the account's refresh tokens. Forcing distinguishes them - the first comes
 * back with a new token, the second throws, and only the second is a sign-out.
 */
export async function getToken({ force = false } = {}) {
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken(force);
}

/**
 * The tenant and role from the token's custom claims.
 *
 * Both null means one of two things, and the app must handle it rather than
 * retrying: a Firebase account that no admin has ever added to a farm, or one
 * whose claims were never written because provisioning failed half way. Either
 * way this account cannot reach any farm and no amount of signing in again will
 * change that.
 */
export async function getClaims({ force = false } = {}) {
  const user = auth.currentUser;
  if (!user) return { tenantId: null, role: null, email: null };
  const res = await user.getIdTokenResult(force);
  const c = res.claims || {};
  return {
    tenantId: c.tenantId || null,
    role: c.role || null,
    email: user.email || null,
  };
}
