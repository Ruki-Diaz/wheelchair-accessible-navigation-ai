"""Unit tests for regional boundary expansion and false-negative mitigation."""

import networkx as nx
import pytest

from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.region import BoundingBox, RouteRegionTooLargeError
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.routing.policy import BALANCED_ACCESSIBILITY_POLICY, RoutingPolicy
from accessroute.routing.service import route_between_coordinates


def test_bounding_box_expand_method():
    bbox = BoundingBox(south=-37.82, west=144.96, north=-37.81, east=144.97)
    initial_area = bbox.area_km2

    expanded = bbox.expand(factor=1.5, min_expansion_m=300.0)
    assert expanded.south < bbox.south
    assert expanded.north > bbox.north
    assert expanded.west < bbox.west
    assert expanded.east > bbox.east
    assert expanded.area_km2 > initial_area


def test_bounding_box_expand_safeguard():
    bbox = BoundingBox(south=-37.82, west=144.96, north=-37.81, east=144.97)
    with pytest.raises(RouteRegionTooLargeError):
        # Exceeds max area limit
        bbox.expand(factor=50.0, max_area_km2=5.0)


def test_controlled_regional_expansion_on_disconnected_initial_box(tmp_path):
    """Test that if an initial small graph has no accessible route, expansion is attempted."""
    # Build a synthetic graph with 2 nodes disconnected by stairs, but an accessible detour exists
    # Node 1 -> Node 2 (stairs, prohibited)
    # Node 1 -> Node 3 -> Node 2 (accessible ramp detour)
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.8180, x=144.9670)
    G.add_node(2, y=-37.8180, x=144.9690)
    G.add_node(3, y=-37.8140, x=144.9680)  # detour node located further out

    # Prohibited direct path with steps
    G.add_edge(1, 2, 0, length=100.0, highway="steps", has_ramp=False, has_wheelchair_ramp=False)

    # Accessible detour
    G.add_edge(1, 3, 0, length=200.0, highway="footway", surface="asphalt")
    G.add_edge(3, 2, 0, length=200.0, highway="footway", surface="asphalt")

    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=G)
    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=50.0),
    )

    orig = (-37.8180, 144.9670)
    dest = (-37.8180, 144.9690)

    res = route_between_coordinates(
        origin=orig,
        destination=dest,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        manager=manager,
        allow_expansion=True,
        max_expansion_attempts=2,
    )

    assert res.found is True
    assert res.total_distance_meters > 0.0


def test_no_route_found_within_searched_area_wording(tmp_path):
    """If no route is found, verify explanation does not claim no real-world route exists."""
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.8180, x=144.9670)
    G.add_node(2, y=-37.8180, x=144.9690)
    # Only a prohibited steps edge
    G.add_edge(1, 2, 0, length=100.0, highway="steps", has_ramp=False, has_wheelchair_ramp=False)

    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=G)
    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=50.0),
    )

    orig = (-37.8180, 144.9670)
    dest = (-37.8180, 144.9690)

    res = route_between_coordinates(
        origin=orig,
        destination=dest,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        manager=manager,
        allow_expansion=True,
        max_expansion_attempts=2,
    )

    assert res.found is False
    assert res.expansion_attempts == 2
    # Check honest, bounded explanation wording
    assert any("found within the searched area" in exp for exp in res.explanations)
    assert not any("no accessible real-world route exists" in exp.lower() for exp in res.explanations)
