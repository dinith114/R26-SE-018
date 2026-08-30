"""
Hybrid Pollination - Stage 2 of the input gate: orchid or some other flower?

WHY A SECOND STAGE
------------------
The novelty gate in orchid_gate.py refuses every non-plant photograph tested -
laptops, screens, desks, rooms, people, 265 images, 100%. It does not separate
an orchid bloom from a rose bloom: 73% of rose, tulip and sunflower photographs
were accepted. 300 of the 1190 reference photographs are bloom close-ups, and in
ResNet's feature space a rose close-up sits very near an orchid close-up.

Tightening the novelty threshold was measured and does not fix it - at
keep_fraction 0.90 the flower refusal rate only reaches 64% while 12.2% of
genuine photographs start being refused. Separating orchid from rose is a
different question from "is this in the reference distribution", so it gets its
own model rather than a tuned threshold.

WHY IT IS SAFE TO TRAIN THIS ONE ON NEGATIVES
---------------------------------------------
orchid_gate.py is deliberately fitted on positives only, because a hastily
assembled negative set differs from this project's photographs in camera and
lighting, and a classifier would learn THAT instead of the subject.

That objection is answered here rather than ignored:

  * The negatives are Oxford Flowers-102 - 8089 photographs across 100 flower
    species, a published dataset, not a scrape. Its two orchid classes
    (hard-leaved pocket orchid, moon orchid) are excluded from the negatives
    rather than deleted, because training the filter to call an orchid "not an
    orchid" would break the stage it sits behind.

  * The decisive test uses a THIRD source. Training positives are this project's
    nursery photographs and training negatives are Oxford's; the reported score
    is measured on Wikimedia Commons orchids versus Wikimedia Commons roses,
    tulips and sunflowers - images from neither training source. A model that
    had learned "phone photo versus Oxford photo" cannot separate two sets that
    both come from Wikimedia. See results/flower_filter.txt for the numbers.
"""

import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_PATH = os.path.join(BASE_DIR, "models", "flower_filter.pkl")


def _l2_normalise(X):
    X = np.asarray(X, dtype=np.float32)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    return X / np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)


class FlowerFilter:
    """Binary orchid / other-flower classifier over ResNet18 embeddings."""

    def __init__(self):
        self.model = None
        self.threshold = 0.5
        self.metrics = {}

    def fit(self, X_orchid, X_other, keep_fraction=0.99, groups=None):
        """
        `keep_fraction` is the share of the project's own photographs that must
        still be called orchid. The refusal threshold is read off their score
        distribution rather than left at 0.5, so the filter cannot start
        rejecting the growers' own plants to win accuracy on roses.
        """
        from sklearn.linear_model import LogisticRegression

        X = np.vstack([_l2_normalise(X_orchid), _l2_normalise(X_other)])
        y = np.concatenate([np.ones(len(X_orchid)), np.zeros(len(X_other))])

        # Balanced weights: 1190 orchids against 8089 other flowers would
        # otherwise be solved by answering "other flower" almost always.
        self.model = LogisticRegression(
            max_iter=2000, class_weight="balanced", C=1.0
        ).fit(X, y)

        p_orchid = self.model.predict_proba(_l2_normalise(X_orchid))[:, 1]
        self.threshold = float(np.quantile(p_orchid, 1.0 - keep_fraction))
        return self

    def orchid_probability(self, X):
        return self.model.predict_proba(_l2_normalise(X))[:, 1]

    def check_embedding(self, emb):
        p = float(self.orchid_probability(np.asarray(emb).reshape(1, -1))[0])
        return {
            "orchid_probability": p,
            "threshold": float(self.threshold),
            "is_orchid": bool(p >= self.threshold),
        }

    def save(self, path=BUNDLE_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "threshold": self.threshold,
                         "metrics": self.metrics}, f)
        return path

    @classmethod
    def load(cls, path=BUNDLE_PATH):
        with open(path, "rb") as f:
            d = pickle.load(f)
        f2 = cls()
        f2.model = d["model"]
        f2.threshold = d["threshold"]
        f2.metrics = d.get("metrics", {})
        return f2


_filter = None


def get_filter():
    """Load the fitted filter once. None if it has not been built."""
    global _filter
    if _filter is None and os.path.exists(BUNDLE_PATH):
        _filter = FlowerFilter.load()
    return _filter
