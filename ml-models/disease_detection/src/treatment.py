"""
treatment.py -- rule-based treatment recommendation, keyed by (disease, severity).

This is NOT a model, and that is a deliberate design decision worth defending:

  * Treatment advice must be auditable. A grower -- or an extension officer
    checking the system -- must be able to see exactly why a recommendation was
    given and correct it. A neural network cannot offer that.
  * There is no training data for it. Learning treatment would need a dataset of
    treatments applied and outcomes observed. This project has photographs, not
    outcomes.
  * It must be correctable in minutes. When a registration changes or a product
    is withdrawn, someone edits one JSON entry. No retraining, no revalidation.

Safety behaviour built into this module
---------------------------------------
Chemical doses in the knowledge base are marked "VERIFY" until a human has
sourced them from the actual product label and the Sri Lanka Department of
Agriculture registered-product list. Any option still unverified is returned
with `show_dose = False` and a referral message instead of a number, so an
unverified rate can never reach a grower even if the front end forgets to check.

Usage
-----
    from treatment import TreatmentAdvisor

    advisor = TreatmentAdvisor()
    advice = advisor.recommend("black_leaf_spot", "moderate")
    print(advice["summary"])

Command line:
    python treatment.py --disease black_leaf_spot --severity moderate
    python treatment.py --list
    python treatment.py --check          # validate the KB, list unverified doses
"""

import argparse
import json
import sys
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KB = Path(__file__).resolve().parent / "treatment_kb.json"

VALID_SEVERITIES = {"mild", "moderate", "severe", "none", "unknown"}

# Entries that are a state, not a disease: one level each, no grading.
STATE_ENTRIES = {"healthy", "unidentified", "invalid_image"}

UNVERIFIED_MESSAGE = (
    "Application rate not yet verified for Sri Lanka. Follow the product label "
    "and confirm with your agricultural extension officer before mixing."
)


class TreatmentAdvisor:
    """Loads the knowledge base once and answers (disease, severity) queries."""

    def __init__(self, kb_path=None):
        self.kb_path = Path(kb_path) if kb_path else DEFAULT_KB
        if not self.kb_path.exists():
            raise FileNotFoundError("Treatment KB not found: {}".format(self.kb_path))
        with open(self.kb_path, encoding="utf-8") as f:
            self.kb = json.load(f)
        self.treatments = self.kb["treatments"]

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def known_diseases(self):
        return sorted(self.treatments.keys())

    def severities_for(self, disease):
        entry = self.treatments.get(disease)
        return sorted(entry["severity_levels"].keys()) if entry else []

    def _normalise_severity(self, disease, severity):
        """
        Map a severity onto the key this disease actually uses.

        Healthy has only 'none' and unidentified has only 'unknown', so a caller
        passing severity=None for a healthy plant should still get an answer
        rather than a KeyError.
        """
        levels = self.treatments[disease]["severity_levels"]
        if severity in levels:
            return severity
        if len(levels) == 1:
            return next(iter(levels))
        return None

    def recommend(self, disease, severity=None):
        """
        Return the treatment record for one (disease, severity) pair.

        Never raises for an unknown disease -- it falls back to the
        'unidentified' entry, because a system that crashes on an unexpected
        label is worse than one that says "I am not sure, ask an expert".
        """
        if disease not in self.treatments:
            disease = "unidentified"

        entry = self.treatments[disease]
        key = self._normalise_severity(disease, severity)

        if key is None:
            return {
                "disease": disease,
                "display_name": entry.get("display_name", disease),
                "severity": severity,
                "error": "unknown severity",
                "message": "Severity '{}' is not defined for {}. Valid values: {}".format(
                    severity, disease, self.severities_for(disease)),
                "escalate_to_expert": True,
            }

        level = entry["severity_levels"][key]
        chemical = self._prepare_chemical(level.get("chemical_control", {}))

        return {
            "disease": disease,
            "display_name": entry.get("display_name", disease),
            "pathogen": entry.get("pathogen"),
            "pathogen_type": entry.get("pathogen_type"),
            "severity": key,
            "summary": level.get("summary", ""),
            "immediate_actions": level.get("immediate_actions", []),
            "cultural_control": level.get("cultural_control", []),
            "chemical_control": chemical,
            "monitoring": level.get("monitoring", ""),
            "escalate_to_expert": level.get("escalate_to_expert", False),
            "escalation_reason": level.get("escalation_reason"),
            "safety": self.kb["safety"]["always_show"],
            "resistance_management": self.kb["safety"]["resistance_management"],
            "grading_protocol": self.kb["grading_protocol"],
        }

    def _prepare_chemical(self, chemical):
        """
        Copy the chemical block, suppressing any dose that is not yet verified.

        This is the safety gate. An unverified rate is replaced by a referral
        message, so it cannot reach a grower through a front end that forgot to
        check the `verified` flag.
        """
        options = []
        for opt in chemical.get("options", []):
            verified = bool(opt.get("verified", False))
            options.append({
                "active_ingredient": opt.get("active_ingredient"),
                "frac_group": opt.get("frac_group"),
                "type": opt.get("type"),
                "notes": opt.get("notes", ""),
                "verified": verified,
                "show_dose": verified,
                "dose": opt.get("dose") if verified else UNVERIFIED_MESSAGE,
                "interval_days": opt.get("interval_days") if verified else None,
                "applications": opt.get("applications") if verified else None,
            })
        return {
            "recommended": chemical.get("recommended", False),
            "rationale": chemical.get("rationale", ""),
            "options": options,
            "any_unverified": any(not o["verified"] for o in options),
        }

    def recommend_from_prediction(self, prediction, severity=None):
        """
        Convenience bridge from preprocess.predict() straight to advice.

        `prediction` is the dict returned by preprocess.predict(). If the
        classifier was not confident, its label is already 'unidentified' and
        the severity model must NOT be consulted -- grading the severity of a
        condition you cannot name is meaningless.
        """
        label = prediction.get("label", "unidentified")
        if label == "unidentified":
            return self.recommend("unidentified")
        if label == "healthy":
            return self.recommend("healthy")
        return self.recommend(label, severity)

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def validate(self):
        """
        Check the KB is internally consistent. Returns (problems, warnings).

        Run this in CI, or at least before the demo. The costly failure mode is
        a classifier that can predict a class the KB cannot advise on -- the
        system then confidently names a disease and has nothing to say about it.
        """
        problems, warnings = [], []

        for name, entry in self.treatments.items():
            if "severity_levels" not in entry:
                problems.append("{}: no severity_levels".format(name))
                continue
            for sev, level in entry["severity_levels"].items():
                if sev not in VALID_SEVERITIES:
                    problems.append("{}/{}: severity not in {}".format(
                        name, sev, sorted(VALID_SEVERITIES)))
                if not level.get("summary"):
                    problems.append("{}/{}: missing summary".format(name, sev))
                if not level.get("immediate_actions"):
                    warnings.append("{}/{}: no immediate_actions".format(name, sev))
                for opt in level.get("chemical_control", {}).get("options", []):
                    if not opt.get("verified", False):
                        warnings.append("{}/{}: dose UNVERIFIED for {}".format(
                            name, sev, opt.get("active_ingredient")))

        # Every class the classifier can output must have advice.
        names_file = COMPONENT_ROOT / "models" / "class_names.json"
        if names_file.exists():
            with open(names_file, encoding="utf-8") as f:
                for cls in json.load(f):
                    if cls not in self.treatments:
                        problems.append(
                            "classifier can predict '{}' but the KB has no entry "
                            "for it -- the system would name a disease it cannot "
                            "advise on".format(cls))
        else:
            warnings.append(
                "models/class_names.json not found -- cannot cross-check that "
                "every predictable class has a treatment entry. Re-run this "
                "after training.")

        # The diseased classes need all three grades. These three describe a
        # STATE rather than a disease, so they have a single level each:
        #   healthy        no disease
        #   unidentified   an orchid whose condition cannot be named
        #   invalid_image  not an orchid at all
        for name, entry in self.treatments.items():
            if name in ("healthy", "unidentified", "invalid_image"):
                continue
            missing = {"mild", "moderate", "severe"} - set(entry["severity_levels"])
            if missing:
                problems.append("{}: missing severity levels {}".format(
                    name, sorted(missing)))

        return problems, warnings


# ----------------------------------------------------------------------
# command line
# ----------------------------------------------------------------------

def print_advice(a):
    print("\n" + "=" * 66)
    print("  {}  --  severity: {}".format(a["display_name"], a["severity"]))
    if a.get("pathogen"):
        print("  pathogen: {} ({})".format(a["pathogen"], a.get("pathogen_type")))
    print("=" * 66)

    if a.get("error"):
        print("\n  {}".format(a["message"]))
        return

    print("\n  {}".format(a["summary"]))

    if a["immediate_actions"]:
        print("\n  DO NOW")
        for s in a["immediate_actions"]:
            print("    - {}".format(s))

    if a["cultural_control"]:
        print("\n  GROWING CONDITIONS")
        for s in a["cultural_control"]:
            print("    - {}".format(s))

    chem = a["chemical_control"]
    print("\n  CHEMICAL TREATMENT: {}".format(
        "recommended" if chem["recommended"] else "not recommended"))
    if chem["rationale"]:
        print("    {}".format(chem["rationale"]))
    for opt in chem["options"]:
        print("\n    * {}  [FRAC {}]".format(
            opt["active_ingredient"], opt["frac_group"]))
        print("      type : {}".format(opt["type"]))
        print("      dose : {}".format(opt["dose"]))
        if opt["notes"]:
            print("      note : {}".format(opt["notes"]))

    if a["monitoring"]:
        print("\n  MONITORING")
        print("    {}".format(a["monitoring"]))

    if a["escalate_to_expert"]:
        print("\n  ** REFER TO AN EXPERT **")
        if a.get("escalation_reason"):
            print("     {}".format(a["escalation_reason"]))

    print("\n  SAFETY")
    for s in a["safety"]:
        print("    - {}".format(s))
    print("\n  RESISTANCE MANAGEMENT")
    print("    {}".format(a["resistance_management"]))
    print()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", default=None)
    ap.add_argument("--disease")
    ap.add_argument("--severity")
    ap.add_argument("--list", action="store_true", help="list every entry")
    ap.add_argument("--check", action="store_true", help="validate the KB")
    args = ap.parse_args()

    advisor = TreatmentAdvisor(args.kb)

    if args.check:
        problems, warnings = advisor.validate()
        print("\n{:-^66}".format(" TREATMENT KB VALIDATION "))
        print("  file: {}".format(advisor.kb_path))
        print("  entries: {}".format(", ".join(advisor.known_diseases())))
        print("\n  problems : {}".format(len(problems)))
        for p in problems:
            print("    ! {}".format(p))
        print("\n  warnings : {}".format(len(warnings)))
        for w in warnings:
            print("    - {}".format(w))
        print("\n  Warnings about UNVERIFIED doses are expected until you have")
        print("  sourced each rate from the product label and the Department of")
        print("  Agriculture list. Until then treatment.py returns a referral")
        print("  message in place of the number, so no unverified rate can")
        print("  reach a grower.")
        print("-" * 66)
        sys.exit(1 if problems else 0)

    if args.list:
        for d in advisor.known_diseases():
            for s in advisor.severities_for(d):
                print_advice(advisor.recommend(d, s))
        return

    if not args.disease:
        ap.error("give --disease (with --severity), or --list, or --check")

    print_advice(advisor.recommend(args.disease, args.severity))


if __name__ == "__main__":
    main()
