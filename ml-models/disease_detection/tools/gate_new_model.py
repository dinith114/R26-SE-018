"""
gate_new_model.py -- may a retrained model replace the one the app uses?

Retraining is gated twice:

  BEFORE training   only expert-approved photographs count, 30 per new disease
                    from at least 3 growers (backend/app/services/
                    disease_contributions.py).
  AFTER training    this script.

A new disease must not be paid for with the diseases the app already knows.
A class learned from little evidence steals predictions from its neighbours,
and the grower whose plant has Black Leaf Spot is not helped by a model that
now also knows Anthracnose but misses their disease more often. So the new
model passes only if all three hold:

  1. macro F1 over the OLD classes drops by no more than --max-drop (0.01)
  2. no single old class's F1 drops by more than --max-class-drop (0.05)
  3. every NEW class reaches --min-new-f1 (0.60): below that it mostly
     mislabels. 0.60 is the F1 of the weakest class the app already ships,
     Black Leaf Spot, so a new class is held to the bar the old ones meet.

Both files are evaluate.py's test-set output (metrics_test.json). The old
classes must be scored on the SAME test photographs, and they are when a new
class is appended: split_dataset.py splits each class folder on its own with a
fixed seed, so adding a folder moves no existing photograph. The script checks
the per-class photo counts match and refuses to compare if they do not.

Exit code 0 = PASS, 1 = FAIL, 2 = cannot compare -- so a deployment script can
refuse to copy the new model into models/ on anything but 0.

Usage
-----
    python gate_new_model.py --old ../models/metrics_test.json \\
                             --new ../models_retrained/metrics_test.json
"""

import argparse
import json
import sys
from pathlib import Path

PASS, FAIL, CANNOT = 0, 1, 2


def judge(old, new, max_drop=0.01, max_class_drop=0.05, min_new_f1=0.60):
    """
    Compare two metrics_test.json documents.
    Returns (code, report) where report is a JSON-ready dict.
    """
    old_classes = list(old["class_names"])
    new_classes = [c for c in new["class_names"] if c not in old_classes]
    report = {"old_classes": old_classes, "new_classes": new_classes, "checks": [],
              "per_class": []}

    lost = [c for c in old_classes if c not in new["class_names"]]
    if lost:
        report["reason"] = "the new model no longer has class(es) {}".format(lost)
        return CANNOT, report
    moved = [c for c in old_classes
             if old["per_class"][c]["support"] != new["per_class"][c]["support"]]
    if moved:
        report["reason"] = ("class(es) {} were not tested on the same photographs: "
                            "the test sets differ, so the scores cannot be "
                            "compared".format(moved))
        return CANNOT, report

    def f1(doc, c):
        return float(doc["per_class"][c]["f1"])

    before = sum(f1(old, c) for c in old_classes) / len(old_classes)
    after = sum(f1(new, c) for c in old_classes) / len(old_classes)
    report["old_macro_f1_before"] = before
    report["old_macro_f1_after"] = after

    def check(name, value, limit, ok):
        report["checks"].append({"check": name, "value": value, "limit": limit, "pass": ok})

    check("macro F1 on the old classes may fall by at most {:.2f}".format(max_drop),
          after - before, -max_drop, after - before >= -max_drop)
    for c in old_classes:
        change = f1(new, c) - f1(old, c)
        report["per_class"].append({"class": c, "f1_before": f1(old, c),
                                    "f1_after": f1(new, c), "change": change})
        check("{} may fall by at most {:.2f}".format(c, max_class_drop),
              change, -max_class_drop, change >= -max_class_drop)
    for c in new_classes:
        report["per_class"].append({"class": c, "f1_before": None,
                                    "f1_after": f1(new, c), "change": None})
        check("new class {} must reach F1 {:.2f}".format(c, min_new_f1),
              f1(new, c), min_new_f1, f1(new, c) >= min_new_f1)

    if not new_classes:
        report["note"] = "no new class: this compares two versions of the same classes"
    return (PASS if all(ch["pass"] for ch in report["checks"]) else FAIL), report


def print_report(code, report, out=print):
    out("=" * 66)
    out("  RETRAINED MODEL GATE")
    out("=" * 66)
    if code == CANNOT:
        out("  CANNOT COMPARE: " + report["reason"])
        out("=" * 66)
        return
    out("  {:<28}{:>11}{:>11}{:>11}".format("class", "F1 before", "F1 after", "change"))
    for row in report["per_class"]:
        if row["f1_before"] is None:
            out("  {:<28}{:>11}{:>11.3f}{:>11}".format(row["class"] + " (new)", "-",
                                                        row["f1_after"], "-"))
        else:
            out("  {:<28}{:>11.3f}{:>11.3f}{:>+11.3f}".format(
                row["class"], row["f1_before"], row["f1_after"], row["change"]))
    out("\n  old classes, macro F1: {:.3f} -> {:.3f}".format(
        report["old_macro_f1_before"], report["old_macro_f1_after"]))
    out("")
    for ch in report["checks"]:
        out("  [{}] {}  ({:+.3f})".format("PASS" if ch["pass"] else "FAIL", ch["check"],
                                          ch["value"]))
    out("\n  VERDICT: {}".format(
        "PASS -- the new model may replace the current one." if code == PASS else
        "FAIL -- keep the current model."))
    out("=" * 66)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True, help="metrics_test.json of the model in use")
    ap.add_argument("--new", required=True, help="metrics_test.json of the retrained model")
    ap.add_argument("--max-drop", type=float, default=0.01)
    ap.add_argument("--max-class-drop", type=float, default=0.05)
    ap.add_argument("--min-new-f1", type=float, default=0.60)
    ap.add_argument("--report", default=None, help="also write the verdict as JSON here")
    args = ap.parse_args()

    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    code, report = judge(old, new, args.max_drop, args.max_class_drop, args.min_new_f1)
    print_report(code, report)
    if args.report:
        report["verdict"] = {PASS: "PASS", FAIL: "FAIL", CANNOT: "CANNOT_COMPARE"}[code]
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.exit(code)


if __name__ == "__main__":
    main()
