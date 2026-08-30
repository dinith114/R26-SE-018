"""
Build and MEASURE stage 2 of the input gate (orchid vs other flower).

The headline number deliberately comes from a THIRD source. Training uses this
project's nursery photographs as positives and Oxford Flowers-102 as negatives;
the reported score is measured on Wikimedia Commons orchids versus Wikimedia
Commons roses, tulips and sunflowers. Both halves of that test set come from the
same place, so a model that had merely learned "phone camera versus Oxford
camera" scores at chance on it.

Run:  python src/train_flower_filter.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchid_gate import embed
from flower_filter import FlowerFilter, BUNDLE_PATH
from train_orchid_gate import collect_project_images, load_or_build_embeddings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
F102_DIR = os.path.join(DATA_DIR, "images", "flowers102")
F102_CACHE = os.path.join(DATA_DIR, "flowers102_embeddings.npz")
VAL_CACHE = os.path.join(DATA_DIR, "gate_validation_embeddings.npz")
VALIDATION_DIR = os.path.join(DATA_DIR, "images", "gate_validation")
RESULTS = os.path.join(BASE_DIR, "results", "flower_filter.txt")

KEEP_FRACTION = 0.99


def load_flowers102():
    """Oxford Flowers-102, split into its orchid classes and everything else."""
    csv = os.path.join(F102_DIR, "flowers102_labels.csv")
    df = pd.read_csv(csv)
    df = df[df.image_path.apply(os.path.exists)].reset_index(drop=True)

    if os.path.exists(F102_CACHE):
        cached = np.load(F102_CACHE, allow_pickle=True)
        if list(cached["paths"]) == list(df.image_path):
            return df, cached["X"]

    print("  embedding {} Flowers-102 images (CPU, this is the slow step)".format(len(df)))
    X = embed(df.image_path.tolist(), verbose=True)
    np.savez_compressed(F102_CACHE, X=X, paths=np.array(df.image_path, dtype=object))
    return df, X


PLANT_NEG_DIR = os.path.join(DATA_DIR, "images", "plant_negatives")
PLANT_NEG_CACHE = os.path.join(DATA_DIR, "plant_negatives_embeddings.npz")


def load_plant_negatives():
    """
    Non-orchid PLANT photographs - ferns, palms, aloes, bromeliads, cacti.

    Added after a user test: a non-orchid houseplant was assessed "Suitable".
    Stage 2 had only ever been shown orchids against other FLOWERS, so foliage
    that is not an orchid had nothing stopping it - 84% of ferns and 85% of
    houseplants were called orchid.

    The search terms used to collect these are deliberately different from the
    ones behind data/images/gate_validation/not_orchid/{ferns,houseplants},
    which stay untouched as the held-out test. Strap-leaved monocots (aloe,
    agave, bromeliad, anthurium, sansevieria) are included on purpose: a Vanda
    is itself a strap-leaved monocot, so a negative set of only broad-leaved
    plants would not teach the distinction that matters.
    """
    if not os.path.isdir(PLANT_NEG_DIR):
        return [], np.zeros((0, 512), dtype=np.float32)

    paths = []
    for sub in sorted(os.listdir(PLANT_NEG_DIR)):
        d = os.path.join(PLANT_NEG_DIR, sub)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".jpg", ".png")):
                    paths.append(os.path.join(d, f))

    if not paths:
        return [], np.zeros((0, 512), dtype=np.float32)

    if os.path.exists(PLANT_NEG_CACHE):
        cached = np.load(PLANT_NEG_CACHE, allow_pickle=True)
        if list(cached["paths"]) == list(paths):
            return paths, cached["X"]

    print("  embedding {} non-orchid plant photographs".format(len(paths)))
    X = embed(paths, verbose=True)
    np.savez_compressed(PLANT_NEG_CACHE, X=X, paths=np.array(paths, dtype=object))
    return paths, X


def load_validation():
    """The held-out Wikimedia set, embedded once and cached."""
    rows = []
    for label in sorted(os.listdir(VALIDATION_DIR)):
        label_dir = os.path.join(VALIDATION_DIR, label)
        if not os.path.isdir(label_dir):
            continue
        for category in sorted(os.listdir(label_dir)):
            cat_dir = os.path.join(label_dir, category)
            if not os.path.isdir(cat_dir):
                continue
            for f in sorted(os.listdir(cat_dir)):
                if f.lower().endswith((".jpg", ".png")):
                    rows.append({"path": os.path.join(cat_dir, f),
                                 "label": label, "category": category})
    df = pd.DataFrame(rows)

    if os.path.exists(VAL_CACHE):
        cached = np.load(VAL_CACHE, allow_pickle=True)
        if list(cached["paths"]) == list(df.path):
            return df, cached["X"]

    print("  embedding {} validation images".format(len(df)))
    X = embed(df.path.tolist(), verbose=True)
    np.savez_compressed(VAL_CACHE, X=X, paths=np.array(df.path, dtype=object))
    return df, X


def main():
    lines = []

    def say(msg=""):
        print(msg, flush=True)
        lines.append(msg)

    say("=" * 74)
    say("FLOWER FILTER - stage 2 of the input gate (orchid vs other flower)")
    say("=" * 74)

    say("\n[1] Positives - this project's own orchid photographs")
    paths, groups, sources = collect_project_images()
    Xpos = load_or_build_embeddings(paths, verbose=False)
    keep = Xpos.any(axis=1)
    Xpos, groups = Xpos[keep], groups[keep]
    say("  {} images, {} groups".format(len(Xpos), len(np.unique(groups))))

    say("\n[2] Negatives - Oxford Flowers-102")
    f102, Xf = load_flowers102()
    ok = Xf.any(axis=1)
    f102, Xf = f102[ok].reset_index(drop=True), Xf[ok]
    other = ~f102.is_orchid.values
    Xother, Xf102_orchid = Xf[other], Xf[~other]
    say("  {} other-flower images across {} species".format(
        len(Xother), f102[other].class_id.nunique()))
    say("  {} images held out from the two ORCHID classes (2, 7) - excluded from"
        .format(len(Xf102_orchid)))
    say("  training so the filter is never taught to call an orchid 'not orchid'")

    say("\n[2b] Negatives - non-orchid plants (foliage, not flowers)")
    plant_paths, Xplants = load_plant_negatives()
    if len(Xplants):
        Xplants = Xplants[Xplants.any(axis=1)]
        say("  {} photographs of ferns, palms, aloes, bromeliads, cacti".format(len(Xplants)))
        say("  collected with search terms DIFFERENT from the held-out ferns and")
        say("  houseplants in gate_validation, so the test set stays honest")
        Xnegatives = np.vstack([Xother, Xplants])
    else:
        say("  none found - run scratchpad/fetch_plant_negatives.py")
        Xnegatives = Xother
    say("  total negatives: {}".format(len(Xnegatives)))

    say("\n[3] Fitting")
    filt = FlowerFilter().fit(Xpos, Xnegatives, keep_fraction=KEEP_FRACTION)
    say("  logistic regression, balanced class weights")
    say("  threshold {:.4f} (keeps {:.0%} of the project's own photographs)".format(
        filt.threshold, KEEP_FRACTION))

    say("\n[4] In-domain check (same sources as training - optimistic by design)")
    p_pos = filt.orchid_probability(Xpos)
    p_neg = filt.orchid_probability(Xnegatives)
    say("  project photos called orchid   : {:.1%}".format(float((p_pos >= filt.threshold).mean())))
    say("  Flowers-102 called other flower: {:.1%}".format(float((p_neg < filt.threshold).mean())))
    say("  NOTE: both sets were seen in training. The number that counts is below.")

    say("\n[5] THE HONEST TEST - Wikimedia Commons only, neither training source")
    val, Xval = load_validation()
    pv = filt.orchid_probability(Xval)
    val = val.assign(p_orchid=pv, called_orchid=pv >= filt.threshold)

    wiki_orchid = val[val.label == "orchid"]
    wiki_flowers = val[val.category == "other_flowers"]

    say("")
    say("  {:22s} {:>4s} {:>14s} {:>10s}".format("set", "n", "called orchid", "median p"))
    say("  " + "-" * 54)
    for name, sub in (("Wikimedia orchids", wiki_orchid),
                      ("Wikimedia roses/tulips", wiki_flowers)):
        if len(sub):
            say("  {:22s} {:>4d} {:>13.0%} {:>10.2f}".format(
                name, len(sub), float(sub.called_orchid.mean()), float(sub.p_orchid.median())))

    if len(wiki_orchid) and len(wiki_flowers):
        from sklearn.metrics import roc_auc_score
        y = np.r_[np.ones(len(wiki_orchid)), np.zeros(len(wiki_flowers))]
        s = np.r_[wiki_orchid.p_orchid.values, wiki_flowers.p_orchid.values]
        auc = roc_auc_score(y, s)
        say("")
        say("  ROC AUC on the third source: {:.3f}".format(auc))
        say("  (0.5 would mean the filter had only learned which camera took the photo)")
        filt.metrics = {"third_source_auc": float(auc),
                        "wiki_orchid_kept": float(wiki_orchid.called_orchid.mean()),
                        "wiki_flower_refused": float(1 - wiki_flowers.called_orchid.mean())}

    say("\n[6] Flowers-102 orchid classes, never trained on")
    if len(Xf102_orchid):
        p = filt.orchid_probability(Xf102_orchid)
        say("  {} images of Paphiopedilum / Phalaenopsis called orchid: {:.0%}".format(
            len(p), float((p >= filt.threshold).mean())))
        say("  (a different genus from Vanda, so this is generalisation, not recall)")

    say("\n[7] Everything else in the validation set")
    for cat in sorted(val.category.unique()):
        sub = val[val.category == cat]
        say("  {:22s} n={:<4d} called orchid {:>4.0%}".format(
            cat, len(sub), float(sub.called_orchid.mean())))

    filt.save()
    say("\n  saved -> {}".format(BUNDLE_PATH))

    val.to_csv(os.path.join(BASE_DIR, "results", "flower_filter_validation.csv"), index=False)
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n[DONE] report -> {}".format(RESULTS))


if __name__ == "__main__":
    main()
