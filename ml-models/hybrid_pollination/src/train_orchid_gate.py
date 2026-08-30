"""
Hybrid Pollination - Build and MEASURE the input validation gate.

Fits the one-class gate on the project's own orchid photographs, then measures
it two ways:

  1. Grouped cross-validation on the project photographs, to report how often a
     genuine orchid photo would be wrongly refused. Grouping matters: the same
     plant appears in many frames, so an image-level split would put near
     duplicates on both sides and report a false-reject rate that is too good.

  2. A held-out validation set downloaded from Wikimedia Commons, which the gate
     never sees during fitting. It contains things that must be refused
     (laptops, screens, people, rooms, cars, food, documents) and, importantly,
     orchids photographed by other people that must still be ACCEPTED. Measuring
     only refusals would hide a gate that simply says no to everything.

Run:  python src/train_orchid_gate.py
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchid_gate import OrchidGate, embed, BUNDLE_PATH

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
CACHE = os.path.join(DATA_DIR, "gate_embeddings.npz")
VALIDATION_DIR = os.path.join(IMAGES_DIR, "gate_validation")
RESULTS = os.path.join(BASE_DIR, "results", "orchid_gate.txt")

# Raised from 0.99 after stage 2 (flower_filter.py) was added.
#
# At 0.99 stage 1 was the only gate, so it had to be tight enough to refuse
# roses by itself. It never managed that - 27% - and the tightness cost real
# orchid photographs, including a seedling in a plastic pot, which is exactly
# the case the maturity feature exists for. Stage 2 now refuses 80-87% of other
# flowers, so stage 1 no longer has to.
#
# Measured over the whole pipeline (non-plants refused / other flowers refused /
# unseen orchids accepted / the project's own photos wrongly refused):
#
#     0.990   100%   87%   66%   2.6%
#     0.995   100%   80%   80%   2.1%   <- chosen
#     0.999    95%   71%   86%   1.8%
#     1.000    92%   71%   88%   1.7%
#
# 0.999 and above are ruled out regardless of how good the other columns look:
# they stop refusing every non-plant, and a laptop photograph scoring "Suitable"
# is the failure this gate was built to prevent.
# Tightened from 0.995 to 0.98 after a non-orchid houseplant (an anthurium,
# photographed on a white background) was assessed "Suitable, 97.9%".
#
# Stage 2 was extended with foliage negatives first, and that alone was not
# enough - cross-validated foliage refusal only reached 21.5%, because 191
# foliage images cannot outweigh 8089 flowers and 1190 orchids in the fit.
# The stage-1 threshold turned out to be the effective lever. Measured over the
# whole pipeline:
#
#     keep   own refused  non-plants  FOLIAGE  flowers  orchids accepted
#     0.970      4.5%        100%       95%      96%         58%
#     0.980      3.3%        100%       94%      93%         61%   <- chosen
#     0.990      2.1%        100%       86%      91%         65%
#     0.995      1.6%        100%       77%      87%         75%
#
# 0.98 is chosen over 0.995 deliberately, and it is a real trade: unseen orchid
# photographs drop from 75% to 61% accepted. A grower being asked to retake a
# photograph is a nuisance; a fern or an anthurium coming back "Suitable for
# pollination" is the system being wrong about the one thing it exists to
# judge. 0.97 buys one more point of foliage refusal for another point of the
# project's own photographs, which is not worth it.
KEEP_FRACTION = 0.98


# --------------------------------------------------------------------------
# Collecting the project's own photographs
# --------------------------------------------------------------------------

def collect_project_images():
    """
    Every orchid photograph this project owns, with a group id per plant.

    Three sources, all legitimate uploads a grower might make:
      plants/        whole plant, 357 frames of 28 plants
      flowers/       close-ups of blooms
      tagged_plants/ plants photographed with their name tag
    """
    paths, groups, sources = [], [], []

    clean = os.path.join(DATA_DIR, "image_annotations_clean.csv")
    if os.path.exists(clean):
        df = pd.read_csv(clean)
        for _, r in df.iterrows():
            p = str(r["image_path"])
            if os.path.exists(p):
                paths.append(p)
                groups.append("plant:" + str(r["sample_id"]))
                sources.append("plants")

    flowers = os.path.join(DATA_DIR, "flower_annotations.csv")
    if os.path.exists(flowers):
        df = pd.read_csv(flowers)
        for _, r in df.iterrows():
            p = str(r["image_path"])
            if os.path.exists(p):
                paths.append(p)
                # No plant id was recorded for the bloom close-ups, so each frame
                # is its own group. That is the conservative choice: it cannot
                # accidentally place two frames of one flower on the same side.
                groups.append("flower:" + os.path.splitext(str(r["image_name"]))[0])
                sources.append("flowers")

    tagged = os.path.join(DATA_DIR, "tagged_plants.csv")
    if os.path.exists(tagged):
        df = pd.read_csv(tagged)
        for _, r in df.iterrows():
            rel = str(r["image_path"])
            p = rel if os.path.isabs(rel) else os.path.join(IMAGES_DIR, "tagged_plants", rel)
            if os.path.exists(p):
                paths.append(p)
                groups.append("tagged:" + str(r["plant_id"]))
                sources.append("tagged_plants")

    return paths, np.array(groups), np.array(sources)


def load_or_build_embeddings(paths, verbose=True):
    """Embed the project photographs once and cache; ResNet18 on CPU is slow."""
    if os.path.exists(CACHE):
        cached = np.load(CACHE, allow_pickle=True)
        if list(cached["paths"]) == list(paths):
            if verbose:
                print("  using cached embeddings {}".format(cached["X"].shape))
            return cached["X"]
        if verbose:
            print("  cache is stale (image list changed), re-embedding")

    if verbose:
        print("  embedding {} project photographs (CPU, a few minutes)".format(len(paths)))
    X = embed(paths, verbose=verbose)
    np.savez_compressed(CACHE, X=X, paths=np.array(paths, dtype=object))
    return X


# --------------------------------------------------------------------------
# Measurement 1 - how often would a real orchid photo be refused?
# --------------------------------------------------------------------------

def grouped_false_reject_rate(X, groups, n_splits=5):
    """
    Fit on some plants, test on plants held out entirely.

    Reports the share of genuine orchid photographs the gate would turn away.
    Fitting and testing on the same frames would understate this badly, because
    the threshold is a quantile of the very distances being tested.
    """
    from sklearn.model_selection import GroupKFold

    n_groups = len(np.unique(groups))
    n_splits = min(n_splits, n_groups)
    gkf = GroupKFold(n_splits=n_splits)

    refused = 0
    total = 0
    for train_idx, test_idx in gkf.split(X, groups=groups):
        gate = OrchidGate().fit(X[train_idx], keep_fraction=KEEP_FRACTION)
        d = gate.distances(X[test_idx])
        refused += int((d > gate.threshold).sum())
        total += len(test_idx)

    return refused / max(total, 1), total, n_splits


# --------------------------------------------------------------------------
# Measurement 2 - the held-out validation set
# --------------------------------------------------------------------------

def collect_validation():
    """Downloaded images, labelled by the folder they were saved into."""
    rows = []
    if not os.path.isdir(VALIDATION_DIR):
        return rows

    for label in sorted(os.listdir(VALIDATION_DIR)):          # orchid | not_orchid
        label_dir = os.path.join(VALIDATION_DIR, label)
        if not os.path.isdir(label_dir):
            continue
        for category in sorted(os.listdir(label_dir)):
            cat_dir = os.path.join(label_dir, category)
            if not os.path.isdir(cat_dir):
                continue
            files = sorted(glob.glob(os.path.join(cat_dir, "*.jpg")) +
                           glob.glob(os.path.join(cat_dir, "*.png")))
            for f in files:
                rows.append({"path": f, "label": label, "category": category})
    return rows


def evaluate_validation(gate, rows, verbose=True):
    if not rows:
        return None

    paths = [r["path"] for r in rows]
    if verbose:
        print("  embedding {} validation images".format(len(paths)))
    Xv = embed(paths, verbose=verbose)

    d = gate.distances(Xv)
    for r, dist in zip(rows, d):
        r["distance"] = float(dist)
        r["accepted"] = bool(dist <= gate.threshold)

    df = pd.DataFrame(rows)

    by_cat = (df.groupby(["label", "category"])
                .agg(n=("accepted", "size"),
                     accepted=("accepted", "sum"),
                     median_distance=("distance", "median"))
                .reset_index())
    by_cat["accept_rate"] = (by_cat["accepted"] / by_cat["n"]).round(3)

    return df, by_cat


# --------------------------------------------------------------------------

def main():
    lines = []

    def say(msg=""):
        print(msg)
        lines.append(msg)

    say("=" * 74)
    say("ORCHID INPUT GATE - build and measurement")
    say("=" * 74)

    say("\n[1] Collecting the project's own photographs")
    paths, groups, sources = collect_project_images()
    if not paths:
        say("  no images found - nothing to fit")
        return
    for s in sorted(set(sources)):
        say("  {:16s} {:4d} images".format(s, int((sources == s).sum())))
    say("  {:16s} {:4d} images, {} groups".format(
        "TOTAL", len(paths), len(np.unique(groups))))

    say("\n[2] Embedding with frozen ResNet18 (no mask, whole frame)")
    X = load_or_build_embeddings(paths)
    keep = X.any(axis=1)
    if not keep.all():
        say("  dropped {} unreadable images".format(int((~keep).sum())))
        X, groups = X[keep], groups[keep]

    say("\n[3] Grouped cross-validation - false refusals on real orchid photos")
    fr, n_tested, n_splits = grouped_false_reject_rate(X, groups)
    say("  {}-fold GroupKFold over {} images".format(n_splits, n_tested))
    say("  genuine orchid photos refused: {:.1%}".format(fr))
    say("  (threshold is set to keep {:.0%} of training photos)".format(KEEP_FRACTION))

    say("\n[4] Fitting the final gate on all project photographs")
    gate = OrchidGate().fit(X, keep_fraction=KEEP_FRACTION)
    say("  fitted on {} images".format(gate.n_train))
    say("  threshold {:.2f}   train distances p50 {:.2f} / p90 {:.2f} / max {:.2f}".format(
        gate.threshold, gate.train_percentiles["p50"],
        gate.train_percentiles["p90"], gate.train_percentiles["max"]))
    gate.save()
    say("  saved -> {}".format(BUNDLE_PATH))

    say("\n[5] Held-out validation set (never used for fitting)")
    rows = collect_validation()
    if not rows:
        say("  none found - run scratchpad/fetch_val.py to download it")
    else:
        df, by_cat = evaluate_validation(gate, rows)
        say("")
        say("  {:12s} {:20s} {:>4s} {:>9s} {:>9s}".format(
            "label", "category", "n", "accepted", "median d"))
        say("  " + "-" * 58)
        for _, r in by_cat.iterrows():
            say("  {:12s} {:20s} {:>4d} {:>8.0%} {:>9.1f}".format(
                r["label"], r["category"], int(r["n"]),
                r["accept_rate"], r["median_distance"]))

        neg = df[df["label"] == "not_orchid"]
        pos = df[df["label"] == "orchid"]
        say("")
        if len(neg):
            say("  non-orchid images REFUSED : {}/{} = {:.1%}".format(
                int((~neg["accepted"]).sum()), len(neg),
                float((~neg["accepted"]).mean())))
        if len(pos):
            say("  unseen web orchids ACCEPTED: {}/{} = {:.1%}".format(
                int(pos["accepted"].sum()), len(pos),
                float(pos["accepted"].mean())))

        if len(neg) and len(pos):
            from sklearn.metrics import roc_auc_score
            y = (df["label"] == "orchid").astype(int).values
            auc = roc_auc_score(y, -df["distance"].values)
            say("  ROC AUC (orchid vs not, by distance): {:.3f}".format(auc))

        df.to_csv(os.path.join(BASE_DIR, "results", "orchid_gate_validation.csv"),
                  index=False)

    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n[DONE] report -> {}".format(RESULTS))


if __name__ == "__main__":
    main()
