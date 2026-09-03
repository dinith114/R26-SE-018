# Multi-tenant user management — design

Status: approved by user, pending spec review
Author: session with Claude (Opus 5), 2026-09-02
Component: R26-SE-018 Component 3 (Smart Watering & Automated Fertilization)

## Why

The product today has no accounts: one shared `/farm/...` tree in Firebase, one
static `X-API-Key` for every write, no login, and firmware nodes write directly
to fixed paths with no identity at all. This works for one farm operated by one
person. It does not work for the commercialization model the project intends:
"when a plan is sold, it is sold with an admin account, and that admin can then
create and delete further accounts, and controls what those accounts can see and
do."

This spec covers building that: real accounts, tenant isolation (one customer's
farm data is invisible to another customer), and role-based access within a
tenant.

## Decisions made in brainstorming, and why

**Multi-tenant, customer-admin — not platform-superadmin.** Each paying customer
gets their own admin account scoped to their own farm(s). There is no built-in
"see every customer's data" role in the product itself; the person who
provisions a new tenant when a plan is sold does so through a vendor-gated
endpoint (see Bootstrap, below), not through a role inside the app.

**Firebase Authentication**, not a custom backend auth system. The mobile app
already carries the Firebase SDK; the backend already carries `firebase-admin`
(used today for FCM push). Verifying an ID token needs no new dependency.

**Simple roles, tenant-wide — not per-house scoping.** Admin / Operator / Viewer.
An Operator or Viewer sees every house in their tenant, not a subset. Per-house
ACLs were considered and rejected as unneeded complexity for the deployment size
this product targets (one tenant is one grower's operation, not a large
multi-site enterprise).

| Role | View | Water/Tray now | Settings/Auto/Pumps | Manage users |
|---|---|---|---|---|
| Admin | yes | yes | yes | yes |
| Operator | yes | yes | no | no |
| Viewer | yes | no | no | no |

**Firebase path-based tenancy (`/tenants/{tenantId}/farm/...`), not
backend-only enforcement on a flat schema.** This was an explicit trade-off,
presented and chosen knowingly:

- The alternative (tag `houses.meta.tenantId` and filter in the API layer,
  leaving `/farm/...` flat) needs zero firmware changes and touches nothing
  outside the backend. It was the recommended option.
- The chosen option needs a firmware change and a **reflash of every physical
  board** (a `#define TENANT_ID "..."` constant, added the same way `HOUSE_ID`
  and `SECTION_ID` already work — confirmed at `sensor_node_validate.ino:62`,
  which is a compile-time `#define`, not something the WiFi portal configures
  at runtime), and tenant scoping applied across 6 backend route files that
  hardcode `/farm/...`, and an update to `NODE_SIMULATOR.html`.
- Chosen anyway, with the cost explicit, because it gives real database-level
  separation rather than isolation that depends on every future code path
  remembering to filter correctly.

## Data model

```
/tenants/{tenantId}/
    meta/                    { name, ownerUid, plan, createdAt }
    users/{firebaseUid}/     { email, role: "admin" | "operator" | "viewer", addedAt }
    farm/                    <- identical subtree to what exists today under /farm
        meta/                  { farmName, autoMode, latitude, longitude, version }
        houses/{h}/
            meta/
            sections/{s}/
                meta/ latest/ plan/ tray/ fertilizer/ control/ estimated/
        masters/{mac}/         queue/ running/ stop/ acks/{id}
        history/{h}/{s}/{pushId}

/devices/{mac}               <- stays a GLOBAL registry (a board has no tenant
                                 until it is flashed with one)
    tenantId                 <- announced by the board itself, same mechanism
                                 as ip/rssi/fw today (see below - not a runtime
                                 claim step)
    assignedTo                 "H1/S1" (unchanged)
```

`houseId` / `sectionId` stay globally-formatted (`H1`, `S1`, ...) but only need
to be unique **within a tenant**, since every read is now reached via
`/tenants/{tenantId}/farm/houses/{h}`.

**Correcting an assumption from the first draft of this section:** `HOUSE_ID`
and `SECTION_ID` are `#define` constants baked in before flashing, not values
the app assigns at runtime - confirmed at `sensor_node_validate.ino:62`. The
app's "link a node to a section" flow (Calibration screen, Add Section) records
an app-side association for MAC → house/section so the app can display and
manage it; it does not reconfigure where the board writes, because the board
already knows that from compile time. `TENANT_ID` follows the identical
pattern: the board writes to `/tenants/{TENANT_ID}/farm/houses/{HOUSE_ID}/…`
because all three were compiled in together. There is no separate "claim this
device into a tenant" action anywhere in the app - the reflash IS the claim.

## Role resolution — Firebase custom claims, not an RTDB lookup

When an Admin creates a sub-account, the backend:
1. creates the Firebase Auth user (`firebase_admin.auth.create_user(...)`)
2. calls `firebase_admin.auth.set_custom_user_claims(uid, {"tenantId": t, "role": r})`
3. writes `/tenants/{t}/users/{uid}` for the "manage team" screen to list

When that user's app signs in, the ID token carries `tenantId` and `role` as
claims after the next token refresh (the Firebase SDK on the client handles
this automatically — no manual refresh call needed in normal use). The backend
verifies the token with `verify_id_token()` and reads both fields directly off
the decoded token. No Firebase read happens per request to resolve identity.

## Backend changes

**New router, `app/api/routes/accounts.py`:**

| Method | Path | Who | Does |
|---|---|---|---|
| POST | `/api/v2/accounts/tenants` | vendor `X-API-Key` only | creates a tenant + its first Admin user |
| GET | `/api/v2/accounts/users` | any tenant member | lists the tenant's users and roles |
| POST | `/api/v2/accounts/users` | admin | creates a sub-account, sets its role |
| PUT | `/api/v2/accounts/users/{uid}/role` | admin | changes a sub-account's role |
| DELETE | `/api/v2/accounts/users/{uid}` | admin | deletes a sub-account; refuses on self or the tenant's last admin |

**Two FastAPI dependencies used by every existing route:**

```python
async def require_auth(request: Request) -> AuthContext:
    """Verifies Authorization: Bearer <idToken>, sets tenant_id/role/uid on request.state."""

def require_role(*allowed: str):
    """403 unless request.state.role is one of `allowed`."""
```

Applied per existing endpoint:
- read-only (`/overview`, `/houses/{h}`, `/…/history`) — `require_auth` only
- act-now (`/…/water`, `/…/tray-fill`, `/…/plan`) — `require_role("admin", "operator")`
- configure (`/…/mode`, `/houses/{h}/pumps`, `DELETE /houses/{h}`) — `require_role("admin")`

The existing static `X-API-Key` middleware is **superseded, not removed**: it
stays as the sole guard on `POST /api/v2/accounts/tenants` (the one endpoint
that must work before any Firebase user exists to authenticate as), and is
dropped from every other endpoint it currently guards, in favour of
`require_auth` / `require_role`.

**Tenant scoping is applied at ONE chokepoint, not threaded through the code.**

This reverses what an earlier draft of this spec assumed, and the reason is a
measurement taken before Stage 2 began rather than an estimate:

```
/farm/ call sites                                    127
  (smart_care_v2.py alone: 100; the draft guessed ~99 in total)
  reached through _fb_get / _fb_put / _fb_delete      112
functions that would need a tenant_id parameter        74
```

Threading `tenant_id` through 74 function signatures and every one of their
callers has a silent failure mode: a call site that is missed keeps reading and
writing the OLD shared `/farm/...` tree. After migration that tree is stale or
empty, the code does not raise, and no test naturally covers "did we remember
this one". Seventy-four opportunities to forget, each one a cross-tenant defect.

So the prefix is applied inside the three Firebase helpers instead, from a
`contextvars.ContextVar` that `require_auth` sets:

```python
_tenant: ContextVar[Optional[str]] = ContextVar("orchid_tenant", default=None)

def _scoped(path: str) -> str:
    """Rewrite a farm path onto the caller's tenant.

    ONE chokepoint rather than 74 call sites, and the difference is the failure
    mode. A missed call site under the threading approach keeps writing to the
    old shared tree, silently and untested. Here there is nothing to miss: every
    farm path in the process goes through this function.

    It RAISES when no tenant is in context. Falling back to /farm/... would
    reintroduce exactly the shared-tree bug this exists to prevent, and would do
    it invisibly.
    """
    if not path.startswith("/farm/"):
        return path
    tenant = _tenant.get()
    if tenant is None:
        raise RuntimeError(f"farm path {path} used with no tenant in context")
    return f"/tenants/{tenant}{path}"
```

All 127 call sites keep their literal `/farm/...` strings unchanged. No route
signature changes. `_tpath()`, added inert in Stage 1, is removed — the
chokepoint supersedes it.

Two things this approach does NOT get for free, and both must be handled
explicitly:

- **`ThreadPoolExecutor` does not inherit context.** `_run_per_section` in
  `smart_care_v2.py` fans sections out across a thread pool, and a `ContextVar`
  set on the calling task is invisible inside those workers. Each submitted call
  must carry `contextvars.copy_context().run(...)`, or every parallel section
  raises "no tenant in context".
- **One path bypasses the helpers entirely.** `automation.py:277` calls
  `_req.delete(f"{FIREBASE_BASE_URL}/farm/pushTokens/{k}.json")` directly. It
  must be routed through `_fb_delete` or it will keep writing to the shared
  tree — the single instance of exactly the failure this design avoids
  everywhere else.

**Isolation this buys, and what it does not.** The chokepoint enforces tenancy
in the API process. It does nothing about direct database access: the Firebase
Realtime Database rules are still open, so anyone holding the client config can
read and write any tenant's tree over REST. Real isolation needs both layers,
and closing the rules is Stage 3 work because it requires auth tokens in the
firmware and the backend at the same time or both stop writing. Until Stage 3
lands, tenant isolation is a property of this backend, not of the data.

**`automation.py`'s engine loop** currently fetches `/farm/houses.json` once per
pass and runs the plan/tray/water cycles over it. It gains an outer loop:

```python
tenants = _fb_get("/tenants.json", shallow=True) or {}
for tenant_id in tenants:
    houses = _fb_get(_tpath(tenant_id, "houses.json")) or {}
    # existing run_plan_cycle / run_tray_cycle / run_watering_link, unchanged internally
```

Firebase reads scale with tenant count. Fine at the scale this product targets
(single digits to low tens of tenants); revisit if that changes. Out of scope
for this spec.

## Mobile app changes

- new `LoginScreen.js` — Firebase `signInWithEmailAndPassword`; the ID token is
  cached and refreshed by the Firebase SDK's own listener
- every `careV2.js` / `devices.js` call attaches `Authorization: Bearer <idToken>`,
  replacing the static key currently read from `secret.js`
- new `TeamScreen.js`, reachable from Settings, **visible only to Admins**: list
  of the tenant's users with role, an invite/create form, role change, delete
- role-gated UI elsewhere: a Viewer's `SectionDetailScreen` hides Water Now /
  Fill Tray / the Auto toggle; an Operator keeps those but not
  `PUT /houses/{h}/pumps` or house delete

## Migration — existing H1 and H2 data

1. One-time script: copy `/farm/*` to `/tenants/{t0}/farm/*`, where `t0` is a
   new tenant representing the current single-farm operation
2. Create a Firebase Auth account for the current operator, set custom claims
   `{tenantId: t0, role: "admin"}`, write `/tenants/{t0}/users/{uid}`
3. Every physical board gets `#define TENANT_ID "t0"` added and is **reflashed**
4. `NODE_SIMULATOR.html` gets the same `/tenants/{t0}/farm/...` prefix
5. Old flat `/farm/*` is deleted only after the new path is verified live —
   never before, and never by assuming rather than checking

## Testing

Two properties have to be proven by a test, not assumed from the design reading
correctly:

- **Tenant isolation** — a valid, verified token for tenant A gets a 403 or an
  empty result on tenant B's house. This is the test that would catch the exact
  class of bug this whole design exists to prevent.
- **Role enforcement** — a Viewer token gets 403 on `/water`; an Operator token
  gets 403 on `DELETE /houses/{h}`.

Existing `pytest` suite (57 passing at the time of writing) needs a
`tests/test_accounts.py` covering both, using two fake tenants and three fake
roles rather than any real Firebase project.

## Implementation sequencing

An earlier draft of this section had four stages that each "ship and be verified
before the next starts". **That is not possible, and the reason is worth stating
plainly because it was missed twice.**

The sensor nodes do not talk to this backend. They write to Firebase
**directly**, over REST, to a path compiled into the firmware —
`sensor_node_validate.ino:323` builds
`String(FB_HOST) + "/farm/houses/" HOUSE_ID "/sections/" SECTION_ID`. The mobile
app likewise holds the database URL itself. So the moment the backend starts
reading `/tenants/{t}/farm/...`:

- the nodes are still writing to `/farm/...` and the farm goes dark — readings
  land somewhere nothing reads, and no watering is planned from them
- the app sends a static API key and no bearer token, so nothing sets the tenant
  context, so every farm route raises

Stages 2, 3 and 4 are therefore **one atomic cutover**, not a sequence.

### Stage 1 — backend accounts and auth infrastructure — COMPLETE

Shipped 3 September 2026, 13 commits, 127 tests. Changes no existing endpoint's
behaviour: the static-key middleware is untouched, no farm route is guarded, and
`_tpath()` is inert with zero callers.

### Stage 2 — the cutover, prepared as one release

Everything below is built and tested together, and nothing is deployed until all
of it is ready:

- **Backend** — the `ContextVar` chokepoint in the three Firebase helpers; the
  `contextvars.copy_context()` fix for `_run_per_section`'s thread pool; the one
  direct `_req.delete` in `automation.py:277` routed through `_fb_delete`;
  `require_auth` / `require_role` applied to the farm routes per the table
  above; the automation engine's per-tenant loop; `_tpath()` removed.
- **Firmware** — `TENANT_ID` as a compile-time constant beside `HOUSE_ID` and
  `SECTION_ID`, and `NODE_SIMULATOR.html` updated to match.
- **Mobile** — login screen, bearer tokens replacing the static key on every
  call, the Team screen, and role-gated controls.
- **Data** — the migration script copying `/farm/*` to `/tenants/{t0}/farm/*`.

### The cutover itself

Ordered, and with the farm's own clock in mind — the engine plans at 05:00 and
waters between 06:00 and 09:00, so this runs **after 09:00 farm time**:

1. Verify every piece on the bench and in CI, with the migration script
   dry-run against a copy.
2. Set the farm to Auto OFF. The system keeps deciding and alarming; it stops
   acting, so nothing can fire mid-cutover.
3. Run the migration. **Copy, do not move** — `/farm/*` stays exactly where it
   is until the new tree is verified serving.
4. Deploy the backend, install the app, reflash the boards. The farm is
   effectively down for this window; it is minutes, and it is planned.
5. Verify: readings arriving under the new path, a plan generated, a manual
   Water Now confirmed by a node ack.
6. Auto back ON.
7. Only then delete the old `/farm/*` tree — and not on the same day.

### Stage 3 — close the Firebase rules

Deliberately AFTER the cutover, because it needs the new path layout to write
rules against. Until this lands, tenant isolation is a property of this backend
and not of the data: anyone holding the client config can still read and write
any tenant's tree over REST. This is the half of "multi-tenancy" that the
chokepoint cannot provide, and it is what makes the isolation real.

## Explicitly out of scope

- Self-service signup (a tenant is created by the vendor when a plan sells, not
  by a customer filling in a form)
- Per-house scoping within a tenant
- Tightening Firebase Realtime Database *security rules* to enforce isolation
  at the database layer itself, on top of backend enforcement (today's rules
  stay open, as already documented and deliberately deferred — this spec adds a
  second, independent layer of correctness on top of the API, it does not touch
  the rules)
- Billing / plan-tier enforcement (the "plan" a customer buys is assumed to be
  provisioned manually alongside the tenant, not metered by this system)
- Password reset / email verification flows (assumed a fast-follow, not needed
  for the first working version)
