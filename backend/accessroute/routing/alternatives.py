"""Multi-alternative route orchestration for AccessRoute AI Stage 7 Public MVP.

Calculates and compares up to 3 distinct accessibility-informed route alternatives:
1. Accessibility-Aware (Balanced trade-offs)
2. Lower Estimated Slope (Slope-focused terrain caution)
3. Shortest Available (Direct distance with barrier exclusion)

Includes automatic path deduplication, turn-by-turn guidance,
elevation profiles, and comparative metrics.
"""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx

from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.region import (
    DEFAULT_BUFFER_METERS,
    DEFAULT_BUFFER_RATIO,
    BoundingBox,
    RouteRegionTooLargeError,
    validate_coordinates,
)
from accessroute.graph.snapper import SnappedNode, snap_to_nearest_node
from accessroute.routing.astar import RouteResult, a_star_search
from accessroute.routing.directions import DirectionStep, generate_turn_by_turn_directions
from accessroute.routing.elevation_profile import RouteElevationSummary, generate_elevation_profile
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.heuristics import haversine_distance
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.intelligence.route_quality import RouteEvidenceQualityAnalyzer

logger = logging.getLogger(__name__)

# Standard wheelchair / pedestrian movement speed: 3.6 km/h = 60 m/min
STANDARD_PACE_METERS_PER_MIN = 60.0


@dataclass
class RouteAlternative:
    """A distinct, user-facing route option with plain-language metrics."""

    key: str  # "accessibility_aware" | "lower_slope" | "shortest"
    title: str  # "Accessibility-Aware" | "Lower Estimated Slope" | "Shortest Available"
    badge: str  # "Recommended" | "Lower Slope" | "Shortest Distance"
    description: str
    policy_name: str
    physical_distance_m: float
    estimated_duration_min: int
    distance_delta_m: float
    distance_delta_pct: float
    elevation_gain_m: float
    elevation_loss_m: float
    max_uphill_grade_pct: float
    stairs_encountered_count: int
    unpaved_distance_m: float
    paved_percentage: float
    crossings_count: int
    crossings_unknown_kerb_count: int
    missing_data_pct: float
    explanations: List[str]
    directions: List[DirectionStep]
    elevation_summary: RouteElevationSummary
    route_result: RouteResult
    color_hex: str
    is_shortest: bool = False
    evidence_quality: Optional[Dict[str, Any]] = None


@dataclass
class RouteAlternativesResult:
    """Complete collection of route alternatives between geographic coordinates."""

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
    alternatives: List[RouteAlternative]
    region_id: str
    region_bbox: Tuple[float, float, float, float]
    cache_hit: bool
    accessibility_enriched: bool
    terrain_enriched: bool
    expansion_occurred: bool = False
    expansion_attempts: int = 1
    geojson: Dict[str, Any] = field(default_factory=dict)
    blocking_reasons: List[str] = field(default_factory=list)


def calculate_route_alternatives(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    buffer_meters: float = DEFAULT_BUFFER_METERS,
    buffer_ratio: float = DEFAULT_BUFFER_RATIO,
    enrich_elevation: bool = True,
    snap_warning_threshold_m: float = 150.0,
    manager: Optional[DynamicGraphManager] = None,
    allow_expansion: bool = True,
    max_expansion_attempts: int = 2,
    preferences: Optional[Any] = None,
) -> RouteAlternativesResult:
    """Calculate and compare up to 3 distinct route alternatives.

    Workflow:
    1. Validates coordinates.
    2. Acquires single shared regional pedestrian network.
    3. Snaps origin and destination to network.
    4. Evaluates User Preferred (or Balanced), Lower Slope, and Shortest policies.
    5. Deduplicates identical paths while preserving informative badges.
    6. Generates turn-by-turn guidance and elevation profiles for all distinct options.
    7. Calculates factual comparative deltas and personalized explanations.
    8. If strict user constraints block routing, provides deterministic conflict diagnosis without silent relaxation.
    """
    from accessroute.preferences.models import AvoidanceLevel, StepPreference
    from accessroute.preferences.compiler import compile_preferences_to_policy
    from accessroute.scoring.models import FindingType

    orig_lat, orig_lon = origin
    dest_lat, dest_lon = destination
    validate_coordinates(orig_lat, orig_lon, name="origin")
    validate_coordinates(dest_lat, dest_lon, name="destination")

    # Identical endpoints handling
    direct_dist = haversine_distance(orig_lat, orig_lon, dest_lat, dest_lon)
    if direct_dist < 0.5:
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
        single_alt = RouteAlternative(
            key="accessibility_aware",
            title="Your Preferred Route" if preferences else "Accessibility-Aware",
            badge="Direct",
            description="Origin and destination are at the same location.",
            policy_name="preferred" if preferences else "balanced",
            physical_distance_m=0.0,
            estimated_duration_min=0,
            distance_delta_m=0.0,
            distance_delta_pct=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            max_uphill_grade_pct=0.0,
            stairs_encountered_count=0,
            unpaved_distance_m=0.0,
            paved_percentage=100.0,
            crossings_count=0,
            crossings_unknown_kerb_count=0,
            missing_data_pct=0.0,
            explanations=["Origin and destination coordinates are identical."],
            directions=[],
            elevation_summary=RouteElevationSummary(
                points=[],
                elevation_gain_m=0.0,
                elevation_loss_m=0.0,
                max_uphill_grade_pct=0.0,
                max_downhill_grade_pct=0.0,
                min_elevation_m=0.0,
                max_elevation_m=0.0,
            ),
            route_result=empty_res,
            color_hex="#2563eb",
            is_shortest=True,
            evidence_quality=(
                RouteEvidenceQualityAnalyzer.analyze_route_evidence(empty_res).to_dict()
                if "RouteEvidenceQualityAnalyzer" in globals()
                else None
            ),
        )
        return RouteAlternativesResult(
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
            alternatives=[single_alt],
            region_id="zero_distance",
            region_bbox=(orig_lat, orig_lon, orig_lat, orig_lon),
            cache_hit=True,
            accessibility_enriched=True,
            terrain_enriched=True,
            expansion_occurred=False,
            expansion_attempts=1,
        )

    # 1. Acquire Graph (with regional expansion if needed)
    graph_manager = manager or DynamicGraphManager()
    current_bbox = BoundingBox.from_coordinates(
        origin=origin,
        destination=destination,
        buffer_meters=buffer_meters,
        buffer_ratio=buffer_ratio,
    )

    expansion_occurred = False
    expansion_attempts = 1
    max_attempts = max_expansion_attempts if allow_expansion else 1

    last_G: Optional[nx.MultiDiGraph] = None
    last_meta = None
    last_cache_hit = False
    orig_snap: Optional[SnappedNode] = None
    dest_snap: Optional[SnappedNode] = None

    # Determine probe policy for reachability
    user_policy = compile_preferences_to_policy(preferences) if preferences else BALANCED_ACCESSIBILITY_POLICY

    for attempt in range(1, max_attempts + 1):
        expansion_attempts = attempt
        G, meta, cache_hit = graph_manager.get_graph_for_bbox(
            bbox=current_bbox,
            enrich_elevation=enrich_elevation,
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

        orig_snap = snap_to_nearest_node(G, orig_lat, orig_lon)
        dest_snap = snap_to_nearest_node(G, dest_lat, dest_lon)

        # Test reachability with user policy (or balanced default)
        test_route = a_star_search(
            graph=G,
            start=orig_snap.node_id,
            goal=dest_snap.node_id,
            policy=user_policy,
        )

        if test_route.found:
            break

        if allow_expansion and attempt < max_attempts:
            try:
                expanded_bbox = current_bbox.expand(factor=1.5, min_expansion_m=300.0)
                current_bbox = expanded_bbox
                expansion_occurred = True
            except RouteRegionTooLargeError:
                break

    # Snapping notices
    snap_warnings: List[str] = []
    if orig_snap.distance_meters > snap_warning_threshold_m:
        snap_warnings.append(
            f"Origin is {orig_snap.distance_meters:.0f}m from the nearest mapped pedestrian path."
        )
    if dest_snap.distance_meters > snap_warning_threshold_m:
        snap_warnings.append(
            f"Destination is {dest_snap.distance_meters:.0f}m from the nearest mapped pedestrian path."
        )

    # 2. Evaluate Candidate Policies
    if preferences:
        preset_name = getattr(preferences, "preset", None)
        preset_label = preset_name.value.replace("_", " ").title() if hasattr(preset_name, "value") else "selected"
        candidates_config = [
            {
                "key": "accessibility_aware",
                "title": "Your Preferred Route",
                "badge": "Preferred",
                "description": f"Customised to your {preset_label} mobility preferences.",
                "policy": user_policy,
                "color_hex": "#2563eb",  # Blue
            },
            {
                "key": "lower_slope",
                "title": "Lower Estimated Slope",
                "badge": "Lower Slope",
                "description": "Prefers routes with lower estimated terrain difficulty where supported by available elevation evidence.",
                "policy": CONSERVATIVE_ACCESSIBILITY_POLICY,
                "color_hex": "#059669",  # Green
            },
            {
                "key": "shortest",
                "title": "Shortest Available",
                "badge": "Shortest Distance",
                "description": "Minimises physical distance across the mapped pedestrian network.",
                "policy": DISTANCE_FIRST_POLICY,
                "color_hex": "#d97706",  # Amber/Orange
            },
        ]
    else:
        candidates_config = [
            {
                "key": "accessibility_aware",
                "title": "Accessibility-Aware",
                "badge": "Recommended",
                "description": "Prioritises available accessibility evidence while avoiding known barriers.",
                "policy": BALANCED_ACCESSIBILITY_POLICY,
                "color_hex": "#2563eb",  # Blue
            },
            {
                "key": "lower_slope",
                "title": "Lower Estimated Slope",
                "badge": "Lower Slope",
                "description": "Prefers routes with lower estimated terrain difficulty where supported by available elevation evidence.",
                "policy": CONSERVATIVE_ACCESSIBILITY_POLICY,
                "color_hex": "#059669",  # Green
            },
            {
                "key": "shortest",
                "title": "Shortest Available",
                "badge": "Shortest Distance",
                "description": "Primarily minimises physical distance while still respecting hard accessibility prohibitions.",
                "policy": DISTANCE_FIRST_POLICY,
                "color_hex": "#d97706",  # Amber/Orange
            },
        ]

    calculated_routes: List[Tuple[Dict[str, Any], RouteResult]] = []
    preferred_route_found = False

    for cfg in candidates_config:
        res = a_star_search(
            graph=last_G,
            start=orig_snap.node_id,
            goal=dest_snap.node_id,
            policy=cfg["policy"],
        )
        if res.found:
            calculated_routes.append((cfg, res))
            if cfg["key"] == "accessibility_aware":
                preferred_route_found = True

    # 3. Preference Conflict Diagnosis: If user preferences specified but no route satisfied strict constraints
    if preferences and not preferred_route_found:
        # Run unconstrained search to determine if physical path exists
        unconstrained_policy = RoutingPolicy(
            name="unconstrained_diagnostic",
            prohibit_steps_without_ramp=False,
            prohibit_wheelchair_no=False,
            prohibit_known_restrictive_barriers=False,
            max_tolerable_incline_pct=None,
            max_permitted_uphill_grade_pct=None,
            prohibit_unpaved_surfaces=False,
            prohibit_unknown_kerb_crossings=False,
            prohibit_below_min_width=False,
            accessibility_weight=0.0,
            terrain_weight=0.0,
            uncertainty_weight=0.0,
        )
        diag_res = a_star_search(
            graph=last_G,
            start=orig_snap.node_id,
            goal=dest_snap.node_id,
            policy=unconstrained_policy,
        )
        blocking_reasons: List[str] = []
        if not diag_res.found:
            blocking_reasons.append("No physical pedestrian path connects the requested origin and destination in the mapped network.")
        else:
            # Analyze edges in the unconstrained shortest path for strictly prohibited conditions
            if preferences.avoid_steps == StepPreference.NEVER:
                has_stairs = any(
                    "step" in str(e.get("highway", "")).lower()
                    or e.get("steps_without_ramp")
                    or FindingType.STEPS_PRESENT.value in e.get("findings", set())
                    for e in diag_res.edges
                )
                if has_stairs:
                    blocking_reasons.append("Mapped stairs prohibit the available connection, and you selected 'Never use mapped stairs'.")

            if preferences.maximum_permitted_uphill_grade_pct is not None:
                max_uphill = max([float(e.get("grade_pct", 0.0) or 0.0) for e in diag_res.edges] + [0.0])
                if max_uphill > preferences.maximum_permitted_uphill_grade_pct:
                    blocking_reasons.append(
                        f"The available path has an estimated uphill slope of {max_uphill:.1f}%, exceeding your strict limit of {preferences.maximum_permitted_uphill_grade_pct:.1f}%."
                    )

            if preferences.unpaved_surfaces == AvoidanceLevel.STRICTLY_AVOID:
                has_unpaved = any(
                    str(e.get("surface", "")).lower() in ("gravel", "fine_gravel", "ground", "dirt", "grass", "compacted", "unpaved")
                    for e in diag_res.edges
                )
                if has_unpaved:
                    blocking_reasons.append("The available connection contains unpaved surfaces (gravel/dirt/grass), which you have strictly avoided.")

            if preferences.unknown_kerbs == AvoidanceLevel.STRICTLY_AVOID:
                has_unknown_kerb = any(
                    (bool(e.get("is_crossing")) or str(e.get("highway", "")).lower() == "crossing")
                    and str(e.get("kerb", "unknown")).lower() == "unknown"
                    for e in diag_res.edges
                )
                if has_unknown_kerb:
                    blocking_reasons.append("Available road crossings lack recorded kerb information, and you chose to strictly avoid unknown kerbs.")

            if preferences.narrow_paths == AvoidanceLevel.STRICTLY_AVOID and preferences.minimum_path_width_m is not None:
                has_narrow = any(
                    e.get("width") is not None and float(e.get("width")) < preferences.minimum_path_width_m
                    for e in diag_res.edges
                )
                if has_narrow:
                    blocking_reasons.append(f"Available paths have recorded width narrower than your required {preferences.minimum_path_width_m:.1f}m.")
                elif preferences.unknown_width == AvoidanceLevel.STRICTLY_AVOID:
                    has_unknown_width = any(e.get("width") is None for e in diag_res.edges)
                    if has_unknown_width:
                        blocking_reasons.append("Available paths lack recorded width measurements, and you chose to strictly avoid unknown width.")

            if not blocking_reasons:
                blocking_reasons.append("The combination of your strict avoidance constraints prevents finding an accessible path within the searched area.")

        return RouteAlternativesResult(
            found=False,
            requested_origin=origin,
            requested_destination=destination,
            snapped_origin=(orig_snap.latitude, orig_snap.longitude),
            snapped_destination=(dest_snap.latitude, dest_snap.longitude),
            origin_node_id=orig_snap.node_id,
            destination_node_id=dest_snap.node_id,
            origin_snap_distance_m=round(orig_snap.distance_meters, 1),
            destination_snap_distance_m=round(dest_snap.distance_meters, 1),
            snap_warnings=snap_warnings,
            alternatives=[],
            region_id=last_meta.region_id if last_meta else "none",
            region_bbox=(last_meta.bbox.south, last_meta.bbox.west, last_meta.bbox.north, last_meta.bbox.east) if last_meta else (0, 0, 0, 0),
            cache_hit=last_cache_hit,
            accessibility_enriched=last_meta.accessibility_enriched if last_meta else False,
            terrain_enriched=last_meta.terrain_enriched if last_meta else False,
            expansion_occurred=expansion_occurred,
            expansion_attempts=expansion_attempts,
            blocking_reasons=blocking_reasons,
        )

    if not calculated_routes:
        # No route found for any policy
        return RouteAlternativesResult(
            found=False,
            requested_origin=origin,
            requested_destination=destination,
            snapped_origin=(orig_snap.latitude, orig_snap.longitude),
            snapped_destination=(dest_snap.latitude, dest_snap.longitude),
            origin_node_id=orig_snap.node_id,
            destination_node_id=dest_snap.node_id,
            origin_snap_distance_m=round(orig_snap.distance_meters, 1),
            destination_snap_distance_m=round(dest_snap.distance_meters, 1),
            snap_warnings=snap_warnings,
            alternatives=[],
            region_id=last_meta.region_id if last_meta else "none",
            region_bbox=(last_meta.bbox.south, last_meta.bbox.west, last_meta.bbox.north, last_meta.bbox.east) if last_meta else (0, 0, 0, 0),
            cache_hit=last_cache_hit,
            accessibility_enriched=last_meta.accessibility_enriched if last_meta else False,
            terrain_enriched=last_meta.terrain_enriched if last_meta else False,
            expansion_occurred=expansion_occurred,
            expansion_attempts=expansion_attempts,
            blocking_reasons=["No accessible path found connecting the requested endpoints within the searched area."],
        )

    # 4. Find baseline shortest distance among candidate routes
    min_dist = min(res.physical_distance_meters for _, res in calculated_routes)

    # 5. Deduplicate alternatives: keep physically distinct paths
    seen_paths: Dict[Tuple[int, ...], RouteAlternative] = {}
    alternatives: List[RouteAlternative] = []

    for cfg, res in calculated_routes:
        path_key = tuple(res.nodes)

        # Compute granular accessibility stats
        stairs_count = 0
        unpaved_m = 0.0
        paved_m = 0.0
        crossings_count = 0
        unknown_kerb_crossings = 0

        for edge_data in res.edges:
            length_m = float(edge_data.get("length", 0.0))
            highway = str(edge_data.get("highway", "")).lower()
            surface = str(edge_data.get("surface", "unknown")).lower()
            is_crossing = bool(edge_data.get("is_crossing", False)) or highway == "crossing"
            kerb = str(edge_data.get("kerb", "unknown")).lower()

            if "step" in highway:
                stairs_count += 1
            if surface in ("asphalt", "concrete", "paved", "concrete:plates", "paving_stones"):
                paved_m += length_m
            elif surface in ("gravel", "fine_gravel", "ground", "dirt", "grass", "compacted"):
                unpaved_m += length_m

            if is_crossing:
                crossings_count += 1
                if kerb == "unknown":
                    unknown_kerb_crossings += 1

        total_phys_m = max(res.physical_distance_meters, 0.1)
        paved_pct = round((paved_m / total_phys_m) * 100.0, 1)
        dist_delta_m = max(0.0, res.physical_distance_meters - min_dist)
        dist_delta_pct = round((dist_delta_m / min_dist) * 100.0, 1) if min_dist > 0.1 else 0.0
        duration_min = max(1, round(total_phys_m / STANDARD_PACE_METERS_PER_MIN))
        is_shortest = abs(res.physical_distance_meters - min_dist) < 1.0

        # Elevation summary
        elev_summary = generate_elevation_profile(
            nodes=res.nodes,
            edges=res.edges,
            geometries=res.geometries,
            graph=last_G,
        )

        # Turn-by-turn directions
        directions = generate_turn_by_turn_directions(
            nodes=res.nodes,
            edges=res.edges,
            geometries=res.geometries,
            graph=last_G,
        )

        # Explanations
        shortest_res = next((r for _, r in calculated_routes if abs(r.physical_distance_meters - min_dist) < 1.0), None)
        base_metrics = shortest_res.metrics if shortest_res and shortest_res != res else None
        exps = generate_route_explanation(
            route_metrics=res.metrics,
            findings=res.findings_encountered,
            baseline_metrics=base_metrics,
            policy_name=cfg["policy"].name,
            preferences=preferences if cfg["key"] == "accessibility_aware" else None,
        )
        if expansion_occurred:
            exps.insert(0, f"Search area was expanded ({expansion_attempts} attempts) to discover an accessible path.")

        # If this is the shortest alternative and preferences were specified, note conditions avoided
        if cfg["key"] == "shortest" and preferences and not is_shortest:
            pass  # not shortest
        elif cfg["key"] == "shortest" and preferences and len(calculated_routes) > 1:
            if stairs_count > 0 and preferences.avoid_steps != StepPreference.ALLOW:
                exps.append("Note: This shortest path contains mapped stairs that your personal preferences avoid.")
            if unpaved_m > 0 and preferences.unpaved_surfaces != AvoidanceLevel.ALLOW:
                exps.append(f"Note: Contains {unpaved_m:.0f}m of unpaved surfaces that your preferences prefer to avoid.")

        # Check if identical path already exists
        if path_key in seen_paths:
            existing = seen_paths[path_key]
            # Augment existing alternative's description rather than duplicating
            if cfg["key"] == "lower_slope" and existing.key == "accessibility_aware":
                existing.description += " This route also satisfies the lower estimated slope criteria."
                existing.badge = "Preferred & Flattest" if preferences else "Recommended & Flattest"
            elif cfg["key"] == "shortest" and existing.key == "accessibility_aware":
                existing.is_shortest = True
                existing.badge = "Preferred (Shortest)" if preferences else "Recommended (Shortest)"
                existing.description = (
                    "The shortest physical path already satisfies all your selected mobility preferences."
                    if preferences
                    else "The shortest physical path already satisfies all accessibility criteria."
                )
            continue

        alt = RouteAlternative(
            key=cfg["key"],
            title=cfg["title"],
            badge=cfg["badge"],
            description=cfg["description"],
            policy_name=cfg["policy"].name,
            physical_distance_m=round(res.physical_distance_meters, 1),
            estimated_duration_min=duration_min,
            distance_delta_m=round(dist_delta_m, 1),
            distance_delta_pct=dist_delta_pct,
            elevation_gain_m=elev_summary.elevation_gain_m,
            elevation_loss_m=elev_summary.elevation_loss_m,
            max_uphill_grade_pct=elev_summary.max_uphill_grade_pct,
            stairs_encountered_count=stairs_count,
            unpaved_distance_m=round(unpaved_m, 1),
            paved_percentage=paved_pct,
            crossings_count=crossings_count,
            crossings_unknown_kerb_count=unknown_kerb_crossings,
            missing_data_pct=round(float(res.metrics.get("missing_data_pct", 0.0)), 1),
            explanations=exps,
            directions=directions,
            elevation_summary=elev_summary,
            route_result=res,
            color_hex=cfg["color_hex"],
            is_shortest=is_shortest,
            evidence_quality=RouteEvidenceQualityAnalyzer.analyze_route_evidence(res).to_dict(),
        )

        seen_paths[path_key] = alt
        alternatives.append(alt)

    return RouteAlternativesResult(
        found=True,
        requested_origin=origin,
        requested_destination=destination,
        snapped_origin=(orig_snap.latitude, orig_snap.longitude),
        snapped_destination=(dest_snap.latitude, dest_snap.longitude),
        origin_node_id=orig_snap.node_id,
        destination_node_id=dest_snap.node_id,
        origin_snap_distance_m=round(orig_snap.distance_meters, 1),
        destination_snap_distance_m=round(dest_snap.distance_meters, 1),
        snap_warnings=snap_warnings,
        alternatives=alternatives,
        region_id=last_meta.region_id,
        region_bbox=(last_meta.bbox.south, last_meta.bbox.west, last_meta.bbox.north, last_meta.bbox.east),
        cache_hit=last_cache_hit,
        accessibility_enriched=last_meta.accessibility_enriched,
        terrain_enriched=last_meta.terrain_enriched,
        expansion_occurred=expansion_occurred,
        expansion_attempts=expansion_attempts,
    )
