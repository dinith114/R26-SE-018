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
