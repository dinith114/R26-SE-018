# Domain Knowledge: Vanda Breeding Practice

**Source:** Expert interview, Royal Botanic Gardens, Peradeniya
**Collected by:** IT22065230 – Wickramasinghe D.P
**Component:** 4 – Hybrid Pollination & Compatibility Analysis
**Recorded:** 27 August 2026

This is primary-source domain knowledge from a practising orchid breeder. It is
the basis of the Parent A × Parent B compatibility rules and should be cited as
such in the thesis.

---

## 1. Species vs hybrids in Sri Lankan Vanda cultivation

- **V. tessellata** is the native Sri Lankan Vanda species.
- The garden holds **only that one species**. Everything else is a **hybrid**
  (a "cross"). *"We don't make species."*
- **V. sanderiana** was named as an example of a species (not held locally).
- Practice is therefore **hybrid × hybrid**, not species × species.

**Design consequence.** The parent identity space is *registered hybrid names*,
not a species list. The `species` column in the current dataset — `"Vanda"` on
100% of rows — carries no information and must be replaced by grex/cross name.

---

## 2. Cross compatibility (the core rule base)

Reported reliability, most to least successful:

| Cross type | Outcome |
|---|---|
| **Vanda × Vanda** | Most successful. Standard practice. |
| **Intergeneric** (Vanda × another Sarcanthinae genus) | Possible, but *"most intergeneric crosses don't work"* |
| Outside subtribe Sarcanthinae | Not attempted |

**Intergeneric partners** come from subtribe **Sarcanthinae**, section (xiv) of
the orchid family chart (Monandrae → Vandeae). Genera listed on that chart:

> Aerantitis, Aerides, Angraecum, Arachnis, Camarotis, Esmeralda, Euanthe,
> Luisia, Phalaenopsis, Renanthera, Rhynchostylis, Saccolabium, Sarcanthus,
> Sarcochilus, Stauropsis, Trichoglottis, **Vanda**, Vandopsis

Defining character of the group: *growth monopodial, the main stem continuing
its growth from year to year; flowers always lateral.*

### The tessellata rescue rule

Reported first-hand, and the single most useful compatibility fact obtained:

> Mother plants imported from Thailand are crossed, and **no seed pods form,
> whatever they do**. What they then do is cross into **V. tessellata**, which
> works — but the offspring takes on tessellata's characters, giving a
> **smaller flower**, not a large one.

Two separate findings in one:

1. **Cross failure is common and real** — a plant can be healthy and in bloom
   and still produce no pod with a given partner. Compatibility is a property
   of the *pair*, not of either plant alone. This is the justification for the
   whole component.
2. **V. tessellata acts as a broad-compatibility fallback parent**, at a known
   cost to flower size.

---

## 3. Parent selection criteria

What the breeder actually looks at when choosing parents, in their stated order
of importance:

| Criterion | Note |
|---|---|
| **Colour** | *"Mostly we check colours for the choosing"* — the dominant factor |
| **Flower spike** | More flowers on a spike is better |
| **Flower longevity** | How long the bloom lasts |
| **Petal thickness** | Thicker petal → flower keeps longer. Thin → shorter life. |

Note that **none of these are plant-health traits.** They are *flower quality*
traits of the parent, used to predict the quality of the offspring. This is a
different question from the current model's "is this plant healthy enough to
pollinate".

---

## 4. Breeding process and timing

- **Seed pod maturity in Vanda: ~9 months** after pollination.
- After maturing, the pod goes to the **laboratory** (flasking / in-vitro
  germination).

**Design consequence.** Outcome data has a ~9-month feedback loop. No
success/failure label can be generated inside this project's timeline; any
outcome data must come from existing records.

---

## 5. Naming convention (cross direction matters)

> When writing a cross, the **pod parent is written first**, then the
> **pollen parent**.

So `A × B` means A is the pod (seed) parent and B is the pollen donor.

**Design consequence.** Compatibility is **asymmetric**: `A × B` is not the same
attempt as `B × A`. The data model and any prediction must carry direction, and
the app must ask which plant is the pod parent.

---

## 6. Vanda growth forms

Three forms were distinguished:

| Form | Leaf | Note |
|---|---|---|
| **Terete** | Pencil-like, round in cross-section | — |
| **Semi-terete** | Intermediate | **Must be stressed to induce flowering** |
| **Strap-leaf** | Flat, broad, strap-shaped | The common nursery form |

**Design consequence.** This is a *visually determinable* class — leaf
cross-section shape is a shape/aspect-ratio problem, unlike petal thickness.
It is a realistic image-derived feature and is botanically meaningful.

Taxonomic caveat worth stating in the thesis: many terete "Vandas" have been
reclassified into **Papilionanthe**. Horticultural registration (RHS) and
current botanical taxonomy disagree here, so the rule base must state which
naming authority it follows.

---

## 7. Reference example

**Vanda Miss Joaquim** — national flower of Singapore — is
*V. hookeriana × V. teres*. (Both parents are terete; under current taxonomy
the grex is *Papilionanthe* Miss Joaquim.) Useful as a documented, verifiable
worked example of a named cross with known parentage.

---

## 8. Acquisition record — imported Thai hybrids

From the garden's purchase register, dated **2026.07.07**, "Orchid Plants
Purchase for Orchid Show house":

- Dendrobium plants with buds — 52 (Rs. 1000 each)
- **Vanda with flowers — 15 (Rs. 3000 each)**

The 15 Vanda plants, 12 distinct hybrids:

| # | Hybrid | Qty |
|---|---|---|
| 1 | Vanda Kulwadee Maron | 2 |
| 2 | Vanda Red #77 | 1 |
| 3 | Vanda #449 × Renu Gold × Somsri Velvet | 1 |
| 4 | Vanda Twotone Blue | 1 |
| 5 | V. #467 (Wirat Pink × Blitz) × Kulwadee Fragrance | 2 |
| 6 | Vanda Pachara Delight | 1 |
| 7 | Vanda Noppadol Delight | 1 |
| 8 | V. Gordon Dillon × Dr. Anek Blitz | 1 |
| 9 | V. Chaopraya × Kulvadee #10 | 1 |
| 10 | V. Tung Tung × Diamond Blue | 2 |
| 11 | V. Suvannabhumi Butterfly | 1 |
| 12 | V. 416 Thonglor × Taweesuksa | 1 |

**Important:** these are **not the garden's crosses**. They are pre-existing
Thai hybrids acquired to be used as **mother plants** for further crossing.

---

## 9. Critical limitation of tagged-plant photographs

Photographs of plants with their name tags give **parentage**, not **outcome**.

Every tagged plant in a collection is, by definition, a cross that **succeeded**
— it germinated, survived the lab, and was grown on. Crosses that produced no
pod were never flasked, never planted, never tagged and never photographed.

This is **survivorship bias**. A dataset built only from tags contains
`label = success` for every row and can teach a classifier nothing about
failure. Any claim of a "compatibility prediction accuracy" trained this way
would be invalid.

Negative examples must come from elsewhere — see the component README for the
proposed sources.
