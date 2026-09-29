"""Unit tests for Stage 5 dynamic graph acquisition, bounding regions, and spatial caching."""

import json
from pathlib import Path
import pytest
import networkx as nx

from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.graph.errors import (
    CacheCorruptionError,
    CoordinateValidationError,
    NoPedestrianNetworkError,
    RouteRegionTooLargeError,
)
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.region import (
    BoundingBox,
    validate_coordinates,
)
from accessroute.graph.regional_cache import (
    CURRENT_ACCESSIBILITY_VERSION,
    CURRENT_TERRAIN_VERSION,
    RegionMetadata,
    RegionalGraphCache,
)


def test_coordinate_validation_valid():
    """Verify standard coordinates pass validation without error."""
    validate_coordinates(-37.85, 145.18, "origin")
    validate_coordinates(51.5074, -0.1278, "london")
    validate_coordinates(6.9271, 79.8612, "colombo")


def test_coordinate_validation_invalid_range():
    """Verify latitude and longitude range boundaries are strictly enforced."""
    with pytest.raises(CoordinateValidationError, match="latitude 95.0 is out of valid bounds"):
        validate_coordinates(95.0, 145.0)

    with pytest.raises(CoordinateValidationError, match="latitude -90.1 is out of valid bounds"):
        validate_coordinates(-90.1, 0.0)

    with pytest.raises(CoordinateValidationError, match="longitude 185.0 is out of valid bounds"):
        validate_coordinates(0.0, 185.0)

    with pytest.raises(CoordinateValidationError, match="longitude -180.1 is out of valid bounds"):
        validate_coordinates(0.0, -180.1)


def test_coordinate_validation_nan_and_inf():
    """Verify NaN and infinity values are rejected."""
    with pytest.raises(CoordinateValidationError, match="NaN"):
        validate_coordinates(float("nan"), 145.0)

    with pytest.raises(CoordinateValidationError, match="infinite"):
        validate_coordinates(0.0, float("inf"))


def test_bounding_box_creation_and_buffering():
    """Verify BoundingBox accurately encloses endpoints with adaptive padding."""
    origin = (-37.850, 145.180)
    dest = (-37.855, 145.190)

    bbox = BoundingBox.from_coordinates(origin, dest, buffer_meters=300.0)

    # Must contain both endpoints strictly inside
    assert bbox.contains_point(origin[0], origin[1])
    assert bbox.contains_point(dest[0], dest[1])

    # Must have a positive physical area
    assert bbox.area_km2 > 0.1
    assert bbox.south < min(origin[0], dest[0])
    assert bbox.north > max(origin[0], dest[0])
    assert bbox.west < min(origin[1], dest[1])
    assert bbox.east > max(origin[1], dest[1])


def test_bounding_box_safeguards_exceeded():
    """Verify operational safeguards reject overly large separation or area."""
    origin = (-37.85, 145.18)
    far_dest = (-36.85, 145.18)  # ~111 km separation

    with pytest.raises(RouteRegionTooLargeError, match="operational development limit"):
        BoundingBox.from_coordinates(origin, far_dest, max_distance_meters=5000.0)


def test_bounding_box_containment():
    """Verify spatial containment logic for sub-boxes."""
    parent = BoundingBox(south=-37.86, west=145.17, north=-37.84, east=145.20)
    child = BoundingBox(south=-37.855, west=145.18, north=-37.845, east=145.19)
    disjoint = BoundingBox(south=-37.80, west=145.10, north=-37.79, east=145.12)
    overlapping_partial = BoundingBox(south=-37.87, west=145.18, north=-37.85, east=145.19)

    assert parent.contains_box(child) is True
    assert child.contains_box(parent) is False
    assert parent.contains_box(disjoint) is False
    # Partial overlap must NOT be considered full coverage
    assert parent.contains_box(overlapping_partial) is False


def test_synthetic_graph_provider(synthetic_multidigraph):
    """Verify SyntheticGraphProvider produces a valid MultiDiGraph."""
    provider = SyntheticGraphProvider(template_graph=synthetic_multidigraph)
    bbox = BoundingBox(south=-37.855, west=145.18, north=-37.845, east=145.19)
    G = provider.get_pedestrian_network(bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert len(G.nodes) > 0
    assert G.number_of_edges() > 0


def test_regional_cache_save_and_spatial_reuse(tmp_path):
    """Verify saving a graph, finding it via spatial containment, and loading it."""
    cache = RegionalGraphCache(cache_dir=tmp_path)
    parent_bbox = BoundingBox(south=-37.86, west=145.17, north=-37.84, east=145.20)
    meta = RegionMetadata(
        region_id="reg_test_001",
        bbox=parent_bbox,
        created_at="2026-09-24T12:00:00Z",
        node_count=2,
        edge_count=2,
        osm_loaded=True,
        accessibility_enriched=True,
        terrain_enriched=True,
    )

    # Create dummy graph
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.18, y=-37.85)
    G.add_node(2, x=145.19, y=-37.85)
    G.add_edge(1, 2, key=0, length=100.0, highway="footway", surface="paved")
    G.add_edge(2, 1, key=0, length=100.0, highway="footway", surface="paved")

    cache.save_graph(G, meta)

    # 1. Exact or smaller query box should HIT the cache
    query_child = BoundingBox(south=-37.855, west=145.18, north=-37.845, east=145.19)
    hit = cache.find_covering_region(query_child, require_terrain=True)
    assert hit is not None
    region_id, loaded_meta = hit
    assert region_id == "reg_test_001"
    assert loaded_meta.node_count == 2

    # 2. Outside query box should MISS
    query_outside = BoundingBox(south=-37.80, west=145.10, north=-37.79, east=145.12)
    miss = cache.find_covering_region(query_outside)
    assert miss is None

    # 3. Load graph from cache
    loaded_G, loaded_meta2 = cache.load_graph(region_id)
    assert len(loaded_G.nodes) == 2
    assert loaded_G.number_of_edges() == 2


def test_regional_cache_version_invalidation(tmp_path):
    """Verify that cached graphs with stale model versions are bypassed."""
    cache = RegionalGraphCache(cache_dir=tmp_path)
    bbox = BoundingBox(south=-37.86, west=145.17, north=-37.84, east=145.20)
    stale_meta = RegionMetadata(
        region_id="reg_stale",
        bbox=bbox,
        created_at="2026-01-01T00:00:00Z",
        node_count=4,
        edge_count=4,
        accessibility_model_version="1.0",  # Stale version
        terrain_enriched=False,
    )

    G = nx.MultiDiGraph()
    G.add_node(1, x=145.18, y=-37.85)
    G.add_node(2, x=145.19, y=-37.85)
    G.add_edge(1, 2, key=0, length=100.0, highway="footway")
    cache.save_graph(G, stale_meta)

    # When querying with default current version (2.0), the stale region must be rejected
    hit = cache.find_covering_region(bbox, min_accessibility_version="2.0")
    assert hit is None


def test_corrupted_cache_handling(tmp_path):
    """Verify CacheCorruptionError is raised when graph or metadata is unreadable."""
    cache = RegionalGraphCache(cache_dir=tmp_path)
    bad_meta_path = tmp_path / "reg_bad.json"
    bad_meta_path.write_text("invalid json content {{{", encoding="utf-8")
    (tmp_path / "reg_bad.graphml").write_text("<xml>corrupted</xml>", encoding="utf-8")

    with pytest.raises(CacheCorruptionError):
        cache.load_graph("reg_bad")


def test_dynamic_graph_manager_cold_vs_warm(tmp_path, synthetic_multidigraph):
    """Verify DynamicGraphManager executes cold acquisition then reuses cached region."""
    provider = SyntheticGraphProvider(template_graph=synthetic_multidigraph)
    cache = RegionalGraphCache(cache_dir=tmp_path)
    elev_provider = SyntheticElevationProvider(default_elevation=100.0)

    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=elev_provider,
    )

    origin = (-37.850, 145.170)
    dest = (-37.850, 145.176)

    # 1. Cold request -> cache miss
    g_cold, meta_cold, hit_cold = manager.get_graph_for_route(
        origin, dest, enrich_elevation=True
    )
    assert hit_cold is False
    assert meta_cold.accessibility_enriched is True
    assert meta_cold.terrain_enriched is True
    assert len(g_cold.nodes) > 0

    # 2. Warm request (identical coordinates) -> cache hit
    g_warm, meta_warm, hit_warm = manager.get_graph_for_route(
        origin, dest, enrich_elevation=True
    )
    assert hit_warm is True
    assert meta_warm.region_id == meta_cold.region_id

    # 3. Warm request (smaller sub-region inside buffer) -> cache hit
    sub_orig = (-37.850, 145.172)
    sub_dest = (-37.850, 145.174)
    g_sub, meta_sub, hit_sub = manager.get_graph_for_route(
        sub_orig, sub_dest, enrich_elevation=True
    )
    assert hit_sub is True
    assert meta_sub.region_id == meta_cold.region_id


def test_dynamic_manager_elevation_failure_fallback(tmp_path, synthetic_multidigraph):
    """Verify graph acquisition succeeds gracefully with UNKNOWN elevation if elevation fails."""
    provider = SyntheticGraphProvider(template_graph=synthetic_multidigraph)
    cache = RegionalGraphCache(cache_dir=tmp_path)

    # Provider that raises an error
    class BrokenElevationProvider:
        @property
        def source_name(self):
            return "broken"
        @property
        def resolution_meters(self):
            return 30.0
        def get_elevation(self, lat, lon):
            raise ConnectionError("Service unreachable")
        def get_elevations(self, coords):
            raise ConnectionError("Service unreachable")

    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=BrokenElevationProvider(),
    )

    origin = (-37.850, 145.170)
    dest = (-37.850, 145.176)

    G, meta, hit = manager.get_graph_for_route(origin, dest, enrich_elevation=True)
    assert hit is False
    assert meta.accessibility_enriched is True
    # Should fall back to terrain_enriched = False without raising an exception
    assert meta.terrain_enriched is False
    assert len(G.nodes) > 0
