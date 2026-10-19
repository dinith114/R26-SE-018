"""The rule that a measured weak plant is never reported Suitable.

Component 1 runs two sets of models against one photograph. The suitability
classifier scores the plant Suitable / Moderate / Not Suitable, and separate
trait models read leaf condition and plant strength. They are trained on
different features, so they can disagree - and during field testing they did:
the screen showed "Leaf Condition weak", "Plant Strength weak", and a headline
of Suitable above them.

Printing a note under that contradiction does not settle it. It asks the grower
to arbitrate between two of the system's own models, which is the system's job.
So a measured weak trait now HOLDS the verdict at Not Suitable.

The veto runs one way only, and these tests pin that direction. A weak reading
can stop a permissive verdict; a healthy reading can never create one. The trait
models are the weaker evidence - plant strength 0.698, leaf condition 0.557
accuracy - and evidence that weak should be able to withhold a recommendation
without being able to manufacture one.
"""
import pytest

from app.services.hybrid_pollination_service import HybridPollinationService

conflict = HybridPollinationService._trait_conflict


def _res(**traits):
    """A resolution report carrying the named traits.

    Each value is (value, source); source matters because only a MEASURED weak
    reading may veto. A value the grower typed, or one the resolver could not
    determine, carries no veto - see test_user_supplied_weak_does_not_veto.
    """
    return {"traits": {name: {"value": v, "source": s}
                       for name, (v, s) in traits.items()}}


# ── the veto fires ────────────────────────────────────────────
@pytest.mark.parametrize("permissive", ["Suitable", "Moderate"])
def test_measured_weak_vetoes_a_permissive_verdict(permissive):
    """Both labels that green-light a cross are subject to the veto.

    Moderate is included because it still tells the grower the plant "may be
    used for pollination". A plant measured weak should not be pollinated on
    either label.
    """
    out = conflict(permissive, _res(leaf_condition=("weak", "measured")))
    assert out, "a measured weak leaf must veto %s" % permissive
    assert "Not Suitable" in out


def test_both_traits_weak_are_both_named():
    out = conflict("Suitable", _res(leaf_condition=("weak", "measured"),
                                    plant_strength=("weak", "measured")))
    assert "leaf condition" in out and "plant strength" in out


def test_message_does_not_blame_the_plant_for_a_reading():
    """The grower is told to trust the plant over the photograph.

    The veto is an abundance-of-caution rule resting on a 0.557-accuracy
    model, not a diagnosis. The wording has to leave room for the reading
    itself to be wrong, or a grower who can see a healthy plant stops
    believing the app.
    """
    out = conflict("Suitable", _res(plant_strength=("weak", "measured")))
    assert "Inspect the plant" in out


# ── the veto does NOT fire ────────────────────────────────────
def test_healthy_readings_never_promote():
    """The one-way direction. A healthy trait reading is not a veto in reverse.

    Were this to return a message for Not Suitable, the service would flip the
    label the other way and let two weak models overturn the classifier.
    """
    assert conflict("Not Suitable", _res(leaf_condition=("healthy", "measured"),
                                         plant_strength=("strong", "measured"))) == ""


def test_user_supplied_weak_does_not_veto():
    """Only a MEASURED weak reading vetoes.

    The trait input card was removed from the app after Progress Presentation 1
    asked why a system that reads a photograph needs typed input, so in the
    shipped flow this source does not arise. The API still accepts trait
    overrides, though, and a caller must not be able to force a Not Suitable
    verdict by posting leaf_condition=weak alongside the image.
    """
    assert conflict("Suitable", _res(leaf_condition=("weak", "user"))) == ""


def test_unmeasurable_trait_does_not_veto():
    """An absent reading is not a bad reading.

    disease_visible measures `unknown` on every whole-plant frame, and flower
    condition answers "none" on ~99% of them because the bloom detector's
    whole-plant recall is 1%. If missing evidence vetoed, every whole-plant
    photograph would come back Not Suitable.
    """
    assert conflict("Suitable", _res(leaf_condition=("unknown", "unknown"))) == ""


def test_moderate_reading_does_not_veto():
    """Only `weak` vetoes. `moderate` is not a weak plant."""
    assert conflict("Suitable", _res(leaf_condition=("moderate", "measured"),
                                     plant_strength=("moderate", "measured"))) == ""


def test_no_resolution_at_all_does_not_veto():
    """Trait resolution is optional - auto_traits=False skips it entirely.

    With nothing measured there is no disagreement to act on, and the
    classifier's verdict stands unaltered.
    """
    assert conflict("Suitable", None) == ""
    assert conflict("Suitable", {}) == ""


def test_flower_condition_is_not_a_veto_trait():
    """Measured and "none", and still not a veto - deliberately.

    A plant with no open flower cannot be pollinated today, which looks like
    the strongest possible veto. It is not usable as one: the bloom gate's
    whole-plant recall is 1% at the shipped threshold (MIN_FLOWER_FRACTION,
    flower_analysis.py), so "none" on a whole-plant photo means "this framing
    cannot show me a flower", not "this plant has none". Vetoing on it would
    report almost every whole-plant photograph - blooming plants included - as
    Not Suitable.
    """
    assert conflict("Suitable", _res(flower_condition=("none", "measured"))) == ""


# ── visible disease, the veto the reference labels imply ──────
def test_measured_disease_vetoes():
    """Measured on the 28 annotated plants: of the 10 marked disease=yes, 9
    were labelled Not Suitable and none Suitable. Disease is the trait the
    reference labels were actually made with - it accounts for 26 of the 28 -
    so a measured `yes` has to stop a permissive verdict."""
    out = conflict("Suitable", _res(disease_visible=("yes", "measured")))
    assert "visible disease" in out and "Not Suitable" in out


def test_disease_veto_beats_a_moderate_verdict_too():
    out = conflict("Moderate", _res(disease_visible=("yes", "measured")))
    assert "visible disease" in out


def test_disease_no_is_not_a_veto():
    """The one-way rule again. A clean reading does not promote, and must not
    veto either - 17 of the 18 plants marked disease=no were labelled
    Suitable."""
    assert conflict("Suitable", _res(disease_visible=("no", "measured"))) == ""


def test_unknown_disease_is_not_a_veto():
    """`unknown` is what a whole-plant frame returns, on every one of them.

    resolve_disease answers `unknown` until the signal clears ACT_THRESHOLD,
    which a whole-plant photograph does not - the lesions span 1-3 px at that
    distance (AUC 0.51). If unknown vetoed, every whole-plant upload would
    come back Not Suitable.
    """
    assert conflict("Suitable", _res(disease_visible=("unknown", "unknown"))) == ""


def test_user_claimed_disease_does_not_veto():
    """A posted trait value cannot force a Not Suitable verdict - the same
    guard as the weak traits, for the same reason."""
    assert conflict("Suitable", _res(disease_visible=("yes", "user"))) == ""


def test_disease_is_reported_in_preference_to_weakness():
    """Both present: the message names disease, not the weak leaf.

    Disease rests on a 0.806 model and is actionable - treat the plant - while
    `weak` rests on 0.557 and is not. Leading with the weaker evidence would
    bury the thing the grower can do something about.
    """
    out = conflict("Suitable", _res(disease_visible=("yes", "measured"),
                                    leaf_condition=("weak", "measured")))
    assert "visible disease" in out
    assert "leaf condition" not in out
