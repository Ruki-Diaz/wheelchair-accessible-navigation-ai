"""Unit and integration tests for accessibility-aware terrain routing and directionality."""

import networkx as nx
import pytest

from accessroute.elevation import SyntheticElevationProvider, enrich_graph_with_elevation
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import make_policy_cost_func
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.routing.router import compare_routes


@pytest.fixture
def terrain_bifurcation_graph():
    """Create a synthetic diamond graph with two alternative paths:

    Node 1 (start, elev=100m)
    Node 2 (steep hill summit, elev=112m)
    Node 3 (gentle detour mid, elev=102m)
    Node 4 (destination, elev=103m)

    Branch A (1 -> 2 -> 4):
      1 -> 2: length=100m, Delta z = +12m (+12% steep uphill)
      2 -> 4: length=100m, Delta z = -9m (-9% downhill)
      Total physical distance = 200m

    Branch B (1 -> 3 -> 4):
      1 -> 3: length=130m, Delta z = +2m (+1.5% gentle slope)
      3 -> 4: length=130m, Delta z = +1m (+0.8% gentle slope)
      Total physical distance = 260m (+60m detour)
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.849)
    G.add_node(3, x=145.171, y=-37.851)
    G.add_node(4, x=145.172, y=-37.850)

    # Branch A: Short & Steep
    G.add_edge(1, 2, key=0, length=100.0, highway="footway", surface="asphalt")
    G.add_edge(2, 1, key=0, length=100.0, highway="footway", surface="asphalt")
    G.add_edge(2, 4, key=0, length=100.0, highway="footway", surface="asphalt")
    G.add_edge(4, 2, key=0, length=100.0, highway="footway", surface="asphalt")

    # Branch B: Longer & Gentle
    G.add_edge(1, 3, key=0, length=130.0, highway="footway", surface="asphalt")
    G.add_edge(3, 1, key=0, length=130.0, highway="footway", surface="asphalt")
    G.add_edge(3, 4, key=0, length=130.0, highway="footway", surface="asphalt")
    G.add_edge(4, 3, key=0, length=130.0, highway="footway", surface="asphalt")

    provider = SyntheticElevationProvider(
        elevation_map={
            (-37.850, 145.170): 100.0,  # Node 1
            (-37.849, 145.171): 112.0,  # Node 2
            (-37.851, 145.171): 102.0,  # Node 3
            (-37.850, 145.172): 103.0,  # Node 4
        }
    )
    enrich_graph_with_elevation(G, provider)
    return G


# ============================================================================
# 1. UPHILL AVOIDANCE & POLICY TRADE-OFFS
# ============================================================================

def test_terrain_aware_routing_prefers_gentle_detour(terrain_bifurcation_graph):
    """Verify that a terrain-aware policy avoids a +12% steep hill in favor of a gentle detour."""
    G = terrain_bifurcation_graph

    # Distance-first policy chooses the shorter 200m steep path (1 -> 2 -> 4)
    res_dist = a_star_search(G, 1, 4, policy=DISTANCE_FIRST_POLICY)
    assert res_dist.found is True
    assert res_dist.nodes == [1, 2, 4]
    assert res_dist.total_distance_meters == 200.0

    # Conservative policy penalizes the +12% climb and chooses the 260m gentle detour (1 -> 3 -> 4)
    res_cons = a_star_search(G, 1, 4, policy=CONSERVATIVE_ACCESSIBILITY_POLICY)
    assert res_cons.found is True
    assert res_cons.nodes == [1, 3, 4]
    assert res_cons.total_distance_meters == 260.0
    assert res_cons.terrain_cost < 10.0  # Minimal terrain resistance
    assert res_cons.metrics["max_uphill_grade_pct"] < 3.0


def test_terrain_cost_separation(terrain_bifurcation_graph):
    """Verify terrain cost is exposed separately in RouteResult and not mixed into accessibility cost."""
    G = terrain_bifurcation_graph

    # Run over steep path under balanced policy
    res = a_star_search(G, 1, 2, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is True
    assert res.physical_distance_meters == 100.0
    # Both paths are paved asphalt, so accessibility cost is 0
    assert res.accessibility_cost == 0.0
    # Terrain cost is explicitly calculated and positive for +12% climb
    assert res.terrain_cost > 0.0
    assert res.total_cost > res.physical_distance_meters


# ============================================================================
# 2. DIRECTIONALITY: A -> B vs B -> A
# ============================================================================

def test_directionality_asymmetric_routing(terrain_bifurcation_graph):
    """Verify that travel direction changes routing costs and paths.

    Going 1 -> 2 is +12% uphill (costly).
    Going 2 -> 1 is -12% downhill (different cost profile).
    """
    G = terrain_bifurcation_graph

    # Custom policy sensitive to uphill climbs
    uphill_sensitive_policy = RoutingPolicy(
        name="uphill_sensitive",
        distance_weight=1.0,
        terrain_weight=3.0,
        max_preferred_uphill_grade_pct=5.0,
        penalty_per_uphill_grade_pct_m=30.0,
        max_preferred_downhill_grade_pct=15.0,  # Accepts downhill
        penalty_steep_downhill_pct_m=0.0,
    )

    # 1 -> 2 (Uphill: +12m over 100m)
    res_up = a_star_search(G, 1, 2, policy=uphill_sensitive_policy)
    # 2 -> 1 (Downhill: -12m over 100m)
    res_down = a_star_search(G, 2, 1, policy=uphill_sensitive_policy)

    assert res_up.found and res_down.found
    assert res_up.physical_distance_meters == res_down.physical_distance_meters == 100.0
    # Uphill terrain cost must be strictly greater than downhill terrain cost
    assert res_up.terrain_cost > res_down.terrain_cost
    assert res_down.terrain_cost == 0.0  # Downhill slope is within 15% preferred limit


# ============================================================================
# 3. HARD STEEP SLOPE PROHIBITION
# ============================================================================

def test_hard_steep_incline_prohibition(terrain_bifurcation_graph):
    """Verify that when prohibit_steep_incline=True, slopes exceeding threshold are pruned."""
    G = terrain_bifurcation_graph

    strict_slope_policy = RoutingPolicy(
        name="strict_slope",
        distance_weight=1.0,
        terrain_weight=1.0,
        prohibit_steep_incline=True,
        max_permitted_uphill_grade_pct=10.0,  # Prunes slope > 10%
    )

    # Path 1 -> 2 has +12% slope, so it must be completely excluded
    res = a_star_search(G, 1, 4, policy=strict_slope_policy)
    assert res.found is True
    # Successfully routes around the summit via Node 3
    assert res.nodes == [1, 3, 4]


# ============================================================================
# 4. A* VS DIJKSTRA WITH TERRAIN COSTS (OPTIMALITY BENCHMARK)
# ============================================================================

def test_astar_vs_dijkstra_terrain_optimality(terrain_bifurcation_graph):
    """Verify custom A* with terrain costs discovers identical optimal cost as Dijkstra."""
    G = terrain_bifurcation_graph
    policy = BALANCED_ACCESSIBILITY_POLICY

    cost_func = make_policy_cost_func(G, policy)

    res_astar = a_star_search(G, 1, 4, policy=policy)
    dijkstra_cost = nx.dijkstra_path_length(G, 1, 4, weight=cost_func)

    assert res_astar.total_cost == pytest.approx(dijkstra_cost, 1e-4)


# ============================================================================
# 5. ROUTE COMPARISON & TERRAIN EXPLANATIONS
# ============================================================================

def test_route_comparison_terrain_avoidance_explanation(terrain_bifurcation_graph):
    """Verify compare_routes detects steep hill avoidance and generates factual rationale."""
    comp = compare_routes(
        terrain_bifurcation_graph, 1, 4, policy=CONSERVATIVE_ACCESSIBILITY_POLICY
    )
    assert comp.baseline_route.found is True
    assert comp.accessible_route.found is True
    assert comp.distance_difference_m == 60.0
    assert "Steep Uphill Slope" in comp.barriers_avoided
    assert any("uphill" in exp.lower() or "elevation" in exp.lower() for exp in comp.explanations)
    assert "accessible_terrain_cost_m" in comp.pareto_tradeoffs
