"""Humidity-drop predictions are kept and checked against what happened (18 Oct 2026).

Only the latest tray decision used to survive, so nobody could ask "it said a
drop was coming at 09:15 - did one come?". These pin the record and the check.
Firebase is a dict here; nothing leaves the process.
"""
import copy
from datetime import datetime, timedelta, timezone

H = 3_600_000
T0 = 1_792_000_000_000                       # a fixed epoch, ms
TZ = timezone(timedelta(minutes=330))


class FakeFirebase:
    def __init__(self):
        self.tree = {"farm": {}}

    def _walk(self, path, create=False):
        parts = [x for x in path.split("?")[0].removesuffix(".json").split("/") if x]
        node = self.tree
        for k in parts[:-1]:
            if not isinstance(node, dict):
                return None, None
            if k not in node:
                if not create:
                    return None, None
                node[k] = {}
            node = node[k]
        return node, parts[-1]

    def get(self, path):
        parent, key = self._walk(path)
        if not isinstance(parent, dict) or key not in parent:
            return None
        return copy.deepcopy(parent[key])

    def put(self, path, value):
        parent, key = self._walk(path, create=True)
        parent[key] = value
        return True

    def delete(self, path):
        parent, key = self._walk(path)
        if isinstance(parent, dict):
            parent.pop(key, None)
        return True


def install(monkeypatch, now_ms):
    from app.api.routes import smart_care_v2 as sc
    f = FakeFirebase()
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    monkeypatch.setattr(sc, "_fb_delete", f.delete)
    monkeypatch.setattr(sc, "_server_now_ms", lambda: float(now_ms))
    return sc, f


def predict(f, at, says, risk=0.8):
    f.put(f"/farm/trayPredictions/H1/S1/{at}.json",
          {"at": at, "atLocal": "x", "risk": risk, "threshold": 0.7, "horizonHours": 3.0,
           "humidity": 72.0, "lowBand": 60.0, "saysDrop": says})


def readings(f, start, hums):
    """One reading every 20 minutes from `start`, with these humidities."""
    for i, h in enumerate(hums):
        t = start + i * 20 * 60_000
        f.put(f"/farm/history/H1/S1/k{t}.json", {"timestamp": t, "temperature": 30.0, "humidity": h})


def test_each_prediction_is_judged_against_the_next_three_hours(monkeypatch):
    sc, f = install(monkeypatch, now_ms=T0 + 40 * H)
    calm, falls = [72, 70, 69, 68, 67, 66, 66, 67, 68], [72, 68, 64, 61, 58, 57, 58, 60, 62]
    cases = [(0, True, falls), (4, True, calm), (8, False, falls), (12, False, calm)]
    for hour, says, hums in cases:
        predict(f, T0 + hour * H, says)
        readings(f, T0 + hour * H + 60_000, hums)
    # a prefill: said drop, and the tray was filled straight away
    predict(f, T0 + 16 * H, True)
    readings(f, T0 + 16 * H + 60_000, calm)
    f.put(f"/farm/events/H1/S1/{T0 + 16 * H + 5_000}.json",
          {"at": T0 + 16 * H + 5_000, "action": "tray", "reason": "prefill"})
    # only two readings in its window
    predict(f, T0 + 22 * H, False)
    readings(f, T0 + 22 * H + 60_000, [70, 69])
    # still running
    predict(f, T0 + 39 * H, True)

    out = sc.drop_predictions("H1", "S1", days=7, ctx=None)
    got = [r["outcome"] for r in out["predictions"]]
    assert got == ["hit", "false alarm", "missed", "correct quiet", "tray filled", "no data", "pending"]
    s = out["summary"]
    assert (s["hit"], s["false alarm"], s["missed"], s["correct quiet"]) == (1, 1, 1, 1)
    assert s["judged"] == 4 and s["precision"] == 0.5 and s["recall"] == 0.5


def test_no_predictions_gives_no_scores_rather_than_zero(monkeypatch):
    sc, _f = install(monkeypatch, now_ms=T0)
    out = sc.drop_predictions("H1", "S1", days=7, ctx=None)
    assert out["predictions"] == [] and out["summary"]["precision"] is None
    assert out["summary"]["recall"] is None and out["summary"]["judged"] == 0


def test_the_record_keeps_one_prediction_per_fifteen_minutes(monkeypatch):
    sc, f = install(monkeypatch, now_ms=T0)
    base = datetime(2026, 10, 18, 9, 0, tzinfo=TZ)
    sc._log_drop_prediction("H1", "S1", base + timedelta(minutes=2), 0.81, 0.7, 3, 72.0, 60.0)
    sc._log_drop_prediction("H1", "S1", base + timedelta(minutes=9), 0.66, 0.7, 3, 71.0, 60.0)
    sc._log_drop_prediction("H1", "S1", base + timedelta(minutes=16), 0.40, 0.7, 3, 70.0, 60.0)
    kept = f.tree["farm"]["trayPredictions"]["H1"]["S1"]
    assert len(kept) == 2                         # 09:02 and 09:09 share one slot
    first = kept[min(kept)]
    assert first["saysDrop"] is False and first["risk"] == 0.66      # the later call in a slot wins
    assert kept[max(kept)]["horizonHours"] == 3.0 and kept[max(kept)]["lowBand"] == 60.0
