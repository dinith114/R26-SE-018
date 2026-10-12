# Tenancy Cutover 2D — the migration and the cutover

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the existing farm a tenant, copy its data under that tenant, and
write down the order the four pieces go live in — so the day itself is a
checklist, not a set of decisions.

**Architecture:** The migration **copies**. It never moves and never deletes.
Everything that makes this reversible follows from that one choice: the old tree
stays serving until the new one is proven, a board reflashed with the old sketch
rejoins a farm that still exists, and rolling back is redeploying, not restoring
a backup.

**Tech Stack:** Python 3.12, `requests` against the Firebase REST API, the same
`FIREBASE_BASE_URL` every other script uses.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`
("Migration", "The cutover itself")

---

## What is actually there — measured 4 September 2026

```
/farm                      8 284 000 bytes total
  history                  8 205 936    99.1%   <-- the whole problem
  alarms                      31 709
  houses                      29 508
  events                      13 151
  masters                      4 192
  pushTokens                     363
  meta                           209

  houses: H1 (8 sections), H2 (1), H3 (2)
  history: 11 sections, largest H1/S1 at 1 706 970 bytes

NOT under /farm, so scoped() never rewrites them and they do NOT migrate:
  /devices          the global registry, deliberately shared - a board belongs
                    to nobody until it is flashed with a tenant
  /latest       132 bytes   legacy v1, still read by /api/v1/watering
  /prediction   331 bytes   legacy v1, still written by /api/v1/watering
  /history    1 694 299     legacy v1, written by old firmware, read by nothing
  /hybridPrediction         Component 4's

/tenants does not exist yet.
```

**The 8.2 MB of history is the shape of this task.** One `PUT /tenants/{t}/farm.json`
carrying the whole tree is a single 8 MB request that either works or leaves the
destination in a state nobody can describe. Copy branch by branch, and copy
history one section at a time — 11 requests of at most 1.7 MB, each of which can
be retried on its own and none of which can half-write the others.

## The blocker inherited from 2C

**Firebase Authentication is still not enabled on the project.** Measured, with
a control, in `docs/superpowers/plans/2026-09-04-tenancy-2c-mobile.md`. That
splits this plan in two:

- **The data copy does not need it.** Task 1 and Task 2 can be written, run and
  verified today.
- **Provisioning the admin account does.** No Firebase Auth means no user, no
  uid, and so no `tenantId`/`role` claims to stamp. Task 3 is written now and
  **run on the day**, after the console step.

Do not paper over this by inventing a uid. A tenant whose `ownerUid` names
nobody is a farm nobody can administer, and the app has no screen that can fix
it.

## Global Constraints

- **COPY, NEVER MOVE.** No step in this plan deletes anything under `/farm`.
  Deleting it is a separate decision, taken days later, by a person, once the new
  tree has been serving.
- **The tenant id is minted once and written down.** It goes into the firmware's
  `#define TENANT_ID`, the bench's header field, and the admin's custom claims.
  Three places that must agree, and a typo in any of them is a farm writing
  where nothing reads.
- **Idempotent.** Running the copy twice must be harmless. It will be run twice,
  because something will time out.
- **Nothing here deploys.** The deploy is the cutover, and its order is Task 4.
- Commit messages: plain sentences, no `feat:`/`chore:`/`fix:` prefixes, ending
  with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

### Task 1: The migration script

**Files:**
- Create: `backend/scripts/migrate_to_tenant.py`

**Interfaces:**
- `--dry-run` (the default) measures and prints what would happen, writes nothing
- `--tenant t_xxx --copy` copies `/farm/*` to `/tenants/{t}/farm/*`
- `--tenant t_xxx --verify` compares the two trees and reports differences

- [ ] **Step 1: Default to doing nothing**

`--dry-run` is the default and `--copy` must be typed. A migration script whose
default is to migrate gets run by accident exactly once.

The dry run prints, per branch: the byte count at the source, whether the
destination already holds something, and what the copy would do. That output is
the thing pasted into the runbook on the day, so it has to be readable by
somebody who is not the person who wrote it.

- [ ] **Step 2: Copy branch by branch, history section by section**

`meta`, `houses`, `masters`, `alarms`, `events`, `pushTokens` are small enough to
copy whole. `history` is copied one `{house}/{section}` at a time.

Verify each write by reading it back and comparing, before moving to the next.
Firebase returns 200 on a PUT it has accepted, which is not the same as a PUT it
has stored; this project has already been caught believing a 200 (`_fb_put(path,
None)` returns 200 and clears nothing).

- [ ] **Step 3: Idempotence, and what it means for a re-run**

A second run must not duplicate or corrupt. Since every write is a PUT of a
whole branch, a re-run overwrites with the same content — but that is only safe
while the destination is not yet live. Once the farm is running on the new tree,
a re-run would overwrite live data with a stale snapshot of `/farm`.

So refuse to copy a branch that already exists unless `--force` is given, and
say why in the refusal. The safe default is the one that cannot destroy the new
farm's data on day three.

- [ ] **Step 4: `--verify` compares, it does not trust**

Walk both trees and compare: byte counts per branch, and for history, per
section. Report any difference by name. A verify that only checks existence
proves the copy ran, not that it landed.

- [ ] **Step 5: Dry-run it against the live database**

Run it. Put the real output in your report. This is the only step in Task 1
that touches the live project, and it only reads.

- [ ] **Step 6: Commit**

---

### Task 2: Prove the copy works, on a throwaway tenant

**Files:**
- none (this task runs the script from Task 1)

Copying 8 MB of somebody's farm for the first time on cutover day is a bad place
to discover a bug.

- [ ] **Step 1: Copy to a scratch tenant id**

Pick an obviously disposable id — `t_migrationtest` — and run the real copy to
it. This is a write to the live database, so it is 8 MB in and 8 MB out of the
daily budget, once.

- [ ] **Step 2: Verify, then break something, then verify again**

Run `--verify` and expect a clean report. Then delete one section's history from
the scratch tenant by hand and re-run `--verify`: it must name that section. A
verify that passes on a tree you have deliberately damaged is not a verify.

- [ ] **Step 3: Delete the scratch tenant**

`DELETE /tenants/t_migrationtest.json`. Confirm with a read that returns null.
Leaving it behind means the app's own tenant list, when there is one, shows a
farm nobody owns.

- [ ] **Step 4: Report what the copy actually cost**

Wall-clock time and the number of requests. The runbook needs a real number for
"how long will the farm be half-migrated", not an estimate.

---

### Task 3: Provisioning, written now and run on the day

**Files:**
- Create: `backend/scripts/provision_first_tenant.py`

**BLOCKED until Firebase Auth is enabled.** Write it, review it, do not run it.

- [ ] **Step 1: One script, one transaction-shaped sequence**

It must do, in this order, and stop at the first failure:

1. mint the tenant id (`tenant_store.new_tenant_id()`)
2. create the Firebase Auth user for the farm's owner
3. stamp `{tenantId, role: "admin"}` onto that user's custom claims
4. write `/tenants/{t}/meta` and `/tenants/{t}/users/{uid}`
5. print the tenant id in a box, because it is about to be typed into firmware

Steps 2-4 are exactly what `POST /api/v2/accounts/tenants` already does, and
that route is the thing to call rather than reimplement — it has the rollback
that undoes a half-made tenant, and reimplementing it here would give the
project two provisioning paths that can drift.

So this script is mostly a caller: it needs `ORCHID_API_KEY` (the vendor key)
and it posts to the running backend.

- [ ] **Step 2: Say what to do when it half-fails**

The route rolls back its own writes. The script cannot roll back the console
step or an existing account with that email. Write those two cases down.

- [ ] **Step 3: Commit, unrun, and say so in the commit message**

---

### Task 4: The cutover runbook

**Files:**
- Create: `docs/CUTOVER.md`
- Modify: `docs/CUTOVER_REFLASH.md` (link it in as the step it is)

`CUTOVER_REFLASH.md` already covers the one board. This is the document it is
step 4 of.

- [ ] **Step 1: The order, and why each thing is where it is**

```
BEFORE      Firebase Auth enabled in the console, and the probe re-run
            (2C's plan has the exact probe)
            after 09:00 farm time - the engine plans at 05:00 and waters
            06:00-09:00, and a farm mid-cutover in that window misses the day
            Auto OFF - the system keeps deciding and alarming, it stops acting

 1  copy    migrate_to_tenant --copy, then --verify
 2  tenant  provision_first_tenant, write the id down
 3  deploy  the backend (2A) - from this moment the API reads the NEW tree,
            and the boards are still writing to the old one
 4  flash   the one board (docs/CUTOVER_REFLASH.md)
 5  bench   NODE_SIMULATOR.html: Remove all, then set the tenant id
 6  app     install the 2C build, sign in as the admin
 7  prove   a five second Water Now, confirmed by a node ack

AFTER       Auto back ON
            /farm/* deleted - NOT on the same day
```

Step 3 opens a window where the farm is dark: the backend reads the new tree,
the board still writes the old one. It closes at step 4. Say how long that is,
using the real number from Task 2, and say that nothing is lost in it — readings
still land in `/farm`, they are simply not read until the board is flashed.

- [ ] **Step 2: What "it went wrong" looks like at each step, and the way back**

Every step needs its own rollback, and they are not the same:

- after 1: delete `/tenants/{t}` — nothing else has changed
- after 2: same, plus delete the auth user
- after 3: redeploy the previous backend — it reads `/farm`, which is still there
- after 4: reflash the old `.ino` — the board rejoins `/farm`
- after 6: the app is the only thing that changed; the previous APK still works
  against the previous backend

The one that has no easy way back is deleting `/farm`, which is why it is not on
this list and not on the day.

- [ ] **Step 3: The checks that are not optional**

- `android:usesCleartextTraffic` in the installed APK, not the source manifest
- the board's version string reads `validation-2.0`
- a reading under `/tenants/{t}/farm/houses/H1/sections/S8/latest`
- the Water Now ack

- [ ] **Step 4: Commit**

---

## Definition of done for 2D

- the migration script exists, defaults to a dry run, and refuses to overwrite
  an existing destination without `--force`
- the copy has been proven on a throwaway tenant and the throwaway deleted
- `--verify` has been shown to FAIL on a tree that was deliberately damaged
- the provisioning script exists, is unrun, and says so
- `docs/CUTOVER.md` exists with the order, the rollback for each step, and a
  real number for how long the farm is half-migrated
- `/farm/*` is untouched, and nothing is deployed or flashed

## Not in this plan

Enabling Firebase Auth (a console action, and the project owner's). Running the
cutover. Deleting `/farm`. Closing the Firebase rules — that is Stage 3, and it
comes after the farm has been running on the new tree long enough to believe it.
