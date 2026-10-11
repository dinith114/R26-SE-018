# Tenancy Cutover 2C — the mobile app

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app signs a person in, sends that person's Firebase ID token on
every request, and shows each role only the controls the server would actually
accept from them.

**Architecture:** The app already has exactly one place where credentials are
attached — `H` in `services/careV2.js`, shared by three near-identical fetch
helpers. That constant becomes an async header builder that asks the Firebase
SDK for a fresh ID token. Everything else follows from that one change. A
`PERMS` map, taken from the server's own route table, is the single statement of
who may do what, and a pytest in the existing CI suite fails if the map and the
server ever disagree.

**Tech Stack:** React Native 0.81.5 / Expo SDK 54, `firebase` 12.13.0 and
`@react-native-async-storage/async-storage` 2.2.0 — both already installed, so
2C adds no dependency.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`
("Mobile app changes")

---

## BLOCKER, measured before any code was written

**Firebase Authentication is not enabled on the `orchid-smart-care` project.**
No provider, no Identity Platform config. This is not an inference:

```
$ curl -s -X POST "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<the key in google-services.json>" \
       -d '{"email":"does-not-exist@invalid.example","password":"...","returnSecureToken":true}'
{"error":{"code":400,"message":"CONFIGURATION_NOT_FOUND"}}

$ ...same key, accounts:createAuthUri (a lookup, creates nothing)
{"error":{"code":400,"message":"CONFIGURATION_NOT_FOUND"}}

$ ...control, a deliberately invalid key
{"error":{"message":"API key not valid. Please pass a valid API key."}}
```

The control is what makes this conclusive: a bad key is rejected as a bad key,
and this key is accepted and then finds no auth configuration behind it.

**Consequences, stated plainly:**

- Every task below can be written and reviewed. **None can be verified against a
  real sign-in** until Authentication is switched on.
- Stage 1's account routes have never run against real Firebase either. Their
  tests all run behind the `set_decoder` / `set_identity_backend` seams, which is
  the right way to test our own rules, but it means `create_tenant` actually
  creating a user is still unproven.

**What settles it — a console action, and only the project owner can do it:**

1. Firebase Console, Authentication, Get started, **Email/Password, Enable**
2. Same page, Settings, User actions, **uncheck "Enable create (sign-up)"**.
   Every account here is made by an admin through the backend, which uses the
   Admin SDK and ignores that switch. Leaving public sign-up on lets a stranger
   who reads the committed `google-services.json` mint accounts in the project.
   They would get no `tenantId` claim and so reach no farm, but there is no
   reason to allow it.
3. Re-run the probe above. `EMAIL_NOT_FOUND` or `INVALID_LOGIN_CREDENTIALS`
   means it is on. `CONFIGURATION_NOT_FOUND` means it is not.

Do the console work first if you can. If you cannot, implement anyway and mark
every verification step **BLOCKED — needs Firebase Auth enabled** rather than
claiming it passed.

---

## Measured facts this plan is built on

Every number here was measured on 4 September 2026, not estimated.

```
THE CLIENT'S AUTH SURFACE IS ONE LINE
  services/careV2.js:23   const H = { 'Content-Type': ..., 'X-API-Key': API_KEY }
  used by  req()  autoReq()  devReq()   three helpers, otherwise identical
  serving  64 exported functions        29 writes via /care, 8 more via /auto and /devices
  files importing API_KEY: 2 (config/backend.js re-exports it, careV2.js uses it)

THE APP DOES NOT TOUCH THE FARM TREE DIRECTLY
  firebase/database imports outside config: 1, HybridPollinationScreen.js
  and it writes /hybridPrediction, Component 4's, not /farm/...
  So NO client-side path scoping is needed. The backend is the only farm reader.

THE SERVER'S REAL TABLE  (live introspection of app.main, not a grep)
  /api/v2 routes                     63
  require_auth (any signed-in role)  18   all reads
  role(admin, operator)              10
  role(admin)                        34
  no dependency guard                 1   POST /accounts/tenants, guarded inside
                                          the handler by the vendor key
  So every v2 write is behind a real gate. None is protected only by X-API-Key.

WHAT NEEDS ROLE-GATING IN THE UI
  files calling at least one write function   13
  SectionDetailScreen.js alone                16 write functions
  FarmDashboard 5, Today 5, FarmSetup 4, Alarm 3, HousePlanner 3, Run 3,
  AddSensor 2, Calibration 2, PlacementResult 2, AutoControls 1,
  NodePicker 1, Settings 1                    37 write call sites in total

DEPENDENCIES ARE ALREADY PRESENT
  firebase 12.13.0, @react-native-async-storage/async-storage 2.2.0
  firebase/auth is literally `export * from '@firebase/auth'`, and
  @firebase/auth declares a react-native condition pointing at dist/rn/index.js,
  which DOES export getReactNativePersistence. Metro therefore resolves the
  RN build. VERIFY THIS AT RUNTIME ANYWAY (Task 1). It is a resolution
  detail, not a promise.

FIREBASE PROJECT CONFIG IS ALREADY PUBLIC
  mobile/google-services.json is committed and holds the API key, the project
  id `orchid-smart-care` and the database URL. C:\orchid\android\app\ has the
  identical file (same sha256). Nothing new is exposed by putting the same
  values in firebase.js.
```

## Global Constraints

- **Nothing here deploys on its own.** 2A, 2B, 2C and 2D go live as one
  cutover. An app sending bearer tokens to today's server gets 401 on every
  write, because today's server has no `require_auth` on those routes.
- **Keep sending `X-API-Key`.** `app/main.py` has a middleware demanding it on
  every `/api/v2` write, and it is an ADDITIONAL gate, not an alternative one.
  Dropping it from the app breaks every write. Removing the middleware is a
  server change and belongs to the cutover, not here. Ledger it for 2D.
- **The client gate is UX, not security.** A hidden button is a courtesy; the
  403 is the control. Never let a UI check become the only thing standing
  between a viewer and a pump.
- **Never run `expo prebuild`.** It regenerates `C:\orchid\android` and wipes
  `android:usesCleartextTraffic` from the native manifest, breaking all network
  access with no diagnostic.
- **Verify `android:usesCleartextTraffic` survives every build** before
  installing, in `C:\orchid\android\app\src\main\AndroidManifest.xml`.
- The repo is PUBLIC. The backend's `ORCHID_API_KEY` stays in gitignored
  `secret.js`. The Firebase web config is a project identifier, not a secret,
  and is already committed in `google-services.json`.
- Commit messages: plain sentences, no `feat:`/`chore:`/`fix:` prefixes, ending
  with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

### Task 1: The auth module, the only file that imports `firebase/auth`

**Files:**
- Modify: `mobile/src/config/firebase.js`
- Create: `mobile/src/services/auth.js`

**Interfaces:**
- Produces: `signIn(email, password)`, `signOutNow()`, `onAuthChange(cb)`,
  `getToken({ force })`, `getClaims()`

- [ ] **Step 1: Give `firebase.js` the rest of the config**

It currently carries only `databaseURL`, which is all `getDatabase` needs. Auth
needs `apiKey`, `authDomain` and `projectId`. Take them from the committed
`mobile/google-services.json`, do not invent them:

```
apiKey      <- client[0].api_key[0].current_key
authDomain  <- "<project_id>.firebaseapp.com"
projectId   <- project_info.project_id
```

Write a comment saying why these are in git while `ORCHID_API_KEY` is not: a
Firebase web key names a project, it does not authorise anything, and this one
has been in `google-services.json` in this public repo since August. The thing
that authorises is the ID token, which is minted per person and expires.

- [ ] **Step 2: Initialise auth with persistence that survives a restart**

```js
import { initializeAuth, getReactNativePersistence } from 'firebase/auth';
import AsyncStorage from '@react-native-async-storage/async-storage';
```

`initializeAuth`, not `getAuth`: `getAuth` on React Native falls back to
in-memory persistence, and a farmer would be signed out every time the app is
killed, which on a phone is several times a day.

**Verify the import actually resolves before building anything on it:**

```bash
cd mobile && node -e "const m=require('@firebase/auth'); console.log('rn persistence:', typeof m.getReactNativePersistence)"
```

Node resolves the `node` condition, not `react-native`, so this may print
`undefined` even when Metro is fine. If it does, prove it the other way, by
checking the RN build itself:

```bash
grep -c 'getReactNativePersistence' node_modules/@firebase/auth/dist/rn/index.js
```

Put whichever output you got in your report. If `initializeAuth` throws
"already initialized" on a fast refresh, catch it and fall back to `getAuth`.

- [ ] **Step 3: The five functions, and nothing else**

`getToken({ force })` wraps `user.getIdToken(force)`. `getClaims()` wraps
`getIdTokenResult()` and returns `{ tenantId, role }` from `claims`. There is no
`/me` endpoint on the server and there does not need to be: the role is inside
the token, put there by the Admin SDK when the account was created.

Handle "signed in but no claims". A Firebase user with no `tenantId` is not a
member of any farm. Return nulls; Task 3 turns that into a dead end rather than
a redirect loop.

- [ ] **Step 4: Commit**

---

### Task 2: The chokepoint, one request function, a fresh token every call

**Files:**
- Modify: `mobile/src/services/careV2.js`

- [ ] **Step 1: Collapse the three helpers into one**

`req`, `autoReq` and `devReq` differ only in their base URL and in `devReq`
keeping `err.status` (SectionDetail reads 409 from it). Make one
`request(base, path, options)` and keep `err.status` on all of them. A status is
useful everywhere, and Task 5 needs 403 distinguishable from 401.

Three copies of the header logic is three places to forget a token.

- [ ] **Step 2: Build headers per call, not once at module load**

```js
async function authHeaders() {
  const token = await getToken();          // the SDK refreshes it if near expiry
  return {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY,                  // legacy gate, see Global Constraints
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}
```

`H` was a module-level constant, evaluated once at import. An ID token lives one
hour. A constant header would work for an hour and then fail for as long as the
app stayed open, which is the worst shape a bug can have: it works while you are
testing it.

Spread the headers first so an explicit `headers` option can still override,
exactly as `H` was spread first before.

- [ ] **Step 3: 401 refreshes once, 403 does not**

On 401: retry once with `getToken({ force: true })`. If it fails again, sign
out. The refresh token has been revoked, which is what the server does when an
admin changes or deletes an account.

On 403: **do not sign out, do not retry.** The person is correctly signed in and
is not allowed to do this. Signing them out would read as "your session
expired", teaching a viewer to re-enter a password that will not help.

Never retry a non-idempotent write beyond that one refresh. A second POST to
`/water` is a second pour.

- [ ] **Step 4: Verify the header shape without a device**

Stub `global.fetch`, call one read and one write, and print the headers each
received. Confirm `Authorization` is present, that a call after a simulated
expiry carried a different token, and that a 403 did not call sign-out. Put the
captured headers in your report with the token redacted to its first 8
characters.

- [ ] **Step 5: Commit**

---

### Task 3: The login gate

**Files:**
- Create: `mobile/src/screens/LoginScreen.js`
- Create: `mobile/src/config/auth.js`  (the provider, follow `config/prefs.js`)
- Modify: `mobile/App.js`

- [ ] **Step 1: An `AuthProvider` alongside `PrefsProvider`**

Exposes `{ user, role, tenantId, ready, signIn, signOut }`. `ready` is false
until the first `onAuthStateChanged` fires. Without it the app flashes the login
screen for a moment on every cold start for an already signed-in user.

- [ ] **Step 2: Three states in `App.js`, not two**

```
!ready                -> keep the splash up
ready && !user        -> LoginScreen
user && !tenantId     -> "This account is not set up for a farm" plus Sign out
otherwise             -> AppNavigator
```

The third state is the one that is easy to leave out and miserable to hit: a
real Firebase account with no claims. Without it the app signs in, gets 401 on
every call, and offers no way out but reinstalling.

- [ ] **Step 3: The screen itself**

Email, password, one button, one error line. Use `COLORS` from
`config/theme.js`. Errors are for the person, not the console: "That email and
password do not match an account." Never surface Firebase's own codes. They
distinguish "no such user" from "wrong password", which tells a stranger which
addresses have accounts here.

Keep the existing splash. Nothing about push registration moves; it already runs
inside the navigator, which now only mounts for a signed-in user, and that is
correct. An unregistered phone should not receive another farm's alarms.

- [ ] **Step 4: Commit**

---

### Task 4: The permission map, and a test that pins it to the server

**Files:**
- Create: `mobile/src/config/perms.js`
- Create: `backend/tests/test_mobile_perms_match_server.py`

This is the task that keeps the other twelve honest.

- [ ] **Step 1: Write the map from the server's own table**

One flat object: action name to the roles the server accepts. Not
`role === 'admin'` scattered through thirteen screens; those drift silently and
each one is a separate small lie to the user.

```js
export const PERMS = {
  waterSection:  ['admin', 'operator'],
  fillTray:      ['admin', 'operator'],
  // ...
  deleteHouse:   ['admin'],
};
export const can = (role, action) => (PERMS[action] || ['admin']).includes(role);
```

`can` defaults to admin-only for an unknown action. An action nobody thought
about should be hidden from a viewer, not shown to one.

Derive every entry from the route table in "Measured facts": read the guard off
the route, do not reason about what the action sounds like. `stopSection` is
`admin, operator`; `setNodeWifi`, on the same screen and near it in the code, is
`admin`.

- [ ] **Step 2: The test, parse the map, introspect the app, compare**

In the existing pytest suite, so it runs in CI on every push:

1. `from app.main import app`, walk `app.routes`, build
   `{(method, path): allowed_roles}`, reading `require_role`'s closure via
   `inspect.getclosurevars` exactly as this plan's own measurement did
2. read `mobile/src/config/perms.js` and extract `PERMS`. It is plain JSON-ish,
   so a regex plus `json.loads` on a normalised string is enough. If that turns
   out brittle, emit the map as `perms.json` and import it from the JS instead
3. map each action to its route via the path template in `careV2.js`
4. assert the roles agree

Fail with a message naming the action, what the app thinks, and what the server
says. If the two ever diverge, the person reading the failure needs the diff,
not a boolean.

This test is why the map is worth having. Without it the map is a second copy of
the truth that starts rotting the day someone adds a route.

- [ ] **Step 3: Run the full suite**

```bash
cd backend && python -m pytest -q
```

Report the count.

- [ ] **Step 4: Commit**

---

### Task 5: Role-gated controls, all thirteen files

**Files:**
- Modify: the 13 files listed in "Measured facts"

- [ ] **Step 1: A `useCan` hook**

`const can = useCan(); ... {can('waterSection') && <WaterButton/>}`. It reads the
role from the auth context and answers through `can()` from Task 4.

- [ ] **Step 2: Hide, do not disable**

A disabled button asks "why can't I?" on every screen, forever. A viewer should
see a calm read-only app, not a grid of things they cannot have. Where hiding
would leave a confusing hole, such as an empty action bar, put one quiet line:
"Your account has view-only access."

- [ ] **Step 3: Work file by file, largest first**

`SectionDetailScreen.js` has 16 write calls and is the real work. The other
twelve are small. Do not batch them into one edit: a missed control is a button
that 403s, and the way you find it is by looking at each one.

- [ ] **Step 4: Verify by counting, then by reading**

For each file, list every write function it calls and the gate now around it. A
write call with no gate is either a bug or a deliberate always-allowed action,
and if it is the latter, say which.

Report the total: 37 write call sites across 13 files, each either gated or
explained.

- [ ] **Step 5: Commit**

---

### Task 6: The Team screen

**Files:**
- Create: `mobile/src/screens/TeamScreen.js`
- Modify: `mobile/src/services/careV2.js` (four account calls)
- Modify: `mobile/src/navigation/AppNavigator.js`, `mobile/src/screens/SettingsScreen.js`

- [ ] **Step 1: The four calls**

`GET /accounts/users` (any role), `POST /accounts/users`,
`PUT /accounts/users/{uid}/role`, `DELETE /accounts/users/{uid}` (admin). Base
`${BASE_URL}/api/v2/accounts`, through the same `request()` from Task 2.

- [ ] **Step 2: The screen, admin only**

List of members with email and role; add a member (email, password, role);
change a role; remove a member. Reachable from Settings, and the Settings row
itself is hidden for non-admins.

Two things the server will enforce and the screen should not pretend otherwise:

- An admin cannot remove or demote themselves if they are the last admin
  (`_still_admin`). Show the server's refusal rather than second-guessing it.
- Changing a role revokes that person's refresh tokens, so they will be signed
  out. Say so on the confirm: "They will be signed out and will need to sign in
  again."

- [ ] **Step 3: A password field, said honestly**

The admin types the new member's first password and passes it on out of band.
There is no invite email; enabling one is a Firebase console feature and a
different design. Label the field so nobody waits for an email that is not
coming.

- [ ] **Step 4: Sign out in Settings**

With the signed-in email above it, so a person can see which account they are
on. Confirm before signing out: on a farm phone this is a slip that costs
someone their alarms.

- [ ] **Step 5: Commit**

---

### Task 7: Build, install, and verify what can be verified

- [ ] **Step 1: Sync source into `C:\orchid`**

Copy `mobile/` into the build tree. Do NOT run `expo prebuild`.

- [ ] **Step 2: Check the manifest BEFORE building**

```bash
grep -c 'usesCleartextTraffic' /c/orchid/android/app/src/main/AndroidManifest.xml
```

Expect 1. If it is 0, someone ran prebuild; restore it before going further.

- [ ] **Step 3: Build and check again**

```bash
cd /c/orchid/android && ./gradlew assembleRelease
```

Then re-check the manifest count, and confirm the APK exists with a real size.

- [ ] **Step 4: Install and report honestly**

If Firebase Auth is still off, the login screen will show a real error and there
is nothing more to see. Say exactly that. **Do not write "verified" anywhere a
sign-in was not actually performed.**

If Auth is on: sign in as the admin, confirm the farm loads, confirm one write
succeeds, then check that a viewer sees no Water Now. Quote what you saw.

- [ ] **Step 5: Commit and update `WORKLOG.md`**

---

## Definition of done for 2C

- one request path, one place a token is attached, `X-API-Key` still sent
- a fresh ID token per call; a 401 refreshes once then signs out; a 403 does neither
- three app states, including the no-claims dead end
- `PERMS` exists and a CI test fails if it disagrees with the server
- all 37 write call sites across 13 files gated or explained
- Team screen works for an admin and is invisible to everyone else
- the manifest still carries `usesCleartextTraffic` after the build
- every unverifiable step labelled **BLOCKED — needs Firebase Auth enabled**,
  never labelled passed

## Not in this plan

The migration and the cutover (2D), removing the `X-API-Key` middleware, closing
the Firebase rules (Stage 3), and flashing any board. Components 1, 2 and 4 keep
their own unauthenticated fetch code and their own open v1 routes; bringing them
behind this auth is separate work and not part of the cutover.
