"""REST API endpoints for Stage 14 Offline Navigation and PWA Intelligence.

Endpoints:
- POST /api/v1/offline/route-package: Bundle an active route into a standalone offline package.
- GET  /api/v1/offline/route-package/{route_id}: Retrieve or generate an offline package.
- POST /api/v1/offline/mission-package: Bundle verification missions for offline field surveying.
- POST /api/v1/offline/sync: Idempotent batch synchronization of queued community/field reports.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from accessroute.auth.dependencies import get_optional_user
from accessroute.api.schemas.offline import (
    OfflineMissionPackageRequest,
    OfflineMissionPackageResponse,
    OfflineMissionSchema,
    OfflineRoutePackageRequest,
    OfflineRoutePackageResponse,
    OfflineSyncBatchRequest,
    OfflineSyncBatchResponse,
)
from accessroute.offline.models import OfflineSyncQueueItem
from accessroute.offline.service import OfflineService

router = APIRouter(prefix="/offline", tags=["Offline & PWA Intelligence"])

# In-memory service instance
_offline_service: Optional[OfflineService] = None


def get_offline_service() -> OfflineService:
    global _offline_service
    if _offline_service is None:
        _offline_service = OfflineService()
    return _offline_service


@router.post(
    "/route-package",
    response_model=OfflineRoutePackageResponse,
    summary="Generate Offline Route Package",
    description="Serializes an active accessibility-aware route into a standalone offline package.",
)
async def generate_offline_route_package(
    request: OfflineRoutePackageRequest,
    service: OfflineService = Depends(get_offline_service),
) -> OfflineRoutePackageResponse:
    try:
        origin_dict = {"latitude": request.origin.latitude, "longitude": request.origin.longitude}
        dest_dict = {"latitude": request.destination.latitude, "longitude": request.destination.longitude}

        pkg = service.generate_route_package(
            route_data=request.route_data,
            origin=origin_dict,
            destination=dest_dict,
            destination_name=request.destination_name,
            selected_entrance=request.selected_entrance,
            preferences=request.preferences,
            route_id=request.route_id,
        )
        return OfflineRoutePackageResponse(**pkg.to_dict())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate offline route package: {str(e)}",
        )


@router.get(
    "/route-package/{route_id}",
    response_model=OfflineRoutePackageResponse,
    summary="Get Offline Route Package by ID",
    description="Retrieves a default or synthesized offline package for a route ID.",
)
async def get_offline_route_package(
    route_id: str,
    service: OfflineService = Depends(get_offline_service),
) -> OfflineRoutePackageResponse:
    # Synthesize fallback package if requested directly
    sample_route = {
        "route_id": route_id,
        "physical_distance_m": 450.0,
        "estimated_duration_min": 7,
        "directions": [
            {
                "step_index": 1,
                "instruction": "Depart towards accessible pathway",
                "maneuver": "depart",
                "street_name": "Walkway",
                "distance_m": 120.0,
                "cumulative_distance_m": 120.0,
                "latitude": -37.8180,
                "longitude": 144.9670,
                "accessibility_cues": ["Paved concrete surface", "Step-free pathway"],
                "barrier_warnings": [],
            },
            {
                "step_index": 2,
                "instruction": "Arrive at accessible entrance",
                "maneuver": "arrive",
                "street_name": "Entrance Approach",
                "distance_m": 330.0,
                "cumulative_distance_m": 450.0,
                "latitude": -37.8185,
                "longitude": 144.9675,
                "accessibility_cues": ["Step-free automatic doors"],
                "barrier_warnings": [],
            },
        ],
        "route_geometry": [[-37.8180, 144.9670], [-37.8185, 144.9675]],
    }
    pkg = service.generate_route_package(
        route_data=sample_route,
        origin={"latitude": -37.8180, "longitude": 144.9670},
        destination={"latitude": -37.8185, "longitude": 144.9675},
        destination_name="Destination",
    )
    return OfflineRoutePackageResponse(**pkg.to_dict())


@router.post(
    "/mission-package",
    response_model=OfflineMissionPackageResponse,
    summary="Download Offline Verification Missions",
    description="Bundles verification missions for offline field surveying.",
)
async def download_mission_packages(
    request: OfflineMissionPackageRequest,
    service: OfflineService = Depends(get_offline_service),
) -> OfflineMissionPackageResponse:
    try:
        packages = service.generate_mission_packages(
            center_lat=request.center_latitude,
            center_lon=request.center_longitude,
            radius_m=request.radius_m,
            limit=request.limit,
        )
        schemas = [OfflineMissionSchema(**p.to_dict()) for p in packages]
        return OfflineMissionPackageResponse(missions=schemas, total_count=len(schemas))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate mission package: {str(e)}",
        )


@router.post(
    "/sync",
    response_model=OfflineSyncBatchResponse,
    summary="Synchronize Queued Offline Mutations",
    description="Processes locally queued community reports and mission observations idempotently.",
)
async def sync_offline_batch(
    request: OfflineSyncBatchRequest,
    service: OfflineService = Depends(get_offline_service),
    current_user: Optional[Any] = Depends(get_optional_user),
) -> OfflineSyncBatchResponse:
    try:
        items = []
        for it in request.items:
            # If contributor_id is not set and user is authenticated, derive server contributor id
            if current_user and not it.payload.get("contributor_id"):
                it.payload["contributor_id"] = f"usr_{current_user.id}"

            items.append(OfflineSyncQueueItem.from_dict(it.model_dump()))

        synced_count, failed_count, results = service.sync_batch(items)
        return OfflineSyncBatchResponse(
            synced_count=synced_count,
            failed_count=failed_count,
            items=results,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch synchronization failed: {str(e)}",
        )
