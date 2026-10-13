"""The farm's clock: everything about watering happens in the plants' local time.

Why this file exists. The watering models were trained on ERA5 hourly weather
fetched with `timezone=Asia/Colombo` (ml_pipeline/fetch_real_weather.py), so a
predicted `waterTime` of "06:34" means 06:34 *where the plants are*. The server
had no farm timezone at all: it planned and scheduled on UTC, so on a UTC+5:30
farm every watering fired 5.5 hours late. On 24 Aug 2026 the node acknowledged
the day's watering at 06:36:58 UTC = 12:06:58 Sri Lanka — a midday soak, which
is the one thing this component exists to prevent.

The same gap corrupted the model's input: `_dawn_reading` searched 04:00-07:00
UTC, which is 09:30-12:30 local, so "dawn conditions" were late-morning air.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes.smart_care_v2 import farm_now, farm_tz, _dawn_reading
from app.api.routes.automation import _due_sessions

SL_OFFSET_MIN = 330          # UTC+5:30, and Sri Lanka has no DST


def _reading(ts_ms, temp):
    return {"temperature": temp, "humidity": 70.0, "light": 1000.0,
            "timestamp": ts_ms}


def _history_over_one_day(tz):
    """One reading per hour across a full local day, each hour tagged by its
    temperature so we can tell which one was picked."""
    base = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    raw = {}
    for h in range(24):
        t = base + timedelta(hours=h)
        # temperature encodes the LOCAL hour, so the assertion can read it back
        raw[f"h{h:02d}"] = _reading(int(t.timestamp() * 1000), 20.0 + h)
    return raw


def test_farm_clock_is_ahead_of_utc():
    """The farm runs on Sri Lanka time, not the server's UTC."""
    delta = farm_now().utcoffset()
    assert delta is not None, "farm_now() must be timezone-aware"
    assert delta == timedelta(minutes=SL_OFFSET_MIN), (
        f"farm clock is {delta} from UTC, expected +5:30")


def test_dawn_reading_is_picked_by_LOCAL_hour():
    """The model is trained on local dawn. Searching 04:00-07:00 UTC picks a
    09:30-12:30 local reading and feeds late-morning air to the model."""
    tz = farm_tz()
    raw = _history_over_one_day(tz)
    latest = _reading(int(datetime.now(tz).timestamp() * 1000), 99.0)

    picked = _dawn_reading(raw, latest)
    picked_hour = round(picked["temperature"] - 20.0)

    assert 4 <= picked_hour <= 7, (
        f"picked the {picked_hour:02d}:00 local reading as dawn; "
        "dawn is 04:00-07:00 in the plants' own time")
    assert picked_hour == 5, f"expected the 05:00 local reading, got {picked_hour:02d}:00"


def test_watering_is_due_at_the_plans_LOCAL_time():
    """A plan that says 06:34 must fire when it is 06:34 on the farm."""
    now = farm_now()
    plan = {"date": now.strftime("%Y-%m-%d"),
            "waterTime": now.strftime("%H:%M"),
            "durationSec": 90}
    due = _due_sessions(plan, now)
    assert due, f"plan for {plan['waterTime']} was not due at {now:%H:%M} farm time"
    assert due[0]["durationSec"] == 90


def test_watering_is_NOT_due_merely_because_UTC_matches():
    """The regression itself: 5.5 hours from now in UTC terms must not fire."""
    now = farm_now()
    utc_now = datetime.now(timezone.utc)
    plan = {"date": now.strftime("%Y-%m-%d"),
            "waterTime": utc_now.strftime("%H:%M"),
            "durationSec": 90}
    # The UTC hour is 5.5 h behind the farm, so this plan is in the farm's past
    # by more than the catch-up window and must not be treated as due.
    due = _due_sessions(plan, now)
    assert not due, (
        f"a plan timed {plan['waterTime']} fired at {now:%H:%M} farm time — "
        "the scheduler is still comparing against UTC")


def test_plan_date_rolls_over_on_the_farms_midnight():
    """A plan is 'today's' by the farm's date, not the server's."""
    now = farm_now()
    plan = {"date": now.strftime("%Y-%m-%d"),
            "waterTime": now.strftime("%H:%M"), "durationSec": 60}
    assert _due_sessions(plan, now), "today's plan was not recognised as today's"

    stale = dict(plan, date=(now - timedelta(days=1)).strftime("%Y-%m-%d"))
    assert not _due_sessions(stale, now), "yesterday's plan was treated as due"
