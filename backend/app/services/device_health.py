"""Is the hardware telling the truth? Broken, frozen and erratic sensors, silent
nodes, and commands that never ran.

Asked for after the previous viva, where one pump did not run during the demo
and the cause - a loose wire - was only found afterwards. Nothing had said a
word. The user's brief: "if sensors give not normal reading it should be sensor
issue right? so we need to catch that and inform".

WHAT THIS CAN AND CANNOT SEE
----------------------------
Everything here is inferred from what the nodes report. There is no current
sensor yet (the INA219 was postponed), so a pump wire that comes loose cannot be
seen directly: the relay clicks, the node reports the run as done, and no water
moves. What CAN be seen is a node that never carried a command out - the
messages say which part to check and never claim more than that.

There is no tray level check: the tray probe was removed on 10 Oct 2026 (the
grower sets the fill amount in the app), so nothing reports a tray's level.

COST
----
No Firebase reads of its own. The engine already downloads /farm/houses.json
once a minute; each section's `latest` from that download is fed into a small
in-memory history here, and every check runs on that. The price is that the
history starts empty after a server restart, so the slow checks (frozen,
silent) need their full window again before they can fire.

ONE ALARM PER FAULT
-------------------
A fault is reported when it STARTS, not on every tick. Its alarm key carries the
farm date and an occurrence number, so a standing fault re-detected after a
restart lands on the key it already has (and _raise_alarm writes nothing), while
a fault that cleared and came back the same day gets a new key and a new alarm.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from app.services import readings as rd

# ── thresholds, each with the reason it is that number ──────────────────────

# A DHT22 occasionally misses ONE read (a timing glitch on its one-wire bus) and
# the next is fine; three in a row, spread over at least two minutes, is a wire
# or a dead sensor. At a 60 s interval that alarms within about three minutes.
CONSECUTIVE_BAD = 3
BAD_MIN_SPAN_MS = 2 * 60_000

# A light sensor that HAS worked and now reads -999. Ten minutes,
# because the firmware re-probes a missing BH1750 every five: one probe cycle is
# allowed to bring it back before anybody is told.
LOST_MIN_MS = 10 * 60_000

# The same temperature AND humidity, to the 0.1 the node reports, for two hours.
# A working DHT22 in a shade house moves by at least 0.1 in that time; a frozen
# one (the library returning its last good value) does not. Saturated air is
# left out: at 98 %+ RH the humidity can genuinely sit still all night.
FROZEN_MS = 2 * 3600_000
FROZEN_MIN_READINGS = 10
FROZEN_RH_CEILING = 98.0

# Air in a shade house does not change 5 C or 20 % RH in under three minutes.
# Three such jumps in an hour is a loose connector making intermittent contact,
# or a failing sensor - not weather.
JUMP_T = 5.0
JUMP_RH = 20.0
JUMP_GAP_MS = 3 * 60_000
JUMPS_PER_HOUR = 3

# No new reading for twenty minutes. Above any read interval in use (15 s live,
# 60 s for battery nodes) by a wide margin, so a slow cycle never trips it.
SILENT_MS = 20 * 60_000

# A pour a working master would have run or thrown away by now. The master runs
# its queue ONE entry at a time, so an entry's own duration says nothing about
# when it will start - two 120 s pours issued together finish 240 s apart. What
# a live master does guarantee is that it acks every entry, as "stale" if need
# be, once it is MASTER_MAX_AGE_SEC old (master_queue.ino). Only an entry older
# than that plus one longest pour proves the master is not draining. The first
# version used the entry's own duration and called a working master broken
# whenever two pours were queued together. Found in review, 8 Oct 2026.
MASTER_MAX_AGE_SEC = 900
RELAY_MAX_SEC = 120
COMMAND_GRACE_SEC = 90
# Only commands from the last six hours, so a restart does not alarm about
# something from yesterday that nobody can act on any more.
COMMAND_LOOKBACK_SEC = 6 * 3600

# A node whose newest reading is older than this when the server first sees it
# is not one this server can call "silent" - it was switched off before we
# were watching (H1's boards, untouched for weeks). Within it, a node that died
# shortly before a deploy is still caught; the first version used SILENT_MS and
# so lost any node that died 20 minutes to a day before a restart.
SEEN_LIVE_MS = 24 * 3600_000

# A FLAPPING fault - a loose wire making and breaking contact - would start and
# clear every few minutes, and each start was a new alarm: about 150 pushes a
# night from one DHT22 wire, found in review. So a fault only counts as cleared
# after this long without it, and one kind of fault on one section alarms at
# most MAX_ALARMS_PER_DAY times a farm day; after that it stays on the screens
# but sends nothing more.
CLEAR_AFTER_MS = 30 * 60_000
MAX_ALARMS_PER_DAY = 3

# How much history is kept per section: enough for the frozen window.
KEEP_MS = 3 * 3600_000

# What it takes to say a light sensor IS FITTED, so that losing it later is a
# fault. Found 8 Oct 2026 on Node 1 (then with a sensor that has since been
# removed): the first pass after a deploy read a latest 38 days old and marked
# the sensor fitted, so the board's fresh -999s were pushed to the phone as a
# fault. A reading that old describes the board as it WAS, and one stray valid
# value is not a sensor. So it takes CONSECUTIVE_GOOD valid readings, each under
# FRESH_MS old when seen.
FRESH_MS = 2 * 3600_000
CONSECUTIVE_GOOD = 3

FARM_OFFSET_MIN = 330          # Sri Lanka, no DST

# What each fault is called, and what the farmer should do about it. Plain
# words; the app shows these as they are.
TEXT = {
    "dht": ("Temperature sensor not answering",
            "{where}: the temperature and humidity sensor (DHT22) has failed {n} readings in a "
            "row since {since}. Check its three wires: VCC to 3V3, DATA to D4, GND to GND."),
    "light": ("Light sensor stopped",
              "{where}: the light sensor (BH1750) was working and has read nothing since "
              "{since}. Check its four wires: VCC to 3V3, GND, SDA to D21, SCL to D22."),
    "frozen": ("Sensor reading is stuck",
               "{where}: exactly the same temperature and humidity since {since}. A working "
               "sensor always moves a little - unplug the node and plug it back in."),
    "erratic": ("Sensor readings jumping",
                "{where}: {n} impossible jumps in the last hour (latest at {since}). Usually a "
                "loose connector - press the sensor's wires in firmly."),
    "silent": ("Node stopped reporting",
               "{where}: no reading since {since}. If the Wi-Fi dropped, a node on firmware "
               "2.3 keeps its readings and sends them later; if its battery or power bank ran "
               "out, nothing is being recorded. Check the power first."),
    "command": ("Master did not carry out a watering",
                "{where}: the {action} sent at {since} is still waiting in the master "
                "controller's queue. Check the master's power and Wi-Fi. (A loose pump wire "
                "cannot be seen without a current sensor - look at the pump too.)"),
}


class _Section:
    __slots__ = ("hist", "had_light", "good_light",
                 "active", "day_counts", "seen_live")

    def __init__(self) -> None:
        # (ts_ms, temperature|None, humidity|None, light|None)
        self.hist: Deque[tuple] = deque()
        self.had_light = False
        # The current run of fresh valid readings - see CONSECUTIVE_GOOD.
        self.good_light = 0
        self.active: Dict[str, dict] = {}            # kind -> the issue as raised
        self.day_counts: Dict[Tuple[str, str], int] = {}
        # Has this node been seen REPORTING since the server started? Only then
        # can it "stop". Without this, the first pass after a deploy alarmed for
        # every node that had been switched off for weeks - eight pushes for H1,
        # repeated, about boards nobody had plugged in.
        self.seen_live = False


# (tenant, house, section) -> state. Module level, so it lives as long as the
# server process, like the engine's own _state.
_SECTIONS: Dict[Tuple[str, str, str], _Section] = {}
# tenant -> server ms of the last pass, for the route to say "not run yet".
_LAST_RUN: Dict[str, int] = {}


def reset() -> None:
    """Forget everything. For tests."""
    _SECTIONS.clear()
    _LAST_RUN.clear()


def _local(ms: float, offset_min: int) -> str:
    return (datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            + timedelta(minutes=offset_min)).strftime("%H:%M")


def _day(ms: float, offset_min: int) -> str:
    return (datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            + timedelta(minutes=offset_min)).strftime("%Y-%m-%d")


def observe(st: _Section, latest: Optional[dict], now_ms: Optional[float] = None) -> bool:
    """Add `latest` to the history if it is a reading not seen before."""
    if not isinstance(latest, dict):
        return False
    try:
        ts = float(latest.get("timestamp"))
    except (TypeError, ValueError):
        return False
    if st.hist and ts <= st.hist[-1][0]:
        return False                                  # same reading, next tick
    t = rd.value(latest, "temperature")
    h = rd.value(latest, "humidity")
    lx = rd.value(latest, "light")
    st.hist.append((ts, t, h, lx))
    fresh = now_ms is None or now_ms - ts < FRESH_MS
    st.good_light = st.good_light + 1 if (lx is not None and fresh) else 0
    st.had_light = st.had_light or st.good_light >= CONSECUTIVE_GOOD
    if now_ms is not None and now_ms - ts < SEEN_LIVE_MS:
        st.seen_live = True
    while st.hist and st.hist[0][0] < ts - KEEP_MS:
        st.hist.popleft()
    return True


def _tail_bad(hist, idx: int) -> List[tuple]:
    """The run of most recent readings whose field `idx` is None."""
    run = []
    for r in reversed(hist):
        if r[idx] is not None:
            break
        run.append(r)
    return list(reversed(run))


def sensor_faults(st: _Section, now_ms: float) -> Dict[str, dict]:
    """kind -> {"since": ms, "n": count} for every sensor fault standing now."""
    out: Dict[str, dict] = {}
    hist = st.hist
    if not hist:
        return out

    # a. the DHT22: the firmware writes -999 to BOTH fields when a read fails
    bad = [r for r in _tail_bad(hist, 1) if r[2] is None]
    if len(bad) >= CONSECUTIVE_BAD and bad[-1][0] - bad[0][0] >= BAD_MIN_SPAN_MS:
        out["dht"] = {"since": bad[0][0], "n": len(bad)}

    # b. a light sensor that worked, and stopped (never fitted: not a fault)
    if st.had_light:
        run = _tail_bad(hist, 3)
        if len(run) >= CONSECUTIVE_BAD and run[-1][0] - run[0][0] >= LOST_MIN_MS:
            out["light"] = {"since": run[0][0], "n": len(run)}

    # c. frozen: identical values across the window
    last = hist[-1]
    if last[1] is not None and last[2] is not None and last[2] < FROZEN_RH_CEILING:
        same = 0
        start = last[0]
        for r in reversed(hist):
            if r[1] != last[1] or r[2] != last[2]:
                break
            same += 1
            start = r[0]
        if same >= FROZEN_MIN_READINGS and last[0] - start >= FROZEN_MS:
            out["frozen"] = {"since": start, "n": same}

    # d. erratic: physically impossible steps between close readings
    jumps = []
    prev = None
    for r in hist:
        if (prev is not None and r[0] - prev[0] <= JUMP_GAP_MS
                and r[0] >= last[0] - 3600_000):
            dt = abs(r[1] - prev[1]) if r[1] is not None and prev[1] is not None else 0.0
            dh = abs(r[2] - prev[2]) if r[2] is not None and prev[2] is not None else 0.0
            if dt > JUMP_T or dh > JUMP_RH:
                jumps.append(r[0])
        prev = r
    if len(jumps) >= JUMPS_PER_HOUR:
        out["erratic"] = {"since": jumps[-1], "n": len(jumps)}

    # g. silent - only a node that was reporting while this server watched
    if st.seen_live and now_ms - last[0] >= SILENT_MS:
        out["silent"] = {"since": last[0], "n": 0}
    return out


def overdue_commands(queue: Optional[dict], now_ms: float) -> Dict[str, dict]:
    """section id -> the oldest pour still sitting in a master's queue past its time.

    EVERY pour goes through the house's master (_issue_node_command writes
    /farm/masters/{mac}/queue/{id}); the master deletes an entry only after it
    has run it and acked. So an entry still there after its run time plus a
    grace period was never carried out. The first version of this check read
    the SECTION's command document - where pours no longer go - and so could
    never have seen one. Found in review.
    """
    out: Dict[str, dict] = {}
    for cid, cmd in (queue or {}).items():
        if not isinstance(cmd, dict):
            continue
        try:
            issued = float(cmd.get("issuedAtSec"))
        except (TypeError, ValueError):
            continue
        sid = cmd.get("targetSection")
        if not sid:
            continue
        due = issued + MASTER_MAX_AGE_SEC + RELAY_MAX_SEC + COMMAND_GRACE_SEC
        age = now_ms / 1000.0 - issued
        if now_ms / 1000.0 < due or age > COMMAND_LOOKBACK_SEC:
            continue
        prev = out.get(sid)
        if prev is None or issued * 1000.0 < prev["since"]:
            out[sid] = {"since": issued * 1000.0, "n": 0,
                        "action": "tray fill" if cmd.get("action") == "tray"
                        else ("watering" if cmd.get("action") == "water"
                              else str(cmd.get("action") or "command")),
                        "commandId": cid}
    return out


def _update(st: "_Section", faults: Dict[str, dict], now_ms: float, offset_min: int,
            where: str, hid: str, sid: str, started: List[dict]) -> None:
    """Fold this pass's faults into a section's standing ones; append to
    `started` each fault that should be raised now."""
    day = _day(now_ms, offset_min)
    for kind in list(st.active):
        if kind in faults:
            st.active[kind]["lastSeenMs"] = int(now_ms)
        elif now_ms - st.active[kind].get("lastSeenMs", 0) >= CLEAR_AFTER_MS:
            del st.active[kind]                        # cleared for real: may alarm again
    for kind, f in faults.items():
        cur = st.active.get(kind)
        if cur is not None:
            # A node that reported in between and went quiet AGAIN is a new
            # outage - the real battery death after an earlier Wi-Fi drop - not
            # the old one still standing. It used to be folded in and never said.
            new_outage = kind == "silent" and f["since"] > cur["sinceMs"]
            # A fault held back by the daily cap is said once on the next day,
            # if it is still there: it used to stay silent for ever.
            unsaid_new_day = not cur.get("pushed") and cur.get("day") != day
            if not (new_outage or unsaid_new_day):
                cur.update(n=f.get("n", 0))
                continue
        count = st.day_counts.get((kind, day), 0) + 1
        st.day_counts[(kind, day)] = count
        title, body = TEXT[kind]
        pushed = count <= MAX_ALARMS_PER_DAY
        issue = {
            "kind": kind, "houseId": hid, "sectionId": sid, "title": title,
            "message": body.format(where=where, n=f.get("n", 0),
                                   since=_local(f["since"], offset_min),
                                   action=f.get("action", "command")),
            "sinceMs": int(f["since"]),
            "lastSeenMs": int(now_ms),
            "day": day,
            "pushed": pushed,
            # One key per OCCURRENCE, from when the fault began - never a counter
            # that restarts with the server. A counter reused "-1" after a deploy,
            # found that morning's acknowledged alarm under it, and the new fault
            # was written nowhere. A standing "silent" keeps its key across a
            # restart (its start is the last reading, which does not change).
            "key": f"{hid}-{sid}-dev-{kind}-{int(f['since'])}",
        }
        st.active[kind] = issue
        if pushed:
            started.append(issue)                      # beyond the cap: shown, not pushed


def check_farm(tenant: str, houses: dict, now_ms: float, acting: Iterable[str],
               offset_min: int = FARM_OFFSET_MIN,
               master_queues: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Update every section's history from this tick's houses and return the
    faults that STARTED this pass - the ones to raise an alarm for.

    Sensor checks run for every section with a node linked, calibrating houses
    included: a dead sensor is exactly what ruins a calibration. Command checks
    run for every section of an `acting` house, node or not - every pour goes
    through the master.
    """
    if not houses:
        # A failed download arrives as {} - it is not a farm with no sections.
        # Forgetting everything on it made standing faults undetectable for good
        # (a dead node never "silent" again, a lost sensor never alarmed again).
        # Found in review, 8 Oct 2026.
        return []
    acting = set(acting or ())
    started: List[dict] = []
    seen = set()
    for hid, h in houses.items():
        if not isinstance(h, dict):
            continue
        meta = h.get("meta") or {}
        if meta.get("simulated") is True:
            continue                                   # the node bench invents its readings
        hname = meta.get("name") or hid
        overdue = overdue_commands((master_queues or {}).get(meta.get("masterMac") or ""),
                                   now_ms) if hid in acting else {}
        sections = h.get("sections") or {}
        for sid in set(sections) | set(overdue):
            s = sections.get(sid) if isinstance(sections.get(sid), dict) else {}
            key = (tenant, hid, sid)
            latest = s.get("latest")
            has_node = bool(s.get("deviceMac")) and isinstance(latest, dict)
            if not has_node and sid not in overdue:
                # No node linked (never was, or unlinked / taken out by
                # apply-placement): nothing to watch, and a history kept from
                # before would call it "silent" twenty minutes later.
                _SECTIONS.pop(key, None)
                continue
            seen.add(key)
            st = _SECTIONS.setdefault(key, _Section())
            faults: Dict[str, dict] = {}
            if has_node:
                observe(st, latest, now_ms)
                faults.update(sensor_faults(st, now_ms))
            elif st.hist:
                st.hist.clear()                        # node unlinked: no sensor history
            if sid in overdue:
                faults["command"] = overdue[sid]       # the MASTER's fault, node or not
            sname = (s.get("meta") or {}).get("name") or sid
            _update(st, faults, now_ms, offset_min, f"{hname} · {sname}", hid, sid, started)

    # A section that disappeared (house deleted) is forgotten.
    for key in [k for k in _SECTIONS if k[0] == tenant and k not in seen]:
        del _SECTIONS[key]
    _LAST_RUN[tenant] = int(now_ms)
    return started


def snapshot(tenant: str, house_id: str) -> dict:
    """What is wrong in one house right now, per section, for the app."""
    sections: Dict[str, list] = {}
    ran = _LAST_RUN.get(tenant)
    for (t, hid, sid), st in _SECTIONS.items():
        if t != tenant or hid != house_id:
            continue
        # Only faults seen on the last pass. One that has stopped is kept in
        # `active` for CLEAR_AFTER_MS so a flapping wire cannot re-alarm, but a
        # screen must not go on saying "not answering" about a sensor that is.
        sections[sid] = [
            {k: v for k, v in issue.items() if k in ("kind", "title", "message", "sinceMs")}
            for issue in st.active.values()
            if ran is None or issue.get("lastSeenMs", ran) >= ran
        ]
    return {"checkedAtMs": _LAST_RUN.get(tenant), "sections": sections}
