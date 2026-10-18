"""
grading_agreement.py -- how far does an orchid researcher agree with our grades?

Every severity label in this dataset was judged by one person, by eye, against
the 10% and 40% bands. Nothing measured how reliable that judgement is, and the
held-out photographs show a suspicious pattern (graded last in one session, none
of the 30 held-out Black Leaf Spot photographs graded severe). So a researcher
grades 25 photographs blind, and this script compares the two sets of grades:

  exact agreement     same grade
  within one grade    mild vs moderate counts; mild vs severe does not
  Cohen's kappa       agreement beyond what chance would give (0 = chance)
  weighted kappa      kappa where a two-grade disagreement costs four times a
                      one-grade one, the standard score for ordered scales

reported for all 25 photographs, and separately for those graded EARLY in the
labelling session (training photographs) and LAST (held-out photographs). If
the researcher agrees less with the late grades, that supports the
labelling-order explanation. With 12 and 13 photographs the split is a hint,
not proof, and the report says so.

Usage
-----
    python grading_agreement.py --key answer_key_DO_NOT_SHOW.csv \\
                                --researcher researcher_grades.csv
"""

import argparse
import csv
import sys

GRADES = ["mild", "moderate", "severe"]


def kappa(a, b, weighted=False):
    """Cohen's kappa for two lists of grade indices; quadratic weights if asked."""
    k, n = len(GRADES), len(a)
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[x][y] += 1
    rows = [sum(r) for r in observed]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        return ((i - j) ** 2 / (k - 1) ** 2) if weighted else (0.0 if i == j else 1.0)

    num = sum(w(i, j) * observed[i][j] for i in range(k) for j in range(k)) / n
    den = sum(w(i, j) * rows[i] * cols[j] for i in range(k) for j in range(k)) / (n * n)
    return 1.0 - num / den if den else float("nan")


def summary(pairs):
    a = [GRADES.index(p["yours"]) for p in pairs]
    b = [GRADES.index(p["researcher"]) for p in pairs]
    n = len(pairs)
    return {
        "n": n,
        "exact": sum(x == y for x, y in zip(a, b)) / n,
        "within_one": sum(abs(x - y) <= 1 for x, y in zip(a, b)) / n,
        "kappa": kappa(a, b),
        "weighted_kappa": kappa(a, b, weighted=True),
        "researcher_more_severe": sum(y > x for x, y in zip(a, b)),
        "researcher_less_severe": sum(y < x for x, y in zip(a, b)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--researcher", required=True)
    args = ap.parse_args()

    key = {r["photo"]: r for r in csv.DictReader(open(args.key, encoding="utf-8-sig"))}
    pairs = []
    for r in csv.DictReader(open(args.researcher, encoding="utf-8-sig")):
        grade = (r.get("researcher_grade") or "").strip().lower()
        if grade in GRADES and r["photo"] in key:
            k = key[r["photo"]]
            pairs.append({"photo": r["photo"], "yours": k["your_grade"], "researcher": grade,
                          "early": k["original_split"] == "train"})
    if not pairs:
        sys.exit("No researcher grades yet: fill researcher_grade with mild, moderate or severe.")

    print("=" * 66)
    print("  SEVERITY GRADING AGREEMENT, researcher vs our labels")
    print("=" * 66)
    print("  {:<26}{:>4}{:>8}{:>11}{:>8}{:>10}".format(
        "", "n", "exact", "within 1", "kappa", "weighted"))
    for name, part in (("all photos", pairs),
                       ("graded early (training)", [p for p in pairs if p["early"]]),
                       ("graded last (held-out)", [p for p in pairs if not p["early"]])):
        if part:
            s = summary(part)
            print("  {:<26}{:>4}{:>8.0%}{:>11.0%}{:>8.2f}{:>10.2f}".format(
                name, s["n"], s["exact"], s["within_one"], s["kappa"], s["weighted_kappa"]))
    s = summary(pairs)
    print("\n  researcher graded MORE severe than us: {} photos; LESS severe: {}".format(
        s["researcher_more_severe"], s["researcher_less_severe"]))
    print("\n  Kappa reading (Landis & Koch): below 0.20 slight, 0.21-0.40 fair,")
    print("  0.41-0.60 moderate, 0.61-0.80 substantial, above 0.80 almost perfect.")
    print("  With 12 and 13 photos in the two halves, a difference between them")
    print("  is a hint about the labelling order, not proof of it.")
    print("=" * 66)


if __name__ == "__main__":
    main()
