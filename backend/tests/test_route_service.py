"""Unit and integration tests for route_between_coordinates and the Route Service."""

import pytest
import networkx as nx

from accessroute.config import PROTOTYPE_FIXTURE_COORDINATES
from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.graph.errors import CoordinateValidationError, RouteRegionTooLargeError
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
)
from accessroute.routing.service import (
    CoordinatedRouteResult,
    route_between_coordinates,
)


@pytest.fixture
def mock_route_manager(tmp_path, synthetic_multidigraph):
    """Provides a DynamicGraphManager backed by synthetic data for rapid isolated tests."""
    provider = SyntheticGraphProvider(template_graph=synthetic_multidigraph)
    cache = RegionalGraphCache(cache_dir=tmp_path)
    elevation_provider = SyntheticElevationProvider(default_elevation=100.0)
    return DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=elevation_provider,
    )


def test_route_between_coordinates_valid(mock_route_manager):
    """Verify end-to-end coordinate routing produces valid route and geographic telemetry."""
    origin = (-37.850, 145.170)
    dest = (-37.850, 145.176)

    result: CoordinatedRouteResult = route_between_coordinates(
        origin=origin,
        destination=dest,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        manager=mock_route_manager,
    )

    assert result.found is True
    assert result.requested_origin == origin
    assert result.requested_destination == dest
    assert result.origin_snap_distance_m >= 0.0
    assert result.destination_snap_distance_m >= 0.0
    assert result.cache_hit is False
    assert result.accessibility_enriched is True
    assert result.terrain_enriched is True
    assert result.total_distance_meters > 0.0
    assert result.total_cost > 0.0
    assert len(result.route.nodes) >= 2


def test_route_between_coordinates_cache_reuse(mock_route_manager):
    """Verify second query in the same vicinity reuses cached regional graph."""
    origin = (-37.850, 145.170)
    dest = (-37.850, 145.176)

    res1 = route_between_coordinates(origin, dest, manager=mock_route_manager)
    assert res1.cache_hit is False

    res2 = route_between_coordinates(origin, dest, manager=mock_route_manager)
    assert res2.cache_hit is True
    assert res2.region_id == res1.region_id


def test_route_identical_coordinates(mock_route_manager):
    """Verify identical origin and destination returns a zero-distance result cleanly."""
    coord = (-37.850, 145.180)
    res = route_between_coordinates(coord, coord, manager=mock_route_manager)

    assert res.found is True
    assert res.total_distance_meters == 0.0
    assert res.total_cost == 0.0
    assert len(res.route.nodes) == 0
    assert any("identical" in exp.lower() for exp in res.explanations)


def test_coordinate_validation_in_route_service(mock_route_manager):
    """Verify invalid coordinates are caught at the service entry point."""
    with pytest.raises(CoordinateValidationError):
        route_between_coordinates((95.0, 145.0), (-37.85, 145.18), manager=mock_route_manager)

    with pytest.raises(CoordinateValidationError):
        route_between_coordinates((-37.85, 145.18), (-37.85, float("nan")), manager=mock_route_manager)


def test_distance_safeguard_in_route_service(mock_route_manager):
    """Verify separation exceeding limit raises RouteRegionTooLargeError."""
    with pytest.raises(RouteRegionTooLargeError):
        route_between_coordinates(
            (-37.85, 145.18),
            (-36.85, 145.18),  # > 100km
            manager=mock_route_manager,
        )


def test_snapping_distance_warning(tmp_path):
    """Verify warning is flagged when query point is distant from any walkable node."""
    # Build isolated graph far from query point
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.18, y=-37.85)
    G.add_node(2, x=145.181, y=-37.85)
    G.add_edge(1, 2, key=0, length=100.0, highway="footway", surface="paved")

    provider = SyntheticGraphProvider(template_graph=G)
    cache = RegionalGraphCache(cache_dir=tmp_path)
    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(),
    )

    # Query point ~300m away from node 1
    far_origin = (-37.853, 145.180)
    close_dest = (-37.850, 145.1805)

    res = route_between_coordinates(
        origin=far_origin,
        destination=close_dest,
        snap_warning_threshold_m=100.0,
        manager=manager,
    )

    assert len(res.snap_warnings) > 0
    assert res.origin_snap_distance_m > 100.0
    assert any("Snapping notice" in exp for exp in res.explanations)


def test_vermont_south_landmarks_regression_via_cached_graph(real_graph, tmp_path):
    """Regression test: verify landmark routing operates seamlessly through DynamicGraphManager."""
    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=real_graph)
    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=100.0),
    )

    # Library -> Shopping Centre in Vermont South
    orig = PROTOTYPE_FIXTURE_COORDINATES["Library"]
    dest = PROTOTYPE_FIXTURE_COORDINATES["Shopping Centre"]

    res = route_between_coordinates(orig, dest, manager=manager)
    assert res.found is True
    assert res.total_distance_meters > 200.0
    assert res.total_distance_meters < 2000.0
    assert len(res.explanations) > 0
