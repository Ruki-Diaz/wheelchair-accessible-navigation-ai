"""Unit and integration tests for refactored A* pathfinding and Dijkstra benchmarking."""

import pytest
import networkx as nx

from accessroute.config import PROTOTYPE_FIXTURE_COORDINATES
from accessroute.graph.snapper import snap_to_nearest_node
from accessroute.routing.astar import a_star_search, RouteResult


def test_astar_start_equals_destination(synthetic_multidigraph):
    """Verify trivial route where origin and destination are identical."""
    res = a_star_search(synthetic_multidigraph, 101, 101)
    assert res.found is True
    assert res.nodes == [101]
    assert res.total_distance_meters == 0.0
    assert res.total_cost == 0.0


def test_astar_unreachable_destination(synthetic_multidigraph):
    """Verify graceful handling when destination cannot be reached."""
    res = a_star_search(synthetic_multidigraph, 101, 199)
    assert res.found is False
    assert len(res.nodes) == 0
    assert res.total_distance_meters == 0.0
    assert "No path exists" in res.message


def test_astar_selects_minimum_parallel_edge(synthetic_multidigraph):
    """Verify that A* consistently selects the shorter parallel edge (150m vs 200m)."""
    res = a_star_search(synthetic_multidigraph, 101, 102)
    assert res.found is True
    assert res.nodes == [101, 102]
    # Edge key 1 has length 150.0; edge key 0 has length 200.0
    assert res.total_distance_meters == 150.0
    assert res.edges[0]["highway"] == "path"


def test_astar_path_continuity(synthetic_multidigraph):
    """Verify that every step along the computed route is connected by a valid graph edge."""
    res = a_star_search(synthetic_multidigraph, 101, 104)
    assert res.found is True
    assert len(res.nodes) >= 2

    # Check continuity: each pair of sequential nodes must be connected
    for i in range(len(res.nodes) - 1):
        u = res.nodes[i]
        v = res.nodes[i + 1]
        assert synthetic_multidigraph.has_edge(u, v)

    # Expected distance: 150 (101->102) + 180 (102->103) + 170 (103->104) = 500m
    assert res.total_distance_meters == pytest.approx(500.0, 0.01)


def test_astar_vs_dijkstra_synthetic(synthetic_multidigraph):
    """Benchmark custom A* against NetworkX Dijkstra on synthetic graph."""
    res_astar = a_star_search(synthetic_multidigraph, 101, 104)
    dijkstra_dist = nx.dijkstra_path_length(
        synthetic_multidigraph, 101, 104, weight="length"
    )
    assert res_astar.total_distance_meters == pytest.approx(dijkstra_dist, 1e-4)


def test_astar_vs_dijkstra_real_network_multiple_pairs(real_graph):
    """Verify optimality of custom A* against NetworkX Dijkstra across real Vermont South routes."""
    test_pairs = [
        ("Library", "School Entrance"),
        ("Bus Stop", "Medical Centre"),
        ("Shopping Centre", "Park Entrance"),
        ("Supermarket", "Community Centre"),
    ]

    for start_name, goal_name in test_pairs:
        start_coord = PROTOTYPE_FIXTURE_COORDINATES[start_name]
        goal_coord = PROTOTYPE_FIXTURE_COORDINATES[goal_name]

        orig_snapped = snap_to_nearest_node(real_graph, start_coord[0], start_coord[1])
        dest_snapped = snap_to_nearest_node(real_graph, goal_coord[0], goal_coord[1])

        # Run custom A*
        res_astar = a_star_search(real_graph, orig_snapped.node_id, dest_snapped.node_id)
        assert res_astar.found is True, f"Failed to find route from {start_name} to {goal_name}"

        # Run NetworkX Dijkstra ground truth
        dijkstra_dist = nx.dijkstra_path_length(
            real_graph, orig_snapped.node_id, dest_snapped.node_id, weight="length"
        )

        # Assert total distances match within 5 centimeters
        diff = abs(res_astar.total_distance_meters - dijkstra_dist)
        assert (
            diff < 0.05
        ), f"Optimality mismatch between {start_name} and {goal_name}: A*={res_astar.total_distance_meters:.2f}m, Dijkstra={dijkstra_dist:.2f}m"

        # Assert edge continuity on real graph
        for i in range(len(res_astar.nodes) - 1):
            u = res_astar.nodes[i]
            v = res_astar.nodes[i + 1]
            assert real_graph.has_edge(u, v)
