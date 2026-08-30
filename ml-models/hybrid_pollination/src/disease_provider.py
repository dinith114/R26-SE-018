"""
Hybrid Pollination - Disease Signal Provider

Turns `disease_visible` from a question the user answers into a value the
system measures from the image.

Why an interface rather than a direct call:
    Component 1 (Disease Detection) owns the real disease model, and it is not
    finished yet. Rather than block on it - or hard-code "no disease", which
    would make the demo dishonest - this module defines the CONTRACT both sides
    agree on, plus a self-contained fallback that works today.

    Swapping in the teammate's model later is a config change. No fusion,
    API or app code has to move.

Providers:
    HeuristicDiseaseProvider - OpenCV lesion detection, owned by this component
    RemoteDiseaseProvider    - calls Component 1's /api/v1/disease/detect
    NullDiseaseProvider      - reports "unknown", for ablation experiments

Selection is by the ORCHID_DISEASE_PROVIDER environment variable
("heuristic" | "remote" | "null"), defaulting to heuristic.
"""

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import segment_plant


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
# Severity above which the plant is reported as diseased. Calibrated against
# the annotated dataset by validate_disease_provider.py - do not tune by eye.
SEVERITY_THRESHOLD = 0.35

REMOTE_URL = os.environ.get(
    "ORCHID_DISEASE_URL", "http://localhost:8000/api/v1/disease/detect"
)
REMOTE_TIMEOUT = 10.0


# ──────────────────────────────────────────────
# The contract
# ──────────────────────────────────────────────
@dataclass
class DiseaseSignal:
    """
    What the pollination model needs to know about disease.

    Deliberately small: every provider must be able to fill it, including the
    heuristic one, which cannot name a pathogen. `disease_type` is therefore
    optional and never required by downstream fusion.
    """

    present: bool                     # Is disease detected at all
    severity: float                   # 0.0 (clean) to 1.0 (severe)
    confidence: float                 # How much to trust this reading, 0-1
    source: str                       # "heuristic" | "model" | "user" | "none"
    disease_type: str = "unknown"     # Named pathogen, when the provider knows one
    evidence: dict = field(default_factory=dict)   # Measurements behind the call

    @property
    def label(self) -> str:
        """The categorical value the legacy trait pipeline expects."""
        if self.source == "none":
            return "unknown"
        return "yes" if self.present else "no"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


class DiseaseProvider(ABC):
    """Any source of a disease reading for one plant image."""

    name = "abstract"

    @abstractmethod
    def analyze(self, image_path: str, image_kind: str = "plant") -> DiseaseSignal:
        """
        Return a DiseaseSignal for the plant in image_path.

        Args:
            image_path: Image to assess
            image_kind: "plant" (whole-plant frame) or "leaf_closeup".
                        Providers may use this to set confidence honestly.
        """
        raise NotImplementedError

    def is_available(self) -> bool:
        """Whether this provider can currently serve requests."""
        return True


# ──────────────────────────────────────────────
# Heuristic provider - lesion detection
# ──────────────────────────────────────────────
class HeuristicDiseaseProvider(DiseaseProvider):
    """
    Screening-only disease signal from classical CV. NOT a disease detector.

    MEASURED LIMITATION - read before trusting this class
    ------------------------------------------------------
    Validated on the 28 annotated plants with leave-one-plant-out CV
    (probe_disease_features.py, validate_disease_provider.py):

        best single measurement    AUC 0.70  - but that is best-of-40 on 28
                                               plants, i.e. selection bias
        multivariate, LOPO         AUC 0.51, accuracy 0.54
        majority-class baseline          accuracy 0.64

    In other words, on WHOLE-PLANT photographs this heuristic does not beat
    guessing. That is a property of the input, not a bug to tune away:

      - lesions are millimetres across, and these frames cover a whole plant
        from 1-2 m, so a lesion spans 1-3 px
      - the `disease_visible` annotation mixes true pathology with senescence;
        plant id13 is annotated diseased but shows withered spent flowers
      - 28 plants cannot validate any method
      - each plant was shot in one location, so background correlates with
        plant identity

    Consequently this provider reports LOW CONFIDENCE on whole-plant images and
    exists to keep the pipeline runnable and demonstrable, not to replace a
    real model. Disease belongs to Component 1 operating on LEAF CLOSE-UPS.
    Route real assessments through RemoteDiseaseProvider.

    What it can still legitimately flag is gross, large-area necrosis, which is
    visible even at this scale. Subtle spotting is beyond it.

    Measurements, all restricted to segmented plant pixels and all expressed
    RELATIVE to the plant's own leaf tone, so that the naturally yellow-green
    foliage of a healthy Vanda and per-photo exposure differences do not
    register as disease:
        dark_fraction  - tissue much darker than this plant's median
        lesion_count   - dark round spots inside leaf tissue
        necrosis       - dead dark tissue
    """

    name = "heuristic"

    # Whole-plant frames cannot resolve lesions, so confidence is capped well
    # below the level at which fusion will act on the reading unaided.
    MAX_CONFIDENCE_WHOLE_PLANT = 0.35
    MAX_CONFIDENCE_CLOSEUP = 0.60

    # Black-hat kernel: bigger than a lesion, smaller than a leaf
    LESION_KERNEL = 15
    LESION_CONTRAST = 18      # Minimum darkness below local leaf tone
    LESION_MIN_AREA = 6       # px, at the 512-long-side working resolution
    LESION_MAX_AREA = 900     # px, above this it is shadow or a gap, not a spot

    def analyze(self, image_path: str, image_kind: str = "plant") -> DiseaseSignal:
        """
        Args:
            image_path: Image to assess
            image_kind: "plant" for a whole-plant frame, "leaf_closeup" for a
                        single leaf filling the frame. Close-ups get a higher
                        confidence ceiling because lesions are resolvable.
        """
        seg = segment_plant(image_path)
        img = seg["image"]
        mask = seg["plant_mask"]

        leaf_area = int(cv2.countNonZero(mask))
        if leaf_area < 500:
            # Nothing recognisable as a plant - say so instead of guessing
            return DiseaseSignal(
                present=False, severity=0.0, confidence=0.0, source="none",
                evidence={"reason": "no plant segmented", "leaf_area": leaf_area},
            )

        lesions = self._detect_lesions(img, mask)
        dark_fraction = self._relative_dark_fraction(img, mask)
        necrosis = self._necrosis_ratio(img, mask)

        spot_rate = lesions["lesion_count"] / (leaf_area / 10000.0)  # per 100x100 px

        # Only gross damage is detectable at this scale, so severity is driven
        # by how much tissue is dead or much darker than the rest of the plant.
        # Spot count contributes little; the probe showed it is near chance.
        severity = float(np.clip(
            0.50 * min(dark_fraction / 0.12, 1.0)
            + 0.35 * min(necrosis / 0.20, 1.0)
            + 0.15 * min(spot_rate / 10.0, 1.0),
            0.0, 1.0,
        ))

        ceiling = (self.MAX_CONFIDENCE_CLOSEUP if image_kind == "leaf_closeup"
                   else self.MAX_CONFIDENCE_WHOLE_PLANT)

        # Trust the reading less when the frame is crowded with other plants,
        # because then some measured pixels may not belong to the subject.
        confidence = ceiling * float(np.clip(seg["isolation"], 0.0, 1.0))
        if seg["coverage"] < 0.08:
            confidence *= 0.6   # Plant is a small part of the frame

        return DiseaseSignal(
            present=severity >= SEVERITY_THRESHOLD,
            severity=round(severity, 4),
            confidence=round(confidence, 4),
            source="heuristic",
            disease_type="gross_necrosis" if severity >= SEVERITY_THRESHOLD else "none",
            evidence={
                "screening_only": True,
                "note": "Whole-plant CV cannot resolve lesions; see class docstring",
                "image_kind": image_kind,
                "lesion_count": lesions["lesion_count"],
                "spot_rate": round(spot_rate, 3),
                "dark_fraction": round(dark_fraction, 4),
                "necrosis_ratio": round(necrosis, 4),
                "leaf_area_px": leaf_area,
                "isolation": round(seg["isolation"], 3),
                "coverage": round(seg["coverage"], 3),
            },
        )

    # ── Measurements ──────────────────────────
    def _detect_lesions(self, img: np.ndarray, mask: np.ndarray) -> dict:
        """
        Find dark spots sitting inside leaf tissue.

        Black-hat morphology isolates features darker than their surroundings
        and smaller than the structuring element, which is exactly the shape of
        a leaf-spot lesion. Filtering by area and circularity then rejects the
        elongated shadows that fall between leaves.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (self.LESION_KERNEL, self.LESION_KERNEL)
        )
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)

        _, spots = cv2.threshold(blackhat, self.LESION_CONTRAST, 255, cv2.THRESH_BINARY)

        # Only spots on the plant itself count. Eroding the mask first keeps
        # the dark rim at the leaf edge from being counted as lesions.
        inner = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), iterations=1)
        spots = cv2.bitwise_and(spots, inner)

        spots = cv2.morphologyEx(
            spots, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        )

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            (spots > 0).astype(np.uint8), connectivity=8
        )

        count, total_area = 0, 0
        for lab in range(1, n_labels):
            area = stats[lab, cv2.CC_STAT_AREA]
            if not (self.LESION_MIN_AREA <= area <= self.LESION_MAX_AREA):
                continue

            w = stats[lab, cv2.CC_STAT_WIDTH]
            h = stats[lab, cv2.CC_STAT_HEIGHT]
            if w == 0 or h == 0:
                continue

            # Lesions are roughly round; shadows between leaves are long slivers
            elongation = max(w, h) / min(w, h)
            fill = area / float(w * h)
            if elongation > 4.0 or fill < 0.30:
                continue

            count += 1
            total_area += int(area)

        return {"lesion_count": count, "lesion_area": total_area}

    def _relative_dark_fraction(self, img: np.ndarray, mask: np.ndarray) -> float:
        """
        Fraction of leaf tissue much darker than THIS plant's own median.

        Measured relative rather than against a fixed threshold. An absolute
        yellow band was the original mistake: healthy Vanda foliage is
        naturally yellow-green under high light, so an absolute rule scored a
        healthy plant as 85% chlorotic.
        """
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        m = mask > 0
        if not np.any(m):
            return 0.0

        V = hsv[:, :, 2][m].astype(np.float32)
        return float((V < np.median(V) - 70).mean())

    def _necrosis_ratio(self, img: np.ndarray, mask: np.ndarray) -> float:
        """Fraction of leaf tissue that is dead - dark brown or blackened."""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        dark = cv2.inRange(hsv, np.array([0, 0, 0]), np.array([180, 255, 70]))
        brown = cv2.inRange(hsv, np.array([5, 50, 20]), np.array([22, 255, 130]))
        dead = cv2.bitwise_and(cv2.bitwise_or(dark, brown), mask)

        leaf_area = cv2.countNonZero(mask)
        return cv2.countNonZero(dead) / leaf_area if leaf_area else 0.0


# ──────────────────────────────────────────────
# Remote provider - Component 1's model
# ──────────────────────────────────────────────
class RemoteDiseaseProvider(DiseaseProvider):
    """
    Delegates to the Disease Detection component's API.

    Expected response shape (agree this with Component 1 before wiring up):
        {
          "disease_detected": bool,
          "disease_name":     str,
          "severity":         float,   # 0-1, optional
          "confidence":       float    # 0-1
        }

    Any deviation is absorbed by _parse so that a change on their side degrades
    to a low-confidence reading rather than crashing the assessment.
    """

    name = "remote"

    def __init__(self, url: str = REMOTE_URL, timeout: float = REMOTE_TIMEOUT,
                 fallback: DiseaseProvider = None):
        self.url = url
        self.timeout = timeout
        # If their service is down mid-demo, fall back rather than fail
        self.fallback = fallback or HeuristicDiseaseProvider()

    def is_available(self) -> bool:
        try:
            import requests
            r = requests.get(self.url.replace("/detect", "/health"), timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def analyze(self, image_path: str, image_kind: str = "plant") -> DiseaseSignal:
        try:
            import requests
            with open(image_path, "rb") as f:
                r = requests.post(
                    self.url, files={"image": (os.path.basename(image_path), f)},
                    timeout=self.timeout,
                )
            r.raise_for_status()
            return self._parse(r.json())
        except Exception as e:
            signal = self.fallback.analyze(image_path, image_kind)
            signal.evidence["remote_error"] = str(e)
            signal.evidence["fell_back_from"] = "remote"
            signal.confidence *= 0.9
            return signal

    def _parse(self, payload: dict) -> DiseaseSignal:
        present = bool(payload.get("disease_detected", payload.get("present", False)))
        severity = float(payload.get("severity", 1.0 if present else 0.0))
        confidence = float(payload.get("confidence", 0.5))

        return DiseaseSignal(
            present=present,
            severity=round(min(max(severity, 0.0), 1.0), 4),
            confidence=round(min(max(confidence, 0.0), 1.0), 4),
            source="model",
            disease_type=str(payload.get("disease_name", payload.get("disease_type", "unknown"))),
            evidence={"raw_response": payload},
        )


# ──────────────────────────────────────────────
# Null provider - for ablation studies
# ──────────────────────────────────────────────
class NullDiseaseProvider(DiseaseProvider):
    """Reports nothing. Used to measure how much the disease signal contributes."""

    name = "null"

    def analyze(self, image_path: str, image_kind: str = "plant") -> DiseaseSignal:
        return DiseaseSignal(
            present=False, severity=0.0, confidence=0.0, source="none",
            evidence={"reason": "disease provider disabled"},
        )


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────
_PROVIDERS = {
    "heuristic": HeuristicDiseaseProvider,
    "remote": RemoteDiseaseProvider,
    "null": NullDiseaseProvider,
}

_cached = {}


def get_disease_provider(name: str = None) -> DiseaseProvider:
    """
    Return the configured disease provider.

    Args:
        name: "heuristic", "remote" or "null". Defaults to the
              ORCHID_DISEASE_PROVIDER environment variable, then "heuristic".
    """
    if name is None:
        name = os.environ.get("ORCHID_DISEASE_PROVIDER", "heuristic")
    name = name.strip().lower()

    if name not in _PROVIDERS:
        print(f"[WARN] Unknown disease provider '{name}' - using heuristic")
        name = "heuristic"

    if name not in _cached:
        _cached[name] = _PROVIDERS[name]()

    return _cached[name]


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the disease provider on one image")
    parser.add_argument("--image", required=True)
    parser.add_argument("--provider", default=None, choices=list(_PROVIDERS))
    args = parser.parse_args()

    provider = get_disease_provider(args.provider)
    signal = provider.analyze(args.image)

    print(f"\nProvider : {provider.name}")
    print(f"Disease  : {signal.label}  (severity {signal.severity:.2f})")
    print(f"Confidence: {signal.confidence:.2f}")
    print(f"Source   : {signal.source}")
    print("Evidence :")
    for k, v in signal.evidence.items():
        print(f"   {k}: {v}")
