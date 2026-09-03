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
