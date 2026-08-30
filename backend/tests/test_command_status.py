"""Command confirmation, and the setup wizard's dropped fields.

`confirmed` has to mean the NODE ran the relay, not that the server wrote a
document. The node matches commands by id and never deletes them, so an
acknowledgement left over from an earlier run sits in Firebase indefinitely —
reading that as success would let the run screen report a pour that never
happened, which is exactly the class of bug this project already shipped once.
"""
import time
import uuid

import pytest
import requests

API = "http://127.0.0.1:8000"
FB = "https://orchid-smart-care-default-rtdb.firebaseio.com"

HOUSE = "HCMD"            # never H1
SEC = "SC1"
BASE = f"/farm/houses/{HOUSE}/sections/{SEC}"


def fb_put(path, body):
    return requests.put(f"{FB}{path}", json=body, timeout=15)


def fb_delete(path):
    return requests.delete(f"{FB}{path}", timeout=15)


def api(method, path, body=None, expect=200):
    r = requests.request(method, f"{API}{path}", json=body, timeout=60)
    assert r.status_code == expect, f"{method} {path} -> {r.status_code}\n{r.text[:400]}"
    return r.json() if r.content else None


@pytest.fixture(scope="module", autouse=True)
def scratch_section():
    try:
        requests.get(f"{API}/health", timeout=10)
    except requests.RequestException as e:
        pytest.skip(f"backend not running: {e}")
    fb_put(f"{BASE}/meta.json", {"name": "command-status test"})
    yield
    fb_delete(f"/farm/houses/{HOUSE}.json")


def _status():
    return api("GET", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/command-status")


def test_no_command_is_not_confirmed():
    fb_delete(f"{BASE}/command.json")
    fb_delete(f"{BASE}/commandAck.json")
    r = _status()
    assert r["confirmed"] is False
    assert r["command"]["id"] is None


def test_a_command_with_no_ack_is_not_confirmed():
    cid = uuid.uuid4().hex[:12]
    fb_delete(f"{BASE}/commandAck.json")
    fb_put(f"{BASE}/command.json",
           {"id": cid, "action": "water", "durationSec": 20})
    r = _status()
    assert r["command"]["id"] == cid
    assert r["confirmed"] is False, "a command nobody acknowledged is not done"


def test_a_matching_ack_confirms():
    cid = uuid.uuid4().hex[:12]
    fb_put(f"{BASE}/command.json",
           {"id": cid, "action": "water", "durationSec": 20})
    fb_put(f"{BASE}/commandAck.json",
           {"id": cid, "action": "water", "durationSec": 20,
            "done": True, "at": int(time.time())})
    r = _status()
    assert r["confirmed"] is True
    assert r["ack"]["done"] is True


def test_a_STALE_ack_from_an_earlier_command_does_not_confirm():
    """The one that matters. The node leaves its last ack in place, so a NEW
    command must not inherit the previous command's success."""
    old = uuid.uuid4().hex[:12]
    fb_put(f"{BASE}/commandAck.json",
           {"id": old, "action": "water", "durationSec": 20,
            "done": True, "at": int(time.time()) - 600})

    fresh = uuid.uuid4().hex[:12]
    fb_put(f"{BASE}/command.json",
           {"id": fresh, "action": "water", "durationSec": 20})

    r = _status()
    assert r["command"]["id"] == fresh
    assert r["ack"]["id"] == old
    assert r["confirmed"] is False, (
        "a leftover acknowledgement from an earlier command was read as this "
        "command succeeding")


def test_an_ack_that_is_not_done_does_not_confirm():
    cid = uuid.uuid4().hex[:12]
    fb_put(f"{BASE}/command.json", {"id": cid, "action": "tray", "durationSec": 5})
    fb_put(f"{BASE}/commandAck.json", {"id": cid, "action": "tray", "done": False})
    assert _status()["confirmed"] is False


# ── the setup wizard no longer demands a farm name or an owner ─────────────

def test_setup_accepts_no_farm_name():
    """The wizard used to block on a farm name; it is only a screen title."""
    from app.api.routes.smart_care_v2 import FarmSetup
    cfg = FarmSetup(houses=[])
    assert cfg.farmName == "My Farm"


def test_setup_model_has_no_owner_field():
    from app.api.routes.smart_care_v2 import FarmSetup
    assert "ownerName" not in FarmSetup.model_fields, (
        "ownerName is back — it was written to Firebase and read by nothing")
