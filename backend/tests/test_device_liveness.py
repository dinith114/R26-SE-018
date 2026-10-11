"""A board is offline after three missed beats on ITS OWN clock.

validation-2.3 QUIET boards - the battery-powered placement-study nodes - beat
every 60 s instead of 30 s and say so in their device record. Against the
fixed 90 s window one late beat showed them offline in the app. The records
below are TEST DATA.
"""
import time

from app.api.routes.devices import ONLINE_WINDOW_SEC, device_liveness


def _rec(fw, age_sec, **extra):
    return {"fw": fw, "lastSeen": int(time.time()) - age_sec, **extra}


def test_a_quiet_board_gets_three_of_its_own_beats():
    quiet = _rec("validation-2.3", 120, heartbeatSec=60, quiet=True)
    out = device_liveness(quiet)
    assert out["onlineWindowSec"] == 180 and out["online"] is True
    assert device_liveness(_rec("validation-2.3", 200, heartbeatSec=60))["online"] is False


def test_a_normal_board_keeps_the_ninety_second_window():
    assert device_liveness(_rec("validation-2.1", 120))["online"] is False
    assert device_liveness(_rec("validation-2.3", 60, heartbeatSec=30))["onlineWindowSec"] \
        == ONLINE_WINDOW_SEC
    # A faster or junk value never shortens it.
    assert device_liveness(_rec("validation-2.3", 60, heartbeatSec=5))["onlineWindowSec"] \
        == ONLINE_WINDOW_SEC
    assert device_liveness(_rec("validation-2.3", 60, heartbeatSec="x"))["onlineWindowSec"] \
        == ONLINE_WINDOW_SEC
