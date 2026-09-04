"""The app's permission map says the same thing the server enforces.

There are now two statements of who may do what: `require_role` on each route,
and `mobile/src/config/perms.js`, which decides whether the app draws a button.
Two copies of a truth is how a truth rots. The server's copy is the one that
matters - a viewer who reaches an admin endpoint gets a 403 whatever the app
believes - so the failure mode is not a breach, it is a button that exists only
to fail, which is its own kind of broken: the operator presses it, something
refuses, and nothing on the screen explains why.

So this rebuilds the map from the live app on every run and compares.

WHAT IT DOES AND DOES NOT PROVE, said plainly rather than left to be found out.
It proves the two agree about the actions careV2.js declares. It cannot prove a
screen actually consults the map before drawing a control - only reading the
screen does that - and it says nothing about routes the app never calls.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
CARE_JS = REPO / "mobile" / "src" / "services" / "careV2.js"
PERMS_JS = REPO / "mobile" / "src" / "config" / "perms.js"

EVERYONE = ["admin", "operator", "viewer"]

# The three fetch helpers in careV2.js and the base each one prefixes.
BASES = {
    "req": "/api/v2/care",
    "autoReq": "/api/v2/auto",
    "devReq": "/api/v2/devices",
}


def _norm(path: str) -> str:
    """Make a JS template path and a FastAPI path comparable.

    `/houses/${h}/sections/${s}/water` and
    `/houses/{house_id}/sections/{section_id}/water` are the same route; the
    names of the placeholders are not part of the contract, their positions are.
    """
    path = re.sub(r"\$\{[^}]*\}", "*", path)
    path = re.sub(r"\{[^}]*\}", "*", path)
    return path.split("?")[0].rstrip("/") or "/"


def _server_table() -> dict[tuple[str, str], list[str]]:
    """(METHOD, normalised path) -> the roles the route accepts.

    Read off the dependency, not off a decorator or a docstring: the dependency
    is what actually runs. `require_role` returns a closure named `_dep` whose
    `allowed` tuple is the permission, so that is what gets read.
    """
    from app.main import app

    table: dict[tuple[str, str], list[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v2"):
            continue
        dependant = getattr(route, "dependant", None)
        roles: list[str] | None = None
        if dependant is not None:
            for dep in dependant.dependencies:
                fn = dep.call
                name = getattr(fn, "__name__", "")
                if name == "_dep":
                    allowed = inspect.getclosurevars(fn).nonlocals.get("allowed")
                    roles = sorted(allowed or ())
                elif name == "require_auth" and roles is None:
                    # Any signed-in member of the tenant.
                    roles = list(EVERYONE)
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            table[(method, _norm(path))] = roles
    return table


# `export const NAME = (args) => helper(`path`, { method: 'PUT' ... });`
_ACTION = re.compile(
    r"export const (\w+)\s*=[^;]*?\b(req|autoReq|devReq)\(\s*[`'\"]([^`'\"]*)[`'\"]"
    r"(.*?);",
    re.S,
)


def _client_actions() -> dict[str, tuple[str, str]]:
    """action name -> (METHOD, normalised full path) from careV2.js."""
    src = CARE_JS.read_text(encoding="utf-8")
    out: dict[str, tuple[str, str]] = {}
    for name, helper, path, rest in _ACTION.findall(src):
        method = re.search(r"method:\s*'(\w+)'", rest)
        out[name] = (method.group(1) if method else "GET",
                     _norm(BASES[helper] + path))
    return out


def _perms_map() -> dict[str, list[str]]:
    """The PERMS object out of perms.js.

    perms.js is plain data with no expressions in it, so the object body is
    turned into JSON rather than evaluated. If it ever stops being plain data
    this will raise, loudly, which is the right moment to emit a perms.json from
    the JS instead of parsing it - not the moment to make the regex cleverer.
    """
    src = PERMS_JS.read_text(encoding="utf-8")
    start = src.index("export const PERMS = {") + len("export const PERMS = ")
    depth, end = 0, None
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    assert end is not None, "PERMS object is not closed in perms.js"
    body = src[start:end]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)   # block comments
    body = re.sub(r"//[^\n]*", "", body)                # line comments
    body = re.sub(r",(\s*[}\]])", r"\1", body)          # trailing commas
    body = re.sub(r"(\w+)\s*:", r'"\1":', body)         # bare keys
    body = body.replace("'", '"')
    return json.loads(body)


def test_every_client_action_hits_a_real_route():
    """A call the server has no route for is a 404 waiting in somebody's hand."""
    server = _server_table()
    orphans = [
        f"{name}: {method} {path}"
        for name, (method, path) in sorted(_client_actions().items())
        if (method, path) not in server
    ]
    assert orphans == [], (
        "careV2.js calls endpoints that do not exist on the server: "
        + "; ".join(orphans))


def test_perms_map_agrees_with_the_server():
    server = _server_table()
    actions = _client_actions()
    perms = _perms_map()

    problems = []
    for name, (method, path) in sorted(actions.items()):
        expected = server.get((method, path))
        if expected is None:
            continue                       # the test above owns this failure
        actual = perms.get(name)
        if actual is None:
            problems.append(
                f"{name} is missing from perms.js; the server wants "
                f"{'/'.join(expected)} for {method} {path}")
        elif sorted(actual) != sorted(expected):
            problems.append(
                f"{name}: perms.js says {'/'.join(sorted(actual))}, "
                f"the server enforces {'/'.join(expected)} on {method} {path}")

    assert problems == [], (
        "the app would offer controls the server refuses, or hide ones it "
        "allows:\n  " + "\n  ".join(problems))


def test_perms_map_has_no_entries_the_app_never_uses():
    """A stale entry is a rule nobody applies and everybody trusts."""
    actions = _client_actions()
    extra = sorted(set(_perms_map()) - set(actions))
    assert extra == [], (
        "perms.js names actions careV2.js does not have: " + ", ".join(extra))


def test_can_defaults_to_admin_only():
    """The unknown-action default is the safe direction, and is pinned here.

    An action somebody forgets to add should be hidden from a viewer, not shown
    to one. That default lives in JS; this asserts the JS still says so, because
    flipping it is a one-word change with no other visible effect.
    """
    src = PERMS_JS.read_text(encoding="utf-8")
    assert "PERMS[action] || ['admin']" in src, (
        "can() must fall back to admin-only for an unknown action")


@pytest.mark.parametrize("role,action,allowed", [
    ("viewer", "waterSection", False),
    ("operator", "waterSection", True),
    ("admin", "waterSection", True),
    ("operator", "deleteHouse", False),
    ("admin", "deleteHouse", True),
    ("viewer", "getOverview", True),
])
def test_the_cases_that_matter_by_name(role, action, allowed):
    """The four sentences the spec promised, spelled out.

    Derivation is only as good as its matching, and a rule that quietly matched
    nothing would let every other test here pass. These are named, so they fail
    if the plumbing silently stops finding anything.
    """
    perms = _perms_map()
    assert action in perms, f"{action} is not in perms.js at all"
    assert (role in perms[action]) is allowed
