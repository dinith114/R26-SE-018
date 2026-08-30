"""Pretend sensor nodes for a house, so the whole flow can be walked without
buying twenty ESP32s.

Attaches to a house that ALREADY EXISTS - normally one just created in the app -
reads its sections and their coordinates from Firebase, and writes readings to
exactly the paths the firmware writes to. Nothing downstream can tell the
difference: the calibration endpoint counts these readings, PySensors places
from them, and kriging estimates from them.

  python backend/scripts/sim_farm.py --house H5 --claim
  python backend/scripts/sim_farm.py --house H5 --fast-forward 3
  python backend/scripts/sim_farm.py --house H5 --loop --hour 13
  python backend/scripts/sim_farm.py --house H5 --report

What is real and what is not
----------------------------
The FIELD is generated. Its shape is grounded in how a shade house behaves - sun
through netting, depth from the open edge, thermal lag, a draft at the door -
but the parameters are chosen, not measured, and this file says so rather than
implying otherwise.

What is NOT faked is the path. Readings go to /latest and /farm/history through
the same writes the ESP32 makes, in the same shape, and every consumer reads
them identically. --fast-forward skips only the WAITING: it stamps readings
across past days instead of taking days to produce them.

It refuses to write to a house not marked `simulated`. Mixing invented readings
into a measured archive would leave nobody able to tell them apart afterwards.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
import zlib
from typing import Dict, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests                                  # noqa: E402

from app.api.routes.smart_care_v2 import (      # noqa: E402
    _fb_delete, _fb_get, _fb_put, _server_now_ms, farm_now, _natural_key,
)
from app.api.routes.smart_watering import FIREBASE_BASE_URL   # noqa: E402


# ══════════════════════════════════════════════ Firebase helpers

def _fb_post(path: str, data: dict) -> bool:
    """POST, so Firebase assigns a push id - how the firmware writes history."""
    try:
        return requests.post(f"{FIREBASE_BASE_URL}{path}", json=data,
                             timeout=10).status_code == 200
    except Exception:
        return False


def _fb_patch(path: str, data: dict) -> bool:
    """Merge many entries in one request.

    PATCH, not PUT: PUT at a collection path REPLACES everything already there,
    which would silently delete whatever a node had genuinely reported.
    """
    try:
        return requests.patch(f"{FIREBASE_BASE_URL}{path}", json=data,
                              timeout=90).status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════ The microclimate

# Fixed features of the building: a thin patch of netting, the shadow of a post,
# the corner the irrigation line runs along. Drawn once per house and never
# changed, because they are physically fixed. Seeded from the house id, so the
# same house always has the same character.
N_ANOMALIES = 6
ANOMALY_RADIUS_M = 2.2
# Reduced from 1.8: peak spatial spread reached 5.05 C against a reported
# maximum of 3.2-3.5 C in tropical plastic greenhouses. Structural features are
# real but were carrying too much of the variation.
ANOMALY_STRENGTH_C = 0.8

# THE PART THAT MATTERS MOST FOR PLACEMENT.
#
# Air near the open edge follows the sun almost immediately; air at the back is
# buffered by the volume in front of it and peaks later. A lag changes the SHAPE
# of a section's day, not just its amplitude - and two sections whose days are
# shaped differently cannot stand in for one another.
#
# The earlier version of this file had no lag. Every section was then the same
# curve scaled by its own constant, neighbouring sections correlated at 0.99,
# and the placement maths correctly concluded one sensor could speak for a whole
# zone. That conclusion was true of the generated field and false of any real
# house, which is exactly the kind of error a simulator must not introduce.
# 45 minutes at the deepest point. The survey put edge-to-interior
# propagation in porous shade-net structures at 20-60 minutes; 1.6 hours was
# guessed before that figure existed and sat well outside it.
MAX_LAG_HOURS = 0.75

# A cool tongue of outside air along one edge, present only while the wind is
# up. Intermittent and LOCAL - the kind of effect that makes one section
# genuinely unpredictable from its neighbours.
DRAFT_COOLING_C = 1.2
DRAFT_REACH_M = 3.5

# THE THING THAT WAS MISSING.
#
# Cloud cover was applied to the whole house at once, so every section dimmed
# and brightened in perfect step. That is a large shared signal, and it is why
# sections five metres apart correlated at 0.93 where the survey put that
# separation nearer 0.55-0.75.
#
# Real cumulus casts a shadow tens of metres across that DRIFTS with the wind,
# so one end of a house is shaded while the other is in full sun, for a few
# minutes at a time. Local, transient, and uncorrelated with anything else -
# exactly the signal that makes one section unpredictable from its neighbour,
# and the reason a real house needs more than two sensors.
# Per-reading scatter, and the number is not a guess: the DHT22 on these nodes
# is specified at +/-0.5 C, so a simulated node must be at least that imprecise
# or it is a better instrument than the one being simulated.
#
# It matters more than it looks. In geostatistics this is the NUGGET, and the
# survey reports real greenhouses at 5-28% of sill during daylight - its own
# derived correlation table assumes 10%. The simulator was running at under 1%,
# which is why sections five metres apart sat at 0.94 while the guide put them
# near 0.65. Chasing that gap with cloud shadows was chasing the wrong term:
# the field was not too smooth, the sensors were too good.
SENSOR_NOISE_C = 0.5

CLOUD_BAND_M = 9.0        # how wide a passing shadow is
CLOUD_DRIFT_MS = 4.0      # how fast it crosses


class Field:
    """One house's microclimate, as a function of position and time.

    Deliberately not a single smooth gradient. A smooth field is reconstructible
    from almost any placement, which flatters every method equally and so
    measures nothing.
    """

    def __init__(self, house_id: str, width: float, length: float):
        self.w = max(float(width or 10), 1.0)
        self.l = max(float(length or 14), 1.0)
        # zlib.crc32, NOT hash(). Python randomises string hashing per
        # process, so `hash(house_id)` drew a DIFFERENT building every run:
        # the posts and thin netting moved, and a house's archive ended up
        # holding readings from several different buildings. The comment
        # above promised the opposite and was simply wrong. Measured:
        # abs(hash('H5')) & 0xFFFF gave 56931, 872, 32728 on three runs.
        rng = random.Random(zlib.crc32(house_id.encode()) & 0xFFFF)

        self.anoms = [(rng.uniform(0, self.w), rng.uniform(0, self.l),
                       rng.uniform(-1.0, 1.0) * ANOMALY_STRENGTH_C)
                      for _ in range(N_ANOMALIES)]

        self.door_x = rng.uniform(0, self.w)
        self.door_y = rng.choice([0.0, self.l])
        self.sun_dir = -1.0

    def _structural(self, x: float, y: float, sun_elev: float) -> float:
        """Temperature offset from the building's own features.

        THE SHADOWS MOVE, and they have to.

        A static offset per section is invisible to the placement maths:
        correlation is unchanged by adding a constant, so six fixed warm and
        cool spots decorrelate nothing at all. The first version of this did
        exactly that and wondered why neighbouring sections still sat at 0.99.

        A real post casts its shadow west in the morning and east in the
        afternoon, so the cool patch SWEEPS across the floor during the day.
        Each section therefore sits in shade at a different hour, which changes
        the shape of its day rather than its level - and that is what makes two
        sections genuinely different rather than merely offset.

        Shadow length grows as the sun drops, which is why the effect is
        strongest early and late.
        """
        # Long shadows at low sun, short at noon. Capped so dawn does not throw
        # a shadow across the whole farm.
        length = min(6.0, 1.2 / max(0.2, sun_elev))
        # Sun crosses east to west: offset runs one way in the morning and the
        # other in the afternoon.
        shift = length * self.sun_dir
        t = 0.0
        for ax, ay, amp in self.anoms:
            d2 = (x - (ax + shift)) ** 2 + (y - ay) ** 2
            t += amp * math.exp(-d2 / (2 * ANOMALY_RADIUS_M ** 2))
        return t

    def at(self, x: float, y: float, hour: float, cloud: float,
           ambient: float, wind: float, noise: random.Random,
           t_min: float = 0.0) -> Dict[str, float]:
        depth = y / self.l
        shade = math.exp(-2.2 * depth)
        edge = 1.0 - 0.35 * abs((x / self.w) - 0.5) * 2.0

        h = hour - MAX_LAG_HOURS * depth
        elev = max(0.0, math.sin(math.pi * (h - 6.0) / 12.0)) if 6 <= h <= 18 else 0.0
        sun = elev * (1.0 - cloud)

        # East to west: negative before noon, positive after.
        self.sun_dir = -1.0 if hour < 12 else 1.0

        # Where the shadow band has drifted to. Position advances with real
        # time, so consecutive readings see it somewhere plausible rather than
        # jumping about.
        span = self.l + 2 * CLOUD_BAND_M
        band_pos = ((t_min * 60.0 * CLOUD_DRIFT_MS) % span) - CLOUD_BAND_M
        shadow = math.exp(-((y - band_pos) ** 2) / (2 * (CLOUD_BAND_M / 2.5) ** 2))
        local_sun = sun * (1.0 - 0.55 * shadow * cloud)

        temp = 24.0 + ambient + 9.0 * shade * edge * local_sun
        temp += self._structural(x, y, elev) * (0.3 + 0.7 * local_sun)

        dd = math.hypot(x - self.door_x, y - self.door_y)
        if dd < DRAFT_REACH_M:
            temp -= DRAFT_COOLING_C * wind * (1.0 - dd / DRAFT_REACH_M)

        temp += noise.gauss(0, SENSOR_NOISE_C)

        # Humidity moves opposite to temperature, with its own local noise so it
        # is not a deterministic function of it.
        humid = 92.0 - 2.6 * (temp - 24.0) + noise.gauss(0, 1.0)
        humid = min(99.0, max(30.0, humid))
        light = 32000.0 * shade * edge * local_sun + noise.gauss(0, 300)

        temp = round(temp, 1)
        humid = round(humid, 1)
        svp = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
        return {"temperature": temp, "humidity": humid,
                "light": round(max(0.0, light), 1),
                "vpd": round(svp * (1.0 - humid / 100.0), 3)}


def weather(rng: random.Random) -> Tuple[float, float, float]:
    """(cloud, ambient, wind) for one moment. Beta for cloud because most days
    are mostly clear and a few are not."""
    return (rng.betavariate(2.0, 5.0),
            rng.gauss(0.0, 1.4),
            max(0.0, rng.gauss(0.35, 0.3)))


# ══════════════════════════════════════════════ The house

def load_house(house_id: str) -> Tuple[dict, Dict[str, Tuple[float, float]]]:
    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise SystemExit(f"House {house_id} does not exist.")
    secs = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    pos = {}
    for sid in sorted(secs, key=_natural_key):
        m = (secs[sid] or {}).get("meta") or {}
        try:
            pos[sid] = (float(m["x"]), float(m["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    return meta, pos


def guard(meta: dict, house_id: str) -> None:
    if not meta.get("simulated"):
        raise SystemExit(
            f"REFUSED: {house_id} is not marked simulated.\n"
            f"Writing here would mix invented readings into a measured archive, "
            f"and afterwards nobody could separate them.\n"
            f"If this really is a test house: --house {house_id} --claim")


# ══════════════════════════════════════════════ Commands

def claim(house_id: str) -> None:
    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise SystemExit(f"House {house_id} does not exist.")
    meta["simulated"] = True
    _fb_put(f"/farm/houses/{house_id}/meta.json", meta)
    print(f"{house_id} marked simulated. This script may now write to it.")


def push_once(house_id, meta, pos, sensored, force_hour=None, history=True) -> int:
    field = Field(house_id, meta.get("width"), meta.get("length"))
    fn = farm_now()
    hour = force_hour if force_hour is not None else fn.hour + fn.minute / 60.0
    now_ms = _server_now_ms()
    # One sky for the whole house at any moment - that shared weather is what
    # correlates the sections at all, and what the placement maths measures.
    cloud, ambient, wind = weather(random.Random(int(now_ms // 60000)))
    noise = random.Random()

    n = 0
    for sid in sorted(sensored, key=_natural_key):
        if sid not in pos:
            continue
        x, y = pos[sid]
        r = field.at(x, y, hour, cloud, ambient, wind, noise, now_ms / 60000.0)
        r["timestamp"] = now_ms
        _fb_put(f"/farm/houses/{house_id}/sections/{sid}/latest.json", r)
        if history:
            _fb_post(f"/farm/history/{house_id}/{sid}.json", r)
        n += 1
    return n


def fast_forward(house_id, meta, pos, sensored, days: float, per_hour: int = 8) -> int:
    """Write a calibration window's readings, dated into the past.

    The only thing skipped is the waiting. Every reading comes from the same
    Field the live loop uses, lands on the same path, and is read back by the
    same code that reads a real node's archive.

    It also moves calibration.startedAt back, because a window whose readings
    span three days but whose clock says it began a minute ago is not a
    fast-forward, it is a contradiction - and the endpoint checks both.
    """
    field = Field(house_id, meta.get("width"), meta.get("length"))
    now_ms = _server_now_ms()
    step_ms = 3600000.0 / per_hour
    total = int(days * 24 * per_hour)
    noise = random.Random(4)
    written = 0

    for sid in sorted(sensored, key=_natural_key):
        if sid not in pos:
            continue
        x, y = pos[sid]
        batch = {}
        for k in range(total):
            ts = now_ms - (total - k) * step_ms
            hour = (ts / 3600000.0) % 24
            cloud, ambient, wind = weather(random.Random(int(ts // 3600000)))
            r = field.at(x, y, hour, cloud, ambient, wind, noise, ts / 60000.0)
            r["timestamp"] = ts
            # A key of our own, deliberately recognisable: anyone reading the
            # archive later can see which readings a node reported and which
            # were written for a test.
            batch["ff%013d" % int(ts)] = r
        if _fb_patch(f"/farm/history/{house_id}/{sid}.json", batch):
            written += len(batch)
            print(f"  {sid}: {total} readings over {days} days")
        else:
            print(f"  {sid}: FAILED")

    cal = dict(meta.get("calibration") or {})
    if cal:
        cal["startedAt"] = now_ms - (days + 0.1) * 86400000
        meta["calibration"] = cal
        _fb_put(f"/farm/houses/{house_id}/meta.json", meta)
        print(f"  calibration clock moved back {days + 0.1:.1f} days")
    return written


def report(house_id: str, pos: dict) -> None:
    """What the placement maths sees.

    The correlations are the point. If neighbouring sections sit at 0.99 the
    field is too smooth to be worth placing against, every method scores the
    same, and the exercise measures nothing.
    """
    import numpy as np
    from app.api.routes.house_planner import _snapshots_measured

    ids = sorted(pos, key=_natural_key)
    got = _snapshots_measured(house_id, ids)
    if got is None:
        print("Not enough overlapping history yet.")
        return
    fit, test = got
    M = np.vstack([fit, test])
    print(f"\n{M.shape[0]} common periods across {M.shape[1]} sections")

    C = np.corrcoef(M.T)
    off = [C[i, j] for i in range(len(ids)) for j in range(i + 1, len(ids))]
    print(f"correlation between sections: min {min(off):.3f}  "
          f"mean {sum(off) / len(off):.3f}  max {max(off):.3f}")

    sv = np.linalg.svd(M - M.mean(axis=0), compute_uv=False)
    energy = (sv ** 2) / (sv ** 2).sum()
    print("mode energy: " + "  ".join(f"{e:.3f}" for e in energy[:5]))
    print("modes for 99% of the variation: "
          f"{int(np.searchsorted(np.cumsum(energy), 0.99) + 1)} of {len(ids)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated nodes for a real house.")
    ap.add_argument("--house", required=True, help="house id, e.g. H5")
    ap.add_argument("--claim", action="store_true",
                    help="mark the house simulated so this may write to it")
    ap.add_argument("--phase", choices=("calib", "active"), default="calib",
                    help="calib: every section reports. active: only --keep of them")
    ap.add_argument("--keep", type=int, default=0,
                    help="with --phase active, how many sections keep a node")
    ap.add_argument("--fast-forward", type=float, default=None, metavar="DAYS",
                    help="write DAYS of history dated into the past and move the "
                         "calibration clock back to match")
    ap.add_argument("--once", action="store_true", help="one round of readings")
    ap.add_argument("--loop", action="store_true", help="keep reporting")
    ap.add_argument("--every", type=int, default=60, help="seconds between rounds")
    ap.add_argument("--hour", type=float, default=None,
                    help="pretend it is this hour, so the sun gradient shows")
    ap.add_argument("--report", action="store_true",
                    help="correlations and mode energy of the stored history")
    ap.add_argument("--wipe", action="store_true", help="delete this house's history")
    a = ap.parse_args()

    if a.claim:
        claim(a.house)
        return

    meta, pos = load_house(a.house)
    guard(meta, a.house)

    if not pos:
        raise SystemExit(
            f"No section of {a.house} has coordinates. Create the house through "
            f"the planner, which sets them, or set them in each Setup tab.")

    ids = sorted(pos, key=_natural_key)
    if a.phase == "calib":
        sensored = set(ids)
    else:
        k = max(3, a.keep or len(ids) // 2)
        sensored = set(ids[::max(1, len(ids) // k)][:k])
    print(f"{a.house}: {len(ids)} placed sections, {len(sensored)} reporting ({a.phase})")

    if a.wipe:
        _fb_delete(f"/farm/history/{a.house}.json")
        print(f"Cleared history for {a.house}. Sections and positions kept.")
        return
    if a.fast_forward:
        n = fast_forward(a.house, meta, pos, sensored, a.fast_forward)
        print(f"\nWrote {n} readings. The calibration endpoint reads these exactly "
              f"as it reads a real node's archive.")
        report(a.house, pos)
        return
    if a.report:
        report(a.house, pos)
        return
    if a.once:
        print(f"Pushed {push_once(a.house, meta, pos, sensored, a.hour)} readings.")
        return
    if a.loop:
        print(f"Reporting every {a.every}s. Ctrl-C to stop.\n")
        try:
            while True:
                n = push_once(a.house, meta, pos, sensored, a.hour)
                print(f"  {farm_now().strftime('%H:%M:%S')}  {n} nodes reported")
                time.sleep(a.every)
        except KeyboardInterrupt:
            print("\nStopped. Readings go stale for kriging after 30 minutes.")
        return

    print("Nothing to do. Try --fast-forward 3, --loop, --once or --report.")


if __name__ == "__main__":
    main()
