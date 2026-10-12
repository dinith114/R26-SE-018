/**
 * The one place a credential is attached to a request.
 *
 * DELIBERATELY IMPORTS NOTHING. Every dependency - how to get a token, how to
 * sign out, the legacy key, even fetch - is handed in. That is not ceremony:
 * careV2.js pulls in react-native, the theme and the Firebase SDK, so anything
 * living inside it can only be tested on a device. This file can be tested in
 * plain Node in a few milliseconds, and what it decides (when to refresh, when
 * to sign out, when to do neither) is the part that must not be wrong.
 *
 * See __tests__/request.test.mjs.
 */

/**
 * @param getToken   ({force}) => Promise<string|null>
 * @param signOutNow () => Promise<void>
 * @param apiKey     the legacy X-API-Key, still required by the backend
 *                   middleware on every /api/v2 write
 * @param fetchImpl  injected for the tests; defaults to the global
 */
export function makeRequest({ getToken, signOutNow, apiKey, fetchImpl }) {
  const doFetch = fetchImpl || ((...a) => fetch(...a));

  function headers(token) {
    return {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  async function fire(base, path, options, hdrs) {
    /* Headers spread AFTER options so they are not silently dropped by a caller
       passing its own `headers`; a request that quietly loses its Authorization
       header is a 401 nobody can explain. Callers that genuinely need to add a
       header should be given a way to merge, not to replace. */
    const res = await doFetch(`${base}${path}`, { ...options, headers: hdrs });
    if (res.ok) return { res, json: await res.json() };
    let detail = `Server error ${res.status}`;
    try {
      const j = await res.json();
      if (j && j.detail) detail = j.detail;
    } catch (_) { /* not JSON; the status line is all we have */ }
    return { res, detail };
  }

  /**
   * 401 and 403 mean different things and must be treated differently.
   *
   * 401 is "I do not know who you are": the token expired, or an admin revoked
   * this account's refresh tokens by changing its role or deleting it. Forcing
   * a refresh separates those - the first returns a new token, the second
   * fails - so it is worth exactly one retry, and only then a sign-out.
   *
   * 403 is "I know who you are and you may not do this". The person is
   * correctly signed in. Signing them out would read as "your session expired"
   * and teach a viewer to re-enter a password that cannot help. No retry, no
   * sign-out.
   *
   * At most one retry, and only behind a forced refresh, because a blind retry
   * of POST /water is a second pour.
   */
  return async function request(base, path, options = {}) {
    const first = await getToken();
    let out = await fire(base, path, options, headers(first));

    if (out.res.status === 401) {
      /* No token at all means nobody is signed in - the app is mid sign-out, or
         a screen fired during the transition. Nothing to refresh, and calling
         signOut again would be pointless. Let it surface as a 401. */
      if (first !== null && first !== undefined) {
        let fresh = null;
        try { fresh = await getToken({ force: true }); } catch (_) { fresh = null; }
        if (fresh) out = await fire(base, path, options, headers(fresh));
        if (out.res.status === 401) {
          /* Either the refresh failed or a freshly minted token was still
             refused. Both mean this account can no longer act. */
          try { await signOutNow(); } catch (_) { /* already gone */ }
        }
      }
    }

    if (!out.res.ok) {
      const err = new Error(out.detail);
      /* On every path, not only devices. 409 is the one-to-one device rule, and
         403 has to be distinguishable from 401 by the screens. */
      err.status = out.res.status;
      throw err;
    }
    return out.json;
  };
}
