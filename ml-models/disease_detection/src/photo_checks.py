"""
photo_checks.py -- can anyone judge this photograph at all?

Used on CONTRIBUTED photographs before they join the expert's review queue
(backend/app/services/disease_contributions.py). The expert's time is the scarce
resource, so a photograph too small, dark or blurred to judge is refused at the
door, with a reason the grower can act on, rather than after waiting in a queue.

Four checks, on the photograph after EXIF rotation and the 1024-pixel cap that
every stored photograph gets:

  too small    fewer pixels than the model's own 224 x 224 input. Counted as
               pixels rather than by the shorter side, because the dataset itself
               holds narrow crops of a single leaf only 162 pixels across.
  too dark     average brightness (0-255) under MIN_BRIGHTNESS
  washed out   average brightness over MAX_BRIGHTNESS
  blurred      sharpness under MIN_SHARPNESS. Sharpness is the variance of the
               Laplacian -- how sharply brightness changes from one pixel to the
               next -- measured at a fixed 512 pixels so a large photograph and
               a small one are judged alike. Blur softens every edge, which
               flattens the Laplacian and shrinks its variance.

The limits are MEASURED, not guessed. tools/measure_photo_checks.py runs these
same functions on all 667 photographs in the dataset and sets each limit beyond
the worst of them, so not one real photograph would have been refused. It then
blurs and darkens copies to show that bad photographs ARE caught. The numbers
and the evidence are in results/photo_checks/.

Two fingerprints are computed as well:

  sha256   the exact file. The same file sent twice is refused outright.
  dhash    a 64-bit "difference hash": shrink the picture to 9 x 8 grey pixels
           and record whether each pixel is brighter than its right-hand
           neighbour. Re-saving, resizing or recompressing a photograph barely
           changes those 64 answers, so two hashes only a few bits apart are
           very likely the same picture. Such pairs are flagged for the expert
           and counted once. A mirrored or re-shot photograph of the same leaf
           is NOT caught this way -- the expert remains the safeguard there.
"""

import hashlib
from io import BytesIO

import numpy as np

# Set from results/photo_checks/photo_check_thresholds.json. Re-run
# tools/measure_photo_checks.py if the dataset changes.
MIN_PIXELS = 224 * 224
MIN_BRIGHTNESS = 57      # darkest of the 667 real photographs: 77
MAX_BRIGHTNESS = 201     # brightest: 181
MIN_SHARPNESS = 17.7     # softest: 23.6; 75% of it, see the measuring script
COPY_DISTANCE = 12       # catches 99% of re-saved, resized, brightened or cropped copies

STORED_MAX_SIDE = 1024     # contributions are stored at the dataset's resolution
SHARPNESS_SIDE = 512


def open_image(data):
    """Bytes -> upright RGB PIL image. Raises on anything unreadable."""
    from PIL import Image, ImageOps
    img = Image.open(BytesIO(data))
    return ImageOps.exif_transpose(img).convert("RGB")


def cap_size(img, max_side=STORED_MAX_SIDE):
    """Shrink so the longer side is at most max_side. Never enlarges."""
    from PIL import Image
    if max(img.size) <= max_side:
        return img
    scale = max_side / max(img.size)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                      Image.LANCZOS)


def brightness(img):
    return float(np.asarray(img.convert("L"), dtype=np.float64).mean())


def sharpness(img):
    """Variance of the 4-neighbour Laplacian of a 512-pixel greyscale copy."""
    from PIL import Image
    g = img.convert("L")
    scale = SHARPNESS_SIDE / max(g.size)
    g = g.resize((max(3, round(g.width * scale)), max(3, round(g.height * scale))),
                 Image.BILINEAR)
    a = np.asarray(g, dtype=np.float64)
    lap = a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1]
    return float(lap.var())


def measure(img):
    return {"width": img.width, "height": img.height,
            "brightness": round(brightness(img), 1),
            "sharpness": round(sharpness(img), 1)}


def problems(m):
    """[(code, message)] for every check a measured photograph fails."""
    out = []
    if m["width"] * m["height"] < MIN_PIXELS:
        out.append(("too_small",
                    "The photo is only {} x {} pixels. Take it with the phone's camera "
                    "at full size.".format(m["width"], m["height"])))
    if MIN_BRIGHTNESS is not None and m["brightness"] < MIN_BRIGHTNESS:
        out.append(("too_dark",
                    "The photo is too dark to see the plant. Retake it in daylight "
                    "or bright shade."))
    if MAX_BRIGHTNESS is not None and m["brightness"] > MAX_BRIGHTNESS:
        out.append(("washed_out",
                    "The photo is washed out by glare. Retake it out of direct sun."))
    if MIN_SHARPNESS is not None and m["sharpness"] < MIN_SHARPNESS:
        out.append(("blurred",
                    "The photo is blurred. Hold the phone still, tap the affected "
                    "part to focus, and retake it."))
    return out


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def dhash(img, size=8):
    """64-bit difference hash as 16 hex characters."""
    from PIL import Image
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return "{:0{}x}".format(int("".join("1" if b else "0" for b in bits), 2), size * size // 4)


def distance(h1, h2):
    """How many of the 64 bits differ between two difference hashes."""
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")
