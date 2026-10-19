"""A new section can be created at a spot on the house map (18 Oct 2026).

A section added without coordinates never appears on the map - "Section 5" on
the test farm went missing exactly that way. Firebase is a dict here.
"""
import asyncio
import copy

import pytest
from fastapi import HTTPException


class FakeFirebase:
    def __init__(self, meta):
        self.tree = {"farm": {"houses": {"H1": {"meta": meta, "sections": {
            "S1": {"meta": {"name": "Section 1", "x": 1.0, "y": 1.0}}}}}}}

    def _walk(self, path, create=False):
        parts = [x for x in path.split("?")[0].removesuffix(".json").split("/") if x]
        node = self.tree
        for k in parts[:-1]:
            if k not in node:
                if not create:
                    return None, None
                node[k] = {}
            node = node[k]
        return node, parts[-1]

    def get(self, path):
        parent, key = self._walk(path)
        return copy.deepcopy(parent.get(key)) if isinstance(parent, dict) else None

    def put(self, path, value):
        parent, key = self._walk(path, create=True)
        parent[key] = value
        return True


@pytest.fixture
def sc_f(monkeypatch):
    from app.api.routes import smart_care_v2 as sc
    f = FakeFirebase({"name": "Coconut tree house", "width": 4.99, "length": 9.7})
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    return sc, f


def add(sc, **kw):
    return asyncio.run(sc.add_section("H1", sc.SectionIn(name="New spot", **kw), ctx=None))


def test_a_spot_inside_the_house_is_saved_with_the_section(sc_f):
    sc, f = sc_f
    out = add(sc, x=2.4, y=8.85)
    meta = f.tree["farm"]["houses"]["H1"]["sections"][out["sectionId"]]["meta"]
    assert out["sectionId"] == "S2" and (meta["x"], meta["y"]) == (2.4, 8.85)


def test_a_spot_outside_the_house_is_refused(sc_f):
    sc, f = sc_f
    with pytest.raises(HTTPException) as e:
        add(sc, x=2.0, y=12.0)
    assert e.value.status_code == 400 and "outside the house" in e.value.detail
    assert "S2" not in f.tree["farm"]["houses"]["H1"]["sections"]


def test_half_a_position_is_refused(sc_f):
    sc, _f = sc_f
    with pytest.raises(HTTPException) as e:
        add(sc, x=2.0)
    assert e.value.status_code == 400


def test_old_callers_without_a_position_still_work(sc_f):
    sc, f = sc_f
    out = add(sc)
    meta = f.tree["farm"]["houses"]["H1"]["sections"][out["sectionId"]]["meta"]
    assert "x" not in meta and meta["name"] == "New spot"
