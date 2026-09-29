"""Tests for Stage 7 API endpoints, route alternatives, and GeoJSON serialization."""

import pytest
from fastapi.testclient import TestClient

from accessroute.api.dependencies import get_graph_manager, get_regional_cache
from accessroute.api.main import app
from accessroute.graph.region import BoundingBox
from tests.test_route_alternatives import MockAlternativesGraphManager, build_alternatives_test_graph


class DummyCache:
    def load_graph(self, region_id):
        return None, None


@pytest.fixture
def client_with_mock_graph():
    G = build_alternatives_test_graph()
    mock_mgr = MockAlternativesGraphManager(G)
    dummy_cache = DummyCache()

    app.dependency_overrides[get_graph_manager] = lambda: mock_mgr
    app.dependency_overrides[get_regional_cache] = lambda: dummy_cache

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


def test_api_route_alternatives_endpoint(client_with_mock_graph):
    payload = {
        "origin": {"latitude": -37.810, "longitude": 144.960},
        "destination": {"latitude": -37.810, "longitude": 144.962},
        "enrich_elevation": True,
        "allow_expansion": False,
    }

    response = client_with_mock_graph.post("/api/v1/routes/alternatives", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["found"] is True
    assert "alternatives" in data
    assert len(data["alternatives"]) >= 1

    first_alt = data["alternatives"][0]
    assert "key" in first_alt
    assert "title" in first_alt
    assert "badge" in first_alt
    assert "estimated_duration_min" in first_alt
    assert "directions" in first_alt
    assert "elevation_summary" in first_alt

    # Check GeoJSON
    geojson = data["geojson"]
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0

    # Ensure alternatives features are present in GeoJSON
    alt_features = [f for f in geojson["features"] if f["properties"].get("feature_type") == "route_alternative"]
    assert len(alt_features) >= 1


def test_api_route_alternatives_invalid_coords(client_with_mock_graph):
    payload = {
        "origin": {"latitude": 95.0, "longitude": 144.960},  # Invalid lat > 90
        "destination": {"latitude": -37.810, "longitude": 144.962},
    }
    response = client_with_mock_graph.post("/api/v1/routes/alternatives", json=payload)
    assert response.status_code in (400, 422)
