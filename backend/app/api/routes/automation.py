"""
The automation engine — what makes this an automated system rather than an app
with buttons.

WHY THIS FILE EXISTS
--------------------
Every decision the models make already worked, but nothing ever ran them: the
tray decision and the watering plan were only reachable through HTTP endpoints,
and the only caller was a button in the app. Close the app and the farm was
never looked after. Worse, for watering there was no acting code at all — the
plan said "06:01 for 101s" and nothing anywhere turned that into a command.

This module supplies the two missing halves:

  1. A CLOCK          — a loop that wakes up and runs the checks on schedule.
  2. THE WATERING LINK — code that turns today's plan into a real waterCommand
                         when the planned minute arrives.

ONE SWITCH, TWO BEHAVIOURS
--------------------------
There used to be three overlapping flags (mode, trayEnabled, fertEnabled), and
`mode: manual` silently disabled the tray as well as watering. That is replaced
by a single farm-level switch, `/farm/meta/autoMode`, with an optional
per-section override for the odd broken section.

  AUTO ON   The system does everything itself. The farmer is told what happened
            ("Watered Section 1 at 06:01"), but never has to act.

  AUTO OFF  The system still watches and still decides — it simply does not act.
            Instead it raises an ACTION alarm ("Water the plants now"), the
            farmer opens the app and presses the button.

Auto OFF is emphatically NOT "the system does nothing". The intelligence runs
either way; only the hands change.
"""

import asyncio
import os
import traceback
from functools import partial
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import requests as _req

from app.api.routes.smart_care_v2 import (
    _fb_get, _fb_put, _plan_section, _tray_decision, _run_per_section,
    second_session_due, _issue_node_command, RELAY_MAX_SEC, farm_now, farm_tz,
    farm_auto_mode, section_acts_alone, FIREBASE_BASE_URL, _ready,
    _record_fertilized, _log_event,
)

router = APIRouter()


# ─────────────────────────── Tunables ────────────────────────────────────────
TICK_SECONDS        = 60      # how often the engine wakes up
TRAY_CHECK_MINUTES  = 15      # how often the humidity trays are assessed
# On the FARM's clock, not UTC. This used to be PLAN_HOUR_UTC = 4 with the
# comment "~09:30 Sri Lanka" - a hand compensation for a missing timezone that
# was applied here and nowhere else, which is how the rest of the engine ended
# up scheduling in UTC. 05:00 local is after the dawn reading exists (dawn is
# 04:00-07:00) and before the earliest watering the model ever plans (06:06).
PLAN_HOUR_LOCAL     = 5
WATER_WINDOW_MIN    = 20      # how late a missed watering may still be started


# ═══════════════════════ The single Auto switch ══════════════════════════════

def get_auto_mode() -> bool:
    """The farm-level switch. Defaults to ON for a freshly set-up farm."""
    return farm_auto_mode()


def section_is_auto(section: dict, master: Optional[bool] = None) -> bool:
    """Does THIS section act by itself?

    Delegates to the one definition in smart_care_v2. There used to be a second,
    different answer inside `_tray_decision`, and the two disagreed: the tray
    path ignored the farm switch entirely. Keep exactly one.
    """
    return section_acts_alone(section, master)


class AutoModeIn(BaseModel):
    autoMode: bool


@router.put("/auto-mode")
async def set_auto_mode(body: AutoModeIn):
    """Flip the whole farm between acting by itself and alarming the farmer."""
    meta = _fb_get("/farm/meta.json") or {}
    meta["autoMode"] = bool(body.autoMode)
    meta["autoModeSetAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _fb_put("/farm/meta.json", meta)
    return {"status": "success", "autoMode": meta["autoMode"]}


@router.get("/auto-mode")
async def read_auto_mode():
    return {"status": "success", "autoMode": get_auto_mode()}


class OverrideIn(BaseModel):
    # 'auto' | 'manual' | None. None clears the pin and follows the farm switch.
    override: Optional[str] = None


@router.put("/sections/{house_id}/{section_id}/override")
async def set_section_override(house_id: str, section_id: str, body: OverrideIn):
    """Pin ONE section against the farm switch.

    For the case where a single tray leaks or a section is being repotted, and
    the farmer wants that one section left alone without turning the whole farm
    manual. Sending null puts it back under the farm switch.
    """
    if body.override not in (None, "auto", "manual"):
        from fastapi import HTTPException
        raise HTTPException(400, "override must be 'auto', 'manual' or null")
    path = f"/farm/houses/{house_id}/sections/{section_id}/control.json"
    ctrl = _fb_get(path) or {}
    if body.override is None:
        ctrl.pop("override", None)
    else:
        ctrl["override"] = body.override
    _fb_put(path, ctrl)
    return {"status": "success", "control": ctrl,
            "effectiveAuto": section_is_auto({"control": ctrl})}


# ═══════════════════════ Alarms the farmer must act on ═══════════════════════
#
# Two kinds, and the difference matters:
#   ACTION  — Auto is off and something needs doing. This is the alarm.
#   INFO    — Auto is on and the system already did it. Courtesy only.
#
# Both are stored under /farm/alarms so the app can show a history, and the
# unacknowledged ACTION ones are what the phone is told to buzz about.

def _raise_alarm(kind: str, key: str, title: str, message: str,
                 house_id: str = None, section_id: str = None,
                 action: str = None) -> dict:
    """Write an alarm, but never the same one twice.

    `key` identifies the event (e.g. 'H1-S1-water-2026-08-21'), so a scheduler
    that ticks every minute cannot spam the farmer with sixty copies of the
    same "water now" alarm.
    """
    path = f"/farm/alarms/{key}.json"
    if _fb_get(path):
        return {}
    alarm = {
        "kind": kind, "title": title, "message": message,
        "houseId": house_id, "sectionId": section_id, "action": action,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "createdAtMs": int(datetime.now(timezone.utc).timestamp() * 1000),
        "acknowledged": False,
        "pushed": False,
    }
    _fb_put(path, alarm)
    return alarm


# ═══════════════════════ Push notifications ══════════════════════════════════
#
# Delivered straight to Firebase Cloud Messaging, so the phone buzzes even with
# the app closed. The app registers its native FCM device token at startup.
#
# GROUPING: if four sections all fall due at 06:01, four separate pushes would
# wake the farmer four times. Instead one push per event type carries the
# section names ("Water 3 sections now: Section 1, Section 2, Section 4"), and
# the app still lists them individually so each can be acted on separately.

# ─────────────────────────── Push, straight to FCM ───────────────────────────
#
# This used to relay through Expo's push service. That path needed an FCM
# service-account key uploaded to an EAS project, and without it Expo rejected
# every message with InvalidCredentials — a whole extra account and an
# interactive CLI standing between a decision and a farmer's phone, for a build
# that is a real APK and never runs in Expo Go.
#
# Sending directly removes Expo from the delivery path entirely: the backend
# holds the service-account key and talks to FCM itself.
#
# The key is a REAL SECRET — unlike google-services.json, which is only client
# config, it grants server-side access to the whole Firebase project. It is
# therefore kept OUTSIDE the repository and never committed. Point
# FIREBASE_ADMIN_KEY at it, or leave it at the default path below.
# The alarm channel the app creates. VERSIONED, and it has to match
# ALARM_CHANNEL in mobile/src/hooks/usePushAlarms.js exactly — a mismatch means
# Android drops the message to a default channel and it stops sounding like an
# alarm. Android also freezes a channel's settings at creation, so changing how
# alarms behave means a new id on BOTH sides.
ALARM_CHANNEL = "farm-alarm-v3"

# An alarm nobody acknowledges is repeated, because the failure this system
# exists to prevent is a plant going unwatered, and a single chime is missed by
# anyone asleep, outdoors, or in another room. It stops the instant the farmer
# acknowledges in the app — and it gives up eventually rather than nagging
# forever at a phone that is switched off.
ALARM_REPEAT_MINUTES = 5
ALARM_REPEAT_MAX = 6          # ~25 minutes of reminders, then it stays in-app only

FIREBASE_KEY_DEFAULT = os.path.join(
    os.path.expanduser("~"), ".orchid-secrets", "firebase-admin.json")

_fcm_app = None
_fcm_error = None


def _fcm():
    """The firebase-admin app, initialised once. None when no key is present.

    A missing key must never crash the engine: the farm has to keep watering
    whether or not anyone's phone can be reached.
    """
    global _fcm_app, _fcm_error
    if _fcm_app is not None:
        return _fcm_app
    path = os.environ.get("FIREBASE_ADMIN_KEY") or FIREBASE_KEY_DEFAULT
    if not os.path.exists(path):
        _fcm_error = f"no service-account key at {path}"
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials
        _fcm_app = firebase_admin.initialize_app(
            credentials.Certificate(path), name="orchid-push")
        _fcm_error = None
        print(f"[AUTO] push: FCM ready ({path})")
        return _fcm_app
    except Exception as e:
        _fcm_error = str(e)
        print(f"[AUTO] push: could not initialise FCM — {e}")
        return None


class PushTokenIn(BaseModel):
    token: str
    platform: Optional[str] = None


@router.post("/push/register")
async def register_push_token(body: PushTokenIn):
    """Remember a phone so alarms can reach it."""
    tok = (body.token or "").strip()
    if not tok:
        from fastapi import HTTPException
        raise HTTPException(400, "token is required")
    # Firebase keys cannot contain . $ # [ ] /
    key = "".join(c if c.isalnum() else "_" for c in tok)
    _fb_put(f"/farm/pushTokens/{key}.json", {
        "token": tok, "platform": body.platform or "unknown",
        "registeredAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    })
    return {"status": "success", "registered": True}


def _push_tokens() -> List[str]:
    raw = _fb_get("/farm/pushTokens.json") or {}
    return [v["token"] for v in raw.values()
            if isinstance(v, dict) and v.get("token")]


def _drop_push_token(token: str) -> None:
    """Forget a phone that FCM says no longer exists (app uninstalled)."""
    raw = _fb_get("/farm/pushTokens.json") or {}
    for k, v in (raw or {}).items():
        if isinstance(v, dict) and v.get("token") == token:
            try:
                _req.delete(f"{FIREBASE_BASE_URL}/farm/pushTokens/{k}.json", timeout=8)
                print(f"[AUTO] dropped dead push token {k}")
            except Exception:
                pass
            return


def _send_push(title: str, body: str, data: dict = None,
               alarm: bool = False) -> dict:
    """Send to every registered phone, and REPORT WHAT ACTUALLY HAPPENED.

    An earlier version POSTed and discarded the response, returning the token
    count, so `/push/test` answered "success, sentTo 1" while every message was
    being rejected. A dead push setup looked healthy indefinitely. That is the
    same failure as calling a pour successful because the server accepted the
    command, and it is why this returns per-token results.

    A phone that has uninstalled the app comes back as UnregisteredError; its
    token is dropped rather than retried forever.

    Never raises. The farm must keep running with no phone registered, no key
    and no internet.
    """
    tokens = _push_tokens()
    if not tokens:
        return {"accepted": 0, "rejected": 0, "tokens": 0, "errors": []}

    app = _fcm()
    if app is None:
        return {"accepted": 0, "rejected": 0, "tokens": len(tokens),
                "errors": [{"error": "NoCredentials", "message": _fcm_error or
                            "no Firebase service-account key configured"}]}

    try:
        import json as _json
        from firebase_admin import messaging
        # FCM data values must all be strings.
        # FCM data values must be strings. A list would arrive at the app as a
        # Python repr ("['H1-S1-water-2026-08-25']"), which is not parseable
        # there, so anything non-scalar is encoded as JSON.
        payload = {}
        for k, v in (data or {}).items():
            payload[str(k)] = (_json.dumps(v) if isinstance(v, (list, dict, tuple))
                               else str(v))

        if alarm:
            # A data-only message carries no title or body of its own, so the
            # words have to travel in the data payload for the service to build
            # the notification from.
            payload["alarm"] = "1"
            payload["title"] = title
            payload["body"] = body

        msgs = [
            messaging.Message(
                # DATA-ONLY for alarms. A message carrying a `notification`
                # block is drawn by the system itself and the app's
                # FirebaseMessagingService is never called while the app is
                # backgrounded or dead - which is exactly when a farmer needs
                # the alarm. OrchidMessagingService builds the notification
                # instead, and attaches the full-screen intent that lets it take
                # over a locked screen. Ordinary pushes keep the notification
                # block, so nothing else changes.
                notification=(None if alarm
                              else messaging.Notification(title=title, body=body)),
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=(None if alarm
                                  else messaging.AndroidNotification(
                                      channel_id=ALARM_CHANNEL, sound="default")),
                ),
                data=payload,
                token=t,
            )
            for t in tokens
        ]
        batch = messaging.send_each(msgs, app=app)

        accepted, errors, dead = 0, [], []
        for tok, r in zip(tokens, batch.responses):
            if r.success:
                accepted += 1
                continue
            exc = r.exception
            name = type(exc).__name__ if exc else "Unknown"
            errors.append({"error": name, "message": str(exc)})
            if name in ("UnregisteredError", "SenderIdMismatchError"):
                dead.append(tok)

        for tok in dead:
            _drop_push_token(tok)
        if errors:
            print(f"[AUTO] push rejected for {len(errors)} of {len(tokens)}: "
                  f"{errors[0].get('error')} — {errors[0].get('message')}")

        return {"accepted": accepted, "rejected": len(errors),
                "tokens": len(tokens), "errors": errors[:3],
                "dropped": len(dead)}
    except Exception as e:
        print(f"[AUTO] push failed (farm continues regardless): {e}")
        return {"accepted": 0, "rejected": 0, "tokens": len(tokens),
                "errors": [{"error": "SendFailed", "message": str(e)}]}


def alarm_due_for_push(v: dict, now: datetime) -> bool:
    """Should this alarm be pushed (or pushed AGAIN) right now?

    Extracted so the rule can be tested without Firebase. The order matters:
    acknowledged is checked first, so tapping Acknowledge silences a repeating
    alarm on the very next tick rather than after the interval expires.
    """
    if not isinstance(v, dict):
        return False
    if v.get("kind") != "action" or v.get("acknowledged"):
        return False

    count = int(v.get("pushCount") or 0)
    if count >= ALARM_REPEAT_MAX:
        return False                      # said enough; it stays in the app

    last = v.get("lastPushedAt")
    if count and last:
        try:
            when = datetime.strptime(last, "%Y-%m-%d %H:%M:%S UTC").replace(
                tzinfo=timezone.utc)
            if (now - when) < timedelta(minutes=ALARM_REPEAT_MINUTES):
                return False              # too soon to nag again
        except (ValueError, TypeError):
            pass                          # unparseable stamp: treat as due
    return True


def _flush_pending_pushes():
    """Push ACTION alarms, and KEEP pushing until the farmer acknowledges.

    This used to send once and set `pushed: True` forever. One notification is
    easy to miss, and the cost of missing it is a plant that never gets watered
    — so an unacknowledged alarm is repeated every ALARM_REPEAT_MINUTES, up to
    ALARM_REPEAT_MAX times, and stops the moment it is acknowledged.

    Still GROUPED: four sections falling due together produce one notification
    naming them, not four separate buzzes, on every repeat as well as the first.
    """
    raw = _fb_get("/farm/alarms.json") or {}
    now = datetime.now(timezone.utc)
    pending = {}
    for k, v in (raw or {}).items():
        if alarm_due_for_push(v, now):
            pending.setdefault(v.get("action") or "other", []).append((k, v))
    if not pending:
        return

    WORDING = {
        "water":     ("Water the plants now", "Water"),
        "fill-tray": ("Fill the humidity tray now", "Fill the tray in"),
    }
    for action, items in pending.items():
        title, verb = WORDING.get(action, ("The farm needs you", "Attend to"))
        names = []
        for _, v in items:
            names.append(v.get("sectionId") or "a section")
        if len(items) == 1:
            body = items[0][1].get("message", "")
            head = title
        else:
            head = f"{verb} {len(items)} sections now"
            body = ", ".join(names) + ". Open the app to do it."
        # A repeat says so, so the farmer can tell a reminder from a new event.
        repeats = max(int(v.get("pushCount") or 0) for _, v in items)
        if repeats:
            head = f"Still waiting — {head[0].lower()}{head[1:]}"

        _send_push(head, body, {"action": action,
                                "alarmIds": [k for k, _ in items]},
                   alarm=True)                        # result logged inside
        for k, v in items:
            v["pushed"] = True                       # kept for older readers
            v["pushCount"] = int(v.get("pushCount") or 0) + 1
            v["lastPushedAt"] = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            _fb_put(f"/farm/alarms/{k}.json", v)


@router.post("/push/test")
async def push_test(alarm: bool = False):
    """Prove the phone is reachable, without waiting for a real alarm.

    `?alarm=true` sends it down the REAL alarm path - data-only, so the app's
    own messaging service builds the notification and attaches the full-screen
    intent. Worth testing separately: the two paths fail differently. An
    ordinary push failing means the token is wrong; the alarm path failing means
    the notification never gets built at all, and a data-only message that
    nothing handles is silent.
    """
    r = _send_push("Orchid Farm test",
                   "If you can see this, alarms will reach your phone.",
                   {"action": "test"}, alarm=alarm)
    ok = r["accepted"] > 0
    return {"status": "success" if ok else "failed",
            "delivered": ok,
            "accepted": r["accepted"],
            "rejected": r["rejected"],
            "registeredTokens": r["tokens"],
            "errors": r["errors"],
            "message": ("FCM accepted the message; it should arrive on the phone."
                        if ok else
                        ("FCM rejected it. " + (r["errors"][0].get("message") or "")
                         if r["errors"] else
                         "No phone has registered for alarms yet."))}


@router.get("/alarms")
async def list_alarms(limit: int = 50):
    """Newest first. `action` items are the ones that need the farmer."""
    raw = _fb_get("/farm/alarms.json") or {}
    items = []
    for k, v in raw.items():
        if isinstance(v, dict):
            items.append({**v, "id": k})
    items.sort(key=lambda x: x.get("createdAtMs", 0), reverse=True)
    pending = [x for x in items if x["kind"] == "action" and not x.get("acknowledged")]
    return {"status": "success", "alarms": items[:limit],
            "pendingAction": len(pending), "autoMode": get_auto_mode()}


@router.put("/alarms/{alarm_id}/ack")
async def ack_alarm(alarm_id: str):
    a = _fb_get(f"/farm/alarms/{alarm_id}.json")
    if a:
        a["acknowledged"] = True
        _fb_put(f"/farm/alarms/{alarm_id}.json", a)
    return {"status": "success"}


# ═══════════════════════ THE WATERING LINK ═══════════════════════════════════
#
# This is the piece that did not exist anywhere. `_plan_section` produced
# "water at 06:01 for 101 s" and stopped; nothing in the backend or the firmware
# ever turned that into an actual command. Since daily sprinkler watering is
# mandatory for Vanda, that meant the plants were only watered when a human
# happened to press a button.

def _today(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _due_sessions(plan: dict, now: datetime, section: Optional[dict] = None) -> List[dict]:
    """Which watering sessions in today's plan are due right now?

    Returns at most the first session and, on an extreme-heat day, the second.
    A session is due once its minute has passed, and stays due for
    WATER_WINDOW_MIN so a backend restart cannot lose the day's watering.
    """
    out = []
    if not plan or plan.get("date") != _today(now):
        return out

    mins_now = now.hour * 60 + now.minute

    def add(tag, hhmm, secs):
        if not hhmm or not secs:
            return
        try:
            h, m = [int(x) for x in str(hhmm).split(":")]
        except (ValueError, AttributeError):
            return
        due_at = h * 60 + m
        if due_at <= mins_now <= due_at + WATER_WINDOW_MIN:
            out.append({"tag": tag, "time": hhmm, "durationSec": int(secs)})

    add("first", plan.get("waterTime"), plan.get("durationSec"))

    # The second session is NOT scheduled at dawn. It is judged in the afternoon
    # on measured temperature, measured humidity and whether the tray coped, and
    # it only qualifies once the morning watering has actually happened - a
    # second watering makes no sense if the first never ran.
    if section is not None and _already_done(section, _today(now), "first"):
        sec = second_session_due(section, now)
        if sec:
            out.append({"tag": "second", "time": now.strftime("%H:%M"),
                        "durationSec": int(sec["durationSec"]), "why": sec["reason"]})
    return out


def _already_done(section: dict, day: str, tag: str) -> bool:
    log = ((section or {}).get("watering") or {}).get("log") or {}
    return bool(log.get(f"{day}-{tag}"))


def _mark_done(house_id: str, section_id: str, day: str, tag: str, how: str):
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/watering/log/{day}-{tag}.json",
            {"at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "by": how})


def run_watering_link(now: datetime, houses: Optional[dict] = None) -> dict:
    """Turn today's plans into real watering, or into alarms when Auto is off.

    `houses` is passed in by the engine pass. Each of the three cycles used to
    fetch /farm/houses.json for itself, so every 60-second tick downloaded the
    whole farm three times over. That is 4,320 downloads a day of a document
    that had grown to 2.4 MB — about 10 GB a day, which is what exhausted the
    Firebase free tier. One fetch per pass now serves all three.
    """
    houses = houses if houses is not None else (_fb_get("/farm/houses.json") or {})
    master = get_auto_mode()
    day = _today(now)
    watered, alarmed = [], []

    for hid, h in (houses or {}).items():
        if not isinstance(h, dict):
            continue
        hname = (h.get("meta") or {}).get("name", hid)
        for sid, s in ((h.get("sections") or {})).items():
            if not isinstance(s, dict) or not s.get("latest"):
                continue
            plan = s.get("plan") or {}
            for sess in _due_sessions(plan, now, s):
                tag = sess["tag"]
                if _already_done(s, day, tag):
                    continue

                sname = (s.get("meta") or {}).get("name", sid)
                fert = s.get("fertilizer") or {}
                # Fertilizer only ever rides inside a watering, never on dry roots.
                with_fert = bool(fert.get("due")) and fert.get("npkType") not in (None, "None")

                if section_is_auto(s, master):
                    # Same cap the relay enforces, so the alarm text and the
                    # pump agree on how long the plants were watered for.
                    secs = max(10, min(sess["durationSec"], RELAY_MAX_SEC))
                    _fb_put(f"/farm/houses/{hid}/sections/{sid}/control/waterCommand.json", {
                        "requested": True,
                        "durationSec": secs,
                        "withFertilizer": with_fert,
                        "triggeredBy": "auto-schedule",
                        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    })
                    # The scheduled watering has to reach the physical node too,
                    # not just the simulator's control/* contract.
                    node_cmd = _issue_node_command(hid, sid, "water", secs,
                                                   withFertilizer=with_fert)
                    if with_fert:
                        # Same reason as the manual path: feeding has to be
                        # recorded or the schedule can never advance. Inside the
                        # auto branch: a section that only ALARMS has not been
                        # fed, and recording one there would silently push its
                        # next feed a week out.
                        _record_fertilized(hid, sid, s)
                    _log_event(hid, sid, s,
                               action="water",
                               durationSec=secs,
                               withFertilizer=bool(with_fert),
                               npkType=(fert.get("npkForStage") or fert.get("npkType")
                                        if with_fert else None),
                               strength=fert.get("strength") if with_fert else None,
                               by="auto",
                               commandId=(node_cmd or {}).get("id"),
                               confirmed=False)
                    _mark_done(hid, sid, day, tag, "auto")
                    watered.append(f"{hid}-{sid}-{tag}")
                    _raise_alarm(
                        "info", f"{hid}-{sid}-water-{day}-{tag}",
                        "Plants watered",
                        f"{hname} · {sname} was watered at {sess['time']} for "
                        f"{sess['durationSec']}s"
                        + (f", with {fert.get('npkType')} plant food mixed in." if with_fert else "."),
                        hid, sid)
                else:
                    alarmed.append(f"{hid}-{sid}-{tag}")
                    _raise_alarm(
                        "action", f"{hid}-{sid}-water-{day}-{tag}",
                        "Water the plants now",
                        f"{hname} · {sname} should be watered now for {sess['durationSec']}s"
                        + (f", with {fert.get('npkType')} plant food." if with_fert else ".")
                        + " Automatic care is off, so please do it from the app.",
                        hid, sid, action="water")

    return {"watered": watered, "alarmed": alarmed}


# ═══════════════════════ Scheduled checks ════════════════════════════════════

def run_tray_cycle(now: datetime, houses: Optional[dict] = None) -> dict:
    """Assess every tray. _tray_decision issues the command itself when the
    section is automatic; when it is not, we alarm instead."""
    houses = houses if houses is not None else (_fb_get("/farm/houses.json") or {})
    # pass the pass's clock down, so a simulated run stays self-consistent
    results = _run_per_section(houses, partial(_tray_decision, now=now))
    master = get_auto_mode()
    alarmed = []

    for key, r in results.items():
        if not isinstance(r, dict) or r.get("status") not in ("fill", "topup"):
            continue
        if r.get("autoCommanded"):
            continue                       # handled automatically, nothing to say
        hid, _, sid = key.partition("-")
        s = _fb_get(f"/farm/houses/{hid}/sections/{sid}.json") or {}
        if section_is_auto(s, master):
            continue                       # auto but not commanded => in cooldown
        sname = (s.get("meta") or {}).get("name", sid)
        alarmed.append(key)
        _raise_alarm(
            "action", f"{hid}-{sid}-tray-{now.strftime('%Y-%m-%d-%H')}",
            "Fill the humidity tray now",
            f"{sname}: humidity is {r.get('humidity')}%. Open the tray valve for "
            f"{r.get('fillSeconds')}s. Automatic care is off, so please do it from the app.",
            hid, sid, action="fill-tray")

    return {"checked": len(results), "alarmed": alarmed}


def run_plan_cycle(now: Optional[datetime] = None, houses: Optional[dict] = None) -> dict:
    """Generate today's watering plan (and the fertilizer decision) per section.

    The plan is DATED with `now`. That matters: the watering link later asks
    "is this plan for today?", and if the plan was stamped with the real date
    while the pass is running on a simulated one, the two never match and the
    day's watering is silently skipped."""
    houses = houses if houses is not None else (_fb_get("/farm/houses.json") or {})
    results = _run_per_section(houses, partial(_plan_section, now=now))
    return {"planned": len(results)}


# ═══════════════════════ The clock ═══════════════════════════════════════════

_state: Dict[str, object] = {
    "running": False, "lastTick": None, "lastTray": None,
    "lastPlanDay": None, "ticks": 0, "errors": 0, "lastError": None,
}


def _engine_pass(now: datetime) -> dict:
    """One pass. Kept separate from the loop so tests can call it directly.

    The farm is fetched ONCE here and handed to each cycle. Fetching it per
    cycle downloaded the whole document three times a minute, which is how a
    2.4 MB /farm/houses.json turned into roughly 10 GB of egress a day and
    exhausted the Firebase free tier.
    """
    did = {}
    houses = _fb_get("/farm/houses.json") or {}

    # 1. Today's plan, once per day, after dawn so the dawn reading exists.
    if _state["lastPlanDay"] != _today(now) and now.hour >= PLAN_HOUR_LOCAL:
        did["plan"] = run_plan_cycle(now, houses)
        _state["lastPlanDay"] = _today(now)

    # 2. Humidity trays, every TRAY_CHECK_MINUTES.
    last_tray = _state["lastTray"]
    if last_tray is None or (now - last_tray) >= timedelta(minutes=TRAY_CHECK_MINUTES):
        did["tray"] = run_tray_cycle(now, houses)
        _state["lastTray"] = now

    # 3. Watering, checked every tick because a planned minute must not be missed.
    did["water"] = run_watering_link(now, houses)

    # 4. Anything the farmer must act on gets pushed to their phone, grouped so
    #    four due sections do not mean four separate buzzes.
    _flush_pending_pushes()

    _state["lastTick"] = now
    _state["ticks"] = int(_state["ticks"]) + 1
    return did


async def _engine_loop():
    """Wakes up every TICK_SECONDS for as long as the server is up."""
    _state["running"] = True
    print(f"[AUTO] automation engine started (tick {TICK_SECONDS}s)")
    while True:
        try:
            if _ready():
                await asyncio.to_thread(_engine_pass, farm_now())
        except Exception as e:                      # never let one bad pass kill the clock
            _state["errors"] = int(_state["errors"]) + 1
            _state["lastError"] = str(e)
            print(f"[AUTO] pass failed: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(TICK_SECONDS)


def start_engine():
    """Called from main.py on startup."""
    asyncio.get_event_loop().create_task(_engine_loop())


@router.get("/engine")
async def engine_status():
    """Proof the clock is alive — useful in the demo and in the report."""
    return {
        "status": "success",
        "running": _state["running"],
        "tickSeconds": TICK_SECONDS,
        "trayCheckMinutes": TRAY_CHECK_MINUTES,
        "ticks": _state["ticks"],
        "errors": _state["errors"],
        "lastError": _state["lastError"],
        "lastTick": str(_state["lastTick"]),
        "lastTrayCheck": str(_state["lastTray"]),
        "lastPlanDay": _state["lastPlanDay"],
        "autoMode": get_auto_mode(),
    }


@router.post("/engine/run-now")
async def run_now(at: Optional[str] = None):
    """Run one pass immediately, instead of waiting for the next tick.

    `at` lets a caller say what time it should pretend it is, as
    "YYYY-MM-DD HH:MM". The farm simulator needs this: it runs many times faster
    than real time, so without it the watering link would only ever be tested at
    whatever o'clock the real server happens to be at, and a simulated 06:01
    watering could never be exercised at all.

    Only the pass is affected — every decision inside still uses the section's
    own device clock, exactly as it does in production.
    """
    # `at` is given in FARM local time, because that is the clock every watering
    # decision is expressed in - "06:34" in a plan means 06:34 for the plants.
    if at:
        try:
            now = datetime.strptime(at.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=farm_tz())
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "at must look like '2026-08-21 06:01'")
    else:
        now = farm_now()

    did = await asyncio.to_thread(_engine_pass, now)
    return {"status": "success", "at": now.strftime("%Y-%m-%d %H:%M:%S %Z"), "did": did}
