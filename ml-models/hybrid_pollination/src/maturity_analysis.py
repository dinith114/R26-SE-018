"""
Hybrid Pollination - Maturity and Breeding Readiness

Answers the grower's question: "this plant is still small - will it be good for
pollination later?"

WHAT THIS CAN AND CANNOT DO
----------------------------
It cannot predict the future. Nothing trained on 28 plants photographed once
can say what a seedling will become; that would need the same plants
photographed repeatedly over months, which this project does not have.

What it CAN honestly do is three things a breeder actually needs:

  1. Say whether the plant is mature enough to flower AT ALL. A Vanda must
     reach a certain size and leaf count before it blooms, and a plant that
     cannot bloom cannot be pollinated no matter how healthy it is.

  2. Report the plant's CURRENT condition, which is the best available
     indicator of how it is developing. A juvenile with healthy leaves is
     developing well; one already yellowing is not.

  3. Give a concrete estimate of how far off flowering is, and say what to
     watch for - so the grower knows when to come back.

The distinction matters and should be stated to the user in those terms:
this is a **readiness stage assessment**, not a forecast.

Maturity stages used here follow ordinary Vanda cultivation practice:

    seedling    very few leaves, small plant     - years from flowering
    juvenile    growing, not yet flowering size  - months to a year+
    near_mature approaching flowering size       - possibly next season
    mature      flowering size reached           - can be bred from
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trait_features import extract_trait_features


# Leaf-count bands for a monopodial Vanda. A flowering-size plant carries
# roughly 8-12 healthy leaves on a developed stem; the counts below are the
# segmentation-based ESTIMATE, which under-counts overlapping leaves, so the
# thresholds sit lower than the botanical figures.
STAGE_BANDS = [
    ("seedling",    0, 2),
    ("juvenile",    3, 4),
    ("near_mature", 5, 6),
    ("mature",      7, 99),
]

STAGE_GUIDANCE = {
    "seedling": {
        "can_pollinate": False,
        "timeframe": "Several years from flowering size.",
        "advice": "Far too young to breed from. Concentrate on steady growth: "
                  "bright indirect light, good air movement, and regular weak "
                  "feeding. Re-assess in a year.",
    },
    "juvenile": {
        "can_pollinate": False,
        "timeframe": "Roughly one to three years from flowering, depending on culture.",
        "advice": "Still building the stem and leaf count it needs before it can "
                  "flower. Keep it growing steadily and re-assess each season.",
    },
    "near_mature": {
        "can_pollinate": False,
        "timeframe": "Possibly flowering within the next season or two.",
        "advice": "Approaching flowering size. Keep conditions stable and watch "
                  "for a spike forming between the leaves. Once it flowers, "
                  "assess it again for breeding.",
    },
    "mature": {
        "can_pollinate": True,
        "timeframe": "Flowering size reached.",
        "advice": "Large enough to breed from. Whether it can be used right now "
                  "depends on it being in bloom - a plant without an open flower "
                  "has no pollen to give and nowhere to receive it.",
    },
}


def assess_maturity(image_path: str, precomputed: dict = None) -> dict:
    """
    Assess how far a plant is from being usable for breeding.

    Args:
        image_path:  Plant image
        precomputed: Trait features already extracted, to avoid re-segmenting

    Returns:
        dict with stage, can_pollinate_when_mature, current_condition,
        timeframe, advice, measurements, confidence and caveat
    """
    features = precomputed or extract_trait_features(image_path)

    leaf_count = float(features.get("leaf_count_est", 0))
    coverage = float(features.get("plant_coverage", 0))
    elongation = float(features.get("leaf_elongation", 0))
    isolation = float(features.get("seg_isolation", 0))

    stage = "mature"
    for name, low, high in STAGE_BANDS:
        if low <= leaf_count <= high:
            stage = name
            break

    # A plant carrying a flower is mature by definition, whatever the leaf
    # count says. This override matters because leaf counting from a single 2D
    # photograph systematically UNDER-counts: Vanda leaves overlap heavily, and
    # the erosion-based estimate merges them. A visible bloom is direct proof of
    # flowering size and outranks an inferred count.
    stage_evidence = "leaf count"
    try:
        from flower_analysis import analyse_flower
        flower = analyse_flower(image_path)
        if flower["in_bloom"] and flower["confidence"] >= 0.5:
            stage = "mature"
            stage_evidence = "flower present (definitive)"
    except Exception:
        flower = {"in_bloom": False, "confidence": 0.0}

    guidance = STAGE_GUIDANCE[stage]

    # How much of the frame the plant fills is a weak size cue on its own,
    # because it depends entirely on how close the photographer stood. It is
    # used only to flag a disagreement, never to set the stage.
    size_conflict = ""
    if stage in ("seedling", "juvenile") and coverage > 0.45:
        size_conflict = ("The plant fills much of the frame, which suggests a "
                         "close-up rather than a genuinely small plant. Photograph "
                         "the whole plant from further back for a reliable reading.")
    elif stage == "mature" and coverage < 0.08:
        size_conflict = ("The plant occupies very little of the frame. Move closer "
                         "so the leaves can be counted properly.")

    # Confidence comes from how cleanly the plant was separated from its
    # neighbours - leaf counting is meaningless if two plants were merged.
    confidence = round(min(0.75, 0.3 + 0.5 * isolation), 2)
    if size_conflict:
        confidence = round(confidence * 0.6, 2)
    if stage_evidence.startswith("flower"):
        confidence = 0.9   # Direct observation, not inference

    return {
        "stage": stage,
        "stage_label": stage.replace("_", " ").title(),
        "stage_evidence": stage_evidence,
        "in_bloom": bool(flower.get("in_bloom")),
        "ready_to_breed_now": guidance["can_pollinate"],
        "timeframe": guidance["timeframe"],
        "advice": guidance["advice"],
        "size_warning": size_conflict,
        "confidence": confidence,
        "measurements": {
            "leaves_detected": int(leaf_count),
            "leaf_count_note": ("Under-counts overlapping leaves; a 2D photograph "
                                "cannot separate them reliably."),
            "plant_coverage": round(coverage, 3),
            "leaf_elongation": round(elongation, 2),
            "segmentation_isolation": round(isolation, 3),
        },
        "caveat": (
            "This is a readiness STAGE assessment, not a forecast. The system "
            "cannot predict how a young plant will develop - that would need "
            "the same plant photographed repeatedly over months. What it "
            "reports is how far the plant is from flowering size today, and "
            "how healthy it looks today."
        ),
    }


def breeding_outlook(image_path: str, trait_predictor=None) -> dict:
    """
    Full answer for a young plant: how far from breeding, and how it looks now.

    Combines the maturity stage with the trained condition models, because
    "when can I breed from this" and "is it growing well" are two halves of the
    same question.
    """
    features = extract_trait_features(image_path)
    maturity = assess_maturity(image_path, precomputed=features)

    condition = {}
    if trait_predictor is None:
        try:
            from trait_predictor import get_trait_predictor
            trait_predictor = get_trait_predictor()
        except Exception:
            trait_predictor = None

    if trait_predictor is not None:
        for trait in trait_predictor.available():
            r = trait_predictor.predict(image_path, trait, precomputed=features)
            condition[trait] = {"value": r["value"], "confidence": r["confidence"]}

    # Current condition is the only honest signal about how it is developing
    leaf = condition.get("leaf_condition", {}).get("value", "unknown")
    strength = condition.get("plant_strength", {}).get("value", "unknown")

    if leaf == "healthy" and strength in ("strong", "moderate"):
        trajectory = "developing well"
        note = ("The plant looks healthy for its stage. If conditions stay the "
                "same it should keep developing normally.")
    elif leaf == "weak" or strength == "weak":
        trajectory = "needs attention"
        note = ("The plant already shows weakness at this stage. Correct its "
                "growing conditions now - a plant that struggles while young "
                "rarely becomes a strong parent.")
    else:
        trajectory = "uncertain"
        note = ("Current condition could not be judged confidently. Re-photograph "
                "the whole plant in even light.")

    return {
        "maturity": maturity,
        "current_condition": condition,
        "trajectory": trajectory,
        "trajectory_note": note,
        "summary": (
            f"{maturity['stage_label']} - {maturity['timeframe']} "
            f"Currently {trajectory}."
        ),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Assess how far a plant is from being usable for breeding")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    out = breeding_outlook(args.image)
    m = out["maturity"]

    print("\n" + "=" * 62)
    print("BREEDING READINESS OUTLOOK")
    print("=" * 62)
    print(f"\n  Stage        : {m['stage_label']}  (confidence {m['confidence']:.0%})")
    print(f"  Ready now    : {'yes' if m['ready_to_breed_now'] else 'no'}")
    print(f"  Timeframe    : {m['timeframe']}")
    print(f"  Leaves found : {m['measurements']['leaves_detected']}")

    if out["current_condition"]:
        print("\n  Current condition:")
        for k, v in out["current_condition"].items():
            print(f"    {k:16s} {v['value']}  ({v['confidence']:.0%})")

    print(f"\n  Trajectory   : {out['trajectory']}")
    print(f"  {out['trajectory_note']}")
    print(f"\n  Advice       : {m['advice']}")
    if m["size_warning"]:
        print(f"\n  [!] {m['size_warning']}")
    print(f"\n  {m['caveat']}")
    print("=" * 62)
