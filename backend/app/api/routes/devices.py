"""Device registry: pairing physical ESP32 nodes with farm sections.

Every node announces itself under its own MAC address at /devices/{mac} and then
reads back the section a farmer has assigned it to. Nothing here is written by
the node except its own heartbeat fields - assignment is the app's decision.

The one-to-one rule is enforced here rather than in the app, because two phones
could otherwise assign two boards to the same section at the same moment. The
device records are the single source of truth for who owns what: a `deviceMac`
copied onto the section is a convenience for the app, never the authority.
"""
import re
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import requests as _req

from app.api.routes.smart_watering import _fb_get, _fb_put, FIREBASE_BASE_URL
from app.api.deps import require_auth, require_role
from app.services.firebase_auth import ROLE_ADMIN, ROLE_OPERATOR, AuthContext
from app.services.tenant_context import (
    NoTenantInContext, current_tenant, scoped,
)

router = APIRouter()

# A node announces every HEARTBEAT_SEC. Three missed beats is a generous margin
# for a slow network before we call it offline, and short enough that a farmer
# unplugging a board sees it go grey while they are still standing there.
#
# This comment described the intent long before the firmware did it: until
# validation-1.6 the node only announced INSIDE its reading cycle, so `lastSeen`
# moved once every read interval and a healthy 5-minute node spent most of its
# life looking offline against a 120 s window. Hence the split below - a board
# that actually heartbeats is judged on 90 s, an older one on its read interval.
HEARTBEAT_SEC = 30
HEARTBEAT_MISSES = 3
ONLINE_WINDOW_SEC = HEARTBEAT_SEC * HEARTBEAT_MISSES        # 90 s

# Same shape as the reading-freshness margin in smart_care_v2: two missed cycles
# plus the overhead of doing the HTTP work.
LEGACY_CYCLE_MISSES = 2
LEGACY_OVERHEAD_SEC = 12


def sends_heartbeat(rec: dict) -> bool:
    """True if this board's firmware announces on its own clock."""
    m = re.search(r"validation-(\d+)\.(\d+)", str((rec or {}).get("fw") or ""))
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (1, 6)


def device_liveness(rec: dict) -> dict:
    """Is the BOARD there? A different question from whether its readings are fresh.

    A node can be answering commands in two seconds while its last reading is
    minutes old - that is normal between cycles, and it is the whole point of
    heartbeating separately. Keeping the two apart stops a mid-cycle node being
    reported dead, and lets the app say which of the two has actually failed.
    """
    rec = rec or {}
    beats = sends_heartbeat(rec)
    if beats:
        window = ONLINE_WINDOW_SEC
    else:
        ms = rec.get("readIntervalMs") or READ_INTERVAL_DEFAULT_MS
        window = int(ms / 1000.0 * LEGACY_CYCLE_MISSES + LEGACY_OVERHEAD_SEC)
    last = rec.get("lastSeen") or 0
    age = max(0, int(time.time()) - int(last))
    return {"lastSeenSec": age if last else None,
            "online": bool(last) and age <= window,
            "onlineWindowSec": window,
            "heartbeat": beats}


# Clearing a key needs DELETE, not PUT with None: requests treats json=None as
# "send no body", so the PUT leaves Firebase untouched while still returning 200.
# That made unassign report success and change nothing.
def _fb_delete(path: str) -> bool:
    try:
        return _req.delete(f"{FIREBASE_BASE_URL}{scoped(path)}", timeout=8).status_code == 200
    except NoTenantInContext:
        raise
    except Exception:
        return False


# How often a node reads its sensors and reports, in milliseconds.
#
# A demo wants fast updates; a house running on battery wants a slow one. This
# used to be a compile-time #define, so changing it meant physically retrieving
# a board and reflashing it.
#
# The bounds are enforced here AND in the firmware. Below the floor a node would
# hammer Firebase; above the ceiling it becomes indistinguishable from a dead
# one, because the freshness rules would call it stale long before it spoke
# again.
READ_INTERVAL_MIN_MS = 5_000        # 5 s
READ_INTERVAL_MAX_MS = 3_600_000    # 1 hour
READ_INTERVAL_DEFAULT_MS = 15_000   # what the firmware falls back to


class IntervalBody(BaseModel):
    readIntervalMs: int = Field(..., description="Milliseconds between readings")


class AssignBody(BaseModel):
    house: str = Field(..., description="House id, e.g. H1")
    section: str = Field(..., description="Section id, e.g. S2")
    force: bool = Field(False, description="Reassign even if the device or section is already paired")


def _all_devices() -> Dict[str, dict]:
    """Every device record on the platform, UNFILTERED.

    There is no legitimate caller of this on its own. Every use in the codebase
    is `mine_only(_all_devices())`; it is left as a separate function only
    because the raw read and the narrowing are two different ideas and the
    narrowing is the one worth naming.
    """
    return _fb_get("/devices.json") or {}


def _is_mine(rec: dict) -> bool:
    """Is this board the caller's to see and touch?

    Three cases, and the third is the one worth stating. A board carrying
    ANOTHER tenant's id is not ours. A board carrying OURS is. A board carrying
    NONE is unclaimed and belongs to whoever claims it first - true today,
    because no board has been flashed with a tenant yet, and true afterwards for
    a brand-new board out of its box.
    """
    owner = (rec or {}).get("tenantId")
    return not owner or owner == current_tenant()


def mine_only(devices: dict) -> dict:
    """Only the boards the caller may see.

    THE registry is global by design - a board belongs to nobody until it is
    flashed with a tenant - so every reader has to narrow it, not just the routes
    in this module. The chokepoint in `scoped()` cannot help here: /devices is
    deliberately outside /farm/, so nothing rewrites these paths and nothing
    fails loudly when a reader forgets.

    WHAT IT COSTS TO FORGET, measured: house and section ids are unique only
    WITHIN a tenant - every farm's first house is H1 - so matching
    `assignedTo == "H1/S1"` across the whole registry hits another customer's
    board deterministically. One tenant deleting their own house unassigned every
    board in every identically-named house on the platform. Silent for them;
    "No sensor node" and offline alarms for the others.
    """
    return {mac: rec for mac, rec in (devices or {}).items()
            if _is_mine(rec or {})}


def _mine(mac: str) -> dict:
    """One device the caller owns, or 404.

    404 AND NOT 403. A 403 says "this exists and is not yours", which confirms a
    MAC is registered on the platform - the same leak wearing a different hat.
    To this caller the board simply does not exist.
    """
    if current_tenant() is None:
        # Every route here is guarded, so the tenant is always set by the time
        # we arrive. If that ever stops being true, refuse rather than fall
        # back to showing everything.
        raise NoTenantInContext("device route reached with no tenant in context")
    rec = _fb_get(f"/devices/{mac}.json")
    if not isinstance(rec, dict) or not _is_mine(rec):
        raise HTTPException(404, f"No device {mac} has announced itself yet. "
                                 "Power the node on and wait about 30 seconds.")
    return rec


def _decorate(mac: str, rec: dict) -> dict:
    """Adds derived fields the app needs but the node should not have to compute."""
    live = device_liveness(rec)
    age = live["lastSeenSec"]
    assigned = rec.get("assignedTo") or None
    house, section = (assigned.split("/", 1) + [None])[:2] if assigned else (None, None)
    return {
        "mac": mac,
        "shortId": mac[-4:],           # what the node advertises as OrchidNode-XXXX
        "ip": rec.get("ip"),
        "rssi": rec.get("rssi"),
        "firmware": rec.get("fw"),
        "lastSeenSec": age,
        "online": live["online"],
        "onlineWindowSec": live["onlineWindowSec"],
        "heartbeat": live["heartbeat"],
        "assignedTo": assigned,
        "house": house,
        "section": section,
        "identifying": bool(rec.get("identify")),
        # What the node is actually using. Absent means it has never been set
        # and the board is on its compiled-in default.
        "readIntervalMs": rec.get("readIntervalMs") or READ_INTERVAL_DEFAULT_MS,
        "readIntervalSet": rec.get("readIntervalMs") is not None,
    }


def _device_for_section(devices: Dict[str, dict], house: str, section: str) -> Optional[str]:
    """MAC currently claiming this section, or None. Scans the registry rather
    than trusting section/deviceMac, which can drift if a write half-fails."""
    target = f"{house}/{section}"
    for mac, rec in devices.items():
        if (rec or {}).get("assignedTo") == target:
            return mac
    return None


@router.get("/")
def list_devices(only_unassigned: bool = False, ctx: AuthContext = Depends(require_auth)) -> dict:
    """Every node that has ever announced itself.

    `only_unassigned=true` is what the Add Section flow shows: boards that are
    powered on and waiting to be claimed.
    """
    # Another farm's boards are not merely uninteresting here, they are a leak:
    # the decorated record carries the MAC, the IP and the house and section the
    # board is installed in.
    devices = mine_only(_all_devices())
    out: List[dict] = [_decorate(m, r or {}) for m, r in devices.items()]
    if only_unassigned:
        out = [d for d in out if not d["assignedTo"]]
    # Online first, then most recently seen: a farmer standing next to a board
    # they just powered on should find it at the top.
    out.sort(key=lambda d: (not d["online"], d["lastSeenSec"]))
    return {"status": "success", "count": len(out), "devices": out}


@router.put("/{mac}/assign")
def assign_device(mac: str, body: AssignBody, ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Bind one node to one section, both directions, refusing to break the 1:1 rule."""
    _mine(mac)          # 404 unless this board is the caller's
    # MINE_ONLY, and this one is not cosmetic. `_mine(mac)` proves the board
    # being assigned is the caller's; the holder lookup below is keyed by
    # house/section, and those ids are unique only WITHIN a tenant - every farm's
    # first house is H1. Against the raw registry, assigning my own board to my
    # own H1/S1 finds ANOTHER farm's board sitting on their H1/S1, refuses with a
    # 409 naming it, and with force=true deletes their assignment outright.
    devices = mine_only(_all_devices())
    if mac not in devices:
        raise HTTPException(404, f"No device {mac} has announced itself yet. "
                                 "Power the node on and wait about 30 seconds.")

    target = f"{body.house}/{body.section}"
    current = (devices[mac] or {}).get("assignedTo")

    if current and current != target and not body.force:
        raise HTTPException(409, f"This node is already assigned to {current}. "
                                 "Unassign it first, or pass force=true to move it.")

    holder = _device_for_section(devices, body.house, body.section)
    if holder and holder != mac and not body.force:
        raise HTTPException(409, f"Section {target} already has node {holder[-4:]}. "
                                 "A section can only have one node.")

    # Displace the previous holder first, so there is never a moment where two
    # devices both believe they own the section.
    if holder and holder != mac:
        _fb_delete(f"/devices/{holder}/assignedTo.json")

    if not _fb_put(f"/devices/{mac}/assignedTo.json", target):
        raise HTTPException(502, "Could not write the assignment to Firebase.")

    # Convenience copy for the app. The device registry above stays authoritative.
    # CLAIM IT. An unclaimed board belongs to whoever assigns it first; without
    # this, a second tenant could assign the same board and silently take it.
    # A board that already carries a tenant never reaches here - _mine() 404s.
    if not (devices[mac] or {}).get("tenantId"):
        _fb_put(f"/devices/{mac}/tenantId.json", current_tenant())

    _fb_put(f"/farm/houses/{body.house}/sections/{body.section}/deviceMac.json", mac)

    return {"status": "success", "mac": mac, "assignedTo": target,
            "displaced": holder if holder and holder != mac else None,
            "message": f"Node {mac[-4:]} now reports to {target}. "
                       "It will pick this up within about 15 seconds."}


@router.delete("/{mac}/assign")
def unassign_device(mac: str, ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Release a node. It keeps reporting to its fallback section rather than
    going silent, so an unclaimed board is still visibly alive."""
    _mine(mac)          # 404 unless this board is the caller's
    devices = mine_only(_all_devices())
    if mac not in devices:
        raise HTTPException(404, f"No device {mac}.")
    current = (devices[mac] or {}).get("assignedTo")
    if not _fb_delete(f"/devices/{mac}/assignedTo.json"):
        raise HTTPException(502, "Could not clear the assignment in Firebase.")
    if current and "/" in current:
        h, s = current.split("/", 1)
        _fb_delete(f"/farm/houses/{h}/sections/{s}/deviceMac.json")
    return {"status": "success", "mac": mac, "wasAssignedTo": current}


@router.put("/{mac}/interval")
def set_read_interval(mac: str, body: IntervalBody, ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """How often this node reads its sensors and reports.

    The node picks this up inside the assignment fetch it already makes every
    cycle, so it costs no extra request and takes effect within one interval.
    """
    _mine(mac)          # 404 unless this board is the caller's
    if mac not in mine_only(_all_devices()):
        raise HTTPException(404, f"No device {mac}.")

    ms = int(body.readIntervalMs)
    clamped = max(READ_INTERVAL_MIN_MS, min(ms, READ_INTERVAL_MAX_MS))
    if not _fb_put(f"/devices/{mac}/readIntervalMs.json", clamped):
        raise HTTPException(502, "Could not write the interval to Firebase.")

    secs = clamped / 1000.0
    if secs < 60:
        pretty = f"{secs:.0f} seconds"
    else:
        mins = round(secs / 60)
        pretty = "1 minute" if mins == 1 else f"{mins} minutes"
    return {"status": "success", "mac": mac,
            "readIntervalMs": clamped,
            "requestedMs": ms,
            "clamped": clamped != ms,
            "message": (f"Node {mac[-4:]} will read every {pretty}. "
                        "It picks this up on its next cycle.")}


@router.post("/{mac}/identify")
def identify_device(mac: str, ctx: AuthContext = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))) -> dict:
    """Blink the node's onboard LED for ~10 seconds.

    Four identical boxes on a bench are indistinguishable in a list. This is how
    the farmer works out which physical unit they are about to assign. The node
    clears the flag itself once it has blinked.
    """
    _mine(mac)          # 404 unless this board is the caller's
    if mac not in mine_only(_all_devices()):
        raise HTTPException(404, f"No device {mac}.")
    if not _fb_put(f"/devices/{mac}/identify.json", True):
        raise HTTPException(502, "Could not send the identify request.")
    return {"status": "success", "mac": mac,
            "message": "The node's blue LED will blink for about 10 seconds."}


@router.post("/{mac}/ping")
def ping_device(mac: str, ctx: AuthContext = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))) -> dict:
    """Ask the node to prove it is there, right now.

    Passive liveness costs a heartbeat interval to notice - fine for a status
    dot, too slow for a farmer standing in front of a board asking "is this
    thing on?". The node polls its device record every 5 s, so an explicit ping
    comes back in single-digit seconds.

    `pingRequest` carries a TOKEN rather than `true`, and the node echoes it into
    `pingAck`. Both values are minted here, so matching them never compares the
    server clock against the node clock - two clocks that are allowed to
    disagree, and whose conflation produced the "161 days ago" bug.

    The previous ack is cleared FIRST. Without that, a ping issued in the same
    second as an earlier one could match a stale ack and report a dead node as
    alive - the exact false confidence this endpoint exists to remove.
    """
    _mine(mac)          # 404 unless this board is the caller's
    if mac not in mine_only(_all_devices()):
        raise HTTPException(404, f"No device {mac}.")
    token = int(time.time())
    _fb_delete(f"/devices/{mac}/pingAck.json")
    if not _fb_put(f"/devices/{mac}/pingRequest.json", token):
        raise HTTPException(502, "Could not send the ping.")
    # Measured on real hardware: 6-8 s normally, but 18.5 s when the ping lands
    # while the board is mid-reading-cycle - pollDeviceFlags() cannot run until
    # the DHT read and its several HTTPS calls finish. Callers must budget for
    # the slow case or they will call a live node dead.
    return {"status": "success", "mac": mac, "token": token,
            "expectWithinSec": 15,
            "message": "Waiting for the node to answer."}


@router.get("/{mac}/ping")
def ping_result(mac: str, token: int, ctx: AuthContext = Depends(require_auth)) -> dict:
    """Has the node answered the ping with this token yet?

    Deliberately a poll rather than a wait: holding the request open would tie up
    a worker for the whole timeout, and the app already polls this way for a
    running pour.
    """
    _mine(mac)          # 404 unless this board is the caller's
    # ONE device, not the whole registry. The app polls this every second while a
    # ping is in flight, and _all_devices() would download every board's record
    # on each of those polls - the same needless egress that pushed
    # /farm/houses.json to 29 MB/day before history was moved out of it.
    rec = _fb_get(f"/devices/{mac}.json")
    if not rec:
        raise HTTPException(404, f"No device {mac}.")
    try:
        answered = int(rec.get("pingAck")) == int(token)
    except (TypeError, ValueError):
        answered = False
    live = device_liveness(rec)
    return {"status": "success", "mac": mac, "token": token,
            "answered": answered,
            "lastSeenSec": live["lastSeenSec"],
            "online": live["online"],
            "message": ("The node answered." if answered
                        else "No answer yet.")}


@router.post("/{mac}/scan")
def request_scan(mac: str, ctx: AuthContext = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))) -> dict:
    """Ask the node which Wi-Fi networks IT can see.

    The scan has to happen on the board, not the phone. They are in different
    places - the node is in the greenhouse and the phone is in a hand - so the
    networks the phone can see are not necessarily ones the node can join, and
    picking from the phone's list would invite exactly the wrong choice. It also
    sidesteps Android gating Wi-Fi scans behind location permission.

    Asynchronous by nature: this only sets the request. The node picks it up
    within about five seconds and writes the result back, which `GET /scan`
    returns. Scanning takes a few seconds more on top, and briefly disturbs the
    node's own connection.
    """
    _mine(mac)          # 404 unless this board is the caller's
    if mac not in mine_only(_all_devices()):
        raise HTTPException(404, f"No device {mac}.")
    # DELETE, not PUT-null: a PUT of None does NOT clear a Firebase key (it is a
    # documented trap on this project). A stale list left in place would be
    # shown as this scan's result.
    _fb_delete(f"/devices/{mac}/scan.json")
    if not _fb_put(f"/devices/{mac}/scanRequest.json", True):
        raise HTTPException(502, "Could not ask the node to scan.")
    return {"status": "success", "mac": mac,
            "message": "Scanning. The node reports back in a few seconds."}


@router.get("/{mac}/scan")
def get_scan(mac: str, ctx: AuthContext = Depends(require_auth)) -> dict:
    """The last scan result, and whether one is still running."""
    _mine(mac)          # 404 unless this board is the caller's
    rec = mine_only(_all_devices()).get(mac)
    if rec is None:
        raise HTTPException(404, f"No device {mac}.")

    networks = rec.get("scan")
    # Firebase stores an empty list as a missing key, so absent means "no result
    # yet", not "no networks" - the two must not be shown the same way.
    if not isinstance(networks, list):
        networks = []

    return {"status": "success", "mac": mac,
            "scanning": bool(rec.get("scanRequest")),
            "networks": sorted(networks,
                               key=lambda x: (x or {}).get("rssi", -999),
                               reverse=True),
            "count": len(networks)}


@router.get("/section/{house}/{section}")
def device_for_section(house: str, section: str, ctx: AuthContext = Depends(require_auth)) -> dict:
    """Which node, if any, is reporting for this section.

    Answers the 'No device - not reporting' state the app shows for a section
    created before its hardware was available.
    """
    # The one route here that is keyed by house/section rather than by MAC, and
    # the one the first pass missed for exactly that reason: an insertion that
    # matched on `mac` skipped it, and so did the cross-tenant test loop. Left
    # open it maps another farm's house and section - both trivially guessable,
    # they are H1/S1 and so on - to that board's MAC, IP and firmware.
    #
    # Narrowed BEFORE the lookup rather than after it, which is the same thing
    # here and the same code as every other reader - a check that runs after the
    # match is one an edit can step past without noticing.
    #
    # Answered as "no device here" rather than 404: to this caller that section
    # genuinely has no board, and saying anything else would confirm one exists.
    devices = mine_only(_all_devices())
    mac = _device_for_section(devices, house, section)
    if not mac:
        return {"status": "success", "house": house, "section": section,
                "device": None, "message": "No device assigned to this section."}
    return {"status": "success", "house": house, "section": section,
            "device": _decorate(mac, devices[mac] or {})}
