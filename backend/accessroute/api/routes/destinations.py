"""Destination, Venue, and Entrance API routes.

Stage 13 Architecture:
Exposes endpoints for destination resolution, entrance discovery, evidence-based
entrance accessibility assessment, direct route-to-entrance calculation,
community entrance reporting, and preferred entrance persistence.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from accessroute.api.dependencies import (
    get_community_service,
    get_geocoder,
    get_graph_manager,
    get_regional_cache,
)
from accessroute.api.routes.community import _check_rate_limit, _resolve_contributor_id
from accessroute.api.schemas.destinations import (
    AssessDestinationRequest,
    DestinationAssessmentResponse,
    DestinationResponse,
    EntranceReportRequest,
    EntranceResponse,
    EntranceSchema,
    PreferredEntranceUpdate,
    RouteToEntranceRequest,
    RouteToEntranceResponse,
    VenueSchema,
)
from accessroute.api.schemas.routing import (
    CoordinatePair,
    DirectionStepSchema,
    ElevationPointSchema,
    ElevationSummarySchema,
    ExpansionMetadataSchema,
    RouteAlternativeSchema,
    RouteAlternativesResponse,
    RouteMetricsSchema,
)
from accessroute.auth.dependencies import get_current_user, get_optional_user
from accessroute.community.models import ObservationCategory
from accessroute.community.service import CommunityObservationService
from accessroute.database.models import SavedPlace, User
from accessroute.database.session import get_db
from accessroute.destinations.assessment import EntranceAssessmentEngine
from accessroute.destinations.entrances import OSMEntranceDiscovery
from accessroute.destinations.models import Destination, Entrance, EntranceType, Venue
from accessroute.destinations.resolver import DestinationResolver
from accessroute.destinations.service import DestinationService
from accessroute.geocoding.base import GeocoderProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.preferences.models import MobilityPreferences
from accessroute.routing.directions import generate_turn_by_turn_directions
from accessroute.routing.elevation_profile import generate_elevation_profile
from accessroute.routing.geojson import route_alternatives_to_geojson

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/destinations", tags=["Destinations & Entrances"])
entrance_router = APIRouter(prefix="/entrances", tags=["Destinations & Entrances"])
routes_to_entrance_router = APIRouter(prefix="/routes", tags=["Destinations & Entrances"])

# In-memory session registry for resolved destinations and discovered entrances
_destination_cache: Dict[str, Destination] = {}
_entrance_cache: Dict[str, Entrance] = {}


def _get_destination_service(
    community_service: CommunityObservationService = Depends(get_community_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> DestinationService:
    return DestinationService(
        community_service=community_service,
        graph_manager=graph_manager,
    )


@router.get(
    "/resolve",
    response_model=DestinationResponse,
    summary="Resolve Destination Venue and Entrances",
    description="Resolves a search query or coordinate pair to identify whether the destination is a venue with multiple entrances.",
)
def resolve_destination(
    query: Optional[str] = Query(None, description="Free-text search query or place name"),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Latitude"),
    lon: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Longitude"),
    label: Optional[str] = Query(None, description="Optional label for coordinates"),
    geocoder: GeocoderProvider = Depends(get_geocoder),
    service: DestinationService = Depends(_get_destination_service),
) -> DestinationResponse:
    dest: Optional[Destination] = None

    if query:
        # Search via geocoder
        candidates = geocoder.search(query, limit=1)
        if not candidates:
            # Fallback to coordinate resolver using query as label
            if lat is not None and lon is not None:
                dest = service.resolve_coordinates(lat, lon, label=query)
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No matching place or venue found for query '{query}'.",
                )
        else:
            dest = service.resolve_destination_candidate(candidates[0])
    elif lat is not None and lon is not None:
        dest = service.resolve_coordinates(lat, lon, label=label)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'query' or ('lat' and 'lon') must be provided.",
        )

    # Cache for subsequent assessment and routing
    _destination_cache[dest.id] = dest
    if dest.is_venue and dest.venue:
        for ent in dest.venue.entrances:
            _entrance_cache[ent.id] = ent

    return DestinationResponse(
        id=dest.id,
        name=dest.name,
        latitude=dest.latitude,
        longitude=dest.longitude,
        is_venue=dest.is_venue,
        venue=VenueSchema(**dest.venue.to_dict()) if dest.venue else None,
        display_name=dest.display_name,
        place_type=dest.place_type,
    )


@router.get(
    "/{destination_id}/entrances",
    response_model=List[EntranceSchema],
    summary="Get Known Entrances for Destination Venue",
)
def get_destination_entrances(
    destination_id: str,
    service: DestinationService = Depends(_get_destination_service),
) -> List[EntranceSchema]:
    dest = _destination_cache.get(destination_id)
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination '{destination_id}' not found. Please resolve the destination first.",
        )

    if not dest.is_venue or not dest.venue:
        return []

    entrances = service.get_venue_entrances(dest.venue)
    for ent in entrances:
        _entrance_cache[ent.id] = ent

    return [EntranceSchema(**e.to_dict()) for e in entrances]


@router.post(
    "/{destination_id}/assess",
    response_model=DestinationAssessmentResponse,
    summary="Assess Destination Entrances Against Mobility Preferences",
)
def assess_destination_entrances(
    destination_id: str,
    req: AssessDestinationRequest,
    service: DestinationService = Depends(_get_destination_service),
) -> DestinationAssessmentResponse:
    dest = _destination_cache.get(destination_id)
    if not dest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Destination '{destination_id}' not found.",
        )

    prefs = MobilityPreferences()
    if req.mobility_preferences:
        try:
            prefs = MobilityPreferences(**req.mobility_preferences)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid mobility preferences: {exc}",
            )

    origin_coord = (req.origin.latitude, req.origin.longitude) if req.origin else None
    assessment = service.assess_destination(dest, prefs, origin=origin_coord)

    return DestinationAssessmentResponse(**assessment.to_dict())


@entrance_router.get(
    "/{entrance_id}",
    response_model=EntranceSchema,
    summary="Get Specific Entrance Details and Evidence Provenance",
)
def get_entrance_details(entrance_id: str) -> EntranceSchema:
    ent = _entrance_cache.get(entrance_id)
    if not ent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entrance '{entrance_id}' not found.",
        )
    return EntranceSchema(**ent.to_dict())


@router.post(
    "/to-entrance",
    response_model=RouteToEntranceResponse,
    summary="Calculate Accessibility-Aware Route Directly to Entrance",
)
@router.post(
    "/{destination_id}/routes/to-entrance",
    response_model=RouteToEntranceResponse,
    summary="Calculate Accessibility-Aware Route Directly to Entrance (by destination)",
)
@routes_to_entrance_router.post(
    "/to-entrance",
    response_model=RouteToEntranceResponse,
    summary="Calculate Accessibility-Aware Route Directly to Entrance (Standard Routes Endpoint)",
)
def plan_route_to_entrance(
    req: RouteToEntranceRequest,
    destination_id: Optional[str] = None,
    service: DestinationService = Depends(_get_destination_service),
    manager: DynamicGraphManager = Depends(get_graph_manager),
    cache: RegionalGraphCache = Depends(get_regional_cache),
) -> RouteToEntranceResponse:
    ent = _entrance_cache.get(req.entrance_id)
    if not ent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entrance '{req.entrance_id}' not found.",
        )

    prefs = MobilityPreferences()
    if req.mobility_preferences:
        try:
            prefs = MobilityPreferences(**req.mobility_preferences)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid mobility preferences: {exc}",
            )

    origin = (req.origin.latitude, req.origin.longitude)
    result = service.route_to_entrance(origin, ent, prefs, manager=manager)

    graph = None
    try:
        graph, _ = cache.load_graph(result.region_id)
    except Exception as exc:
        logger.debug("Could not load cached graph for entrance GeoJSON: %s", exc)

    geojson_data = route_alternatives_to_geojson(
        result=result,
        graph=graph,
        include_segments=True,
        active_index=0,
    )

    alt_schemas = []
    for alt in result.alternatives:
        dir_schemas = [
            DirectionStepSchema(
                step_index=s.step_index,
                instruction=s.instruction,
                maneuver=s.maneuver,
                street_name=s.street_name,
                distance_m=s.distance_m,
                cumulative_distance_m=s.cumulative_distance_m,
                latitude=s.latitude,
                longitude=s.longitude,
                accessibility_cues=s.accessibility_cues,
                barrier_warnings=s.barrier_warnings,
            )
            for s in alt.directions
        ]

        elev_pts = [
            ElevationPointSchema(
                distance_m=pt.distance_m,
                elevation_m=pt.elevation_m,
                latitude=pt.latitude,
                longitude=pt.longitude,
                grade_pct=pt.grade_pct,
            )
            for pt in alt.elevation_summary.points
        ]
        elev_schema = ElevationSummarySchema(
            points=elev_pts,
            elevation_gain_m=alt.elevation_summary.elevation_gain_m,
            elevation_loss_m=alt.elevation_summary.elevation_loss_m,
            max_uphill_grade_pct=alt.elevation_summary.max_uphill_grade_pct,
            max_downhill_grade_pct=alt.elevation_summary.max_downhill_grade_pct,
            min_elevation_m=alt.elevation_summary.min_elevation_m,
            max_elevation_m=alt.elevation_summary.max_elevation_m,
            elevation_source=alt.elevation_summary.elevation_source,
        )

        alt_schemas.append(
            RouteAlternativeSchema(
                key=alt.key,
                title=alt.title,
                badge=alt.badge,
                description=alt.description,
                policy_name=alt.policy_name,
                physical_distance_m=alt.physical_distance_m,
                estimated_duration_min=alt.estimated_duration_min,
                distance_delta_m=alt.distance_delta_m,
                distance_delta_pct=alt.distance_delta_pct,
                elevation_gain_m=alt.elevation_gain_m,
                elevation_loss_m=alt.elevation_loss_m,
                max_uphill_grade_pct=alt.max_uphill_grade_pct,
                stairs_encountered_count=alt.stairs_encountered_count,
                unpaved_distance_m=alt.unpaved_distance_m,
                paved_percentage=alt.paved_percentage,
                crossings_count=alt.crossings_count,
                crossings_unknown_kerb_count=alt.crossings_unknown_kerb_count,
                missing_data_pct=alt.missing_data_pct,
                explanations=alt.explanations,
                directions=dir_schemas,
                elevation_summary=elev_schema,
                color_hex=alt.color_hex,
                is_shortest=alt.is_shortest,
                evidence_quality=alt.evidence_quality,
            )
        )

    routes_resp = RouteAlternativesResponse(
        found=result.found,
        requested_origin=req.origin,
        requested_destination=CoordinatePair(latitude=ent.latitude, longitude=ent.longitude),
        snapped_origin=CoordinatePair(
            latitude=result.snapped_origin[0],
            longitude=result.snapped_origin[1],
        ),
        snapped_destination=CoordinatePair(
            latitude=result.snapped_destination[0],
            longitude=result.snapped_destination[1],
        ),
        origin_snap_distance_m=round(result.origin_snap_distance_m, 1),
        destination_snap_distance_m=round(result.destination_snap_distance_m, 1),
        snap_warnings=result.snap_warnings,
        alternatives=alt_schemas,
        region_id=result.region_id,
        cache_hit=result.cache_hit,
        accessibility_enriched=result.accessibility_enriched,
        terrain_enriched=result.terrain_enriched,
        expansion_occurred=result.expansion_occurred,
        expansion_attempts=result.expansion_attempts,
        geojson=geojson_data,
        blocking_reasons=result.blocking_reasons,
    )

    return RouteToEntranceResponse(
        destination_id=ent.venue_id,
        entrance=EntranceSchema(**ent.to_dict()),
        routes=routes_resp,
    )


@router.post(
    "/reports/entrance",
    status_code=status.HTTP_201_CREATED,
    summary="Report Community Entrance Accessibility Observation",
)
def report_entrance_issue(
    req: EntranceReportRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    service: DestinationService = Depends(_get_destination_service),
) -> Dict[str, Any]:
    contributor_id = _resolve_contributor_id(current_user, req.contributor_id)

    # Rate limiting (30 reports/hour)
    _check_rate_limit(contributor_id, limit=30, window_s=3600.0)

    try:
        cat = ObservationCategory(req.category)
    except ValueError:
        cat = ObservationCategory.ENTRANCE_ACCESSIBILITY

    success, obs, msg = service.report_entrance_issue(
        entrance_id=req.entrance_id,
        category=cat,
        value=req.value,
        latitude=req.latitude,
        longitude=req.longitude,
        contributor_id=contributor_id,
        notes=req.notes,
        is_temporary=req.is_temporary,
        expected_duration_hours=req.expected_duration_hours,
    )

    if not success or not obs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )

    # If this entrance is cached in memory, re-enrich it
    if req.entrance_id in _entrance_cache:
        service.collector.enrich_entrance_evidence(_entrance_cache[req.entrance_id])

    return {
        "success": True,
        "message": msg,
        "observation_id": obs.id,
        "entrance_id": req.entrance_id,
    }


@router.put(
    "/saved-places/{place_id}/preferred-entrance",
    summary="Save Preferred Entrance for a Saved Place",
)
def set_preferred_entrance(
    place_id: str,
    req: PreferredEntranceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    place = (
        db.query(SavedPlace)
        .filter(SavedPlace.id == place_id, SavedPlace.user_id == current_user.id)
        .first()
    )
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved place '{place_id}' not found.",
        )

    place.preferred_entrance_id = req.entrance_id
    place.preferred_entrance_name = req.entrance_name
    db.commit()
    db.refresh(place)

    return {
        "place_id": place.id,
        "label": place.label,
        "preferred_entrance_id": place.preferred_entrance_id,
        "preferred_entrance_name": place.preferred_entrance_name,
    }
