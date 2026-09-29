"""Domain models for Stage 14: Installable Mobile PWA, Offline Navigation & Field Surveying.

Defines:
- OfflineRoutePackage: Complete snapshot of a calculated route, maneuvers, terrain,
  accessibility findings, entrance details, and active community evidence.
- OfflineMissionPackage: Actionable verification mission bundle for offline field surveys.
- OfflineSyncQueueItem: Idempotent mutation queued for synchronization.
- OfflineSyncBatchRequest & OfflineSyncBatchResponse: Batch synchronization schemas.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


CURRENT_OFFLINE_SCHEMA_VERSION = "stage14_v1"


class SyncItemStatus(str, Enum):
    """Lifecycle state of a locally queued synchronization item."""
    PENDING = "PENDING"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


@dataclass
class OfflineRoutePackage:
    """A self-contained, versioned snapshot of an accessibility-aware route for offline use.
    
    Contains all physical metrics, maneuvers, terrain elevations, entrance metadata,
    and community evidence available at the time of download.
    """
    route_id: str
    created_at: str
    downloaded_at: str
    origin: Dict[str, Any]
    destination: Dict[str, Any]
    destination_name: str
    selected_entrance: Optional[Dict[str, Any]] = None
    entrance_coordinates: Optional[Any] = None
    mobility_preferences_snapshot: Dict[str, Any] = field(default_factory=dict)
    route_geometry: List[Any] = field(default_factory=list)
    route_segments: List[Dict[str, Any]] = field(default_factory=list)
    maneuvers: List[Dict[str, Any]] = field(default_factory=list)
    distance_m: float = 0.0
    estimated_duration_min: int = 0
    elevation_profile: Optional[Any] = None
    accessibility_findings: List[Any] = field(default_factory=list)
    upcoming_accessibility_events: List[Dict[str, Any]] = field(default_factory=list)
    evidence_quality: Optional[Any] = None
    osm_evidence: List[Any] = field(default_factory=list)
    terrain_evidence: Optional[Any] = None
    community_evidence_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    known_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    data_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    region_bounds: Any = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    package_version: str = "1.0.0"
    schema_version: str = "stage14_v1"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize route package to a clean dictionary."""
        return {
            "route_id": self.route_id,
            "created_at": self.created_at,
            "downloaded_at": self.downloaded_at,
            "origin": self.origin,
            "destination": self.destination,
            "destination_name": self.destination_name,
            "selected_entrance": self.selected_entrance,
            "entrance_coordinates": self.entrance_coordinates,
            "mobility_preferences_snapshot": self.mobility_preferences_snapshot,
            "route_geometry": self.route_geometry,
            "route_segments": self.route_segments,
            "maneuvers": self.maneuvers,
            "distance_m": self.distance_m,
            "estimated_duration_min": self.estimated_duration_min,
            "elevation_profile": self.elevation_profile,
            "accessibility_findings": self.accessibility_findings,
            "upcoming_accessibility_events": self.upcoming_accessibility_events,
            "evidence_quality": self.evidence_quality,
            "osm_evidence": self.osm_evidence,
            "terrain_evidence": self.terrain_evidence,
            "community_evidence_snapshot": self.community_evidence_snapshot,
            "known_conflicts": self.known_conflicts,
            "data_timestamp": self.data_timestamp,
            "region_bounds": self.region_bounds,
            "package_version": self.package_version,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineRoutePackage":
        """Deserialize from dictionary with schema version validation."""
        schema_v = data.get("schema_version", "")
        if not schema_v.startswith("stage14_"):
            raise ValueError(f"Incompatible offline route package schema version: '{schema_v}'. Expected 'stage14_v*'.")
        
        return cls(
            route_id=data["route_id"],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            downloaded_at=data.get("downloaded_at", datetime.now(timezone.utc).isoformat()),
            origin=data["origin"],
            destination=data["destination"],
            destination_name=data.get("destination_name", "Destination"),
            selected_entrance=data.get("selected_entrance"),
            entrance_coordinates=data.get("entrance_coordinates"),
            mobility_preferences_snapshot=data.get("mobility_preferences_snapshot", {}),
            route_geometry=data.get("route_geometry", []),
            route_segments=data.get("route_segments", []),
            maneuvers=data.get("maneuvers", []),
            distance_m=float(data.get("distance_m", 0.0)),
            estimated_duration_min=int(data.get("estimated_duration_min", data.get("estimated_duration", 0))),
            elevation_profile=data.get("elevation_profile"),
            accessibility_findings=data.get("accessibility_findings", []),
            upcoming_accessibility_events=data.get("upcoming_accessibility_events", []),
            evidence_quality=data.get("evidence_quality"),
            osm_evidence=data.get("osm_evidence", []),
            terrain_evidence=data.get("terrain_evidence"),
            community_evidence_snapshot=data.get("community_evidence_snapshot", []),
            known_conflicts=data.get("known_conflicts", []),
            data_timestamp=data.get("data_timestamp", datetime.now(timezone.utc).isoformat()),
            region_bounds=data.get("region_bounds", [0.0, 0.0, 0.0, 0.0]),
            package_version=data.get("package_version", "1.0.0"),
            schema_version=schema_v,
        )


@dataclass
class OfflineMissionPackage:
    """Actionable verification mission bundled for offline surveying in the field."""
    mission_id: str
    coordinates: Dict[str, float]  # {"latitude": float, "longitude": float}
    feature_type: str
    missing_attribute: str
    priority: str
    why_it_matters: str
    suggested_actions: List[str]
    osm_element_id: Optional[int] = None
    existing_evidence: Dict[str, Any] = field(default_factory=dict)
    downloaded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "coordinates": self.coordinates,
            "feature_type": self.feature_type,
            "missing_attribute": self.missing_attribute,
            "priority": self.priority,
            "why_it_matters": self.why_it_matters,
            "suggested_actions": self.suggested_actions,
            "osm_element_id": self.osm_element_id,
            "existing_evidence": self.existing_evidence,
            "downloaded_at": self.downloaded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineMissionPackage":
        return cls(
            mission_id=data["mission_id"],
            coordinates=data["coordinates"],
            feature_type=data["feature_type"],
            missing_attribute=data["missing_attribute"],
            priority=data["priority"],
            why_it_matters=data["why_it_matters"],
            suggested_actions=data.get("suggested_actions", []),
            osm_element_id=data.get("osm_element_id"),
            existing_evidence=data.get("existing_evidence", {}),
            downloaded_at=data.get("downloaded_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class OfflineSyncQueueItem:
    """Individual queued mutation for synchronization."""
    local_id: str
    operation_type: str  # "community_report" | "mission_observation"
    payload: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempt_count: int = 0
    last_attempt_at: Optional[str] = None
    status: SyncItemStatus = SyncItemStatus.PENDING
    server_id: Optional[str] = None
    error: Optional[str] = None

    def mark_attempt(self) -> None:
        self.status = SyncItemStatus.SYNCING
        self.attempt_count += 1
        self.last_attempt_at = datetime.now(timezone.utc).isoformat()

    def mark_failed(self, error: str, retryable: bool = True) -> None:
        self.status = SyncItemStatus.FAILED_RETRYABLE if retryable else SyncItemStatus.FAILED_PERMANENT
        self.error = error

    def mark_synced(self, server_id: Optional[str] = None) -> None:
        self.status = SyncItemStatus.SYNCED
        if server_id:
            self.server_id = server_id
        self.error = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_id": self.local_id,
            "operation_type": self.operation_type,
            "payload": self.payload,
            "created_at": self.created_at,
            "attempt_count": self.attempt_count,
            "last_attempt_at": self.last_attempt_at,
            "status": self.status.value if isinstance(self.status, SyncItemStatus) else self.status,
            "server_id": self.server_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineSyncQueueItem":
        status_val = data.get("status", SyncItemStatus.PENDING.value)
        try:
            status_enum = SyncItemStatus(status_val)
        except ValueError:
            status_enum = SyncItemStatus.PENDING

        return cls(
            local_id=data["local_id"],
            operation_type=data["operation_type"],
            payload=data.get("payload", {}),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            attempt_count=int(data.get("attempt_count", 0)),
            last_attempt_at=data.get("last_attempt_at"),
            status=status_enum,
            server_id=data.get("server_id"),
            error=data.get("error"),
        )
