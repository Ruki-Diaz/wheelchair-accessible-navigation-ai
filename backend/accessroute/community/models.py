"""Domain models and provenance representations for Community Accessibility Evidence.

Stage 9 Architecture:
Distinguishes evidence sources across:
1. OpenStreetMap (OSM)
2. Community Observation
3. Terrain Model (Copernicus DEM)
4. System Derived
5. Future Authority Data

Maintains strict provenance, explicit verification states, and conflict visibility.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid


class AccessibilityEvidenceSource(str, Enum):
    """Authoritative source of a piece of accessibility evidence."""
    OPENSTREETMAP = "openstreetmap"
    COMMUNITY_OBSERVATION = "community_observation"
    TERRAIN_ESTIMATE = "terrain_estimate"
    SYSTEM_DERIVED = "system_derived"
    FUTURE_AUTHORITY_DATA = "future_authority_data"


class ObservationCategory(str, Enum):
    """Categorical classification of community-reported accessibility observations."""
    KERB = "kerb"
    STAIRS = "stairs"
    RAMP = "ramp"
    SURFACE = "surface"
    PATH_WIDTH = "path_width"
    SLOPE = "slope"
    BARRIER = "barrier"
    TEMPORARY_OBSTACLE = "temporary_obstacle"
    CONSTRUCTION = "construction"
    PATH_BLOCKED = "path_blocked"
    LIFT_STATUS = "lift_status"
    ENTRANCE_ACCESSIBILITY = "entrance_accessibility"
    OTHER = "other"


# Standard structured values for categories
STRUCTURED_VALUES: Dict[ObservationCategory, List[str]] = {
    ObservationCategory.KERB: [
        "lowered",
        "flush",
        "raised",
        "no_kerb",
        "unknown",
    ],
    ObservationCategory.STAIRS: [
        "present",
        "absent",
        "without_ramp",
        "with_ramp",
        "steep_flight",
        "other",
    ],
    ObservationCategory.RAMP: [
        "present",
        "absent",
        "wheelchair_designated",
        "too_steep",
    ],
    ObservationCategory.SURFACE: [
        "asphalt",
        "concrete",
        "paved",
        "paving_stones",
        "compacted",
        "gravel",
        "dirt",
        "grass",
        "cobblestone",
        "other",
    ],
    ObservationCategory.BARRIER: [
        "gate",
        "bollard",
        "cycle_barrier",
        "turnstile",
        "construction_barrier",
        "other",
    ],
    ObservationCategory.PATH_BLOCKED: [
        "construction",
        "fallen_tree",
        "flooding",
        "event_fencing",
        "parked_vehicle",
        "overgrowth",
        "other",
    ],
    ObservationCategory.TEMPORARY_OBSTACLE: [
        "construction",
        "roadworks",
        "debris",
        "event_barrier",
        "scaffolding",
        "other",
    ],
    ObservationCategory.CONSTRUCTION: [
        "footpath_closed",
        "crossing_closed",
        "scaffolding_narrowed",
        "roadworks",
        "other",
    ],
    ObservationCategory.LIFT_STATUS: [
        "operational",
        "out_of_service",
        "unknown",
    ],
    ObservationCategory.ENTRANCE_ACCESSIBILITY: [
        "level_entry",
        "ramped",
        "steps_only",
        "inaccessible",
        "entrance_exists",
        "entrance_moved",
        "step_free",
        "steps_present",
        "ramp_present",
        "automatic_door",
        "manual_door",
        "door_width",
        "temporary_closure",
        "lift_unavailable",
        "threshold_lip",
        "entrance_inaccessible",
    ],
    ObservationCategory.PATH_WIDTH: [
        "adequate",
        "narrow",
        "impassable",
    ],
    ObservationCategory.SLOPE: [
        "gentle",
        "moderate",
        "steep",
    ],
    ObservationCategory.OTHER: [
        "other",
    ],
}


class VerificationStatus(str, Enum):
    """Deterministic community verification status."""
    UNVERIFIED = "unverified"
    COMMUNITY_SUPPORTED = "community_supported"
    COMMUNITY_DISPUTED = "community_disputed"
    VERIFIED = "verified"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass
class CommunityObservation:
    """A structured, geo-located accessibility observation submitted by a user."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: AccessibilityEvidenceSource = AccessibilityEvidenceSource.COMMUNITY_OBSERVATION
    category: ObservationCategory = ObservationCategory.OTHER
    value: str = "other"
    latitude: float = 0.0
    longitude: float = 0.0

    # Matching to OpenStreetMap elements
    osm_element_type: Optional[str] = None  # 'way' | 'node' | None
    osm_element_id: Optional[int] = None
    matched_distance_m: Optional[float] = None
    match_confidence: Optional[float] = None

    # Temporal properties
    is_temporary: bool = False
    reported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expected_end_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Verification lifecycle
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confirmations_count: int = 1
    disputes_count: int = 0

    # Privacy-conscious metadata
    contributor_id: Optional[str] = None
    notes: Optional[str] = None
    photo_url: Optional[str] = None

    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Return True if this observation is active and not expired or rejected."""
        if self.verification_status in (VerificationStatus.EXPIRED, VerificationStatus.REJECTED):
            return False
        if self.is_temporary and self.expires_at is not None:
            current_time = now or datetime.now(timezone.utc)
            # Ensure timezone-aware comparison
            if self.expires_at.tzinfo is None:
                exp = self.expires_at.replace(tzinfo=timezone.utc)
            else:
                exp = self.expires_at
            if current_time > exp:
                return False
        return True

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Return True if a temporary observation has passed its expiration time."""
        if not self.is_temporary or self.expires_at is None:
            return False
        current_time = now or datetime.now(timezone.utc)
        exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
        return current_time > exp

    def to_dict(self) -> Dict[str, Any]:
        """Serialize observation to a dictionary."""
        return {
            "id": self.id,
            "source": self.source.value,
            "category": self.category.value,
            "value": self.value,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "matched_distance_m": self.matched_distance_m,
            "match_confidence": self.match_confidence,
            "is_temporary": self.is_temporary,
            "reported_at": self.reported_at.isoformat(),
            "expected_end_at": self.expected_end_at.isoformat() if self.expected_end_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "verification_status": self.verification_status.value,
            "confirmations_count": self.confirmations_count,
            "disputes_count": self.disputes_count,
            "contributor_id": self.contributor_id,
            "notes": self.notes,
            "photo_url": self.photo_url,
            "is_active": self.is_active(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommunityObservation":
        """Reconstruct observation from dictionary representation."""
        def parse_dt(v: Any) -> Optional[datetime]:
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v))
            except Exception:
                return None

        return cls(
            id=str(data.get("id", str(uuid.uuid4()))),
            source=AccessibilityEvidenceSource(data.get("source", AccessibilityEvidenceSource.COMMUNITY_OBSERVATION.value)),
            category=ObservationCategory(data.get("category", ObservationCategory.OTHER.value)),
            value=str(data.get("value", "other")),
            latitude=float(data.get("latitude", 0.0)),
            longitude=float(data.get("longitude", 0.0)),
            osm_element_type=data.get("osm_element_type"),
            osm_element_id=int(data["osm_element_id"]) if data.get("osm_element_id") is not None else None,
            matched_distance_m=float(data["matched_distance_m"]) if data.get("matched_distance_m") is not None else None,
            match_confidence=float(data["match_confidence"]) if data.get("match_confidence") is not None else None,
            is_temporary=bool(data.get("is_temporary", False)),
            reported_at=parse_dt(data.get("reported_at")) or datetime.now(timezone.utc),
            expected_end_at=parse_dt(data.get("expected_end_at")),
            expires_at=parse_dt(data.get("expires_at")),
            verification_status=VerificationStatus(data.get("verification_status", VerificationStatus.UNVERIFIED.value)),
            confirmations_count=int(data.get("confirmations_count", 0)),
            disputes_count=int(data.get("disputes_count", 0)),
            contributor_id=data.get("contributor_id"),
            notes=data.get("notes"),
            photo_url=data.get("photo_url"),
        )


@dataclass
class VerificationOpportunity:
    """An identified geographic accessibility data gap that invites community verification."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    latitude: float = 0.0
    longitude: float = 0.0
    osm_element_type: str = "way"  # 'way' | 'node'
    osm_element_id: int = 0
    missing_attribute: str = "kerb"  # 'kerb' | 'surface' | 'width' | 'incline'
    feature_type: str = "crossing"  # 'crossing' | 'footway' | 'barrier'
    importance_reason: str = "Pedestrian crossing lacks recorded kerb ramp status in OpenStreetMap."
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "missing_attribute": self.missing_attribute,
            "feature_type": self.feature_type,
            "importance_reason": self.importance_reason,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class EvidenceConflict:
    """Explicitly detected disagreement between OpenStreetMap and active Community observations."""
    osm_element_type: str
    osm_element_id: int
    latitude: float
    longitude: float
    attribute_name: str
    osm_claim: str
    community_claim: str
    conflict_summary: str
    community_observation_id: str
    verification_status: VerificationStatus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "attribute_name": self.attribute_name,
            "osm_claim": self.osm_claim,
            "community_claim": self.community_claim,
            "conflict_summary": self.conflict_summary,
            "community_observation_id": self.community_observation_id,
            "verification_status": self.verification_status.value,
        }
