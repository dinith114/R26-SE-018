/**
 * Who is signed in, for the whole app.
 *
 * Follows PrefsProvider's shape deliberately: a provider, a hook, and a `ready`
 * flag that is false until the stored state has been read back. Without `ready`
 * the app would show the login screen for a frame on every cold start, even for
 * someone who never signed out - the sign-in is restored from disk, and that
 * takes a tick.
 *
 * `role` and `tenantId` come from the ID token's custom claims, not from a
 * request. The backend stamps them on the account with the Admin SDK, so they
 * arrive already signed and the phone cannot edit them. That is also why there
 * is no /me endpoint to call.
 */
import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { onAuthChange, getClaims, signIn as fbSignIn, signOutNow } from '../services/auth';

const AuthContext = createContext({
  user: null, role: null, tenantId: null, email: null,
  ready: false, signIn: async () => {}, signOut: async () => {},
});

export function AuthProvider({ children }) {
  const [user,     setUser]     = useState(null);
  const [claims,   setClaims]   = useState({ tenantId: null, role: null, email: null });
  const [ready,    setReady]    = useState(false);

  useEffect(() => {
    /* Fires once with the restored user (or null), then on every change -
       including the sign-out that request.js triggers when a token is refused
       for good. So a revoked account lands on the login screen without any
       screen having to handle it. */
    const unsub = onAuthChange(async (u) => {
      setUser(u);
      if (u) {
        try {
          setClaims(await getClaims());
        } catch (_) {
          /* The token could not be read. Treat it as no claims rather than
             guessing at a role - App.js has a state for exactly this. */
          setClaims({ tenantId: null, role: null, email: u.email || null });
        }
      } else {
        setClaims({ tenantId: null, role: null, email: null });
      }
      setReady(true);
    });
    return unsub;
  }, []);

  const signIn = useCallback(async (email, password) => {
    await fbSignIn(email, password);
    /* Claims are not read here. onAuthChange fires for this sign-in and reads
       them once; doing it in both places means two reads and a race over which
       one lands last. */
  }, []);

  const signOut = useCallback(() => signOutNow(), []);

  return (
    <AuthContext.Provider value={{
      user,
      role: claims.role,
      tenantId: claims.tenantId,
      email: claims.email,
      ready,
      signIn,
      signOut,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
