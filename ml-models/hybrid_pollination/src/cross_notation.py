"""
Hybrid Pollination - Orchid Cross Notation Parser

Parses orchid names as breeders and tags actually write them.

The convention that matters (Peradeniya breeder interview):

    The POD (seed) parent is written FIRST, then the POLLEN parent.

So `A x B` and `B x A` are different attempts, and compatibility is asymmetric.
The parser preserves that order; nothing downstream may sort the pair.

Handles the forms seen on real tags and in the garden's purchase register:

    V. Gordon Dillon x Dr Anek Blitz
    Vanda Kulwadee Maron                       (grex name, no parentage shown)
    V. #467 (Wirat Pink x Blitz) x Kulwadee Fragrance
    Vanda #449 x Renu Gold x Somsri Velvet
    V. coerulea x V. sanderiana
    Aeridovanda Frank Johnston

Note the genuine ambiguity in `A x B x C`: it may be a three-way lineage
written loosely, or a two-step cross. The parser reports what it sees and flags
the ambiguity rather than silently guessing.
"""

import re


# ──────────────────────────────────────────────
# Genus vocabulary
# ──────────────────────────────────────────────
# Abbreviations seen on tags, mapped to the full genus name.
GENUS_ABBREV = {
    "v": "Vanda",
    "van": "Vanda",
    "vanda": "Vanda",
    "asctm": "Ascocentrum",
    "ascocentrum": "Ascocentrum",
    "ascda": "Ascocenda",
    "ascocenda": "Ascocenda",
    "aer": "Aerides",
    "aerides": "Aerides",
    "arach": "Arachnis",
    "arachnis": "Arachnis",
    "ren": "Renanthera",
    "renanthera": "Renanthera",
    "rhy": "Rhynchostylis",
    "rhynchostylis": "Rhynchostylis",
    "phal": "Phalaenopsis",
    "phalaenopsis": "Phalaenopsis",
    "papilionanthe": "Papilionanthe",
    "pda": "Papilionanthe",
    "luisia": "Luisia",
    "vandopsis": "Vandopsis",
    "trichoglottis": "Trichoglottis",
    "sarcochilus": "Sarcochilus",
    "paraphalaenopsis": "Paraphalaenopsis",
    # Nothogenera (intergeneric hybrid genus names)
    "aranda": "Aranda",
    "mokara": "Mokara",
    "renantanda": "Renantanda",
    "kagawara": "Kagawara",
    "aeridovanda": "Aeridovanda",
    "papilionanda": "Papilionanda",
    "luisanda": "Luisanda",
    "paravanda": "Paravanda",
    "renanopsis": "Renanopsis",
    "renvanvanda": "Renvanvanda",
    "taprobanea": "Taprobanea",
}

# Multiplication sign in any of the ways a tag or keyboard may produce it
CROSS_SEPARATOR = re.compile(r"\s+(?:[x×✕✖X])\s+")


def normalise_name(name: str) -> str:
    """
    Tidy a raw tag string without changing its meaning.

    Filesystem-safe substitutions are undone, spacing is collapsed, and the
    stray punctuation that folder names accumulate is trimmed.
    """
    s = str(name).strip()
    s = s.replace("×", "x").replace("✕", "x").replace("✖", "x")
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" .,-")
    return s


# Ploidy markers written on nursery tags: 2n diploid, 3n triploid, 4n tetraploid.
# Worth extracting - a triploid is usually sterile, and a 4n x 2n cross tends to
# give sterile triploid offspring, so ploidy is a real compatibility signal.
PLOIDY_RE = re.compile(r"\b([234])\s*n\b", re.IGNORECASE)

# Clone / selection numbers: "#77", "#463". Identify an individual plant within
# a grex; they are not part of the parent's identity.
CLONE_RE = re.compile(r"#\s*\d+")

# A genus prefix, tolerating every spacing seen on real tags:
#   "V. Name"  "V.Name"  "V .Name"  "V . Name"  "Vanda Name"  "V(marue) Name"
GENUS_PREFIX_RE = re.compile(
    r"^([A-Za-z]+)\s*(?:\([^)]*\))?\s*(?:\.\s*|\s+)(.*)$"
)


def expand_genus(token: str) -> tuple:
    """
    Split a leading genus abbreviation off a name.

    Applied repeatedly, because tags sometimes stack prefixes -
    `V. Ascda.Kultana pappion` carries both a genus and a nothogenus.

    Returns:
        (genus or "", remainder). Genus is "" when the name carries no
        recognisable genus prefix, which is normal for the second half of a
        cross - `V. Gordon Dillon x Dr Anek` names no genus for the pollen
        parent, and it is understood to be the same genus.
    """
    token = token.strip()
    genus = ""

    while True:
        m = GENUS_PREFIX_RE.match(token)
        if not m:
            break

        head, rest = m.group(1).lower(), m.group(2).strip()
        if head not in GENUS_ABBREV or not rest:
            break

        # First prefix wins; later ones are refinements of the same plant
        genus = genus or GENUS_ABBREV[head]
        token = rest

    return genus, token


def extract_ploidy(name: str) -> tuple:
    """
    Pull a ploidy marker out of a name.

    Returns:
        (ploidy or "", name without the marker)
    """
    m = PLOIDY_RE.search(name)
    if not m:
        return "", name
    return f"{m.group(1)}n", PLOIDY_RE.sub("", name).strip()


def parent_key(name: str) -> str:
    """
    Canonical identity for a parent, so that the same plant written different
    ways collapses to one entry.

    `V. Dr Anek`, `Dr Anek` and `dr anek` are the same parent. Without this the
    inventory reports a parent appearing once per spelling, and the collection
    looks far thinner than it is.

    Genus, ploidy, clone number, punctuation and case are all removed, because
    none of them change WHICH plant is being named.
    """
    s = normalise_name(name).lower()
    s = CLONE_RE.sub(" ", s)
    _, s = extract_ploidy(s)

    _, s = expand_genus(s)

    s = re.sub(r"[^\w\s]", " ", s)      # drop apostrophes, dots, parentheses
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_cross(name: str) -> dict:
    """
    Parse an orchid tag string.

    Returns a dict with:
        raw         - the input, unchanged
        normalised  - cleaned string
        genus       - leading genus, or "" if none recognised
        parents     - [seed_parent, pollen_parent, ...] in WRITTEN ORDER,
                      empty when the tag shows only a grex name
        grex        - the grex name when no parentage is shown
        ambiguous   - True when 3+ parts were found, so the lineage is unclear
        note        - explanation when something needed interpretation
    """
    raw = str(name)
    s = normalise_name(raw)

    result = {
        "raw": raw, "normalised": s, "genus": "", "parents": [],
        "parent_keys": [], "ploidy": "", "grex": "",
        "ambiguous": False, "unreadable": False, "note": "",
    }

    if not s:
        result["unreadable"] = True
        result["note"] = "Empty tag"
        return result

    # A tag may be half-readable: "UNKNOWN_1 X Dr Anek" still names one parent,
    # so it is parsed rather than discarded.
    if s.upper().startswith("UNKNOWN"):
        result["unreadable"] = True
        result["note"] = "One or both parents not recorded"
        if not CROSS_SEPARATOR.search(s):
            return result

    result["ploidy"], s = extract_ploidy(s)

    # Pull the genus off the front before splitting, so that "V. A x B" does not
    # lose its genus to the first parent only
    genus, remainder = expand_genus(s)
    result["genus"] = genus

    # A parenthesised group is a sub-cross: `#467 (Wirat Pink x Blitz) x Kulwadee`
    # Protect it so the inner ' x ' is not split on.
    protected, groups = _protect_parens(remainder)

    parts = [p.strip() for p in CROSS_SEPARATOR.split(protected) if p.strip()]
    parts = [_restore_parens(p, groups) for p in parts]

    if len(parts) <= 1:
        # No separator - this is a grex name, not a written parentage
        result["grex"] = remainder
        result["grex_key"] = parent_key(remainder)
        if not result["note"]:
            result["note"] = "Grex name only; parentage not shown on the tag"
        return result

    result["parents"] = parts
    result["parent_keys"] = [
        "" if p.upper().startswith("UNKNOWN") else parent_key(p) for p in parts
    ]

    if len(parts) > 2:
        result["ambiguous"] = True
        result["note"] = (
            f"{len(parts)} parts found. Ambiguous: may be a multi-step lineage "
            "written loosely, or a grex whose name contains 'x'. "
            "First part treated as the pod parent."
        )

    return result


def _protect_parens(s: str) -> tuple:
    """Replace parenthesised groups with placeholders so they are not split."""
    groups = []

    def swap(m):
        groups.append(m.group(0))
        return f"@@{len(groups) - 1}@@"

    return re.sub(r"\([^()]*\)", swap, s), groups


def _restore_parens(s: str, groups: list) -> str:
    """Put parenthesised groups back."""
    for i, g in enumerate(groups):
        s = s.replace(f"@@{i}@@", g)
    return s


def parent_genus(parent: str, default_genus: str = "") -> str:
    """
    Best-effort genus for one parent name.

    Falls back to default_genus, because the pollen parent on a tag usually
    omits the genus when it matches the pod parent.
    """
    genus, _ = expand_genus(parent)
    return genus or default_genus


def format_cross(seed: str, pollen: str) -> str:
    """Render a cross in the conventional pod-first order."""
    return f"{seed} × {pollen}"


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    samples = [
        "V. Gordon Dillon x Dr Anek Blitz",
        "Vanda Kulwadee Maron",
        "V. #467 (Wirat Pink x Blitz) x Kulwadee Fragrance",
        "Vanda #449 x Renu Gold x Somsri Velvet",
        "V. coerulea x V. sanderiana",
        "Aeridovanda Frank Johnston",
        "V. 416 Thonglor x Taweesuksa",
        "Vanda Twotone Blue",
        "UNKNOWN_1",
    ]

    print(f"{'input':<52} {'genus':<12} parents")
    print("-" * 100)
    for s in samples:
        r = parse_cross(s)
        parents = " | ".join(r["parents"]) if r["parents"] else f"(grex: {r['grex']})"
        flag = "  <AMBIGUOUS>" if r["ambiguous"] else ""
        print(f"{s:<52} {r['genus'] or '-':<12} {parents}{flag}")
        if r["note"]:
            print(f"{'':<52} {'':<12} note: {r['note']}")
