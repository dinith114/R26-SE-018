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

import requests                                  # noqa: E402

from app.api.routes.smart_care_v2 import (      # noqa: E402
    _fb_delete, _fb_get, _fb_put, _server_now_ms, farm_now,
)
from app.api.routes.smart_watering import FIREBASE_BASE_URL   # noqa: E402


def _fb_patch(path: str, data: dict) -> bool:
    """Merge a whole batch of entries in one request.

    PATCH, not PUT: PUT at a collection path REPLACES everything already there,
    so backfilling would silently delete whatever a node had genuinely reported.
    PATCH adds the given keys and leaves the rest alone.
    """
    try:
        return requests.patch(f"{FIREBASE_BASE_URL}{path}", json=data,
                              timeout=60).status_code == 200
    except Exception:
        return False


def _fb_post(path: str, data: dict) -> bool:
    """POST, so Firebase assigns a push id.

    History is a COLLECTION - the firmware posts each reading and lets Firebase
    key it (`-P0D7Upt_BJoImiEVgWQ`). A PUT would replace the whole archive with
    one entry, which is exactly the mistake this helper exists to prevent: the
    simulator must write history the same way the hardware does, or the
    calibration analysis reads a shape it will never see in the field.
    """
    try:
        return requests.post(f"{FIREBASE_BASE_URL}{path}", json=data,
                             timeout=8).status_code == 200
    except Exception:
        return False

HOUSE = "HSIM"
HOUSE_W, HOUSE_L = 10.0, 14.0        # metres

# Which sections keep a node AFTER calibration. Five anchors leaves one spare
# above MIN_ANCHORS, so the house keeps working if one is switched off - which
# is the more interesting demo.
#
# DURING calibration every section has one: that is what a calibration window
# is, and it is the data the placement decision is made from. --phase selects
# which set reports, because pushing only these five made four sections read
# "No node" on a house that was supposedly mid-calibration.
KEPT_AFTER = {"S1", "S3", "S5", "S7", "S9"}
SENSORED = KEPT_AFTER          # replaced at startup when --phase calib

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


def push_once(force_hour: float = None, history: bool = True) -> int:
    """One reading from every pretend node, exactly as firmware would write it.

    BOTH paths, because the firmware writes both: `/latest` is the current
    state every screen reads, and `/farm/history/{h}/{s}` is the archive the
    calibration analysis reads. Writing only `/latest` was the earlier gap -
    the simulated house looked alive on every screen while having no history at
    all, so PySensors could never be run against it and the whole calibration
    phase was untestable without waiting three real days.

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
        if history:
            _fb_post("/farm/history/%s/%s.json" % (HOUSE, sid), r)
        n += 1
    return n


def backfill(days: float, per_hour: int = 4) -> int:
    """Write a calibration window's worth of history, dated into the past.

    This is the ONE thing here that is not what the hardware does, and it is
    worth being precise about what it is and is not.

    It is NOT fake data in the sense that matters: every reading is generated by
    the same field() the live simulator uses, written to the same path, in the
    same shape, and read back by the same code that reads the real node's
    archive. What it fakes is only the WAITING - it stamps readings across the
    last N days instead of taking N days to produce them.

    Without it, testing the calibration flow means waiting three real days
    between every code change. With it, the analysis still runs on stored
    readings it did not generate, which is the property that matters.

    Never point this at a house a real node writes to: it would interleave
    invented readings with measured ones in the same archive, and afterwards
    nobody could tell which was which.
    """
    meta = _fb_get("/farm/houses/%s/meta.json" % HOUSE) or {}
    if not meta.get("simulated"):
        print("REFUSED: %s is not marked simulated. Backfilling a real house "
              "would mix invented readings into a measured archive." % HOUSE)
        return 0

    pos = layout()
    now_ms = _server_now_ms()
    step_ms = 3600000.0 / per_hour
    total = int(days * 24 * per_hour)
    written = 0

    # EVERY section, not just the ones that stay sensored afterwards. That is
    # what a calibration window is: a node in every section, collecting the data
    # that will decide which of them keep one. Backfilling only SENSORED made
    # the house look like four nodes had never been installed, and calibration
    # correctly refused to finish.
    for sid in sorted(pos, key=lambda s: int(s[1:])):
        x, y = pos[sid]
        # ONE write per section, not one per reading. Posting each reading
        # individually meant 288 sequential HTTP round trips per section and the
        # backfill timed out half way through, leaving two sections with three
        # days of history and three with none - which looks exactly like a farm
        # where three nodes were never installed.
        batch = {}
        for k in range(total):
            ts = now_ms - (total - k) * step_ms
            # Hour of day at that historical instant, so the archive carries a
            # real diurnal cycle rather than N copies of one moment. A matrix
            # whose rows are all the same has rank 1, and every placement method
            # would score identically on it.
            hour = ((ts / 3600000.0) % 24)
            r = field(x, y, hour)
            r["timestamp"] = ts
            # A key of our own rather than a Firebase push id, and deliberately
            # recognisable: anyone reading the archive later can see at a glance
            # which entries were backfilled and which a node actually reported.
            batch["bf%013d" % int(ts)] = r
        if _fb_patch("/farm/history/%s/%s.json" % (HOUSE, sid), batch):
            written += len(batch)
            print("  %s: %d readings over %.1f days" % (sid, total, days))
        else:
            print("  %s: FAILED" % sid)
    return written


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
    ap.add_argument("--phase", choices=("calib", "active"), default="active",
                    help="calib: every section reports, as during calibration. "
                         "active: only the sections that keep a node, so the "
                         "rest are estimated by kriging.")
    ap.add_argument("--backfill", type=float, default=None, metavar="DAYS",
                    help="write DAYS of history dated into the past, so the "
                         "calibration flow can be tested without waiting")
    a = ap.parse_args()

    global SENSORED
    if a.phase == "calib":
        SENSORED = set(layout().keys())
        print("phase: calibrating - all %d sections reporting\n"
              % len(SENSORED))
    else:
        SENSORED = set(KEPT_AFTER)
        print("phase: active - %d sections reporting, %d estimated\n"
              % (len(SENSORED), len(layout()) - len(SENSORED)))

    if a.remove:
        remove()
        return
    if a.backfill:
        n = backfill(a.backfill)
        print("\nBackfilled %d history readings over %.1f days." % (n, a.backfill))
        print("The calibration endpoint reads these the same way it reads the")
        print("real node's archive - nothing downstream knows the difference.")
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
