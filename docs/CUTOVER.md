# The tenancy cutover

**One day, seven steps, and a rollback for each.** Four pieces of this system
were changed separately and go live together: the backend reads
`/tenants/{t}/farm/...` instead of `/farm/...`, the board writes there, the bench
writes there, and the app sends a person's token instead of a shared key. Any one
of them alone takes the farm dark.

Read this whole page before starting. `docs/CUTOVER_REFLASH.md` is step 4 in
detail.

---

## Before the day

- [ ] **Firebase Authentication is enabled.** As of 4 September 2026 it is not,
      and until it is, nobody can sign in to anything. Console → Authentication
      → Get started → Email/Password → Enable. Then Settings → User actions →
      uncheck **Enable create (sign-up)**: every account is made by an admin
      through the backend, which uses the Admin SDK and ignores that switch, so
      leaving public sign-up on only lets a stranger who reads the committed
      `google-services.json` mint accounts nobody wants.
- [ ] **Prove it, do not assume it.** A valid key with no auth behind it answers
      `CONFIGURATION_NOT_FOUND`, and an invalid key answers `API key not valid`
      — so the second is the control that tells you which problem you have:

      curl -s -X POST "https://identitytoolkit.googleapis.com/v1/accounts:createAuthUri?key=<key from mobile/google-services.json>" \
        -H 'Content-Type: application/json' \
        -d '{"identifier":"probe@invalid.example","continueUri":"http://localhost"}'

      `EMAIL_NOT_FOUND` or an empty result means it is on. This creates nothing.
- [ ] 2A, 2B, 2C are all merged and CI is green
- [ ] The previous backend commit and the previous APK are to hand. They are the
      rollback for steps 3 and 6, and neither can be rebuilt quickly on the day.
- [ ] Keep the current `.ino`. It is the rollback for step 4.

## On the day

- [ ] **After 09:00 farm time.** The engine plans at 05:00 and waters 06:00–09:00.
      A farm mid-cutover inside that window misses the day's watering, and Vanda
      need it daily.
- [ ] **Auto OFF.** The system keeps watching, deciding and alarming; it stops
      acting. Nothing can fire while a board is out.

---

## The seven steps

### 1 · Copy the data — 2 minutes

```bash
cd backend
python -m scripts.migrate_to_tenant                        # dry run, reads only
python -m scripts.migrate_to_tenant --tenant <id> --copy   # after step 2 gives you the id
```

Chicken and egg: the copy needs the tenant id, and the id comes from step 2. So
in practice **run step 2 first** and step 1 second — the numbering here is the
logical order, and this is the one place to depart from it. The dry run is worth
doing before either, because it tells you the size of what is about to move.

Measured 4 September 2026: 17 jobs, 8.29 MB, **101 seconds**. Every write is read
back before the next starts.

**Rollback:** `DELETE /tenants/{id}.json`. Nothing else has changed; `/farm` was
never touched.

### 2 · Mint the tenant and the admin account

```bash
cd backend
ORCHID_API_KEY=<the vendor key> python -m scripts.provision_first_tenant \
    --name "Orchid Farm" --email <owner@example.com>
```

It prints the tenant id in a box. **Write it down.** It goes into three places
and they must match exactly:

1. `firmware/sensor_node_validate/sensor_node_validate.ino` → `#define TENANT_ID`
2. `NODE_SIMULATOR.html` → the tenant field in the header bar
3. `--tenant` on the migration script

A transcription error in any of them is a farm writing where nothing reads, and
it looks exactly like healthy hardware.

**Rollback:** delete `/tenants/{id}.json` and remove the auth user in the
Firebase console. The route rolls back its own partial writes; it cannot undo a
console step or an email that already had an account.

### 3 · Deploy the backend

From here the API reads the **new** tree and the board is still writing the
**old** one. **This opens the dark window.** Nothing is lost in it — readings
still land in `/farm` — they are simply not read until step 4 closes it.

The window is however long steps 4 and 5 take: one board, one serial cable, ten
minutes if nothing goes wrong.

**Rollback:** redeploy the previous commit. It reads `/farm`, which is still
there and still being written to, so the farm comes straight back.

### 4 · Flash the one board

`docs/CUTOVER_REFLASH.md`, in full. There is exactly one physical board —
`B0CBD87D254C`, H1/S8, the master with both pumps. The other 24 device records
are bench-generated.

**Rollback:** reflash the previous `.ino`. The board rejoins `/farm`, which is
why the migration copies rather than moves.

### 5 · Reset the bench

Open `NODE_SIMULATOR.html`, **Remove all**, then type the tenant id into the
header. It refuses every farm request without one, reads included.

**Rollback:** none needed; the bench holds no state the farm depends on.

### 6 · Install the app and sign in

The 2C build. Sign in as the admin created in step 2.

**Rollback:** install the previous APK. It sends the shared key and no token,
which the previous backend accepts.

### 7 · Prove it end to end

**A five second Water Now, confirmed by a node ack.** Everything before this is
inference: the board reporting proves it writes, the app loading proves it
reads, and only this proves the whole path — app → backend → the tenant-scoped
queue → the board → the relay → water.

It is also the first physical confirmation since the two-pump change that
watering is channel 1 and the tray is channel 2. That routing was verified in
code and never with water. **Watch which pump starts.**

### Then sweep

Between step 1's copy and step 4's reflash, readings kept landing in `/farm`.
They are missing from the new tree's charts until:

```bash
python -m scripts.migrate_to_tenant --tenant <id> --sweep
```

It PATCHes across **only** the keys the destination lacks. PATCH and not PUT
matters here: the board is now writing to `/tenants`, and a PUT of the whole
branch from `/farm` would overwrite those new readings with a snapshot that
predates them. Safe to run more than once.

---

## The checks that are not optional

- [ ] `android:usesCleartextTraffic` in the **installed** APK, not the source
      manifest — `aapt2 dump xmltree --file AndroidManifest.xml <apk> | grep -i cleartext`
- [ ] the board's boot banner reads **`validation-2.0`** — during the cutover
      that string is the whole diagnostic for "reflashed or not"
- [ ] a reading appears under `/tenants/{id}/farm/houses/H1/sections/S8/latest`
- [ ] `/devices/B0CBD87D254C` now carries `tenantId`
- [ ] the Water Now ack

---

## Afterwards

- [ ] Auto back **ON**
- [ ] Watch one full day: a plan generated at 05:00, a watering between 06:00
      and 09:00, a tray check, an alarm if one is due
- [ ] `--sweep` once more the next morning, to catch anything the first sweep
      raced
- [ ] **`/farm/*` deleted — not on the same day, and not the next one either.**
      It is the rollback for steps 3 and 4 until you are certain, and there is
      no reason at all to be in a hurry about 8 MB.
- [ ] Only then: Stage 3, closing the Firebase rules. They are open today —
      an unauthenticated write to the database returns 200 — and that is the
      last thing this design leaves undone.

## Still open after this

- `X-API-Key` and the middleware in `app/main.py` that demands it. Every
  `/api/v2` write is behind `require_role` now, so the shared key guards nothing
  that is not already guarded, and a secret compiled into every copy of the app
  identifies nobody. Remove the middleware and the header together, in that
  order, in a release of their own — not on cutover day.
- `/api/v1/watering/*` is still mounted unauthenticated and still reads and
  writes the root `/latest` and `/prediction`, which no tenant owns.
