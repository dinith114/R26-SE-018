"""The placement analysis, checked against data whose answer is known.

The fixtures below are TEST DATA, built so each check has a correct answer to
compare against: a house with a known temperature gradient, known per-sensor
biases and known noise. They prove the code recovers what was put in. They are
not, and are never shown as, readings from the farm.
"""
import math

import numpy as np
import pytest

from app.services import placement_analysis as pa
from app.services import readings as rd

from tests.placement_fixtures import LINE, STEP, T0, _house  # noqa: E402


# ── readings: measured or absent, never substituted ─────────────────────────

def test_value_drops_failed_missing_and_impossible():
    assert rd.value({"temperature": 27.5}, "temperature") == 27.5
    assert rd.value({"temperature": -999}, "temperature") is None
    assert rd.value({"temperature": float("nan")}, "temperature") is None
    assert rd.value({}, "temperature") is None
    assert rd.value({"temperature": 0.0}, "temperature") is None        # the 31 Aug reading
    assert rd.why_rejected({"humidity": -999}, "humidity") == "failed"
    assert rd.why_rejected({"humidity": 2.0}, "humidity") == "implausible"
    assert rd.why_rejected({}, "light") == "missing"


def test_plausible_bounds_match_the_server():
    from app.api.routes import smart_care_v2
    assert rd.PLAUSIBLE == smart_care_v2.PLAUSIBLE


def test_a_failed_reading_never_becomes_a_default():
    hist = {"S1": {"a": {"timestamp": T0, "temperature": -999, "humidity": 70.0},
                   "b": {"timestamp": T0 + 1000, "temperature": 27.0, "humidity": 71.0}}}
    stats, buckets = pa.collect(hist)
    vals = [v for b in buckets["S1"].values() for v in b["temperature"]]
    assert vals == [27.0]                     # 28.0 (the model default) must not appear
    assert stats["S1"]["rejected"]["temperature"]["failed"] == 1
    assert stats["S1"]["rejected"]["light"]["missing"] == 2


# ── sensor bias from co-location ────────────────────────────────────────────

def test_colocation_recovers_each_sensors_bias():
    biases = {"S1": (0.3, -1.5), "S2": (-0.2, 1.0), "S3": (0.0, 0.0),
              "S4": (0.1, 0.5), "S5": (-0.1, -0.5), "S6": (0.0, 0.0)}
    hist = _house(LINE, 600, biases=biases, colocate_minutes=60)
    _stats, raw = pa.collect(hist)
    means = pa._means(raw)
    got = pa.colocation_offsets(means, T0, T0 + 60 * STEP)
    assert got is not None and got["buckets"] >= 3
    # Offsets are relative to the group median, so compare after removing it.
    true_t = np.array([biases[s][0] for s in LINE]); true_t -= np.median(true_t)
    est_t = np.array([got["offsets"][s]["temperature"] for s in LINE])
    assert np.max(np.abs(est_t - true_t)) < 0.08


def test_offsets_are_removed_from_the_spatial_data():
    biases = {"S1": (1.0, 0.0)}
    hist = _house(LINE, 600, grad_c_per_m=0.0, biases=biases, colocate_minutes=60)
    out = pa.analyse(hist, LINE, colocation={"startMs": T0, "endMs": T0 + 60 * STEP})
    s1 = out["variation"]["perNode"]["S1"]["temperature"]["mean"]
    s3 = out["variation"]["perNode"]["S3"]["temperature"]["mean"]
    assert abs(s1 - s3) < 0.1                 # the 1.0 C bias is gone


# ── coverage ────────────────────────────────────────────────────────────────

def test_coverage_radius_from_a_known_gradient():
    # 0.1 C per metre, so one sensor stays within +/-0.5 C out to ~5 m.
    hist = _house(LINE, 900, grad_c_per_m=0.1, noise=0.02)
    out = pa.analyse(hist, LINE)
    t = out["coverage"]["fields"]["temperature"]
    assert t["status"] in ("measured", "extrapolated")
    assert 4.0 <= t["radius"] <= 6.0
    node = out["coverage"]["node"]
    assert node["radius"] <= t["radius"] + 1e-9            # the smallest field limits it
    assert node["areaM2"] == pytest.approx(math.pi * node["radius"] ** 2, rel=1e-3)
    assert len(out["coverage"]["pairs"]) == 15              # 6 choose 2


def test_a_uniform_house_reports_no_growth_not_a_fake_radius():
    hist = _house(LINE, 900, grad_c_per_m=0.0, noise=0.02)
    t = pa.analyse(hist, LINE)["coverage"]["fields"]["temperature"]
    assert t["radius"] is None or t["status"] == "extrapolated"


# ── variation ───────────────────────────────────────────────────────────────

def test_variation_compares_spread_with_two_sensor_errors():
    hist = _house(LINE, 900, grad_c_per_m=0.2)
    v = pa.analyse(hist, LINE)["variation"]["between"]["temperature"]
    assert v["twoSensorErrors"] == 1.0
    assert v["meanSpread"] == pytest.approx(2.0, abs=0.2)  # 0.2 C/m over 10 m
    assert v["fractionBeyondSensorError"] > 0.9


# ── placement metrics ───────────────────────────────────────────────────────

def test_placement_rows_metrics_and_recommendation():
    hist = _house(LINE, 900, grad_c_per_m=0.15)
    p = pa.analyse(hist, LINE)["placement"]
    ks = [r["sensors"] for r in p["rows"]]
    assert ks == [2, 3, 4, 5]
    for r in p["rows"]:
        assert r["runtimeUsable"] == (r["sensors"] >= pa.MIN_ANCHORS)
        for m in ("grid", "kriging_greedy", "random"):
            assert m in r["methods"]
            assert set(pa.FIELDS) <= set(r["methods"][m])
        # Every subset was tried, so the best is a true lower bound.
        best = r["methods"]["best"]["normalized"]
        for name, m in r["methods"].items():
            if "normalized" in m:
                assert best <= m["normalized"] + 1e-9, name
    assert p["recommended"] is None or p["recommended"] >= pa.MIN_ANCHORS


def test_too_little_overlap_is_refused_in_words():
    hist = _house(LINE, 100)                  # under four hours
    with pytest.raises(ValueError, match="ten-minute periods"):
        pa.analyse(hist, LINE)


def test_failed_readings_are_counted_and_skipped():
    hist = _house(LINE, 900, fail_every=10)
    out = pa.analyse(hist, LINE)
    assert out["raw"]["S1"]["rejected"]["temperature"]["failed"] == 90
    assert out["buckets"]["common"] >= pa.MIN_COMMON_BUCKETS


# ── the runtime estimator keeps nodes that lack one sensor ──────────────────

def test_a_node_without_light_still_anchors_temperature(monkeypatch):
    from app.api.routes import spatial_service as ss
    now = 1_800_000_000_000
    monkeypatch.setattr(ss, "_server_now_ms", lambda: now)
    written = {}
    monkeypatch.setattr(ss, "_fb_put", lambda path, data: written.__setitem__(path, data))
    secs = {}
    for i, (x, y) in enumerate([(0, 0), (8, 0), (0, 8), (8, 8), (4, 1)]):
        latest = {"timestamp": now, "temperature": 25 + 0.3 * x, "humidity": 80 - y,
                  "light": 2000 + 100 * x if i != 4 else -999}
        secs[f"S{i + 1}"] = {"meta": {"x": x, "y": y}, "latest": latest}
    secs["S9"] = {"meta": {"x": 4, "y": 4}}            # unmonitored
    res = ss.interpolate_house("H1", {"sections": secs})
    est = written["/farm/houses/H1/sections/S9/estimated.json"]
    assert res["anchors"] == 5                          # S5 counted despite no light sensor
    assert est["temperature"] is not None
    assert "light" in est                               # kriged from the four that have it


def test_hourly_series_is_what_the_analysis_ran_on():
    hist = _house(LINE, 600, grad_c_per_m=0.2)       # ten hours
    s = pa.analyse(hist, LINE)["series"]
    assert 9 <= len(s["hourMs"]) <= 11
    assert all(b - a == 3_600_000 for a, b in zip(s["hourMs"], s["hourMs"][1:]))
    for sid in LINE:
        assert len(s["nodes"][sid]["temperature"]) == len(s["hourMs"])
    # The gradient survives: the far end of the line is warmer on average.
    first, last = list(LINE)[0], list(LINE)[-1]
    assert np.mean(s["nodes"][last]["temperature"]) > np.mean(s["nodes"][first]["temperature"])


def test_a_one_way_gradient_gives_an_upper_bound_not_a_whole_house_claim():
    # 2x2 layout, warming only along x. The 5 m pairs across x differ by
    # 0.6 C; the 7 m pairs along y agree. The average line is flat, and this
    # once reported "one node covers at least 8.6 m" - false for the 5 m pairs.
    square = {"S1": (2.5, 3.5), "S2": (7.5, 3.5), "S3": (2.5, 10.5), "S4": (7.5, 10.5)}
    hist = _house(square, 900, grad_c_per_m=0.12, noise=0.02)
    cov = pa.analyse(hist, square)["coverage"]
    t = cov["fields"]["temperature"]
    assert t["status"] == "direction-dependent"
    assert t["atMost"] == 5.0
    node = cov["node"]
    assert node["bound"] == "atMost" and node["radius"] <= 5.0


# ── coverage review fixes, 7 Oct 2026: the failure cases the reviewers built ──

def _cov(coords, temps):
    """coverage() on one snapshot row per field: temperature as given, humidity
    and VPD identical everywhere (so they never limit the answer)."""
    ids = list(coords)
    mats = {"temperature": np.array([[temps[s] for s in ids]], dtype=float),
            "humidity": np.full((1, len(ids)), 80.0),
            "vpd": np.full((1, len(ids)), 0.8)}
    return pa.coverage(mats, ids, coords)


def test_a_noise_level_slope_is_not_a_kilometre_radius():
    # 0.001 C per metre across a 10 m line: the fit reaches 0.5 C at 500 m.
    out = _cov(LINE, {s: 0.001 * x for s, (x, _y) in LINE.items()})
    t = out["fields"]["temperature"]
    assert t["radius"] is None and t["status"] == "no-growth"
    assert out["node"] is None or out["node"].get("radius") is None


def test_the_worst_field_is_never_dropped_from_the_headline():
    # Uncorrected sensor offsets of +/-0.35 C: neighbours 2 m apart differ by 0.7.
    temps = {s: (0.35 if i % 2 else -0.35) for i, s in enumerate(LINE)}
    out = _cov(LINE, temps)
    assert out["fields"]["temperature"]["status"] == "below-spacing"
    assert out["node"]["bound"] == "atMost" and out["node"]["limitedBy"] == "temperature"
    assert out["node"]["radius"] <= 2.0


def test_a_fitted_radius_is_never_beyond_a_closer_pair_that_disagrees():
    # Warming across the 3 m side only: the 3 m pairs differ by 0.75 C.
    rect = {"A": (0.0, 0.0), "B": (3.0, 0.0), "C": (0.0, 10.0), "D": (3.0, 10.0)}
    out = _cov(rect, {s: 0.25 * x for s, (x, _y) in rect.items()})
    t = out["fields"]["temperature"]
    assert t["radius"] is None
    assert t["status"] in ("direction-dependent", "below-spacing")
    assert t["atMost"] <= 3.0
