"""Setting a section's growth stage from the app (15 Oct 2026).

Growth stage decides which plant food a section gets. Until now it could only be
chosen when the section was created, carried no date, and the camera path had
no writer. These pin down the new endpoint and how the resolver reads what it
writes. Firebase is a dict here; nothing leaves the process.
"""
from datetime import datetime, timedelta, timezone

import pytest

TZ = timezone(timedelta(minutes=330))
BASE = "/farm/houses/H1/sections/S1"


class FakeFirebase:
    def __init__(self):
        self.tree = {"farm": {"houses": {"H1": {"sections": {"S1": {
            "meta": {"name": "Bright edge", "growthStage": "Active"}}}}}}}
        self.deleted = []

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
        v = parent[key]
        if "shallow=true" in path and isinstance(v, dict):
            return {k: True for k in v}
        return v

    def put(self, path, value):
        parent, key = self._walk(path, create=True)
        parent[key] = value
        return True

    def delete(self, path):
        self.deleted.append(path)
        parent, key = self._walk(path)
        if isinstance(parent, dict):
            parent.pop(key, None)
        return True


@pytest.fixture
def fb(monkeypatch):
    from app.api.routes import smart_care_v2 as sc
    f = FakeFirebase()
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    monkeypatch.setattr(sc, "_fb_delete", f.delete)
    monkeypatch.setattr(sc, "farm_tz", lambda: TZ)
    monkeypatch.setattr(sc, "_ready", lambda: False)     # no models in CI
    return sc, f


def meta(f):
    return f.tree["farm"]["houses"]["H1"]["sections"]["S1"]["meta"]


def test_a_manual_stage_is_saved_with_its_date(fb):
    sc, f = fb
    out = sc.set_growth_stage("H1", "S1", sc.GrowthStageIn(stage="Flowering"), ctx=None)
    m = meta(f)
    assert m["growthStage"] == "Flowering" and m["growthStageBy"] == "manual"
    assert abs(m["growthStageSetAt"] - out["setAt"]) == 0
    gs = sc._resolve_growth_stage({"meta": m})
    assert gs["stage"] == "Flowering" and gs["source"] == "manual"
    assert gs["needsAttention"] is False
    assert gs["message"].startswith("Growth stage set by you on ")
    assert m["name"] == "Bright edge"                    # the rest of meta untouched


def test_a_stage_from_a_photo_says_what_the_photo_saw(fb):
    sc, f = fb
    sc.set_growth_stage("H1", "S1", sc.GrowthStageIn(
        stage="Flowering", by="photo", photoStage="pre_bloom", photoConfidence=0.873), ctx=None)
    m = meta(f)
    assert m["growthStagePhoto"] == {"stage": "pre_bloom", "confidence": 0.873}
    gs = sc._resolve_growth_stage({"meta": m})
    assert gs["source"] == "photo" and gs["stage"] == "Flowering"
    assert "pre bloom (87%), fed as Flowering" in gs["message"]


def test_setting_by_hand_after_a_photo_forgets_the_photo(fb):
    sc, f = fb
    sc.set_growth_stage("H1", "S1", sc.GrowthStageIn(
        stage="Flowering", by="photo", photoStage="budding", photoConfidence=0.9), ctx=None)
    sc.set_growth_stage("H1", "S1", sc.GrowthStageIn(stage="Active"), ctx=None)
    m = meta(f)
    assert "growthStagePhoto" not in m and m["growthStageBy"] == "manual"
    assert any(p.endswith("/meta/growthStagePhoto.json") for p in f.deleted)


@pytest.mark.parametrize("body", [
    {"stage": "Blooming"},
    {"stage": "Active", "by": "guess"},
    {"stage": "Flowering", "by": "photo", "photoStage": "Flowering"},
    {"stage": "Flowering", "by": "photo", "photoStage": "budding", "photoConfidence": 87},
])
def test_nonsense_is_refused_and_nothing_written(fb, body):
    sc, f = fb
    with pytest.raises(sc.HTTPException) as e:
        sc.set_growth_stage("H1", "S1", sc.GrowthStageIn(**body), ctx=None)
    assert e.value.status_code == 400
    assert meta(f) == {"name": "Bright edge", "growthStage": "Active"}


def test_an_unknown_section_is_404(fb):
    sc, _ = fb
    with pytest.raises(sc.HTTPException) as e:
        sc.set_growth_stage("H1", "S9", sc.GrowthStageIn(stage="Active"), ctx=None)
    assert e.value.status_code == 404


def test_a_newer_choice_beats_an_older_camera_prediction(fb):
    sc, _ = fb
    now = datetime.now(timezone.utc).timestamp() * 1000
    pred = {"stage": "Dormant", "confidence": 0.95, "predictedAt": now - 3_600_000}
    newer = {"meta": {"growthStage": "Flowering", "growthStageSetAt": now}, "growthPrediction": pred}
    assert sc._resolve_growth_stage(newer)["stage"] == "Flowering"
    older = {"meta": {"growthStage": "Flowering", "growthStageSetAt": now - 7_200_000},
             "growthPrediction": pred}
    assert sc._resolve_growth_stage(older)["stage"] == "Dormant"


def test_operators_may_set_it(fb):
    """Feeding is already theirs (fertilizeSection is admin+operator)."""
    import inspect
    from app.main import app
    route = next(r for r in app.routes
                 if getattr(r, "path", "") == "/api/v2/care/houses/{house_id}/sections/{section_id}/growth-stage")
    dep = next(d.call for d in route.dependant.dependencies if d.call.__name__ == "_dep")
    assert sorted(inspect.getclosurevars(dep).nonlocals["allowed"]) == ["admin", "operator"]
