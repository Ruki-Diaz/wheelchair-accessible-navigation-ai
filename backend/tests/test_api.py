"""Integration tests for FastAPI endpoints, request validation, and error handlers."""

from unittest.mock import MagicMock, patch
import networkx as nx
from fastapi.testclient import TestClient

from accessroute.api.dependencies import get_geocoder, get_graph_manager
from accessroute.api.main import app
from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.geocoding.base import GeocodeCandidate, GeocoderProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.regional_cache import RegionalGraphCache


class MockGeocoder(GeocoderProvider):
    @property
    def provider_name(self) -> str:
        return "mock_geocoder"

    def search(self, query: str, limit: int = 5, proximity=None, country_code=None):
        if not query.strip():
            return []
        return [
            GeocodeCandidate(
                display_name=f"{query} Test Landmark, Melbourne",
                latitude=-37.8180,
                longitude=144.9671,
                place_type="landmark",
            )
        ]


def get_mock_manager(tmp_path):
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.8180, x=144.9670)
    G.add_node(2, y=-37.8180, x=144.9690)
    G.add_edge(1, 2, 0, length=120.0, highway="footway", surface="asphalt")

    cache = RegionalGraphCache(cache_dir=tmp_path)
    provider = SyntheticGraphProvider(template_graph=G)
    return DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=30.0),
    )


def test_api_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "accessroute-ai"
    assert "routing_engine" in data


def test_api_geocoding_search_endpoint():
    app.dependency_overrides[get_geocoder] = lambda: MockGeocoder()
    try:
        client = TestClient(app)
        response = client.get("/api/v1/geocode/search", params={"q": "Flinders"})
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "Flinders"
        assert data["count"] == 1
        assert "Flinders Test Landmark" in data["candidates"][0]["display_name"]
    finally:
        app.dependency_overrides.clear()


def test_api_route_plan_valid(tmp_path):
    mock_mgr = get_mock_manager(tmp_path)
    app.dependency_overrides[get_graph_manager] = lambda: mock_mgr
    try:
        client = TestClient(app)
        payload = {
            "origin": {"latitude": -37.8180, "longitude": 144.9670},
            "destination": {"latitude": -37.8180, "longitude": 144.9690},
            "policy": "balanced",
            "enrich_elevation": True,
            "compare_baseline": True,
        }
        response = client.post("/api/v1/routes/plan", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["policy"] == "balanced"
        assert data["metrics"]["physical_distance_m"] > 0.0
        assert "geojson" in data
        assert data["geojson"]["type"] == "FeatureCollection"
    finally:
        app.dependency_overrides.clear()


def test_api_route_plan_unsupported_policy(tmp_path):
    mock_mgr = get_mock_manager(tmp_path)
    app.dependency_overrides[get_graph_manager] = lambda: mock_mgr
    try:
        client = TestClient(app)
        payload = {
            "origin": {"latitude": -37.8180, "longitude": 144.9670},
            "destination": {"latitude": -37.8180, "longitude": 144.9690},
            "policy": "super_fast_invalid",
        }
        response = client.post("/api/v1/routes/plan", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_api_route_plan_invalid_coordinates():
    client = TestClient(app)
    payload = {
        "origin": {"latitude": 195.0, "longitude": 144.9670},  # latitude > 90 invalid
        "destination": {"latitude": -37.8180, "longitude": 144.9690},
    }
    response = client.post("/api/v1/routes/plan", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "error_code" in data or "detail" in data


def test_api_route_plan_region_too_large():
    client = TestClient(app)
    # 500 km separation (exceeds 10km operational limit)
    payload = {
        "origin": {"latitude": -37.8180, "longitude": 144.9670},
        "destination": {"latitude": -33.8688, "longitude": 151.2093},
    }
    response = client.post("/api/v1/routes/plan", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data.get("error_code") == "REGION_TOO_LARGE"


def test_api_cors_preflight_headers():
    client = TestClient(app)
    response = client.options(
        "/api/v1/routes/plan",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_api_serves_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "AccessRoute AI" in response.text
