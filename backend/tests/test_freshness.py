"""Reading-freshness regression tests.

The bug these were written for: every section on the farm displayed
"161 days ago" as its last reading while the nodes were reporting normally.

Root cause: `_farm_now_ms` defined "now" as the newest reading ANYWHERE on the
farm, so a single section carrying a future-dated timestamp (the old browser
simulator's fast-forward clock, which had run on to 2027) dragged the farm clock
163 days ahead. Every genuinely-live section was then aged against that clock.

One bad row must never change how any other section is aged.
"""
import time

from app.api.routes.smart_care_v2 import _farm_now_ms, _freshness, _freshness_limits

MIN_MS = 60_000.0
DAY_MS = 86_400_000.0


def _now_ms() -> float:
    return time.time() * 1000.0


def _section(ts_ms):
    return {"latest": {"temperature": 30.0, "humidity": 65.0, "timestamp": ts_ms}}


def _farm(**sections):
    return {"H1": {"sections": sections}}


def test_future_dated_section_does_not_age_its_neighbours():
    """The reported bug, reduced: S1 is stamped 163 days ahead, S2 is current."""
    now = _now_ms()
    houses = _farm(
        S1=_section(now + 163 * DAY_MS),   # old browser simulator's 2027 clock
        # One cycle old. This was 2 minutes when freshness used a flat 15-minute
        # threshold; now that lateness is measured against the node's OWN
        # reporting interval, 2 minutes on a 15-second node is four missed
        # readings and is correctly called "delayed".
        S2=_section(now - 20_000),
    )
    farm_now = _farm_now_ms(houses)
    fresh = _freshness(houses["H1"]["sections"]["S2"], farm_now)

    assert fresh["state"] == "live", (
        f"a healthy section read as {fresh['state']!r} ({fresh['label']!r}) "
        "because another section was future-dated"
    )
    assert fresh["trusted"] is True


def test_future_dated_section_is_itself_flagged_not_called_current():
    """The bad reading must not clamp to zero age and render as 'just now'."""
    now = _now_ms()
    sec = _section(now + 163 * DAY_MS)
    fresh = _freshness(sec, _farm_now_ms(_farm(S1=sec)))

    assert fresh["trusted"] is False
    assert fresh["state"] != "live"
    assert "just now" not in fresh["label"].lower()


def test_small_clock_skew_is_still_tolerated():
    """Device clocks drift by seconds; that must not be called a fault."""
    now = _now_ms()
    sec = _section(now + 30_000)          # 30 s ahead
    fresh = _freshness(sec, _farm_now_ms(_farm(S1=sec)))
    assert fresh["state"] == "live"
    assert fresh["trusted"] is True


def test_a_node_that_stopped_reporting_still_goes_stale():
    """The guard must not accidentally make dead nodes look healthy."""
    now = _now_ms()
    houses = _farm(S1=_section(now - 3 * DAY_MS), S2=_section(now - 1 * MIN_MS))
    fresh = _freshness(houses["H1"]["sections"]["S1"], _farm_now_ms(houses))
    assert fresh["state"] == "stale"
    assert fresh["trusted"] is False


def test_section_with_no_reading_is_never():
    fresh = _freshness({}, _farm_now_ms(_farm()))
    assert fresh["state"] == "never"
    assert fresh["trusted"] is False


# ── lateness is judged against the node's OWN reporting interval ───────────
#
# These thresholds used to be flat: 15 minutes "live", 60 "stale", whatever the
# node was configured to do. Once the interval became settable from the app that
# was wrong in both directions — a node on 15 seconds could miss sixty readings
# and still read "live", while a node on 5 minutes was judged by a number that
# only happened to suit it.

from app.api.routes.smart_care_v2 import _freshness_limits


def test_a_fast_node_is_called_late_quickly():
    live, delayed = _freshness_limits(15_000)
    assert live <= 2.0, f"a 15s node is allowed {live:.1f} min of silence"
    assert delayed <= 5.0


def test_a_slow_node_is_given_proportionally_longer():
    live, delayed = _freshness_limits(300_000)      # 5 minutes
    assert live > 10.0, "a 5-minute node must not be called late after 2 minutes"
    assert live <= 20.0, "but not hidden for hours either"


def test_the_floor_stops_a_fast_node_flapping():
    """One dropped packet on a 5-second interval must not read as a dead node."""
    live, _ = _freshness_limits(5_000)
    assert live >= 1.5


def test_the_ceiling_stops_a_very_slow_node_hiding():
    live, delayed = _freshness_limits(3_600_000)    # 1 hour
    assert live <= 20.0, "an hourly node still has to be reported late eventually"


def test_a_disconnected_five_minute_node_eventually_goes_stale():
    """The reported symptom: the node was unplugged and the app still said live."""
    now = _now_ms()
    sec = _section(now - 30 * MIN_MS)
    f = _freshness(sec, _farm_now_ms(_farm(S1=sec)), 300_000)
    assert f["state"] == "stale"
    assert f["trusted"] is False


def test_missing_interval_falls_back_to_the_firmware_default():
    a = _freshness_limits(None)
    b = _freshness_limits(15_000)
    assert a == b


# --------------------------------------------------------------------------
# "If read time is 5 min then wait 10 min" - the farmer's own rule.
#
# Freshness used to be a flat 15 minutes live / 60 minutes stale, and worse,
# "delayed" was marked TRUSTED. So a node on the 5-minute production setting
# could be silent for a quarter of an hour while the app showed its last
# reading in full colour with Water Now still pressable.
# --------------------------------------------------------------------------
FIVE_MIN_MS = 300_000


def test_five_minute_node_is_live_just_before_double_its_interval():
    now = _now_ms()
    fresh = _freshness(_section(now - 9 * MIN_MS), now, FIVE_MIN_MS)
    assert fresh["state"] == "live", f"9 min on a 5 min node read as {fresh['state']!r}"
    assert fresh["trusted"] is True


def test_five_minute_node_is_not_trusted_past_double_its_interval():
    now = _now_ms()
    fresh = _freshness(_section(now - 11 * MIN_MS), now, FIVE_MIN_MS)
    assert fresh["trusted"] is False, (
        f"11 min of silence from a 5 min node was still trusted ({fresh['label']!r}); "
        "the app would keep the readings coloured and the buttons live"
    )


def test_delayed_is_never_trusted_at_any_interval():
    """The regression that let a quiet node look healthy. 'delayed' and 'stale'
    differ in how long, never in whether the numbers may be believed."""
    now = _now_ms()
    for ms in (15_000, 60_000, FIVE_MIN_MS, 3_600_000):
        live_min, delayed_min = _freshness_limits(ms)
        # squarely inside the delayed band
        age = (live_min + delayed_min) / 2.0
        fresh = _freshness(_section(now - age * MIN_MS), now, ms)
        assert fresh["state"] == "delayed", f"{ms}ms: expected delayed, got {fresh['state']!r}"
        assert fresh["trusted"] is False, f"{ms}ms: delayed reading was trusted"


def test_a_node_is_not_called_late_before_it_was_due():
    """The other direction of the same bug. A 1-hour node must not be declared
    dead at 15 minutes just because that was once the hardcoded threshold."""
    now = _now_ms()
    fresh = _freshness(_section(now - 16 * MIN_MS), now, 3_600_000)
    assert fresh["trusted"] is True, (
        "a node set to report hourly was called untrustworthy 16 minutes in"
    )
