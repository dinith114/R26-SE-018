"""The Automatic care switch must cover every path that can move water.

Why this file exists. There were two different answers to "may this section act
by itself":

    automation.section_is_auto()  -> farm switch + control.override
    _tray_decision()              -> control.mode != "manual"   (the LEGACY key)

`/farm/meta/autoMode` replaced `mode`/`trayEnabled`/`fertEnabled`, so the tray
path was consulting a key nothing sets any more and ignoring the master switch
entirely. On 24 Aug 2026 the farm had `autoMode: false` while H1/S5 still
carried `control.mode: "auto"` — so "Check Tray" would have opened a valve while
the app was telling the farmer the system would only alert them.

The app makes a promise on that switch. These tests hold it to it.
"""
import pytest

from app.api.routes.smart_care_v2 import section_acts_alone
from app.api.routes.automation import section_is_auto


def _section(**control):
    return {"control": control} if control else {"control": {}}


# ── the farm switch ────────────────────────────────────────────────────────

def test_farm_switch_off_stops_a_plain_section():
    assert section_acts_alone(_section(), master=False) is False


def test_farm_switch_on_lets_a_plain_section_act():
    assert section_acts_alone(_section(), master=True) is True


def test_legacy_mode_key_cannot_override_the_farm_switch():
    """The regression. `mode` is the retired per-section key; a section still
    carrying mode:'auto' must NOT act while the farm switch is off."""
    sec = _section(mode="auto", trayEnabled=True)
    assert section_acts_alone(sec, master=False) is False, (
        "the legacy control.mode key is overriding the farm's Automatic care "
        "switch — this is what let Check Tray open a valve with auto off")


def test_legacy_mode_manual_does_not_block_an_explicit_override():
    sec = _section(mode="manual", override="auto")
    assert section_acts_alone(sec, master=False) is True


# ── the per-section override, which deliberately beats the farm switch ─────

def test_override_auto_beats_the_farm_switch():
    assert section_acts_alone(_section(override="auto"), master=False) is True


def test_override_manual_beats_the_farm_switch():
    assert section_acts_alone(_section(override="manual"), master=True) is False


def test_absent_override_follows_the_farm():
    assert section_acts_alone(_section(), master=True) is True
    assert section_acts_alone(_section(), master=False) is False


# ── one definition, not two ───────────────────────────────────────────────

@pytest.mark.parametrize("control", [
    {},
    {"mode": "auto"},
    {"mode": "manual"},
    {"override": "auto"},
    {"override": "manual"},
    {"mode": "auto", "override": "manual"},
    {"mode": "manual", "override": "auto"},
])
@pytest.mark.parametrize("master", [True, False])
def test_both_entry_points_agree(control, master):
    """automation.section_is_auto delegates to smart_care_v2.section_acts_alone.
    If these ever diverge again, one path will move water when the other says no."""
    assert section_is_auto({"control": control}, master) is \
           section_acts_alone({"control": control}, master)
