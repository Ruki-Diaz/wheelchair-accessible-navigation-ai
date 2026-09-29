"""Tests for interactive route elevation profile generation."""

import pytest
import networkx as nx
from shapely.geometry import LineString

from accessroute.routing.elevation_profile import generate_elevation_profile


def test_generate_elevation_profile_synthetic():
    G = nx.MultiDiGraph()
    G.add_node(1, x=144.960, y=-37.810, elevation_m=20.0)
    G.add_node(2, x=144.961, y=-37.810, elevation_m=24.0)
    G.add_node(3, x=144.962, y=-37.810, elevation_m=22.0)

    nodes = [1, 2, 3]
    edges = [
        {"length": 100.0, "geometry": LineString([(144.960, -37.810), (144.961, -37.810)])},
        {"length": 80.0, "geometry": LineString([(144.961, -37.810), (144.962, -37.810)])},
    ]

    summary = generate_elevation_profile(nodes, edges, graph=G)
    assert len(summary.points) == 3
    # Start: dist=0, elev=20.0
    assert summary.points[0].distance_m == 0.0
    assert summary.points[0].elevation_m == 20.0
    # Point 2: dist=100.0, elev=24.0
    assert summary.points[1].distance_m == 100.0
    assert summary.points[1].elevation_m == 24.0
    # Point 3: dist=180.0, elev=22.0
    assert summary.points[2].distance_m == 180.0
    assert summary.points[2].elevation_m == 22.0

    # Vertical climb and descent
    assert summary.elevation_gain_m == 4.0
    assert summary.elevation_loss_m == 2.0
    assert summary.min_elevation_m == 20.0
    assert summary.max_elevation_m == 24.0
    assert summary.max_uphill_grade_pct > 0.0


def test_generate_elevation_profile_empty():
    summary = generate_elevation_profile([], [])
    assert len(summary.points) == 0
    assert summary.elevation_gain_m == 0.0
