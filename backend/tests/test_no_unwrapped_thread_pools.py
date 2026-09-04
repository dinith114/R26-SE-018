"""Every thread pool in the backend carries the tenant into its workers.

A ContextVar does not cross a thread boundary. The plan for this stage named
`_run_per_section` as "the" thread pool and wrapped it; there were two, and the
second - `set_mode_all` - went unwrapped for the whole stage. It did not fail
quietly: the chokepoint raised NoTenantInContext on every call and wrote
nothing. It failed loudly into a silence, because no test called that endpoint.

So this asserts on the source rather than on behaviour, deliberately. The defect
is an ABSENT wrapper, which has no behavioural surface at all until somebody
calls the one endpoint that uses that pool - and `/mode-all` is exported by the
mobile app but not yet called by any screen, so the endpoint sat broken behind a
button nobody had wired up.

It is a tripwire, not a proof. A pool built in a helper, or a `submit` written
across several lines, would slip past it. The behavioural test for each endpoint
is still the real cover; this is the cheap check that catches the next one added
by hand.
"""
import ast
import pathlib


def _pool_dispatches(tree: ast.AST):
    """Every `<something>.submit(...)` and `<something>.map(...)` call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("submit", "map"):
            yield node


def test_every_thread_pool_dispatch_copies_the_context():
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []

    for path in sorted(root.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "ThreadPoolExecutor" not in src:
            continue
        tree = ast.parse(src)
        for call in _pool_dispatches(tree):
            # `copy_context()` may appear as the dispatched callable itself
            # (`pool.submit(copy_context().run, fn, ...)`) or inside a lambda
            # (`pool.map(lambda j: copy_context().run(fn, ...), jobs)`).
            segment = ast.get_source_segment(src, call) or ""
            if "copy_context" in segment:
                continue
            offenders.append(
                f"{path.relative_to(root)}:{call.lineno}: {segment.splitlines()[0]}")

    assert offenders == [], (
        "these dispatch work to a thread without carrying the tenant, so every "
        "worker will raise NoTenantInContext: " + "; ".join(offenders))
