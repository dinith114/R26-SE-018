"""
Hybrid Pollination - Grower Cross Logbook

WHY THIS EXISTS
---------------
The RHS register records hybrids that were successfully made and registered.
Nobody registers "I attempted this cross and got no pod". It therefore has no
denominator, and no success rate can honestly be derived from it - which is
why the compatibility engine returns evidence tiers instead of percentages.

This module collects the missing half: what a grower actually attempted and
what actually happened, failures included. It is an INSTRUMENT, not a model.
On day one it holds nothing and predicts nothing. Its value is that after a
season it holds the negatives no register ever will.

THREE FAILURES, NOT ONE
-----------------------
A cross can fail at three different gates and they mean completely different
things:

    no pod set        (7-21 days)  usually technique, timing or dead pollen
    capsule aborted   (1-8 months) usually pod-parent condition
    capsule empty     (at harvest) this is where genetic incompatibility lives

Collapsing them into one boolean destroys the only signal worth having. Every
record therefore carries the stage it stopped at, not just whether it worked.

CENSORING
---------
A cross still in progress is not a failure, and neither is one whose label was
lost. Both are right-censored observations. `lost` exists as its own outcome
precisely so that abandoned records do not quietly become failures and bias
every count computed from this file.

STORAGE
-------
Local JSON is authoritative and Firebase is a best-effort mirror, in that
order. The grower is standing in a greenhouse: the record must be written
whether or not there is signal. The mirror is what makes the data survive the
device - the Peradeniya garden lost years of handwritten crossing books to a
flood, and an off-site copy is the whole point of replacing those books.
"""

import os
import json
import uuid
import shutil
import threading
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE_DIR, "data", "pollination_log")
PHOTO_DIR = os.path.join(LOG_DIR, "photos")
STORE_PATH = os.path.join(LOG_DIR, "logbook.json")

FB_ROOT = "/pollination"

# Rates below this are not shown at all - a count is reported instead. At n=3
# a percentage is noise wearing the clothes of a measurement.
MIN_N_FOR_RATE = 5


# ──────────────────────────────────────────────
# The stage pipeline
# ──────────────────────────────────────────────
# `due_days` is when the grower should next be asked about this stage, counted
# from pollination. Vanda capsules take about nine months, so the gaps are
# long and a reminder is not a nicety - nobody remembers an unmarked capsule
# eight months later.
#
# Every stage carries its own explanation. A grower who has never bred before
# is told "pod set" and has no idea what to look at; the words that matter -
# ovary, capsule, protocorm - are nursery vocabulary, not common knowledge.
# The text lives here rather than in the app so there is one source for it.
#
#   gate      the yes/no question asked at this stage
#   detail    what this stage actually is, in plain words
#   look_for  where on the plant to look, and what it looks like
#   timing    how long this stage normally lasts
#
STAGES = [
    {"key": "pollinated", "label": "Pollinated", "phase": "plant", "due_days": 14,
     "gate": "Did the base of the flower start to swell?",
     "detail": "You have moved the pollinia onto the other flower. Nothing "
               "visible happens for about two weeks, and then the flower "
               "either begins to form a pod or drops off.",
     "look_for": "Look at the short green stalk directly behind the flower, "
                 "between the petals and the stem. That is the ovary. If the "
                 "cross took, it thickens and lengthens; if it did not, the "
                 "whole flower yellows and falls.",
     "timing": "Check after about 2 weeks"},

    {"key": "pod_set", "label": "Pod set", "phase": "plant", "due_days": 45,
     "gate": "Is the pod still green and firmly attached?",
     "detail": "The ovary has swollen - that swelling IS the young seed pod. "
               "The pollen was accepted. It is not yet seed: a pod can still "
               "be empty, and that is only known at harvest.",
     "look_for": "A thickened green pod where the flower was, usually ribbed "
                 "along its length and clearly fatter than the flower stalks "
                 "around it.",
     "timing": "Normally 1-3 weeks after pollination"},

    {"key": "capsule_developing", "label": "Capsule developing", "phase": "plant",
     "due_days": 240,
     "gate": "Is it still green and growing, or has it started to ripen?",
     "detail": "The pod is growing. A Vanda capsule takes about nine months, "
               "and for most of that time nothing changes at all. The plant is "
               "carrying it the whole while, which is why a weak pod parent "
               "often loses the capsule here.",
     "look_for": "Still green, still firmly attached, slowly getting larger. "
                 "A capsule turning yellow and soft before month eight is "
                 "being aborted, not ripening.",
     "timing": "About 9 months in total"},

    {"key": "capsule_mature", "label": "Capsule mature", "phase": "plant",
     "due_days": None,
     "gate": "Harvested before it split open?",
     "detail": "The capsule has stopped growing and is ripening. It will split "
               "along its ribs on its own and release seed as fine as dust, "
               "which is then lost. It has to be cut just before that.",
     "look_for": "Colour turning from green to yellow-brown, and the ribs "
                 "becoming more pronounced. Once a hairline crack appears it "
                 "is hours, not days.",
     "timing": "Check weekly from month eight"},

    {"key": "sown", "label": "Sown / flasked", "phase": "lab", "due_days": None,
     "gate": "Did anything green appear in the flask?",
     "detail": "Orchid seed has no food store of its own, so it will not grow "
               "in soil. It is sown onto sterile jelly in a sealed flask - "
               "usually done by a laboratory rather than the grower.",
     "look_for": "Nothing for several weeks, then a green haze across the "
                 "surface of the jelly.",
     "timing": "4-8 weeks to the first sign"},

    {"key": "germinated", "label": "Germinated", "phase": "lab", "due_days": None,
     "gate": "Big enough to come out of the flask?",
     "detail": "The seed has germinated into protocorms - tiny green beads "
               "that become seedlings. This is the first proof the cross "
               "produced living, viable seed.",
     "look_for": "Green beads turning into small plantlets with their first "
                 "leaves and roots.",
     "timing": "Months in the flask before deflasking"},

    {"key": "seedlings", "label": "Seedlings deflasked", "phase": "lab",
     "due_days": None,
     "gate": "Growing on well?",
     "detail": "The seedlings have been taken out of the flask and are growing "
               "in the nursery. The cross has worked; what remains is time.",
     "look_for": "New leaves and roots after the move out of the flask.",
     "timing": "1-2 years from sowing"},

    {"key": "bloomed", "label": "First bloom", "phase": "lab", "due_days": None,
     "gate": "",
     "detail": "The offspring have flowered. Only now can anyone see what the "
               "cross actually produced.",
     "look_for": "The first spike on a seedling from this cross.",
     "timing": "2-4 years after deflasking"},
]

STAGE_INDEX = {s["key"]: i for i, s in enumerate(STAGES)}

# Each exit names the gate it failed at, because that is what carries the
# information. `means` is shown to the grower so the record is not just a
# label but an explanation of what that label usually indicates.
EXITS = {
    "no_pod_set": {
        "label": "No pod set",
        "after": "pollinated",
        "means": "The flower withered and dropped without the base thickening.",
        "detail": "This is the commonest outcome and it usually says nothing "
                  "about whether the two plants are compatible. The three "
                  "ordinary causes are: the flower was too young or too old "
                  "when pollinated, the pollinia were not pressed firmly onto "
                  "the sticky stigma, or the pollen was no longer alive. Worth "
                  "trying the same pair again before concluding anything.",
        "counts_as": "A failure at the first gate.",
    },
    "capsule_aborted": {
        "label": "Capsule aborted",
        "after": "capsule_developing",
        "means": "The pod started, then yellowed and dropped before ripening.",
        "detail": "The cross itself worked - pollen was accepted and a pod "
                  "formed. What failed was the plant's ability to carry it. "
                  "Nine months is a long demand on a plant that is not in good "
                  "condition, which is exactly what the readiness check on the "
                  "Assess tab is trying to warn about.",
        "counts_as": "A failure at the capsule gate.",
    },
    "capsule_empty": {
        "label": "Capsule empty",
        "after": "capsule_mature",
        "means": "The capsule ripened but held no viable seed.",
        "detail": "The capsule feels light, and when opened the contents are "
                  "not the fine dust that viable orchid seed looks like. This "
                  "is the one outcome that genuinely points at the two plants "
                  "being incompatible - everything earlier can be explained by "
                  "technique or condition.",
        "counts_as": "A failure at the seed gate - the one that matters most.",
    },
    "no_germination": {
        "label": "No germination",
        "after": "sown",
        "means": "Sown into flask, but nothing grew.",
        "detail": "Either the seed was not viable, or something went wrong in "
                  "the flasking - contamination, or a medium that did not suit "
                  "this cross. If the lab reports contamination it is worth "
                  "recording that in the notes, because it is not the cross's "
                  "fault.",
        "counts_as": "A failure at the seed gate.",
    },
    "lost": {
        "label": "Lost track",
        "after": "",
        "means": "The label went missing, the plant died, or you stopped "
                 "following this one.",
        "detail": "This is NOT a failure. It means the outcome is simply "
                  "unknown, and it is kept apart from the failures on purpose: "
                  "if abandoned records quietly counted as failures, every "
                  "number in this logbook would drift downward over time and "
                  "look worse than the truth.",
        "counts_as": "Counted separately. Not in any success or failure count.",
    },
}

#
# Help for the fields asked at pollination. These exist because a failure
# with none of them recorded cannot be told apart from a careless one - but a
# grower who is not told WHY they are being asked just leaves them blank.
#
FIELD_HELP = {
    "flower_age_days": {
        "label": "Flower age",
        "short": "How many days the flower had been open when you pollinated it.",
        "detail": "An orchid flower is not receptive the moment it opens, and "
                  "it loses receptivity as it ages. Roughly 3 to 7 days after "
                  "opening is the usual window. Recording it is what lets a "
                  "failure later be read as 'the flower was too old' rather "
                  "than 'these plants do not cross'. If you do not know, leave "
                  "it blank - a blank is honest, a guess is not.",
    },
    "pollen_source": {
        "label": "Fresh or stored pollen",
        "short": "Fresh means taken from a flower the same day. Stored means "
                 "kept, usually in a fridge.",
        "detail": "Stored pollinia lose viability, and how much depends on how "
                  "long and how cold. A cross that fails on stored pollen may "
                  "have nothing to do with compatibility, so this one field "
                  "decides whether that failure can be interpreted at all.",
    },
    "parent_name": {
        "label": "Name on the tag",
        "short": "Optional. A plant with no readable tag still gets logged.",
        "detail": "If the tag is missing or unreadable, leave this blank. The "
                  "plant is filed under an id such as P-004, which you can "
                  "write on a fresh tag. If you identify it later, add the "
                  "name then - every cross already referring to that id picks "
                  "it up.",
    },
    "photo": {
        "label": "Parent photograph",
        "short": "A picture of the plant being used, so the record is not just "
                 "a name.",
        "detail": "Taking the photo here is what ties the picture and the name "
                  "together in one record. Elsewhere in the app the two are "
                  "entered separately and nothing can check they describe the "
                  "same plant; here they cannot come apart.",
    },
}

# Which gate each outcome sits at, for the pass/fail counts.
GATE_OF_EXIT = {
    "no_pod_set": "pod_set",
    "capsule_aborted": "capsule_mature",
    "capsule_empty": "viable_seed",
    "no_germination": "viable_seed",
}

GATES = [
    {"key": "pod_set",     "label": "Pod set",
     "question": "Of the crosses attempted, how many set a pod?",
     "reached": "pod_set"},
    {"key": "capsule_mature", "label": "Capsule matured",
     "question": "Of the pods that set, how many matured?",
     "reached": "capsule_mature"},
    {"key": "viable_seed", "label": "Viable seed",
     "question": "Of the capsules harvested, how many germinated?",
     "reached": "germinated"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CrossLogService:
    """The grower's own crossing records. One file, one lock, no ORM."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self):
        if self._ready:
            return
        self._ready = True
        self._lock = threading.Lock()
        os.makedirs(PHOTO_DIR, exist_ok=True)
        self._store = self._read()

    # ── storage ───────────────────────────────
    def _read(self) -> dict:
        if not os.path.exists(STORE_PATH):
            return {"plants": {}, "crosses": {}, "seq": {"plant": 0, "cross": 0}}
        try:
            with open(STORE_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            # A corrupt file must not take the feature down in front of a
            # grower. It is moved aside, named, and a fresh one started.
            print(f"[WARN] logbook.json unreadable ({e}); starting a new one")
            try:
                shutil.move(STORE_PATH, STORE_PATH + ".corrupt")
            except Exception:
                pass
            return {"plants": {}, "crosses": {}, "seq": {"plant": 0, "cross": 0}}

        data.setdefault("plants", {})
        data.setdefault("crosses", {})
        data.setdefault("seq", {"plant": 0, "cross": 0})
        return data

    def _write(self) -> None:
        """Write via a temp file so a crash mid-write cannot truncate the log."""
        os.makedirs(LOG_DIR, exist_ok=True)
        tmp = STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._store, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)

    def _mirror(self, path: str, data: dict) -> None:
        """
        Best-effort copy to Firebase.

        Deliberately swallows every error. The local write has already
        succeeded by the time this runs, and a greenhouse with no signal must
        not produce a failed save.
        """
        try:
            from app.api.routes.smart_watering import _fb_put
            _fb_put(f"{FB_ROOT}{path}.json", data)
        except Exception:
            pass

    # ── ids ───────────────────────────────────
    def _next_id(self, kind: str, prefix: str) -> str:
        self._store["seq"][kind] = self._store["seq"].get(kind, 0) + 1
        n = self._store["seq"][kind]
        if kind == "cross":
            return f"{prefix}-{datetime.now().strftime('%y')}-{n:03d}"
        return f"{prefix}-{n:03d}"

    # ── photos ────────────────────────────────
    def save_photo(self, upload) -> str:
        """Store an uploaded photo and return the id used to fetch it back."""
        ext = os.path.splitext(upload.filename or "")[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png"):
            ext = ".jpg"
        photo_id = uuid.uuid4().hex
        dest = os.path.join(PHOTO_DIR, photo_id + ext)
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload.file, f)
        return photo_id + ext

    def photo_path(self, photo_id: str) -> str:
        """Absolute path of a stored photo, or "" if it is not one of ours."""
        safe = os.path.basename(photo_id)          # no traversal out of PHOTO_DIR
        path = os.path.join(PHOTO_DIR, safe)
        return path if os.path.exists(path) else ""

    # ── plants ────────────────────────────────
    def register_plant(self, name: str = "", photo: str = "",
                       genus: str = "", location: str = "") -> dict:
        """
        Record one plant.

        A name is optional on purpose. Half the plants in a working collection
        have a lost or unreadable tag, and a logbook that refuses them is a
        logbook the grower stops using. An unnamed plant gets an id it can be
        labelled with instead, and the name can be filled in later - every
        cross already referencing the id picks it up.
        """
        with self._lock:
            plant_id = self._next_id("plant", "P")
            record = {
                "plantId": plant_id,
                "name": (name or "").strip(),
                "genus": (genus or "").strip(),
                "photo": photo or "",
                "location": (location or "").strip(),
                "addedAt": _now(),
            }
            self._store["plants"][plant_id] = record
            self._write()
        self._mirror(f"/plants/{plant_id}", record)
        return record

    def plants(self) -> list:
        return sorted(self._store["plants"].values(),
                      key=lambda p: p["addedAt"], reverse=True)

    def display_name(self, plant_id: str) -> str:
        p = self._store["plants"].get(plant_id) or {}
        return p.get("name") or plant_id

    # ── crosses ───────────────────────────────
    def log_cross(self, pod_plant_id: str, pollen_plant_id: str,
                  pod_health: dict = None, pollen_health: dict = None,
                  flower_age_days=None, pollen_source: str = "fresh",
                  pollen_stored_days=None, logged_by: str = "",
                  notes: str = "", conditions: dict = None) -> dict:
        """
        Record one attempted cross, pod parent first.

        The two health readings are SNAPSHOTS, copied in rather than linked.
        A plant's condition changes; what matters for this record is what it
        was on the day the pollinia were moved, and a live link would quietly
        rewrite history every time the plant was re-assessed.
        """
        with self._lock:
            cross_id = self._next_id("cross", "X")
            record = {
                "crossId": cross_id,
                "podPlantId": pod_plant_id,
                "pollenPlantId": pollen_plant_id,
                "podName": self.display_name(pod_plant_id),
                "pollenName": self.display_name(pollen_plant_id),
                "pollinatedAt": _now(),
                "stage": "pollinated",
                "outcome": "",
                # Covariates. A failure with none of these recorded cannot be
                # told apart from a careless one.
                "flowerAgeDays": flower_age_days,
                "pollenSource": pollen_source,
                "pollenStoredDays": pollen_stored_days,
                "conditions": conditions or {},
                "podHealth": pod_health or {},
                "pollenHealth": pollen_health or {},
                "loggedBy": (logged_by or "").strip(),
                "notes": (notes or "").strip(),
                "history": [{"stage": "pollinated", "at": _now(), "note": ""}],
            }
            self._store["crosses"][cross_id] = record
            self._write()
        self._mirror(f"/crosses/{cross_id}", record)
        return self._decorate(record)

    def update_stage(self, cross_id: str, stage: str = "",
                     outcome: str = "", note: str = "") -> dict:
        """
        Move a cross to the next stage, or close it at the gate it failed.

        Exactly one of `stage` / `outcome` is expected. Both are appended to
        the same history list, so the record reads as what happened in order
        rather than as a single mutable status field.
        """
        with self._lock:
            record = self._store["crosses"].get(cross_id)
            if not record:
                raise KeyError(cross_id)

            if outcome:
                if outcome not in EXITS:
                    raise ValueError(f"unknown outcome: {outcome}")
                record["outcome"] = outcome
                record["history"].append(
                    {"outcome": outcome, "at": _now(), "note": note or ""}
                )
            elif stage:
                if stage not in STAGE_INDEX:
                    raise ValueError(f"unknown stage: {stage}")
                record["stage"] = stage
                record["outcome"] = ""
                record["history"].append(
                    {"stage": stage, "at": _now(), "note": note or ""}
                )
            else:
                raise ValueError("pass a stage or an outcome")

            self._write()
        self._mirror(f"/crosses/{cross_id}", record)
        return self._decorate(record)

    def delete_cross(self, cross_id: str) -> dict:
        """
        Remove a record entirely.

        This has to exist: a grower learning the app will create test entries
        and duplicates, and a logbook clogged with junk is one they stop
        trusting and stop using.

        It is also the single most dangerous button here. The whole point of
        this file is to keep the failures that the RHS register cannot hold,
        and a grower who deletes every cross that did not work rebuilds the
        register's bias by hand - a book of successes only. The app therefore
        asks a different question before deleting a closed failure than before
        deleting a fresh mistake, and `deleted` keeps a count so the records
        that have gone are at least visible as a number.
        """
        with self._lock:
            record = self._store["crosses"].pop(cross_id, None)
            if record is None:
                raise KeyError(cross_id)
            self._store["deleted"] = self._store.get("deleted", 0) + 1
            self._write()

        try:
            import requests as _req
            from app.api.routes.smart_watering import FIREBASE_BASE_URL
            _req.delete(f"{FIREBASE_BASE_URL}{FB_ROOT}/crosses/{cross_id}.json", timeout=8)
        except Exception:
            pass
        return record

    def crosses(self) -> list:
        return [self._decorate(c) for c in
                sorted(self._store["crosses"].values(),
                       key=lambda c: c["pollinatedAt"], reverse=True)]

    def cross(self, cross_id: str) -> dict:
        record = self._store["crosses"].get(cross_id)
        return self._decorate(record) if record else None

    def _decorate(self, record: dict) -> dict:
        """Add the derived fields the app shows but should not have to compute."""
        out = dict(record)
        out["photos"] = {
            "pod": (self._store["plants"].get(record["podPlantId"]) or {}).get("photo", ""),
            "pollen": (self._store["plants"].get(record["pollenPlantId"]) or {}).get("photo", ""),
        }

        try:
            started = datetime.fromisoformat(record["pollinatedAt"])
            days = (datetime.now(timezone.utc) - started).days
        except Exception:
            days = 0
        out["dayCount"] = max(days, 0)

        stage_def = STAGES[STAGE_INDEX.get(record.get("stage", "pollinated"), 0)]
        out["stageLabel"] = stage_def["label"]
        out["gateQuestion"] = stage_def["gate"]
        out["closed"] = bool(record.get("outcome"))
        out["outcomeLabel"] = EXITS.get(record.get("outcome", ""), {}).get("label", "")

        # Overdue only means "worth asking about", never "failed".
        due = stage_def["due_days"]
        out["dueInDays"] = (due - days) if (due is not None and not out["closed"]) else None
        out["overdue"] = bool(out["dueInDays"] is not None and out["dueInDays"] <= 0)
        return out

    # ── counts ────────────────────────────────
    def stats(self) -> dict:
        """
        Counts, and a rate only once there is enough to justify one.

        Every gate reports its numerator AND denominator. A rate without the
        denominator behind it is the single easiest way to turn three records
        into a claim they cannot support, so below MIN_N_FOR_RATE the rate is
        omitted entirely rather than shown with a caveat nobody reads.
        """
        records = list(self._store["crosses"].values())
        open_records = [c for c in records if not c.get("outcome")]
        lost = [c for c in records if c.get("outcome") == "lost"]

        gates = []
        for gate in GATES:
            reached_idx = STAGE_INDEX[gate["reached"]]

            # Censored records - still running, or lost - are in neither the
            # numerator nor the denominator. Counting an unfinished cross as a
            # failure is the mistake that would make every number here wrong.
            passed = failed = 0
            for c in records:
                if c.get("outcome") == "lost":
                    continue
                if STAGE_INDEX.get(c.get("stage", "pollinated"), 0) >= reached_idx:
                    passed += 1
                elif GATE_OF_EXIT.get(c.get("outcome", "")) == gate["key"]:
                    failed += 1

            n = passed + failed
            entry = {
                "key": gate["key"], "label": gate["label"],
                "question": gate["question"],
                "passed": passed, "failed": failed, "n": n,
                "rate": None,
                "statement": f"{passed} of {n}" if n else "no completed attempts yet",
            }
            if n >= MIN_N_FOR_RATE:
                entry["rate"] = round(passed / n, 3)
            gates.append(entry)

        return {
            "total": len(records),
            "open": len(open_records),
            "lost": len(lost),
            "deleted": self._store.get("deleted", 0),
            "gates": gates,
            "minNForRate": MIN_N_FOR_RATE,
            "note": "Counts only. The register records successes alone, so this "
                    "logbook exists to collect the failures it cannot hold. "
                    "Rates appear once a gate has at least "
                    f"{MIN_N_FOR_RATE} completed attempts behind it.",
        }

    def reference(self) -> dict:
        """The stage pipeline and exit vocabulary, so the app never hardcodes it."""
        return {"stages": STAGES, "exits": EXITS, "gates": GATES,
                "fieldHelp": FIELD_HELP}


cross_log_service = CrossLogService()
