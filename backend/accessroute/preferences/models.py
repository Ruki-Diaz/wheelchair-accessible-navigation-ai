"""User mobility preferences and personal accessibility constraints domain model.

Represents user-controlled navigation preferences across stairs, terrain slopes,
surface materials, kerb transitions, path widths, and data missingness tolerance.
"""

from enum import Enum
import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class AvoidanceLevel(str, Enum):
    """Semantic avoidance levels for environmental conditions."""
    ALLOW = "allow"
    PREFER_AVOID = "prefer_avoid"
    STRICTLY_AVOID = "strictly_avoid"


class StepPreference(str, Enum):
    """Specific user constraints regarding staircases."""
    NEVER = "never"                # Strict hard prohibition on mapped stairs without ramps
    AVOID_WHEN_POSSIBLE = "avoid_when_possible"  # Soft penalty for stairs; allows if no alternative
    PREFER_AVOID = "prefer_avoid"  # Alias for avoid_when_possible
    ALLOW = "allow"                # Neutral towards stairs


class KerbPreference(str, Enum):
    """User preferences for kerb transitions at crossings."""
    PREFER_LOWERED = "prefer_lowered"  # Prioritize flush or ramped kerb transitions
    AVOID_RAISED = "avoid_raised"      # Heavy penalty on confirmed raised kerbs
    ALLOW_ANY = "allow_any"            # No kerb preference


class DataConfidenceLevel(str, Enum):
    """Global user tolerance for missing or unrecorded accessibility information."""
    FLEXIBLE = "flexible"    # Accepts paths with missing attributes to prevent detours
    BALANCED = "balanced"    # Moderate caution; prefers verified infrastructure when reasonable
    CAUTIOUS = "cautious"    # Strongly prefers documented infrastructure and penalizes unknowns


class MobilityPresetName(str, Enum):
    """Standard starting mobility profile presets (not universal clinical standards)."""
    MANUAL_WHEELCHAIR = "manual_wheelchair"
    POWERED_WHEELCHAIR = "powered_wheelchair"
    MOBILITY_SCOOTER = "mobility_scooter"
    WALKER = "walker"
    PRAM = "pram"
    CUSTOM = "custom"


class MobilityPreferences(BaseModel):
    """User-controlled mobility and accessibility routing preferences."""

    preset_name: MobilityPresetName = Field(
        default=MobilityPresetName.MANUAL_WHEELCHAIR,
        description="Starting preset identifier.",
    )

    # 1. Stairs & Steps
    steps: StepPreference = Field(
        default=StepPreference.NEVER,
        description="Preference regarding mapped stairs and steps.",
    )

    # 2. Terrain & Slope Thresholds (Percentages)
    max_preferred_uphill_grade_pct: float = Field(
        default=6.0,
        ge=0.0,
        le=25.0,
        description="Uphill gradient % above which terrain penalties apply.",
    )
    max_permitted_uphill_grade_pct: Optional[float] = Field(
        default=10.0,
        ge=0.0,
        le=30.0,
        description="Hard maximum uphill gradient %; slopes steeper than this are strictly prohibited.",
    )

    max_preferred_downhill_grade_pct: float = Field(
        default=7.0,
        ge=0.0,
        le=25.0,
        description="Downhill gradient % above which descent risk penalties apply.",
    )
    max_permitted_downhill_grade_pct: Optional[float] = Field(
        default=12.0,
        ge=0.0,
        le=30.0,
        description="Hard maximum downhill gradient %; steeper descents are strictly prohibited.",
    )

    # 3. Surface Tolerances
    unpaved_surfaces: AvoidanceLevel = Field(
        default=AvoidanceLevel.PREFER_AVOID,
        description="Avoidance level for unpaved surfaces (gravel, dirt, grass, compacted).",
    )
    rough_surfaces: AvoidanceLevel = Field(
        default=AvoidanceLevel.PREFER_AVOID,
        description="Avoidance level for rough paved surfaces (cobblestone, rough setts).",
    )
    unknown_surfaces: AvoidanceLevel = Field(
        default=AvoidanceLevel.ALLOW,
        description="Avoidance level when path surface material is unrecorded in OSM.",
    )

    # 4. Kerbs & Pedestrian Crossings
    kerb_preference: KerbPreference = Field(
        default=KerbPreference.AVOID_RAISED,
        description="Preference for kerb cuts and transitions.",
    )
    unknown_kerbs: AvoidanceLevel = Field(
        default=AvoidanceLevel.PREFER_AVOID,
        description="Avoidance level for crossings with unknown kerb ramp status.",
    )

    # 5. Dimensions & Barriers
    minimum_path_width_m: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=3.0,
        description="Minimum required path clearance width in meters.",
    )
    unknown_width: AvoidanceLevel = Field(
        default=AvoidanceLevel.ALLOW,
        description="Treatment of paths where width is unrecorded in OSM.",
    )
    narrow_paths: AvoidanceLevel = Field(
        default=AvoidanceLevel.ALLOW,
        description="Avoidance level for paths narrower than minimum width.",
    )
    avoid_restrictive_barriers: AvoidanceLevel = Field(
        default=AvoidanceLevel.STRICTLY_AVOID,
        description="Treatment of narrow barriers (turnstiles, cycle chicanes, kissing gates).",
    )

    # 6. Global Data Confidence / Missingness Tolerance
    data_confidence: DataConfidenceLevel = Field(
        default=DataConfidenceLevel.BALANCED,
        description="Global tolerance for missing accessibility metadata.",
    )

    @model_validator(mode="before")
    @classmethod
    def map_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            mapping = {
                "preset": "preset_name",
                "avoid_steps": "steps",
                "preferred_maximum_uphill_grade_pct": "max_preferred_uphill_grade_pct",
                "maximum_permitted_uphill_grade_pct": "max_permitted_uphill_grade_pct",
                "preferred_maximum_downhill_grade_pct": "max_preferred_downhill_grade_pct",
                "maximum_permitted_downhill_grade_pct": "max_permitted_downhill_grade_pct",
                "avoid_unpaved_surfaces": "unpaved_surfaces",
                "avoid_unknown_kerbs": "unknown_kerbs",
                "avoid_unknown_width": "unknown_width",
                "avoid_narrow_paths": "narrow_paths",
            }
            res = dict(data)
            for old_k, new_k in mapping.items():
                if old_k in res and new_k not in res:
                    res[new_k] = res.pop(old_k)
            return res
        return data

    @property
    def preset(self) -> MobilityPresetName:
        return self.preset_name

    @preset.setter
    def preset(self, val: MobilityPresetName) -> None:
        self.preset_name = val

    @property
    def avoid_steps(self) -> StepPreference:
        return self.steps

    @avoid_steps.setter
    def avoid_steps(self, val: StepPreference) -> None:
        self.steps = val

    @property
    def preferred_maximum_uphill_grade_pct(self) -> float:
        return self.max_preferred_uphill_grade_pct

    @preferred_maximum_uphill_grade_pct.setter
    def preferred_maximum_uphill_grade_pct(self, val: float) -> None:
        self.max_preferred_uphill_grade_pct = val

    @property
    def maximum_permitted_uphill_grade_pct(self) -> Optional[float]:
        return self.max_permitted_uphill_grade_pct

    @maximum_permitted_uphill_grade_pct.setter
    def maximum_permitted_uphill_grade_pct(self, val: Optional[float]) -> None:
        self.max_permitted_uphill_grade_pct = val

    @property
    def preferred_maximum_downhill_grade_pct(self) -> float:
        return self.max_preferred_downhill_grade_pct

    @preferred_maximum_downhill_grade_pct.setter
    def preferred_maximum_downhill_grade_pct(self, val: float) -> None:
        self.max_preferred_downhill_grade_pct = val

    @property
    def maximum_permitted_downhill_grade_pct(self) -> Optional[float]:
        return self.max_permitted_downhill_grade_pct

    @maximum_permitted_downhill_grade_pct.setter
    def maximum_permitted_downhill_grade_pct(self, val: Optional[float]) -> None:
        self.max_permitted_downhill_grade_pct = val

    @model_validator(mode="after")
    def validate_slopes_and_finite(self) -> "MobilityPreferences":
        """Ensure preferred slopes do not exceed hard maximums and values are finite."""
        if not math.isfinite(self.max_preferred_uphill_grade_pct):
            raise ValueError("max_preferred_uphill_grade_pct must be a finite number.")

        if self.max_permitted_uphill_grade_pct is not None:
            if not math.isfinite(self.max_permitted_uphill_grade_pct):
                raise ValueError("max_permitted_uphill_grade_pct must be a finite number.")
            if self.max_preferred_uphill_grade_pct > self.max_permitted_uphill_grade_pct:
                raise ValueError(
                    f"Preferred uphill slope ({self.max_preferred_uphill_grade_pct}%) cannot exceed "
                    f"hard maximum permitted uphill slope ({self.max_permitted_uphill_grade_pct}%)."
                )

        if not math.isfinite(self.max_preferred_downhill_grade_pct):
            raise ValueError("max_preferred_downhill_grade_pct must be a finite number.")

        if self.max_permitted_downhill_grade_pct is not None:
            if not math.isfinite(self.max_permitted_downhill_grade_pct):
                raise ValueError("max_permitted_downhill_grade_pct must be a finite number.")
            if self.max_preferred_downhill_grade_pct > self.max_permitted_downhill_grade_pct:
                raise ValueError(
                    f"Preferred downhill slope ({self.max_preferred_downhill_grade_pct}%) cannot exceed "
                    f"hard maximum permitted downhill slope ({self.max_permitted_downhill_grade_pct}%)."
                )

        return self


# =============================================================================
# STARTING MOBILITY PRESETS
# Note: These are configurable starting templates, NOT universal clinical facts.
# =============================================================================

def get_preset_preferences(preset: MobilityPresetName) -> MobilityPreferences:
    """Return a starting MobilityPreferences configuration for a named profile."""
    if preset == MobilityPresetName.MANUAL_WHEELCHAIR:
        return MobilityPreferences(
            preset_name=MobilityPresetName.MANUAL_WHEELCHAIR,
            steps=StepPreference.NEVER,
            max_preferred_uphill_grade_pct=4.0,
            max_permitted_uphill_grade_pct=8.0,
            max_preferred_downhill_grade_pct=6.0,
            max_permitted_downhill_grade_pct=10.0,
            unpaved_surfaces=AvoidanceLevel.PREFER_AVOID,
            rough_surfaces=AvoidanceLevel.PREFER_AVOID,
            unknown_surfaces=AvoidanceLevel.ALLOW,
            kerb_preference=KerbPreference.AVOID_RAISED,
            unknown_kerbs=AvoidanceLevel.PREFER_AVOID,
            avoid_restrictive_barriers=AvoidanceLevel.STRICTLY_AVOID,
            data_confidence=DataConfidenceLevel.BALANCED,
        )

    if preset == MobilityPresetName.POWERED_WHEELCHAIR:
        return MobilityPreferences(
            preset_name=MobilityPresetName.POWERED_WHEELCHAIR,
            steps=StepPreference.NEVER,
            max_preferred_uphill_grade_pct=6.0,
            max_permitted_uphill_grade_pct=12.0,
            max_preferred_downhill_grade_pct=8.0,
            max_permitted_downhill_grade_pct=14.0,
            unpaved_surfaces=AvoidanceLevel.PREFER_AVOID,
            rough_surfaces=AvoidanceLevel.PREFER_AVOID,
            unknown_surfaces=AvoidanceLevel.ALLOW,
            kerb_preference=KerbPreference.AVOID_RAISED,
            unknown_kerbs=AvoidanceLevel.PREFER_AVOID,
            minimum_path_width_m=0.9,
            unknown_width=AvoidanceLevel.ALLOW,
            avoid_restrictive_barriers=AvoidanceLevel.STRICTLY_AVOID,
            data_confidence=DataConfidenceLevel.BALANCED,
        )

    if preset == MobilityPresetName.MOBILITY_SCOOTER:
        return MobilityPreferences(
            preset_name=MobilityPresetName.MOBILITY_SCOOTER,
            steps=StepPreference.NEVER,
            max_preferred_uphill_grade_pct=7.0,
            max_permitted_uphill_grade_pct=12.0,
            max_preferred_downhill_grade_pct=8.0,
            max_permitted_downhill_grade_pct=12.0,
            unpaved_surfaces=AvoidanceLevel.PREFER_AVOID,
            rough_surfaces=AvoidanceLevel.PREFER_AVOID,
            unknown_surfaces=AvoidanceLevel.ALLOW,
            kerb_preference=KerbPreference.AVOID_RAISED,
            unknown_kerbs=AvoidanceLevel.PREFER_AVOID,
            minimum_path_width_m=1.0,
            unknown_width=AvoidanceLevel.ALLOW,
            avoid_restrictive_barriers=AvoidanceLevel.STRICTLY_AVOID,
            data_confidence=DataConfidenceLevel.BALANCED,
        )

    if preset == MobilityPresetName.WALKER:
        return MobilityPreferences(
            preset_name=MobilityPresetName.WALKER,
            steps=StepPreference.PREFER_AVOID,
            max_preferred_uphill_grade_pct=5.0,
            max_permitted_uphill_grade_pct=10.0,
            max_preferred_downhill_grade_pct=6.0,
            max_permitted_downhill_grade_pct=10.0,
            unpaved_surfaces=AvoidanceLevel.PREFER_AVOID,
            rough_surfaces=AvoidanceLevel.PREFER_AVOID,
            unknown_surfaces=AvoidanceLevel.ALLOW,
            kerb_preference=KerbPreference.AVOID_RAISED,
            unknown_kerbs=AvoidanceLevel.PREFER_AVOID,
            avoid_restrictive_barriers=AvoidanceLevel.PREFER_AVOID,
            data_confidence=DataConfidenceLevel.BALANCED,
        )

    if preset == MobilityPresetName.PRAM:
        return MobilityPreferences(
            preset_name=MobilityPresetName.PRAM,
            steps=StepPreference.PREFER_AVOID,
            max_preferred_uphill_grade_pct=6.0,
            max_permitted_uphill_grade_pct=14.0,
            max_preferred_downhill_grade_pct=8.0,
            max_permitted_downhill_grade_pct=14.0,
            unpaved_surfaces=AvoidanceLevel.ALLOW,
            rough_surfaces=AvoidanceLevel.ALLOW,
            unknown_surfaces=AvoidanceLevel.ALLOW,
            kerb_preference=KerbPreference.PREFER_LOWERED,
            unknown_kerbs=AvoidanceLevel.ALLOW,
            avoid_restrictive_barriers=AvoidanceLevel.PREFER_AVOID,
            data_confidence=DataConfidenceLevel.FLEXIBLE,
        )

    # Default Custom
    return MobilityPreferences(preset_name=MobilityPresetName.CUSTOM)
