"""Live navigation and re-routing API endpoints."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from accessroute.api.dependencies import get_graph_manager, get_navigation_service
from accessroute.api.schemas.navigation import (
    CoordinatePair,
    GPSLocationSchema,
    NavigationProgressRequest,
    NavigationProgressResponse,
    NavigationRerouteRequest,
    NavigationRerouteResponse,
    UpcomingEventSchema,
)
from accessroute.api.schemas.routing import (
    DirectionStepSchema,
    ElevationPointSchema,
    ElevationSummarySchema,
    RouteAlternativeSchema,
)
from accessroute.navigation.models import GPSLocation, RerouteRequest
from accessroute.navigation.service import LiveNavigationService
from accessroute.navigation.simulation import SimulatedLocationProvider
from accessroute.routing.alternatives import RouteAlternative

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/navigation", tags=["Navigation"])


def _convert_alt_to_schema(alt: RouteAlternative) -> RouteAlternativeSchema:
    """Helper to convert domain RouteAlternative into RouteAlternativeSchema."""
    dir_schemas = [
        DirectionStepSchema(
            step_index=step.step_index,
            instruction=step.instruction,
            maneuver=step.maneuver,
            street_name=step.street_name,
            distance_m=step.distance_m,
            cumulative_distance_m=step.cumulative_distance_m,
            latitude=step.latitude,
            longitude=step.longitude,
            accessibility_cues=step.accessibility_cues,
            barrier_warnings=step.barrier_warnings,
        )
        for step in alt.directions
    ]

    elev_pts = [
        ElevationPointSchema(
            distance_from_start_m=p.cumulative_distance_m,
            elevation_m=p.elevation_m,
            slope_grade_pct=p.slope_grade_pct,
            latitude=p.latitude,
            longitude=p.longitude,
        )
        for p in alt.elevation_summary.points
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

    return RouteAlternativeSchema(
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


@router.post(
    "/reroute",
    response_model=NavigationRerouteResponse,
    summary="Accessibility-Aware Re-routing",
    description="Recalculates route from current GPS position to original destination preserving mobility preferences.",
)
async def reroute_navigation(
    req: NavigationRerouteRequest,
    nav_service: LiveNavigationService = Depends(get_navigation_service),
):
    domain_req = RerouteRequest(
        current_position=(req.current_position.latitude, req.current_position.longitude),
        destination=(req.destination.latitude, req.destination.longitude),
        mobility_preferences=req.mobility_preferences,
        original_route_distance_m=req.original_route_distance_m,
        reroute_reason=req.reroute_reason,
        reroute_token=req.reroute_token,
    )

    res = nav_service.reroute(domain_req)

    schema_route = None
    if res.success and res.new_route is not None:
        schema_route = _convert_alt_to_schema(res.new_route)

    return NavigationRerouteResponse(
        success=res.success,
        reroute_reason=res.reroute_reason,
        distance_delta_m=res.distance_delta_m,
        explanation=res.explanation,
        new_route=schema_route,
        blocking_reasons=res.blocking_reasons,
        reroute_token=res.reroute_token,
    )


@router.post(
    "/progress",
    response_model=NavigationProgressResponse,
    summary="Evaluate Route Progress",
    description="Calculates geometric projection, distance completed, next maneuver, and upcoming accessibility events.",
)
async def evaluate_navigation_progress(
    req: NavigationProgressRequest,
    nav_service: LiveNavigationService = Depends(get_navigation_service),
):
    coords = [(p.latitude, p.longitude) for p in req.route_coordinates]
    loc = GPSLocation(
        latitude=req.location.latitude,
        longitude=req.location.longitude,
        accuracy_m=req.location.accuracy_m,
        heading=req.location.heading,
        speed_mps=req.location.speed_mps,
        timestamp=req.location.timestamp or 0.0,
    )

    progress = nav_service.track_progress(
        route_coordinates=coords,
        location=loc,
    )

    events_schema = [
        UpcomingEventSchema(
            type=e.type,
            distance_ahead_m=e.distance_ahead_m,
            severity=e.severity,
            evidence_source=e.evidence_source,
            description=e.description,
            segment_id=e.segment_id,
            verification_status=e.verification_status,
        )
        for e in progress.upcoming_events
    ]

    return NavigationProgressResponse(
        distance_along_route_m=progress.distance_along_route_m,
        remaining_distance_m=progress.remaining_distance_m,
        completion_percentage=progress.completion_percentage,
        nearest_point=CoordinatePair(
            latitude=progress.nearest_point[0],
            longitude=progress.nearest_point[1],
        ),
        cross_track_distance_m=progress.cross_track_distance_m,
        current_segment_index=progress.current_segment_index,
        current_step_index=progress.current_step_index,
        next_maneuver=progress.next_maneuver,
        next_instruction=progress.next_instruction,
        distance_to_next_maneuver_m=progress.distance_to_next_maneuver_m,
        estimated_remaining_duration_min=progress.estimated_remaining_duration_min,
        deviation_state=progress.deviation_state.value,
        accuracy_band=progress.accuracy_band.value,
        is_arrived=progress.is_arrived,
        upcoming_events=events_schema,
        arrival_message=(
            f"You've reached the selected entrance area ({req.entrance_name})."
            if progress.is_arrived and req.entrance_name
            else ("You've reached your destination." if progress.is_arrived else None)
        ),
        entrance_details=(
            {"entrance_id": req.entrance_id, "entrance_name": req.entrance_name}
            if progress.is_arrived and (req.entrance_id or req.entrance_name)
            else None
        ),
    )


@router.get(
    "/simulation-trace",
    summary="Get Simulated GPS Trace",
    description="Generates deterministic simulated GPS points along a sample or provided route for UI testing.",
)
async def get_simulation_trace(
    scenario: str = Query("normal", description="Scenario: normal, jitter, deviation, arrival"),
    start_lat: float = Query(-37.8650),
    start_lon: float = Query(145.1850),
    end_lat: float = Query(-37.8630),
    end_lon: float = Query(145.1870),
):
    # Sample route
    sample_coords = [
        (start_lat, start_lon),
        (start_lat + (end_lat - start_lat) * 0.33, start_lon + (end_lon - start_lon) * 0.25),
        (start_lat + (end_lat - start_lat) * 0.66, start_lon + (end_lon - start_lon) * 0.75),
        (end_lat, end_lon),
    ]

    provider = SimulatedLocationProvider(sample_coords, speed_mps=1.0)

    if scenario == "jitter":
        points = provider.generate_jitter_stream(jitter_radius_m=30.0, num_updates=6)
    elif scenario == "deviation":
        points = provider.generate_deviation_stream(divergence_meters=55.0, consecutive_points=5)
    else:
        points = list(provider.generate_normal_stream())

    return {
        "scenario": scenario,
        "points_count": len(points),
        "locations": [p.to_dict() for p in points],
    }
