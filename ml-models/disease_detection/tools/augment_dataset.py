"""
augment_dataset.py -- data preparation for the Vanda orchid disease classifier.

Two subcommands.

  rename   raw/<class>/  ->  processed/<class>/
           Bakes EXIF rotation into the pixels, converts to RGB, caps the long
           side at 1024px, saves as <Prefix>_0001.jpg. Writes rename_map.csv.

  augment  split/train/<class>/  ->  split_augmented/train/<class>/
           Produces 54 files per original and a manifest CSV.

           54 = 6 geometries  x  9 colour variants
                6 geometries : original, rot45, rot90, rot180, rot225, rot270
                9 colour     : none, bh50, bl40, eh50, el40, ch50, cl40, sh50, sl40

RUN ORDER MATTERS: split BEFORE augment. Never augment validation or test.
See PROJECT_CONTEXT.md section 6.

Examples
--------
  python augment_dataset.py rename --input ../data/raw/black-leaf-spot
      --output ../data/processed/black_leaf_spot --prefix Black_LS

  python augment_dataset.py augment --input ../data/split/train/black_leaf_spot
      --output ../data/split_augmented/train/black_leaf_spot
      --disease black_leaf_spot --labels ../data/severity_labels.csv
"""

import argparse
import csv
import math
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps, ExifTags

ORIENTATION_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "Orientation")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

# The five extra rotations. 0 (the untouched original) is handled separately.
ROTATIONS = [45, 90, 180, 225, 270]

# code -> (kind, value).  value is the "+50 / -40" style number from the spec.
ADJUSTMENTS = {
    "bh50": ("brightness", +50),
    "bl40": ("brightness", -40),
    "eh50": ("exposure",   +50),
    "el40": ("exposure",   -40),
    "ch50": ("contrast",   +50),
    "cl40": ("contrast",   -40),
    "sh50": ("saturation", +50),
    "sl40": ("saturation", -40),
}


# --------------------------------------------------------------------------
# colour maths
# --------------------------------------------------------------------------

def _srgb_to_linear(c):
    """sRGB 0..1 -> linear light 0..1 (the real amount of photons)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(l):
    """linear light 0..1 -> sRGB 0..1 (what gets stored in the JPEG)."""
    return 12.92 * l if l <= 0.0031308 else 1.055 * (l ** (1 / 2.4)) - 0.055


def _exposure_lut(stops_x100):
    """
    Build a 256-entry lookup table for an exposure change.

    Exposure deliberately differs from brightness. PIL Brightness scales the
    stored sRGB numbers directly. A camera exposure control multiplies the
    LIGHT itself, which is linear, and is measured in stops: +50 means
    +0.5 stops, i.e. 2^0.5 = 1.41x the light. Because sRGB is gamma-encoded,
    doing this in linear light produces a visibly different image from a plain
    1.41x on the stored values -- which is the whole point, otherwise bh50 and
    eh50 would be near-duplicates and would add no real variety.
    """
    gain = 2.0 ** (stops_x100 / 100.0)
    lut = []
    for v in range(256):
        linear = _srgb_to_linear(v / 255.0) * gain
        linear = min(max(linear, 0.0), 1.0)
        lut.append(int(round(_linear_to_srgb(linear) * 255.0)))
    return lut


# Precompute the two exposure tables once; they never change.
_EXPOSURE_LUTS = {+50: _exposure_lut(+50), -40: _exposure_lut(-40)}


def apply_adjustment(img, code):
    """Apply one colour adjustment identified by its short code."""
    kind, value = ADJUSTMENTS[code]
    if kind == "exposure":
        lut = _EXPOSURE_LUTS[value]
        return img.point(lut * 3)                      # same table for R, G, B
    factor = 1.0 + value / 100.0                       # +50 -> 1.5, -40 -> 0.6
    enhancer = {
        "brightness": ImageEnhance.Brightness,
        "contrast":   ImageEnhance.Contrast,
        "saturation": ImageEnhance.Color,
    }[kind](img)
    return enhancer.enhance(factor)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def _largest_inner_rect(w, h, angle_deg):
    """
    Size of the largest axis-aligned rectangle that fits wholly inside a
    w x h rectangle rotated by angle_deg. Used to crop away the black
    triangles that a 45 or 225 degree rotation leaves in the corners.

    Why bother: black corners are a trivially learnable shortcut. A CNN would
    latch onto "black triangle => rotated training image" long before it learns
    what a lesion looks like, inflating training accuracy and collapsing at
    test time on real grower photos that have no black corners.
    """
    if w <= 0 or h <= 0:
        return 0.0, 0.0
    angle = math.radians(angle_deg % 180)
    sin_a, cos_a = abs(math.sin(angle)), abs(math.cos(angle))

    width_is_longer = w >= h
    side_long, side_short = (w, h) if width_is_longer else (h, w)

    if side_short <= 2.0 * sin_a * cos_a * side_long or abs(sin_a - cos_a) < 1e-10:
        # Half-constrained case (includes exactly 45 degrees).
        x = 0.5 * side_short
        wr, hr = (x / sin_a, x / cos_a) if width_is_longer else (x / cos_a, x / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        wr = (w * cos_a - h * sin_a) / cos_2a
        hr = (h * cos_a - w * sin_a) / cos_2a
    return wr, hr


def rotate_image(img, degrees, corner_mode):
    """Rotate by `degrees`. 90/180/270 need no crop; 45/225 do."""
    if degrees == 0:
        return img
    if degrees in (90, 180, 270):
        # Exact quarter turns: no interpolation, no black corners.
        return img.rotate(degrees, expand=True)

    rotated = img.rotate(degrees, resample=Image.BICUBIC, expand=True)
    if corner_mode == "fill":
        return rotated                                  # keep the black corners

    wr, hr = _largest_inner_rect(img.width, img.height, degrees)
    wr, hr = int(wr), int(hr)
    if wr < 8 or hr < 8:
        return rotated
    cx, cy = rotated.width / 2, rotated.height / 2
    left, top = int(cx - wr / 2), int(cy - hr / 2)
    return rotated.crop((left, top, left + wr, top + hr))


def cap_long_side(img, max_side):
    """Shrink so the longer side is at most max_side. Never enlarges."""
    if max_side is None or max(img.width, img.height) <= max_side:
        return img
    scale = max_side / max(img.width, img.height)
    new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(new_size, Image.LANCZOS)


def list_images(folder):
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


# --------------------------------------------------------------------------
# subcommand: rename
# --------------------------------------------------------------------------

def cmd_rename(args):
    src, dst = Path(args.input).resolve(), Path(args.output).resolve()
    if not src.is_dir():
        sys.exit("ERROR: input folder not found: {}".format(src))
    dst.mkdir(parents=True, exist_ok=True)

    images = list_images(src)
    if not images:
        sys.exit("ERROR: no images in {}".format(src))

    print("\nrename: {}".format(src))
    print("    ->  {}".format(dst))
    print("    {} image(s), prefix '{}', long side <= {}px".format(
        len(images), args.prefix, args.max_side))

    rows = []
    for i, path in enumerate(images, start=1):
        with Image.open(path) as im:
            exif = im.getexif()
            orientation = exif.get(ORIENTATION_TAG) if exif else None
            orig_w, orig_h = im.width, im.height

            # exif_transpose physically rotates the pixels, then drops the tag
            # so nothing downstream rotates a second time.
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im = cap_long_side(im, args.max_side)

            out_name = "{}_{:04d}.jpg".format(args.prefix, i)
            im.save(dst / out_name, "JPEG", quality=args.quality,
                    optimize=True, subsampling=1)
            new_w, new_h = im.width, im.height

        rows.append({
            "new_filename": out_name,
            "original_filename": path.name,
            "exif_orientation": orientation if orientation else "none",
            "was_rotated": "yes" if orientation not in (None, 1) else "no",
            "orig_width": orig_w, "orig_height": orig_h,
            "new_width": new_w, "new_height": new_h,
        })

        if i % 50 == 0 or i == len(images):
            print("      {}/{}".format(i, len(images)))

    map_path = dst / "rename_map.csv"
    with open(map_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    rotated = sum(1 for r in rows if r["was_rotated"] == "yes")
    print("    done: {} written, {} physically rotated".format(len(rows), rotated))
    print("    trace file: {}".format(map_path))


# --------------------------------------------------------------------------
# subcommand: augment
# --------------------------------------------------------------------------

def load_severity_labels(labels_path):
    """
    Read severity_labels.csv into {image_stem: severity}.

    A missing file or a missing row is not fatal -- severity is written blank
    and can be backfilled later with update_manifest_severity.py, so training
    the disease classifier is never blocked waiting on hand-labelling.
    """
    if not labels_path:
        return {}
    p = Path(labels_path)
    if not p.exists():
        print("    NOTE: labels file not found ({}); severity left blank".format(p))
        return {}
    mapping = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row.get("image_id") or row.get("filename") or row.get("image")
            if key:
                mapping[Path(key).stem] = (row.get("severity") or "").strip()
    print("    severity labels loaded: {} row(s)".format(len(mapping)))
    return mapping


def cmd_augment(args):
    src, dst = Path(args.input).resolve(), Path(args.output).resolve()
    if not src.is_dir():
        sys.exit("ERROR: input folder not found: {}".format(src))
    dst.mkdir(parents=True, exist_ok=True)

    images = list_images(src)
    if not images:
        sys.exit("ERROR: no images in {}".format(src))

    severity_map = load_severity_labels(args.labels)
    geometries = [0] + ROTATIONS
    variants = 1 + len(ADJUSTMENTS)
    per_image = len(geometries) * variants

    print("\naugment: {}".format(src))
    print("     ->  {}".format(dst))
    print("    {} original(s) x {} = {} files".format(
        len(images), per_image, len(images) * per_image))
    print("    corner-mode={}  quality={}  max-side={}".format(
        args.corner_mode, args.quality, args.max_side or "unchanged"))

    rows = []
    for n, path in enumerate(images, start=1):
        stem = path.stem
        # Healthy plants have no disease severity; the CSV stores 'none'.
        default_sev = "none" if args.disease == "healthy" else ""
        severity = severity_map.get(stem, default_sev)

        with Image.open(path) as opened:
            base = opened.convert("RGB")

            for degrees in geometries:
                geo = rotate_image(base, degrees, args.corner_mode)
                geo = cap_long_side(geo, args.max_side)
                rot_tag = "" if degrees == 0 else "_rot{}".format(degrees)

                for code in [None] + list(ADJUSTMENTS.keys()):
                    out_img = geo if code is None else apply_adjustment(geo, code)
                    adj_tag = "" if code is None else "_{}".format(code)
                    out_name = "{}{}{}.jpg".format(stem, rot_tag, adj_tag)
                    out_img.save(dst / out_name, "JPEG",
                                 quality=args.quality, optimize=True, subsampling=1)

                    rows.append({
                        "image_id": Path(out_name).stem,
                        "image_path": (dst / out_name).as_posix(),
                        "disease": args.disease,
                        "plant_part": args.plant_part,
                        "severity": severity,
                        "source_image": path.name,
                        "rotation": degrees,
                        "adjustment": code or "none",
                        "is_original": "True" if (degrees == 0 and code is None) else "False",
                    })

        if n % 20 == 0 or n == len(images):
            print("      {}/{} originals  ({} files)".format(n, len(images), len(rows)))

    manifest = dst / "manifest_{}.csv".format(args.disease)
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("    done: {} files from {} originals".format(len(rows), len(images)))
    print("    manifest: {}".format(manifest))
    blank = sum(1 for r in rows if not r["severity"])
    if blank:
        print("    NOTE: {} row(s) have blank severity -> run "
              "update_manifest_severity.py after hand-labelling".format(blank))


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("rename", help="clean raw photos into processed/")
    r.add_argument("--input", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--prefix", required=True, help="e.g. Black_LS")
    r.add_argument("--max-side", type=int, default=1024)
    r.add_argument("--quality", type=int, default=92)
    r.set_defaults(func=cmd_rename)

    a = sub.add_parser("augment", help="expand a TRAIN folder 54x")
    a.add_argument("--input", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--disease", required=True,
                   help="class name, e.g. black_leaf_spot")
    a.add_argument("--plant-part", default="leaf")
    a.add_argument("--labels", default=None, help="path to severity_labels.csv")
    a.add_argument("--corner-mode", choices=["crop", "fill"], default="crop",
                   help="crop = remove black triangles from 45/225 rotations")
    a.add_argument("--max-side", type=int, default=None,
                   help="optionally shrink outputs to save disk (e.g. 512)")
    a.add_argument("--quality", type=int, default=88)
    a.set_defaults(func=cmd_augment)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
