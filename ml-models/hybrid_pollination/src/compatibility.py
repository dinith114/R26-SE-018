"""
Hybrid Pollination - Parent A x Parent B Compatibility

Level 2 of the component. Level 1 asks "is this ONE plant fit to breed from";
this asks "should these TWO plants be crossed, and in which direction".

WHAT THIS DOES NOT DO, AND WHY
------------------------------
It does not output a success probability. It cannot, and neither can anything
else built on the available data.

The RHS International Orchid Register records hybrids that were successfully
made and registered. Nobody registers "I attempted this cross and got no pod".
The register therefore has no denominator: it can prove a pairing IS possible,
but it can never say how often such attempts succeed.

This is visible as a direct contradiction in the source material:

    RHS-derived compilation  : intergeneric crosses = "moderate-high success"
    Peradeniya breeder       : "most intergeneric crosses don't work"

Both are honest. The register sees only the survivors; the breeder sees the
attempts. Any percentage derived from the register alone would be survivorship
bias dressed as a measurement.

So the output is an EVIDENCE TIER plus the precedents behind it. A breeder can
act on "this exact cross has been registered 3 times" far more safely than on
a fabricated "87% likely to succeed".

DIRECTION MATTERS
-----------------
By convention the pod (seed) parent is written first, then the pollen parent.
A x B and B x A are different attempts. Nothing here sorts the pair.
"""

import os
import csv
import sys
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cross_notation import (
    parse_cross, normalise_name, expand_genus, suggest_genus,
    genus_alliance, GENUS_ABBREV, VANDA_ALLIANCE,
)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "data", "knowledge")

CROSSES_CSV = os.path.join(KNOWLEDGE_DIR, "registered_crosses.csv")
NOTHOGENERA_CSV = os.path.join(KNOWLEDGE_DIR, "nothogenera.csv")
TRAITS_CSV = os.path.join(KNOWLEDGE_DIR, "parent_traits.csv")

# The native Sri Lankan species the Peradeniya breeder uses when an imported
# hybrid x hybrid cross yields no pod. Broadly compatible, but reduces flower
# size in the offspring.
RESCUE_PARENT = "V. tessellata"


# ──────────────────────────────────────────────
# Evidence tiers
# ──────────────────────────────────────────────
TIER_REGISTERED = "registered"        # This exact pairing is in the register
TIER_GENUS_PROVEN = "genus_proven"    # This genus combination is registered
TIER_UNDEMONSTRATED = "undemonstrated"  # No registered precedent found
TIER_BLOCKED = "blocked"              # Plant health rules out the attempt
TIER_UNKNOWN_NAME = "unknown_name"    # A name was not recognised - cannot judge

TIER_ORDER = [TIER_BLOCKED, TIER_UNKNOWN_NAME, TIER_UNDEMONSTRATED,
              TIER_GENUS_PROVEN, TIER_REGISTERED]

# The methodology specifies a two-class output (Compatible / Low Compatibility).
# The four evidence tiers carry more information, so they are kept as the
# primary result and this mapping provides the simpler view on top rather than
# replacing it. "Not Advised" is separated out because a health block is a
# different kind of answer from weak evidence.
TIER_TO_CLASS = {
    TIER_REGISTERED: "Compatible",
    TIER_GENUS_PROVEN: "Compatible",
    TIER_UNDEMONSTRATED: "Low Compatibility",
    TIER_UNKNOWN_NAME: "Cannot Check",
    TIER_BLOCKED: "Not Advised",
}

TIER_LABEL = {
    TIER_REGISTERED: "Registered precedent",
    TIER_GENUS_PROVEN: "Genus combination proven",
    TIER_UNDEMONSTRATED: "No registered precedent",
    TIER_UNKNOWN_NAME: "Name not recognised",
    TIER_BLOCKED: "Not advised - plant condition",
}


@dataclass
class CompatibilityResult:
    """A directional verdict on one pairing, with its evidence."""

    pod_parent: str
    pollen_parent: str
    tier: str
    headline: str
    reasoning: list = field(default_factory=list)
    precedents: list = field(default_factory=list)     # Registered crosses cited
    pod_genus: str = ""
    pollen_genus: str = ""
    cross_type: str = ""                                # interspecific | intergeneric
    expected_offspring: dict = field(default_factory=dict)
    suggestion: str = ""
    warnings: list = field(default_factory=list)

    health_used: bool = False

    # How each name was understood, so the app can show it rather than leaving
    # the grower to discover after the fact that the engine read "Catliya" as
    # a Vanda. Keys "pod" and "pollen", each: genus, genus_source
    # (stated|matched|assumed), recognised, did_you_mean.
    name_check: dict = field(default_factory=dict)

    @property
    def tier_label(self) -> str:
        return TIER_LABEL.get(self.tier, self.tier)

    @property
    def compatibility_class(self) -> str:
        """Two-class summary: Compatible / Low Compatibility / Not Advised."""
        return TIER_TO_CLASS.get(self.tier, "Low Compatibility")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tier_label"] = self.tier_label
        d["compatibility_class"] = self.compatibility_class
        return d


# ──────────────────────────────────────────────
# Knowledge base
# ──────────────────────────────────────────────
class KnowledgeBase:
    """The registry-derived facts this engine reasons over."""

    def __init__(self, knowledge_dir: str = KNOWLEDGE_DIR):
        self.crosses = self._load_csv(os.path.join(knowledge_dir, "registered_crosses.csv"))
        self.nothogenera = self._load_csv(os.path.join(knowledge_dir, "nothogenera.csv"))
        self.traits = {
            self._key(r["species"]): r
            for r in self._load_csv(os.path.join(knowledge_dir, "parent_traits.csv"))
        }

        # Genus pairs with at least one registered hybrid, DIRECTIONAL
        self.genus_pairs = set()
        # ...and undirected, since a nothogenus name implies the combination
        # works without recording which way round it was done
        self.genus_combos = set()

        for c in self.crosses:
            a, b = c.get("seed_genus", ""), c.get("pollen_genus", "")
            if a and b:
                self.genus_pairs.add((a, b))
                self.genus_combos.add(frozenset((a, b)))

        # What each nothogenus is a hybrid OF. Used to expand a hybrid genus
        # back into the natural genera it contains.
        self.nothogenus_parents = {}

        for n in self.nothogenera:
            genera = [g.strip() for g in n.get("parent_genera", "").split("|") if g.strip()]
            if n.get("nothogenus") and genera:
                self.nothogenus_parents[n["nothogenus"]] = set(genera)
            for i in range(len(genera)):
                for j in range(i + 1, len(genera)):
                    self.genus_combos.add(frozenset((genera[i], genera[j])))

        # Name -> genus, so a grex written without its genus prefix can still be
        # placed. Tags in the collection usually read "Kulwadee Maron", not
        # "Vanda Kulwadee Maron", and looking the bare name up is a fact where
        # assuming the collection's genus is only a guess.
        self.name_genus = {}
        for c in self.crosses:
            for side in ("seed", "pollen"):
                name, genus = c.get(f"{side}_parent"), c.get(f"{side}_genus")
                if name and genus:
                    self.name_genus.setdefault(self._key(name), genus)
            if c.get("grex"):
                g, _ = expand_genus(c["grex"])
                if g:
                    self.name_genus.setdefault(self._key(c["grex"]), g)
        for species in self.traits.values():
            g, _ = expand_genus(species.get("species", ""))
            if g:
                self.name_genus.setdefault(self._key(species["species"]), g)

    def constituent_genera(self, genus: str) -> set:
        """
        The natural genera a genus name stands for.

        A nothogenus is not an atomic genus - it is the recorded name for a
        cross between several. `Aeridovanda` IS `Aerides x Vanda`, so a plant
        called an Aeridovanda carries both. Treating the name as opaque makes
        the engine blind to the commonest thing a breeder actually does:
        crossing a hybrid back into one of its own parent genera.
        """
        return set(self.nothogenus_parents.get(genus, {genus}))

    def nothogenus_covering(self, genera: set) -> str:
        """
        The registered nothogenus whose parent genera are exactly this set.

        Matching is exact, not by subset: a nothogenus name is registered for
        one specific combination of genera, and a cross that brings in a genus
        outside that set produces a different (and here unregistered) one.
        """
        for name, parents in self.nothogenus_parents.items():
            if parents == genera:
                return name
        return ""

    def genus_for_name(self, name: str) -> str:
        """The genus recorded against this exact parent name, or ""."""
        return self.name_genus.get(self._key(name), "")

    def knows_name(self, name: str) -> bool:
        """True when this exact parent appears somewhere in the knowledge base."""
        return self._key(name) in self.name_genus

    @staticmethod
    def _load_csv(path: str) -> list:
        if not os.path.exists(path):
            print(f"[WARN] Knowledge file missing: {path}")
            return []
        with open(path, newline="", encoding="utf-8") as f:
            # '#' comment lines are documentation, not data
            lines = [ln for ln in f if not ln.lstrip().startswith("#")]
        return list(csv.DictReader(lines))

    @staticmethod
    def _key(name: str) -> str:
        """Comparison key: lowercase, punctuation-free, genus abbreviations expanded."""
        s = normalise_name(name).lower()
        s = s.replace(".", " ")
        parts = s.split()
        if parts and parts[0] in GENUS_ABBREV:
            parts[0] = GENUS_ABBREV[parts[0]].lower()
        return " ".join(parts).strip()

    def find_exact(self, pod: str, pollen: str) -> list:
        """Registered crosses matching this pairing in this direction."""
        pk, lk = self._key(pod), self._key(pollen)
        return [c for c in self.crosses
                if self._key(c["seed_parent"]) == pk
                and self._key(c["pollen_parent"]) == lk]

    def find_reversed(self, pod: str, pollen: str) -> list:
        """Registered crosses matching this pairing the OTHER way round."""
        return self.find_exact(pollen, pod)

    def find_involving(self, parent: str) -> list:
        """Every registered cross this parent appears in, either side."""
        k = self._key(parent)
        return [c for c in self.crosses
                if self._key(c["seed_parent"]) == k or self._key(c["pollen_parent"]) == k]

    def genus_precedents(self, genus_a: str, genus_b: str) -> list:
        """Registered crosses joining these two genera, either direction."""
        combo = frozenset((genus_a, genus_b))
        return [c for c in self.crosses
                if frozenset((c.get("seed_genus", ""), c.get("pollen_genus", ""))) == combo]

    def nothogenus_for(self, genus_a: str, genus_b: str) -> str:
        """The registered hybrid genus name for this combination, if any."""
        for n in self.nothogenera:
            genera = {g.strip() for g in n.get("parent_genera", "").split("|")}
            if {genus_a, genus_b} <= genera:
                return n["nothogenus"]
        return ""

    def traits_for(self, parent: str) -> dict:
        return self.traits.get(self._key(parent), {})


# ──────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────
class CompatibilityEngine:
    """Assesses a directional pairing against the registry knowledge base."""

    def __init__(self, kb: KnowledgeBase = None):
        self.kb = kb or KnowledgeBase()

    def assess(
        self,
        pod_parent: str,
        pollen_parent: str,
        pod_health: dict = None,
        pollen_health: dict = None,
    ) -> CompatibilityResult:
        """
        Assess crossing pod_parent (seed) with pollen_parent (pollen donor).

        Args:
            pod_parent:    Name of the plant that will carry the seed pod
            pollen_parent: Name of the pollen donor
            pod_health:    Optional Level 1 result for the pod parent,
                           e.g. {"suitability": "Suitable", "confidence": 0.8}
            pollen_health: Optional Level 1 result for the pollen parent

        Returns:
            CompatibilityResult. Order is meaningful and never sorted.
        """
        # How the two names were understood. This used to be one line -
        #   pod_genus = parse_cross(pod)["genus"] or "Vanda"
        # - and that "or Vanda" was wrong in a way nothing downstream could
        # detect. A name the parser could not place became a Vanda, so
        # "Catliya x Aeridovanda Frank Johnston" was reported as the
        # established Vanda x Aeridovanda combination: a confident verdict on
        # a plant the grower never named.
        pod_name = self._resolve_name(pod_parent, default_genus="Vanda")
        pollen_name = self._resolve_name(pollen_parent,
                                         default_genus=pod_name["genus"])

        pod_genus = pod_name["genus"]
        pollen_genus = pollen_name["genus"]

        result = CompatibilityResult(
            pod_parent=normalise_name(pod_parent),
            pollen_parent=normalise_name(pollen_parent),
            tier=TIER_UNDEMONSTRATED,
            headline="",
            pod_genus=pod_genus,
            pollen_genus=pollen_genus,
            cross_type="interspecific" if pod_genus == pollen_genus else "intergeneric",
            health_used=bool(pod_health or pollen_health),
            name_check={"pod": pod_name, "pollen": pollen_name},
        )

        self._warn_about_names(result, pod_name, pollen_name)

        # ── Health gate ───────────────────────
        # Stated as a rule from the breeder interview and horticultural
        # literature, NOT as something this project measured. A diseased or
        # weak parent is not worth the nine months a pod takes to mature.
        blocked_by = self._health_block(pod_health, pollen_health, result)
        if blocked_by:
            result.tier = TIER_BLOCKED
            result.headline = f"Not advised - {blocked_by}"
            result.suggestion = (
                "Treat and recover the plant, then re-assess. A Vanda seed pod "
                "takes about nine months to mature, so a weak parent is an "
                "expensive gamble."
            )
            return result

        # ── Name gate ─────────────────────────
        # A genus the engine had to GUESS cannot support a verdict.
        #
        # Measured failure: "Banana" x "Table" returned "Compatible - Vanda x
        # Vanda, the standard, most reliable cross" with five precedents. Both
        # names were unrecognised, both were assumed to be Vanda because that
        # is the collection's genus, and the assumption then flowed into a
        # confident answer. `_warn_about_names` already recorded the guess in
        # `warnings`, but a warning beside a green verdict is not a refusal.
        #
        # Everything downstream - the register lookup, the alliance rules, the
        # precedents - is reasoning about GENERA. If the genus is a guess, the
        # reasoning has nothing underneath it, so the honest answer is that the
        # cross cannot be judged rather than that it is fine.
        guessed = [lbl for lbl, info in (("pod", pod_name), ("pollen", pollen_name))
                   if info["genus_source"] == "assumed"]
        if guessed:
            which = " and ".join("%s parent" % g for g in guessed)
            result.tier = TIER_UNKNOWN_NAME
            result.headline = (
                "Cannot check this cross - the %s %s not recognised"
                % (which, "names are" if len(guessed) > 1 else "name is")
            )
            result.suggestion = (
                "Write the genus at the front of the name, for example "
                "\"V. Fuch Sunset\" or \"Aerides leeana\". Without a genus the "
                "system has nothing to look up, and it will not guess one."
            )
            return result

        # ── Evidence search ───────────────────
        exact = self.kb.find_exact(result.pod_parent, result.pollen_parent)
        reverse = self.kb.find_reversed(result.pod_parent, result.pollen_parent)

        if exact:
            result.tier = TIER_REGISTERED
            grex = exact[0].get("grex", "")
            result.headline = f"This exact cross is registered as {grex}"
            result.precedents = exact
            result.reasoning.append(
                f"Found {len(exact)} registered cross(es) with this pod and pollen "
                f"parent in this direction."
            )
        elif reverse:
            result.tier = TIER_REGISTERED
            grex = reverse[0].get("grex", "")
            result.headline = f"Registered in the opposite direction as {grex}"
            result.precedents = reverse
            result.reasoning.append(
                f"The register has {normalise_name(reverse[0]['seed_parent'])} x "
                f"{normalise_name(reverse[0]['pollen_parent'])} - the same parents "
                "with the roles swapped."
            )
            result.warnings.append(
                "Direction is not interchangeable. A pairing registered one way "
                "round is evidence the parents are compatible, but the reciprocal "
                "cross can still fail."
            )
        else:
            genus_precedents = self.kb.genus_precedents(pod_genus, pollen_genus)
            combo_known = frozenset((pod_genus, pollen_genus)) in self.kb.genus_combos

            # Expand both sides into the natural genera they contain, and ask
            # whether a registered nothogenus already names that combination.
            #
            # Without this the engine could not see a BACKCROSS. Aeridovanda
            # is Aerides x Vanda, so Aerides x Aeridovanda brings in no genus
            # the Aeridovanda name does not already record - yet it came back
            # "no registered precedent", while Aeridovanda x V. tessellata in
            # the same knowledge base is a registered cross. The engine was
            # contradicting its own data because it read a nothogenus as an
            # atomic genus unrelated to its parents.
            pod_set = self.kb.constituent_genera(pod_genus)
            pollen_set = self.kb.constituent_genera(pollen_genus)
            combined = pod_set | pollen_set
            notho_cover = self.kb.nothogenus_covering(combined)
            is_backcross = bool(notho_cover) and (
                pod_set != pollen_set and (pod_set <= pollen_set or pollen_set <= pod_set)
            )

            if genus_precedents or combo_known or notho_cover:
                result.tier = TIER_GENUS_PROVEN
                result.precedents = genus_precedents[:5]

                notho = self.kb.nothogenus_for(pod_genus, pollen_genus) or notho_cover
                if pod_genus == pollen_genus:
                    # Named as a GENUS check. The engine reads only the
                    # genus from each name, so two different Vanda varieties
                    # give an identical answer - and a headline naming the
                    # varieties implied an assessment of them that never
                    # happened.
                    result.headline = (
                        f"{pod_genus} x {pod_genus} - a standard genus pairing"
                    )
                    result.reasoning.append(
                        "Same-genus crosses are routine practice. The Peradeniya "
                        "breeder reports Vanda x Vanda as the most successful type."
                    )
                elif is_backcross:
                    # One parent already contains the other's genus, so this
                    # adds nothing new - the offspring stay inside the same
                    # registered nothogenus. Worth saying plainly: a breeder
                    # reads "intergeneric" as "long odds", and this is the one
                    # kind of intergeneric cross that is not.
                    hybrid, parent = (
                        (pod_genus, pollen_genus) if pollen_set <= pod_set
                        else (pollen_genus, pod_genus)
                    )
                    result.headline = (
                        f"{pod_genus} x {pollen_genus} stays within {notho_cover}"
                    )
                    result.reasoning.append(
                        f"{hybrid} is itself a hybrid of "
                        + " and ".join(sorted(self.kb.constituent_genera(hybrid)))
                        + f", so crossing it with {parent} introduces no genus it does "
                        f"not already carry. The offspring are still {notho_cover}."
                    )
                    result.reasoning.append(
                        f"This is a backcross into a parent genus, not a new "
                        f"intergeneric combination. The {notho_cover} name is "
                        f"registered, which means this genus combination has been "
                        f"made successfully."
                    )
                    result.warnings.append(
                        "No registered cross with these two exact parents was found, "
                        "so the evidence here is at genus level. The register records "
                        "only successes and cannot say how often an attempt fails."
                    )
                else:
                    result.headline = (
                        f"{pod_genus} x {pollen_genus} is an established combination"
                        + (f" (registered as {notho})" if notho else "")
                    )
                    result.reasoning.append(
                        f"A registered hybrid genus exists for this combination"
                        + (f" - {notho}" if notho else "")
                        + ", which means the cross has been made successfully at least once."
                    )
                    result.warnings.append(
                        "Intergeneric cross. The register proves it is possible, but "
                        "it cannot show how often attempts fail - and the Peradeniya "
                        "breeder reports that most intergeneric attempts do not take."
                    )

                if genus_precedents:
                    result.reasoning.append(
                        f"{len(genus_precedents)} registered cross(es) join these two genera."
                    )
            else:
                result.tier = TIER_UNDEMONSTRATED
                pod_alliance = genus_alliance(pod_genus)
                pollen_alliance = genus_alliance(pollen_genus)

                # Two recognised genera from different alliances is a stronger
                # statement than "nothing found". Orchid hybrids are made
                # within an alliance; Vanda x Cattleya is not an unexplored
                # pairing, it is a wall. Saying "no precedent" there reads as a
                # gap in a small knowledge base and invites the grower to try.
                if (pod_alliance and pollen_alliance
                        and pod_alliance != pollen_alliance):
                    result.headline = (
                        f"{pod_genus} and {pollen_genus} are in different "
                        "orchid alliances - this cross is not viable"
                    )
                    result.reasoning.append(
                        f"{pod_genus} belongs to the {pod_alliance} alliance and "
                        f"{pollen_genus} to the {pollen_alliance} alliance. Orchid "
                        "hybrids are made within an alliance; no registered "
                        "hybrid joins these two."
                    )
                    result.warnings.append(
                        "This is not a gap in the knowledge base. The two genera "
                        "are too distantly related to produce a viable capsule, "
                        "so there is nothing to attempt here."
                    )
                else:
                    result.headline = (
                        f"No registered precedent for {pod_genus} x {pollen_genus}"
                    )
                    result.reasoning.append(
                        "No hybrid joining these genera was found in the knowledge "
                        "base. This is weak evidence against, not proof of "
                        "impossibility - the knowledge base is a small extract, not "
                        "the full register."
                    )
                    result.warnings.append(
                        "Absence from the register is not the same as a recorded "
                        "failure. Check the full RHS register before concluding."
                    )

        # ── Offspring expectation ─────────────
        result.expected_offspring = self._expected_offspring(
            result.pod_parent, result.pollen_parent
        )

        # ── Fallback advice ───────────────────
        result.suggestion = self._suggestion(result)

        return result

    # ── Helpers ───────────────────────────────
    def _resolve_name(self, name: str, default_genus: str) -> dict:
        """
        Work out which genus a typed name belongs to, and say how confident
        that is.

        Three routes, in descending order of trust:

          stated   the name carries its genus - "V. tessellata", "Cattleya
                   Bowringiana". Nothing is being inferred.
          matched  the name has no genus prefix but IS in the knowledge base,
                   which records one - "Kulwadee Maron" is a Vanda because the
                   register says so, not because we guessed.
          assumed  neither. The collection is Vandaceous so the genus of the
                   other parent (or Vanda) is the best available guess - but it
                   IS a guess, and the caller must be told.

        The third case is the one that produced the Catliya bug. It still
        returns a genus, because refusing to assess every unlisted hybrid name
        would make the screen useless, but it now returns it labelled.
        """
        clean = normalise_name(name)
        parsed = parse_cross(clean)

        out = {
            "name": clean,
            "genus": "",
            "genus_source": "",
            "recognised": self.kb.knows_name(clean),
            "did_you_mean": "",
        }

        if parsed["genus"]:
            out["genus"] = parsed["genus"]
            out["genus_source"] = "stated"
            return out

        recorded = self.kb.genus_for_name(clean)
        if recorded:
            out["genus"] = recorded
            out["genus_source"] = "matched"
            return out

        out["genus"] = default_genus
        out["genus_source"] = "assumed"

        # A near-miss on the first word is worth offering: a grower copying a
        # hand-written tag types Catliya far more often than they invent a new
        # grex whose first word happens to be two edits from a genus name.
        first = clean.split()[0] if clean.split() else ""
        hint = suggest_genus(first)
        if hint and hint != default_genus:
            out["did_you_mean"] = hint

        return out

    @staticmethod
    def _warn_about_names(result, pod_name: dict, pollen_name: dict) -> None:
        """
        Surface any name the engine had to guess at.

        These go in first so they sit above the evidence warnings: if the
        genus was guessed, everything after it is conditional on that guess.
        """
        for label, info in (("pod parent", pod_name), ("pollen parent", pollen_name)):
            if info["genus_source"] != "assumed":
                continue

            if info["did_you_mean"]:
                meant = info["did_you_mean"]
                message = (
                    f"The {label} \"{info['name']}\" is not a name this system "
                    f"recognises. Did you mean {meant}? It has been read as a "
                    f"{info['genus']} for this check."
                )
                if genus_alliance(meant) != VANDA_ALLIANCE:
                    message += (
                        f" If you did mean {meant}, the verdict below does not "
                        f"apply - {meant} is in a different alliance and cannot "
                        f"be crossed with this collection at all."
                    )
                result.warnings.append(message)
            else:
                result.warnings.append(
                    f"The {label} \"{info['name']}\" carries no genus and is not "
                    f"in the knowledge base. It has been read as a "
                    f"{info['genus']}, which is the collection's genus - write "
                    f"the genus on the name (for example \"V. {info['name']}\") "
                    f"if that is wrong."
                )

    def _health_block(self, pod_health, pollen_health, result) -> str:
        """
        Return a reason string if either parent's condition rules out the cross.

        A Moderate verdict means different things in the two roles, so the two
        roles get different advice. The pod parent carries the capsule for
        around nine months and a compromised plant should not be asked to; the
        pollen parent only has to donate pollinia, so Moderate is acceptable
        there and saying otherwise would be noise.

        Until the application began sending pollen_health this loop only ever
        ran on the pod side, and the single shared message told a Moderate
        pollen parent to "consider using it as the pollen donor" - which it
        already was.
        """
        blockers = []

        for role, health in (("pod", pod_health), ("pollen", pollen_health)):
            if not health:
                continue

            label = "pod parent" if role == "pod" else "pollen parent"
            suitability = str(health.get("suitability", "")).strip().lower()

            if suitability == "not suitable":
                blockers.append(f"the {label} was assessed Not Suitable")

            elif suitability == "moderate" and role == "pod":
                result.warnings.append(
                    "The pod parent was assessed only Moderate. The cross can "
                    "proceed, but consider reversing it and using this plant as "
                    "the pollen donor instead: carrying a capsule for nine months "
                    "costs the plant far more than donating pollinia."
                )

            elif suitability == "moderate" and role == "pollen":
                result.warnings.append(
                    "The pollen parent was assessed only Moderate. That is "
                    "acceptable in this role - a pollen donor needs viable "
                    "pollinia rather than the vigour to carry a capsule - so the "
                    "cross is not blocked on that account."
                )

        return " and ".join(blockers)

    def _expected_offspring(self, pod: str, pollen: str) -> dict:
        """
        Predict offspring traits from the two parents' documented contributions.

        Only fires where both parents are known species in the traits table.
        Named hybrids are not covered - their trait contributions would have to
        be measured from photographs, which is the trait-inheritance work still
        outstanding.
        """
        a = self.kb.traits_for(pod)
        b = self.kb.traits_for(pollen)

        if not a and not b:
            return {
                "known": False,
                "note": "Neither parent is a documented species; offspring traits "
                        "cannot be predicted from the knowledge base yet.",
            }

        out = {"known": True}
        size_rank = {"small": 0, "medium": 1, "large": 2}
        inverse = {0: "small", 1: "medium", 2: "large"}

        sizes = [size_rank.get(p.get("flower_size", ""), None) for p in (a, b) if p]
        sizes = [s for s in sizes if s is not None]
        if sizes:
            # Offspring flower size tends toward the mean of the parents, which
            # is why crossing into small-flowered tessellata reduces size.
            out["flower_size"] = inverse[round(sum(sizes) / len(sizes))]

        colours = [p.get("dominant_colour") for p in (a, b) if p and p.get("dominant_colour")]
        if colours:
            out["colour_influences"] = colours

        if any(p.get("fragrance") == "high" for p in (a, b) if p):
            out["fragrance"] = "possible - at least one parent is strongly fragrant"

        patterns = [p.get("pattern") for p in (a, b) if p and p.get("pattern")]
        if patterns:
            out["pattern_influences"] = patterns

        out["caveat"] = (
            "Horticultural priors from parent species records, not a trained "
            "model. Real offspring vary widely within a grex."
        )
        return out

    def _suggestion(self, result: CompatibilityResult) -> str:
        """Actionable next step, including the breeder's tessellata fallback."""
        if result.tier == TIER_REGISTERED:
            return (
                "Proceed. Record the cross as "
                f"{result.pod_parent} x {result.pollen_parent} (pod parent first) "
                "and expect roughly nine months to pod maturity."
            )

        if result.tier == TIER_GENUS_PROVEN and result.cross_type == "interspecific":
            return (
                "Proceed. This is the standard cross type. Label the pollinated "
                "flower with both parents and the date."
            )

        # Intergeneric or undemonstrated: offer the documented rescue route
        return (
            f"Attempt it, but have a fallback. The Peradeniya breeder reports that "
            f"when an imported hybrid x hybrid cross yields no pod, crossing into "
            f"{RESCUE_PARENT} (the native Sri Lankan species) does take - at the cost "
            f"of a smaller flower, since the offspring inherit its characters. "
            f"If no pod has set after this attempt, try {result.pod_parent} x {RESCUE_PARENT}."
        )

    # ── Ranking ───────────────────────────────
    def rank_partners(self, pod_parent: str, candidates: list,
                      pod_health: dict = None) -> list:
        """
        Rank candidate pollen donors for one pod parent, best evidence first.

        This is the screen a breeder actually wants: "I have this plant in
        flower - which of my other plants should I put on it?"
        """
        results = [self.assess(pod_parent, c, pod_health=pod_health) for c in candidates]
        return sorted(
            results,
            key=lambda r: (TIER_ORDER.index(r.tier), len(r.precedents)),
            reverse=True,
        )


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Assess a Parent A x Parent B cross")
    parser.add_argument("--pod", help="Pod (seed) parent - written first")
    parser.add_argument("--pollen", help="Pollen parent")
    args = parser.parse_args()

    engine = CompatibilityEngine()

    if args.pod and args.pollen:
        pairs = [(args.pod, args.pollen)]
    else:
        pairs = [
            ("V. coerulea", "V. sanderiana"),        # registered
            ("V. sanderiana", "V. coerulea"),        # registered, reversed
            ("V. tessellata", "Aerides lawrenceae"),  # registered intergeneric
            ("V. tessellata", "V. coerulea"),        # genus proven
            ("V. Kulwadee Maron", "V. Pachara Delight"),  # unregistered hybrids
            ("V. coerulea", "Phalaenopsis amabilis"),      # undemonstrated
        ]

    for pod, pollen in pairs:
        r = engine.assess(pod, pollen)
        print("\n" + "=" * 70)
        print(f"{r.pod_parent}  x  {r.pollen_parent}")
        print(f"   (pod parent)      (pollen parent)")
        print("=" * 70)
        print(f"  Tier      : {r.tier_label}  [{r.cross_type}]")
        print(f"  Verdict   : {r.headline}")
        for reason in r.reasoning:
            print(f"    - {reason}")
        if r.precedents:
            print(f"  Precedents:")
            for p in r.precedents[:3]:
                print(f"    - {p['seed_parent']} x {p['pollen_parent']} = {p['grex']} "
                      f"({p.get('year') or 'year n/a'})")
        if r.expected_offspring.get("known"):
            eo = r.expected_offspring
            bits = []
            if "flower_size" in eo:
                bits.append(f"size {eo['flower_size']}")
            if "colour_influences" in eo:
                bits.append("colour from " + " + ".join(eo["colour_influences"]))
            if "fragrance" in eo:
                bits.append("fragrance possible")
            print(f"  Offspring : {'; '.join(bits)}")
        for w in r.warnings:
            print(f"  ! {w}")
        print(f"  Next      : {r.suggestion}")
