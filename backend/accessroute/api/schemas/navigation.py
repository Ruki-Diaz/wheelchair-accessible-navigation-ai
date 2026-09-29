"""Pydantic schemas for live GPS navigation and re-routing endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from accessroute.api.schemas.routing import CoordinatePair, RouteAlternativeSchema
from accessroute.preferences.models import MobilityPreferences


class GPSLocationSchema(BaseModel):
    """Raw GPS coordinate reading from browser geolocation API."""

    latitude: float = Field(..., description="Latitude coordinate in WGS84.")
    longitude: float = Field(..., description="Longitude coordinate in WGS84.")
    accuracy_m: float = Field(..., description="Estimated horizontal 1-sigma accuracy in meters.")
    heading: Optional[float] = Field(default=None, description="Compass heading in degrees [0, 360).")
    speed_mps: Optional[float] = Field(default=None, description="Movement speed in meters per second.")
    timestamp: Optional[float] = Field(default=None, description="Client reading timestamp (ms or s).")


class UpcomingEventSchema(BaseModel):
    """Upcoming physical accessibility event along route corridor."""

    type: str = Field(..., description="Event type, e.g. KERB_UNKNOWN, STAIRS, CONSTRUCTION.")
    distance_ahead_m: float = Field(..., description="Meters ahead along route from user position.")
    severity: str = Field(..., description="Alert severity: info, warning, or critical.")
    evidence_source: str = Field(..., description="Data provenance: osm, copernicus_dem, or community.")
    description: str = Field(..., description="Factual plain-language notification.")
    segment_id: Optional[str] = Field(default=None, description="Associated OSM or community ID.")
    verification_status: Optional[str] = Field(default=None, description="Community verification status.")


class NavigationProgressRequest(BaseModel):
    """Payload to evaluate progress along an active route."""

    location: GPSLocationSchema
    route_coordinates: List[CoordinatePair]
    mobility_preferences: Optional[MobilityPreferences] = None
    entrance_id: Optional[str] = None
    entrance_name: Optional[str] = None


class NavigationProgressResponse(BaseModel):
    """Calculated route progress metrics."""

    distance_along_route_m: float
    remaining_distance_m: float
    completion_percentage: float
    nearest_point: CoordinatePair
    cross_track_distance_m: float
    current_segment_index: int
    current_step_index: int
    next_maneuver: str
    next_instruction: str
    distance_to_next_maneuver_m: float
    estimated_remaining_duration_min: int
    deviation_state: str
    accuracy_band: str
    is_arrived: bool
    upcoming_events: List[UpcomingEventSchema] = Field(default_factory=list)
    arrival_message: Optional[str] = None
    entrance_details: Optional[Dict[str, Any]] = None


class NavigationRerouteRequest(BaseModel):
    """Request payload for off-route or obstruction-triggered recalculation."""

    current_position: CoordinatePair
    destination: CoordinatePair
    mobility_preferences: Optional[MobilityPreferences] = None
    original_route_distance_m: Optional[float] = None
    reroute_reason: str = Field(default="deviation", description="Reason: deviation, community_blockage, user_requested.")
    reroute_token: Optional[str] = Field(default=None, description="Client token to discard stale responses.")


class NavigationRerouteResponse(BaseModel):
    """Response payload containing newly calculated accessible route alternative."""

    success: bool
    reroute_reason: str
    distance_delta_m: float = 0.0
    explanation: str = ""
    new_route: Optional[RouteAlternativeSchema] = None
    blocking_reasons: List[str] = Field(default_factory=list)
    reroute_token: Optional[str] = None
