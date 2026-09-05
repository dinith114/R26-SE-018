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
