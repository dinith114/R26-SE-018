"""The outdoor fetch works when the forecast model is not loaded.

`forecast_v2.pkl` is not in the repository - it is a trained artefact, built by
`ml_pipeline/build_forecast_model.py` - so CI runs with `_fc` as None, and so
does any fresh clone before the models are built.

`_fetch_outdoor` used to reach into `_fc` for a clearness reference without
checking it existed. With no model that raised AttributeError, and the broad
`except Exception` around the whole function reported it as "outdoor forecast
unavailable" - which reads as the weather service being down and sends whoever
is debugging it after the network instead of the missing file.

It never bit production, because `predict_day` only calls it behind `ready()`
and `ready()` is exactly `_fc is not None`. It bit CI, where a tenancy test
called the helper directly, and it took a red build to notice - a failure that
had been reported as somebody else's outage the whole time.

So the point of this test is not the clearness number. It is that the helper
stands on its own, and that the next person to call it directly does not spend
an afternoon on a network that was never the problem.
"""
from __future__ import annotations

import json

import pytest

from app.api.routes import forecast as fx
from app.services.tenant_context import tenant_scope


class _Body:
    """Enough of an http response for json.load."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


@pytest.fixture
def offline_weather(monkeypatch):
    """A stubbed Open-Meteo reply, so no test here touches the network."""
    payload = json.dumps({"hourly": {
        "temperature_2m": [30.0] * 24,
        "relative_humidity_2m": [70.0] * 24,
        "shortwave_radiation": [500.0] * 24,
    }}).encode()
    monkeypatch.setattr(fx.urllib.request, "urlopen",
                        lambda url, timeout=None: _Body(payload))
    monkeypatch.setattr(fx, "farm_location", lambda: (7.0, 80.0))
    fx._outdoor_cache.clear()
    yield
    fx._outdoor_cache.clear()


def test_fetch_outdoor_works_with_no_model_loaded(monkeypatch, offline_weather):
    monkeypatch.setattr(fx, "_fc", None)

    with tenant_scope("t_nomodel"):
        out = fx._fetch_outdoor("2026-09-04")

    assert out is not None, (
        "the helper still needs the model it is supposed to work without")
    # The four measured values come from the weather, not from the model.
    assert out["out_tmax"] == 30.0
    assert out["out_rhmin"] == 70.0
    assert out["out_radsum"] == 12000.0
    assert out["out_radmax"] == 500.0
    # Only clearness needs a calibration reference. With none, comparing the day
    # against itself gives 1.0 - which says "no reference" rather than inventing
    # a sky condition.
    assert out["out_clearness"] == 1.0


def test_a_model_with_no_calibration_for_this_month_also_survives(
        monkeypatch, offline_weather):
    """The older, narrower version of the same gap.

    `monthly_peak_radsum` is keyed by month, and a model trained on a partial
    year has months missing. That fallback already existed; this pins it, so a
    later tidy-up of the None handling cannot quietly take it away too.
    """
    monkeypatch.setattr(fx, "_fc", {"monthly_peak_radsum": {1: 99999.0}})

    with tenant_scope("t_othermonth"):
        out = fx._fetch_outdoor("2026-09-04")          # month 9, not in the map

    assert out is not None
    assert out["out_clearness"] == 1.0


def test_the_month_key_is_read_as_both_int_and_string(
        monkeypatch, offline_weather):
    """joblib round-trips dict keys as ints, JSON would make them strings.

    The lookup tries both. Worth pinning because it looks redundant and is the
    kind of line somebody deletes while tidying.
    """
    monkeypatch.setattr(fx, "_fc", {"monthly_peak_radsum": {"9": 24000.0}})

    with tenant_scope("t_strkey"):
        out = fx._fetch_outdoor("2026-09-04")

    assert out["out_clearness"] == 0.5, (
        "12000 / 24000 - the string key was not consulted")
