"""
Hybrid Pollination - what the grower can breed from.

WHY THIS IS NOT JUST A NAME LIST
--------------------------------
The Varieties tab used to return the names in the knowledge base and nothing
else. That is the REGISTER's contents, not the grower's, and the two barely
overlap: the register extract holds species and intergeneric nothogenera -
Aerides lawrenceae, Aranda Blue Star - while the collection this project was
built around is Thai Vanda hybrids. A grower opening that tab saw fifty-three
names of plants they have never grown, and none of their own.

So this returns two groups, kept apart because they answer different
questions:

    mine      what this grower actually has, with photographs
    register  what the knowledge base has evidence for, names only

The second is also an honest statement of coverage. A grower can see exactly
how much the register knows before relying on it, which is the same reason the
input gate refuses rather than guesses and the cross check reports an evidence
tier rather than a percentage.

NAMES CARRY A CONFIDENCE TIER
-----------------------------
A name typed by a grower is not the same kind of fact as a name in the
register, and a photograph with the wrong name on it is worse than no name at
all. Every entry therefore says which it is:

    register   the name matches an entry in the knowledge base
    named      a name, from a tag or from the grower, not in the register
    unnamed    no name; the plant is filed under an id it can be labelled with

A mistyped name shows up as `named`, where it misleads nobody, rather than
sitting unmarked beside a registered one.
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
COLLECTION_DIR = os.path.join(
    BASE_DIR, "ml-models", "hybrid_pollination", "data", "knowledge", "collection")
MANIFEST = os.path.join(COLLECTION_DIR, "plants.json")

TIER_REGISTER = "register"
TIER_NAMED = "named"
TIER_UNNAMED = "unnamed"


class VarietiesService:
    """The two lists behind the Varieties tab."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self):
        if self._ready:
            return
        self._ready = True
        self.collection = self._load_collection()

    @staticmethod
    def _load_collection() -> list:
        """
        Photographs of plants in this project's collection.

        Shipped with the repository rather than written at runtime, so a fresh
        checkout shows the same plants this project was built on instead of an
        empty tab.
        """
        if not os.path.exists(MANIFEST):
            print(f"[WARN] collection manifest missing: {MANIFEST}")
            return []
        try:
            with open(MANIFEST, encoding="utf-8") as fh:
                return json.load(fh).get("plants", [])
        except Exception as e:
            print(f"[WARN] collection manifest unreadable: {e}")
            return []

    def photo_path(self, name: str) -> str:
        """Absolute path of a collection photograph, or "" if not one of ours."""
        safe = os.path.basename(name)
        path = os.path.join(COLLECTION_DIR, safe)
        return path if os.path.exists(path) else ""

    # ── the two lists ─────────────────────────
    def mine(self) -> list:
        """
        The grower's own plants: the collection shipped with the project, plus
        every plant registered through the crossing logbook.

        Logbook plants are included because that is how the list grows. A
        grower who logs a cross has, in doing so, registered two plants with
        photographs - and they should not have to enter them a second time to
        see them here.
        """
        from app.services.compatibility_service import compatibility_service
        from app.services.cross_log_service import cross_log_service

        kb = compatibility_service.engine.kb if compatibility_service.is_loaded else None

        def tier_for(name: str) -> str:
            if not name:
                return TIER_UNNAMED
            if kb and kb.knows_name(name):
                return TIER_REGISTER
            return TIER_NAMED

        out, seen = [], set()

        for p in self.collection:
            name = p.get("tag_name", "")
            key = name.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": name,
                "tier": tier_for(name),
                "photo": f"collection/{p['photo']}",
                "seed_parent": p.get("seed_parent", ""),
                "pollen_parent": p.get("pollen_parent", ""),
                "colour": p.get("dominant_colour", ""),
                "pattern": p.get("pattern", ""),
                "source": "collection",
            })

        for p in cross_log_service.plants():
            name = (p.get("name") or "").strip()
            key = (name or p["plantId"]).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": name or p["plantId"],
                "plantId": p["plantId"],
                "tier": tier_for(name),
                "photo": f"log/{p['photo']}" if p.get("photo") else "",
                "seed_parent": "", "pollen_parent": "",
                "colour": "", "pattern": "",
                "source": "logbook",
            })

        out.sort(key=lambda r: (r["tier"] == TIER_UNNAMED, r["name"].lower()))
        return out

    def register(self) -> list:
        """
        Every name the knowledge base has evidence for, with how much.

        `crosses` is the count of registered crosses that cite the name, which
        is what makes this a statement of coverage rather than a list: a name
        appearing in one cross is weaker evidence than one appearing in five,
        and the grower can see which is which.
        """
        from app.services.compatibility_service import compatibility_service
        if not compatibility_service.is_loaded:
            return []
        kb = compatibility_service.engine.kb

        counts, genus = {}, {}
        for c in kb.crosses:
            for side in ("seed", "pollen"):
                n = c.get(f"{side}_parent")
                if n:
                    counts[n] = counts.get(n, 0) + 1
                    genus.setdefault(n, c.get(f"{side}_genus", ""))
            if c.get("grex"):
                counts.setdefault(c["grex"], 0)

        for sp in kb.traits.values():
            counts.setdefault(sp["species"], 0)

        return sorted(
            ({"name": n, "tier": TIER_REGISTER, "crosses": k,
              "genus": genus.get(n, "")} for n, k in counts.items()),
            key=lambda r: r["name"].lower())

    def summary(self) -> dict:
        mine = self.mine()
        reg = self.register()
        return {
            "mine": mine,
            "register": reg,
            "counts": {
                "mine": len(mine),
                "with_photo": sum(1 for p in mine if p["photo"]),
                "register": len(reg),
                "registered_crosses": len(
                    compatibility_engine_crosses()),
            },
            "note": "Photographs are of plants in this collection. A tag name "
                    "is what is written on the label; it is not a claim that "
                    "the plant is the registered variety of that name.",
        }


def compatibility_engine_crosses() -> list:
    from app.services.compatibility_service import compatibility_service
    if not compatibility_service.is_loaded:
        return []
    return compatibility_service.engine.kb.crosses


varieties_service = VarietiesService()
