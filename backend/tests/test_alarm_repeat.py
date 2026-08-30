"""An alarm nobody acknowledges must keep asking — but not forever.

The failure this guards against is a plant that never gets watered because the
one notification arrived while the farmer was asleep, outdoors, or in another
room. A single chime is not a safety mechanism.

The opposite failure matters too: an alarm that nags forever at a phone that is
switched off trains the farmer to ignore the app entirely.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes.automation import (
    alarm_due_for_push, ALARM_REPEAT_MINUTES, ALARM_REPEAT_MAX,
)

NOW = datetime(2026, 8, 25, 6, 0, 0, tzinfo=timezone.utc)


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def alarm(**over):
    a = {"kind": "action", "action": "water", "acknowledged": False}
    a.update(over)
    return a


# ── the first push ────────────────────────────────────────────────────────

def test_a_brand_new_action_alarm_is_pushed():
    assert alarm_due_for_push(alarm(), NOW) is True


def test_an_info_alarm_is_never_pushed():
    assert alarm_due_for_push(alarm(kind="info"), NOW) is False


def test_junk_is_ignored():
    assert alarm_due_for_push(None, NOW) is False
    assert alarm_due_for_push("not a dict", NOW) is False


# ── repeating ─────────────────────────────────────────────────────────────

def test_it_does_not_nag_before_the_interval():
    a = alarm(pushCount=1, lastPushedAt=stamp(NOW - timedelta(minutes=ALARM_REPEAT_MINUTES - 1)))
    assert alarm_due_for_push(a, NOW) is False


def test_it_repeats_once_the_interval_has_passed():
    a = alarm(pushCount=1, lastPushedAt=stamp(NOW - timedelta(minutes=ALARM_REPEAT_MINUTES + 1)))
    assert alarm_due_for_push(a, NOW) is True, (
        "an unacknowledged alarm stopped asking — this is the plant nobody watered")


def test_it_gives_up_after_the_maximum():
    a = alarm(pushCount=ALARM_REPEAT_MAX,
              lastPushedAt=stamp(NOW - timedelta(hours=5)))
    assert alarm_due_for_push(a, NOW) is False, (
        "an alarm nagged past its limit; it should stay in the app instead")


# ── acknowledging silences it immediately ─────────────────────────────────

def test_acknowledging_stops_it_at_once_even_when_a_repeat_is_due():
    """Checked BEFORE the interval, so Acknowledge takes effect on the next
    tick rather than after another five minutes."""
    a = alarm(acknowledged=True, pushCount=2,
              lastPushedAt=stamp(NOW - timedelta(hours=1)))
    assert alarm_due_for_push(a, NOW) is False


def test_acknowledging_stops_it_before_the_first_push_too():
    assert alarm_due_for_push(alarm(acknowledged=True), NOW) is False


# ── robustness ────────────────────────────────────────────────────────────

def test_an_unparseable_timestamp_does_not_wedge_the_alarm():
    """A corrupt stamp must not silence an alarm forever — better to repeat
    once too often than to drop the only warning a farmer gets."""
    a = alarm(pushCount=1, lastPushedAt="whenever")
    assert alarm_due_for_push(a, NOW) is True


def test_a_missing_timestamp_with_a_count_still_pushes():
    assert alarm_due_for_push(alarm(pushCount=1), NOW) is True


@pytest.mark.parametrize("count", range(0, ALARM_REPEAT_MAX))
def test_every_count_below_the_max_is_still_allowed(count):
    a = alarm(pushCount=count, lastPushedAt=stamp(NOW - timedelta(hours=1)))
    assert alarm_due_for_push(a, NOW) is True
