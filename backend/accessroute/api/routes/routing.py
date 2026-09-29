"""Coordinate route planning endpoints."""

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status

from accessroute.api.dependencies import get_graph_manager, get_regional_cache
from accessroute.api.schemas.routing import (
    BaselineComparisonSchema,
    CoordinatePair,
    DirectionStepSchema,
    ElevationPointSchema,
    ElevationSummarySchema,
    ExpansionMetadataSchema,
    RouteAlternativeSchema,
    RouteAlternativesRequest,
    RouteAlternativesResponse,
    RouteMetricsSchema,
    RoutePlanRequest,
    RoutePlanResponse,
)
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.preferences.models import MobilityPreferences
from accessroute.routing.alternatives import calculate_route_alternatives
from accessroute.routing.directions import generate_turn_by_turn_directions
from accessroute.routing.elevation_profile import generate_elevation_profile
from accessroute.routing.geojson import route_alternatives_to_geojson, route_result_to_geojson
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.routing.service import route_between_coordinates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["Routing"])

POLICY_MAP = {
    "balanced": BALANCED_ACCESSIBILITY_POLICY,
    "conservative": CONSERVATIVE_ACCESSIBILITY_POLICY,
    "distance_first": DISTANCE_FIRST_POLICY,
}


@router.post(
    "/plan",
    response_model=RoutePlanResponse,
    summary="Plan Accessible Route Between Coordinates",
    description="Calculate an accessibility-aware pedestrian route between any two geographic coordinates with multi-criteria optimization.",
)
def plan_route(
    request: RoutePlanRequest,
    manager: DynamicGraphManager = Depends(get_graph_manager),
    cache: RegionalGraphCache = Depends(get_regional_cache),
) -> RoutePlanResponse:
    # 1. Resolve Routing Policy
    if request.preferences:
        active_policy = compile_preferences_to_policy(request.preferences)
        preset_val = getattr(request.preferences.preset, "value", request.preferences.preset)
        policy_key = f"preferences:{preset_val}"
    else:
        policy_key = request.policy.strip().lower()
        if policy_key not in POLICY_MAP:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported routing policy '{request.policy}'. Supported: {list(POLICY_MAP.keys())}",
            )
        active_policy = POLICY_MAP[policy_key]

    origin = (request.origin.latitude, request.origin.longitude)
    destination = (request.destination.latitude, request.destination.longitude)

    # 2. Execute Coordinated Route Planning
    result = route_between_coordinates(
        origin=origin,
        destination=destination,
        policy=active_policy,
        enrich_elevation=request.enrich_elevation,
        manager=manager,
        allow_expansion=request.allow_expansion,
    )

    # 3. Load Regional Graph for GeoJSON Export
    graph = None
    try:
        graph, _ = cache.load_graph(result.region_id)
    except Exception as exc:
        logger.debug("Could not load cached graph for GeoJSON enhancement: %s", exc)

    # 4. Generate RFC 7946 GeoJSON FeatureCollection
    geojson_data = route_result_to_geojson(
        result=result,
        graph=graph,
        include_segments=True,
        include_baseline=request.compare_baseline,
    )

    # 5. Build Baseline Comparison Metrics
    baseline_comp: Optional[BaselineComparisonSchema] = None
    if request.compare_baseline and result.baseline_route and result.baseline_route.found:
        base_dist = result.baseline_route.physical_distance_meters
        acc_dist = result.physical_distance_meters
        delta_m = max(0.0, acc_dist - base_dist)
        delta_pct = round((delta_m / base_dist) * 100.0, 1) if base_dist > 0.1 else 0.0

        # Identify barriers avoided in accessible route vs baseline
        base_findings = result.baseline_route.findings_encountered
        acc_findings = result.route.findings_encountered
        avoided_count = len(base_findings - acc_findings)

        baseline_comp = BaselineComparisonSchema(
            baseline_distance_m=round(base_dist, 1),
            accessible_distance_m=round(acc_dist, 1),
            distance_delta_m=round(delta_m, 1),
            distance_delta_pct=delta_pct,
            barriers_avoided_count=avoided_count,
        )

    # 6. Format Metrics
    metrics_dict = result.route.metrics
    metrics_schema = RouteMetricsSchema(
        physical_distance_m=round(result.physical_distance_meters, 1),
        total_cost=round(result.total_cost, 1),
        accessibility_cost=round(result.accessibility_cost, 1),
        terrain_cost=round(result.terrain_cost, 1),
        uncertainty_cost=round(result.uncertainty_cost, 1),
        elevation_gain_m=round(float(metrics_dict.get("elevation_gain_m", 0.0)), 1),
        elevation_loss_m=round(float(metrics_dict.get("elevation_loss_m", 0.0)), 1),
        max_uphill_grade_pct=round(float(metrics_dict.get("max_uphill_grade_pct", 0.0)), 1),
        missing_data_pct=round(float(metrics_dict.get("missing_data_pct", 0.0)), 1),
    )

    # 7. Format Regional Expansion Telemetry
    initial_bbox_list = list(result.initial_bbox) if result.initial_bbox else None
    final_bbox_list = list(result.region_bbox) if result.region_bbox else None
    expansion_schema = ExpansionMetadataSchema(
        expansion_occurred=result.expansion_occurred,
        attempts=result.expansion_attempts,
        initial_bbox=initial_bbox_list,
        final_bbox=final_bbox_list,
    )

    route_id = f"rte_{uuid.uuid4().hex[:12]}"

    return RoutePlanResponse(
        route_id=route_id,
        found=result.found,
        policy=policy_key,
        requested_origin=request.origin,
        requested_destination=request.destination,
        snapped_origin=CoordinatePair(
            latitude=result.snapped_origin[0],
            longitude=result.snapped_origin[1],
        ),
        snapped_destination=CoordinatePair(
            latitude=result.snapped_destination[0],
            longitude=result.snapped_destination[1],
        ),
        origin_snap_distance_m=result.origin_snap_distance_m,
        destination_snap_distance_m=result.destination_snap_distance_m,
        snap_warnings=result.snap_warnings,
        metrics=metrics_schema,
        baseline_comparison=baseline_comp,
        explanations=result.explanations,
        expansion=expansion_schema,
        region_id=result.region_id,
        cache_hit=result.cache_hit,
        accessibility_enriched=result.accessibility_enriched,
        terrain_enriched=result.terrain_enriched,
        geojson=geojson_data,
    )


@router.post(
    "/alternatives",
    response_model=RouteAlternativesResponse,
    summary="Compare Accessible Route Alternatives",
    description="Calculate and compare multiple distinct route alternatives (Accessibility-Aware, Lower Slope, Shortest) with directions, elevation profiles, and plain-language cards.",
)
def plan_route_alternatives(
    request: RouteAlternativesRequest,
    manager: DynamicGraphManager = Depends(get_graph_manager),
    cache: RegionalGraphCache = Depends(get_regional_cache),
) -> RouteAlternativesResponse:
    origin = (request.origin.latitude, request.origin.longitude)
    destination = (request.destination.latitude, request.destination.longitude)

    result = calculate_route_alternatives(
        origin=origin,
        destination=destination,
        enrich_elevation=request.enrich_elevation,
        allow_expansion=request.allow_expansion,
        manager=manager,
        preferences=request.preferences,
    )

    graph = None
    try:
        graph, _ = cache.load_graph(result.region_id)
    except Exception as exc:
        logger.debug("Could not load cached graph for alternatives GeoJSON: %s", exc)

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

    return RouteAlternativesResponse(
        found=result.found,
        requested_origin=request.origin,
        requested_destination=request.destination,
        snapped_origin=CoordinatePair(
            latitude=result.snapped_origin[0],
            longitude=result.snapped_origin[1],
        ),
        snapped_destination=CoordinatePair(
            latitude=result.snapped_destination[0],
            longitude=result.snapped_destination[1],
        ),
        origin_snap_distance_m=result.origin_snap_distance_m,
        destination_snap_distance_m=result.destination_snap_distance_m,
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

