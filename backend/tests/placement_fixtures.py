"""Test-house readings with a known answer, shared by the placement tests.

TEST DATA ONLY: a known temperature gradient, known per-sensor biases and known
noise, so each assertion has a right answer to compare against. Never shown as,
or mixed with, readings from the farm.
"""
import math
import random

T0 = 1_790_000_000_000          # an arbitrary fixed epoch, ms
STEP = 60_000                   # one reading a minute


def _house(coords, minutes, grad_c_per_m=0.1, biases=None, noise=0.05,
           colocate_minutes=0, fail_every=0, seed=1):
    """Histories for nodes at `coords`.

    For the first `colocate_minutes` every node reads the SAME air (they sit
    together); after that each reads its own position. Temperature rises
    grad_c_per_m along x; humidity falls 1 % per 0.5 C of it, so VPD varies too.
    """
    rng = random.Random(seed)
    biases = biases or {}
    hist = {}
    for sid, (x, _y) in coords.items():
        b = biases.get(sid, (0.0, 0.0))
        recs = {}
        for m in range(minutes):
            ts = T0 + m * STEP
            day = 3.0 * math.sin(2 * math.pi * m / 1440.0)        # a daily swing
            here = 0.0 if m < colocate_minutes else grad_c_per_m * x
            t = 26.0 + day + here + b[0] + rng.gauss(0, noise)
            h = 80.0 - 2.0 * (day + here) + b[1] + rng.gauss(0, noise * 4)
            rec = {"timestamp": ts, "temperature": round(t, 2), "humidity": round(h, 2),
                   "light": -999}                                  # no BH1750 on these
            if fail_every and m % fail_every == 0:
                rec["temperature"] = -999                          # a DHT22 glitch
            recs[f"k{m:06d}"] = rec
        hist[sid] = recs
    return hist


LINE = {f"S{i + 1}": (2.0 * i, 3.0) for i in range(6)}     # 6 nodes, 0..10 m along x
