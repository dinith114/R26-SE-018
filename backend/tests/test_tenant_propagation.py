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
                        if path.startswith("/tenants.json") else {})

    seen = []
    monkeypatch.setattr(automation, "_engine_pass",
                        lambda now: seen.append(current_tenant()))
    monkeypatch.setattr(automation, "farm_now", lambda: None)

    automation.run_all_tenants()
    assert sorted(seen) == ["t_a", "t_b"]


def test_one_tenants_failure_does_not_stop_the_next(monkeypatch):
    """A farm whose data is broken must not stop every other farm being
    watered. The engine has one job and it is to keep running."""
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_bad": True, "t_good": True}
                        if path.startswith("/tenants.json") else {})

    done = []

    def _pass(now):
        t = current_tenant()
        if t == "t_bad":
            raise RuntimeError("this farm's data is broken")
        done.append(t)

    monkeypatch.setattr(automation, "_engine_pass", _pass)
    monkeypatch.setattr(automation, "farm_now", lambda: None)
    out = automation.run_all_tenants()

    assert done == ["t_good"]
    assert "t_bad" in out and "error" in str(out["t_bad"]).lower()


def test_the_context_does_not_leak_between_tenants(monkeypatch):
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_a": True} if path.startswith("/tenants.json") else {})
    monkeypatch.setattr(automation, "_engine_pass", lambda now: None)
    monkeypatch.setattr(automation, "farm_now", lambda: None)

    automation.run_all_tenants()
    assert current_tenant() is None, "the last tenant was left in context"


def test_run_now_covers_every_tenant(monkeypatch):
    """The endpoint both simulators drive their accelerated clock through.

    It called _engine_pass directly, outside any tenant scope, so every call
    raised on the first farm read and both simulators were dead. Nothing in the
    suite touched it, which is why CI stayed green through the breakage.
    """
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_a": True, "t_b": True}
                        if path.startswith("/tenants.json") else {})
    seen = []
    monkeypatch.setattr(automation, "_engine_pass",
                        lambda now: seen.append(current_tenant()))
    # A real datetime: run_now formats it into the response.
    from datetime import datetime, timedelta, timezone as _tz
    monkeypatch.setattr(automation, "farm_now",
                        lambda: datetime(2026, 9, 3, 6, 30,
                                         tzinfo=_tz(timedelta(minutes=330))))

    import asyncio
    out = asyncio.get_event_loop().run_until_complete(automation.run_now())

    assert sorted(seen) == ["t_a", "t_b"]
    assert set(out["did"]) == {"t_a", "t_b"}


def test_the_auto_switch_is_not_shared_between_farms(monkeypatch):
    """The worst thing this codebase could do.

    farm_auto_mode caches for five seconds, and run_all_tenants walks every
    tenant inside ONE tick - far inside that. Shared, the first farm's Auto
    switch would be applied to every other farm in the pass: one customer's
    Auto ON running another customer's pumps.
    """
    from app.api.routes import smart_care_v2 as care

    metas = {"t_on": {"autoMode": True}, "t_off": {"autoMode": False}}
    monkeypatch.setattr(care, "_fb_get", lambda path: metas[current_tenant()])
    care._auto_cache.clear()

    with tenant_scope("t_on"):
        assert care.farm_auto_mode() is True
    with tenant_scope("t_off"):
        assert care.farm_auto_mode() is False,             "the first farm's Auto switch leaked into the second"
    with tenant_scope("t_on"):
        assert care.farm_auto_mode() is True


def test_the_clock_is_not_shared_between_farms(monkeypatch):
    """A shared timezone shifts farm_now(), which hour counts as dawn, and when
    the plan day rolls over - so one farm would be watered on another's clock."""
    from app.api.routes import smart_care_v2 as care

    zones = {"t_lk": {"timezone": "Asia/Colombo"},
             "t_uk": {"timezone": "Etc/UTC"}}
    monkeypatch.setattr(care, "_fb_get", lambda path: zones[current_tenant()])
    care._tz_cache.clear()

    from datetime import datetime, timedelta
    instant = datetime(2026, 9, 3, 12, 0)      # a ZoneInfo needs an instant
    with tenant_scope("t_lk"):
        lk = care.farm_tz().utcoffset(instant)
    with tenant_scope("t_uk"):
        uk = care.farm_tz().utcoffset(instant)

    assert lk == timedelta(minutes=330)
    assert uk == timedelta(0), "the first farm's timezone leaked into the second"


def test_the_scheduled_loop_reaches_the_pass_at_all(monkeypatch):
    """The bug that made the whole engine silently dead.

    farm_now() reads /farm/meta.json. It was passed as an argument to
    asyncio.to_thread, so Python evaluated it BEFORE the call and outside every
    tenant scope - it raised each tick, the loop's own except swallowed it, and
    run_all_tenants was never reached. No plan, no tray check, no watering, on a
    system with real pumps, and the only symptom was a log line.

    The loop must therefore hand run_all_tenants nothing that touches a farm
    path. This asserts on the source, because the failure was in the argument
    expression rather than in anything the function did.
    """
    import inspect

    from app.api.routes import automation

    src = inspect.getsource(automation._engine_loop)
    assert "run_all_tenants" in src, "the loop no longer calls run_all_tenants"

    # The WHOLE body, not just the calling line. The first version of this test
    # only looked at the line containing run_all_tenants, which would have
    # missed the same bug written one line earlier:
    #     now = farm_now()
    #     await asyncio.to_thread(run_all_tenants, now)
    # Nothing in this loop may touch a farm path, wherever it is written.
    reads_a_farm_path = ("farm_now", "farm_tz", "get_auto_mode", "_fb_get")
    offenders = [ln.strip() for ln in src.splitlines()
                 if not ln.strip().startswith("#")
                 and any(name in ln for name in reads_a_farm_path)]
    assert offenders == [], (
        "the loop reads a farm path outside every tenant scope: %s" % offenders)


def test_each_farm_is_passed_its_own_clock(monkeypatch):
    """One `now` shared across tenants would let one farm's local hour decide
    another farm's dawn check and plan-day rollover."""
    from app.api.routes import automation

    monkeypatch.setattr(automation, "_fb_get",
                        lambda path: {"t_a": True, "t_b": True}
                        if path.startswith("/tenants.json") else {})
    clocks = {"t_a": "A-clock", "t_b": "B-clock"}
    monkeypatch.setattr(automation, "farm_now", lambda: clocks[current_tenant()])

    got = {}
    monkeypatch.setattr(automation, "_engine_pass",
                        lambda now: got.__setitem__(current_tenant(), now))

    automation.run_all_tenants()
    assert got == {"t_a": "A-clock", "t_b": "B-clock"}
