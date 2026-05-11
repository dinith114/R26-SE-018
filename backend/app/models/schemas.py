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
class SuitabilityResponse(BaseModel):
    """Response from the suitability assessment endpoint."""
    suitability: str = Field(..., description="Predicted suitability label")
    confidence: float = Field(..., description="Prediction confidence (0-1)")
    probabilities: Dict[str, float] = Field(
        ..., description="Probability for each class"
    )
    recommendation: str = Field(..., description="Human-readable recommendation")
    features_extracted: int = Field(..., description="Number of image features extracted")


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
