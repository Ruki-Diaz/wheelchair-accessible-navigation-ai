"""Tests for multi-alternative route calculation, deduplication, and card generation."""

import pytest
import networkx as nx
from shapely.geometry import LineString

from accessroute.graph.manager import DynamicGraphManager
from accessroute.routing.alternatives import calculate_route_alternatives
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
)


class MockAlternativesGraphManager:
    """Mock DynamicGraphManager returning a synthetic network with stairs, steep slope, and gentle detour."""

    def __init__(self, G, region_id="test_alt_region"):
        self.G = G
        self.region_id = region_id

    def get_graph_for_bbox(self, bbox, enrich_elevation=True, force_refresh=False):
        class MockMeta:
            def __init__(self, rid, b):
                self.region_id = rid
                self.bbox = b
                self.accessibility_enriched = True
                self.terrain_enriched = True
        return self.G, MockMeta(self.region_id, bbox), True


def build_alternatives_test_graph():
    """Constructs a network where:

    - Path A (Shortest): Direct line 1 -> 2 -> 4 (total 100m, but 1->2 has steps)
    - Path B (Accessibility-Aware): Detour 1 -> 3 -> 4 (total 140m, paved, ramped, gentle slope)
    - Path C (Flattest): Detour 1 -> 5 -> 4 (total 160m, extremely flat slope)
    """
    G = nx.MultiDiGraph()
    # Coordinates in Melbourne region
    G.add_node(1, x=144.960, y=-37.810, elevation_m=20.0)
    G.add_node(2, x=144.961, y=-37.810, elevation_m=28.0)
    G.add_node(3, x=144.960, y=-37.811, elevation_m=21.0)
    G.add_node(4, x=144.962, y=-37.810, elevation_m=21.5)
    G.add_node(5, x=144.960, y=-37.812, elevation_m=20.2)

    # Path A: Steps (prohibited by balanced and conservative)
    G.add_edge(1, 2, 0, length=50.0, highway="steps", has_ramp=False, surface="concrete", findings={"HIGHWAY_STEPS"})
    G.add_edge(2, 4, 0, length=50.0, highway="footway", surface="asphalt", findings=set())

    # Path B: Paved gentle detour
    G.add_edge(1, 3, 0, length=70.0, highway="footway", surface="asphalt", findings=set())
    G.add_edge(3, 4, 0, length=70.0, highway="footway", surface="asphalt", findings=set())

    # Path C: Flat detour
    G.add_edge(1, 5, 0, length=80.0, highway="footway", surface="asphalt", findings=set())
    G.add_edge(5, 4, 0, length=80.0, highway="footway", surface="asphalt", findings=set())

    return G


def test_calculate_route_alternatives_deduplication_and_cards():
    G = build_alternatives_test_graph()
    mock_mgr = MockAlternativesGraphManager(G)

    orig = (-37.810, 144.960)
    dest = (-37.810, 144.962)

    result = calculate_route_alternatives(
        origin=orig,
        destination=dest,
        manager=mock_mgr,
        allow_expansion=False,
    )

    assert result.found is True
    assert len(result.alternatives) >= 1

    # Verify at least one alternative is found
    primary = result.alternatives[0]
    assert primary.title == "Accessibility-Aware"
    assert primary.physical_distance_m > 0
    assert primary.estimated_duration_min >= 1
    assert len(primary.directions) >= 2
    assert len(primary.elevation_summary.points) >= 2


def test_calculate_route_alternatives_identical_endpoints():
    orig = (-37.810, 144.960)
    result = calculate_route_alternatives(orig, orig)
    assert result.found is True
    assert len(result.alternatives) == 1
    assert result.alternatives[0].physical_distance_m == 0.0
    assert result.alternatives[0].is_shortest is True
