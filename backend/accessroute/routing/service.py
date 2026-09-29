"""High-level location-independent routing orchestration service."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from accessroute.graph.manager import DynamicGraphManager, get_graph_for_route
from accessroute.graph.region import (
    DEFAULT_BUFFER_METERS,
    DEFAULT_BUFFER_RATIO,
    BoundingBox,
    validate_coordinates,
)
from accessroute.graph.snapper import SnappedNode, snap_to_nearest_node
from accessroute.routing.astar import RouteResult, a_star_search
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.heuristics import haversine_distance
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)

logger = logging.getLogger(__name__)

DEFAULT_SNAP_WARNING_DISTANCE_METERS = 150.0


@dataclass
class CoordinatedRouteResult:
    """End-to-end routing outcome between arbitrary geographic coordinates."""

    found: bool
    requested_origin: Tuple[float, float]
    requested_destination: Tuple[float, float]
    snapped_origin: Tuple[float, float]
    snapped_destination: Tuple[float, float]
    origin_node_id: int
    destination_node_id: int
    origin_snap_distance_m: float
    destination_snap_distance_m: float
    snap_warnings: List[str]
    route: RouteResult
    baseline_route: Optional[RouteResult]
    region_id: str
    region_bbox: Tuple[float, float, float, float]  # (south, west, north, east)
    cache_hit: bool
    accessibility_enriched: bool
    terrain_enriched: bool
    explanations: List[str] = field(default_factory=list)
    expansion_occurred: bool = False
    expansion_attempts: int = 1
    initial_bbox: Optional[Tuple[float, float, float, float]] = None

    @property
    def total_distance_meters(self) -> float:
        return self.route.total_distance_meters

    @property
    def physical_distance_meters(self) -> float:
        return self.route.physical_distance_meters

    @property
    def total_cost(self) -> float:
        return self.route.total_cost

    @property
    def terrain_cost(self) -> float:
        return self.route.terrain_cost

    @property
    def accessibility_cost(self) -> float:
        return self.route.accessibility_cost

    @property
    def uncertainty_cost(self) -> float:
        return self.route.uncertainty_cost


def route_between_coordinates(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    policy: Optional[RoutingPolicy] = None,
    buffer_meters: float = DEFAULT_BUFFER_METERS,
    buffer_ratio: float = DEFAULT_BUFFER_RATIO,
    enrich_elevation: bool = True,
    snap_warning_threshold_m: float = DEFAULT_SNAP_WARNING_DISTANCE_METERS,
    manager: Optional[DynamicGraphManager] = None,
    force_refresh: bool = False,
    allow_expansion: bool = True,
    max_expansion_attempts: int = 2,
    expansion_factor: float = 1.5,
    min_expansion_m: float = 300.0,
) -> CoordinatedRouteResult:
    """Calculate an accessibility-aware route between any two geographic coordinates.

    Orchestrates the complete end-to-end pipeline:
    1. Validates coordinates and bounds.
    2. Dynamically acquires or reuses a regional pedestrian network.
    3. Normalizes accessibility and enriches terrain.
    4. Snaps origin and destination to the nearest walkable nodes.
    5. Flags snapping distance warnings if coordinates are far from mapped paths.
    6. Executes multi-criteria A* search.
    7. Automatically expands the search region if no accessible route is found within the initial boundary.
    8. Calculates baseline shortest path for comparative factual explainability.
    9. Returns structured CoordinatedRouteResult with full spatial and expansion telemetry.

    Args:
        origin: (latitude, longitude) of origin point.
        destination: (latitude, longitude) of destination point.
        policy: RoutingPolicy instance (defaults to BALANCED_ACCESSIBILITY_POLICY).
        buffer_meters: Minimum spatial padding in meters around endpoints.
        buffer_ratio: Proportional padding based on separation distance.
        enrich_elevation: Whether to attach elevation/grade evidence.
        snap_warning_threshold_m: Snapping distance threshold above which a warning is flagged.
        manager: Optional DynamicGraphManager instance for custom providers or caching.
        force_refresh: If True, bypasses cache and re-downloads fresh OSM network.
        allow_expansion: Whether to expand search region if routing fails.
        max_expansion_attempts: Maximum number of regional expansion attempts.
        expansion_factor: Multiplier for expanding bounding box on retry.
        min_expansion_m: Minimum metric expansion per side on retry.

    Returns:
        CoordinatedRouteResult with route telemetry, geographic metadata, and explanations.

    Raises:
        CoordinateValidationError: If coordinates are out of bounds or invalid.
        RouteRegionTooLargeError: If requested separation exceeds operational limits.
        GraphAcquisitionError: If the pedestrian graph cannot be acquired.
    """
    orig_lat, orig_lon = origin
    dest_lat, dest_lon = destination
    validate_coordinates(orig_lat, orig_lon, name="origin")
    validate_coordinates(dest_lat, dest_lon, name="destination")

    active_policy = policy if policy is not None else BALANCED_ACCESSIBILITY_POLICY

    # Check for identical origin and destination
    direct_dist = haversine_distance(orig_lat, orig_lon, dest_lat, dest_lon)
    if direct_dist < 0.5:
        # Immediate 0m result
        empty_res = RouteResult(
            found=True,
            start_node=0,
            goal_node=0,
            nodes=[],
            edges=[],
            total_distance_meters=0.0,
            total_cost=0.0,
            accessibility_cost=0.0,
            terrain_cost=0.0,
            uncertainty_cost=0.0,
            findings_encountered=set(),
            metrics={"physical_distance_m": 0.0},
        )
        return CoordinatedRouteResult(
            found=True,
            requested_origin=origin,
            requested_destination=destination,
            snapped_origin=origin,
            snapped_destination=destination,
            origin_node_id=0,
            destination_node_id=0,
            origin_snap_distance_m=0.0,
            destination_snap_distance_m=0.0,
            snap_warnings=[],
            route=empty_res,
            baseline_route=empty_res,
            region_id="zero_distance",
            region_bbox=(orig_lat, orig_lon, orig_lat, orig_lon),
            cache_hit=True,
            accessibility_enriched=True,
            terrain_enriched=True,
            explanations=["Origin and destination coordinates are identical."],
            expansion_occurred=False,
            expansion_attempts=1,
            initial_bbox=(orig_lat, orig_lon, orig_lat, orig_lon),
        )

    # 1. Initialize Bounding Box
    graph_manager = manager or DynamicGraphManager()
    current_bbox = BoundingBox.from_coordinates(
        origin=origin,
        destination=destination,
        buffer_meters=buffer_meters,
        buffer_ratio=buffer_ratio,
    )
    initial_bbox_tuple = (
        current_bbox.south,
        current_bbox.west,
        current_bbox.north,
        current_bbox.east,
    )

    expansion_occurred = False
    expansion_attempts = 1
    max_attempts = max_expansion_attempts if allow_expansion else 1

    last_G = None
    last_meta = None
    last_cache_hit = False
    orig_snap: Optional[SnappedNode] = None
    dest_snap: Optional[SnappedNode] = None
    accessible_route: Optional[RouteResult] = None

    # Regional acquisition & routing loop with controlled expansion
    for attempt in range(1, max_attempts + 1):
        expansion_attempts = attempt
        G, meta, cache_hit = graph_manager.get_graph_for_bbox(
            bbox=current_bbox,
            enrich_elevation=enrich_elevation,
            force_refresh=force_refresh,
        )
        last_G = G
        last_meta = meta
        last_cache_hit = cache_hit

        # Enrich graph with active community observations in bounding box
        try:
            from accessroute.community.service import CommunityObservationService
            comm_svc = CommunityObservationService()
            comm_svc.enrich_graph_with_observations(
                G, bbox=(current_bbox.south, current_bbox.west, current_bbox.north, current_bbox.east)
            )
        except Exception as e:
            logger.warning("Could not enrich graph with community observations: %s", e)

        # 2. Snap coordinates to pedestrian network
        orig_snap = snap_to_nearest_node(G, orig_lat, orig_lon)
        dest_snap = snap_to_nearest_node(G, dest_lat, dest_lon)

        # 3. Calculate accessible route via multi-criteria A*
        accessible_route = a_star_search(
            graph=G,
            start=orig_snap.node_id,
            goal=dest_snap.node_id,
            policy=active_policy,
        )

        if accessible_route.found:
            break

        # Attempt expansion if route was not found within current bounding box
        if allow_expansion and attempt < max_attempts:
            try:
                expanded_bbox = current_bbox.expand(
                    factor=expansion_factor,
                    min_expansion_m=min_expansion_m,
                )
                logger.info(
                    "Accessible route not found in bbox %s (attempt %d). Expanding to area=%.2f km²...",
                    current_bbox.spatial_id,
                    attempt,
                    expanded_bbox.area_km2,
                )
                current_bbox = expanded_bbox
                expansion_occurred = True
            except RouteRegionTooLargeError:
                logger.info("Cannot expand region further; reached operational area limit.")
                break

    # 4. Calculate baseline shortest path for comparative explainability
    baseline_route = a_star_search(
        graph=last_G,
        start=orig_snap.node_id,
        goal=dest_snap.node_id,
        policy=DISTANCE_FIRST_POLICY,
    )

    snap_warnings: List[str] = []
    if orig_snap.distance_meters > snap_warning_threshold_m:
        snap_warnings.append(
            f"Origin point is {orig_snap.distance_meters:.0f}m from the nearest mapped pedestrian path."
        )
    if dest_snap.distance_meters > snap_warning_threshold_m:
        snap_warnings.append(
            f"Destination point is {dest_snap.distance_meters:.0f}m from the nearest mapped pedestrian path."
        )

    # 5. Generate deterministic explanations
    explanations: List[str] = []
    if accessible_route.found:
        base_metrics = baseline_route.metrics if baseline_route.found else None
        explanations = generate_route_explanation(
            route_metrics=accessible_route.metrics,
            findings=accessible_route.findings_encountered,
            baseline_metrics=base_metrics,
            policy_name=active_policy.name,
        )
        if expansion_occurred:
            explanations.insert(
                0,
                f"Regional expansion notice: Search area was expanded ({expansion_attempts} attempts) to discover an accessible detour.",
            )
        for warn in snap_warnings:
            explanations.insert(0, f"Snapping notice: {warn}")
    else:
        explanations = [
            f"No route satisfying the {active_policy.name} routing policy was found within the searched area."
        ]
        if expansion_occurred:
            explanations.append(
                f"Searched area was expanded {expansion_attempts} time(s) up to {last_meta.bbox.area_km2:.1f} km²."
            )
        for warn in snap_warnings:
            explanations.insert(0, f"Snapping notice: {warn}")

    return CoordinatedRouteResult(
        found=accessible_route.found,
        requested_origin=origin,
        requested_destination=destination,
        snapped_origin=(orig_snap.latitude, orig_snap.longitude),
        snapped_destination=(dest_snap.latitude, dest_snap.longitude),
        origin_node_id=orig_snap.node_id,
        destination_node_id=dest_snap.node_id,
        origin_snap_distance_m=round(orig_snap.distance_meters, 1),
        destination_snap_distance_m=round(dest_snap.distance_meters, 1),
        snap_warnings=snap_warnings,
        route=accessible_route,
        baseline_route=baseline_route,
        region_id=last_meta.region_id,
        region_bbox=(last_meta.bbox.south, last_meta.bbox.west, last_meta.bbox.north, last_meta.bbox.east),
        cache_hit=last_cache_hit,
        accessibility_enriched=last_meta.accessibility_enriched,
        terrain_enriched=last_meta.terrain_enriched,
        explanations=explanations,
        expansion_occurred=expansion_occurred,
        expansion_attempts=expansion_attempts,
        initial_bbox=initial_bbox_tuple,
    )
