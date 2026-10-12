"""
Hybrid Pollination — Pydantic Schemas
Request/response models for the pollination API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict
from enum import Enum


class LeafCondition(str, Enum):
    healthy = "healthy"
    moderate = "moderate"
    weak = "weak"
    unknown = "unknown"


class PlantStrength(str, Enum):
    strong = "strong"
    moderate = "moderate"
    weak = "weak"
    unknown = "unknown"


class DiseaseVisible(str, Enum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


class FlowerCondition(str, Enum):
    good = "good"
    moderate = "moderate"
    weak = "weak"
    unknown = "unknown"


class SuitabilityLabel(str, Enum):
    suitable = "Suitable"
    moderate = "Moderate"
    not_suitable = "Not Suitable"


# ──────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────
class PlantTraitsInput(BaseModel):
    """Plant trait data provided by the user."""
    leaf_condition: LeafCondition = LeafCondition.unknown
    plant_strength: PlantStrength = PlantStrength.unknown
    disease_visible: DiseaseVisible = DiseaseVisible.unknown
    flower_condition: FlowerCondition = FlowerCondition.unknown


# ──────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────
class ResolvedTraitOut(BaseModel):
    """One trait, plus where its value came from."""
    name: str
    value: str
    source: str = Field(..., description="measured | user | unknown")
    confidence: float = Field(..., description="How far the value can be trusted (0-1)")
    explanation: str = Field("", description="Plain-language reasoning for the grower")
    needs_user_input: bool = Field(
        False, description="Measurement too weak to act on - ask the grower"
    )
    suggested_value: str = Field("", description="Best guess, when there is one")
    evidence: Dict = Field(default_factory=dict, description="Measurements behind the value")


class TraitResolutionOut(BaseModel):
    """How every trait was determined for one assessment."""
    traits: Dict[str, ResolvedTraitOut]
    asked_for: list = Field(
        default_factory=list,
        description="Traits the system could not determine from the image"
    )
    fully_automatic: bool = Field(
        ..., description="True when no user input was needed at all"
    )


class InputCheckOut(BaseModel):
    """
    Result of screening an upload before it is assessed.

    The suitability model cannot say "this is not a plant" - it has three
    classes and forces every input onto one of them. This carries the separate
    judgement of whether the photograph shows an orchid at all.
    """
    is_orchid: bool = Field(..., description="Whether the image may be assessed")
    gate_available: bool = Field(
        True, description="False when the validation model is not installed, in "
                          "which case is_orchid is not a real judgement."
    )
    message: str = Field("", description="Explanation written for the grower")
    distance: Optional[float] = Field(
        None, description="Novelty distance from the training photographs"
    )
    threshold: Optional[float] = Field(
        None, description="Distance beyond which an image is refused"
    )
    vegetation: Optional[float] = Field(
        None, description="Share of the frame that reads as plant tissue (0-1)"
    )
    orchid_probability: Optional[float] = Field(
        None, description="Stage 2: probability this is an orchid rather than "
                          "another flower. Null when the stage is not installed."
    )
    familiarity: Optional[str] = Field(
        None, description="'typical' or 'unusual' - how ordinary this photograph "
                          "is for the reference collection. An 'unusual' photo "
                          "still gets a verdict, but it is an extrapolation and "
                          "the confidence is damped to say so."
    )
    typical_limit: Optional[float] = Field(
        None, description="Novelty distance below which a photo counts as typical"
    )
    confidence: Optional[float] = Field(
        None, description="Confidence in a refusal (0 when accepted)"
    )


class SuitabilityResponse(BaseModel):
    """Response from the suitability assessment endpoint."""
    suitability: str = Field(..., description="Predicted suitability label")
    confidence: float = Field(..., description="Prediction confidence (0-1)")
    probabilities: Dict[str, float] = Field(
        ..., description="Probability for each class"
    )
    recommendation: str = Field(..., description="Human-readable recommendation")
    features_extracted: int = Field(..., description="Number of image features extracted")
    trait_resolution: Optional[TraitResolutionOut] = Field(
        None,
        description="Where each trait value came from. Null when trait resolution "
                    "was disabled or unavailable."
    )
    input_check: Optional[InputCheckOut] = Field(
        None,
        description="Confirmation that the upload was screened and accepted as "
                    "an orchid. A refused image never reaches this response - "
                    "the endpoint returns 422 instead."
    )


class HealthResponse(BaseModel):
    """API health check response."""
    status: str
    model_loaded: bool
    model_name: str = ""
    classes: list = []


class ErrorResponse(BaseModel):
    """Standard error response."""
    status: str = "error"
    message: str
    detail: Optional[str] = None


# ──────────────────────────────────────────────
# Level 2 — Parent A × Parent B Compatibility
# ──────────────────────────────────────────────
class ParentHealth(BaseModel):
    """A Level 1 assessment result, carried into a Level 2 cross check."""
    suitability: str = Field(..., description="Suitable | Moderate | Not Suitable")
    confidence: float = 0.0


class CompatibilityRequest(BaseModel):
    """
    A directional pairing.

    Order is meaningful: by breeding convention the pod (seed) parent is named
    first and the pollen donor second. A × B is a different attempt from B × A,
    so these fields are never swapped or sorted.
    """
    pod_parent: str = Field(
        ..., description="Plant that will carry the seed pod", min_length=1
    )
    pollen_parent: str = Field(
        ..., description="Plant donating the pollen", min_length=1
    )
    pod_health: Optional[ParentHealth] = Field(
        None, description="Level 1 assessment of the pod parent, if the grower "
                          "photographed it first"
    )
    pollen_health: Optional[ParentHealth] = Field(
        None, description="Level 1 assessment of the pollen parent"
    )


class CompatibilityResponse(BaseModel):
    """Verdict on one pairing, with the evidence behind it.

    There is deliberately no success probability. The orchid register records
    only crosses that worked, so it has no denominator and no rate can be
    derived from it. `tier` and `precedents` carry the evidence instead.
    """
    pod_parent: str
    pollen_parent: str
    tier: str = Field(..., description="registered | genus_proven | undemonstrated | blocked")
    tier_label: str
    headline: str
    reasoning: list = []
    precedents: list = Field([], description="Registered crosses cited as evidence")
    pod_genus: str = ""
    pollen_genus: str = ""
    cross_type: str = Field("", description="interspecific | intergeneric")
    expected_offspring: Dict = {}
    suggestion: str = ""
    warnings: list = []
    compatibility_class: str = Field(
        "", description="Compatible | Low Compatibility | Not Advised — a "
                        "two-class summary of the evidence tier"
    )
    health_used: bool = Field(
        False, description="Whether a Level 1 assessment was factored in"
    )
    name_check: Dict = Field(
        {}, description="How each typed name was understood — keys 'pod' and "
                        "'pollen', each with genus, genus_source "
                        "(stated|matched|assumed), recognised and did_you_mean. "
                        "An assumed genus means the engine fell back to the "
                        "collection's genus because the name carried none and "
                        "was not in the knowledge base."
    )


class PartnerRankRequest(BaseModel):
    """Rank several candidate pollen donors against one pod parent."""
    pod_parent: str = Field(..., min_length=1)
    candidates: list = Field(..., description="Candidate pollen donor names")


# ──────────────────────────────────────────────
#  Grower cross logbook
# ──────────────────────────────────────────────
class CrossLogRequest(BaseModel):
    """
    One attempted cross, as the grower performed it.

    Order is meaningful here for the same reason it is in CompatibilityRequest:
    the pod parent carries the capsule and the pollen parent donates, so a
    record that sorted the pair would be recording a different attempt from
    the one that was made.

    The covariates are optional but they are the difference between a usable
    record and a useless one. A cross can fail because two plants are
    incompatible, or because the flower was too old, or because stored pollen
    had died. Logging only the outcome makes those indistinguishable forever.
    """
    pod_plant_id: str = Field(..., min_length=1, description="Registered plant carrying the pod")
    pollen_plant_id: str = Field(..., min_length=1, description="Registered plant donating pollen")
    pod_health: Optional[ParentHealth] = Field(
        None, description="Level 1 assessment of the pod parent ON THE DAY, copied "
                          "in as a snapshot rather than linked"
    )
    pollen_health: Optional[ParentHealth] = None
    flower_age_days: Optional[int] = Field(
        None, description="Days since the pollinated flower opened — the largest "
                          "single technique variable"
    )
    pollen_source: str = Field("fresh", description="fresh | stored")
    pollen_stored_days: Optional[int] = None
    logged_by: str = ""
    notes: str = ""
    conditions: Dict = Field(
        {}, description="Temperature / humidity at pollination, from the farm sensors"
    )


class CrossStageRequest(BaseModel):
    """
    Move a cross forward, or close it where it failed.

    Exactly one of `stage` or `outcome` is expected. `outcome` names the gate
    it stopped at — no_pod_set, capsule_aborted, capsule_empty,
    no_germination — or `lost`, which is censored data and is deliberately
    NOT a failure.
    """
    stage: str = ""
    outcome: str = ""
    note: str = ""
