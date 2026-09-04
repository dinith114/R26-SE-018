"""Copy /farm/* to /tenants/{id}/farm/*.

COPIES. Never moves, never deletes. Everything that makes the cutover reversible
follows from that one choice: the old tree keeps serving until the new one is
proven, a board reflashed with the old sketch rejoins a farm that still exists,
and rolling back is a redeploy rather than a restore from a backup nobody tested.

    python -m scripts.migrate_to_tenant                        # dry run, reads only
    python -m scripts.migrate_to_tenant --tenant t_x --copy
    python -m scripts.migrate_to_tenant --tenant t_x --verify

WHY BRANCH BY BRANCH, AND HISTORY SECTION BY SECTION

Measured 4 Sep 2026: /farm is 8.28 MB and /farm/history is 8.21 MB of it - 99%.
One PUT carrying the whole tree is a single 8 MB request that either works or
leaves the destination in a state nobody can describe. Split up, it is ~17
requests of at most 1.7 MB, each of which can be retried on its own and none of
which can half-write the others.

WHAT DOES NOT MIGRATE, AND WHY

/devices stays global. A board belongs to no tenant until it is flashed with
one, and the app's Link-a-node list has to see boards before they are anybody's.

/latest, /prediction and the root /history are v1 paths. `scoped()` in the
backend only rewrites paths starting with '/farm/', so these were never part of
the tenant tree. /latest and /prediction are still read and written by the v1
watering routes; the root /history is written by old firmware and read by
nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.api.routes.smart_watering import FIREBASE_BASE_URL  # noqa: E402

TIMEOUT = 60

# Copied whole. Each is small - the largest, alarms, was 31 KB when measured.
SIMPLE_BRANCHES = ("meta", "houses", "masters", "alarms", "events", "pushTokens")

# Copied one {house}/{section} at a time.
BIG_BRANCH = "history"


# ── the four requests, kept deliberately dumb ──────────────────────────────

def get(path: str):
    r = requests.get(f"{FIREBASE_BASE_URL}{path}", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def put(path: str, data) -> None:
    r = requests.put(f"{FIREBASE_BASE_URL}{path}", json=data, timeout=TIMEOUT)
    r.raise_for_status()


def size_of(path: str) -> int:
    """Bytes of JSON at a path, without parsing it.

    Parsing 8 MB to count it is a waste, and `len(response.content)` is what
    actually crossed the wire, which is the number that matters for both the
    daily budget and the risk of a single request.
    """
    r = requests.get(f"{FIREBASE_BASE_URL}{path}", timeout=TIMEOUT)
    r.raise_for_status()
    return len(r.content)


def shallow(path: str) -> dict:
    r = requests.get(f"{FIREBASE_BASE_URL}{path}?shallow=true", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json() or {}


# ── what there is to copy ──────────────────────────────────────────────────

def history_sections() -> list:
    """[(house, section)], read from the tree rather than assumed."""
    out = []
    for house in sorted(shallow("/farm/history.json")):
        for section in sorted(shallow(f"/farm/history/{house}.json")):
            out.append((house, section))
    return out


def plan_jobs() -> list:
    """[(source path, destination suffix, label)] - the whole copy, in order."""
    jobs = [(f"/farm/{b}.json", f"/farm/{b}.json", b) for b in SIMPLE_BRANCHES]
    for house, section in history_sections():
        p = f"/farm/history/{house}/{section}.json"
        jobs.append((p, p, f"history/{house}/{section}"))
    return jobs


def dest(tenant: str, suffix: str) -> str:
    return f"/tenants/{tenant}{suffix}"


# ── the three modes ────────────────────────────────────────────────────────

def do_dry_run(tenant: str | None) -> int:
    jobs = plan_jobs()
    print(f"source     {FIREBASE_BASE_URL}/farm")
    print(f"tenant     {tenant or '(none given - pass --tenant to see the destination)'}")
    print(f"jobs       {len(jobs)}")
    print()
    print(f"  {'what':<28} {'bytes':>10}   destination")
    total = 0
    for src, suffix, label in jobs:
        n = size_of(src)
        total += n
        d = dest(tenant, suffix) if tenant else "-"
        occupied = ""
        if tenant and get(d) is not None:
            occupied = "  ALREADY HAS DATA"
        print(f"  {label:<28} {n:>10}   {d}{occupied}")
    print()
    print(f"  {'TOTAL':<28} {total:>10}")
    print()
    print("Nothing was written. Add --copy to do it.")
    return 0


def do_copy(tenant: str, force: bool) -> int:
    jobs = plan_jobs()
    started = time.time()
    copied = skipped = 0

    for src, suffix, label in jobs:
        d = dest(tenant, suffix)

        # Refuse an occupied destination unless told twice. A re-run is safe
        # while the new tree is not yet live and destroys data the moment it is:
        # once the farm is running on /tenants, this would overwrite live
        # readings with a stale snapshot of /farm.
        if not force and get(d) is not None:
            print(f"  SKIP  {label:<28} destination already has data "
                  f"(--force to overwrite)")
            skipped += 1
            continue

        payload = get(src)
        if payload is None:
            print(f"  none  {label:<28} nothing at the source")
            continue

        put(d, payload)

        # Read it back. Firebase answers 200 to a PUT it has ACCEPTED, which is
        # not the same as one it has stored - this project has already been
        # caught believing a 200 from `_fb_put(path, None)`, which returns 200
        # and clears nothing.
        back = get(d)
        if back != payload:
            print(f"  FAIL  {label:<28} read-back does not match what was sent")
            return 1

        # Compact separators, so this agrees with what --dry-run measured on
        # the wire. The default ", " and ": " inflate every count by about a
        # tenth, and two different numbers for the same branch is how a reader
        # stops trusting either.
        n = len(json.dumps(payload, separators=(",", ":")))
        print(f"  ok    {label:<28} {n:>10} bytes")
        copied += 1

    secs = time.time() - started
    print()
    print(f"copied {copied}, skipped {skipped}, in {secs:.1f}s "
          f"({len(jobs)} jobs)")
    print(f"/farm is untouched. Verify with --tenant {tenant} --verify")
    return 0


def do_verify(tenant: str) -> int:
    """Did anything land WRONG, and how far has the source moved since?

    Those are two questions and the first draft of this asked neither. It
    compared the two trees for exact equality, and reported three failures on a
    copy that had just read every write back successfully.

    THE FARM IS LIVE. Measured 4 Sep 2026, while this script was being written:
    history/H1/S1 had four keys at the source that were not at the destination,
    zero keys changed, zero missing - a pure append - and houses had all three
    of its keys changed, because each house carries its sections' `latest`
    readings and those are rewritten on every report.

    So exact equality can never pass, and a verify that can never pass teaches
    whoever runs it to ignore the output. What actually matters is:

      CORRUPTION   every key at the destination must match the source. A branch
                   written truncated, or written from a bad read, shows up here
                   and is a real failure.
      DRIFT        keys that have appeared at the source since the copy. Not a
                   failure - it is the farm doing its job - but it is the size
                   of the gap in the new tree's charts, so it gets counted and
                   printed rather than hidden.
    """
    jobs = plan_jobs()
    corrupt, drift = [], []

    for src, suffix, label in jobs:
        a = get(src)
        b = get(dest(tenant, suffix))

        if b is None:
            corrupt.append(f"{label}: missing at the destination")
            continue
        if a == b:
            print(f"  ok       {label}")
            continue
        if not (isinstance(a, dict) and isinstance(b, dict)):
            corrupt.append(f"{label}: differs and is not a keyed branch")
            continue

        missing_at_dest = sorted(set(a) - set(b))
        only_at_dest = sorted(set(b) - set(a))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])

        # History is APPEND-ONLY: a push id, once written, is never rewritten.
        # So a changed key there is the copy having done damage. Every other
        # branch is live config - `houses` carries each section's `latest`, and
        # that is rewritten on every report - so a changed key there is the farm
        # running, not a fault. Judging them by the same rule reported `houses`
        # as corrupt on a copy that was perfect, which is the kind of false
        # alarm that teaches somebody to skip the check.
        append_only = label.startswith("history/")

        if only_at_dest:
            corrupt.append(
                f"{label}: {len(only_at_dest)} key(s) exist ONLY at the "
                f"destination {only_at_dest[:3]}")
        if changed and append_only:
            corrupt.append(
                f"{label}: {len(changed)} key(s) changed in an append-only "
                f"branch {changed[:3]}")
        elif changed:
            drift.append((label, len(changed)))
            print(f"  moved    {label}  ({len(changed)} key(s) updated since)")
        if missing_at_dest:
            drift.append((label, len(missing_at_dest)))
            print(f"  behind   {label}  ({len(missing_at_dest)} new at the source)")

    print()
    if drift:
        total = sum(n for _l, n in drift)
        print(f"DRIFT: {total} key(s) have appeared at the source since the copy, "
              f"across {len(drift)} branch(es).")
        print("  Expected on a running farm. Sweep them with --sweep, which "
              "PATCHes only")
        print("  the missing keys and never overwrites anything already there.")
        print()
    if corrupt:
        print(f"{len(corrupt)} PROBLEM(S) - these are copy failures, not drift:")
        for c in corrupt:
            print(f"  !! {c}")
        return 1
    # Said plainly, because the honest limit of this check is easy to overstate.
    # The real proof that a branch copied correctly is the read-back --copy does
    # at the moment it writes it. Run later against a live farm, this can only
    # compare a moving source with a fixed snapshot, so what it rules out is
    # data at the destination that never came from the source, and history
    # rewritten in transit. It cannot rule out a branch that was copied badly
    # and has since been overwritten by drift.
    print(f"no corruption found: nothing at the destination that did not come "
          f"from the source, and no rewritten history ({len(jobs)} branches)")
    return 0


def do_sweep(tenant: str) -> int:
    """PATCH across only the keys the destination is missing.

    For the tail that accumulates between the copy and the reflash. PATCH and
    not PUT, deliberately and importantly: after the board is reflashed it
    writes to /tenants, so a PUT of the whole branch from /farm would overwrite
    those new readings with a snapshot that predates them. PATCH merges by key
    and cannot do that.

    Safe to run repeatedly, and safe to run after the cutover.
    """
    jobs = plan_jobs()
    swept = 0
    for src, suffix, label in jobs:
        a = get(src)
        b = get(dest(tenant, suffix)) or {}
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        missing = {k: a[k] for k in set(a) - set(b)}
        if not missing:
            continue
        r = requests.patch(f"{FIREBASE_BASE_URL}{dest(tenant, suffix)}",
                           json=missing, timeout=TIMEOUT)
        r.raise_for_status()
        print(f"  swept  {label:<28} {len(missing)} key(s)")
        swept += len(missing)
    print()
    print(f"swept {swept} key(s). /farm is untouched.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", help="destination tenant id, e.g. t_a1b2c3d4e5f6")
    ap.add_argument("--copy", action="store_true", help="actually copy")
    ap.add_argument("--verify", action="store_true",
                    help="check nothing landed wrong, and report how far the "
                         "source has moved since")
    ap.add_argument("--sweep", action="store_true",
                    help="PATCH across only the keys the destination is missing")
    ap.add_argument("--force", action="store_true",
                    help="overwrite branches that already exist at the destination")
    args = ap.parse_args()

    if (args.copy or args.verify or args.sweep) and not args.tenant:
        ap.error("--copy, --verify and --sweep need --tenant")

    # The default is the one that cannot do damage. A migration script whose
    # default is to migrate gets run by accident exactly once.
    if args.copy:
        return do_copy(args.tenant, args.force)
    if args.verify:
        return do_verify(args.tenant)
    if args.sweep:
        return do_sweep(args.tenant)
    return do_dry_run(args.tenant)


if __name__ == "__main__":
    sys.exit(main())
