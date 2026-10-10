"""The humidity tray after the probe was removed (10 Oct 2026).

The grower sets how many seconds a tray fill pours (Pour lengths in the app);
the models decide only WHEN. With no setting, a fill is one full tray. Nothing
reads the tray's level any more, and the probe fields old firmware still sends
must change nothing. The readings here are TEST DATA built for one case each.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes import smart_care_v2 as sc
from app.services.tenant_context import tenant_scope

TZ = timezone(timedelta(minutes=330))
DAY = datetime(2026, 10, 11, 10, 0, tzinfo=TZ)


class _Scaler:
    @staticmethod
    def transform(x):
        return x


def _model(secs):
    class _M:
        @staticmethod
        def predict(x):
            return [float(secs)]
    return _M()


@pytest.fixture
def tray(monkeypatch):
    sent = []
    state = {"model_secs": 40.0, "risk": None}
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: True)
    monkeypatch.setattr(sc, "_fb_get", lambda p: {})
    monkeypatch.setattr(sc, "_issue_node_command", lambda *x, **k: sent.append(x) or {"id": "c1"})
    monkeypatch.setattr(sc, "_drop_risk", lambda *x, **k: state["risk"])

    def decide(humidity=45.0, durations=None, prev=None, latest_extra=None, when=DAY):
        monkeypatch.setattr(sc, "_tray", {"scaler": _Scaler(), "model": _model(state["model_secs"]),
                                          "rh_target_low": 60.0, "rh_target_high": 80.0,
                                          "drop_threshold": 0.7, "drop_horizon_hours": 3})
        latest = {"timestamp": when.timestamp() * 1000, "temperature": 31.0,
                  "humidity": humidity, "light": 9000, **(latest_extra or {})}
        section = {"latest": latest, "control": {"override": "auto"}}
        if durations:
            section["control"]["durations"] = durations
        if prev:
            section["tray"] = prev
        with tenant_scope("t_tray"):
            return sc._tray_decision("H1", "S1", section, now=when)

    decide.sent = sent
    decide.state = state
    return decide


def test_with_no_setting_a_fill_is_one_full_tray(tray):
    out = tray()
    assert out["status"] == "fill"
    assert out["fillSeconds"] == sc.TRAY_MAX_SEC
    assert out["amountSetBy"] == "full tray"
    assert len(tray.sent) == 1 and tray.sent[0][3] == sc.TRAY_MAX_SEC


def test_the_growers_amount_is_what_every_fill_pours(tray):
    out = tray(durations={"tray": 5})
    assert out["fillSeconds"] == 5 and out["amountSeconds"] == 5 and out["amountSetBy"] == "you"
    assert tray.sent[0][3] == 5


def test_a_setting_above_the_tray_is_capped_at_what_it_holds(tray):
    out = tray(durations={"tray": 999})
    assert out["fillSeconds"] == sc.TRAY_MAX_SEC


def test_the_model_still_decides_when(tray):
    tray.state["model_secs"] = 0
    out = tray(humidity=72.0, durations={"tray": 5})
    assert out["status"] == "ok" and out["fillSeconds"] == 0 and tray.sent == []
    assert out["amountSeconds"] == 5            # shown, not poured


def test_an_anticipated_drop_pours_the_same_amount(tray):
    tray.state["model_secs"] = 0
    tray.state["risk"] = 0.9
    out = tray(humidity=68.0, durations={"tray": 7})
    assert out["status"] == "prefill" and out["fillSeconds"] == 7


def test_old_firmware_probe_fields_change_nothing(tray):
    # A probe reading "full" used to block the fill; "empty" used to force one.
    full = tray(latest_extra={"sampleMoisture": 95.0, "soilRaw": 1100})
    assert full["status"] == "fill" and full["fillSeconds"] == sc.TRAY_MAX_SEC
    tray.state["model_secs"] = 0
    empty = tray(humidity=72.0, latest_extra={"sampleMoisture": 0.0, "soilRaw": 2600})
    assert empty["status"] == "ok" and empty["fillSeconds"] == 0
    for key in ("trayLevel", "trayEmpty", "trayResponds"):
        assert key not in full and key not in empty


def test_the_rest_after_a_fill_scales_with_what_went_in(tray):
    filled = (DAY - timedelta(hours=1)).timestamp() * 1000
    whole = tray(prev={"lastFillTs": filled, "lastFillSeconds": sc.TRAY_MAX_SEC})
    assert whole["status"] == "cooldown" and whole["cooldownHours"] == sc.COOLDOWN_HOURS
    assert whole["trayAtLimit"] is True        # filled, still dry: the second-watering gate
    part = tray(prev={"lastFillTs": filled, "lastFillSeconds": 5})
    assert part["cooldownHours"] < sc.COOLDOWN_HOURS


def test_the_app_never_sees_the_retired_fields():
    shown = sc._display({"timestamp": 1, "temperature": 30.0, "humidity": 70.0,
                         "sampleMoisture": 40.0, "soilRaw": 2000})
    assert "sampleMoisture" not in shown and "soilRaw" not in shown
    assert shown["temperature"] == 30.0
