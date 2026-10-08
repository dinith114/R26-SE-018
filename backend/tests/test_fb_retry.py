"""A Firebase request that fails in transit is tried once more, and a write that
still fails is said out loud.

Found in the 8 Oct 2026 rehearsal. A co-location Start answered 200 while its
write never reached the database: a live stream on the house's meta showed the
second press land and nothing from the first. Both helpers gave up on the first
error and told nobody, so the app said "Started".
"""
import pytest

from app.api.routes import smart_watering as sw
from app.services.tenant_context import tenant_scope


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body

    def json(self):
        return self._body


class _Flaky:
    """Fails the first `fail` calls - by raising, or with a status code - then succeeds."""

    def __init__(self, fail=1, how=TimeoutError("read timed out"), body=None):
        self.calls, self.fail, self.how, self.body = [], fail, how, body

    def _go(self, url):
        self.calls.append(url)
        if len(self.calls) <= self.fail:
            if isinstance(self.how, int):
                return _Resp(self.how)
            raise self.how
        return _Resp(200, self.body)

    def get(self, url, **kw):
        return self._go(url)

    def put(self, url, **kw):
        return self._go(url)


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(sw, "FB_RETRY_DELAY_S", 0, raising=False)


def test_a_write_that_fails_once_is_retried(monkeypatch):
    req = _Flaky(fail=1)
    monkeypatch.setattr(sw, "_req", req)
    with tenant_scope("t_a"):
        assert sw._fb_put("/farm/houses/H1/meta.json", {"a": 1}) is True
    assert len(req.calls) == 2


def test_a_write_that_keeps_failing_is_reported(monkeypatch, capsys):
    req = _Flaky(fail=5)
    monkeypatch.setattr(sw, "_req", req)
    with tenant_scope("t_a"):
        assert sw._fb_put("/farm/houses/H1/meta.json", {"a": 1}) is False
    assert len(req.calls) == 2
    assert "[FB] PUT failed (TimeoutError): /farm/houses/H1/meta.json" in capsys.readouterr().out


def test_a_refusal_is_not_retried(monkeypatch):
    """A 401 or 404 will be the same a moment later; only transit failures are."""
    req = _Flaky(fail=5, how=401)
    monkeypatch.setattr(sw, "_req", req)
    with tenant_scope("t_a"):
        assert sw._fb_put("/farm/houses/H1/meta.json", {"a": 1}) is False
    assert len(req.calls) == 1


def test_a_read_that_fails_once_is_retried(monkeypatch):
    req = _Flaky(fail=1, how=503, body={"name": "H1"})
    monkeypatch.setattr(sw, "_req", req)
    with tenant_scope("t_a"):
        assert sw._fb_get("/farm/houses/H1/meta.json") == {"name": "H1"}
    assert len(req.calls) == 2
