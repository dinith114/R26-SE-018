"""
Hybrid Pollination - Compatibility Service Layer

Wraps the Level 2 Parent A x Parent B engine for the API.

The engine deliberately never returns a success probability - the orchid
register records only successes, so it has no denominator. See
ml-models/hybrid_pollination/src/compatibility.py for the full reasoning.
"""

import os
import sys

ML_SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ml-models", "hybrid_pollination", "src"
)
sys.path.insert(0, ML_SRC_DIR)


class CompatibilityService:
    """Singleton wrapper around the compatibility engine."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.engine = None
        self.error = ""
        self._load()

    def _load(self):
        try:
            from compatibility import CompatibilityEngine
            self.engine = CompatibilityEngine()
            n = len(self.engine.kb.crosses)
            print(f"[INFO] Compatibility engine loaded ({n} registered crosses)")
        except Exception as e:
            self.error = str(e)
            print(f"[ERROR] Could not load compatibility engine: {e}")

    @property
    def is_loaded(self) -> bool:
        return self.engine is not None

    def assess(self, pod_parent: str, pollen_parent: str,
               pod_health: dict = None, pollen_health: dict = None) -> dict:
        """
        Assess one directional pairing. Pod parent first, always.

        `pod_health` / `pollen_health` carry a Level 1 image assessment into the
        Level 2 cross check, so a photograph of the plant and the name on its
        tag are used together: the image answers what condition the plant is in,
        the name answers what it can be crossed with.
        """
        result = self.engine.assess(pod_parent, pollen_parent,
                                    pod_health=pod_health,
                                    pollen_health=pollen_health)
        out = result.to_dict()

        # The grower's own attempts at THIS pairing, from the crossing logbook.
        #
        # The register holds 27 crosses, all of them successes, because nobody
        # registers a cross that died - so it can state that a pairing is
        # possible and can never state how often it works. The logbook is the
        # other half: the same grower's attempts, failures included, which is
        # the only place a real rate could come from.
        #
        # Imported here rather than at module load: the logbook is a separate
        # service with its own storage, and a failure to read it must leave the
        # compatibility verdict intact rather than taking the endpoint down.
        try:
            from app.services.cross_log_service import cross_log_service
            out["your_history"] = cross_log_service.history_for(
                pod_parent, pollen_parent
            )
        except Exception as e:
            print(f"[WARN] logbook history unavailable: {e}")
            out["your_history"] = {}

        return out

    def rank(self, pod_parent: str, candidates: list,
             pod_health: dict = None) -> list:
        """Rank candidate pollen donors for one pod parent."""
        results = self.engine.rank_partners(pod_parent, candidates,
                                            pod_health=pod_health)
        return [r.to_dict() for r in results]

    def known_parents(self) -> list:
        """
        Every parent name the knowledge base recognises.

        Used by the app to offer suggestions as the grower types, so they are
        steered toward names the engine can actually find evidence for.
        """
        if not self.is_loaded:
            return []

        names = set()
        for c in self.engine.kb.crosses:
            names.add(c["seed_parent"])
            names.add(c["pollen_parent"])
            if c.get("grex"):
                names.add(c["grex"])
        for species in self.engine.kb.traits.values():
            names.add(species["species"])

        return sorted(names)

    def info(self) -> dict:
        return {
            "engine_loaded": self.is_loaded,
            "registered_crosses": len(self.engine.kb.crosses) if self.is_loaded else 0,
            "nothogenera": len(self.engine.kb.nothogenera) if self.is_loaded else 0,
            "documented_species": len(self.engine.kb.traits) if self.is_loaded else 0,
            "error": self.error,
        }


compatibility_service = CompatibilityService()
