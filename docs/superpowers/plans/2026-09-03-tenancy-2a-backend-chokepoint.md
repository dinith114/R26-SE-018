# Tenancy Cutover 2A — Backend Chokepoint

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every farm read and write onto `/tenants/{id}/farm/...` through a single chokepoint that cannot be bypassed, and guard the farm routes with the roles Stage 1 built.

**Architecture:** A `ContextVar` holds the caller's tenant. The three Firebase helpers rewrite any path beginning `/farm/` onto that tenant, and **raise** when none is set — so a code path that forgets fails loudly instead of silently using the old shared tree. All 127 existing call sites keep their literal paths and change not at all.

**Tech Stack:** Python 3.12, FastAPI 0.115.0, `contextvars` (stdlib), pytest 8.3.0.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`

## Global Constraints

- **This plan is NOT deployed on its own.** It is one of four parts of an atomic cutover (2A backend, 2B firmware, 2C mobile, 2D migration). The sensor nodes write to Firebase directly on a path compiled into their firmware, and the app holds the database URL itself — deploying this alone takes the farm dark and makes every farm route raise. Build it, test it, merge it; do not deploy until 2B, 2C and 2D are ready.
- `_scoped()` **must raise when no tenant is in context.** Never fall back to `/farm/...`. That fallback is precisely the shared-tree bug this design exists to prevent, and it would be invisible.
- Only paths starting `/farm/` are rewritten. `/devices/...` is a deliberately global registry; `/tenants/...` is already absolute; v1's `/latest.json` and `/prediction.json` must pass through untouched.
- `firebase_admin` must NEVER be imported at module load.
- Roles are exactly `"admin"`, `"operator"`, `"viewer"`.
- Python 3.12-compatible syntax only. Tests run with plain `python` on PATH.
- Commit messages: plain sentences. No `feat:`/`chore:`/`fix:` prefixes. NEVER a `Co-Authored-By` trailer.
- Do not touch firmware, mobile, or `ml_pipeline` — those are 2B and 2C.
- The `X-API-Key` middleware in `main.py` stays. It is removed in 2C, when the app has bearer tokens to replace it with.

## Where the helpers actually live — read before starting

Measured, not assumed:

```
_fb_get, _fb_put   defined in app/api/routes/smart_watering.py   (the v1 file)
_fb_delete         defined TWICE: smart_care_v2.py:59 and devices.py:78
direct _req.delete on a /farm path: automation.py:277  (bypasses all helpers)

importers: devices.py, forecast.py, house_planner.py, smart_care_v2.py,
           app/services/tenant_store.py
```

`tenant_store.py` uses these helpers for `/tenants/{t}/...` paths, which do not
start with `/farm/` and so pass through unscoped. That is correct and must stay
correct — a test pins it.

---

### Task 1: The tenant context and the scoping rule

**Files:**
- Create: `backend/app/services/tenant_context.py`
- Create: `backend/tests/test_tenant_context.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TENANT: ContextVar[Optional[str]]`
  - `set_tenant(tenant_id: str | None) -> Token` and `reset_tenant(token) -> None`
  - `current_tenant() -> str | None`
  - `scoped(path: str) -> str` — rewrites `/farm/...`, raises `NoTenantInContext` otherwise
  - `class NoTenantInContext(RuntimeError)`
  - `tenant_scope(tenant_id)` — a context manager, for the engine's per-tenant loop

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tenant_context.py`:

```python
"""The one rule every farm path in this process goes through.

The whole design rests on two properties: a farm path is rewritten onto the
caller's tenant, and a farm path with NO tenant is an error rather than a quiet
read of the old shared tree. Everything else is plumbing.
"""
import pytest

from app.services.tenant_context import (
    NoTenantInContext, current_tenant, reset_tenant, scoped, set_tenant,
    tenant_scope,
)


@pytest.fixture(autouse=True)
def _clear():
    tok = set_tenant(None)
    yield
    reset_tenant(tok)


def test_a_farm_path_is_rewritten_onto_the_tenant():
    set_tenant("t_abc")
    assert scoped("/farm/houses.json") == "/tenants/t_abc/farm/houses.json"
    assert (scoped("/farm/houses/H1/sections/S1/latest.json")
            == "/tenants/t_abc/farm/houses/H1/sections/S1/latest.json")


def test_a_farm_path_with_no_tenant_raises():
    """The property the whole design rests on. Falling back to /farm/... would
    read the old shared tree, silently, and no test would catch it."""
    with pytest.raises(NoTenantInContext):
        scoped("/farm/houses.json")


def test_paths_that_are_not_farm_paths_pass_through_untouched():
    """/devices is a deliberately global registry, /tenants is already absolute,
    and the v1 routes still use /latest and /prediction. None of them are the
    caller's farm and none may be rewritten - with or without a tenant set."""
    for path in ("/devices/AABBCC.json",
                 "/tenants/t_abc/users.json",
                 "/latest.json",
                 "/prediction.json"):
        assert scoped(path) == path
        set_tenant("t_abc")
        assert scoped(path) == path
        set_tenant(None)


def test_a_path_that_merely_starts_with_the_letters_farm_is_not_a_farm_path():
    """`/farmhouse.json` is not `/farm/...`. Prefix matching has to be on the
    separator, or a future sibling key gets silently rewritten."""
    set_tenant("t_abc")
    assert scoped("/farmhouse.json") == "/farmhouse.json"
    assert scoped("/farm.json") == "/farm.json"


def test_current_tenant_reports_what_is_set():
    assert current_tenant() is None
    set_tenant("t_abc")
    assert current_tenant() == "t_abc"


def test_tenant_scope_restores_the_previous_value():
    set_tenant("t_outer")
    with tenant_scope("t_inner"):
        assert current_tenant() == "t_inner"
    assert current_tenant() == "t_outer"


def test_tenant_scope_restores_even_when_the_body_raises():
    set_tenant("t_outer")
    with pytest.raises(ValueError):
        with tenant_scope("t_inner"):
            raise ValueError("boom")
    assert current_tenant() == "t_outer"


def test_an_empty_tenant_id_is_refused_at_the_door():
    """An empty string is not a tenant. Accepting it would build
    `/tenants//farm/...`, which Firebase treats as a different path again."""
    with pytest.raises(ValueError):
        set_tenant("")
    with pytest.raises(ValueError):
        with tenant_scope(""):
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tenant_context.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tenant_context'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/tenant_context.py`:

```python
"""Which tenant's farm this piece of work belongs to.

WHY A CONTEXTVAR AND NOT A PARAMETER. Threading a tenant id through the code
would mean 74 function signatures and every one of their callers - measured, not
estimated - and the failure mode of missing one is silent: that call site keeps
reading and writing the old shared /farm/... tree, which no test naturally
covers. Here there is nothing to miss. Every farm path in the process is
rewritten at one place, and a piece of work with no tenant raises rather than
guessing.

WHAT IS AND IS NOT SCOPED. Only paths under `/farm/`. `/devices/...` is a global
registry by design - a board belongs to no tenant until it is flashed with one -
`/tenants/...` is already absolute, and the v1 routes still read `/latest.json`
and `/prediction.json`. Rewriting any of those would break them.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar, Token
from typing import Optional

FARM_PREFIX = "/farm/"
TENANT: ContextVar[Optional[str]] = ContextVar("orchid_tenant", default=None)


class NoTenantInContext(RuntimeError):
    """A farm path was used by work that does not know whose farm it is."""


def set_tenant(tenant_id: Optional[str]) -> Token:
    """Set the tenant for this context. Returns a token for `reset_tenant`."""
    if tenant_id is not None and not str(tenant_id).strip():
        # `/tenants//farm/...` is a different path to Firebase, not an error,
        # so an empty id would write somewhere real and wrong.
        raise ValueError("tenant id may not be empty")
    return TENANT.set(tenant_id)


def reset_tenant(token: Token) -> None:
    TENANT.reset(token)


def current_tenant() -> Optional[str]:
    return TENANT.get()


@contextlib.contextmanager
def tenant_scope(tenant_id: str):
    """Run a block as one tenant, restoring whatever was set before.

    The engine's per-tenant loop uses this: one pass over the farm, once per
    tenant, with no chance of the previous tenant's id leaking into the next
    iteration because the body raised.
    """
    token = set_tenant(tenant_id)
    try:
        yield
    finally:
        reset_tenant(token)


def scoped(path: str) -> str:
    """A farm path, rewritten onto the current tenant.

    RAISES when a farm path is used with no tenant in context. That is the point
    of the whole design: falling back to `/farm/...` would read and write the old
    shared tree, do it silently, and be invisible to every test.
    """
    if not path.startswith(FARM_PREFIX):
        return path
    tenant = TENANT.get()
    if tenant is None:
        raise NoTenantInContext(
            f"farm path {path!r} used with no tenant in context")
    return f"/tenants/{tenant}{path}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tenant_context.py -q`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tenant_context.py backend/tests/test_tenant_context.py
git commit -m "Add the tenant context that every farm path will go through

Threading a tenant id through the code would mean 74 function signatures and
every one of their callers, measured rather than estimated, and the failure mode
of missing one is silent - that call site keeps using the old shared tree and no
test naturally covers whether we remembered it.

So the rewrite happens at one place, and a farm path with no tenant in context
raises. Falling back to /farm/... would reintroduce exactly the bug this exists
to prevent, invisibly. Only /farm/ paths are touched: /devices is a global
registry by design, /tenants is already absolute, and the v1 routes still read
/latest and /prediction."
```

---

### Task 2: Put the chokepoint in the Firebase helpers

**Files:**
- Modify: `backend/app/api/routes/smart_watering.py` (`_fb_get`, `_fb_put`)
- Modify: `backend/app/api/routes/smart_care_v2.py` (`_fb_delete`, and remove `_tpath`)
- Modify: `backend/app/api/routes/devices.py` (its own `_fb_delete`)
- Modify: `backend/app/api/routes/automation.py` (the direct `_req.delete` at line 277)
- Delete: `backend/tests/test_tpath.py`
- Create: `backend/tests/test_scoping_chokepoint.py`

**Interfaces:**
- Consumes: `scoped`, `set_tenant`, `NoTenantInContext` from `app.services.tenant_context`.
- Produces: no new public names. Every existing helper keeps its signature; only what it does to the path changes.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scoping_chokepoint.py`:

```python
"""Every farm path in the process really does go through the chokepoint.

These tests do not care what the helpers return. They care about the URL that
would have been requested, because that is the thing the design is about. The
`requests` module each helper uses is replaced, and the URL recorded.
"""
import pytest

from app.api.routes import devices, smart_care_v2, smart_watering
from app.services.tenant_context import NoTenantInContext, set_tenant


class _Recorder:
    """Stands in for `requests`, remembering the URL and reporting success."""

    def __init__(self):
        self.urls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True}

    def _record(self, url, **kw):
        self.urls.append(url)
        return self._Resp()

    get = put = delete = patch = post = _record


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(smart_watering, "_req", r)
    monkeypatch.setattr(smart_care_v2, "_req", r)
    monkeypatch.setattr(devices, "_req", r)
    tok = set_tenant(None)
    yield r
    from app.services.tenant_context import reset_tenant
    reset_tenant(tok)


def test_fb_get_and_put_rewrite_a_farm_path(rec):
    set_tenant("t_abc")
    smart_watering._fb_get("/farm/houses.json")
    smart_watering._fb_put("/farm/houses/H1/meta.json", {"name": "x"})
    assert all("/tenants/t_abc/farm/" in u for u in rec.urls), rec.urls
    assert not any(u.endswith("//farm/houses.json") for u in rec.urls)


def test_both_delete_helpers_rewrite_a_farm_path(rec):
    """_fb_delete is defined twice, in smart_care_v2 and in devices. Both are
    real code paths and both have to be scoped - one of them being missed is
    exactly the kind of gap this whole chokepoint exists to make impossible."""
    set_tenant("t_abc")
    smart_care_v2._fb_delete("/farm/houses/H1.json")
    devices._fb_delete("/farm/houses/H2.json")
    assert len(rec.urls) == 2
    assert all("/tenants/t_abc/farm/houses/" in u for u in rec.urls), rec.urls


def test_a_farm_path_with_no_tenant_raises_rather_than_using_the_shared_tree(rec):
    for call in (lambda: smart_watering._fb_get("/farm/houses.json"),
                 lambda: smart_watering._fb_put("/farm/houses.json", {}),
                 lambda: smart_care_v2._fb_delete("/farm/houses.json"),
                 lambda: devices._fb_delete("/farm/houses.json")):
        with pytest.raises(NoTenantInContext):
            call()
    assert rec.urls == [], "a request was sent with no tenant in context"


def test_non_farm_paths_are_untouched_and_need_no_tenant(rec):
    """The device registry is global, the tenants tree is absolute, and the v1
    routes still read /latest. None of them may be rewritten, and none of them
    may require a tenant to be set."""
    smart_watering._fb_get("/devices/AABBCC.json")
    smart_watering._fb_get("/tenants/t_x/users.json")
    smart_watering._fb_get("/latest.json")
    assert rec.urls == [
        smart_watering.FIREBASE_BASE_URL + "/devices/AABBCC.json",
        smart_watering.FIREBASE_BASE_URL + "/tenants/t_x/users.json",
        smart_watering.FIREBASE_BASE_URL + "/latest.json",
    ]


def test_the_push_token_delete_no_longer_bypasses_the_helpers():
    """automation.py deleted a /farm/pushTokens path with a raw _req.delete,
    the one call in the codebase that went round the helpers. A single bypass is
    all it takes to keep writing to the shared tree."""
    import inspect

    from app.api.routes import automation
    src = inspect.getsource(automation)
    offenders = [line.strip() for line in src.splitlines()
                 if "_req.delete" in line and "/farm/" in line]
    assert offenders == [], offenders


def test_tpath_is_gone():
    """Stage 1 added it inert as a seam. The chokepoint supersedes it, and a
    second way to build a farm path is a second thing to forget."""
    assert not hasattr(smart_care_v2, "_tpath")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_scoping_chokepoint.py -q`
Expected: FAIL — the helpers send unscoped URLs, and `_tpath` still exists.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/routes/smart_watering.py`, add the import at the top of the Firebase helpers section and scope both functions:

```python
from app.services.tenant_context import scoped


def _fb_get(path: str) -> Optional[dict]:
    try:
        resp = _req.get(f"{FIREBASE_BASE_URL}{scoped(path)}", timeout=8)
        return resp.json() if resp.status_code == 200 else None
    except NoTenantInContext:
        raise
    except Exception:
        return None


def _fb_put(path: str, data: dict) -> bool:
    try:
        resp = _req.put(f"{FIREBASE_BASE_URL}{scoped(path)}", json=data, timeout=8)
        return resp.status_code == 200
    except NoTenantInContext:
        raise
    except Exception:
        return False
```

`NoTenantInContext` must also be imported. **The re-raise matters:** these
helpers swallow every exception by design, and swallowing this one would turn a
missing tenant into a silent `None`/`False` — the exact silence the chokepoint
exists to break.

Apply the identical change to `_fb_delete` in `smart_care_v2.py` and to the
separate `_fb_delete` in `devices.py`.

In `smart_care_v2.py`, delete the whole `_tpath` function.

In `automation.py`, replace the direct delete at line 277:

```python
                _fb_delete(f"/farm/pushTokens/{k}.json")
```

importing `_fb_delete` from `smart_care_v2` alongside the other helpers it
already imports. This was the one call in the codebase that went round the
helpers, and one bypass is all it takes.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_scoping_chokepoint.py -q`
Expected: PASS, 6 passed

Then confirm what broke, deliberately: `cd backend && python -m pytest tests/ -q`
Expected: FAILURES in the older suites that call farm paths with no tenant set —
that is the chokepoint working. Task 3 fixes them properly. Record the count in
your report; do not paper over them here.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/smart_watering.py backend/app/api/routes/smart_care_v2.py \
        backend/app/api/routes/devices.py backend/app/api/routes/automation.py \
        backend/tests/test_scoping_chokepoint.py
git rm backend/tests/test_tpath.py
git commit -m "Route every farm path through the tenant chokepoint

All 127 call sites keep their literal /farm/... strings; the three helpers
rewrite them. _fb_delete is defined twice, in smart_care_v2 and in devices, and
both are live code paths - a test pins both, because one of them being missed is
the kind of gap the chokepoint exists to make impossible.

The helpers swallow every exception by design, so they now re-raise
NoTenantInContext specifically. Swallowing it would turn a missing tenant into a
silent None or False, which is the silence this is meant to break.

automation.py deleted a push token with a raw _req.delete against
FIREBASE_BASE_URL - the one call that went round the helpers. It goes through
_fb_delete now. _tpath is removed: a second way to build a farm path is a second
thing to forget."
```

---

### Task 3: Set the tenant — on requests, in the engine, and across the thread pool

**Files:**
- Modify: `backend/app/api/deps.py` (`require_auth` sets the context)
- Modify: `backend/app/api/routes/smart_care_v2.py` (`_run_per_section`'s thread pool)
- Modify: `backend/app/api/routes/automation.py` (per-tenant engine loop)
- Create: `backend/tests/test_tenant_propagation.py`

**Interfaces:**
- Consumes: `set_tenant`, `tenant_scope`, `current_tenant` from `app.services.tenant_context`.
- Produces: `automation.run_all_tenants(now) -> dict` — one engine pass per tenant, keyed by tenant id.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tenant_propagation.py`:

```python
"""The tenant reaches the places that actually do the work.

Three of them, and each fails differently when it does not:
  * a request - every farm route raises
  * the thread pool - every section raises, because ContextVar does not cross
    a thread boundary on its own
  * the engine - it has no request to inherit from at all
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_auth
from app.services.firebase_auth import ROLE_ADMIN, AuthContext, set_decoder
from app.services.tenant_context import current_tenant, set_tenant, tenant_scope


@pytest.fixture(autouse=True)
def _clean():
    tok = set_tenant(None)
    yield
    from app.services.tenant_context import reset_tenant
    reset_tenant(tok)
    set_decoder(None)


def test_require_auth_puts_the_callers_tenant_in_context():
    set_decoder(lambda t: {"uid": "u1", "tenantId": "t_abc", "role": ROLE_ADMIN})

    app = FastAPI()

    @app.get("/whose")
    def whose(ctx: AuthContext = Depends(require_auth)):
        return {"tenant": current_tenant()}

    r = TestClient(app).get("/whose", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"tenant": "t_abc"}


def test_the_thread_pool_carries_the_tenant():
    """ContextVar does NOT cross a thread boundary on its own. _run_per_section
    fans every section out across a pool, so without copy_context every section
    in a parallel pass raises 'no tenant in context' - and it would look like a
    Firebase problem, not a threading one."""
    from app.api.routes.smart_care_v2 import _run_per_section

    houses = {"H1": {"sections": {"S1": {"latest": {"temperature": 25}},
                                  "S2": {"latest": {"temperature": 26}}}}}

    with tenant_scope("t_abc"):
        seen = _run_per_section(houses, lambda h, s, sec: current_tenant())

    assert seen == {"H1-S1": "t_abc", "H1-S2": "t_abc"}


def test_the_engine_runs_one_pass_per_tenant_each_in_its_own_context(monkeypatch):
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_a": True, "t_b": True}
                        if path == "/tenants.json" else {})

    seen = []
    monkeypatch.setattr(automation, "_engine_pass",
                        lambda now: seen.append(current_tenant()))

    automation.run_all_tenants(now=None)
    assert sorted(seen) == ["t_a", "t_b"]


def test_one_tenants_failure_does_not_stop_the_next(monkeypatch):
    """A farm whose data is broken must not stop every other farm being
    watered. The engine has one job and it is to keep running."""
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_bad": True, "t_good": True}
                        if path == "/tenants.json" else {})

    done = []

    def _pass(now):
        t = current_tenant()
        if t == "t_bad":
            raise RuntimeError("this farm's data is broken")
        done.append(t)

    monkeypatch.setattr(automation, "_engine_pass", _pass)
    out = automation.run_all_tenants(now=None)

    assert done == ["t_good"]
    assert "t_bad" in out and "error" in str(out["t_bad"]).lower()


def test_the_context_does_not_leak_between_tenants(monkeypatch):
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_a": True} if path == "/tenants.json" else {})
    monkeypatch.setattr(automation, "_engine_pass", lambda now: None)

    automation.run_all_tenants(now=None)
    assert current_tenant() is None, "the last tenant was left in context"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tenant_propagation.py -q`
Expected: FAIL — `require_auth` does not set the context, and
`automation.run_all_tenants` does not exist.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/deps.py`, have `require_auth` set the context:

```python
from app.services.tenant_context import set_tenant


def require_auth(request: Request) -> AuthContext:
    """Any signed-in member of any tenant."""
    ctx = verify_bearer(request.headers.get("authorization"))
    if ctx is None:
        raise HTTPException(401, "Please sign in.")
    request.state.auth = ctx
    # Every farm path this request touches is rewritten onto this tenant. Set
    # here rather than per route, because a route that forgot would not fail
    # safely - it would fail loudly at the first farm read, which is better than
    # the old silent shared tree but is still an outage.
    set_tenant(ctx.tenant_id)
    return ctx
```

In `backend/app/api/routes/smart_care_v2.py`, carry the context into the pool.
Find `_run_per_section` and change the submit call:

```python
import contextvars

    ...
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        # ContextVar does not cross a thread boundary. Without copying the
        # context into each worker, every section in a parallel pass raises
        # "no tenant in context" - and it reads like a Firebase fault rather
        # than a threading one, which is a bad hour to spend.
        futures = {pool.submit(contextvars.copy_context().run, fn, hid, sid, s):
                   f"{hid}-{sid}" for hid, sid, s in jobs}
```

In `backend/app/api/routes/automation.py`, add the per-tenant loop and use it
from the engine loop:

```python
from app.services.tenant_context import tenant_scope


def run_all_tenants(now) -> dict:
    """One engine pass per tenant.

    The engine has no request to inherit a tenant from, so it sets one per
    iteration. Every tenant is attempted even if an earlier one fails: a farm
    with broken data must not stop every other farm being watered.
    """
    tenants = _fb_get("/tenants.json") or {}
    out = {}
    for tenant_id in tenants:
        try:
            with tenant_scope(tenant_id):
                out[tenant_id] = _engine_pass(now)
        except Exception as e:
            traceback.print_exc()
            out[tenant_id] = {"error": str(e)}
    return out
```

Change `_engine_loop` to call `run_all_tenants(farm_now())` in place of
`_engine_pass(farm_now())`, and change the `/engine/run-now` endpoint the same
way. `_state` is currently a single global dict; give it one entry per tenant so
one farm's `lastPlanDay` does not suppress another's plan:

```python
_state_by_tenant: Dict[str, Dict[str, object]] = {}


def _state_for(tenant_id: str) -> dict:
    """Per tenant, because lastPlanDay and lastTray are per farm.

    A single shared dict would let the first tenant's pass mark the day planned
    and every other tenant would then be skipped until tomorrow."""
    return _state_by_tenant.setdefault(tenant_id, {
        "running": False, "lastTick": None, "lastTray": None,
        "lastPlanDay": None, "ticks": 0, "errors": 0, "lastError": None,
    })
```

Replace every `_state[...]` use inside `_engine_pass` with
`_state_for(current_tenant())[...]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tenant_propagation.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/app/api/routes/smart_care_v2.py \
        backend/app/api/routes/automation.py backend/tests/test_tenant_propagation.py
git commit -m "Set the tenant on requests, in the engine, and across the thread pool

Three places do the work and each fails differently without a tenant. A request
gets one from require_auth. The engine has no request to inherit from, so it
sets one per iteration and keeps going when a tenant fails - a farm with broken
data must not stop every other farm being watered.

The thread pool is the one that would have cost an afternoon. ContextVar does
not cross a thread boundary, and _run_per_section fans every section out across
a pool, so without copying the context each worker raises no-tenant and it reads
like a Firebase fault rather than a threading one.

The engine's _state also becomes per tenant. Shared, the first tenant's pass
would mark the day planned and every other farm would be skipped until tomorrow."
```

---

### Task 4: Guard the farm routes, and prove isolation end to end

**Files:**
- Modify: `backend/app/api/routes/smart_care_v2.py` (route signatures gain a guard)
- Modify: `backend/app/api/routes/house_planner.py`, `devices.py`, `forecast.py` (same)
- Create: `backend/tests/test_farm_isolation.py`

**Interfaces:**
- Consumes: `require_auth`, `require_role` from `app.api.deps`.
- Produces: no new names.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_farm_isolation.py`:

```python
"""The property this entire stage exists for.

Two tenants, one fake database, real routing. Tenant A must not be able to see
or change anything of tenant B's, and the only thing separating them is the
token - there is no parameter either of them could change to reach the other.
"""
import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, set_decoder,
)


@pytest.fixture
def farm(monkeypatch):
    """A fake Firebase holding two tenants' farms, and a client over the real app."""
    db = {
        "/tenants/t_a/farm/houses.json": {"H1": {"meta": {"name": "Farm A"}}},
        "/tenants/t_b/farm/houses.json": {"H1": {"meta": {"name": "Farm B"}}},
    }

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200 if body is not None else 404

        def json(self):
            return self.body

    class _Req:
        def get(self, url, **kw):
            path = url.split("firebaseio.com", 1)[-1]
            return _Resp(db.get(path))

        def put(self, url, **kw):
            db[url.split("firebaseio.com", 1)[-1]] = kw.get("json")
            return _Resp({})

        delete = put

    from app.api.routes import devices, smart_care_v2, smart_watering
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)

    from app.main import app
    yield TestClient(app), db
    set_decoder(None)


def _tok(uid, tenant, role):
    return {"Authorization": f"Bearer {uid}@{tenant}@{role}"}


def test_a_farm_route_with_no_token_is_401(farm):
    client, _ = farm
    assert client.get("/api/v2/care/overview").status_code == 401


def test_each_tenant_sees_only_its_own_farm(farm):
    """The test this whole stage exists for. Same endpoint, same shape of
    request, and the only difference is whose token it is."""
    client, _ = farm
    a = client.get("/api/v2/care/overview", headers=_tok("ua", "t_a", ROLE_ADMIN))
    b = client.get("/api/v2/care/overview", headers=_tok("ub", "t_b", ROLE_ADMIN))
    assert a.status_code == 200 and b.status_code == 200
    assert "Farm A" in a.text and "Farm A" not in b.text
    assert "Farm B" in b.text and "Farm B" not in a.text


def test_a_viewer_cannot_water(farm):
    client, _ = farm
    r = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("v", "t_a", ROLE_VIEWER), json={"durationSec": 30})
    assert r.status_code == 403


def test_an_operator_can_water_but_cannot_change_the_mode(farm):
    client, _ = farm
    assert client.put("/api/v2/care/houses/H1/sections/S1/mode",
                      headers=_tok("o", "t_a", ROLE_OPERATOR),
                      json={"override": "manual"}).status_code == 403


def test_no_farm_write_ever_lands_outside_the_callers_tenant(farm):
    """Not "the response looked right" - the actual paths written. A leak here
    would be a write into another customer's farm."""
    client, db = farm
    before = set(db)
    client.post("/api/v2/care/houses/H1/sections/S1/water",
                headers=_tok("a", "t_a", ROLE_ADMIN), json={"durationSec": 30})
    written = set(db) - before
    assert written, "the request wrote nothing; the test proves nothing"
    for path in written:
        assert path.startswith("/tenants/t_a/") or path.startswith("/devices/"), path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_farm_isolation.py -q`
Expected: FAIL — the farm routes have no guard, so the unauthenticated call
returns something other than 401 and the tenant is never set.

- [ ] **Step 3: Write minimal implementation**

Add a guard to every route in `smart_care_v2.py`, `house_planner.py`,
`devices.py` and `forecast.py`, following the spec's table:

- read-only (`/overview`, `/houses/{h}`, `/…/history`, `/model-info`, `/alerts`,
  `/…/calibration`, `/…/events`, all of `forecast.py`, all GETs in `devices.py`)
  — `ctx: AuthContext = Depends(require_auth)`
- act-now (`/…/water`, `/…/tray-fill`, `/…/plan`, `/plan-all`, `/tray-check*`,
  `/…/stop`, `/…/fertilize`) — `Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))`
- configure (`/setup`, `/houses*` create/edit/delete, `/…/mode`, `/…/pumps`,
  `/…/wifi`, `/…/durations`, `/…/position`, `/…/master`, `/apply-placement`,
  `/…/analyze-placement`, device assign/unassign/interval/scan, everything in
  `automation.py` that changes state) — `Depends(require_role(ROLE_ADMIN))`

Add the parameter to each route function's signature. The body of every route
stays exactly as it is — the tenant reaches the Firebase helpers through the
context, not through the code.

`house_planner.py` and `forecast.py` import their helpers lazily inside
functions; those imports are unchanged, and the context is already set by the
time the route body runs.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_farm_isolation.py -q`
Expected: PASS, 5 passed

Then the whole suite: `cd backend && python -m pytest tests/ -q`
Expected: PASS. Older tests that call route functions directly may need a
`tenant_scope("t_test")` wrapper — add it to those tests, and do NOT weaken the
chokepoint to accommodate them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/ backend/tests/test_farm_isolation.py
git commit -m "Guard the farm routes and prove two tenants cannot see each other

Reads need a member, watering needs an operator, configuration needs an admin -
the table the spec set out. Every route body is unchanged: the tenant reaches
the Firebase helpers through the context rather than through the code, which is
the whole point of the chokepoint.

The isolation test asserts on the paths actually written, not on the response
looking right. A leak here would be a write into another customer's farm, and a
response-shaped assertion would not see it."
```

---

### Task 5: The CI list, and a clean-environment run

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `backend/requirements-ci.txt` if anything new is needed

- [ ] **Step 1: Add the four new test files to the pure-logic job**

`tests/test_tenant_context.py`, `tests/test_scoping_chokepoint.py`,
`tests/test_tenant_propagation.py`, `tests/test_farm_isolation.py`.
Remove `tests/test_tpath.py`, which no longer exists.

- [ ] **Step 2: Run the whole suite locally**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS, no failures.

- [ ] **Step 3: Run the exact CI command in a clean virtualenv**

`firebase-admin` is installed locally and would mask a module-load import.

```bash
python -m venv /tmp/civ3
/tmp/civ3/Scripts/python.exe -m pip install -q -r requirements-ci.txt
/tmp/civ3/Scripts/python.exe -m pytest -q --no-header <the full file list from tests.yml>
```
Expected: PASS. If a dependency is missing, add it to `requirements-ci.txt` with
a comment saying which test needs it and why.

- [ ] **Step 4: Prove the chokepoint cannot be bypassed**

This is the check that matters most, and it is a grep, not a test:

```bash
cd backend
grep -rn 'FIREBASE_BASE_URL' app/ --include=*.py | grep '_req\.'
```
Expected: exactly the helper definitions in `smart_watering.py`,
`smart_care_v2.py` and `devices.py` — and nothing else. Any other line is a path
that goes round the chokepoint. Put the output in your report.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tests.yml backend/requirements-ci.txt
git commit -m "Put the tenancy tests in CI

Also records the check that matters more than any of them: grepping for
_req calls against FIREBASE_BASE_URL should find the three helper definitions
and nothing else. Anything else is a path that goes round the chokepoint, and
one is all it takes."
```

---

## Definition of done for 2A

- `pytest tests/ -q` passes locally and in a clean CI-only virtualenv
- A farm path with no tenant in context raises `NoTenantInContext`; nothing falls back to `/farm/...`
- Two tenants' tokens against the same endpoint return only their own farm, proven on the paths written rather than the response shape
- A Viewer cannot water; an Operator cannot change the mode; reads need a member
- `grep FIREBASE_BASE_URL ... | grep _req\.` finds only the three helper definitions
- `_tpath` is gone

## Not in this plan

Firmware `TENANT_ID` and the reflash (2B), the mobile login screen and bearer
tokens (2C), the data migration script and the cutover runbook (2D), and closing
the Firebase rules (Stage 3). **None of 2A is deployed until 2B, 2C and 2D are
ready** — see the spec's cutover section.
