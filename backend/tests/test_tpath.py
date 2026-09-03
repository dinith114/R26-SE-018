"""The seam Stage 2 turns on.

Added now, wired now, switched later. Stage 2 moves the farm subtree under
/tenants/{id}/farm and rewrites ~99 call sites; having the helper already in
place and already proven means that stage is a mechanical substitution rather
than a substitution plus a new function nobody has run.

While every caller passes None, this returns exactly today's paths - which is
the property that lets Stage 1 ship without touching farm behaviour at all.
"""
from app.api.routes.smart_care_v2 import _tpath


def test_no_tenant_gives_todays_path_exactly():
    assert _tpath(None, "houses.json") == "/farm/houses.json"
    assert _tpath("", "meta/autoMode.json") == "/farm/meta/autoMode.json"


def test_a_tenant_nests_the_same_suffix():
    assert _tpath("t_abc", "houses.json") == "/tenants/t_abc/farm/houses.json"


def test_a_leading_slash_on_the_suffix_is_tolerated():
    """Call sites are being rewritten by hand from f"/farm/..." strings, and
    one of them will keep the slash."""
    assert _tpath(None, "/houses.json") == "/farm/houses.json"
    assert _tpath("t_abc", "/houses.json") == "/tenants/t_abc/farm/houses.json"
