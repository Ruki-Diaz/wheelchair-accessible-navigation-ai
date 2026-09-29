"""A* pathfinding algorithm operating on OpenStreetMap NetworkX graphs.

Supports multi-criteria optimization, separating physical distance, accessibility penalties,
and contextual uncertainty costs while preserving A* heuristic admissibility.
"""

from dataclasses import dataclass, field
import heapq
import itertools
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import networkx as nx
from shapely.geometry import LineString

from accessroute.routing.heuristics import make_graph_haversine_heuristic
from accessroute.routing.policy import RoutingPolicy
from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
)
from accessroute.scoring.normalizer import (
    extract_edge_evidence,
    extract_node_evidence,
)


@dataclass
class RouteResult:
    """Encapsulates the result of a pathfinding query with separated multi-criteria metrics."""
    found: bool
    start_node: int
    goal_node: int
    nodes: List[int] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    total_distance_meters: float = 0.0
    total_cost: float = 0.0
    accessibility_cost: float = 0.0
    terrain_cost: float = 0.0
    uncertainty_cost: float = 0.0
    findings_encountered: Set[str] = field(default_factory=set)
    metrics: Dict[str, Any] = field(default_factory=dict)
    explanations: List[str] = field(default_factory=list)
    policy_name: str = "distance_first"
    geometries: List[LineString] = field(default_factory=list)
    nodes_expanded: int = 0
    message: str = ""

    @property
    def physical_distance_meters(self) -> float:
        """Alias for total_distance_meters."""
        return self.total_distance_meters



def default_distance_cost(u: int, v: int, edge_data: Dict[str, Any]) -> float:
    """Default Stage 1 cost function: pure physical edge length in meters."""
    length = edge_data.get("length")
    if length is None:
        return float("inf")
    try:
        return float(length)
    except (ValueError, TypeError):
        return float("inf")


def a_star_search(
    graph: nx.MultiDiGraph,
    start: int,
    goal: int,
    cost_func: Optional[Callable[[int, int, Dict[str, Any]], float]] = None,
    heuristic_func: Optional[Callable[[int, int], float]] = None,
    policy: Optional[RoutingPolicy] = None,
) -> RouteResult:
    """Calculate the optimal path between start and goal nodes using A* search.

    Preserves A* admissibility:
    When a RoutingPolicy is active, the heuristic h(u, goal) = distance_weight * haversine(u, goal).
    Because all accessibility and uncertainty penalties are non-negative, this heuristic is a strictly
    admissible and consistent lower bound on remaining cost.

    Args:
        graph: NetworkX MultiDiGraph representing the pedestrian network.
        start: OSM node ID of the starting location.
        goal: OSM node ID of the destination location.
        cost_func: Optional callable (u, v, edge_data) -> float.
        heuristic_func: Optional callable (u, v) -> float.
        policy: Optional active RoutingPolicy governing multi-criteria weights and prohibitions.

    Returns:
        RouteResult containing path nodes, selected edges, decomposed costs, metrics, and explanations.
    """
    if start not in graph:
        raise ValueError(f"Start node {start} does not exist in the graph.")
    if goal not in graph:
        raise ValueError(f"Goal node {goal} does not exist in the graph.")

    # Lazy import to avoid circular dependencies
    from accessroute.routing.cost_evaluator import (
        evaluate_transition_cost,
        make_policy_cost_func,
    )
    from accessroute.routing.explainability import generate_route_explanation

    # Edge cost function defaults
    if cost_func is None:
        if policy is not None:
            cost_func = make_policy_cost_func(graph, policy)
        else:
            cost_func = default_distance_cost

    # Heuristic defaults to admissible Haversine distance scaled by distance_weight
    if heuristic_func is None:
        scale = policy.distance_weight if policy is not None else 1.0
        heuristic_func = make_graph_haversine_heuristic(graph, scale=scale)

    # Trivial case: origin is destination
    if start == goal:
        return RouteResult(
            found=True,
            start_node=start,
            goal_node=goal,
            nodes=[start],
            total_distance_meters=0.0,
            total_cost=0.0,
            accessibility_cost=0.0,
            uncertainty_cost=0.0,
            nodes_expanded=0,
            policy_name=policy.name if policy else "distance_first",
            message="Origin and destination are identical.",
        )

    # Priority queue: entries are (f_score, tie_breaker_counter, node_id)
    tie_breaker = itertools.count()
    open_set: List[Tuple[float, int, int]] = []
    initial_h = heuristic_func(start, goal)
    heapq.heappush(open_set, (initial_h, next(tie_breaker), start))

    came_from: Dict[int, int] = {}
    edge_taken: Dict[int, Tuple[int, Any, Dict[str, Any]]] = {}  # v -> (u, key, edge_data)
    g_score: Dict[int, float] = {start: 0.0}
    f_score: Dict[int, float] = {start: initial_h}
    closed_set = set()
    nodes_expanded = 0

    while open_set:
        current_f, _, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path backwards from goal to start
            path_nodes: List[int] = []
            path_edges: List[Dict[str, Any]] = []
            path_geometries: List[LineString] = []
            curr = goal

            while curr in came_from:
                prev = came_from[curr]
                _, key, edge_data = edge_taken[curr]
                path_nodes.append(curr)
                path_edges.append(edge_data)

                # Geometry extraction
                geom = edge_data.get("geometry")
                if geom is not None and isinstance(geom, LineString):
                    path_geometries.append(geom)
                else:
                    u_node = graph.nodes[prev]
                    v_node = graph.nodes[curr]
                    path_geometries.append(
                        LineString([(u_node["x"], u_node["y"]), (v_node["x"], v_node["y"])])
                    )
                curr = prev

            path_nodes.append(start)
            path_nodes.reverse()
            path_edges.reverse()
            path_geometries.reverse()

            total_dist = sum(float(e.get("length", 0.0)) for e in path_edges)
            final_cost = g_score[goal]

            # Detailed Multi-Criteria Decomposition & Metric Aggregation
            total_acc_cost = 0.0
            total_terrain_cost = 0.0
            total_unc_cost = 0.0
            route_findings: Set[str] = set()

            # Aggregate metrics
            paved_distance = 0.0
            unpaved_distance = 0.0
            unpaved_count = 0
            unknown_surface_count = 0
            crossings_count = 0
            crossings_without_kerb = 0
            raised_kerbs = 0
            lowered_kerbs = 0
            steps_count = 0
            total_missing_fields = 0
            elevation_gain_m = 0.0
            elevation_loss_m = 0.0
            max_uphill_grade_pct = 0.0
            max_downhill_grade_pct = 0.0
            known_elevation_dist = 0.0
            suspicious_grade_count = 0

            for i in range(len(path_nodes) - 1):
                u = path_nodes[i]
                v = path_nodes[i + 1]
                e_data = path_edges[i]
                phys_len = float(e_data.get("length", 0.0))

                edge_ev = (
                    e_data["_accessibility_evidence"]
                    if "_accessibility_evidence" in e_data
                    else extract_edge_evidence(e_data)
                )
                node_v_data = graph.nodes.get(v, {})
                node_ev = (
                    node_v_data["_accessibility_evidence"]
                    if "_accessibility_evidence" in node_v_data
                    else extract_node_evidence(v, node_v_data)
                )

                terrain_ev = e_data.get("terrain_evidence")
                if terrain_ev is None or not hasattr(terrain_ev, "signed_grade"):
                    elev_u = graph.nodes[u].get("elevation_m")
                    elev_v = graph.nodes[v].get("elevation_m")
                    if elev_u is not None and elev_v is not None:
                        delta_z = float(elev_v) - float(elev_u)
                        sg = delta_z / max(phys_len, 0.1)
                        from accessroute.scoring.models import EdgeTerrainEvidence, SlopeDirection
                        terrain_ev = EdgeTerrainEvidence(
                            elevation_start_m=elev_u,
                            elevation_end_m=elev_v,
                            elevation_change_m=delta_z,
                            length_m=phys_len,
                            signed_grade=sg,
                            absolute_grade=abs(sg),
                            direction=SlopeDirection.UPHILL if sg >= 0.02 else (SlopeDirection.DOWNHILL if sg <= -0.02 else SlopeDirection.FLAT),
                            is_known=True,
                        )

                if policy is not None:
                    bd = evaluate_transition_cost(
                        edge_evidence=edge_ev,
                        node_evidence=node_ev,
                        policy=policy,
                        physical_distance_m=phys_len,
                        terrain_evidence=terrain_ev,
                    )
                    total_acc_cost += bd.accessibility_penalty_m
                    total_terrain_cost += bd.terrain_penalty_m
                    total_unc_cost += bd.uncertainty_penalty_m
                    route_findings.update(f.value if hasattr(f, "value") else str(f) for f in bd.findings)
                else:
                    route_findings.update(f.value if hasattr(f, "value") else str(f) for f in edge_ev.findings)
                    if node_ev:
                        route_findings.update(f.value if hasattr(f, "value") else str(f) for f in node_ev.findings)
                    if "findings" in e_data:
                        route_findings.update(f.value if hasattr(f, "value") else str(f) for f in e_data["findings"])

                # Terrain telemetry
                if terrain_ev is not None and getattr(terrain_ev, "is_known", False):
                    known_elevation_dist += phys_len
                    elevation_gain_m += getattr(terrain_ev, "elevation_gain_m", 0.0)
                    elevation_loss_m += getattr(terrain_ev, "elevation_loss_m", 0.0)
                    sg = getattr(terrain_ev, "signed_grade", None)
                    if sg is not None:
                        g_pct = sg * 100.0
                        if g_pct > max_uphill_grade_pct:
                            max_uphill_grade_pct = g_pct
                        if g_pct < max_downhill_grade_pct:
                            max_downhill_grade_pct = g_pct
                        if g_pct >= 8.0:
                            route_findings.add(FindingType.STEEP_UPHILL_RECORDED.value)
                            route_findings.add(FindingType.STEEP_INCLINE_RECORDED.value)
                        elif g_pct <= -8.0:
                            route_findings.add(FindingType.STEEP_DOWNHILL_RECORDED.value)
                            route_findings.add(FindingType.STEEP_INCLINE_RECORDED.value)
                    if getattr(terrain_ev, "is_grade_suspicious", False):
                        suspicious_grade_count += 1
                        route_findings.add(FindingType.SUSPICIOUS_GRADE_FLAGGED.value)

                # Surface aggregation
                if edge_ev.surface in (
                    SurfaceType.ASPHALT,
                    SurfaceType.CONCRETE,
                    SurfaceType.PAVED,
                    SurfaceType.CONCRETE_PLATES,
                    SurfaceType.PAVING_STONES,
                ):
                    paved_distance += phys_len
                elif edge_ev.surface in (
                    SurfaceType.GRAVEL,
                    SurfaceType.FINE_GRAVEL,
                    SurfaceType.DIRT,
                    SurfaceType.GROUND,
                    SurfaceType.GRASS,
                    SurfaceType.COMPACTED,
                ):
                    unpaved_distance += phys_len
                    unpaved_count += 1
                elif edge_ev.surface == SurfaceType.UNKNOWN:
                    unknown_surface_count += 1

                # Crossings and kerbs
                if edge_ev.is_crossing or (node_ev and node_ev.is_crossing):
                    crossings_count += 1
                    has_kerb = (
                        edge_ev.kerb != KerbType.UNKNOWN
                        or (node_ev and node_ev.kerb != KerbType.UNKNOWN)
                    )
                    if not has_kerb:
                        crossings_without_kerb += 1

                if edge_ev.kerb == KerbType.RAISED or (node_ev and node_ev.kerb == KerbType.RAISED):
                    raised_kerbs += 1
                elif edge_ev.kerb in (KerbType.LOWERED, KerbType.FLUSH) or (
                    node_ev and node_ev.kerb in (KerbType.LOWERED, KerbType.FLUSH)
                ):
                    lowered_kerbs += 1

                if edge_ev.is_steps:
                    steps_count += 1

                total_missing_fields += len(edge_ev.missing_fields)

            paved_pct = (paved_distance / total_dist * 100.0) if total_dist > 0 else 0.0
            possible_fields_count = len(path_edges) * 8  # 8 primary fields evaluated
            missing_pct = (
                (total_missing_fields / possible_fields_count * 100.0)
                if possible_fields_count > 0
                else 0.0
            )
            known_elev_pct = (known_elevation_dist / total_dist * 100.0) if total_dist > 0 else 0.0

            metrics = {
                "physical_distance_m": total_dist,
                "total_cost": final_cost,
                "accessibility_cost_m": total_acc_cost,
                "terrain_cost_m": total_terrain_cost,
                "uncertainty_cost_m": total_unc_cost,
                "findings": sorted(list(route_findings)),
                "paved_distance_m": paved_distance,
                "paved_distance_pct": paved_pct,
                "unpaved_distance_m": unpaved_distance,
                "unpaved_segments_count": unpaved_count,
                "unknown_surface_segments_count": unknown_surface_count,
                "crossings_count": crossings_count,
                "crossings_without_kerb_info_count": crossings_without_kerb,
                "raised_kerbs_count": raised_kerbs,
                "lowered_kerbs_count": lowered_kerbs,
                "steps_count": steps_count,
                "missing_data_pct": missing_pct,
                "elevation_gain_m": round(elevation_gain_m, 1),
                "elevation_loss_m": round(elevation_loss_m, 1),
                "max_uphill_grade_pct": round(max_uphill_grade_pct, 1),
                "max_downhill_grade_pct": round(max_downhill_grade_pct, 1),
                "known_elevation_pct": round(known_elev_pct, 1),
                "suspicious_grade_count": suspicious_grade_count,
                "policy_name": policy.name if policy else "distance_first",
            }

            # Generate deterministic factual explanations
            explanations = generate_route_explanation(
                route_metrics=metrics,
                findings=route_findings,
                policy_name=policy.name if policy else "distance_first",
            )

            return RouteResult(
                found=True,
                start_node=start,
                goal_node=goal,
                nodes=path_nodes,
                edges=path_edges,
                total_distance_meters=total_dist,
                total_cost=final_cost,
                accessibility_cost=total_acc_cost,
                terrain_cost=total_terrain_cost,
                uncertainty_cost=total_unc_cost,
                findings_encountered=route_findings,
                metrics=metrics,
                explanations=explanations,
                policy_name=policy.name if policy else "distance_first",
                geometries=path_geometries,
                nodes_expanded=nodes_expanded,
                message=f"Optimal route found across {len(path_nodes)} nodes.",
            )

        if current in closed_set:
            continue
        closed_set.add(current)
        nodes_expanded += 1

        # Explore outgoing neighbors from current node
        for neighbor in graph.neighbors(current):
            edge_dict = graph.get_edge_data(current, neighbor)
            if not edge_dict:
                continue

            # Parallel Edge Selection:
            # Select the edge with minimal total cost under the active cost function
            best_key = None
            best_cost = float("inf")
            best_edge_data = None

            for key, data in edge_dict.items():
                cost = cost_func(current, neighbor, data)
                if cost < best_cost:
                    best_cost = cost
                    best_key = key
                    best_edge_data = data

            if best_edge_data is None or best_cost == float("inf"):
                continue  # Prohibited or impassable transition

            tentative_g_score = g_score[current] + best_cost

            if tentative_g_score < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                edge_taken[neighbor] = (current, best_key, best_edge_data)
                g_score[neighbor] = tentative_g_score
                h_val = heuristic_func(neighbor, goal)
                f_val = tentative_g_score + h_val
                f_score[neighbor] = f_val
                heapq.heappush(open_set, (f_val, next(tie_breaker), neighbor))

    # Open set exhausted without reaching goal
    return RouteResult(
        found=False,
        start_node=start,
        goal_node=goal,
        nodes=[],
        edges=[],
        total_distance_meters=0.0,
        total_cost=float("inf"),
        accessibility_cost=0.0,
        uncertainty_cost=0.0,
        geometries=[],
        nodes_expanded=nodes_expanded,
        policy_name=policy.name if policy else "distance_first",
        message="No path exists between the specified nodes in the pedestrian network under the active routing policy.",
    )
