"""The second retraining gate: a new disease must not cost the old ones.

The inputs below are made-up metrics files, not trained models. They exist to
show the rule deciding correctly at its edges.

Run from ml-models/disease_detection:  python -m pytest tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from gate_new_model import CANNOT, FAIL, PASS, judge  # noqa: E402

OLD = {
    "class_names": ["black_leaf_spot", "healthy", "phyllosticta_leaf_spot"],
    "per_class": {
        "black_leaf_spot": {"f1": 0.60, "support": 15},
        "healthy": {"f1": 0.94, "support": 24},
        "phyllosticta_leaf_spot": {"f1": 0.79, "support": 28},
    },
}


def retrained(changes, new_f1=0.70, new_support=6):
    per_class = {c: dict(v, f1=v["f1"] + changes.get(c, 0.0)) for c, v in OLD["per_class"].items()}
    per_class["anthracnose"] = {"f1": new_f1, "support": new_support}
    return {"class_names": ["anthracnose"] + OLD["class_names"], "per_class": per_class}


def test_a_new_class_that_costs_the_old_ones_nothing_passes():
    code, report = judge(OLD, retrained({}))
    assert code == PASS
    assert report["new_classes"] == ["anthracnose"]


def test_a_small_drop_within_the_limits_passes():
    code, _ = judge(OLD, retrained({"black_leaf_spot": -0.02, "healthy": +0.01}))
    assert code == PASS            # macro change -0.0033, one class -0.02


def test_the_old_classes_getting_worse_on_average_fails():
    code, report = judge(OLD, retrained({"black_leaf_spot": -0.04, "phyllosticta_leaf_spot": -0.03}))
    assert code == FAIL            # macro change -0.023 > 0.01
    assert not report["checks"][0]["pass"]


def test_one_old_class_collapsing_fails_even_if_the_average_holds():
    code, report = judge(OLD, retrained({"black_leaf_spot": -0.08, "healthy": +0.05,
                                         "phyllosticta_leaf_spot": +0.03}))
    assert code == FAIL
    failed = [c["check"] for c in report["checks"] if not c["pass"]]
    assert failed == ["black_leaf_spot may fall by at most 0.05"]


def test_a_weak_new_class_fails():
    code, _ = judge(OLD, retrained({}, new_f1=0.45))
    assert code == FAIL


def test_different_test_photographs_cannot_be_compared():
    new = retrained({})
    new["per_class"]["healthy"]["support"] = 25
    code, report = judge(OLD, new)
    assert code == CANNOT and "healthy" in report["reason"]


def test_a_class_that_disappears_cannot_be_compared():
    new = retrained({})
    new["class_names"].remove("healthy")
    code, _ = judge(OLD, new)
    assert code == CANNOT
