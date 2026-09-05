"""Create the first tenant and its admin account.

NEVER RUN. Written 4 September 2026 and deliberately unrun, because Firebase
Authentication is not enabled on the orchid-smart-care project - measured, with
a control, in docs/superpowers/plans/2026-09-04-tenancy-2c-mobile.md. Without it
there is no user, no uid, and so no tenantId/role claims to stamp, and a tenant
whose ownerUid names nobody is a farm nobody can administer and no screen in the
app can repair.

    python -m scripts.provision_first_tenant --name "Orchid Farm" \
        --email owner@example.com --backend https://orchidfarm.duckdns.org

MOSTLY A CALLER, ON PURPOSE

POST /api/v2/accounts/tenants already does all of this: it mints the id, creates
the auth user, stamps the claims, writes /tenants/{t}/meta and
/tenants/{t}/users/{uid}, and - the part worth not reimplementing - rolls all of
it back if any step fails, including deleting the auth user it just made. A
second provisioning path here would be a second set of rules that can drift from
the one the app uses, and the drift would show up as a tenant that half exists.

So this script's job is to call that route carefully, read the answer, and put
the tenant id somewhere it cannot be misread. It needs the VENDOR key
(ORCHID_API_KEY), which is the same static key the /api/v2 write middleware uses
and which lives on the server, not in the app.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

import requests

TIMEOUT = 60


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", required=True, help='the farm\'s name, e.g. "Orchid Farm"')
    ap.add_argument("--email", required=True, help="the owner's email; becomes the admin")
    ap.add_argument("--backend", default="https://orchidfarm.duckdns.org",
                    help="where the backend is running")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args()

    key = os.environ.get("ORCHID_API_KEY", "").strip()
    if not key:
        print("ORCHID_API_KEY is not set. It is the vendor key, and it lives on "
              "the server, not in the app.", file=sys.stderr)
        return 2

    # Typed, not passed as an argument: a password in argv is a password in the
    # shell history and in the process list.
    password = getpass.getpass("First password for the admin account: ")
    if len(password) < 8:
        print("The backend requires at least 8 characters.", file=sys.stderr)
        return 2
    if password != getpass.getpass("Again: "):
        print("They do not match.", file=sys.stderr)
        return 2

    print()
    print(f"  backend  {args.backend}")
    print(f"  farm     {args.name}")
    print(f"  admin    {args.email}")
    print()
    if not args.yes and input("Create this tenant? [y/N] ").strip().lower() != "y":
        print("Nothing was created.")
        return 1

    r = requests.post(
        f"{args.backend}/api/v2/accounts/tenants",
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json={"name": args.name, "adminEmail": args.email,
              "adminPassword": password, "plan": "starter"},
        timeout=TIMEOUT,
    )

    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text[:300]
        print(f"\nFailed: HTTP {r.status_code}  {detail}", file=sys.stderr)
        print(_what_that_means(r.status_code), file=sys.stderr)
        return 1

    body = r.json()
    tid, uid = body.get("tenantId"), body.get("adminUid")

    # Boxed because it is about to be typed into firmware, into the bench's
    # header field, and read back by whoever checks the reflash. Three places
    # that must agree exactly, and a transcription error in any of them is a
    # farm writing where nothing reads.
    line = "=" * 58
    print()
    print(line)
    print(f"  TENANT ID   {tid}")
    print(f"  ADMIN UID   {uid}")
    print(line)
    print()
    print("Write the tenant id down NOW. It goes into three places and they")
    print("must match exactly:")
    print("   1. firmware/sensor_node_validate/sensor_node_validate.ino")
    print("      #define TENANT_ID \"" + str(tid) + "\"")
    print("   2. NODE_SIMULATOR.html, the tenant field in the header bar")
    print("   3. the --tenant argument to scripts.migrate_to_tenant")
    print()
    print(json.dumps(body, indent=2))
    return 0


def _what_that_means(status: int) -> str:
    """The two failures this script cannot undo, said before they happen.

    The route rolls back its own writes - a half-made tenant and the auth user
    with it. What it cannot undo is the state of the world outside it.
    """
    if status == 401:
        return ("\nThe vendor key was refused. Check ORCHID_API_KEY matches the "
                "one the server was started with; the server reads it from its "
                "own environment, so a key rotated in one place and not the "
                "other looks exactly like this.")
    if status == 409:
        return ("\nThat email already has an account somewhere on this "
                "deployment. Nothing was created and nothing needs undoing, but "
                "this script cannot delete the existing account for you - the "
                "message is deliberately vague about whose tenant it belongs "
                "to, and that is not an oversight. Use a different address, or "
                "remove the account in the Firebase console.")
    if status == 500:
        return ("\nProvisioning failed part way and the route rolled back what "
                "it had written. Check the server log for the tenant id it was "
                "using, then confirm /tenants/{id} is absent before retrying - "
                "the rollback is best effort, and a leftover meta node with no "
                "users under it is the shape of one that did not finish.")
    return ("\nIf Firebase Authentication is still not enabled on the project, "
            "this is what that looks like from here. See "
            "docs/superpowers/plans/2026-09-04-tenancy-2c-mobile.md for the "
            "probe that tells you, and the console steps that fix it.")


if __name__ == "__main__":
    sys.exit(main())
