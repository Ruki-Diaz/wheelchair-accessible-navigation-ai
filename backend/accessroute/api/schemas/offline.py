"""Pydantic schemas for Stage 14 Offline Navigation and PWA API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from accessroute.api.schemas.routing import CoordinatePair


class OfflineRoutePackageRequest(BaseModel):
    """Request payload to bundle an active route into an offline package."""
    route_id: Optional[str] = Field(None, description="Optional route identifier.")
    origin: CoordinatePair = Field(..., description="Origin coordinates.")
    destination: CoordinatePair = Field(..., description="Destination coordinates.")
    destination_name: str = Field(default="Destination", description="Human-readable destination name.")
    selected_entrance: Optional[Dict[str, Any]] = Field(None, description="Selected entrance details if available.")
    route_data: Dict[str, Any] = Field(..., description="Calculated route data including geometry, maneuvers, and metrics.")
    preferences: Optional[Dict[str, Any]] = Field(None, description="User mobility preferences snapshot.")


class OfflineRoutePackageResponse(BaseModel):
    """Complete serialized offline route package."""
    route_id: str
    created_at: str
    downloaded_at: str
    origin: Dict[str, float]
    destination: Dict[str, float]
    destination_name: str
    selected_entrance: Optional[Dict[str, Any]] = None
    entrance_coordinates: Optional[Dict[str, float]] = None
    mobility_preferences_snapshot: Dict[str, Any] = Field(default_factory=dict)
    route_geometry: List[List[float]] = Field(default_factory=list)
    route_segments: List[Dict[str, Any]] = Field(default_factory=list)
    maneuvers: List[Dict[str, Any]] = Field(default_factory=list)
    distance_m: float
    estimated_duration_min: int
    elevation_profile: Optional[Dict[str, Any]] = None
    accessibility_findings: List[str] = Field(default_factory=list)
    upcoming_accessibility_events: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_quality: Optional[Dict[str, Any]] = None
    osm_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    terrain_evidence: Optional[Dict[str, Any]] = None
    community_evidence_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    known_conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    data_timestamp: str
    region_bounds: List[float] = Field(default_factory=list)
    package_version: str = "1.0.0"
    schema_version: str = "stage14_v1"


class OfflineMissionPackageRequest(BaseModel):
    """Request payload to download verification missions for offline field surveying."""
    center_latitude: float = Field(..., ge=-90.0, le=90.0, description="Center latitude.")
    center_longitude: float = Field(..., ge=-180.0, le=180.0, description="Center longitude.")
    radius_m: float = Field(default=1000.0, ge=50.0, le=10000.0, description="Search radius in meters.")
    limit: int = Field(default=15, ge=1, le=50, description="Maximum number of missions.")


class OfflineMissionSchema(BaseModel):
    """Individual verification mission in an offline package."""
    mission_id: str
    coordinates: Dict[str, float]
    feature_type: str
    missing_attribute: str
    priority: str
    why_it_matters: str
    suggested_actions: List[str]
    osm_element_id: Optional[int] = None
    existing_evidence: Dict[str, Any] = Field(default_factory=dict)
    downloaded_at: str


class OfflineMissionPackageResponse(BaseModel):
    """Response containing bundled offline verification missions."""
    missions: List[OfflineMissionSchema]
    total_count: int


class OfflineSyncQueueItemSchema(BaseModel):
    """Individual queued mutation sent for batch synchronization."""
    local_id: str = Field(..., description="Client-generated unique ID (UUID) for idempotency.")
    operation_type: str = Field(..., description="'community_report' or 'mission_observation'.")
    payload: Dict[str, Any] = Field(..., description="Payload attributes of the report.")
    created_at: Optional[str] = Field(None, description="Local creation timestamp.")
    attempt_count: int = Field(default=0, description="Number of prior attempts.")
    last_attempt_at: Optional[str] = Field(None, description="Last attempt timestamp.")
    status: str = Field(default="PENDING", description="Sync status.")
    server_id: Optional[str] = Field(None, description="Server ID if already processed.")
    error: Optional[str] = Field(None, description="Error explanation if failed.")


class OfflineSyncBatchRequest(BaseModel):
    """Request payload for idempotent batch synchronization of queued field observations."""
    items: List[OfflineSyncQueueItemSchema] = Field(..., description="List of queued mutations to sync.")


class OfflineSyncBatchResponse(BaseModel):
    """Response returned after processing a batch of synchronization items."""
    synced_count: int
    failed_count: int
    items: List[Dict[str, Any]]
