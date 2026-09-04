"""Every control the app can reach is gated, or is explained here by name.

The permission map being right (test_mobile_perms_match_server.py) proves
nothing on its own: a map nobody consults is a document. This walks the screens
and asserts that each one that can trigger a write either checks `can()` for
that action, sits behind the AdminOnly guard in AppNavigator, or appears in the
EXPLAINED table below with a reason somebody wrote down.

It is a text scan and it says so. It cannot tell a `can()` guarding the right
control from one guarding the wrong control on the same screen - only reading
the screen does that, and it was read once, by hand, on 4 September 2026. What
this catches is the next screen, or the next button on an existing screen, added
by somebody who did not know the rule. That is the failure that actually
happens.

Two real gaps were found by running this the first time, and both were the kind
that only shows up in somebody's hand: RunScreen fires its pour ON MOUNT rather
than from a button, so gating the two doors that lead to it left a viewer able
to start watering by arriving; and the Wi-Fi scan had no check of its own.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.test_mobile_perms_match_server import (
    CARE_JS, _client_actions, _perms_map,
)

MOBILE = Path(__file__).resolve().parent.parent.parent / "mobile"
NAV_JS = MOBILE / "src" / "navigation" / "AppNavigator.js"

# (file relative to mobile/, action) -> why no can() sits at the call site.
# Adding a row here is a deliberate act with a reason attached, which is the
# point: the alternative is a silent exception nobody revisits.
EXPLAINED = {
    ("src/screens/AlarmScreen.js", "fillTray"):
        "one Act button covers water and tray; it is gated on waterSection and "
        "both are admin+operator, so one check is the same check",
    ("src/screens/TodayScreen.js", "trayCheckAll"):
        "issued by the Check button alongside planAll, which gates it; the two "
        "go out in one call and share admin+operator",
    ("src/screens/SectionDetailScreen.js", "requestDeviceScan"):
        "only reachable from the Wi-Fi dialog, whose single door is gated on "
        "setNodeWifi (admin), so a check here would always be true where it runs",
    ("src/hooks/usePushAlarms.js", "registerPushToken"):
        "every signed-in role may register for alarms, and the hook only mounts "
        "for a member of a farm",
}

# Not screens. careV2 declares the actions; perms.js and auth.js name them in
# the map and in a doc example.
SKIP = {
    "src/services/careV2.js",
    "src/config/perms.js",
    "src/config/auth.js",
}


def _write_actions() -> set[str]:
    return {name for name, (method, _p) in _client_actions().items()
            if method != "GET"}


def _admin_guarded_screens() -> set[str]:
    """Screens whose ROUTE actually mounts an AdminOnly-wrapped component.

    Two steps, not one, and the second is the one that matters. Reading only the
    `adminOnly(FooScreen, ...)` calls says a guard was BUILT; it does not say the
    route uses it. Unwiring `component={FooGuarded}` back to `component={FooScreen}`
    leaves the factory call sitting there, unused and perfectly convincing - a
    mutation that passed this test until it was written this way.
    """
    src = NAV_JS.read_text(encoding="utf-8")
    # const FooGuarded = adminOnly(FooScreen, '...')
    built = dict(re.findall(r"const\s+(\w+)\s*=\s*adminOnly\((\w+),", src))
    # <Stack.Screen name="Foo" component={FooGuarded} />
    mounted = set(re.findall(r"<Stack\.Screen[^>]*component=\{(\w+)\}", src))
    return {screen for wrapper, screen in built.items() if wrapper in mounted}


def _js_files():
    for p in sorted((MOBILE / "src").rglob("*.js")):
        rel = p.relative_to(MOBILE).as_posix()
        if rel not in SKIP:
            yield rel, p


def test_every_reachable_write_control_is_gated():
    writes = _write_actions()
    guarded = _admin_guarded_screens()
    assert guarded, "AppNavigator no longer wraps anything in AdminOnly"

    ungated = []
    for rel, path in _js_files():
        src = path.read_text(encoding="utf-8")
        screen = path.stem
        for action in sorted(writes):
            if not re.search(rf"\b{action}\b", src):
                continue
            if re.search(rf"can\('{action}'\)", src):
                continue                       # checked at the control
            if screen in guarded:
                continue                       # whole screen is admin-only
            if (rel, action) in EXPLAINED:
                continue                       # deliberate, with a reason
            ungated.append(f"{rel}: {action}")

    assert ungated == [], (
        "these can trigger a write with no check on the account, so the button "
        "exists only to come back 403:\n  " + "\n  ".join(ungated))


def test_explained_entries_still_apply():
    """A reason that has outlived its file is worse than no reason.

    An EXPLAINED row for a call site that no longer exists reads as considered
    coverage while covering nothing, and the next person adding that action to
    that file inherits the exemption without ever seeing it.
    """
    stale = []
    for (rel, action), _why in sorted(EXPLAINED.items()):
        path = MOBILE / rel
        if not path.exists():
            stale.append(f"{rel} no longer exists (exempting {action})")
            continue
        if not re.search(rf"\b{action}\b", path.read_text(encoding="utf-8")):
            stale.append(f"{rel} no longer calls {action}")
    assert stale == [], "stale exemptions: " + "; ".join(stale)


def test_the_admin_only_screens_are_actually_admin_only():
    """Every screen behind AdminOnly does only admin things.

    If one of them grows an admin+operator action, the blanket guard starts
    denying an operator something the server would allow - the opposite failure
    to the one this file mostly watches for, and just as invisible.
    """
    perms = _perms_map()
    writes = _write_actions()
    wrong = []
    for rel, path in _js_files():
        if path.stem not in _admin_guarded_screens():
            continue
        src = path.read_text(encoding="utf-8")
        for action in sorted(writes):
            if re.search(rf"\b{action}\b", src) and perms.get(action) != ["admin"]:
                wrong.append(f"{rel}: {action} is {'/'.join(perms.get(action, []))}")
    assert wrong == [], (
        "these screens are behind AdminOnly but contain actions an operator is "
        "allowed, so the guard denies more than the server does:\n  "
        + "\n  ".join(wrong))
