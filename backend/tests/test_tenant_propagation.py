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
