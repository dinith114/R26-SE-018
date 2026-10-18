"""
measure_photo_checks.py -- set the photo-check limits from the real photographs.

A limit picked by feel ("blur below 100") invites the obvious question: how do
you know it would not refuse good photographs? This script answers with
measurements, using the very functions the backend runs (src/photo_checks.py):

  1. REAL PHOTOGRAPHS  all 667 in data/processed/. Each limit is set beyond the
                       worst of them, with a margin, so none would be refused.
  2. BAD COPIES        200 of them, blurred, darkened or washed out on purpose.
                       The share caught shows the checks do their job.
  3. COPIES            the same 200, re-saved at low quality, resized, slightly
                       brightened or cropped. The copy distance is the smallest
                       that catches them, and the false alarms it would raise
                       among the 221,445 pairs of DIFFERENT photographs are
                       counted too.

Writes results/photo_checks/ (report, thresholds JSON, figure). Copy the
thresholds into src/photo_checks.py.

Usage
-----
    python measure_photo_checks.py
"""

import argparse
import json
import math
import random
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPONENT_ROOT / "src"))
import photo_checks as pc  # noqa: E402

SAMPLE = 200
SEED = 42


def popcount64(x):
    """Bits set in each element of a uint64 array."""
    x = x.astype(np.uint64)
    table = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
    total = np.zeros(x.shape, dtype=np.int64)
    for shift in range(0, 64, 8):
        total += table[((x >> np.uint64(shift)) & np.uint64(0xFF)).astype(np.int64)]
    return total


def resave(img, quality):
    from PIL import Image
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return Image.open(BytesIO(buf.getvalue())).convert("RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(COMPONENT_ROOT / "data" / "processed"))
    ap.add_argument("--out", default=str(COMPONENT_ROOT / "results" / "photo_checks"))
    args = ap.parse_args()

    from PIL import Image, ImageEnhance, ImageFilter

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    photos = sorted(Path(args.data).rglob("*.jpg"))
    if not photos:
        sys.exit("ERROR: no photographs under {}".format(args.data))

    # --- 1. the real photographs ---------------------------------------------
    real, images = [], {}
    for p in photos:
        img = pc.cap_size(pc.open_image(p.read_bytes()))
        m = pc.measure(img)
        m.update(file=str(p.relative_to(Path(args.data))).replace("\\", "/"), dhash=pc.dhash(img))
        real.append(m)
        images[m["file"]] = img
    B = np.array([r["brightness"] for r in real])
    S = np.array([r["sharpness"] for r in real])
    short = np.array([min(r["width"], r["height"]) for r in real])
    pixels = np.array([r["width"] * r["height"] for r in real])

    # Margins beyond the worst real photograph, because a grower's phone in a
    # shade house will sometimes do worse than the dataset's worst, and refusing
    # a photograph an expert could have judged is the costlier mistake.
    # Brightness gets a fixed 20 levels. Sharpness spans orders of magnitude, so
    # its margin is a ratio: 75% of the softest real photograph. At 50% the
    # check missed a third of photographs blurred by 4 pixels; at 75% it misses
    # 4%, and still refuses none of the 667 (both measured, see the report).
    min_brightness = max(5, math.floor(B.min()) - 20)
    max_brightness = min(250, math.ceil(B.max()) + 20)
    min_sharpness = round(float(S.min()) * 0.75, 1)

    say("=" * 72)
    say("  PHOTO-CHECK LIMITS, measured on {} real photographs".format(len(real)))
    say("  run at {}".format(datetime.now().isoformat(timespec="seconds")))
    say("=" * 72)
    say("\n  {:<12}{:>10}{:>10}{:>10}{:>10}{:>10}".format(
        "", "min", "1st pct", "median", "99th pct", "max"))
    for name, v in (("brightness", B), ("sharpness", S), ("short side", short),
                    ("pixels", pixels)):
        say("  {:<12}{:>10.1f}{:>10.1f}{:>10.1f}{:>10.1f}{:>10.1f}".format(
            name, v.min(), np.percentile(v, 1), np.median(v), np.percentile(v, 99), v.max()))
    worst = sorted(real, key=lambda r: r["sharpness"])[:3]
    say("\n  softest real photographs: {}".format(
        ", ".join("{} ({})".format(r["file"], r["sharpness"]) for r in worst)))
    darkest = sorted(real, key=lambda r: r["brightness"])[:3]
    say("  darkest real photographs: {}".format(
        ", ".join("{} ({})".format(r["file"], r["brightness"]) for r in darkest)))

    say("\n  LIMITS")
    say("    too small   fewer than {:,} pixels (224 x 224; smallest real photograph {:,})".format(
        pc.MIN_PIXELS, int(pixels.min())))
    say("    too dark    brightness < {}   (darkest real photograph {:.1f}, minus 20)".format(
        min_brightness, B.min()))
    say("    washed out  brightness > {}   (brightest real photograph {:.1f}, plus 20)".format(
        max_brightness, B.max()))
    say("    blurred     sharpness < {}   (75% of the softest real photograph, {:.1f})".format(
        min_sharpness, S.min()))

    pc.MIN_BRIGHTNESS, pc.MAX_BRIGHTNESS, pc.MIN_SHARPNESS = (
        min_brightness, max_brightness, min_sharpness)
    refused = [r for r in real if pc.problems(r)]
    say("\n  real photographs refused by these limits: {} of {}".format(len(refused), len(real)))

    # --- 2. bad copies ---------------------------------------------------------
    rng = random.Random(SEED)
    sample = rng.sample(sorted(images), SAMPLE)
    degradations = [
        ("blur, radius 2 px", lambda im: im.filter(ImageFilter.GaussianBlur(2))),
        ("blur, radius 3 px", lambda im: im.filter(ImageFilter.GaussianBlur(3))),
        ("blur, radius 4 px", lambda im: im.filter(ImageFilter.GaussianBlur(4))),
        ("blur, radius 6 px", lambda im: im.filter(ImageFilter.GaussianBlur(6))),
        ("blur, radius 8 px", lambda im: im.filter(ImageFilter.GaussianBlur(8))),
        ("darkened to 25%", lambda im: ImageEnhance.Brightness(im).enhance(0.25)),
        ("darkened to 10%", lambda im: ImageEnhance.Brightness(im).enhance(0.10)),
        ("brightened x3 (glare)", lambda im: ImageEnhance.Brightness(im).enhance(3.0)),
        ("shrunk to 200 px", lambda im: im.resize(
            (max(1, round(im.width * 200 / max(im.size))),
             max(1, round(im.height * 200 / max(im.size)))))),
    ]
    say("\n  BAD COPIES -- {} photographs, each spoiled on purpose".format(SAMPLE))
    caught_summary = {}
    for name, fn in degradations:
        caught = sum(1 for f in sample if pc.problems(pc.measure(fn(images[f]))))
        caught_summary[name] = caught / SAMPLE
        say("    {:<24} caught {:>4} of {}  ({:.0%})".format(name, caught, SAMPLE, caught / SAMPLE))

    # --- 3. copies -------------------------------------------------------------
    variants = [
        ("re-saved at JPEG quality 40", lambda im: resave(im, 40)),
        ("resized to half", lambda im: im.resize((im.width // 2, im.height // 2), Image.LANCZOS)),
        ("brightened 15%", lambda im: ImageEnhance.Brightness(im).enhance(1.15)),
        ("cropped 3% each side", lambda im: im.crop((
            round(im.width * .03), round(im.height * .03),
            round(im.width * .97), round(im.height * .97)))),
    ]
    copy_d = {name: [pc.distance(pc.dhash(images[f]), pc.dhash(fn(images[f]))) for f in sample]
              for name, fn in variants}
    all_copy = np.concatenate([np.array(v) for v in copy_d.values()])
    # The smallest distance that catches 99% of the copies.
    copy_distance = int(np.percentile(all_copy, 99))

    hashes = np.array([int(r["dhash"], 16) for r in real], dtype=np.uint64)
    pair_d = popcount64(hashes[:, None] ^ hashes[None, :])
    iu = np.triu_indices(len(real), k=1)
    distinct = pair_d[iu]
    alarms = int((distinct <= copy_distance).sum())

    say("\n  COPIES -- the same {} photographs, altered slightly".format(SAMPLE))
    say("    {:<30}{:>8}{:>8}{:>8}".format("", "median", "99th", "max"))
    for name, d in copy_d.items():
        say("    {:<30}{:>8.0f}{:>8.0f}{:>8.0f}".format(
            name, np.median(d), np.percentile(d, 99), max(d)))
    say("    copy distance (catches 99% of copies): {} of 64 bits".format(copy_distance))
    say("    copies caught at that distance: {:.1%}".format((all_copy <= copy_distance).mean()))
    say("\n    pairs of DIFFERENT photographs: {:,}".format(len(distinct)))
    say("    median distance between different photographs: {:.0f} bits".format(np.median(distinct)))
    say("    different pairs within the copy distance (false alarms): {} ({:.3%})".format(
        alarms, alarms / len(distinct)))
    close = sorted(zip(distinct.tolist(), iu[0].tolist(), iu[1].tolist()))[:10]
    say("    closest pairs of different photographs (look at these by eye):")
    for d, i, j in close:
        say("      {:>2} bits  {}  {}".format(d, real[i]["file"], real[j]["file"]))

    # Near-copies that cross the ORIGINAL train / test split. check_leakage.py
    # tracks each photograph's 54 augmented copies, so it cannot see two
    # separate shots of one leaf. This can.
    split_csv = Path(args.data).parent / "split" / "split_manifest.csv"
    cross_split = []
    if split_csv.exists():
        import csv
        split = {r["image_id"]: r["split"] for r in csv.DictReader(open(split_csv, encoding="utf-8"))}
        stem = [Path(r["file"]).stem for r in real]
        for i in range(len(real)):
            if split.get(stem[i]) in ("validation", "test"):
                for j in np.where(pair_d[i] <= 6)[0]:
                    if j != i and split.get(stem[j]) == "train":
                        cross_split.append({"held_out": real[i]["file"], "part": split[stem[i]],
                                            "train": real[j]["file"], "bits": int(pair_d[i][j])})
        say("\n  NEAR-COPIES ACROSS THE ORIGINAL SPLIT (6 bits or fewer)")
        if cross_split:
            for c in cross_split:
                say("    {} ({}) ~ {} (train), {} bits".format(c["held_out"], c["part"], c["train"], c["bits"]))
            say("    Two shots of the same leaf, one in training and one held out. The")
            say("    augmentation leakage check cannot see these; this check can.")
        else:
            say("    none")

    thresholds = {
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "photographs": len(real),
        "MIN_PIXELS": pc.MIN_PIXELS,
        "MIN_BRIGHTNESS": min_brightness,
        "MAX_BRIGHTNESS": max_brightness,
        "MIN_SHARPNESS": min_sharpness,
        "COPY_DISTANCE": copy_distance,
        "real_refused": len(refused),
        "bad_copies_caught": caught_summary,
        "copies_caught": float((all_copy <= copy_distance).mean()),
        "false_alarm_pairs": alarms,
        "distinct_pairs": int(len(distinct)),
        "near_copies_across_split": cross_split,
        "real_range": {"brightness": [float(B.min()), float(B.max())],
                       "sharpness": [float(S.min()), float(S.max())],
                       "short_side": [int(short.min()), int(short.max())],
                       "pixels": [int(pixels.min()), int(pixels.max())]},
    }
    (out_dir / "photo_check_thresholds.json").write_text(json.dumps(thresholds, indent=2),
                                                        encoding="utf-8")
    (out_dir / "photo_checks_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 3, figsize=(13, 3.6))
        ax[0].hist(B, bins=40, color="tab:blue", alpha=0.8)
        for v in (min_brightness, max_brightness):
            ax[0].axvline(v, color="red", ls="--")
        ax[0].set_title("brightness of real photos\n(red: limits)", fontsize=10)
        ax[1].hist(np.log10(S), bins=40, color="tab:green", alpha=0.8)
        ax[1].axvline(math.log10(min_sharpness), color="red", ls="--")
        ax[1].set_title("sharpness of real photos, log10\n(red: blur limit)", fontsize=10)
        ax[2].hist(distinct, bins=range(0, 65), color="grey", alpha=0.7, density=True,
                   label="different photos")
        ax[2].hist(all_copy, bins=range(0, 65), color="tab:orange", alpha=0.8, density=True,
                   label="altered copies")
        ax[2].axvline(copy_distance + 0.5, color="red", ls="--")
        ax[2].set_title("difference-hash distance\n(red: copy limit)", fontsize=10)
        ax[2].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / "photo_checks.png", dpi=180)
        plt.close(fig)
    except ImportError:
        pass

    say("\n  written: {}".format(out_dir))
    (out_dir / "photo_checks_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
