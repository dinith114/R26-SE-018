"""A simulated shade house, so virtual sensing can be seen working.

Kriging needs four placed, reporting sections before it will estimate a fifth
(MIN_ANCHORS). The real farm has one node, so the feature is built, deployed and
completely invisible - interpolate_house returns "insufficient-anchors" and
writes nothing, which is the correct behaviour and looks identical to a broken
feature.

This stands up a house of pretend nodes that behave like the real ones: they
write to /farm/houses/HSIM/sections/{id}/latest on the same paths and in the
same shape an ESP32 does, and the backend cannot tell the difference. The engine
then kriges the unmonitored sections for real, and the app shows them in purple.

It is deliberately a SEPARATE house. Faking readings into H1 would put invented
numbers on the real farm, where a later session could not tell them from
measurements.

  python backend/scripts/sim_farm.py --seed        # create the house
  python backend/scripts/sim_farm.py --loop        # keep the nodes reporting
  python backend/scripts/sim_farm.py --remove      # delete the whole house

--loop is what makes it visible: an anchor older than MAX_ANCHOR_AGE_MIN (30
min) stops counting, so a house seeded once goes quiet half an hour later.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.routes.smart_care_v2 import (      # noqa: E402
    _fb_delete, _fb_get, _fb_put, _server_now_ms, farm_now,
)

HOUSE = "HSIM"
HOUSE_W, HOUSE_L = 10.0, 14.0        # metres

# Which of the nine get a pretend node. Five anchors leaves one spare above
# MIN_ANCHORS, so the house keeps working if one is switched off to see what
# happens - which is the more interesting demo.
SENSORED = {"S1", "S3", "S5", "S7", "S9"}

RNG = random.Random(7)               # fixed, so the layout is the same each run


def field(x: float, y: float, hour: float) -> dict:
    """The microclimate at a point, as physics would roughly have it.

    y = 0 is the open, sun-facing edge. Light falls off with depth into the
    house, temperature follows it, and humidity moves the other way because
    warmer air of the same water content sits further from saturation. The same
    shape simulate_spatial.py validates against, plus a day/night cycle so the
    numbers on screen move like real ones.
    """
    depth = y / HOUSE_L
    shade = math.exp(-2.2 * depth)
    edge = 1.0 - 0.35 * abs((x / HOUSE_W) - 0.5) * 2.0

    # Sun angle: zero before 06:00 and after 18:00, peaking at midday.
    sun = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0)) if 6 <= hour <= 18 else 0.0

    light = 32000.0 * shade * edge * sun + random.gauss(0, 300)
    temp = 24.0 + 9.0 * shade * edge * sun + random.gauss(0, 0.2)
    humid = 92.0 - 30.0 * shade * edge * sun + random.gauss(0, 1.0)

    temp = round(temp, 1)
    humid = round(min(99.0, max(30.0, humid)), 1)
    # VPD from the pair, so the triple stays physically consistent - the same
    # formula the backend uses everywhere else.
    svp = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
    return {"temperature": temp, "humidity": humid,
            "light": round(max(0.0, light), 1),
            "vpd": round(svp * (1.0 - humid / 100.0), 3)}


def layout() -> dict:
    """Nine sections on a jittered 3x3 grid.

    Jittered because three perfectly collinear anchors make the kriging matrix
    singular, and a real house is never a perfect grid anyway.
    """
    rng = random.Random(7)           # local, so --loop does not drift the layout
    out, k = {}, 0
    for r in range(3):
        for c in range(3):
            k += 1
            x = (c + 0.5) * HOUSE_W / 3 + rng.uniform(-0.5, 0.5)
            y = (r + 0.5) * HOUSE_L / 3 + rng.uniform(-0.5, 0.5)
            out["S%d" % k] = (round(min(max(x, 0.2), HOUSE_W - 0.2), 2),
                              round(min(max(y, 0.2), HOUSE_L - 0.2), 2))
    return out


def seed() -> None:
    pos = layout()
    _fb_put("/farm/houses/%s/meta.json" % HOUSE, {
        "name": "Simulated House (test)",
        "type": "shade-net",
        "plantCount": 90,
        "sectionCount": len(pos),
        # So a later session, or anyone reading the database, can tell at a
        # glance that nothing in here was measured.
        "simulated": True,
        "createdAt": farm_now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    for sid, (x, y) in pos.items():
        _fb_put("/farm/houses/%s/sections/%s/meta.json" % (HOUSE, sid), {
            "name": "Sim %s" % sid[1:],
            "label": ("simulated node" if sid in SENSORED else "no sensor - estimated"),
            "growthStage": "Active",
            "lightExposure": round(1.0 - 0.5 * (y / HOUSE_L), 2),
            "plantCount": 10,
            "x": x, "y": y,
            "simulated": True,
        })
    print("Seeded %s: %d sections, %d with a pretend node, %d to estimate."
          % (HOUSE, len(pos), len(SENSORED), len(pos) - len(SENSORED)))
    for sid in sorted(pos, key=lambda s: int(s[1:])):
        x, y = pos[sid]
        print("  %3s  (%5.2f, %5.2f) m  %s"
              % (sid, x, y, "node" if sid in SENSORED else "estimated"))


def push_once(force_hour: float = None) -> int:
    """One reading from every pretend node, exactly as firmware would write it.

    force_hour pretends it is a different time of day. Worth having: the field
    is driven by sun angle, so after dark every section reads the same 24 C and
    kriging correctly returns one flat number everywhere. That is honest and
    completely undemonstrative - the spatial gradient only exists while the sun
    is up. The TIMESTAMP is always real, so the reading is still fresh.
    """
    fn = farm_now()
    hour = force_hour if force_hour is not None else fn.hour + fn.minute / 60.0
    now_ms = _server_now_ms()
    pos = layout()
    n = 0
    for sid in sorted(SENSORED, key=lambda s: int(s[1:])):
        x, y = pos[sid]
        r = field(x, y, hour)
        r["timestamp"] = now_ms
        _fb_put("/farm/houses/%s/sections/%s/latest.json" % (HOUSE, sid), r)
        n += 1
    return n


def remove() -> None:
    if not _fb_get("/farm/houses/%s/meta.json" % HOUSE):
        print("%s does not exist - nothing to remove." % HOUSE)
        return
    # DELETE, not a PUT of None: a PUT of None does not clear a Firebase key.
    _fb_delete("/farm/houses/%s.json" % HOUSE)
    _fb_delete("/farm/history/%s.json" % HOUSE)
    print("Removed %s and its history." % HOUSE)


def report() -> None:
    """What the kriging actually did with the readings just pushed."""
    from app.api.routes import spatial_service as sp
    house = _fb_get("/farm/houses/%s.json" % HOUSE) or {}
    if not house:
        print("%s does not exist. Run --seed first." % HOUSE)
        return
    r = sp.interpolate_house(HOUSE, house)
    print("  anchors %s  targets %s  written %s  status %s"
          % (r["anchors"], r["targets"], r["written"], r["status"]))
    if r.get("message"):
        print("  %s" % r["message"])
    fresh = _fb_get("/farm/houses/%s/sections.json" % HOUSE) or {}
    for sid in sorted(fresh, key=lambda s: int(s[1:])):
        est = (fresh[sid] or {}).get("estimated") or {}
        if est:
            print("  %3s  %s C +/-%s   %s %% +/-%s   from %s anchors"
                  % (sid, est.get("temperature"), est.get("temperatureSd"),
                     est.get("humidity"), est.get("humiditySd"), est.get("anchors")))


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated house for virtual sensing.")
    ap.add_argument("--seed", action="store_true", help="create the house and its sections")
    ap.add_argument("--loop", action="store_true", help="keep the pretend nodes reporting")
    ap.add_argument("--once", action="store_true", help="push one round of readings")
    ap.add_argument("--report", action="store_true", help="show what kriging produced")
    ap.add_argument("--remove", action="store_true", help="delete the simulated house")
    ap.add_argument("--every", type=int, default=60, help="seconds between pushes")
    ap.add_argument("--hour", type=float, default=None,
                    help="pretend it is this hour (0-24), so the sun-driven gradient shows")
    a = ap.parse_args()

    if a.remove:
        remove()
        return
    if a.seed:
        seed()
    if a.report and not (a.loop or a.once):
        report()
        return
    if a.once or a.seed:
        print("Pushed readings from %d simulated nodes." % push_once(a.hour))
        report()
    if a.loop:
        print("Reporting every %ds. Ctrl-C to stop.\n" % a.every)
        try:
            while True:
                n = push_once(a.hour)
                print("  %s  %d nodes reported" % (farm_now().strftime("%H:%M:%S"), n))
                time.sleep(a.every)
        except KeyboardInterrupt:
            print("\nStopped. The house stays; readings go stale in 30 minutes.")


if __name__ == "__main__":
    main()
