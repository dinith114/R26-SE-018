"""
Hybrid Pollination - Trait Resolution Layer

This module is the direct answer to the review comment:

    "is it necessary to get user inputs, like disease, with the uploaded
     image to predict the pollination? need to think of how to get the
     prediction"

The answer implemented here is: no, user input is not a precondition. Every
trait is MEASURED from the image first. The user is asked only when the
measurement is too uncertain to act on, and any answer they do give is treated
as a correction to a stated estimate rather than as raw input.

Resolution order for each trait:

    1. measured  - a provider read it from the image with enough confidence
    2. user      - the user supplied or corrected the value
    3. unknown   - neither is available; downstream must handle it

The important property is that the system always states what it believes and
how sure it is BEFORE the user answers. That is what separates this from a
data-entry form: the user is reviewing a judgement, not making one.

Honest caveat carried through in code:
    The disease heuristic scores AUC 0.52 on whole-plant frames (see
    HeuristicDiseaseProvider). Its confidence is capped below the acting
    threshold on purpose, so on whole-plant photos disease resolution will
    normally REQUEST a leaf close-up or a user answer instead of asserting
    one. Suppressing that request would be pretending to a capability the
    measurements do not support.
"""

import os
import sys
from dataclasses import dataclass, field, asdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from disease_provider import get_disease_provider, DiseaseSignal


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
# Confidence at or above which a measurement is acted on without asking.
ACT_THRESHOLD = 0.55

# Confidence below which the measurement is not even shown as a suggestion.
SUGGEST_THRESHOLD = 0.20


# ──────────────────────────────────────────────
# Result types
# ──────────────────────────────────────────────
@dataclass
class ResolvedTrait:
    """
    One trait, plus the story of where its value came from.

    `explanation` exists so the app can show the reasoning to a grower. A
    breeder will not trust "Not Suitable" on its own, but will engage with
    "3.1% of leaf tissue is necrotic".
    """

    name: str
    value: str
    source: str                # "measured" | "user" | "unknown"
    confidence: float
    explanation: str = ""
    needs_user_input: bool = False   # Measurement too weak - ask the grower
    suggested_value: str = ""        # What the system would guess if forced
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResolutionReport:
    """All traits for one plant, plus what the app still needs to ask about."""

    traits: dict                      # name -> ResolvedTrait
    asked_for: list = field(default_factory=list)   # Traits needing user input

    def values(self) -> dict:
        """Plain name -> value dict, for the legacy trait pipeline."""
        return {n: t.value for n, t in self.traits.items()}

    def to_dict(self) -> dict:
        return {
            "traits": {n: t.to_dict() for n, t in self.traits.items()},
            "asked_for": self.asked_for,
            "fully_automatic": len(self.asked_for) == 0,
        }


# ──────────────────────────────────────────────
# Resolver
# ──────────────────────────────────────────────
class TraitResolver:
    """
    Resolves plant traits from an image, falling back to the user only when
    the image cannot answer with enough confidence.

    All four traits are now read from the photograph:

        disease_visible   disease_provider.py  (whole-plant frames cannot
                          answer this - it asks for a leaf close-up instead)
        leaf_condition    trained model, Random Forest on 549 features
        plant_strength    trained model, Extra Trees on 512 CNN features
        flower_condition  flower_analysis.py, plus maturity_analysis.py so a
                          plant with no bloom is told when to come back

    Nothing here is a required user input. Every value is stated with its
    source and its confidence first; the grower corrects it only if they
    disagree.
    """

    MODEL_TRAITS = ("leaf_condition", "plant_strength")

    def __init__(self, disease_provider=None, trait_predictor=None):
        self.disease_provider = disease_provider or get_disease_provider()

        if trait_predictor is not None:
            self.trait_predictor = trait_predictor
        else:
            try:
                from trait_predictor import get_trait_predictor
                self.trait_predictor = get_trait_predictor()
            except Exception as e:
                print(f"[WARN] Trait models unavailable: {e}")
                self.trait_predictor = None

    # ── Disease ───────────────────────────────
    def resolve_disease(
        self,
        image_path: str,
        image_kind: str = "plant",
        user_value: str = None,
    ) -> ResolvedTrait:
        """
        Resolve `disease_visible` for one plant.

        Args:
            image_path: Plant image, or a leaf close-up
            image_kind: "plant" or "leaf_closeup"
            user_value: "yes"/"no" if the grower has already answered

        Returns:
            ResolvedTrait. When needs_user_input is True the caller should
            prompt, ideally by requesting a leaf close-up first.
        """
        signal: DiseaseSignal = self.disease_provider.analyze(image_path, image_kind)

        # An explicit user answer wins. The measurement is still reported, so
        # that disagreements can be logged and used as retraining data later.
        if user_value in ("yes", "no"):
            # Only counts as a real disagreement when the measurement was
            # confident enough to have an opinion in the first place.
            agrees = None
            if signal.confidence >= SUGGEST_THRESHOLD:
                agrees = signal.label == user_value

            return ResolvedTrait(
                name="disease_visible",
                value=user_value,
                source="user",
                confidence=1.0,
                explanation=self._disease_explanation(
                    signal, user_confirmed=user_value, agrees=agrees
                ),
                suggested_value=signal.label,
                evidence={**signal.evidence,
                          "measured_value": signal.label,
                          "measured_confidence": signal.confidence,
                          "agrees_with_user": agrees},
            )

        if signal.confidence >= ACT_THRESHOLD:
            return ResolvedTrait(
                name="disease_visible",
                value=signal.label,
                source="measured",
                confidence=signal.confidence,
                explanation=self._disease_explanation(signal),
                evidence=signal.evidence,
            )

        # Not confident enough to assert. Say so rather than guessing.
        suggested = signal.label if signal.confidence >= SUGGEST_THRESHOLD else ""
        return ResolvedTrait(
            name="disease_visible",
            value="unknown",
            source="unknown",
            confidence=signal.confidence,
            explanation=self._low_confidence_explanation(signal, image_kind),
            needs_user_input=True,
            suggested_value=suggested,
            evidence=signal.evidence,
        )

    def _disease_explanation(self, signal: DiseaseSignal, user_confirmed: str = None,
                             agrees: bool = None) -> str:
        ev = signal.evidence
        bits = []

        if "necrosis_ratio" in ev:
            bits.append(f"{ev['necrosis_ratio'] * 100:.1f}% of leaf tissue reads as dead")
        if "dark_fraction" in ev:
            bits.append(f"{ev['dark_fraction'] * 100:.1f}% much darker than the plant's own tone")
        if ev.get("lesion_count"):
            bits.append(f"{ev['lesion_count']} dark spots detected on leaf tissue")

        measurement = "; ".join(bits) if bits else "no measurable damage"

        if user_confirmed is not None:
            if agrees is None:
                # Too uncertain to have had an opinion - do not imply one either way
                return (f"You reported disease: {user_confirmed}. Image analysis was "
                        f"inconclusive, so your answer was used.")
            if agrees is False:
                return (f"You reported disease: {user_confirmed}. Image analysis suggested "
                        f"'{signal.label}' ({measurement}). Your answer was used.")
            return f"You reported disease: {user_confirmed}. Image analysis agrees ({measurement})."

        if signal.source == "model":
            name = signal.disease_type
            return (f"Disease model reports {'disease detected' if signal.present else 'no disease'}"
                    + (f" ({name})" if name not in ("unknown", "none") else "")
                    + f", confidence {signal.confidence:.0%}.")

        return f"Measured from image: {measurement}."

    def _low_confidence_explanation(self, signal: DiseaseSignal, image_kind: str) -> str:
        if signal.source == "none":
            return ("No plant could be isolated in this image, so disease could not be "
                    "assessed. Try a photo with the plant filling more of the frame.")

        if image_kind != "leaf_closeup":
            return (
                "Disease cannot be judged reliably from a whole-plant photo - lesions are "
                "only a few pixels at this distance. Add a close-up of a single leaf, or "
                "confirm the plant's disease status yourself."
            )

        return (
            f"Image evidence was inconclusive (confidence {signal.confidence:.0%}). "
            "Please confirm whether disease is visible."
        )

    # ── Model-predicted traits ────────────────
    def resolve_model_trait(self, image_path: str, trait: str,
                            user_value: str = None) -> ResolvedTrait:
        """
        Resolve a trait that has a trained image model behind it.

        Same contract as disease: measure first, act only when confident
        enough, and treat a user answer as a correction to a stated estimate.
        """
        if self.trait_predictor is None:
            return ResolvedTrait(
                name=trait,
                value=user_value or "unknown",
                source="user" if user_value else "unknown",
                confidence=1.0 if user_value else 0.0,
                explanation="Trait models are not loaded. Run train_traits.py.",
                needs_user_input=not user_value,
            )

        prediction = self.trait_predictor.predict(image_path, trait)
        measured = prediction["value"]
        confidence = prediction["confidence"]

        if user_value:
            agrees = None
            if confidence >= SUGGEST_THRESHOLD and measured != "unknown":
                agrees = measured == user_value

            if agrees is False:
                explanation = (f"You reported {trait.replace('_', ' ')}: {user_value}. "
                               f"Image analysis suggested '{measured}'. Your answer was used.")
            elif agrees is True:
                explanation = (f"You reported {trait.replace('_', ' ')}: {user_value}. "
                               f"Image analysis agrees.")
            else:
                explanation = (f"You reported {trait.replace('_', ' ')}: {user_value}. "
                               f"Image analysis was inconclusive, so your answer was used.")

            return ResolvedTrait(
                name=trait, value=user_value, source="user", confidence=1.0,
                explanation=explanation, suggested_value=measured,
                evidence={"measured_value": measured,
                          "measured_confidence": confidence,
                          "agrees_with_user": agrees,
                          "probabilities": prediction["probabilities"],
                          **prediction["model_info"]},
            )

        if confidence >= ACT_THRESHOLD:
            return ResolvedTrait(
                name=trait, value=measured, source="measured",
                confidence=confidence, explanation=prediction["explanation"],
                evidence={"probabilities": prediction["probabilities"],
                          **prediction["model_info"]},
            )

        # Below the acting threshold but still a real prediction.
        #
        # The value is REPORTED rather than replaced with "unknown", and flagged
        # for confirmation. Hiding a genuine estimate behind "unknown" would be
        # its own kind of dishonesty: the system does have an opinion, it simply
        # is not certain, and the grower is better served by seeing the estimate
        # with its confidence than by being asked a bare question.
        if confidence >= SUGGEST_THRESHOLD and measured != "unknown":
            return ResolvedTrait(
                name=trait, value=measured, source="measured",
                confidence=confidence, explanation=prediction["explanation"],
                needs_user_input=True,          # means "please confirm"
                suggested_value=measured,
                evidence={"probabilities": prediction["probabilities"],
                          **prediction["model_info"]},
            )

        # Too weak to even suggest
        return ResolvedTrait(
            name=trait, value="unknown", source="unknown", confidence=confidence,
            explanation=prediction["explanation"],
            needs_user_input=True,
            evidence={"probabilities": prediction["probabilities"],
                      **prediction["model_info"]},
        )

    # ── Full resolution ───────────────────────
    def resolve(
        self,
        image_path: str,
        leaf_closeup_path: str = None,
        user_traits: dict = None,
    ) -> ResolutionReport:
        """
        Resolve every trait for one plant.

        Args:
            image_path:        Whole-plant image (required)
            leaf_closeup_path: Optional leaf close-up. When present it is used
                               for disease, because that is the framing disease
                               assessment actually needs.
            user_traits:       Any values the grower has already supplied

        Returns:
            ResolutionReport
        """
        user_traits = user_traits or {}
        traits, asked = {}, []

        disease_img = leaf_closeup_path or image_path
        disease_kind = "leaf_closeup" if leaf_closeup_path else "plant"

        disease = self.resolve_disease(
            disease_img, disease_kind,
            user_value=self._clean(user_traits.get("disease_visible")),
        )
        traits["disease_visible"] = disease
        if disease.needs_user_input:
            asked.append("disease_visible")

        # Model-predicted traits
        for name in self.MODEL_TRAITS:
            trait = self.resolve_model_trait(
                image_path, name, user_value=self._clean(user_traits.get(name))
            )
            traits[name] = trait
            if trait.needs_user_input:
                asked.append(name)

        flower = self.resolve_flower(
            image_path, user_value=self._clean(user_traits.get("flower_condition"))
        )
        traits["flower_condition"] = flower
        if flower.needs_user_input:
            asked.append("flower_condition")

        return ResolutionReport(traits=traits, asked_for=asked)

    def resolve_flower(self, image_path, user_value=None):
        """
        Flower condition, or an honest statement that there is no flower.

        A plant with no bloom is not a defective plant - it is a plant at the
        wrong point in its cycle, and saying "could not be measured" hides that
        difference. The grower needs to know which of the two they are looking
        at, because one means "come back later" and the other means "photograph
        the bloom closer".

        Note the direction of the error. flower_analysis.py is deliberately
        tuned for precision over recall: a bloom measured at saturation 33
        against a sky at 44 means no threshold separates every flower from the
        background, so the detector prefers to miss a flower rather than invent
        one. "No flower detected" therefore means "none visible in this frame",
        not "this plant has never flowered" - and the wording says so.
        """
        if user_value:
            return ResolvedTrait(
                name="flower_condition", value=user_value, source="user",
                confidence=1.0,
                explanation="Supplied by the grower, and used in place of the "
                            "image reading.",
            )

        try:
            from flower_analysis import bloom_gate
            gate = bloom_gate(image_path)
        except Exception as e:
            return ResolvedTrait(
                name="flower_condition", value="unknown", source="unknown",
                confidence=0.0,
                explanation="Flower detection unavailable ({}).".format(e),
                needs_user_input=True,
            )

        status = gate.get("status")
        evidence = {k: v for k, v in (gate.get("flower") or {}).items()
                    if isinstance(v, (int, float, str, bool))}

        if status == "in_bloom":
            # A bloom is present, but how GOOD it is - petal substance, spike
            # count, how long it will last - is not something this project has
            # ever measured, so no grade is invented for it.
            return ResolvedTrait(
                name="flower_condition", value="present", source="measured",
                confidence=float(gate["flower"].get("confidence", 0.5)),
                explanation="A flower is visible, so this plant can take part "
                            "in a cross now. Flower quality (petal thickness, "
                            "spike length, how long the bloom lasts) is judged "
                            "by eye - the system does not grade it.",
                evidence=evidence, needs_user_input=True,
                suggested_value="good",
            )

        if status == "uncertain":
            return ResolvedTrait(
                name="flower_condition", value="unknown", source="unknown",
                confidence=0.0,
                explanation="Something flower-like is visible but not clearly "
                            "enough to be sure. Photograph the bloom closer to "
                            "confirm.",
                evidence=evidence, needs_user_input=True,
            )

        # No flower found. Say what that means for pollination, and add the
        # growth-stage reading so a young plant gets an answer about its
        # FUTURE rather than a blank.
        note = ("No flower detected in this image. Pollination needs an open "
                "flower, so a cross cannot be made from this photo.")
        try:
            from maturity_analysis import assess_maturity
            maturity = assess_maturity(image_path)
            stage = maturity.get("stage", "")
            label = maturity.get("stage_label", "")
            timeframe = maturity.get("timeframe", "")
            if stage:
                evidence["maturity_stage"] = stage
                evidence["maturity_confidence"] = maturity.get("confidence", 0.0)
            if label:
                note += " Growth stage looks like {}.".format(label)
            if timeframe:
                note += " " + str(timeframe)
            note += " Photograph it again when flowers appear."
        except Exception:
            note += " Photograph it again when flowers appear."

        return ResolvedTrait(
            name="flower_condition", value="none", source="measured",
            confidence=0.5,
            explanation=note, evidence=evidence,
            needs_user_input=False,
        )

    @staticmethod
    def _clean(value):
        """Normalise a user-supplied trait value, treating blanks as absent."""
        if value is None:
            return None
        value = str(value).strip().lower()
        return None if value in ("", "unknown", "none", "null") else value


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Resolve plant traits from an image")
    parser.add_argument("--image", required=True)
    parser.add_argument("--closeup", default=None, help="Optional leaf close-up")
    args = parser.parse_args()

    report = TraitResolver().resolve(args.image, args.closeup)

    print("\n" + "=" * 62)
    print("TRAIT RESOLUTION")
    print("=" * 62)
    for name, t in report.traits.items():
        flag = "ASK" if t.needs_user_input else "OK "
        print(f"\n  [{flag}] {name}: {t.value}  ({t.source}, confidence {t.confidence:.0%})")
        print(f"        {t.explanation}")
        if t.suggested_value:
            print(f"        suggested: {t.suggested_value}")

    print(f"\n  Fully automatic: {len(report.asked_for) == 0}")
    print(f"  Still asking for: {report.asked_for or 'nothing'}")
    print("=" * 62)
