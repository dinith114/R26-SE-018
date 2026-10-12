"""What a master controller may do on its own when the cloud cannot be reached.

Every watering is decided by the engine in the cloud. If the engine, or the
farm's internet, is down at a section's planned minute, nothing waters that day
- and Vanda are watered every day. So the engine gives each master a copy of
the day's plan, and the master, once the cloud has been silent past a section's
planned minute AND past the engine's own late window, waters that section
itself, once, and reports it when the cloud is back
(firmware/sensor_node_validate/queue_fallback.ino).

This file is the backend's half, as pure functions with no Firebase:
  signature()   - has anything a master would need changed since last time?
  build_plans() - the plan document each master is given
  read_report() - what a master's report of an offline watering says

THE MASTER NEVER WATERS BEFORE THE ENGINE HAS GIVEN UP. The engine starts a
missed watering up to WATER_WINDOW_MIN (20) late. The master waits
FALLBACK_AFTER_MIN, which is longer, so the two can never both pour the same
morning. FALLBACK_UNTIL_MIN stops a master from watering into the hot middle of
the day when the outage started at dawn.

ONLY SECTIONS THAT ACT BY THEMSELVES. A section the grower runs by hand is
answered with alarms, not water, when the cloud is up; it gets nothing from a
master on its own either. A house with today's plans but no automatic section
still gets a document - with no entries - so its master knows today's answer is
"nothing", rather than falling back to yesterday's plan.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

FALLBACK_AFTER_MIN = 25     # the engine's late window (20 min) plus 5 minutes of margin
FALLBACK_UNTIL_MIN = 120    # no offline watering more than two hours after the planned minute
MAX_POUR_SEC = 120          # the relay cap, restated: the firmware enforces it again


def _minutes(hhmm) -> Optional[Tuple[int, int]]:
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
    except (TypeError, ValueError, AttributeError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def signature(houses: dict, today: str, is_auto: Callable[[dict], bool]) -> tuple:
    """Everything build_plans() depends on, from the farm already in memory.

    The engine compares this every pass and rebuilds the plans only when it
    changes, so an ordinary minute costs no extra Firebase traffic - the channel
    lookups in build_plans() read the database and happen only on a change.
    """
    out = []
    for hid in sorted(houses or {}):
        h = houses[hid]
        if not isinstance(h, dict):
            continue
        hmeta = h.get("meta") or {}
        mac = (hmeta.get("masterMac") or "").strip()
        if not mac:
            continue
        for sid in sorted(h.get("sections") or {}):
            s = (h.get("sections") or {})[sid]
            if not isinstance(s, dict):
                continue
            p = s.get("plan") or {}
            if p.get("date") != today:
                continue
            out.append((hid, sid, mac, p.get("waterTime"), p.get("durationSec"),
                        bool(is_auto(s)), (s.get("meta") or {}).get("relayChannel"),
                        hmeta.get("waterChannel")))
    return tuple(out)


def build_plans(houses: dict, today: str, tz, is_auto: Callable[[dict], bool],
                channel_for: Callable[[str, str], Optional[int]],
                made_at_sec: int) -> Dict[str, dict]:
    """{master MAC: plan document} for every house with a master and a plan for today.

    Times are absolute epoch seconds computed on the farm's clock here, so the
    firmware needs no time zone: it compares them with its own clock.
    """
    day = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=tz)
    day_start = int(day.timestamp())
    plans: Dict[str, dict] = {}
    for hid in sorted(houses or {}):
        h = houses[hid]
        if not isinstance(h, dict):
            continue
        mac = ((h.get("meta") or {}).get("masterMac") or "").strip()
        if not mac:
            continue
        sections = h.get("sections") or {}
        planned = {sid: s for sid, s in sections.items()
                   if isinstance(s, dict) and (s.get("plan") or {}).get("date") == today}
        if not planned:
            continue            # before today's plan exists: leave the master yesterday's
        doc = plans.setdefault(mac, {
            "day": today, "dayStartSec": day_start, "madeAtSec": int(made_at_sec),
            "afterMin": FALLBACK_AFTER_MIN, "untilMin": FALLBACK_UNTIL_MIN,
            "entries": {},
        })
        for sid in sorted(planned):
            s = planned[sid]
            if not is_auto(s):
                continue
            p = s.get("plan") or {}
            hm = _minutes(p.get("waterTime"))
            try:
                secs = int(p.get("durationSec") or 0)
            except (TypeError, ValueError):
                secs = 0
            if hm is None or secs <= 0:
                continue
            ch = channel_for(hid, sid)
            if not ch:
                continue        # no watering channel: the engine could not water it either
            due = int(day.replace(hour=hm[0], minute=hm[1]).timestamp())
            doc["entries"][f"{hid}-{sid}"] = {
                "house": hid, "section": sid, "dueSec": due,
                "durationSec": min(secs, MAX_POUR_SEC), "channel": int(ch),
            }
    return plans


def read_report(raw) -> Optional[dict]:
    """A master's report of an offline watering, checked, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    house = str(raw.get("house") or "").strip()
    section = str(raw.get("targetSection") or "").strip()
    try:
        ran = int(raw.get("ranSec"))
        at = int(raw.get("at"))
    except (TypeError, ValueError):
        return None
    if not house or not section or ran < 0 or at < 1_700_000_000:
        return None
    return {"house": house, "section": section, "ranSec": ran, "at": at,
            "outcome": str(raw.get("outcome") or "done"),
            "fromYesterday": bool(raw.get("fromYesterday")),
            "channel": raw.get("channel")}
