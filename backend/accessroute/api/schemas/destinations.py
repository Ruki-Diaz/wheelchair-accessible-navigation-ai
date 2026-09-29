"""Pydantic V2 schemas for Stage 13 Destination, Venue, and Entrance API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from accessroute.api.schemas.routing import CoordinatePair, RouteAlternativesResponse


class EntranceEvidenceSchema(BaseModel):
    wheelchair: str = "unknown"
    step_free: Optional[bool] = None
    steps_count: Optional[int] = None
    ramp: str = "unknown"
    automatic_door: Optional[bool] = None
    door_type: str = "unknown"
    door_width_m: Optional[float] = None
    threshold_height_cm: Optional[float] = None
    lift_access: str = "unknown"
    opening_hours: Optional[str] = None
    source: str = "unknown"
    source_timestamp: Optional[str] = None
    osm_element_id: Optional[str] = None
    community_observation_ids: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    is_temporary: bool = False
    expires_at: Optional[str] = None


class EntranceSchema(BaseModel):
    id: str
    venue_id: str
    name: str
    latitude: float
    longitude: float
    entrance_type: str
    evidence: EntranceEvidenceSchema
    evidence_completeness: Dict[str, str] = Field(default_factory=dict)
    provenance_sources: List[str] = Field(default_factory=list)
    community_reports_count: int = 0
    active_conflicts: List[str] = Field(default_factory=list)
    is_active: bool = True
    approach_snap_distance_m: Optional[float] = None


EntranceResponse = EntranceSchema


class VenueSchema(BaseModel):
    id: str
    name: str
    venue_type: str
    latitude: float
    longitude: float
    entrances: List[EntranceSchema] = Field(default_factory=list)
    address: Optional[str] = None


class DestinationResponse(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    is_venue: bool
    venue: Optional[VenueSchema] = None
    display_name: str
    place_type: Optional[str] = None


class EntranceAssessmentSchema(BaseModel):
    entrance_id: str
    entrance_name: str
    entrance_type: str
    status: str
    matching_reasons: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    warning_reasons: List[str] = Field(default_factory=list)
    missing_attributes: List[str] = Field(default_factory=list)
    route_summary: Optional[Dict[str, Any]] = None
    combined_summary: str = ""


class DestinationAssessmentResponse(BaseModel):
    destination_id: str
    destination_name: str
    is_venue: bool
    entrances_count: int
    recommended_entrance_id: Optional[str] = None
    entrance_assessments: List[EntranceAssessmentSchema] = Field(default_factory=list)
    has_matching_entrance: bool = False
    summary_headline: str
    summary_explanation: str


class AssessDestinationRequest(BaseModel):
    origin: Optional[CoordinatePair] = None
    mobility_preferences: Optional[Dict[str, Any]] = None


class RouteToEntranceRequest(BaseModel):
    origin: CoordinatePair
    entrance_id: str
    mobility_preferences: Optional[Dict[str, Any]] = None


class RouteToEntranceResponse(BaseModel):
    destination_id: str
    entrance: EntranceSchema
    routes: RouteAlternativesResponse


class EntranceReportRequest(BaseModel):
    entrance_id: str
    value: str
    category: str = "entrance_accessibility"
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    notes: Optional[str] = Field(None, max_length=1000)
    is_temporary: bool = False
    expected_duration_hours: Optional[float] = Field(None, ge=0.5, le=720.0)
    contributor_id: Optional[str] = None


class PreferredEntranceUpdate(BaseModel):
    entrance_id: Optional[str] = None
    entrance_name: Optional[str] = None
