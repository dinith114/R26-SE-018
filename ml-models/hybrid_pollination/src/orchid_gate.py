"""
Hybrid Pollination - Input Validation Gate

Decides whether an uploaded photograph actually shows an orchid plant, before
any suitability assessment is allowed to run.

WHY THIS EXISTS
---------------
A photograph of a laptop screen was uploaded during testing and came back as
"Suitable, 98.7% confidence". That is not a bug in the suitability model; it is
the model working exactly as trained. It has three output classes - Suitable,
Moderate, Not Suitable - and every input is forced onto one of them. It was
never shown anything that was not an orchid, so it has no way to answer
"this is not a plant". The gate supplies that missing answer.

WHY IT IS FITTED ON POSITIVES ONLY
----------------------------------
The obvious alternative is a two-class orchid/not-orchid classifier. That needs
a negative set, and any negative set assembled quickly differs from this
project's photographs in camera, resolution, compression and lighting. The
classifier would learn THAT difference rather than the subject - a shortcut -
and would then happily pass a laptop photo taken on the same phone as the
orchids. This is the same failure already recorded for the flower model, which
reached 0.999 accuracy on cutouts and then answered "flower" for every real
nursery photograph.

So the gate is fitted on the project's own photographs and nothing else. No
negative influences the boundary. Downloaded negatives are used only to MEASURE
the result, never to fit it.

WHY NOT A LIST OF IMAGENET PLANT CLASSES
----------------------------------------
This was measured before being rejected. ResNet18's own ImageNet head
classifies these Vanda plants as "sea anemone" with p=0.89 - the strap leaves
read as tentacles. Plant classes barely appear. A hand-picked class list would
reject the real orchids, so the 1000-way head is discarded and the 512-d
embedding beneath it is used instead: it carries the visual signature without
depending on ImageNet having a label for what we are looking at.

WHY NEAREST NEIGHBOURS AND NOT A DISTANCE TO THE CENTRE
-------------------------------------------------------
The first version measured Mahalanobis distance from the mean of the project's
photographs. Under grouped cross-validation it refused 62.9% of genuine orchid
photographs - unusable. The reason is that these photographs are not one blob.
Whole plants, bloom close-ups and name-tag shots form three visually different
populations, and the mean of the three sits in the empty space between them, so
real photographs are far from it and the threshold has to be opened so wide it
stops refusing anything.

Measured on the same grouped splits (false refusals of real orchid photographs,
share of known non-orchids refused):

    mahalanobis, raw            62.9%  refused    100% of negatives
    mahalanobis, L2 normalised  75.7%  refused    100%
    k-NN k=1,  cosine           98.7%  refused    100%   (degenerate)
    k-NN k=5,  cosine            1.3%  refused    100%
    k-NN k=10, cosine            1.1%  refused    100%   <- chosen

k=1 fails for the opposite reason: near-duplicate frames of the same plant sit
almost on top of each other, so the training distances are near zero and the
threshold collapses. k=10 asks a stable question - "are there ten photographs in
the reference set that look like this one?" - which a new plant can satisfy
while a laptop cannot.

WHAT THIS GATE DOES AND DOES NOT DO
-----------------------------------
Measured on 543 held-out images. It refuses every non-plant photograph tested -
laptops, screens, cars, rooms, people, food, documents, 265 images, 100% - which
is the failure it was built for, and it does so at every threshold setting. It
mostly refuses other foliage (ferns 90%, houseplants 71%).

It does NOT reliably separate an orchid bloom from another flower: 73% of rose,
tulip and sunflower photographs were accepted. 300 of the 1190 reference
photographs are bloom close-ups, and in this feature space a rose close-up sits
very near an orchid close-up. Tightening the threshold was measured and does not
fix it - at keep_fraction 0.90 the flower refusal rate only reaches 64% while
12.2% of genuine photographs start being refused.

So this is an out-of-domain filter, not a species classifier. Treating it as the
latter would be overclaiming.

TWO SIGNALS
-----------
1. Embedding novelty - cosine distance to the 10th nearest of the project's own
   photographs in ResNet18's 512-d space. This is the decisive signal.
2. Vegetation fraction - share of the frame that is green by the ExG + HSV test
   from segmentation.py. Not decisive on its own (a lawn would pass), but it is
   cheap and it is the part a person can check by eye, which matters when the
   app has to explain a refusal to a grower.
"""

import os
import pickle
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import resize_long_side, vegetation_mask

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
INPUT_SIZE = 224

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_PATH = os.path.join(BASE_DIR, "models", "orchid_gate.pkl")

# A frame with almost no vegetation is reported as such in the explanation.
# It does not by itself reject - see check_image() - because a tight flower
# close-up can be mostly petal and very little leaf.
LOW_VEGETATION = 0.02

_model = None
_torch = None


def _load_model():
    """ResNet18 with the 1000-class head removed. Loaded once."""
    global _model, _torch
    if _model is not None:
        return _model, _torch

    import torch
    import torchvision

    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
    weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
    net = torchvision.models.resnet18(weights=weights)
    net.fc = torch.nn.Identity()
    net.eval()

    _model, _torch = net, torch
    return _model, _torch


def read_image(image_path):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Could not read image: " + str(image_path))
    return img


def embed(image_paths, batch_size=16, verbose=False):
    """
    Embed images WITHOUT masking and WITHOUT segmentation.

    The gate asks "is this a photograph of an orchid plant", which is a question
    about the whole frame. Masking to the plant first would answer a different
    question - and on a laptop photo the mask is empty, so masking would hand
    the network a flat grey square and throw the evidence away.

    Returns:
        (n_images, 512) float32. Rows for unreadable images stay zero.
    """
    net, torch = _load_model()
    out = np.zeros((len(image_paths), 512), dtype=np.float32)

    for start in range(0, len(image_paths), batch_size):
        chunk = image_paths[start:start + batch_size]
        if verbose and start % (batch_size * 8) == 0:
            print("  embedding {}/{}".format(start, len(image_paths)))

        tensors, rows = [], []
        for i, path in enumerate(chunk):
            try:
                img = read_image(path)
                img = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE),
                                 interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD
                tensors.append(np.transpose(rgb, (2, 0, 1)))
                rows.append(start + i)
            except Exception:
                continue

        if not tensors:
            continue

        batch = torch.from_numpy(np.stack(tensors))
        with torch.no_grad():
            embeddings = net(batch).numpy()
        for row, emb in zip(rows, embeddings):
            out[row] = emb

    return out


def vegetation_fraction(img):
    """
    Share of the frame that reads as living plant tissue.

    Uses the cheap ExG + HSV test only - no GrabCut - so this adds a few
    milliseconds rather than half a second to every upload.
    """
    small = resize_long_side(img)
    veg = vegetation_mask(small)
    return float(cv2.countNonZero(veg)) / float(veg.size)


K_NEIGHBOURS = 10


def _l2_normalise(X):
    """Project onto the unit sphere so distance means angle, not magnitude."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.maximum(norms, 1e-9)


class OrchidGate:
    """
    One-class novelty detector over the project's own photographs.

    Scores an image by its cosine distance to the k-th nearest reference
    photograph. See the module docstring for the measurements that ruled out
    distance-to-centre and k=1.
    """

    def __init__(self, k=K_NEIGHBOURS):
        self.k = k
        self.reference = None        # L2-normalised training embeddings
        self.threshold = None
        self.train_percentiles = {}
        self.n_train = 0

    # ---------------------------------------------------------------- fitting

    def fit(self, X, keep_fraction=0.99):
        """
        Fit on positives only.

        `keep_fraction` is the share of genuine orchid photographs that must
        still pass. It is 0.99 rather than 1.0 deliberately: the project's own
        set contains a few odd frames (a hand holding a name tag, a shot of
        mostly sky between leaves) and pinning the threshold to the single worst
        of them would push the boundary out until the gate stopped refusing
        anything.
        """
        self.reference = _l2_normalise(X)
        self.n_train = int(self.reference.shape[0])

        d = self._knn_distance(self.reference)
        self.threshold = float(np.quantile(d, keep_fraction))
        self.train_percentiles = {
            "p50": float(np.percentile(d, 50)),
            "p90": float(np.percentile(d, 90)),
            "p99": float(np.percentile(d, 99)),
            "max": float(d.max()),
        }
        return self

    def _knn_distance(self, Xn):
        """
        Cosine distance to the k-th nearest reference photograph.

        Computed as a dot product because both sides are unit vectors, which
        keeps a single lookup at a few milliseconds even with the whole
        reference set in memory.
        """
        sim = Xn @ self.reference.T                    # cosine similarity
        k = min(self.k, sim.shape[1])
        # k largest similarities => k smallest distances; take the k-th
        kth = np.partition(sim, -k, axis=1)[:, -k]
        return 1.0 - kth

    # -------------------------------------------------------------- inference

    def distances(self, X):
        return self._knn_distance(_l2_normalise(X))

    def check_embedding(self, emb):
        d = float(self.distances(np.asarray(emb).reshape(1, -1))[0])
        return {
            "distance": d,
            "threshold": float(self.threshold),
            "is_orchid": bool(d <= self.threshold),
        }

    # ------------------------------------------------------------ persistence

    def save(self, path=BUNDLE_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({
                "k": self.k,
                "reference": self.reference,
                "threshold": self.threshold,
                "train_percentiles": self.train_percentiles,
                "n_train": self.n_train,
            }, f)
        return path

    @classmethod
    def load(cls, path=BUNDLE_PATH):
        with open(path, "rb") as f:
            d = pickle.load(f)
        g = cls(k=d.get("k", K_NEIGHBOURS))
        g.reference = d["reference"]
        g.threshold = d["threshold"]
        g.train_percentiles = d.get("train_percentiles", {})
        g.n_train = d.get("n_train", 0)
        return g


_gate = None


def get_gate():
    """Load the fitted gate once. None if it has not been built yet."""
    global _gate
    if _gate is None and os.path.exists(BUNDLE_PATH):
        _gate = OrchidGate.load()
    return _gate


def check_image(image_path):
    """
    Decide whether one uploaded photograph may proceed to assessment.

    Returns `is_orchid`, the two measured signals, and a `message` written for
    the grower rather than for a developer. When the gate has not been built the
    image is allowed through and `gate_available` is False, so a missing model
    file degrades to the previous behaviour instead of blocking the whole app.
    """
    gate = get_gate()
    if gate is None:
        return {
            "is_orchid": True,
            "gate_available": False,
            "message": "Input validation is not available on this server.",
        }

    try:
        img = read_image(image_path)
    except Exception as e:
        return {
            "is_orchid": False,
            "gate_available": True,
            "distance": None,
            "vegetation": None,
            "confidence": 1.0,
            "message": "That file could not be read as an image. ({})".format(e),
        }

    veg = vegetation_fraction(img)
    emb = embed([image_path], verbose=False)[0]
    verdict = gate.check_embedding(emb)

    d = verdict["distance"]
    thr = verdict["threshold"]
    is_orchid = verdict["is_orchid"]

    # Stage 2 - only asked of images that already passed the novelty check, and
    # only to answer the one question stage 1 cannot: orchid, or some other
    # flower? Absent bundle means stage 1 alone, which is the previous
    # behaviour rather than a failure. See flower_filter.py.
    flower_probability = None
    if is_orchid:
        try:
            from flower_filter import get_filter
            ff = get_filter()
            if ff is not None:
                second = ff.check_embedding(emb)
                flower_probability = round(second["orchid_probability"], 3)
                if not second["is_orchid"]:
                    is_orchid = False
                    return {
                        "is_orchid": False,
                        "gate_available": True,
                        "distance": round(d, 2),
                        "threshold": round(thr, 2),
                        "vegetation": round(veg, 4),
                        "orchid_probability": flower_probability,
                        "confidence": round(1.0 - flower_probability, 3),
                        "message": ("This looks like a flower, but not an orchid. "
                                    "This system assesses Vanda orchids only."),
                    }
        except Exception as e:
            print("[WARN] flower filter unavailable: {}".format(e))

    # How far past the threshold, squashed to 0-1 so the app can show a number.
    over = max(0.0, (d - thr) / max(thr, 1e-6))
    confidence = 0.0 if is_orchid else float(min(0.99, over / (over + 0.5)))

    # How ordinary this photograph is for the reference collection, separate
    # from whether it is admitted at all.
    #
    # This exists because of a measured failure. All 58 internet orchid
    # photographs that passed the gate were assessed "Suitable" at a median
    # confidence of 0.99 - not one Moderate, not one Not Suitable. The
    # suitability model is not broken: under grouped CV on this nursery's own
    # plants it recalls 99% of Not Suitable images. It is extrapolating, and
    # sounding certain while doing it.
    #
    # The p90 of the training distances separates the two populations usefully:
    # 10% of the project's own photographs sit above it, against 61% of the
    # internet orchids that passed. A photograph above that line still gets a
    # verdict, but the app is told the verdict is on thinner evidence.
    typical_limit = float(gate.train_percentiles.get("p90", thr))
    familiarity = "typical" if d <= typical_limit else "unusual"

    if is_orchid:
        message = ("Orchid plant recognised." if familiarity == "typical" else
                   "Orchid recognised, but this photograph is unlike the "
                   "reference collection - the verdict rests on weaker evidence.")
    elif veg < LOW_VEGETATION:
        message = ("This does not look like an orchid plant. Almost none of the "
                   "frame is plant tissue. Please photograph the plant itself.")
    else:
        message = ("This does not look like an orchid plant. There is greenery "
                   "in the frame, but it does not match the orchids this system "
                   "was built on. Please photograph a single Vanda plant.")

    return {
        "is_orchid": is_orchid,
        "gate_available": True,
        "distance": round(d, 2),
        "threshold": round(thr, 2),
        "vegetation": round(veg, 4),
        "orchid_probability": flower_probability,
        "familiarity": familiarity,
        "typical_limit": round(typical_limit, 3),
        "confidence": round(confidence, 3),
        "message": message,
    }


if __name__ == "__main__":
    import glob

    g = get_gate()
    if g is None:
        print("Gate not built yet. Run: python src/train_orchid_gate.py")
        raise SystemExit(1)

    print("Gate fitted on {} photographs, threshold {:.2f}".format(
        g.n_train, g.threshold))
    sample = sorted(glob.glob(os.path.join(
        BASE_DIR, "data", "images", "plants", "*.jpg")))[:3]
    for p in sample:
        print(os.path.basename(p), check_image(p))
