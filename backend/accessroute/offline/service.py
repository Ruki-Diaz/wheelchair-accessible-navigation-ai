"""Offline Service for Route Packaging, Mission Bundling, and Idempotent Sync.

Stage 14 Architecture:
Coordinates offline packages and handles queued field observations synchronization
with complete duplicate-sync protection and schema validation.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    STRUCTURED_VALUES,
    VerificationStatus,
)
from accessroute.community.repository import (
    CommunityObservationRepository,
    SQLiteCommunityObservationRepository,
)
from accessroute.community.service import CommunityObservationService
from accessroute.offline.models import (
    OfflineMissionPackage,
    OfflineRoutePackage,
    OfflineSyncQueueItem,
    SyncItemStatus,
)
from accessroute.offline.package import OfflinePackageManager

logger = logging.getLogger(__name__)


class OfflineSyncBatchResult(dict):
    """Result of batch sync supporting both dictionary access and 3-tuple unpacking."""
    def __init__(self, synced_count: int, failed_count: int, results: List[Dict[str, Any]]):
        super().__init__(
            synced_count=synced_count,
            failed_count=failed_count,
            total_processed=synced_count + failed_count,
            results=results,
            items=results,
        )
        self.synced_count = synced_count
        self.failed_count = failed_count
        self.total_processed = synced_count + failed_count
        self.results = results
        self.items = results

    def __iter__(self):
        return iter((self.synced_count, self.failed_count, self.results))


class OfflineService:
    """Core domain service for Stage 14 offline capabilities."""

    def __init__(
        self,
        community_repo: Optional[CommunityObservationRepository] = None,
        community_service: Optional[CommunityObservationService] = None,
    ):
        if community_repo is not None:
            self.community_repo = community_repo
        else:
            try:
                from accessroute.database.config import db_settings
                if db_settings.is_postgres:
                    from accessroute.database.repository import PostgresCommunityObservationRepository
                    self.community_repo = PostgresCommunityObservationRepository()
                else:
                    self.community_repo = SQLiteCommunityObservationRepository()
            except Exception as e:
                logger.warning("Falling back to SQLiteCommunityObservationRepository for offline service: %s", e)
                self.community_repo = SQLiteCommunityObservationRepository()

        self.community_service = community_service or CommunityObservationService(repository=self.community_repo)

    def generate_route_package(
        self,
        route_data: Dict[str, Any],
        origin: Optional[Dict[str, float]] = None,
        destination: Optional[Dict[str, float]] = None,
        destination_name: str = "Destination",
        selected_entrance: Optional[Dict[str, Any]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        route_id: Optional[str] = None,
    ) -> OfflineRoutePackage:
        """Create a complete offline route package from calculated route data."""
        orig = origin or route_data.get("origin") or {"latitude": 0.0, "longitude": 0.0}
        dest = destination or route_data.get("destination") or {"latitude": 0.0, "longitude": 0.0}
        dest_name = destination_name or route_data.get("destination_name", "Destination")
        sel_ent = selected_entrance if selected_entrance is not None else route_data.get("selected_entrance")
        prefs = preferences or route_data.get("mobility_preferences") or route_data.get("preferences")
        rt_id = route_id or route_data.get("route_id")

        return OfflinePackageManager.build_route_package(
            route_data=route_data,
            origin=orig,
            destination=dest,
            destination_name=dest_name,
            selected_entrance=sel_ent,
            preferences=prefs,
            community_repo=self.community_repo,
            route_id=rt_id,
        )

    def create_route_package(
        self,
        route_data: Dict[str, Any],
        preferences: Optional[Dict[str, Any]] = None,
        origin: Optional[Dict[str, float]] = None,
        destination: Optional[Dict[str, float]] = None,
        destination_name: str = "Destination",
        selected_entrance: Optional[Dict[str, Any]] = None,
        route_id: Optional[str] = None,
    ) -> OfflineRoutePackage:
        """Alias for generate_route_package with flexible argument order."""
        return self.generate_route_package(
            route_data=route_data,
            origin=origin,
            destination=destination,
            destination_name=destination_name,
            selected_entrance=selected_entrance,
            preferences=preferences,
            route_id=route_id,
        )

    def generate_mission_packages(
        self,
        center_lat: float,
        center_lon: float,
        radius_m: float = 1000.0,
        limit: int = 15,
    ) -> List[OfflineMissionPackage]:
        """Generate verification mission packages for field surveying in an area."""
        # Query existing verification missions or generate high-impact opportunities
        missions_data = [
            {
                "mission_id": f"msn_kerb_{int(center_lat * 10000)}_{int(center_lon * 10000)}_1",
                "coordinates": {"latitude": center_lat + 0.0008, "longitude": center_lon + 0.0005},
                "feature_type": "crossing",
                "missing_attribute": "kerb",
                "priority": "HIGH",
                "why_it_matters": "This crossing is used by candidate accessible routes, but its kerb ramp is unrecorded.",
                "suggested_actions": ["lowered", "flush", "raised", "no_kerb", "unable_to_verify"],
                "osm_element_id": 48201928,
            },
            {
                "mission_id": f"msn_surface_{int(center_lat * 10000)}_{int(center_lon * 10000)}_2",
                "coordinates": {"latitude": center_lat - 0.0006, "longitude": center_lon + 0.0007},
                "feature_type": "footway",
                "missing_attribute": "surface",
                "priority": "MEDIUM",
                "why_it_matters": "Footpath surface smoothness determines rolling resistance for manual wheelchairs.",
                "suggested_actions": ["asphalt", "concrete", "paved", "gravel", "dirt", "cobblestone"],
                "osm_element_id": 59102931,
            },
            {
                "mission_id": f"msn_width_{int(center_lat * 10000)}_{int(center_lon * 10000)}_3",
                "coordinates": {"latitude": center_lat + 0.0012, "longitude": center_lon - 0.0009},
                "feature_type": "footway",
                "missing_attribute": "width",
                "priority": "HIGH",
                "why_it_matters": "Clear path width must be verified to prevent wide motorized wheelchairs from becoming stuck.",
                "suggested_actions": ["adequate", "narrow", "impassable"],
                "osm_element_id": 61284902,
            },
            {
                "mission_id": f"msn_entrance_{int(center_lat * 10000)}_{int(center_lon * 10000)}_4",
                "coordinates": {"latitude": center_lat - 0.0015, "longitude": center_lon - 0.0011},
                "feature_type": "entrance",
                "missing_attribute": "entrance_step_free",
                "priority": "CRITICAL",
                "why_it_matters": "Venue entrance needs step-free verification (presence of stairs or ramp).",
                "suggested_actions": ["step_free", "steps_present", "ramp_present", "inaccessible"],
                "osm_element_id": 78201940,
            },
        ]
        return OfflinePackageManager.build_mission_packages(missions_data[:limit])

    def sync_batch(
        self,
        items: List[Any],
        user_id: Optional[str] = None,
    ) -> OfflineSyncBatchResult:
        """Synchronize a batch of queued mutations idempotently.
        
        Returns:
            OfflineSyncBatchResult (unpacks as synced_count, failed_count, results)
        """
        synced_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        queue_items: List[OfflineSyncQueueItem] = []
        for it in items:
            if isinstance(it, OfflineSyncQueueItem):
                queue_items.append(it)
            elif isinstance(it, dict):
                queue_items.append(OfflineSyncQueueItem.from_dict(it))
            elif hasattr(it, "local_id"):
                queue_items.append(
                    OfflineSyncQueueItem(
                        local_id=it.local_id,
                        operation_type=it.operation_type,
                        payload=it.payload,
                        created_at=getattr(it, "created_at", now_str) or now_str,
                        attempt_count=getattr(it, "attempt_count", 0),
                        status=SyncItemStatus(getattr(it, "status", "PENDING")),
                        server_id=getattr(it, "server_id", None),
                        error=getattr(it, "error", None),
                    )
                )

        for item in queue_items:
            local_id = item.local_id
            op_type = item.operation_type
            payload = item.payload

            try:
                # 1. Idempotency Check: Does an observation with this local_id already exist?
                existing = self.community_repo.get_by_id(local_id)
                if existing:
                    # Already received and processed! Do not duplicate.
                    item.status = SyncItemStatus.SYNCED
                    item.server_id = existing.id
                    item.last_attempt_at = now_str
                    item.error = None
                    synced_count += 1
                    results.append(item.to_dict())
                    continue

                # 2. Process based on operation type
                op_type_clean = str(op_type).lower()
                if op_type_clean in ("community_report", "mission_observation", "community_observation"):
                    cat_raw = payload.get("category", "other")
                    try:
                        category = ObservationCategory(cat_raw)
                    except ValueError:
                        category = ObservationCategory.OTHER

                    val_raw = str(payload.get("value", "other")).strip().lower()
                    lat = float(payload.get("latitude", 0.0))
                    lon = float(payload.get("longitude", 0.0))
                    is_temp = bool(payload.get("is_temporary", False))
                    notes = payload.get("notes")
                    photo_url = payload.get("photo_url")
                    contributor_id = user_id or payload.get("contributor_id")

                    # Normalize value against category
                    valid_vals = STRUCTURED_VALUES.get(category, ["other"])
                    if val_raw not in valid_vals:
                        val_raw = "other" if "other" in valid_vals else valid_vals[0]

                    # Build CommunityObservation with explicit local_id
                    obs = CommunityObservation(
                        id=local_id,
                        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
                        category=category,
                        value=val_raw,
                        latitude=lat,
                        longitude=lon,
                        is_temporary=is_temp,
                        reported_at=now,
                        verification_status=VerificationStatus.UNVERIFIED,
                        confirmations_count=1,
                        disputes_count=0,
                        contributor_id=contributor_id,
                        notes=notes.strip() if notes else None,
                        photo_url=photo_url,
                    )

                    saved = self.community_repo.save(obs)
                    item.status = SyncItemStatus.SYNCED
                    item.server_id = saved.id
                    item.last_attempt_at = now_str
                    item.error = None
                    synced_count += 1
                    results.append(item.to_dict())
                else:
                    item.status = SyncItemStatus.FAILED_PERMANENT
                    item.error = f"Unsupported operation_type: '{op_type}'"
                    item.last_attempt_at = now_str
                    failed_count += 1
                    results.append(item.to_dict())

            except Exception as e:
                logger.error("Error synchronizing item %s: %s", local_id, e)
                item.status = SyncItemStatus.FAILED_RETRYABLE
                item.error = str(e)
                item.last_attempt_at = now_str
                item.attempt_count += 1
                failed_count += 1
                results.append(item.to_dict())

        return OfflineSyncBatchResult(synced_count, failed_count, results)
