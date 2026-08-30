"""
Stage 2 retrained to reject non-orchid FOLIAGE, and measured honestly.

WHY THIS EXISTS
---------------
Stage 2 was trained on orchids against other FLOWERS (Oxford Flowers-102). It
had never been shown a fern, a palm or an anthurium, so non-orchid foliage had
nothing stopping it: 84% of ferns and 85% of houseplants were called "orchid",
and in use an anthurium photographed on a white background was assessed
"Suitable, 97.9%".

Fixing that needs foliage in the negative set. The only foliage images available
were the held-out ferns and houseplants in gate_validation, plus aloe and agave
downloaded before Wikimedia began rate-limiting. Putting the held-out images
into training destroys their value as a test, so they are not simply added.

HOW THE NUMBER STAYS HONEST
---------------------------
The foliage negatives are cross-validated. In each of 5 folds the filter is
fitted on four fifths of them and scored on the fifth, which it has never seen.
The reported foliage refusal rate is the average over the held-out fifths, so no
image is ever scored by a model that trained on it.

Everything else keeps its original status and is scored against the final model:
roses and tulips, and the orchid photographs, were never in training at all, so
those remain a fully held-out third-source test.

Run:  python src/train_flower_filter_cv.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchid_gate import embed
from flower_filter import FlowerFilter, BUNDLE_PATH
from train_orchid_gate import collect_project_images, load_or_build_embeddings
from train_flower_filter import (load_flowers102, load_validation,
                                 load_plant_negatives)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE_DIR, "results", "flower_filter_cv.txt")
KEEP_FRACTION = 0.99
FOLIAGE_CATEGORIES = {"ferns", "houseplants"}


def main():
    lines = []

    def say(msg=""):
        print(msg, flush=True)
        lines.append(msg)

    say("=" * 74)
    say("STAGE 2 RETRAINED - now including non-orchid foliage as negatives")
    say("=" * 74)

    say("\n[1] Positives - the project's own orchid photographs")
    paths, groups, sources = collect_project_images()
    Xpos = load_or_build_embeddings(paths, verbose=False)
    Xpos = Xpos[Xpos.any(axis=1)]
    say("  {}".format(len(Xpos)))

    say("\n[2] Negatives - Oxford Flowers-102 (other flowers)")
    f102, Xf = load_flowers102()
    ok = Xf.any(axis=1)
    f102, Xf = f102[ok].reset_index(drop=True), Xf[ok]
    Xflowers = Xf[~f102.is_orchid.values]
    say("  {}".format(len(Xflowers)))

    say("\n[3] Negatives - foliage")
    _, Xdown = load_plant_negatives()
    if len(Xdown):
        Xdown = Xdown[Xdown.any(axis=1)]
    say("  {} downloaded (aloe, agave - independent of the test set)".format(len(Xdown)))

    val, Xval = load_validation()
    foliage_mask = val.category.isin(FOLIAGE_CATEGORIES).values
    Xfoliage_val = Xval[foliage_mask]
    say("  {} ferns and houseplants from the validation set - CROSS-VALIDATED"
        .format(len(Xfoliage_val)))
    say("  below, never scored by a model that trained on them")

    # foliage pool that gets cross-validated
    Xfoliage = np.vstack([Xdown, Xfoliage_val]) if len(Xdown) else Xfoliage_val

    say("\n[4] Cross-validated foliage refusal (the honest foliage number)")
    from sklearn.model_selection import KFold
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    refused = total = 0
    for tr, te in kf.split(Xfoliage):
        neg = np.vstack([Xflowers, Xfoliage[tr]])
        f = FlowerFilter().fit(Xpos, neg, keep_fraction=KEEP_FRACTION)
        p = f.orchid_probability(Xfoliage[te])
        refused += int((p < f.threshold).sum())
        total += len(te)
    foliage_cv = refused / max(total, 1)
    say("  foliage refused: {}/{} = {:.1%}   (was 16% before)".format(
        refused, total, foliage_cv))

    say("\n[5] Final model, fitted on everything")
    Xneg = np.vstack([Xflowers, Xfoliage])
    filt = FlowerFilter().fit(Xpos, Xneg, keep_fraction=KEEP_FRACTION)
    filt.metrics = {"foliage_refused_cv": float(foliage_cv)}
    say("  {} positives vs {} negatives, threshold {:.4f}".format(
        len(Xpos), len(Xneg), filt.threshold))

    say("\n[6] Still fully held out - never in training at any point")
    pv = filt.orchid_probability(Xval)
    called = pv >= filt.threshold
    for name, mask in (
        ("orchids (Vanda + other genera)", (val.label == "orchid").values),
        ("roses, tulips, sunflowers", (val.category == "other_flowers").values),
    ):
        sub = called[mask]
        if len(sub):
            if name.startswith("orchids"):
                say("  {:34s} n={:<4d} ACCEPTED {:.0%}".format(name, len(sub), sub.mean()))
            else:
                say("  {:34s} n={:<4d} REFUSED  {:.0%}".format(
                    name, len(sub), 1 - sub.mean()))

    from sklearn.metrics import roc_auc_score
    orc = (val.label == "orchid").values
    flw = (val.category == "other_flowers").values
    sel = orc | flw
    auc = roc_auc_score(orc[sel].astype(int), pv[sel])
    say("  ROC AUC orchid vs other flower (third source): {:.3f}".format(auc))

    say("\n[7] Per-category, final model")
    for cat in sorted(val.category.unique()):
        m = (val.category == cat).values
        tag = " (in training, CV number above)" if cat in FOLIAGE_CATEGORIES else ""
        say("  {:22s} n={:<4d} called orchid {:>4.0%}{}".format(
            cat, int(m.sum()), called[m].mean(), tag))

    filt.save()
    say("\n  saved -> {}".format(BUNDLE_PATH))

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n[DONE] report -> {}".format(RESULTS))


if __name__ == "__main__":
    main()
