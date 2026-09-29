"""Data models and enums for live GPS navigation, progress tracking, and re-routing."""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Tuple

from accessroute.preferences.models import MobilityPreferences


class NavigationState(str, Enum):
    """Client-side navigation lifecycle states."""

    IDLE = "IDLE"
    ACQUIRING_LOCATION = "ACQUIRING_LOCATION"
    READY = "READY"
    NAVIGATING = "NAVIGATING"
    OFF_ROUTE = "OFF_ROUTE"
    REROUTING = "REROUTING"
    ARRIVED = "ARRIVED"
    LOCATION_UNAVAILABLE = "LOCATION_UNAVAILABLE"
    ERROR = "ERROR"


class AccuracyQualityBand(str, Enum):
    """Observable quality bands for raw GPS horizontal accuracy."""

    HIGH_ACCURACY = "HIGH_ACCURACY"        # <= 10m
    MODERATE_ACCURACY = "MODERATE_ACCURACY"  # 10m - 25m
    LOW_ACCURACY = "LOW_ACCURACY"            # 25m - 50m
    VERY_LOW_ACCURACY = "VERY_LOW_ACCURACY"  # > 50m

    @classmethod
    def from_accuracy_meters(cls, accuracy_m: float) -> "AccuracyQualityBand":
        if accuracy_m <= 10.0:
            return cls.HIGH_ACCURACY
        elif accuracy_m <= 25.0:
            return cls.MODERATE_ACCURACY
        elif accuracy_m <= 50.0:
            return cls.LOW_ACCURACY
        else:
            return cls.VERY_LOW_ACCURACY


class DeviationState(str, Enum):
    """Off-route deviation classification."""

    ON_ROUTE = "ON_ROUTE"
    POSSIBLY_OFF_ROUTE = "POSSIBLY_OFF_ROUTE"
    OFF_ROUTE = "OFF_ROUTE"


class UpcomingEventType(str, Enum):
    """Types of accessibility events detected ahead along route corridor."""

    KERB_UNKNOWN = "KERB_UNKNOWN"
    KERB_LOWERED = "KERB_LOWERED"
    KERB_RAISED = "KERB_RAISED"
    STAIRS = "STAIRS"
    UNPAVED_SURFACE = "UNPAVED_SURFACE"
    STEEP_ESTIMATED_GRADE = "STEEP_ESTIMATED_GRADE"
    COMMUNITY_BLOCKAGE = "COMMUNITY_BLOCKAGE"
    CONSTRUCTION = "CONSTRUCTION"
    BARRIER = "BARRIER"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    UNKNOWN_WIDTH = "UNKNOWN_WIDTH"


@dataclass
class GPSLocation:
    """Current raw GPS reading with accuracy and motion properties."""

    latitude: float
    longitude: float
    accuracy_m: float
    heading: Optional[float] = None
    speed_mps: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def quality_band(self) -> AccuracyQualityBand:
        return AccuracyQualityBand.from_accuracy_meters(self.accuracy_m)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy_m": round(self.accuracy_m, 1),
            "heading": round(self.heading, 1) if self.heading is not None else None,
            "speed_mps": round(self.speed_mps, 2) if self.speed_mps is not None else None,
            "quality_band": self.quality_band.value,
            "timestamp": self.timestamp,
        }


@dataclass
class UpcomingAccessibilityEvent:
    """Actionable accessibility event detected ahead on active route corridor."""

    type: str  # UpcomingEventType value
    distance_ahead_m: float
    severity: str  # "info" | "warning" | "critical"
    evidence_source: str  # "osm" | "copernicus_dem" | "community"
    description: str
    segment_id: Optional[str] = None
    verification_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "distance_ahead_m": round(self.distance_ahead_m, 1),
            "severity": self.severity,
            "evidence_source": self.evidence_source,
            "description": self.description,
            "segment_id": self.segment_id,
            "verification_status": self.verification_status,
        }


@dataclass
class RouteProgress:
    """Deterministic snapshot of user position and progress along selected route."""

    distance_along_route_m: float
    remaining_distance_m: float
    completion_percentage: float
    nearest_point: Tuple[float, float]
    cross_track_distance_m: float
    current_segment_index: int
    current_step_index: int
    next_maneuver: str
    next_instruction: str
    distance_to_next_maneuver_m: float
    estimated_remaining_duration_min: int
    deviation_state: DeviationState
    accuracy_band: AccuracyQualityBand
    is_arrived: bool = False
    upcoming_events: List[UpcomingAccessibilityEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "distance_along_route_m": round(self.distance_along_route_m, 1),
            "remaining_distance_m": round(self.remaining_distance_m, 1),
            "completion_percentage": round(self.completion_percentage, 1),
            "nearest_point": {"latitude": self.nearest_point[0], "longitude": self.nearest_point[1]},
            "cross_track_distance_m": round(self.cross_track_distance_m, 1),
            "current_segment_index": self.current_segment_index,
            "current_step_index": self.current_step_index,
            "next_maneuver": self.next_maneuver,
            "next_instruction": self.next_instruction,
            "distance_to_next_maneuver_m": round(self.distance_to_next_maneuver_m, 1),
            "estimated_remaining_duration_min": self.estimated_remaining_duration_min,
            "deviation_state": self.deviation_state.value,
            "accuracy_band": self.accuracy_band.value,
            "is_arrived": self.is_arrived,
            "upcoming_events": [e.to_dict() for e in self.upcoming_events],
        }


@dataclass
class RerouteRequest:
    """Request payload for off-route or obstacle-triggered rerouting."""

    current_position: Tuple[float, float]
    destination: Tuple[float, float]
    mobility_preferences: Optional[MobilityPreferences] = None
    original_route_distance_m: Optional[float] = None
    reroute_reason: str = "deviation"
    reroute_token: Optional[str] = None


@dataclass
class RerouteResult:
    """Outcome of an accessibility-aware re-routing calculation."""

    success: bool
    new_route: Optional[Any] = None  # RouteAlternative / RouteAlternativeSchema
    reroute_reason: str = "deviation"
    distance_delta_m: float = 0.0
    explanation: str = ""
    blocking_reasons: List[str] = field(default_factory=list)
    reroute_token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "reroute_reason": self.reroute_reason,
            "distance_delta_m": round(self.distance_delta_m, 1),
            "explanation": self.explanation,
            "blocking_reasons": self.blocking_reasons,
            "reroute_token": self.reroute_token,
        }
