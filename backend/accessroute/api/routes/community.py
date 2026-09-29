"""FastAPI router for Stage 9 Community Accessibility Data, Verification & Evidence.

Provides RESTful endpoints for:
1. Submitting community accessibility reports (POST /reports)
2. Listing and filtering observations (GET /reports)
3. Viewing individual report details (GET /reports/{id})
4. Confirming observations (POST /reports/{id}/confirm)
5. Disputing observations (POST /reports/{id}/dispute)
6. Spatial radius lookup (GET /nearby)
7. Deterministic verification opportunities / data gaps (GET /verification-opportunities)
8. GeoJSON FeatureCollection visualization (GET /geojson)
"""

from collections import defaultdict
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from accessroute.api.schemas.community import (
    CommunityReportCreate,
    CommunityReportResponse,
    CommunityReportsListResponse,
    InteractionRequest,
    InteractionResponse,
    VerificationOpportunitiesResponse,
    VerificationOpportunityItem,
)
from accessroute.auth.dependencies import get_optional_user
from accessroute.community.models import (
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.service import CommunityObservationService
from accessroute.database.models import User
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.region import BoundingBox

router = APIRouter(prefix="/community", tags=["Community Accessibility"])

# Shared service instance
_community_service = CommunityObservationService()
_graph_manager = DynamicGraphManager()

_submission_timestamps: Dict[str, List[float]] = defaultdict(list)


def _check_rate_limit(key: str, limit: int = 30, window_s: float = 3600.0) -> None:
    now = time.time()
    valid_ts = [t for t in _submission_timestamps[key] if now - t < window_s]
    if len(valid_ts) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for community submissions. Please try again later.",
        )
    valid_ts.append(now)
    _submission_timestamps[key] = valid_ts


def _resolve_contributor_id(user: Optional[User], raw_contributor_id: Optional[str]) -> str:
    """Derive contributor ID to prevent spoofing.

    If authenticated, returns 'usr_<user.id>'.
    If anonymous, ensures the ID cannot spoof the 'usr_' prefix.
    """
    if user:
        return f"usr_{user.id}"
    raw = (raw_contributor_id or "").strip()
    if raw.startswith("usr_"):
        return f"anon_{raw.replace('usr_', '')}"
    return raw if raw else "anon_contributor"


def _to_response_schema(obs: CommunityObservation) -> CommunityReportResponse:
    return CommunityReportResponse(
        id=obs.id,
        source=obs.source.value if hasattr(obs.source, "value") else str(obs.source),
        category=obs.category.value if hasattr(obs.category, "value") else str(obs.category),
        value=obs.value,
        latitude=obs.latitude,
        longitude=obs.longitude,
        osm_element_type=obs.osm_element_type,
        osm_element_id=obs.osm_element_id,
        matched_distance_m=obs.matched_distance_m,
        match_confidence=obs.match_confidence,
        is_temporary=obs.is_temporary,
        reported_at=obs.reported_at.isoformat() if hasattr(obs.reported_at, "isoformat") else str(obs.reported_at),
        expected_end_at=obs.expected_end_at.isoformat() if obs.expected_end_at and hasattr(obs.expected_end_at, "isoformat") else (str(obs.expected_end_at) if obs.expected_end_at else None),
        expires_at=obs.expires_at.isoformat() if obs.expires_at and hasattr(obs.expires_at, "isoformat") else (str(obs.expires_at) if obs.expires_at else None),
        verification_status=obs.verification_status.value if hasattr(obs.verification_status, "value") else str(obs.verification_status),
        confirmations_count=obs.confirmations_count,
        disputes_count=obs.disputes_count,
        notes=obs.notes,
        photo_url=obs.photo_url,
        is_active=obs.is_active(),
    )


@router.post(
    "/reports",
    response_model=CommunityReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a community accessibility observation",
    description="Records a structured observation about physical infrastructure (kerb, stairs, surface, barrier, obstacle).",
)
def submit_report(
    payload: CommunityReportCreate,
    current_user: Optional[User] = Depends(get_optional_user),
) -> CommunityReportResponse:
    effective_contributor_id = _resolve_contributor_id(current_user, payload.contributor_id)
    _check_rate_limit(effective_contributor_id, limit=30, window_s=3600.0)

    # Validate category enum
    try:
        cat_enum = ObservationCategory(payload.category.lower().strip())
    except ValueError:
        valid_cats = [c.value for c in ObservationCategory]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category '{payload.category}'. Valid categories: {valid_cats}",
        )

    # Attempt spatial snapping against local/cached graph if available
    graph = None
    try:
        bbox = BoundingBox.from_coordinates(
            origin=(payload.latitude, payload.longitude),
            destination=(payload.latitude, payload.longitude),
            buffer_meters=200.0,
        )
        G, _, _ = _graph_manager.get_graph_for_bbox(bbox=bbox, enrich_elevation=False)
        graph = G
    except Exception:
        # Snapping failure is non-fatal: report is preserved with unmatched status
        graph = None

    obs = _community_service.submit_report(
        category=cat_enum,
        value=payload.value,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_temporary=payload.is_temporary,
        expected_duration_hours=payload.expected_duration_hours,
        expires_at=payload.expires_at,
        contributor_id=effective_contributor_id,
        notes=payload.notes,
        photo_url=payload.photo_url,
        graph=graph,
    )
    return _to_response_schema(obs)


@router.get(
    "/reports",
    response_model=CommunityReportsListResponse,
    summary="List community accessibility reports",
    description="Retrieve recent community reports with optional filtering by category or status.",
)
def list_reports(
    category: Optional[str] = Query(None, description="Filter by category (e.g. kerb, stairs, surface)."),
    verification_status: Optional[str] = Query(None, description="Filter by status (e.g. UNVERIFIED, COMMUNITY_SUPPORTED)."),
    include_expired: bool = Query(False, description="Whether to include expired temporary reports."),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of reports to return."),
) -> CommunityReportsListResponse:
    all_obs = _community_service.repository.get_all(include_expired=include_expired, limit=limit)

    filtered = all_obs
    if category:
        cat_str = category.lower().strip()
        filtered = [o for o in filtered if (o.category.value if hasattr(o.category, "value") else str(o.category)).lower() == cat_str]
    if verification_status:
        stat_str = verification_status.upper().strip()
        filtered = [o for o in filtered if (o.verification_status.value if hasattr(o.verification_status, "value") else str(o.verification_status)).upper() == stat_str]

    return CommunityReportsListResponse(
        count=len(filtered),
        reports=[_to_response_schema(o) for o in filtered],
    )


@router.get(
    "/reports/{report_id}",
    response_model=CommunityReportResponse,
    summary="Get a community observation by ID",
)
def get_report(report_id: str) -> CommunityReportResponse:
    obs = _community_service.repository.get_by_id(report_id)
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Community observation '{report_id}' not found.",
        )
    return _to_response_schema(obs)


@router.post(
    "/reports/{report_id}/confirm",
    response_model=InteractionResponse,
    summary="Confirm an existing accessibility observation",
    description="Independent peer confirmation. Prevents multiple votes by the same contributor.",
)
def confirm_report(
    report_id: str,
    payload: InteractionRequest,
    current_user: Optional[User] = Depends(get_optional_user),
) -> InteractionResponse:
    effective_contributor_id = _resolve_contributor_id(current_user, payload.contributor_id)
    _check_rate_limit(f"vote_{effective_contributor_id}", limit=60, window_s=3600.0)

    success, obs, message = _community_service.confirm_report(
        observation_id=report_id,
        contributor_id=effective_contributor_id,
    )
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Community observation '{report_id}' not found.",
        )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return InteractionResponse(
        success=True,
        observation_id=report_id,
        new_status=obs.verification_status.value if hasattr(obs.verification_status, "value") else str(obs.verification_status),
        confirmations_count=obs.confirmations_count,
        disputes_count=obs.disputes_count,
        message=message,
    )


@router.post(
    "/reports/{report_id}/dispute",
    response_model=InteractionResponse,
    summary="Dispute an existing accessibility observation",
    description="Record that an observation is inaccurate or no longer present.",
)
def dispute_report(
    report_id: str,
    payload: InteractionRequest,
    current_user: Optional[User] = Depends(get_optional_user),
) -> InteractionResponse:
    effective_contributor_id = _resolve_contributor_id(current_user, payload.contributor_id)
    _check_rate_limit(f"vote_{effective_contributor_id}", limit=60, window_s=3600.0)

    success, obs, message = _community_service.dispute_report(
        observation_id=report_id,
        contributor_id=effective_contributor_id,
    )
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Community observation '{report_id}' not found.",
        )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return InteractionResponse(
        success=True,
        observation_id=report_id,
        new_status=obs.verification_status.value if hasattr(obs.verification_status, "value") else str(obs.verification_status),
        confirmations_count=obs.confirmations_count,
        disputes_count=obs.disputes_count,
        message=message,
    )


@router.get(
    "/nearby",
    response_model=CommunityReportsListResponse,
    summary="Find observations near coordinates",
    description="Search active community reports within a specified radius in meters.",
)
def get_nearby(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_m: float = Query(300.0, ge=10.0, le=5000.0),
    include_expired: bool = Query(False),
) -> CommunityReportsListResponse:
    nearby_obs = _community_service.get_nearby_observations(
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        include_expired=include_expired,
    )
    return CommunityReportsListResponse(
        count=len(nearby_obs),
        reports=[_to_response_schema(o) for o in nearby_obs],
    )


@router.get(
    "/verification-opportunities",
    response_model=VerificationOpportunitiesResponse,
    summary="Identify accessibility data gaps / verification opportunities",
    description="Deterministically identifies crossings with unknown kerbs or footways with unknown surfaces.",
)
def get_verification_opportunities(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_m: float = Query(400.0, ge=50.0, le=2000.0),
    max_count: int = Query(25, ge=1, le=100),
) -> VerificationOpportunitiesResponse:
    try:
        bbox = BoundingBox.from_coordinates(
            origin=(latitude, longitude),
            destination=(latitude, longitude),
            buffer_meters=radius_m,
        )
        G, _, _ = _graph_manager.get_graph_for_bbox(bbox=bbox, enrich_elevation=False)
        opps = _community_service.identify_verification_opportunities(G, max_count=max_count)
    except Exception as e:
        opps = []

    return VerificationOpportunitiesResponse(
        count=len(opps),
        opportunities=[
            VerificationOpportunityItem(
                latitude=o.latitude,
                longitude=o.longitude,
                osm_element_type=o.osm_element_type,
                osm_element_id=o.osm_element_id,
                missing_attribute=o.missing_attribute,
                feature_type=o.feature_type,
                importance_reason=o.importance_reason,
            )
            for o in opps
        ],
    )


@router.get(
    "/geojson",
    summary="Get GeoJSON FeatureCollection of community reports",
    description="Returns RFC 7946 GeoJSON FeatureCollection of community observations for map rendering.",
)
def get_community_geojson(
    min_lat: Optional[float] = Query(None, ge=-90.0, le=90.0),
    min_lon: Optional[float] = Query(None, ge=-180.0, le=180.0),
    max_lat: Optional[float] = Query(None, ge=-90.0, le=90.0),
    max_lon: Optional[float] = Query(None, ge=-180.0, le=180.0),
    include_expired: bool = Query(False),
) -> Dict[str, Any]:
    if min_lat is not None and min_lon is not None and max_lat is not None and max_lon is not None:
        obs_list = _community_service.get_bbox_observations(
            min_lat=min_lat,
            min_lon=min_lon,
            max_lat=max_lat,
            max_lon=max_lon,
            include_expired=include_expired,
        )
    else:
        obs_list = _community_service.repository.get_all(include_expired=include_expired, limit=200)

    features: List[Dict[str, Any]] = []
    for obs in obs_list:
        cat_str = obs.category.value if hasattr(obs.category, "value") else str(obs.category)
        stat_str = obs.verification_status.value if hasattr(obs.verification_status, "value") else str(obs.verification_status)
        features.append({
            "type": "Feature",
            "id": f"community_{obs.id}",
            "geometry": {
                "type": "Point",
                "coordinates": [float(obs.longitude), float(obs.latitude)],
            },
            "properties": {
                "id": obs.id,
                "feature_type": "community_observation",
                "category": cat_str,
                "value": obs.value,
                "is_temporary": obs.is_temporary,
                "verification_status": stat_str,
                "confirmations_count": obs.confirmations_count,
                "disputes_count": obs.disputes_count,
                "reported_at": obs.reported_at.isoformat() if hasattr(obs.reported_at, "isoformat") else str(obs.reported_at),
                "expires_at": obs.expires_at.isoformat() if obs.expires_at and hasattr(obs.expires_at, "isoformat") else (str(obs.expires_at) if obs.expires_at else None),
                "notes": obs.notes,
                "is_active": obs.is_active(),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
