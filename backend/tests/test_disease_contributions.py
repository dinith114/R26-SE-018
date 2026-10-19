"""Contributed photographs: who may send, who may approve, and what counts.

These tests pin the answer to the PP2 panel's trust question. One person must
never be able to fill the counter that makes a new disease trainable, so:

  * sending a photograph needs a signed-in account, recorded with the photo
  * only an account on the server's expert list may approve, correct or reject
  * only approved photographs count, from at least three accounts, and
    near-identical photographs count once
  * every decision is appended to a log that is never rewritten
  * before the expert sees anything: a leaf photo unlike any orchid leaf is
    refused, a photo the model takes for a disease the app already detects
    needs the grower to say it is different, and a name the app already
    detects is refused

The live model is replaced by dc.assess_photo stubs: CI has no TensorFlow, and
these tests pin the rules, not the network.

Real routing through TestClient and a throwaway app, as test_auth_deps.py does,
with the token check replaced by firebase_auth.set_decoder. Storage goes to a
temporary folder, so nothing touches ml-models/disease_detection/data/pending.
"""
import csv
import json
import random
from io import BytesIO

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from app.api.routes import disease_detection  # noqa: E402
from app.services import disease_contributions as dc  # noqa: E402
from app.services.firebase_auth import set_decoder  # noqa: E402

PEOPLE = {
    "grower-1": {"uid": "g1", "tenantId": "t1", "role": "viewer", "email": "g1@farm.lk"},
    "grower-2": {"uid": "g2", "tenantId": "t1", "role": "operator", "email": "g2@farm.lk"},
    "grower-3": {"uid": "g3", "tenantId": "t2", "role": "admin", "email": "g3@farm.lk"},
    # Mixed case on purpose: the expert list must match emails case-insensitively.
    "expert": {"uid": "ex", "tenantId": "t1", "role": "viewer", "email": "Researcher@Lab.lk"},
}
API = "/api/v1/disease"


def _decode(token):
    if token not in PEOPLE:
        raise ValueError("unknown token")
    return dict(PEOPLE[token])


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "PENDING", tmp_path / "pending")
    monkeypatch.setattr(dc, "CSV_PATH", tmp_path / "pending" / "contributions.csv")
    monkeypatch.setattr(dc, "LOG_PATH", tmp_path / "pending" / "review_log.jsonl")
    monkeypatch.setattr(dc, "EXPERTS_FILE", tmp_path / "experts.txt")
    monkeypatch.setenv(dc.EXPERTS_ENV, "researcher@lab.lk")
    # As on a server without the model: the same answer with or without
    # TensorFlow installed. Tests about the model say what it sees.
    monkeypatch.setattr(dc, "assess_photo", lambda data: None)
    set_decoder(_decode)
    yield tmp_path
    set_decoder(None)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(disease_detection.router, prefix=API)
    return TestClient(app)


def auth(token):
    return {"Authorization": "Bearer " + token}


def photo(seed, size=(400, 300), dark=False, smooth=False, quality=95):
    """A JPEG that passes the quality checks unless told otherwise.

    Coarse random colour blocks give every seed its own difference hash; fine
    noise on top gives it the edges a sharp photograph has.
    """
    rng = np.random.default_rng(seed)
    blocks = rng.integers(70, 190, size=(6, 8, 3)).astype(np.uint8)
    a = np.asarray(Image.fromarray(blocks).resize(size, Image.BICUBIC), dtype=np.int16)
    if not smooth:
        a = a + rng.integers(-35, 36, size=a.shape)
    if dark:
        a = a // 8
    buf = BytesIO()
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def resaved(data, quality=60):
    buf = BytesIO()
    Image.open(BytesIO(data)).save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def send(client, token, data, disease="Anthracnose", part="leaf", severity="moderate", **extra):
    return client.post(
        API + "/contribute",
        headers=auth(token) if token else {},
        files={"image": ("leaf.jpg", data, "image/jpeg")},
        data={"disease": disease, "plant_part": part, "severity": severity, **extra},
    )


def decide(client, image_id, decision, token="expert", **body):
    return client.post("{}/review/items/{}".format(API, image_id),
                       headers=auth(token), json={"decision": decision, **body})


def progress(client, disease="anthracnose"):
    body = client.get(API + "/pending-counts").json()
    return next((d for d in body["diseases"] if d["disease"] == disease), None)


def csv_rows():
    with open(dc.CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------

def test_sending_a_photo_needs_sign_in(client):
    assert send(client, None, photo(1)).status_code == 401
    assert send(client, "forged", photo(1)).status_code == 401


def test_a_photo_is_tied_to_the_account_that_sent_it_and_waits(client):
    r = send(client, "grower-1", photo(1))
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["status"] == "pending"
    assert result["verified"] is False
    row = csv_rows()[0]
    assert (row["contributor_uid"], row["contributor_tenant"]) == ("g1", "t1")
    p = progress(client)
    assert (p["approved"], p["waiting"], p["ready_for_training"]) == (0, 1, False)


def test_ticking_confirmed_no_longer_makes_a_photo_count(client):
    # What an app build from before expert review sends.
    r = send(client, "grower-1", photo(1), verified="true", verified_by="Peradeniya")
    assert r.status_code == 200
    assert csv_rows()[0]["claimed_confirmed_by"] == "Peradeniya"
    assert progress(client)["approved"] == 0


@pytest.mark.parametrize("kind, words", [
    ("dark", "too dark"),
    ("blurred", "blurred"),
    ("small", "pixels"),
])
def test_unusable_photos_are_refused_with_a_reason(client, kind, words):
    data = {"dark": photo(2, dark=True), "blurred": photo(3, smooth=True),
            "small": photo(4, size=(150, 150))}[kind]
    r = send(client, "grower-1", data)
    assert r.status_code == 422, kind
    assert words in r.json()["detail"]
    assert not dc.CSV_PATH.exists()


def test_the_same_file_twice_is_refused(client):
    data = photo(5)
    assert send(client, "grower-1", data).status_code == 200
    again = send(client, "grower-1", data)
    assert again.status_code == 409
    assert "already sent" in again.json()["detail"]
    assert send(client, "grower-2", data).status_code == 409


def test_a_daily_limit_stops_one_account_burying_the_queue(client, monkeypatch):
    monkeypatch.setattr(dc, "DAILY_LIMIT", 2)
    assert send(client, "grower-1", photo(6)).status_code == 200
    assert send(client, "grower-1", photo(7)).status_code == 200
    assert send(client, "grower-1", photo(8)).status_code == 429
    assert send(client, "grower-2", photo(8)).status_code == 200


def test_growers_see_only_their_own_photos(client):
    mine = send(client, "grower-1", photo(9)).json()["result"]["image_id"]
    send(client, "grower-2", photo(10))
    r = client.get(API + "/contributions/mine", headers=auth("grower-1"))
    assert [c["image_id"] for c in r.json()["contributions"]] == [mine]
    assert client.get(API + "/contributions/mine").status_code == 401


# --------------------------------------------------------------------------
# who may review
# --------------------------------------------------------------------------

def test_only_an_expert_may_review(client):
    image_id = send(client, "grower-1", photo(11)).json()["result"]["image_id"]
    for token in ("grower-1", "grower-3"):          # grower-3 is a farm ADMIN
        assert client.get(API + "/review/queue", headers=auth(token)).status_code == 403
        assert client.get(API + "/review/items/" + image_id, headers=auth(token)).status_code == 403
        assert client.get(API + "/review/log", headers=auth(token)).status_code == 403
        assert decide(client, image_id, "approve", token=token).status_code == 403
    assert client.get(API + "/review/queue").status_code == 401
    assert client.get(API + "/review/queue", headers=auth("expert")).status_code == 200
    assert client.get(API + "/review/whoami", headers=auth("expert")).json()["expert"] is True
    assert client.get(API + "/review/whoami", headers=auth("grower-3")).json()["expert"] is False


def test_the_expert_list_takes_emails_or_uids_from_the_env_or_a_file(monkeypatch):
    from app.services.firebase_auth import AuthContext
    monkeypatch.setenv(dc.EXPERTS_ENV, "")
    someone = AuthContext(uid="u42", tenant_id="t1", role="viewer", email="Doc@Inst.lk")
    assert not dc.is_expert(someone)
    dc.EXPERTS_FILE.write_text("# orchid researchers\ndoc@inst.lk   # by email\n", encoding="utf-8")
    assert dc.is_expert(someone)
    dc.EXPERTS_FILE.write_text("u42\n", encoding="utf-8")
    assert dc.is_expert(someone)
    dc.EXPERTS_FILE.write_text("U42\n", encoding="utf-8")       # uids are exact
    assert not dc.is_expert(someone)


def test_an_expert_cannot_approve_their_own_photo(client):
    image_id = send(client, "expert", photo(12)).json()["result"]["image_id"]
    r = decide(client, image_id, "approve")
    assert r.status_code == 409
    assert progress(client)["approved"] == 0


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------

def test_approve_correct_and_reject_are_logged_and_never_rewritten(client):
    ids = [send(client, t, photo(s)).json()["result"]["image_id"]
           for t, s in (("grower-1", 13), ("grower-2", 14), ("grower-3", 15))]

    assert decide(client, ids[0], "approve").json()["item"]["status"] == "approved"
    fixed = decide(client, ids[1], "correct", disease="Phytophthora black rot",
                   plant_part="stem", severity="severe", note="Rot, not anthracnose").json()["item"]
    assert fixed["status"] == "corrected"
    assert (fixed["final_disease"], fixed["final_plant_part"], fixed["final_severity"]) == (
        "phytophthora_black_rot", "stem", "severe")
    gone = decide(client, ids[2], "reject", reason="unclear").json()["item"]
    assert gone["status"] == "rejected" and "unclear" in gone["status_text"]

    first = dc.LOG_PATH.read_text(encoding="utf-8")
    entries = [json.loads(line) for line in first.splitlines()]
    assert [e["decision"] for e in entries] == ["approve", "correct", "reject"]
    assert entries[1]["before"]["final_disease"] == "anthracnose"
    assert entries[1]["after"]["final_disease"] == "phytophthora_black_rot"
    assert entries[0]["expert_email"] == "Researcher@Lab.lk"

    decide(client, ids[2], "approve")              # the expert changes their mind
    second = dc.LOG_PATH.read_text(encoding="utf-8")
    assert second.startswith(first)                # appended, nothing rewritten
    assert len(second.splitlines()) == 4

    log = client.get(API + "/review/log", headers=auth("expert")).json()["decisions"]
    assert log[0]["image_id"] == ids[2] and log[0]["decision"] == "approve"

    mine = client.get(API + "/contributions/mine", headers=auth("grower-2")).json()["contributions"]
    assert mine[0]["status_text"].startswith("Approved, corrected to Phytophthora Black Rot")
    assert mine[0]["review_note"] == "Rot, not anthracnose"


def test_a_rejection_needs_a_reason(client):
    image_id = send(client, "grower-1", photo(16)).json()["result"]["image_id"]
    assert decide(client, image_id, "reject").status_code == 422
    assert decide(client, image_id, "reject", reason="made-up").status_code == 422


def test_a_correction_moves_the_photo_to_the_corrected_disease(client):
    image_id = send(client, "grower-1", photo(17)).json()["result"]["image_id"]
    decide(client, image_id, "correct", disease="Sunburn")
    assert progress(client, "sunburn")["approved"] == 1
    old = progress(client, "anthracnose")
    assert old is None or old["approved"] == 0


def test_a_resaved_copy_is_flagged_for_the_expert_and_counted_once(client):
    original = photo(18)
    first = send(client, "grower-1", original).json()["result"]
    second = send(client, "grower-2", resaved(original)).json()["result"]
    assert first["possible_copy"] is False and second["possible_copy"] is True

    item = client.get(API + "/review/items/" + second["image_id"], headers=auth("expert")).json()["item"]
    assert [c["image_id"] for c in item["possible_copies"]] == [first["image_id"]]
    assert item["photo"].startswith("data:image/jpeg;base64,")

    decide(client, first["image_id"], "approve")
    decide(client, second["image_id"], "approve")
    p = progress(client)
    assert (p["approved"], p["approved_unique"]) == (2, 1)


# --------------------------------------------------------------------------
# the counter rule, on prepared records
# --------------------------------------------------------------------------

def _records(n, growers, status="approved", disease="anthracnose", seed=0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        row = {k: "" for k in dc.FIELDS}
        row.update(image_id="{}_{:04d}".format(disease, seed * 1000 + i), disease=disease,
                   plant_part="leaf", severity="mild", status=status, final_disease=disease,
                   final_plant_part="leaf", final_severity="mild",
                   contributor_uid=growers[i % len(growers)],
                   submitted_at="2026-10-13T00:00:00+00:00",
                   dhash="{:016x}".format(rng.getrandbits(64)))
        out.append(row)
    return out


def _counted(rows):
    dc._save(rows)
    return dc.counts()["diseases"][0]


def test_thirty_approved_photos_from_one_account_are_not_enough():
    p = _counted(_records(30, ["g1"]))
    assert p["approved_unique"] == 30 and p["growers"] == 1
    assert p["ready_for_training"] is False
    assert p["blockers"] == ["photos from 2 more growers"]


def test_thirty_approved_photos_from_three_accounts_are_enough():
    p = _counted(_records(30, ["g1", "g2", "g3"]))
    assert p["ready_for_training"] is True and p["blockers"] == []


def test_waiting_and_rejected_photos_never_count():
    rows = (_records(29, ["g1", "g2", "g3"]) + _records(10, ["g1"], "pending", seed=1)
            + _records(5, ["g2"], "rejected", seed=2))
    p = _counted(rows)
    assert (p["approved_unique"], p["waiting"], p["rejected"], p["needed"]) == (29, 10, 5, 1)
    assert p["ready_for_training"] is False


def test_near_identical_approved_photos_count_once():
    rows = _records(30, ["g1", "g2", "g3"])
    rows[1]["dhash"] = rows[0]["dhash"]
    p = _counted(rows)
    assert (p["approved"], p["approved_unique"], p["ready_for_training"]) == (30, 29, False)


def test_old_self_verified_photos_go_back_to_waiting(tmp_path):
    folder = dc.PENDING / "phytophthora_black_rot"
    folder.mkdir(parents=True)
    (folder / "phytophthora_black_rot_0001.jpg").write_bytes(photo(19))
    dc.CSV_PATH.write_text(
        "image_id,disease,plant_part,severity,verified,verification_source,verified_by,"
        "submitted_at,notes,original_filename\n"
        "phytophthora_black_rot_0001,phytophthora_black_rot,stem,moderate,true,"
        "user_attested,Peradeniya,2026-08-30T17:52:03+00:00,,20260818_155026.jpg\n",
        encoding="utf-8")
    p = dc.counts()["diseases"][0]
    assert (p["approved"], p["waiting"]) == (0, 1)
    row = csv_rows()[0]
    assert row["status"] == "pending"
    assert row["claimed_confirmed_by"] == "Peradeniya"
    assert len(row["dhash"]) == 16                  # fingerprinted, so copies are caught


# --------------------------------------------------------------------------
# checks before the expert: the name, and what the model sees
# --------------------------------------------------------------------------

def model_says(monkeypatch, is_orchid=True, guess=None, confidence=None, distance=0.3):
    monkeypatch.setattr(dc, "assess_photo", lambda data: {
        "is_orchid": is_orchid, "distance": distance, "distance_limit": 0.55,
        "guess": guess if is_orchid else None, "confidence": confidence})


@pytest.mark.parametrize("name, words", [
    ("Black Leaf Spot", "already detects Black Leaf Spot"),
    ("black spot", "already detects Black Leaf Spot"),
    ("Black lef spot", "already detects Black Leaf Spot"),
    ("Phylosticta", "already detects Phyllosticta Leaf Spot"),
    ("Phyllosticta leaf spot disease", "already detects Phyllosticta Leaf Spot"),
    ("Phyllosticta capitalensis", "already detects Phyllosticta Leaf Spot"),
    ("healthy leaf", "Check a plant already handles healthy leaves"),
    ("leaf spot", "too general"),
    ("Disease", "too general"),
    ("fungus", "too general"),
])
def test_a_name_the_app_already_detects_or_too_general_is_refused(client, name, words):
    r = send(client, "grower-1", photo(30), disease=name)
    assert r.status_code == 422, name
    assert words in r.json()["detail"]
    assert not dc.CSV_PATH.exists()


@pytest.mark.parametrize("name", ["Black rot", "Anthracnose", "Cercospora leaf spot",
                                  "Bacterial soft rot", "Fusarium wilt"])
def test_a_new_disease_is_accepted_even_when_its_name_is_close(client, name):
    assert send(client, "grower-1", photo(31), disease=name).status_code == 200, name


def test_a_leaf_photo_unlike_any_orchid_is_refused_before_review(client, monkeypatch):
    model_says(monkeypatch, is_orchid=False, distance=0.71)
    r = send(client, "grower-1", photo(32), part="leaf")
    assert r.status_code == 422
    assert "doesn't look like an orchid leaf" in r.json()["detail"]
    assert not dc.CSV_PATH.exists()


def test_a_stem_photo_unlike_the_leaf_photos_is_sent_and_marked(client, monkeypatch):
    # The orchid check learned from leaves only; a real stem must not be turned away.
    model_says(monkeypatch, is_orchid=False, distance=0.62)
    r = send(client, "grower-1", photo(33), part="stem")
    assert r.status_code == 200
    image_id = r.json()["result"]["image_id"]
    item = client.get(API + "/review/items/" + image_id, headers=auth("expert")).json()["item"]
    assert item["model_check"]["status"] == "note"
    assert "Unlike the orchid leaf photos" in item["model_check"]["text"]


def test_a_photo_the_model_knows_needs_the_grower_to_say_it_is_different(client, monkeypatch):
    model_says(monkeypatch, guess="phyllosticta_leaf_spot", confidence=0.96)
    r = send(client, "grower-1", photo(34))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "looks_known" and detail["disease"] == "phyllosticta_leaf_spot"
    assert "Phyllosticta Leaf Spot (96% sure)" in detail["message"]
    assert not dc.CSV_PATH.exists()

    r = send(client, "grower-1", photo(34), confirmed_new="true")
    assert r.status_code == 200
    image_id = r.json()["result"]["image_id"]
    item = client.get(API + "/review/items/" + image_id, headers=auth("expert")).json()["item"]
    assert item["model_check"]["status"] == "sent_anyway"
    assert "thinks this is Phyllosticta Leaf Spot (96%)" in item["model_check"]["text"]


def test_an_unsure_model_lets_the_photo_through(client, monkeypatch):
    model_says(monkeypatch, guess="black_leaf_spot", confidence=0.62)
    r = send(client, "grower-1", photo(35))
    assert r.status_code == 200
    row = csv_rows()[0]
    assert (row["model_check"], row["model_guess"], row["model_confidence"]) == (
        "ok", "black_leaf_spot", "0.62")


def test_without_the_model_photos_are_still_accepted_and_marked(client):
    r = send(client, "grower-1", photo(36))
    assert r.status_code == 200
    image_id = r.json()["result"]["image_id"]
    item = client.get(API + "/review/items/" + image_id, headers=auth("expert")).json()["item"]
    assert item["model_check"]["status"] == "not_checked"
    assert "Not checked by the model" in item["model_check"]["text"]


def test_the_instant_check_reports_everything_before_anything_is_sent(client, monkeypatch):
    def check(data, **form):
        return client.post(API + "/contribute/check", headers=auth("grower-1"),
                           files={"image": ("leaf.jpg", data, "image/jpeg")}, data=form)

    assert client.post(API + "/contribute/check",
                       files={"image": ("leaf.jpg", photo(37), "image/jpeg")}).status_code == 401

    model_says(monkeypatch, is_orchid=False, distance=0.7)
    body = check(photo(37), disease="black spot").json()["result"]
    assert body["quality_ok"] is True and body["is_orchid"] is False
    assert body["by_part"]["leaf"]["verdict"] == "refuse"
    assert body["by_part"]["flower"]["verdict"] == "note"
    assert body["name"]["ok"] is False and body["name"]["known"] == "black_leaf_spot"

    model_says(monkeypatch, guess="healthy", confidence=0.93)
    body = check(photo(37)).json()["result"]
    assert body["by_part"]["leaf"]["verdict"] == "confirm"
    assert "looks healthy" in body["by_part"]["leaf"]["message"]
    assert body["by_part"]["stem"]["verdict"] == "ok"   # the model knows only leaves
    assert body["model_guess"]["disease"] == "healthy"

    dark = check(photo(38, dark=True)).json()["result"]
    assert dark["quality_ok"] is False and "too dark" in dark["problems"][0]["message"]
    assert dark["checked_by_model"] is False           # refused whatever the model thinks

    model_says(monkeypatch, guess="black_leaf_spot", confidence=0.5)
    sent = photo(39)
    assert check(sent).json()["result"]["already_sent"] is False
    send(client, "grower-1", sent)
    assert check(sent).json()["result"]["already_sent"] is True
    assert not list((dc.PENDING / "anthracnose").glob("*.jpg"))[1:]  # the check stored nothing


def test_the_name_check_suggests_a_name_already_being_collected(client):
    send(client, "grower-1", photo(40), disease="Anthracnose")
    r = client.get(API + "/contribute/check-name", params={"name": "Anthracnos"}).json()["result"]
    assert r["ok"] is True and r["already_collecting"] is False
    assert [s["display_name"] for s in r["similar"]] == ["Anthracnose"]
    same = client.get(API + "/contribute/check-name", params={"name": "anthracnose"}).json()["result"]
    assert same["already_collecting"] is True and same["similar"] == []
    known = client.get(API + "/contribute/check-name", params={"name": "BLS"}).json()["result"]
    assert known["ok"] is False and known["known_display_name"] == "Black Leaf Spot"
