"""The two dependencies every guarded route uses.

Deliberately only two. Per-house access lists were considered and rejected in
the design: a tenant is one grower's operation, and a role that applies across
it is the whole of what this product needs. Adding a third axis here would be
paid for on every route and used by none.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.firebase_auth import AuthContext, verify_bearer


def require_auth(request: Request) -> AuthContext:
    """Any signed-in member of any tenant."""
    ctx = verify_bearer(request.headers.get("authorization"))
    if ctx is None:
        raise HTTPException(401, "Please sign in.")
    # Handy for logging and for routes that would rather read request.state.
    request.state.auth = ctx
    return ctx


def require_role(*allowed: str):
    """Membership plus one of `allowed`.

    The message names neither the required role nor the caller's own. A refusal
    should not double as documentation of the permission model for somebody
    probing the API.
    """
    def _dep(request: Request) -> AuthContext:
        ctx = require_auth(request)
        if ctx.role not in allowed:
            raise HTTPException(403, "Your account cannot do this.")
        return ctx
    return _dep
