"""Pytest test fixtures for AccessRoute AI test suite."""

import sys
from pathlib import Path
import pytest
import networkx as nx
from shapely.geometry import LineString

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from accessroute.graph.loader import get_pedestrian_graph


@pytest.fixture
def synthetic_multidigraph() -> nx.MultiDiGraph:
    """Create a controlled in-memory MultiDiGraph with parallel edges and an unreachable island.

    Topology:
        Node 101 --- (parallel edges: 150m vs 200m) ---> Node 102 ---> Node 103 ---> Node 104
        Node 199 (Disconnected island node)
    """
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    # Add nodes with geographic coordinates
    G.add_node(101, x=145.1700, y=-37.8500, highway="crossing")
    G.add_node(102, x=145.1720, y=-37.8500, highway="footway")
    G.add_node(103, x=145.1740, y=-37.8500, highway="footway")
    G.add_node(104, x=145.1760, y=-37.8500, highway="crossing")
    G.add_node(199, x=145.1800, y=-37.8600)  # Isolated node

    # Add parallel edges between 101 and 102
    # Longer edge (key 0)
    line_0 = LineString([(145.1700, -37.8500), (145.1710, -37.8510), (145.1720, -37.8500)])
    G.add_edge(101, 102, key=0, length=200.0, highway="footway", geometry=line_0)
    G.add_edge(102, 101, key=0, length=200.0, highway="footway")

    # Shorter direct edge (key 1)
    line_1 = LineString([(145.1700, -37.8500), (145.1720, -37.8500)])
    G.add_edge(101, 102, key=1, length=150.0, highway="path", geometry=line_1)
    G.add_edge(102, 101, key=1, length=150.0, highway="path")

    # Edge between 102 and 103
    G.add_edge(102, 103, key=0, length=180.0, highway="footway")
    G.add_edge(103, 102, key=0, length=180.0, highway="footway")

    # Edge between 103 and 104
    G.add_edge(103, 104, key=0, length=170.0, highway="footway")
    G.add_edge(104, 103, key=0, length=170.0, highway="footway")

    return G


@pytest.fixture(scope="session")
def real_graph() -> nx.MultiDiGraph:
    """Session-scoped fixture loading the real Vermont South pedestrian graph once."""
    return get_pedestrian_graph("vermont_south")
