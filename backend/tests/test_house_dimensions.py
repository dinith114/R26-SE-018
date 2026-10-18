"""Correcting a house's size, and moving its sections with it (17 Oct 2026).

The farm's house is 4.99 x 9.7 m (16 x 32 ft); the app had planned it as
10 x 14 m and had no way to correct a size afterwards. Firebase is a dict here.
"""
import asyncio

import pytest


class FakeFirebase:
    def __init__(self, sections):
        self.tree = {"farm": {"houses": {"H1": {
            "meta": {"name": "Test", "width": 10.0, "length": 14.0, "type": "shade-net"},
            "sections": {sid: {"meta": dict(m)} for sid, m in sections.items()}}}}}

    def _walk(self, path, create=False):
        parts = [x for x in path.split("?")[0].removesuffix(".json").split("/") if x]
        node = self.tree
        for k in parts[:-1]:
            if not isinstance(node, dict) or (k not in node and not create):
                return None, None
            node = node.setdefault(k, {})
        return node, parts[-1]

    def get(self, path):
        parent, key = self._walk(path)
        return parent.get(key) if isinstance(parent, dict) else None

    def put(self, path, value):
        parent, key = self._walk(path, create=True)
        parent[key] = value
        return True


GRID = {"S1": {"x": 2.5, "y": 3.5, "name": "Section 1"}, "S2": {"x": 7.5, "y": 3.5},
        "S3": {"x": 2.5, "y": 10.5}, "S4": {"x": 7.5, "y": 10.5}, "S5": {"name": "unplaced"}}


@pytest.fixture
def fb(monkeypatch):
    from app.api.routes import smart_care_v2 as sc
    f = FakeFirebase(GRID)
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    return sc, f


def run(sc, **body):
    return asyncio.run(sc.set_house_dimensions("H1", sc.DimensionsIn(**body), ctx=None))


def secs(f):
    return {k: (v["meta"].get("x"), v["meta"].get("y"))
            for k, v in f.tree["farm"]["houses"]["H1"]["sections"].items()}


def test_a_new_size_leaves_measured_positions_alone_by_default(fb):
    sc, f = fb
    out = run(sc, width=4.99, length=9.7)
    meta = f.tree["farm"]["houses"]["H1"]["meta"]
    assert (meta["width"], meta["length"]) == (4.99, 9.7) and meta["name"] == "Test"
    assert out["moved"] == {}
    assert secs(f)["S1"] == (2.5, 3.5)


def test_asked_to_scale_the_planned_grid_follows_the_house(fb):
    sc, f = fb
    out = run(sc, width=4.99, length=9.7, scaleSections=True)
    s = secs(f)
    assert s["S1"] == (1.25, 2.42) and s["S2"] == (3.74, 2.42)
    # 10.5 x 9.7 / 14 = 7.275, which rounds to 7.27 in binary floating point
    assert s["S3"] == (1.25, 7.27) and s["S4"] == (3.74, 7.27)
    assert s["S5"] == (None, None)                      # unplaced stays unplaced
    assert set(out["moved"]) == {"S1", "S2", "S3", "S4"}
    assert f.tree["farm"]["houses"]["H1"]["sections"]["S1"]["meta"]["name"] == "Section 1"


def test_feet_arrive_as_metres_and_scaling_twice_is_harmless(fb):
    sc, f = fb
    run(sc, width=4.88, length=9.75, scaleSections=True)    # 16 x 32 ft, sent by the app
    first = secs(f)
    run(sc, width=4.88, length=9.75, scaleSections=True)    # saved again: same size, no move
    assert secs(f) == first


def test_scaling_a_house_that_had_no_size_is_refused(fb):
    sc, f = fb
    f.tree["farm"]["houses"]["H1"]["meta"].pop("width")
    with pytest.raises(sc.HTTPException) as e:
        run(sc, width=5, length=10, scaleSections=True)
    assert e.value.status_code == 400
    assert secs(f)["S1"] == (2.5, 3.5)


def test_impossible_sizes_are_refused_before_anything_is_written():
    from pydantic import ValidationError
    from app.api.routes import smart_care_v2 as sc
    for w, l in ((0.5, 10), (5, 250)):
        with pytest.raises(ValidationError):
            sc.DimensionsIn(width=w, length=l)
