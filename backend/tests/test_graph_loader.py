"""Unit and integration tests for graph loading, validation, and caching."""

from pathlib import Path
import pytest
import networkx as nx
import osmnx as ox

from accessroute.graph.loader import (
    get_graph_metadata,
    get_pedestrian_graph,
    validate_graph,
)


def test_validate_graph_success(synthetic_multidigraph):
    """Ensure a valid MultiDiGraph passes validation without errors."""
    validate_graph(synthetic_multidigraph)


def test_validate_graph_not_multidigraph():
    """Ensure simple DiGraph is rejected with TypeError."""
    G = nx.DiGraph()
    G.add_node(1, x=145.0, y=-37.0)
    G.add_edge(1, 1, length=10.0)
    with pytest.raises(TypeError, match="Expected networkx.MultiDiGraph"):
        validate_graph(G)


def test_validate_graph_empty():
    """Ensure empty graph raises ValueError."""
    G = nx.MultiDiGraph()
    with pytest.raises(ValueError, match="empty network"):
        validate_graph(G)


def test_validate_graph_missing_coordinates():
    """Ensure nodes lacking coordinates trigger ValueError."""
    G = nx.MultiDiGraph()
    G.add_node(1)  # Missing x, y
    G.add_node(2, x=145.0, y=-37.0)
    G.add_edge(1, 2, key=0, length=50.0)
    with pytest.raises(ValueError, match="missing spatial coordinates"):
        validate_graph(G)


def test_validate_graph_missing_edge_length():
    """Ensure edges lacking length trigger ValueError."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.0, y=-37.0)
    G.add_node(2, x=145.1, y=-37.0)
    G.add_edge(1, 2, key=0)  # Missing length
    with pytest.raises(ValueError, match="missing required 'length' attribute"):
        validate_graph(G)


def test_cache_save_and_reload(tmp_path, synthetic_multidigraph):
    """Test serializing a graph to GraphML and loading it locally from disk."""
    cache_file = tmp_path / "test_area_walk.graphml"
    ox.save_graphml(synthetic_multidigraph, filepath=cache_file)
    assert cache_file.exists()

    loaded_G = ox.load_graphml(filepath=cache_file)
    validate_graph(loaded_G)

    assert len(loaded_G.nodes) == len(synthetic_multidigraph.nodes)
    assert len(loaded_G.edges) == len(synthetic_multidigraph.edges)


def test_unknown_area_id_raises():
    """Ensure requesting an unconfigured area raises ValueError."""
    with pytest.raises(ValueError, match="Unknown area_id"):
        get_pedestrian_graph("antarctica_south_pole")


def test_real_graph_metadata(real_graph):
    """Verify that the loaded real Vermont South graph contains valid structure and tags."""
    metadata = get_graph_metadata(real_graph)
    assert metadata["graph_type"] == "MultiDiGraph"
    assert metadata["node_count"] > 500, "Expected a substantial pedestrian network"
    assert metadata["edge_count"] > 1000
    assert metadata["bounding_box"]["min_lat"] < -37.80
    assert metadata["bounding_box"]["max_lon"] > 145.10
