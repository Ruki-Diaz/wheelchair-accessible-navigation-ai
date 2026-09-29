"""Unit tests for GeoJSON serialization and segment evidence features."""

import networkx as nx

from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.routing.geojson import route_result_to_geojson
from accessroute.routing.policy import BALANCED_ACCESSIBILITY_POLICY
from accessroute.routing.service import route_between_coordinates


def test_route_result_to_geojson_valid_structure(tmp_path):
    # Construct a 3-node linear graph
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.8180, x=144.9670)
    G.add_node(2, y=-37.8180, x=144.9680)
    G.add_node(3, y=-37.8180, x=144.9690)
    G.add_edge(1, 2, 0, length=50.0, highway="footway", surface="concrete", wheelchair="yes")
    G.add_edge(2, 3, 0, length=50.0, highway="footway", surface="asphalt", kerb="lowered")

    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=G)
    manager = DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=25.0),
    )

    res = route_between_coordinates(
        origin=(-37.8180, 144.9670),
        destination=(-37.8180, 144.9690),
        policy=BALANCED_ACCESSIBILITY_POLICY,
        manager=manager,
    )

    geojson_data = route_result_to_geojson(res, graph=G, include_segments=True, include_baseline=True)

    assert geojson_data["type"] == "FeatureCollection"
    assert "features" in geojson_data
    features = geojson_data["features"]

    # Verify presence of key feature types
    types = [f["properties"]["feature_type"] for f in features]
    assert "requested_origin" in types
    assert "requested_destination" in types
    assert "snapped_origin" in types
    assert "snapped_destination" in types
    assert "accessible_route" in types
    assert "baseline_route" in types
    assert "route_segment" in types

    # Inspect segment-level properties for evidence inspector
    segment_features = [f for f in features if f["properties"]["feature_type"] == "route_segment"]
    assert len(segment_features) == 2
    first_seg = segment_features[0]["properties"]
    assert first_seg["surface"] == "concrete"
    assert first_seg["wheelchair"] == "yes"
    assert "source" in first_seg


def test_geojson_unfound_route(tmp_path):
    # Empty disconnected endpoints
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.8180, x=144.9670)
    G.add_node(2, y=-37.8180, x=144.9690)

    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=G)
    manager = DynamicGraphManager(provider=provider, cache=cache)

    res = route_between_coordinates(
        origin=(-37.8180, 144.9670),
        destination=(-37.8180, 144.9690),
        manager=manager,
        allow_expansion=False,
    )

    geojson_data = route_result_to_geojson(res, graph=G)
    assert geojson_data["type"] == "FeatureCollection"
    assert geojson_data["properties"]["route_found"] is False
    # Still contains origin and destination points for mapping
    assert len(geojson_data["features"]) == 4
