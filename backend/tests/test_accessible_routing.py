"""Comprehensive test suite for Stage 3 accessibility-aware routing, policies, and explainability.

Covers:
- Explicit wheelchair=no prohibition
- Steps prohibited vs ramp-equipped steps
- Raised kerb penalty & lowered kerb preference
- Paved vs unpaved surface trade-offs
- Contextual crossing uncertainty penalties
- Node barrier evaluation (passable vs restrictive)
- MultiDiGraph parallel edge accessibility selection
- Trivial start == goal paths and unreachable destinations
- Preservation of Stage 1 baseline route
- A* vs Dijkstra optimality with multi-criteria costs
- Deterministic factual explanation generation
- Policy configuration sensitivity
"""

import pytest
import networkx as nx

from accessroute.graph.enricher import enrich_graph_accessibility
from accessroute.routing.astar import a_star_search, RouteResult
from accessroute.routing.cost_evaluator import (
    evaluate_transition_cost,
    make_policy_cost_func,
)
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.routing.router import compare_routes, plan_route
from accessroute.scoring.models import (
    BarrierType,
    FindingType,
    KerbType,
    SurfaceType,
    WheelchairAccess,
)


@pytest.fixture
def accessibility_test_graph() -> nx.MultiDiGraph:
    """Construct a controlled MultiDiGraph for testing accessibility trade-offs.

    Topology:
        Node 1 (Origin)
        Branch A: 1 -> 2 (Stairs, 30m) -> 3 (Goal, 30m)  Total: 60m with stairs
        Branch B: 1 -> 4 (Paved, 40m) -> 3 (Goal, 40m)   Total: 80m paved ramp
        Branch C: 1 -> 5 (Unpaved, 35m) -> 3 (Goal, 35m) Total: 70m unpaved gravel
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850)
    G.add_node(3, x=145.172, y=-37.850)
    G.add_node(4, x=145.171, y=-37.851)
    G.add_node(5, x=145.171, y=-37.849)

    # Branch A (Stairs): 1 -> 2 -> 3 (60m)
    G.add_edge(1, 2, key=0, length=30.0, highway="steps")
    G.add_edge(2, 1, key=0, length=30.0, highway="steps")
    G.add_edge(2, 3, key=0, length=30.0, highway="footway", surface="asphalt")
    G.add_edge(3, 2, key=0, length=30.0, highway="footway", surface="asphalt")

    # Branch B (Paved bypass): 1 -> 4 -> 3 (80m)
    G.add_edge(1, 4, key=0, length=40.0, highway="footway", surface="concrete")
    G.add_edge(4, 1, key=0, length=40.0, highway="footway", surface="concrete")
    G.add_edge(4, 3, key=0, length=40.0, highway="footway", surface="concrete")
    G.add_edge(3, 4, key=0, length=40.0, highway="footway", surface="concrete")

    # Branch C (Unpaved gravel): 1 -> 5 -> 3 (70m)
    G.add_edge(1, 5, key=0, length=35.0, highway="path", surface="gravel")
    G.add_edge(5, 1, key=0, length=35.0, highway="path", surface="gravel")
    G.add_edge(5, 3, key=0, length=35.0, highway="path", surface="gravel")
    G.add_edge(3, 5, key=0, length=35.0, highway="path", surface="gravel")

    return G


# ============================================================================
# 1. HARD PROHIBITIONS
# ============================================================================

def test_prohibit_wheelchair_no(accessibility_test_graph):
    """Verify that an edge with wheelchair=no is completely impassable under accessible policies."""
    G = accessibility_test_graph
    # Tag branch B with wheelchair=no
    G[1][4][0]["wheelchair"] = "no"

    # With wheelchair=no on Branch B and stairs on Branch A:
    # Balanced policy must take Branch C (unpaved) rather than prohibited wheelchair=no
    res = a_star_search(G, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is True
    assert 4 not in res.nodes, "Route should not use node 4 with wheelchair=no"
    assert res.nodes == [1, 5, 3]


def test_prohibit_steps_without_ramp(accessibility_test_graph):
    """Verify that stairs without ramps are avoided even if physically shorter."""
    G = accessibility_test_graph
    # Baseline distance-only chooses Branch A (60m)
    res_base = a_star_search(G, 1, 3, policy=None)
    assert res_base.nodes == [1, 2, 3]
    assert res_base.total_distance_meters == 60.0

    # Accessible policy avoids Branch A and chooses Branch C (70m) or B (80m)
    res_acc = a_star_search(G, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res_acc.found is True
    assert 2 not in res_acc.nodes, "Route must not use stairs node 2"


def test_steps_permitted_with_wheelchair_ramp(accessibility_test_graph):
    """Verify that stairs with wheelchair ramp are traversable under accessible policy."""
    G = accessibility_test_graph
    # Add ramp:wheelchair=yes to the stairs on Branch A
    G[1][2][0]["ramp:wheelchair"] = "yes"

    res = a_star_search(G, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is True
    # Now that the stairs have a wheelchair ramp, it is traversable and remains shortest (60m)
    assert res.nodes == [1, 2, 3]
    assert res.total_distance_meters == 60.0


def test_prohibit_restrictive_node_barrier(accessibility_test_graph):
    """Verify that turnstiles and restrictive barriers block traversal."""
    G = accessibility_test_graph
    # Put turnstile on node 4
    G.nodes[4]["barrier"] = "turnstile"

    res = a_star_search(G, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is True
    assert 4 not in res.nodes, "Node 4 with turnstile must be prohibited"


# ============================================================================
# 2. SOFT ACCESSIBILITY PENALTIES & SURFACE TRADE-OFFS
# ============================================================================

def test_paved_preferred_over_unpaved(accessibility_test_graph):
    """Verify that under Conservative policy, a longer paved path (80m) is preferred over unpaved (70m)."""
    G = accessibility_test_graph
    # Branch B: 80m paved
    # Branch C: 70m gravel
    # Conservative policy adds penalty_unpaved_surface_m (200m) to Branch C edges,
    # so Branch B has lower total cost than Branch C!
    res_cons = a_star_search(G, 1, 3, policy=CONSERVATIVE_ACCESSIBILITY_POLICY)
    assert res_cons.found is True
    assert res_cons.nodes == [1, 4, 3], "Conservative policy should prefer paved Branch B over gravel Branch C"
    assert res_cons.total_distance_meters == 80.0


def test_distance_first_prefers_shorter_unpaved(accessibility_test_graph):
    """Verify that under Distance-First policy, the shorter unpaved path (70m) is preferred over paved (80m)."""
    G = accessibility_test_graph
    res_dist = a_star_search(G, 1, 3, policy=DISTANCE_FIRST_POLICY)
    assert res_dist.found is True
    # Distance-first avoids stairs (Branch A prohibited), but chooses shorter Branch C (70m) over B (80m)
    assert res_dist.nodes == [1, 5, 3]
    assert res_dist.total_distance_meters == 70.0


def test_raised_kerb_penalized(accessibility_test_graph):
    """Verify that raised kerbs incur soft penalty, favoring flush/lowered alternatives."""
    G = accessibility_test_graph
    # Add raised kerb to node 4
    G.nodes[4]["kerb"] = "raised"

    res = a_star_search(G, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY)
    # Raised kerb on node 4 adds penalty, tipping preference to Branch C
    assert res.nodes == [1, 5, 3]


# ============================================================================
# 3. UNCERTAINTY & CROSSING TRADE-OFFS
# ============================================================================

def test_crossing_uncertainty_penalty():
    """Verify that missing kerb ramp on an uncontrolled crossing incurs contextual uncertainty."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850, kerb="unknown")
    G.add_node(3, x=145.170, y=-37.851)
    G.add_node(4, x=145.171, y=-37.851, kerb="flush", traffic_signals="yes")

    # Path 1: 100m direct crossing with unknown kerb
    G.add_edge(1, 2, key=0, length=100.0, highway="crossing", footway="crossing")
    G.add_edge(2, 1, key=0, length=100.0, highway="crossing", footway="crossing")

    # Path 2: 135m detour with confirmed flush kerb and traffic signals
    G.add_edge(1, 3, key=0, length=40.0, highway="footway", surface="asphalt")
    G.add_edge(3, 1, key=0, length=40.0, highway="footway", surface="asphalt")
    G.add_edge(
        3, 4, key=0, length=55.0, highway="crossing", crossing="traffic_signals", traffic_signals="yes", kerb="flush"
    )
    G.add_edge(
        4, 3, key=0, length=55.0, highway="crossing", crossing="traffic_signals", traffic_signals="yes", kerb="flush"
    )
    G.add_edge(4, 2, key=0, length=40.0, highway="footway", surface="asphalt")
    G.add_edge(2, 4, key=0, length=40.0, highway="footway", surface="asphalt")

    res_cons = a_star_search(G, 1, 2, policy=CONSERVATIVE_ACCESSIBILITY_POLICY)
    assert res_cons.found is True
    # Conservative policy uncertainty penalty on unverified crossing diverts to Path 2
    assert res_cons.nodes == [1, 3, 4, 2]
    assert res_cons.total_distance_meters == 135.0


# ============================================================================
# 4. MULTIDIGRAPH PARALLEL EDGE SELECTION
# ============================================================================

def test_parallel_edge_accessibility_selection():
    """Verify that A* selects an accessible parallel edge over a shorter inaccessible edge."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node(10, x=145.170, y=-37.850)
    G.add_node(20, x=145.171, y=-37.850)

    # Shorter stairs (30m) vs Longer concrete ramp (45m)
    G.add_edge(10, 20, key=0, length=30.0, highway="steps")
    G.add_edge(10, 20, key=1, length=45.0, highway="footway", surface="concrete")

    # Baseline selects key 0 (stairs)
    res_base = a_star_search(G, 10, 20, policy=None)
    assert res_base.total_distance_meters == 30.0
    assert res_base.edges[0]["highway"] == "steps"

    # Accessible policy selects key 1 (paved ramp)
    res_acc = a_star_search(G, 10, 20, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res_acc.total_distance_meters == 45.0
    assert res_acc.edges[0]["highway"] == "footway"
    assert res_acc.edges[0]["surface"] == "concrete"


# ============================================================================
# 5. A* ADMISSIBILITY & DIJKSTRA OPTIMALITY BENCHMARK
# ============================================================================

def test_astar_vs_dijkstra_accessibility_optimality(accessibility_test_graph):
    """Verify that A* and Dijkstra yield identical costs under an accessibility policy."""
    G = accessibility_test_graph
    policy = BALANCED_ACCESSIBILITY_POLICY
    cost_func = make_policy_cost_func(G, policy)

    # Run custom A*
    res_astar = a_star_search(G, 1, 3, policy=policy)

    # Run NetworkX Dijkstra with the exact same cost callable
    dijkstra_dist = nx.dijkstra_path_length(G, 1, 3, weight=cost_func)

    assert res_astar.total_cost == pytest.approx(dijkstra_dist, 1e-4)


# ============================================================================
# 6. ROUTE COMPARISON & DETERMINISTIC EXPLANATIONS
# ============================================================================

def test_route_comparison_and_explanation(accessibility_test_graph):
    """Verify that compare_routes accurately detects barriers avoided and generates factual explanations."""
    comp = compare_routes(
        accessibility_test_graph, 1, 3, policy=BALANCED_ACCESSIBILITY_POLICY
    )
    assert comp.baseline_route.found is True
    assert comp.accessible_route.found is True
    assert comp.distance_difference_m > 0
    assert "Outdoor Stairs" in comp.barriers_avoided
    assert len(comp.explanations) > 0
    # Explanation must reference stairs avoidance
    assert any("stairs" in exp.lower() for exp in comp.explanations)


def test_start_equals_goal(accessibility_test_graph):
    """Verify trivial path where origin == destination under policy."""
    res = a_star_search(accessibility_test_graph, 1, 1, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is True
    assert res.nodes == [1]
    assert res.total_distance_meters == 0.0
    assert res.total_cost == 0.0


def test_unreachable_accessible_destination():
    """Verify graceful handling when destination is completely unreachable without crossing stairs."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850)
    # The only connection is stairs
    G.add_edge(1, 2, key=0, length=25.0, highway="steps")

    res = a_star_search(G, 1, 2, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert res.found is False
    assert len(res.nodes) == 0
    assert "No path exists" in res.message
