"""Domain models and typed representations for OpenStreetMap accessibility evidence.

Stage 2 Architecture:
Strictly distinguishes between:
1. Raw OSM evidence (unmodified strings/lists directly from OpenStreetMap)
2. Normalized categorical models (type-safe Enums and parsed Value Objects)
3. Deterministic findings (factual observations derived solely from present evidence)
4. Unknown/missing fields (explicitly recognized; never defaulted or invented)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class WheelchairAccess(str, Enum):
    """Explicit wheelchair accessibility status from OpenStreetMap 'wheelchair' tag."""
    YES = "yes"
    DESIGNATED = "designated"
    LIMITED = "limited"
    NO = "no"
    UNKNOWN = "unknown"
    OTHER = "other"


class SurfaceType(str, Enum):
    """Normalized surface material from OpenStreetMap 'surface' tag."""
    ASPHALT = "asphalt"
    PAVED = "paved"
    CONCRETE = "concrete"
    CONCRETE_PLATES = "concrete:plates"
    PAVING_STONES = "paving_stones"
    COMPACTED = "compacted"
    FINE_GRAVEL = "fine_gravel"
    GRAVEL = "gravel"
    GROUND = "ground"
    DIRT = "dirt"
    GRASS = "grass"
    COBBLESTONE = "cobblestone"
    UNKNOWN = "unknown"
    OTHER = "other"


class KerbType(str, Enum):
    """Normalized kerb height profile from OpenStreetMap 'kerb' tag."""
    FLUSH = "flush"
    LOWERED = "lowered"
    ROLLED = "rolled"
    RAISED = "raised"
    NO = "no"
    UNKNOWN = "unknown"
    OTHER = "other"


class SmoothnessType(str, Enum):
    """Normalized surface smoothness from OpenStreetMap 'smoothness' tag."""
    EXCELLENT = "excellent"
    GOOD = "good"
    INTERMEDIATE = "intermediate"
    BAD = "bad"
    VERY_BAD = "very_bad"
    HORRIBLE = "horrible"
    VERY_HORRIBLE = "very_horrible"
    IMPASSABLE = "impassable"
    UNKNOWN = "unknown"
    OTHER = "other"


class TactilePaving(str, Enum):
    """Normalized tactile paving indicator from OpenStreetMap 'tactile_paving' tag."""
    YES = "yes"
    NO = "no"
    INCORRECT = "incorrect"
    PRIMITIVE = "primitive"
    UNKNOWN = "unknown"
    OTHER = "other"


class BarrierType(str, Enum):
    """Normalized barrier classification from OpenStreetMap 'barrier' tag."""
    NONE = "none"
    BOLLARD = "bollard"
    GATE = "gate"
    CYCLE_BARRIER = "cycle_barrier"
    TURNSTILE = "turnstile"
    BLOCK = "block"
    DEBRIS = "debris"
    KERB = "kerb"
    LIFT_GATE = "lift_gate"
    SWING_GATE = "swing_gate"
    UNKNOWN = "unknown"
    OTHER = "other"


class FindingType(str, Enum):
    """Deterministic, factual observations derived strictly from confirmed OSM tags.

    No arbitrary scores or penalties are assigned. These findings record what
    is explicitly known or verifiable from the physical infrastructure.
    """
    # Wheelchair-specific findings
    WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED = "WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED"
    WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED = "WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED"
    WHEELCHAIR_ACCESS_LIMITED = "WHEELCHAIR_ACCESS_LIMITED"

    # Infrastructure obstacles & steps
    STEPS_PRESENT = "STEPS_PRESENT"
    RAMP_PRESENT = "RAMP_PRESENT"
    RAMP_WHEELCHAIR_DESIGNATED = "RAMP_WHEELCHAIR_DESIGNATED"
    HANDRAIL_PRESENT = "HANDRAIL_PRESENT"

    # Kerb findings
    FLUSH_KERB_RECORDED = "FLUSH_KERB_RECORDED"
    LOWERED_KERB_RECORDED = "LOWERED_KERB_RECORDED"
    RAISED_KERB_RECORDED = "RAISED_KERB_RECORDED"
    ROLLED_KERB_RECORDED = "ROLLED_KERB_RECORDED"

    # Surface findings
    PAVED_SURFACE_RECORDED = "PAVED_SURFACE_RECORDED"
    UNPAVED_SURFACE_RECORDED = "UNPAVED_SURFACE_RECORDED"
    ROUGH_SURFACE_RECORDED = "ROUGH_SURFACE_RECORDED"

    # Crossing & safety findings
    PEDESTRIAN_CROSSING_RECORDED = "PEDESTRIAN_CROSSING_RECORDED"
    SIGNALIZED_CROSSING_RECORDED = "SIGNALIZED_CROSSING_RECORDED"
    MARKED_CROSSING_RECORDED = "MARKED_CROSSING_RECORDED"
    TACTILE_PAVING_RECORDED = "TACTILE_PAVING_RECORDED"
    LIT_AT_NIGHT = "LIT_AT_NIGHT"

    # Incline and terrain findings
    STEEP_INCLINE_RECORDED = "STEEP_INCLINE_RECORDED"  # >= 8% or <= -8%
    STEEP_UPHILL_RECORDED = "STEEP_UPHILL_RECORDED"    # >= +8% directional grade
    STEEP_DOWNHILL_RECORDED = "STEEP_DOWNHILL_RECORDED" # <= -8% directional grade
    MODERATE_UPHILL_RECORDED = "MODERATE_UPHILL_RECORDED" # +5% to +8%
    MODERATE_DOWNHILL_RECORDED = "MODERATE_DOWNHILL_RECORDED" # -8% to -5%
    ELEVATION_EVIDENCE_AVAILABLE = "ELEVATION_EVIDENCE_AVAILABLE"
    ELEVATION_EVIDENCE_MISSING = "ELEVATION_EVIDENCE_MISSING"
    SUSPICIOUS_GRADE_FLAGGED = "SUSPICIOUS_GRADE_FLAGGED"

    # Barrier findings
    RESTRICTIVE_BARRIER_RECORDED = "RESTRICTIVE_BARRIER_RECORDED"  # e.g., turnstile, cycle_barrier
    PASSABLE_BARRIER_RECORDED = "PASSABLE_BARRIER_RECORDED"  # e.g., bollard, gate (may be passable depending on spacing)

    # Access constraints
    RESTRICTED_ACCESS_RECORDED = "RESTRICTED_ACCESS_RECORDED"  # private or permissive access

    # Community evidence findings
    COMMUNITY_PATH_BLOCKED = "COMMUNITY_PATH_BLOCKED"
    COMMUNITY_CONSTRUCTION_REPORTED = "COMMUNITY_CONSTRUCTION_REPORTED"
    COMMUNITY_STAIRS_REPORTED = "COMMUNITY_STAIRS_REPORTED"
    COMMUNITY_UNVERIFIED_OBSTACLE = "COMMUNITY_UNVERIFIED_OBSTACLE"
    COMMUNITY_CONFLICT_FLAGGED = "COMMUNITY_CONFLICT_FLAGGED"


@dataclass(frozen=True)
class InclineMeasurement:
    """Represents normalized longitudinal slope information.

    Does NOT assume missing incline is 0%.
    """
    raw: str = ""
    percentage: Optional[float] = None  # e.g. 5.0 for 5%, -8.0 for -8%
    direction: Optional[str] = None  # e.g. 'up', 'down'
    is_parsed: bool = False

    @property
    def is_known(self) -> bool:
        return self.is_parsed and (self.percentage is not None or self.direction is not None)


@dataclass(frozen=True)
class WidthMeasurement:
    """Represents normalized passage clearance width in meters.

    Does NOT guess ambiguous or missing widths.
    """
    raw: str = ""
    width_meters: Optional[float] = None
    is_parsed: bool = False

    @property
    def is_known(self) -> bool:
        return self.is_parsed and self.width_meters is not None

    @property
    def meters(self) -> Optional[float]:
        return self.width_meters


@dataclass
class EdgeAccessibilityEvidence:
    """Comprehensive accessibility evidence extracted for a single network edge (way)."""
    # Primary normalized attributes
    wheelchair: WheelchairAccess = WheelchairAccess.UNKNOWN
    surface: SurfaceType = SurfaceType.UNKNOWN
    kerb: KerbType = KerbType.UNKNOWN
    smoothness: SmoothnessType = SmoothnessType.UNKNOWN
    tactile_paving: TactilePaving = TactilePaving.UNKNOWN
    incline: InclineMeasurement = field(default_factory=InclineMeasurement)
    width: WidthMeasurement = field(default_factory=WidthMeasurement)

    # Path classification attributes
    highway_type: str = "unknown"
    footway_type: Optional[str] = None
    is_crossing: bool = False
    crossing_signals: bool = False
    crossing_markings: Optional[str] = None
    is_steps: bool = False
    step_count: Optional[int] = None
    has_ramp: bool = False
    has_wheelchair_ramp: bool = False
    is_lit: Optional[bool] = None
    access: str = "yes"

    # Deterministic factual findings (no arbitrary scores)
    findings: Set[FindingType] = field(default_factory=set)

    # Explicit audit of missing fields
    missing_fields: List[str] = field(default_factory=list)

    # Full preserved raw attributes for auditability
    raw_tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert evidence to a serializable dictionary."""
        return {
            "wheelchair": self.wheelchair.value,
            "surface": self.surface.value,
            "kerb": self.kerb.value,
            "smoothness": self.smoothness.value,
            "tactile_paving": self.tactile_paving.value,
            "incline_percentage": self.incline.percentage,
            "incline_direction": self.incline.direction,
            "incline_raw": self.incline.raw,
            "width_meters": self.width.width_meters,
            "width_raw": self.width.raw,
            "highway_type": self.highway_type,
            "footway_type": self.footway_type,
            "is_crossing": self.is_crossing,
            "crossing_signals": self.crossing_signals,
            "crossing_markings": self.crossing_markings,
            "is_steps": self.is_steps,
            "step_count": self.step_count,
            "has_ramp": self.has_ramp,
            "has_wheelchair_ramp": self.has_wheelchair_ramp,
            "is_lit": self.is_lit,
            "access": self.access,
            "findings": sorted([f.value for f in self.findings]),
            "missing_fields": sorted(self.missing_fields),
            "raw_tags": self.raw_tags,
        }


@dataclass
class NodeAccessibilityEvidence:
    """Comprehensive accessibility evidence extracted for a single network node (point)."""
    node_id: int
    latitude: float
    longitude: float
    kerb: KerbType = KerbType.UNKNOWN
    tactile_paving: TactilePaving = TactilePaving.UNKNOWN
    barrier: BarrierType = BarrierType.NONE
    wheelchair: WheelchairAccess = WheelchairAccess.UNKNOWN
    is_crossing: bool = False
    has_traffic_signals: bool = False

    # Deterministic findings for this point
    findings: Set[FindingType] = field(default_factory=set)

    # Explicit audit of missing fields
    missing_fields: List[str] = field(default_factory=list)

    # Preserved raw tags
    raw_tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert evidence to a serializable dictionary."""
        return {
            "node_id": self.node_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "kerb": self.kerb.value,
            "tactile_paving": self.tactile_paving.value,
            "barrier": self.barrier.value,
            "wheelchair": self.wheelchair.value,
            "is_crossing": self.is_crossing,
            "has_traffic_signals": self.has_traffic_signals,
            "findings": sorted([f.value for f in self.findings]),
            "missing_fields": sorted(self.missing_fields),
            "raw_tags": self.raw_tags,
        }


class SlopeDirection(str, Enum):
    """Categorical slope direction relative to travel direction along directed edge."""
    FLAT = "flat"
    UPHILL = "uphill"
    DOWNHILL = "downhill"
    UNKNOWN = "unknown"


@dataclass
class NodeElevationEvidence:
    """Elevation data attached to a single network node."""
    elevation_m: Optional[float] = None
    source: str = "UNKNOWN"
    status: str = "UNKNOWN"  # "MEASURED", "INTERPOLATED", "MISSING"
    is_known: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elevation_m": self.elevation_m,
            "source": self.source,
            "status": self.status,
            "is_known": self.is_known,
        }


@dataclass
class EdgeTerrainEvidence:
    """Terrain and elevation profile evidence for a single directed edge u -> v."""
    elevation_start_m: Optional[float] = None
    elevation_end_m: Optional[float] = None
    elevation_change_m: Optional[float] = None
    length_m: float = 0.0
    signed_grade: Optional[float] = None  # e.g. +0.06 for 6% uphill, -0.04 for 4% downhill
    absolute_grade: Optional[float] = None
    direction: SlopeDirection = SlopeDirection.UNKNOWN
    is_grade_suspicious: bool = False
    grade_uncertainty: Optional[float] = None
    elevation_source: str = "UNKNOWN"
    elevation_gain_m: float = 0.0
    elevation_loss_m: float = 0.0
    max_intermediate_grade: Optional[float] = None
    sample_count: int = 2
    is_known: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elevation_start_m": self.elevation_start_m,
            "elevation_end_m": self.elevation_end_m,
            "elevation_change_m": self.elevation_change_m,
            "length_m": self.length_m,
            "signed_grade": self.signed_grade,
            "absolute_grade": self.absolute_grade,
            "direction": self.direction.value,
            "is_grade_suspicious": self.is_grade_suspicious,
            "grade_uncertainty": self.grade_uncertainty,
            "elevation_source": self.elevation_source,
            "elevation_gain_m": self.elevation_gain_m,
            "elevation_loss_m": self.elevation_loss_m,
            "max_intermediate_grade": self.max_intermediate_grade,
            "sample_count": self.sample_count,
            "is_known": self.is_known,
        }

