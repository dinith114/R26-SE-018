"""
disease_contributions.py -- contributed photographs, expert review, and the rule
that decides when a new disease has enough evidence to be trained.

Why this exists (PP2 panel)
---------------------------
The first version let whoever uploaded a photograph tick "confirmed by an
institute" on it, and counted every ticked photograph toward the 30 a new class
needs. One person could fill the counter alone. Now:

  1. Every contribution is tied to the SIGNED-IN account that sent it
     (app.api.deps.require_auth). Reinstalling the app does not change it.
  2. A photograph counts only once an EXPERT approves it. Experts are a short
     list kept on the server -- the DISEASE_EXPERTS environment variable and/or
     ml-models/disease_detection/data/experts.txt -- never in the app, so no
     phone can promote anyone.
  3. A disease needs 30 approved photographs from AT LEAST 3 DIFFERENT
     ACCOUNTS, and near-identical photographs count once.
  4. Every decision is appended to review_log.jsonl and never edited, so who
     approved what, and when, can always be shown.

Photographs too small, dark or blurred for anyone to judge are refused at
upload (src/photo_checks.py; its limits were measured on the 667 dataset
photographs), so the expert's time goes on photographs that can be judged.

Before a photograph reaches the expert, the live diagnosis model also looks at
it, and the name typed for it is checked:

  * a LEAF photo unlike every orchid leaf the model was trained on is refused
    (the same distance check, and limit, that Check a plant uses). Stem and
    flower photos are only marked for the expert, because that check learned
    from leaves alone and would turn genuine stems and flowers away.
  * a leaf photo the model is very sure shows a disease it ALREADY detects
    needs the grower to say it is something different; it is then sent, and
    the expert sees what the model thought.
  * a name the app already detects ("black spot", "phylosticta") or one too
    general to count ("leaf spot") is refused, with the reason.

The app runs these the moment a photo is chosen (check_photo, check_name) and
the server applies them again when the photo is sent, so no app build can skip
them.

Reaching the counter makes retraining POSSIBLE, not automatic: a person runs
it, and the new model replaces the live one only if the diseases it already
knows do not get worse.

Storage
-------
  data/pending/contributions.csv    one row per photograph, its current state
  data/pending/<disease>/<id>.jpg   the photograph, stored as an ORIGINAL
  data/pending/review_log.jsonl     every expert decision, append-only

Small files under one lock rather than a database: there are tens of
contributions, not millions, and both files can be opened and read at the viva.
"""

import base64
import csv
import difflib
import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from io import BytesIO

from app.services import disease_service as ds

# disease_service has put ml-models/disease_detection/src on sys.path. The
# checks live there so the measuring script and the server run the same code.
import photo_checks as pc  # noqa: E402

PENDING = ds.PENDING
CSV_PATH = PENDING / "contributions.csv"
LOG_PATH = PENDING / "review_log.jsonl"
EXPERTS_FILE = ds.COMPONENT / "data" / "experts.txt"
EXPERTS_ENV = "DISEASE_EXPERTS"

# A new class may not be trained until it has this many approved originals.
# 30 photographs copied 54 times are still only 30 photographs of information;
# fewer would teach the model a few leaves rather than the disease, and an
# under-trained class steals predictions from the classes that already work.
MIN_PHOTOS = 30
MIN_GROWERS = 3
# Keeps one account from burying the expert's queue. Generous for a real grower.
DAILY_LIMIT = 25

# A contributed leaf photo the live model is at least this sure belongs to a
# class it already knows is probably not new. Stricter than the 0.70 Check a
# plant uses, because a wrong "already known" here would turn away exactly the
# new disease this screen exists to collect; even then the grower may send it.
LOOKS_KNOWN_CONFIDENCE = 0.90

# What growers type for the conditions the app already detects. Compared after
# lower-casing and dropping punctuation and filler words, and also when a
# letter or two is off ("phylosticta", "black lef spot").
KNOWN_NAMES = {
    "black_leaf_spot": ("black leaf spot", "black leaf spots", "black leafspot",
                        "black spot", "black spots", "bls"),
    "phyllosticta_leaf_spot": ("phyllosticta leaf spot", "phyllosticta leaf spots",
                               "phyllosticta"),
    "healthy": ("healthy", "no disease", "not diseased", "normal", "none"),
}
# A grower who names one of these could mean either known disease or a new
# one, so the photo could never be counted toward anything.
TOO_GENERAL = {"leaf spot", "leaf spots", "spot", "spots", "fungus", "fungal",
               "fungi", "rot", "blight"}
_FILLER = {"disease", "diseases", "infection", "orchid", "orchids", "vanda",
           "the", "a", "an", "of", "on", "in"}
SIMILAR_NAME = 0.88       # typo tolerance for the names above
SUGGEST_NAME = 0.80       # looser: only suggests a name already being collected

log = logging.getLogger(__name__)

PENDING_STATUS = "pending"
APPROVED = "approved"
CORRECTED = "corrected"          # approved, with the expert's labels
REJECTED = "rejected"
COUNTED = {APPROVED, CORRECTED}

REJECT_REASONS = {
    "wrong_disease": "Not this disease",
    "unclear": "Too unclear to judge",
    "not_orchid": "Not an orchid",
    "duplicate": "Same plant already sent",
    "other": "Other reason",
}

FIELDS = [
    "image_id", "disease", "plant_part", "severity",
    "status", "final_disease", "final_plant_part", "final_severity",
    "contributor_uid", "contributor_tenant", "claimed_confirmed_by",
    "submitted_at", "notes", "original_filename",
    "sha256", "dhash", "width", "height", "brightness", "sharpness",
    "reviewed_by", "reviewed_at", "review_reason", "review_note",
    # What the live model made of the photo when it was sent (empty on rows
    # from before this check existed).
    "model_check", "model_guess", "model_confidence", "orchid_distance",
]

_lock = threading.RLock()


class PhotoRefused(ValueError):
    """The photograph fails a quality check; `problems` holds (code, message)."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__(" ".join(message for _, message in problems))


class DuplicatePhoto(ValueError):
    pass


class TooManyContributions(ValueError):
    pass


class NotFound(LookupError):
    pass


class SelfReview(PermissionError):
    pass


class KnownDisease(ValueError):
    """The typed name is a condition the app already detects, or too general."""


class LooksKnown(ValueError):
    """The model is very sure the photo shows something the app already detects."""

    def __init__(self, message, guess, confidence):
        self.guess = guess
        self.confidence = confidence
        super().__init__(message)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _display(slug):
    return (slug or "unknown").replace("_", " ").title()


def _photo_path(row):
    # Stored under the disease it was SUBMITTED as; a correction changes the
    # label in the CSV, never the file's location.
    return PENDING / row["disease"] / (row["image_id"] + ".jpg")


# ---------------------------------------------------------------------------
# the expert list
# ---------------------------------------------------------------------------

def expert_entries():
    """Emails (anything with an @) and account uids allowed to review."""
    entries = set()
    for part in os.environ.get(EXPERTS_ENV, "").replace(";", ",").split(","):
        if part.strip():
            entries.add(part.strip())
    if EXPERTS_FILE.exists():
        for line in EXPERTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                entries.add(line)
    return entries


def is_expert(ctx):
    """Re-read on every call, so adding an expert needs no restart."""
    if ctx is None:
        return False
    email = (ctx.email or "").strip().lower()
    for entry in expert_entries():
        if "@" in entry:
            if email and email == entry.lower():
                return True
        elif ctx.uid == entry:
            return True
    return False


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

def _fingerprint(row):
    """Fill fingerprint and quality columns from the stored photograph."""
    path = _photo_path(row)
    if not path.exists():
        return
    try:
        data = path.read_bytes()
        img = pc.open_image(data)
    except Exception:                                            # noqa: BLE001
        return
    m = pc.measure(img)
    row.update(sha256=pc.sha256(data), dhash=pc.dhash(img), width=m["width"],
               height=m["height"], brightness=m["brightness"], sharpness=m["sharpness"])


def _migrate(row):
    """
    A row from before expert review. It was 'verified' by the person who sent
    it, which is exactly what could not be trusted, so it goes back to waiting
    for an expert. The claim is kept, as information for the expert.
    """
    claimed = (row.get("verified_by") or "").strip() \
        if (row.get("verified") or "").strip().lower() == "true" else ""
    row.update(status=PENDING_STATUS, final_disease=row.get("disease", ""),
               final_plant_part=row.get("plant_part", ""),
               final_severity=row.get("severity", ""),
               contributor_uid="", contributor_tenant="", claimed_confirmed_by=claimed)
    _fingerprint(row)


def _save(rows):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, CSV_PATH)       # a crash mid-write cannot corrupt the file


def _load():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    migrated = False
    for row in rows:
        if not row.get("status"):
            _migrate(row)
            migrated = True
        for key in FIELDS:
            if row.get(key) is None:
                row[key] = ""
    if migrated:
        _save(rows)
    return rows


def _append_log(entry):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _next_id(slug, rows):
    used = [r["image_id"] for r in rows if r["disease"] == slug]
    folder = PENDING / slug
    if folder.is_dir():
        used += [p.stem for p in folder.glob("*.jpg")]
    numbers = [int(i.rsplit("_", 1)[1]) for i in used if i.rsplit("_", 1)[-1].isdigit()]
    return "{}_{:04d}".format(slug, max(numbers, default=0) + 1)


def _data_uri(raw):
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _thumbnail(row, side=200):
    path = _photo_path(row)
    if not path.exists():
        return None
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((side, side))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=75)
    return _data_uri(buf.getvalue())


# ---------------------------------------------------------------------------
# the counter rule
# ---------------------------------------------------------------------------

def _distinct_photos(rows):
    """How many photographs remain once near-identical ones are merged."""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i]["dhash"], rows[j]["dhash"]
            if a and b and pc.distance(a, b) <= pc.COPY_DISTANCE:
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(rows))})


def _progress(rows):
    names = {r["final_disease"] if r["status"] in COUNTED else r["disease"] for r in rows}
    out = {}
    for d in sorted(n for n in names if n):
        approved = [r for r in rows if r["status"] in COUNTED and r["final_disease"] == d]
        unique = _distinct_photos(approved)
        # Rows from before sign-in existed have no account; together they count
        # as one grower, never as several.
        growers = len({r["contributor_uid"] or "before-sign-in" for r in approved})
        needed = max(0, MIN_PHOTOS - unique)
        growers_needed = max(0, MIN_GROWERS - growers)
        blockers = []
        if needed:
            blockers.append("{} more approved photo{}".format(needed, "" if needed == 1 else "s"))
        if growers_needed:
            blockers.append("photos from {} more grower{}".format(
                growers_needed, "" if growers_needed == 1 else "s"))
        out[d] = {
            "disease": d,
            "display_name": _display(d),
            "approved": len(approved),
            "approved_unique": unique,
            "growers": growers,
            "waiting": sum(1 for r in rows if r["status"] == PENDING_STATUS and r["disease"] == d),
            "rejected": sum(1 for r in rows if r["status"] == REJECTED and r["disease"] == d),
            "needed": needed,
            "growers_needed": growers_needed,
            "ready_for_training": not blockers,
            "blockers": blockers,
            # App builds from before expert review read these two.
            "verified": unique,
            "total": sum(1 for r in rows if d in (r["disease"], r["final_disease"])),
        }
    return out


RULES = [
    "Only photographs approved by an orchid expert count.",
    "A disease needs {} approved photographs from at least {} different "
    "accounts.".format(MIN_PHOTOS, MIN_GROWERS),
    "Near-identical photographs count once.",
]


def counts():
    with _lock:
        rows = _load()
    progress = _progress(rows)
    return {
        "minimum_required": MIN_PHOTOS,
        "minimum_growers": MIN_GROWERS,
        "diseases": sorted(progress.values(),
                           key=lambda e: (-e["approved_unique"], -e["waiting"], e["disease"])),
        "total_contributions": len(rows),
        "rules": RULES,
        "note": ("Reaching the target makes retraining possible, not automatic. A "
                 "person runs it, and the new model replaces the current one only if "
                 "the diseases it already knows do not get worse."),
    }


# ---------------------------------------------------------------------------
# what each side sees
# ---------------------------------------------------------------------------

def _status_text(row):
    if row["status"] == PENDING_STATUS:
        return "Waiting for expert review"
    if row["status"] == APPROVED:
        return "Approved by an expert"
    if row["status"] == CORRECTED:
        changes = []
        if row["final_disease"] != row["disease"]:
            changes.append(_display(row["final_disease"]))
        if row["final_plant_part"] != row["plant_part"]:
            changes.append(row["final_plant_part"])
        if row["final_severity"] != row["severity"]:
            changes.append(row["final_severity"])
        return "Approved, corrected to {}".format(", ".join(changes))
    return "Not accepted: {}".format(
        REJECT_REASONS.get(row["review_reason"], "see the expert's note").lower())


def _number(value):
    try:
        return float(value) if "." in str(value) else int(value)
    except (TypeError, ValueError):
        return None


def _grower_view(row, thumbnail=True):
    return {
        "image_id": row["image_id"],
        "disease": row["disease"], "display_name": _display(row["disease"]),
        "plant_part": row["plant_part"], "severity": row["severity"],
        "status": row["status"], "status_text": _status_text(row),
        "counts": row["status"] in COUNTED,
        "final_disease": row["final_disease"], "final_display_name": _display(row["final_disease"]),
        "final_plant_part": row["final_plant_part"], "final_severity": row["final_severity"],
        "submitted_at": row["submitted_at"], "reviewed_at": row["reviewed_at"],
        "review_reason": row["review_reason"],
        "review_reason_text": REJECT_REASONS.get(row["review_reason"], ""),
        "review_note": row["review_note"],
        "thumbnail": _thumbnail(row) if thumbnail else None,
    }


def _grower_label(uid):
    if not uid:
        return "Sent before sign-in"
    return "Grower " + hashlib.sha256(uid.encode("utf-8")).hexdigest()[:5].upper()


def _copies_of(row, rows):
    if not row["dhash"]:
        return []
    out = []
    for other in rows:
        if other["image_id"] != row["image_id"] and other["dhash"]:
            d = pc.distance(row["dhash"], other["dhash"])
            if d <= pc.COPY_DISTANCE:
                out.append({"image_id": other["image_id"], "status": other["status"], "bits": d})
    return sorted(out, key=lambda c: c["bits"])


def _expert_view(row, rows, thumbnail=True):
    same = [r for r in rows if r["contributor_uid"] == row["contributor_uid"]]
    view = _grower_view(row, thumbnail)
    view.update({
        "grower": _grower_label(row["contributor_uid"]),
        "grower_photos": len(same),
        "grower_photos_this_disease": sum(1 for r in same if r["disease"] == row["disease"]),
        "claimed_confirmed_by": row["claimed_confirmed_by"],
        "notes": row["notes"],
        "quality": {k: _number(row[k]) for k in ("width", "height", "brightness", "sharpness")},
        "possible_copies": _copies_of(row, rows),
        "reviewed_by": row["reviewed_by"],
        "model_check": {
            "status": row.get("model_check") or "",
            "text": _model_check_text(row),
            "guess": row.get("model_guess") or None,
            "confidence": _number(row.get("model_confidence")),
            "orchid_distance": _number(row.get("orchid_distance")),
        },
    })
    return view


def mine(uid):
    """The signed-in grower's own photographs, newest first."""
    with _lock:
        rows = _load()
    own = sorted((r for r in rows if r["contributor_uid"] == uid),
                 key=lambda r: r["submitted_at"], reverse=True)
    return [_grower_view(r) for r in own]


def queue(status=PENDING_STATUS):
    """
    The expert's lists. 'approved' includes corrected photographs.
    Waiting photographs come oldest first, so none is left behind.
    """
    with _lock:
        rows = _load()
    if status == "all":
        chosen = list(rows)
    elif status == APPROVED:
        chosen = [r for r in rows if r["status"] in COUNTED]
    else:
        chosen = [r for r in rows if r["status"] == status]
    if status == PENDING_STATUS:
        chosen.sort(key=lambda r: r["submitted_at"])
    else:
        chosen.sort(key=lambda r: r["reviewed_at"] or r["submitted_at"], reverse=True)
    return [_expert_view(r, rows) for r in chosen]


def item(image_id):
    with _lock:
        rows = _load()
    row = next((r for r in rows if r["image_id"] == image_id), None)
    if row is None:
        raise NotFound("No contributed photograph called {}.".format(image_id))
    view = _expert_view(row, rows, thumbnail=False)
    path = _photo_path(row)
    view["photo"] = _data_uri(path.read_bytes()) if path.exists() else None
    by_id = {r["image_id"]: r for r in rows}
    for c in view["possible_copies"]:
        c["thumbnail"] = _thumbnail(by_id[c["image_id"]])
    view["history"] = [e for e in decisions(limit=None) if e["image_id"] == image_id]
    return view


def decisions(limit=50):
    """The decision log, newest first."""
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    entries.reverse()
    return entries if limit is None else entries[:limit]


# ---------------------------------------------------------------------------
# checks before the expert sees a photograph
# ---------------------------------------------------------------------------

NOT_ORCHID = ("It doesn't look like an orchid leaf. Send a clear photo of the "
              "affected orchid leaf.")


def _words(name):
    s = re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
    return " ".join(w for w in s.split() if w not in _FILLER)


def _similar(a, b):
    return difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()


def known_disease_for(name):
    """The class the app already detects that a typed name refers to, or None."""
    words = _words(name)
    if not words:
        return None
    for slug, aliases in KNOWN_NAMES.items():
        for alias in aliases:
            a = _words(alias)
            if words == a:
                return slug
            if len(words.replace(" ", "")) >= 6 and _similar(words, a) >= SIMILAR_NAME:
                return slug
    # "Phyllosticta capitalensis" names the fungus behind Phyllosticta Leaf
    # Spot, and a "healthy leaf" is still a healthy leaf.
    first = words.split()[0]
    if _similar(first, "phyllosticta") >= SIMILAR_NAME:
        return "phyllosticta_leaf_spot"
    if first == "healthy":
        return "healthy"
    return None


def _name_problem(name):
    """Why a typed disease name cannot be used, or None when it can."""
    if not (name or "").strip():
        return None                      # _clean_labels reports a missing name
    words = _words(name)
    if not words or words in TOO_GENERAL:
        return ("'{}' is too general to count toward a new disease. Give the "
                "condition its own name, for example Anthracnose.".format(name.strip()))
    known = known_disease_for(name)
    if known == "healthy":
        return "Contribute is for diseases. Check a plant already handles healthy leaves."
    if known:
        return ("The app already detects {}. Use Check a plant for it: Contribute is "
                "for conditions the app does not know yet.".format(_display(known)))
    return None


def check_name(name):
    """What Contribute shows under the name field while the grower types."""
    name = (name or "").strip()
    problem = _name_problem(name)
    known = known_disease_for(name) if problem else None
    out = {"name": name, "ok": problem is None, "message": problem,
           "known": known, "known_display_name": _display(known) if known else None,
           "already_collecting": False, "similar": []}
    if problem or not name:
        return out
    with _lock:
        rows = _load()
    slug = ds._slug(name)
    names = {r["final_disease"] if r["status"] in COUNTED else r["disease"] for r in rows} - {""}
    out["already_collecting"] = slug in names
    # Offered, never applied: "Anthracnos" and "Anthracnose" would otherwise be
    # counted as two diseases, but only the grower knows which one they mean.
    close = sorted(((_similar(slug, n), n) for n in names if n != slug), reverse=True)
    out["similar"] = [{"disease": n, "display_name": _display(n)}
                      for score, n in close if score >= SUGGEST_NAME][:3]
    return out


def assess_photo(image_bytes):
    """
    What the live diagnosis model makes of a photograph: is it like the orchid
    photos it was trained on, and what does it think the photo shows?

    Runs Check a plant's own cascade (src/disease_predict.py), unchanged, and
    reads only its first two stages. Returns None when the model cannot run on
    this server -- no TensorFlow, or no model files: the photo is then still
    checked for quality and still reviewed by an expert, so a server without the
    model degrades instead of refusing every contribution.
    """
    try:
        if not ds.model_status()["disease_ready"]:
            return None
        result = ds._cascade().predict(image_bytes, models_dir=ds.MODELS,
                                       threshold=ds.DEFAULT_THRESHOLD,
                                       include_treatment=False)
    except Exception as exc:                                     # noqa: BLE001
        log.warning("contributed photo not checked by the model: %s", exc)
        return None
    is_orchid = result.get("valid_orchid_image") is not False
    confidence = result.get("confidence")
    return {
        "is_orchid": is_orchid,
        "distance": result.get("validation_distance"),
        "distance_limit": result.get("validation_threshold"),
        # The cascade itself withholds a class for a photo that is not an orchid.
        "guess": result.get("raw_prediction") if is_orchid else None,
        "confidence": None if confidence is None else round(float(confidence), 4),
    }


def _verdict(assessment, part):
    """
    What happens to a photo sent as `part`, with the sentence the grower sees:

      refuse       a leaf photo unlike every orchid leaf the model knows
      confirm      the model is very sure it shows something the app already
                   detects, so the grower must say it is a different disease
      note         a stem or flower photo unlike the leaf-only training photos:
                   accepted, and marked for the expert
      ok
      not_checked  the model could not run on this server
    """
    leaf = (part or "leaf") == "leaf"
    if assessment is None:
        return "not_checked", None
    if not assessment["is_orchid"]:
        if leaf:
            return "refuse", NOT_ORCHID
        return "note", ("Unlike the orchid leaf photos the model knows. That is expected "
                        "for a {}, and the expert will check it.".format(part))
    guess, confidence = assessment["guess"], assessment["confidence"]
    if (leaf and guess in KNOWN_NAMES and confidence is not None
            and confidence >= LOOKS_KNOWN_CONFIDENCE):
        if guess == "healthy":
            return "confirm", ("This leaf looks healthy to the app ({:.0f}% sure). If it "
                               "has a problem, send it anyway and describe it in the "
                               "notes.".format(confidence * 100))
        return "confirm", ("This looks like {} ({:.0f}% sure), which the app already "
                           "detects. Use Check a plant for it, or send it if you are sure "
                           "it is a different disease.".format(_display(guess),
                                                               confidence * 100))
    return "ok", None


def check_photo(image_bytes, disease="", plant_part=""):
    """
    Everything Contribute can tell the grower the moment a photo is chosen,
    before the rest of the form is filled in. submit() applies the same rules
    again, so skipping this check gets a photo nowhere.

    The verdict is given for every plant part, so the app can follow the
    grower's choice of part without sending the photo a second time.
    """
    try:
        img = pc.cap_size(pc.open_image(image_bytes))
    except ImportError as exc:                                   # pragma: no cover
        raise ds.ModelUnavailable("Pillow is required to read images: {}".format(exc))
    except Exception as exc:                                     # noqa: BLE001
        raise ds.InvalidImage("Could not read that image: {}".format(exc))
    problems = pc.problems(pc.measure(img))
    # A photo too dark or blurred to judge is refused whatever the model thinks.
    assessment = None if problems else assess_photo(image_bytes)
    digest = pc.sha256(image_bytes)
    with _lock:
        rows = _load()

    guess = None
    if assessment and assessment["guess"] in KNOWN_NAMES and assessment["confidence"] is not None:
        guess = {"disease": assessment["guess"], "display_name": _display(assessment["guess"]),
                 "confidence": assessment["confidence"]}
    by_part = {}
    for part in sorted(ds.VALID_PARTS):
        verdict, message = _verdict(assessment, part)
        by_part[part] = {"verdict": verdict, "message": message}
    return {
        "quality_ok": not problems,
        "problems": [{"code": code, "message": message} for code, message in problems],
        "already_sent": any(r["sha256"] == digest for r in rows),
        "checked_by_model": assessment is not None,
        "is_orchid": None if assessment is None else assessment["is_orchid"],
        "model_guess": guess,
        "by_part": by_part,
        "name": check_name(disease) if (disease or "").strip() else None,
    }


def _model_check_text(row):
    """One sentence for the expert about what the model made of the photo."""
    check = row.get("model_check") or ""
    guess = row.get("model_guess") or ""
    confidence = _number(row.get("model_confidence"))
    pct = "" if confidence is None else " ({:.0f}%)".format(confidence * 100)
    if check == "sent_anyway":
        return ("The model thinks this is {}{}; the grower says it is a different "
                "disease.".format(_display(guess), pct))
    if check == "note":
        return "Unlike the orchid leaf photos the model knows (sent as a {}).".format(
            row["plant_part"])
    if check == "not_checked":
        return "Not checked by the model: it was not running when this was sent."
    if check == "ok":
        if guess:
            return "An orchid photo the model does not recognise well (best guess {}{}).".format(
                _display(guess), pct)
        return "An orchid photo the model does not recognise well."
    return ""


# ---------------------------------------------------------------------------
# the two actions
# ---------------------------------------------------------------------------

def _clean_labels(disease, plant_part, severity):
    slug = ds._slug(disease)
    if not slug:
        raise ds.InvalidContribution("A disease name is required.")
    part = (plant_part or "").strip().lower()
    grade = (severity or "").strip().lower()
    if part not in ds.VALID_PARTS:
        raise ds.InvalidContribution(
            "Plant part must be one of {}.".format(", ".join(sorted(ds.VALID_PARTS))))
    if grade not in ds.VALID_SEVERITIES:
        raise ds.InvalidContribution(
            "Severity must be one of {}.".format(", ".join(sorted(ds.VALID_SEVERITIES))))
    return slug, part, grade


def submit(image_bytes, *, disease, plant_part, severity, contributor,
           notes="", original_filename="", claimed_confirmed_by="", confirmed_new=False):
    """
    Check and store one photograph. It joins the queue as 'pending' and counts
    for nothing until an expert approves it.

    `confirmed_new` is the grower saying a photo the model takes for a disease
    the app already knows is something different; without it such a photo is
    refused with LooksKnown, so the app can ask.

    Stored as an ORIGINAL and never augmented here: augmenting before the
    train / test split would put variants of one leaf on both sides of it.
    """
    slug, part, grade = _clean_labels(disease, plant_part, severity)
    problem = _name_problem(disease)
    if problem:
        raise KnownDisease(problem)
    try:
        img = pc.cap_size(pc.open_image(image_bytes))
    except ImportError as exc:                                   # pragma: no cover
        raise ds.ModelUnavailable("Pillow is required to store images: {}".format(exc))
    except Exception as exc:                                     # noqa: BLE001
        raise ds.InvalidImage("Could not read that image: {}".format(exc))

    measured = pc.measure(img)
    problems = pc.problems(measured)
    if problems:
        raise PhotoRefused(problems)
    digest, fingerprint = pc.sha256(image_bytes), pc.dhash(img)

    # Outside the lock: the model takes a moment, and the files need not wait.
    assessment = assess_photo(image_bytes)
    verdict, message = _verdict(assessment, part)
    if verdict == "refuse":
        raise PhotoRefused([("not_orchid", message)])
    if verdict == "confirm" and not confirmed_new:
        raise LooksKnown(message, assessment["guess"], assessment["confidence"])

    with _lock:
        rows = _load()
        same = next((r for r in rows if r["sha256"] == digest), None)
        if same:
            when = same["submitted_at"][:10]
            if same["contributor_uid"] == contributor.uid:
                raise DuplicatePhoto("You already sent this exact photo on {}.".format(when))
            raise DuplicatePhoto("This exact photo has already been sent.")
        today = datetime.now(timezone.utc).date().isoformat()
        sent_today = sum(1 for r in rows if r["contributor_uid"] == contributor.uid
                         and r["submitted_at"].startswith(today))
        if sent_today >= DAILY_LIMIT:
            raise TooManyContributions(
                "You have sent {} photos today, the daily limit. Please send the rest "
                "tomorrow.".format(sent_today))

        image_id = _next_id(slug, rows)
        (PENDING / slug).mkdir(parents=True, exist_ok=True)
        img.save(PENDING / slug / (image_id + ".jpg"), "JPEG", quality=92, optimize=True)
        row = {
            "image_id": image_id, "disease": slug, "plant_part": part, "severity": grade,
            "status": PENDING_STATUS,
            "final_disease": slug, "final_plant_part": part, "final_severity": grade,
            "contributor_uid": contributor.uid, "contributor_tenant": contributor.tenant_id,
            "claimed_confirmed_by": (claimed_confirmed_by or "").strip()[:200],
            "submitted_at": _now(), "notes": (notes or "").strip()[:1000],
            "original_filename": (original_filename or "").strip()[:200],
            "sha256": digest, "dhash": fingerprint,
            "width": measured["width"], "height": measured["height"],
            "brightness": measured["brightness"], "sharpness": measured["sharpness"],
            "reviewed_by": "", "reviewed_at": "", "review_reason": "", "review_note": "",
            "model_check": "sent_anyway" if verdict == "confirm" else verdict,
            "model_guess": (assessment or {}).get("guess") or "",
            "model_confidence": "" if not assessment or assessment["confidence"] is None
            else assessment["confidence"],
            "orchid_distance": "" if not assessment or assessment["distance"] is None
            else assessment["distance"],
        }
        rows.append(row)
        _save(rows)
        copies = _copies_of(row, rows)
        progress = _progress(rows)[slug]

    return {
        "saved": True,
        "image_id": image_id,
        "disease": slug,
        "display_name": _display(slug),
        "status": PENDING_STATUS,
        "status_text": _status_text(row),
        "possible_copy": bool(copies),
        "model_check": row["model_check"],
        "progress": progress,
        "minimum_required": MIN_PHOTOS,
        "minimum_growers": MIN_GROWERS,
        # App builds from before expert review read these.
        "verified": False,
        "count_verified": progress["approved_unique"],
        "needed": progress["needed"],
        "ready_for_training": progress["ready_for_training"],
    }


def review(image_id, decision, *, expert, reason=None, note="",
           disease=None, plant_part=None, severity=None):
    """
    Record one expert decision:

      approve   the grower's labels are right
      correct   approve with the expert's labels (disease, part or severity)
      reject    not usable; one of REJECT_REASONS is required

    The CSV keeps the current state; the log gains one line that is never
    edited, holding the labels before and after.
    """
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "correct", "reject"):
        raise ds.InvalidContribution("Decision must be approve, correct or reject.")

    with _lock:
        rows = _load()
        row = next((r for r in rows if r["image_id"] == image_id), None)
        if row is None:
            raise NotFound("No contributed photograph called {}.".format(image_id))
        if row["contributor_uid"] and row["contributor_uid"] == expert.uid:
            raise SelfReview("You sent this photo yourself, so a different expert "
                             "must review it.")

        before = {k: row[k] for k in ("status", "final_disease", "final_plant_part",
                                      "final_severity")}
        if decision == "reject":
            if reason not in REJECT_REASONS:
                raise ds.InvalidContribution("Choose why the photo is not accepted.")
            row.update(status=REJECTED, review_reason=reason)
        elif decision == "approve":
            row.update(status=APPROVED, review_reason="", final_disease=row["disease"],
                       final_plant_part=row["plant_part"], final_severity=row["severity"])
        else:
            slug, part, grade = _clean_labels(disease or row["disease"],
                                              plant_part or row["plant_part"],
                                              severity or row["severity"])
            unchanged = (slug, part, grade) == (row["disease"], row["plant_part"], row["severity"])
            row.update(status=APPROVED if unchanged else CORRECTED, review_reason="",
                       final_disease=slug, final_plant_part=part, final_severity=grade)
        row.update(reviewed_by=expert.email or expert.uid, reviewed_at=_now(),
                   review_note=(note or "").strip()[:500])
        _save(rows)
        _append_log({
            "at": row["reviewed_at"],
            "image_id": image_id,
            "decision": decision,
            "reason": row["review_reason"],
            "note": row["review_note"],
            "expert_uid": expert.uid,
            "expert_email": expert.email,
            "before": before,
            "after": {k: row[k] for k in ("status", "final_disease", "final_plant_part",
                                          "final_severity")},
        })
        return _expert_view(row, rows)
