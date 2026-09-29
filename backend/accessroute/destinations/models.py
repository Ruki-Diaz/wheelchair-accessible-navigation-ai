"""Domain models for Destination, Venue, and Entrance Intelligence.

Stage 13 Architecture:
Solves the destination vs. entrance gap: reaching a venue centroid != reaching
a usable, accessible entrance. Maintains strict evidence provenance, explicit
unknowns, and deterministic compliance assessments against MobilityPreferences.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class VenueType(str, Enum):
    """Categorical classification of destination venues."""
    BUILDING = "building"
    SHOPPING_CENTRE = "shopping_centre"
    STATION = "station"
    HOSPITAL = "hospital"
    UNIVERSITY = "university"
    PUBLIC_FACILITY = "public_facility"
    BUSINESS = "business"
    PARK = "park"
    ADDRESS = "address"
    POINT_OF_INTEREST = "point_of_interest"
    ARBITRARY_COORDINATE = "arbitrary_coordinate"


class EntranceType(str, Enum):
    """Functional classification of building / venue entrances."""
    MAIN = "main"
    SECONDARY = "secondary"
    ACCESSIBLE = "accessible"
    CAR_PARK = "car_park"
    SERVICE = "service"
    EMERGENCY = "emergency"
    DELIVERY = "delivery"
    UNKNOWN = "unknown"


class EvidenceProvenance(str, Enum):
    """Authoritative source of entrance accessibility evidence."""
    OPENSTREETMAP = "openstreetmap"
    COMMUNITY_OBSERVATION = "community_observation"
    VENUE_DATA = "venue_data"
    SYSTEM_DERIVED = "system_derived"
    UNKNOWN = "unknown"


class EntranceAssessmentStatus(str, Enum):
    """Deterministic accessibility evaluation of an entrance against user preferences."""
    MATCHES_CURRENT_PREFERENCES = "matches_current_preferences"
    PARTIALLY_VERIFIED = "partially_verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    DOES_NOT_MATCH_CURRENT_PREFERENCES = "does_not_match_current_preferences"
    TEMPORARILY_REPORTED_UNAVAILABLE = "temporarily_reported_unavailable"


@dataclass
class EntranceAccessibilityEvidence:
    """Detailed accessibility attributes and evidence for an entrance."""
    wheelchair: str = "unknown"  # "yes", "no", "limited", "unknown"
    step_free: Optional[bool] = None
    steps_count: Optional[int] = None
    ramp: str = "unknown"  # "yes", "no", "wheelchair_designated", "too_steep", "unknown"
    automatic_door: Optional[bool] = None
    door_type: str = "unknown"  # "sliding", "swing", "revolving", "automatic", "manual", "unknown"
    door_width_m: Optional[float] = None
    threshold_height_cm: Optional[float] = None
    lift_access: str = "unknown"  # "yes", "no", "operational", "out_of_service", "unknown"
    opening_hours: Optional[str] = None
    source: EvidenceProvenance = EvidenceProvenance.UNKNOWN
    source_timestamp: Optional[str] = None
    osm_element_id: Optional[str] = None
    community_observation_ids: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    is_temporary: bool = False
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wheelchair": self.wheelchair,
            "step_free": self.step_free,
            "steps_count": self.steps_count,
            "ramp": self.ramp,
            "automatic_door": self.automatic_door,
            "door_type": self.door_type,
            "door_width_m": self.door_width_m,
            "threshold_height_cm": self.threshold_height_cm,
            "lift_access": self.lift_access,
            "opening_hours": self.opening_hours,
            "source": self.source.value if isinstance(self.source, EvidenceProvenance) else str(self.source),
            "source_timestamp": self.source_timestamp,
            "osm_element_id": self.osm_element_id,
            "community_observation_ids": self.community_observation_ids,
            "notes": self.notes,
            "is_temporary": self.is_temporary,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntranceAccessibilityEvidence":
        src = data.get("source", EvidenceProvenance.UNKNOWN)
        if isinstance(src, str):
            try:
                src = EvidenceProvenance(src)
            except ValueError:
                src = EvidenceProvenance.UNKNOWN

        return cls(
            wheelchair=data.get("wheelchair", "unknown"),
            step_free=data.get("step_free"),
            steps_count=data.get("steps_count"),
            ramp=data.get("ramp", "unknown"),
            automatic_door=data.get("automatic_door"),
            door_type=data.get("door_type", "unknown"),
            door_width_m=data.get("door_width_m"),
            threshold_height_cm=data.get("threshold_height_cm"),
            lift_access=data.get("lift_access", "unknown"),
            opening_hours=data.get("opening_hours"),
            source=src,
            source_timestamp=data.get("source_timestamp"),
            osm_element_id=data.get("osm_element_id"),
            community_observation_ids=data.get("community_observation_ids", []),
            notes=data.get("notes"),
            is_temporary=data.get("is_temporary", False),
            expires_at=data.get("expires_at"),
        )


@dataclass
class Entrance:
    """An individual entrance associated with a destination venue."""
    id: str
    venue_id: str
    name: str
    latitude: float
    longitude: float
    entrance_type: EntranceType = EntranceType.MAIN
    evidence: EntranceAccessibilityEvidence = field(default_factory=EntranceAccessibilityEvidence)
    evidence_completeness: Dict[str, str] = field(default_factory=dict)
    provenance_sources: List[EvidenceProvenance] = field(default_factory=list)
    community_reports_count: int = 0
    active_conflicts: List[str] = field(default_factory=list)
    is_active: bool = True
    approach_snap_distance_m: Optional[float] = None
    approach_node_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "venue_id": self.venue_id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "entrance_type": self.entrance_type.value if isinstance(self.entrance_type, EntranceType) else str(self.entrance_type),
            "evidence": self.evidence.to_dict(),
            "evidence_completeness": self.evidence_completeness,
            "provenance_sources": [
                s.value if isinstance(s, EvidenceProvenance) else str(s)
                for s in self.provenance_sources
            ],
            "community_reports_count": self.community_reports_count,
            "active_conflicts": self.active_conflicts,
            "is_active": self.is_active,
            "approach_snap_distance_m": self.approach_snap_distance_m,
            "approach_node_id": self.approach_node_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entrance":
        etype = data.get("entrance_type", EntranceType.MAIN)
        if isinstance(etype, str):
            try:
                etype = EntranceType(etype)
            except ValueError:
                etype = EntranceType.MAIN

        sources = []
        for s in data.get("provenance_sources", []):
            if isinstance(s, str):
                try:
                    sources.append(EvidenceProvenance(s))
                except ValueError:
                    sources.append(EvidenceProvenance.UNKNOWN)
            elif isinstance(s, EvidenceProvenance):
                sources.append(s)

        evidence_dict = data.get("evidence", {})
        evidence_obj = EntranceAccessibilityEvidence.from_dict(evidence_dict) if isinstance(evidence_dict, dict) else EntranceAccessibilityEvidence()

        return cls(
            id=str(data["id"]),
            venue_id=str(data["venue_id"]),
            name=str(data.get("name", "Entrance")),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            entrance_type=etype,
            evidence=evidence_obj,
            evidence_completeness=data.get("evidence_completeness", {}),
            provenance_sources=sources,
            community_reports_count=int(data.get("community_reports_count", 0)),
            active_conflicts=data.get("active_conflicts", []),
            is_active=bool(data.get("is_active", True)),
            approach_snap_distance_m=data.get("approach_snap_distance_m"),
            approach_node_id=data.get("approach_node_id"),
        )


@dataclass
class Venue:
    """A destination venue (e.g. building, shopping centre, station) with multiple entrances."""
    id: str
    name: str
    venue_type: VenueType
    latitude: float
    longitude: float
    entrances: List[Entrance] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None  # (south, west, north, east)
    osm_type: Optional[str] = None
    osm_id: Optional[int] = None
    address: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "venue_type": self.venue_type.value if isinstance(self.venue_type, VenueType) else str(self.venue_type),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "entrances": [e.to_dict() for e in self.entrances],
            "bbox": self.bbox,
            "osm_type": self.osm_type,
            "osm_id": self.osm_id,
            "address": self.address,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Venue":
        vtype = data.get("venue_type", VenueType.BUILDING)
        if isinstance(vtype, str):
            try:
                vtype = VenueType(vtype)
            except ValueError:
                vtype = VenueType.BUILDING

        entrances = [
            Entrance.from_dict(e) for e in data.get("entrances", [])
        ]

        bbox_data = data.get("bbox")
        bbox_tuple = tuple(bbox_data) if bbox_data and len(bbox_data) == 4 else None

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            venue_type=vtype,
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            entrances=entrances,
            bbox=bbox_tuple,
            osm_type=data.get("osm_type"),
            osm_id=data.get("osm_id"),
            address=data.get("address"),
        )


@dataclass
class Destination:
    """Normalized internal Destination entity resulting from search or coordinate selection."""
    id: str
    name: str
    latitude: float
    longitude: float
    is_venue: bool = False
    venue: Optional[Venue] = None
    display_name: str = ""
    place_type: Optional[str] = None
    raw_properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_venue": self.is_venue,
            "venue": self.venue.to_dict() if self.venue else None,
            "display_name": self.display_name,
            "place_type": self.place_type,
            "raw_properties": self.raw_properties,
        }


@dataclass
class EntranceAssessment:
    """Evaluation result for an individual entrance against user mobility preferences."""
    entrance_id: str
    entrance_name: str
    entrance_type: EntranceType
    status: EntranceAssessmentStatus
    matching_reasons: List[str] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    warning_reasons: List[str] = field(default_factory=list)
    missing_attributes: List[str] = field(default_factory=list)
    route_summary: Optional[Dict[str, Any]] = None
    combined_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entrance_id": self.entrance_id,
            "entrance_name": self.entrance_name,
            "entrance_type": self.entrance_type.value if isinstance(self.entrance_type, EntranceType) else str(self.entrance_type),
            "status": self.status.value if isinstance(self.status, EntranceAssessmentStatus) else str(self.status),
            "matching_reasons": self.matching_reasons,
            "blocking_reasons": self.blocking_reasons,
            "warning_reasons": self.warning_reasons,
            "missing_attributes": self.missing_attributes,
            "route_summary": self.route_summary,
            "combined_summary": self.combined_summary,
        }


@dataclass
class DestinationAssessment:
    """High-level assessment of a destination venue across all available entrances."""
    destination_id: str
    destination_name: str
    is_venue: bool
    entrances_count: int
    recommended_entrance_id: Optional[str]
    entrance_assessments: List[EntranceAssessment] = field(default_factory=list)
    has_matching_entrance: bool = False
    summary_headline: str = ""
    summary_explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination_id": self.destination_id,
            "destination_name": self.destination_name,
            "is_venue": self.is_venue,
            "entrances_count": self.entrances_count,
            "recommended_entrance_id": self.recommended_entrance_id,
            "entrance_assessments": [ea.to_dict() for ea in self.entrance_assessments],
            "has_matching_entrance": self.has_matching_entrance,
            "summary_headline": self.summary_headline,
            "summary_explanation": self.summary_explanation,
        }
