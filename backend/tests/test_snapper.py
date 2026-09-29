"""Unit and integration tests for spatial coordinate snapping."""

import pytest
import networkx as nx

from accessroute.config import PROTOTYPE_FIXTURE_COORDINATES
from accessroute.graph.snapper import snap_to_nearest_node, SnappedNode


def test_snap_to_nearest_node_synthetic(synthetic_multidigraph):
    """Test snapping an exact coordinate and an offset coordinate on synthetic graph."""
    # Query exact coordinates of Node 101: (-37.8500, 145.1700)
    snapped = snap_to_nearest_node(synthetic_multidigraph, -37.8500, 145.1700)
    assert isinstance(snapped, SnappedNode)
    assert snapped.node_id == 101
    assert snapped.distance_meters < 0.1

    # Query offset coordinate slightly south of Node 102: (-37.8502, 145.1720)
    offset_snapped = snap_to_nearest_node(synthetic_multidigraph, -37.8502, 145.1720)
    assert offset_snapped.node_id == 102
    assert 10.0 < offset_snapped.distance_meters < 30.0


def test_snap_empty_graph_raises():
    """Ensure snapping on an empty graph raises ValueError."""
    empty_g = nx.MultiDiGraph()
    with pytest.raises(ValueError, match="Cannot snap coordinate to an empty graph"):
        snap_to_nearest_node(empty_g, -37.8570, 145.1740)


def test_snap_real_vermont_south_landmarks(real_graph):
    """Test that key prototype fixture landmarks snap cleanly to real OSM footpaths."""
    # Test a set of representative landmarks from the original project
    test_landmarks = [
        ("Library", PROTOTYPE_FIXTURE_COORDINATES["Library"]),
        ("Shopping Centre", PROTOTYPE_FIXTURE_COORDINATES["Shopping Centre"]),
        ("Bus Stop", PROTOTYPE_FIXTURE_COORDINATES["Bus Stop"]),
        ("Supermarket", PROTOTYPE_FIXTURE_COORDINATES["Supermarket"]),
        ("School Entrance", PROTOTYPE_FIXTURE_COORDINATES["School Entrance"]),
    ]

    for name, (lat, lon) in test_landmarks:
        snapped = snap_to_nearest_node(real_graph, lat, lon)
        assert snapped.node_id in real_graph.nodes, f"Node {snapped.node_id} for {name} not in graph"
        # Since prototype coordinates were hand-placed approximations on Google Maps,
        # verify they snap to an actual pedestrian network feature within a sensible tolerance (e.g. < 150m)
        assert (
            snapped.distance_meters < 150.0
        ), f"Landmark {name} snapped unusually far ({snapped.distance_meters:.1f}m)"
        assert snapped.latitude is not None
        assert snapped.longitude is not None
