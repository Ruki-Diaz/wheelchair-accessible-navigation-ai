"""Production routing reliability: prebuilt regional graphs, single-flight
acquisition, bounded Overpass fallback and infrastructure error reporting."""

import threading
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest
import requests.exceptions as req_exc
from fastapi.testclient import TestClient

from accessroute.api.dependencies import get_graph_manager, get_regional_cache
from accessroute.api.main import app
from accessroute.config import DEFAULT_PREBUILT_REGIONS_DIR
from accessroute.graph.errors import NetworkDownloadError
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import GraphProvider, OpenStreetMapGraphProvider, SyntheticGraphProvider
from accessroute.graph.region import BoundingBox
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.routing.alternatives import calculate_route_alternatives

WESTFIELD_DONCASTER = (-37.7846012, 145.1264394)
ROSEVILLE_AVENUE = (-37.7832759, 145.129016)

# Somewhere no prebuilt region covers (Sydney CBD).
UNCOVERED_BBOX = BoundingBox(south=-33.8700, west=151.2050, north=-33.8650, east=151.2110)


class _NoElevation:
    """Elevation provider that must never be reached on a prebuilt hit."""

    def get_elevations(self, *args, **kwargs):  # pragma: no cover - asserted unused
        raise AssertionError("elevation provider called on prebuilt graph hit")


@pytest.fixture()
def prebuilt_cache(tmp_path) -> RegionalGraphCache:
    """Empty writable cache (like a fresh Render instance) + the bundled prebuilt regions."""
    return RegionalGraphCache(cache_dir=tmp_path / "regions", prebuilt_dirs=[DEFAULT_PREBUILT_REGIONS_DIR])


@pytest.fixture()
def overpass_forbidden():
    """Fail loudly if anything reaches Overpass through OSMnx."""
    with patch("osmnx.graph_from_bbox", side_effect=AssertionError("Overpass request attempted")) as mocked:
        yield mocked


def _prod_manager(cache: RegionalGraphCache) -> DynamicGraphManager:
    return DynamicGraphManager(
        provider=OpenStreetMapGraphProvider(endpoints=["https://overpass.example/api"]),
        cache=cache,
        elevation_provider=_NoElevation(),
    )


# ---------------------------------------------------------------------------
# Prebuilt graph lookup
# ---------------------------------------------------------------------------

def test_bundled_prebuilt_regions_present_and_enriched():
    cache = RegionalGraphCache(cache_dir=DEFAULT_PREBUILT_REGIONS_DIR, prebuilt_dirs=[])
    regions = {m.region_id: m for m in cache.list_regions()}
    assert {"reg_561da3e035ef", "reg_549b69abe250"} <= set(regions)
    for meta in regions.values():
        assert meta.accessibility_enriched and meta.terrain_enriched


def test_doncaster_route_uses_prebuilt_graph_with_zero_overpass_requests(prebuilt_cache, overpass_forbidden):
    result = calculate_route_alternatives(
        origin=WESTFIELD_DONCASTER,
        destination=ROSEVILLE_AVENUE,
        manager=_prod_manager(prebuilt_cache),
    )

    assert overpass_forbidden.call_count == 0
    assert result.cache_hit is True
    assert result.region_id == "reg_561da3e035ef"
    assert result.alternatives, "expected at least one accessible route"
    # Nothing was written: the route came entirely from bundled data.
    assert list(prebuilt_cache.cache_dir.glob("*.graphml")) == []


def test_prebuilt_hit_bypasses_provider(prebuilt_cache):
    class _ExplodingProvider(GraphProvider):
        provider_name = "exploding"

        def get_pedestrian_network(self, bbox):
            raise AssertionError("provider must not be called on prebuilt hit")

    manager = DynamicGraphManager(provider=_ExplodingProvider(), cache=prebuilt_cache, elevation_provider=_NoElevation())
    bbox = BoundingBox.from_coordinates(WESTFIELD_DONCASTER, ROSEVILLE_AVENUE)
    G, meta, cache_hit = manager.get_graph_for_bbox(bbox)

    assert cache_hit is True
    assert prebuilt_cache.is_prebuilt(meta.region_id)
    assert len(G) > 100


def test_prebuilt_dirs_not_used_for_explicit_cache_dir(tmp_path):
    cache = RegionalGraphCache(cache_dir=tmp_path)
    assert cache.prebuilt_dirs == []
    bbox = BoundingBox.from_coordinates(WESTFIELD_DONCASTER, ROSEVILLE_AVENUE)
    assert cache.find_covering_region(bbox) is None


def test_clear_cache_never_touches_prebuilt(prebuilt_cache):
    prebuilt_cache.clear_cache()
    assert (DEFAULT_PREBUILT_REGIONS_DIR / "reg_561da3e035ef.graphml").exists()


# ---------------------------------------------------------------------------
# Bounded Overpass fallback for missing regions
# ---------------------------------------------------------------------------

def test_missing_region_invokes_overpass_fallback(prebuilt_cache, synthetic_multidigraph):
    manager = _prod_manager(prebuilt_cache)
    with patch("osmnx.graph_from_bbox", return_value=synthetic_multidigraph) as mocked:
        _, _, cache_hit = manager.get_graph_for_bbox(UNCOVERED_BBOX, enrich_elevation=False)
    assert mocked.call_count == 1
    assert cache_hit is False


def test_overpass_total_budget_skips_remaining_endpoints(small_fake_clock):
    provider = OpenStreetMapGraphProvider(
        endpoints=["https://a.example/api", "https://b.example/api", "https://c.example/api"],
        timeout_seconds=15,
        total_budget_seconds=20,
    )
    import osmnx as ox

    timeouts_used = []

    def slow_timeout(*args, **kwargs):
        timeouts_used.append(ox.settings.requests_timeout)
        small_fake_clock.advance(ox.settings.requests_timeout)
        raise req_exc.ReadTimeout("read timed out")

    with patch("osmnx.graph_from_bbox", side_effect=slow_timeout):
        with pytest.raises(NetworkDownloadError, match="budget exhausted after 2/3"):
            provider.get_pedestrian_network(UNCOVERED_BBOX)

    # First attempt gets the full per-endpoint timeout, second only what's left.
    assert timeouts_used == [15, 5]
    assert small_fake_clock.now <= 20


def test_overpass_per_endpoint_timeout_never_exceeds_60s():
    from accessroute import config

    assert config.OVERPASS_TIMEOUT_SECONDS <= 60
    assert config.OVERPASS_TOTAL_BUDGET_SECONDS < 25  # UI aborts route search at 25 s


@pytest.fixture()
def small_fake_clock():
    class _Clock:
        now = 0.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = _Clock()
    with patch("accessroute.graph.provider.time.monotonic", clock):
        yield clock


# ---------------------------------------------------------------------------
# Single-flight acquisition
# ---------------------------------------------------------------------------

class _BlockingProvider(GraphProvider):
    """Provider that blocks until released, counting calls."""

    provider_name = "blocking:test"

    def __init__(self, fail: bool = False):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._fail = fail

    def get_pedestrian_network(self, bbox):
        self.calls += 1
        self.started.set()
        assert self.release.wait(5)
        if self._fail:
            raise NetworkDownloadError("All 3 Overpass endpoint(s) failed")
        return SyntheticGraphProvider().get_pedestrian_network(bbox)


def _run_concurrently(manager, bbox, provider, n=3):
    results, errors = [], []

    def worker():
        try:
            results.append(manager.get_graph_for_bbox(bbox, enrich_elevation=False))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=worker)
    first.start()
    assert provider.started.wait(5)
    others = [threading.Thread(target=worker) for _ in range(n - 1)]
    for t in others:
        t.start()
    # Give followers time to reach the single-flight wait before the leader finishes.
    threading.Event().wait(0.2)
    provider.release.set()
    for t in [first, *others]:
        t.join(10)
    return results, errors


def test_duplicate_same_region_requests_share_one_download(tmp_path):
    provider = _BlockingProvider()
    manager = DynamicGraphManager(provider=provider, cache=RegionalGraphCache(cache_dir=tmp_path), elevation_provider=None)

    results, errors = _run_concurrently(manager, UNCOVERED_BBOX, provider, n=3)

    assert errors == []
    assert provider.calls == 1
    assert len(results) == 3
    # Every request gets its own graph object (routing mutates graphs).
    assert len({id(G) for G, _, _ in results}) == 3


def test_contained_region_request_waits_for_inflight_acquisition(tmp_path):
    provider = _BlockingProvider()
    manager = DynamicGraphManager(provider=provider, cache=RegionalGraphCache(cache_dir=tmp_path), elevation_provider=None)
    inner = BoundingBox(south=-33.8690, west=151.2060, north=-33.8660, east=151.2100)

    result, errors = [], []
    leader = threading.Thread(target=lambda: result.append(manager.get_graph_for_bbox(UNCOVERED_BBOX, enrich_elevation=False)))
    leader.start()
    assert provider.started.wait(5)
    follower = threading.Thread(target=lambda: result.append(manager.get_graph_for_bbox(inner, enrich_elevation=False)))
    follower.start()
    threading.Event().wait(0.2)
    provider.release.set()
    leader.join(10)
    follower.join(10)

    assert provider.calls == 1
    assert len(result) == 2


def test_inflight_failure_propagates_without_second_download(tmp_path):
    provider = _BlockingProvider(fail=True)
    manager = DynamicGraphManager(provider=provider, cache=RegionalGraphCache(cache_dir=tmp_path), elevation_provider=None)

    results, errors = _run_concurrently(manager, UNCOVERED_BBOX, provider, n=2)

    assert results == []
    assert len(errors) == 2
    assert all(isinstance(e, NetworkDownloadError) for e in errors)
    assert provider.calls == 1
    # Registry is cleared so a later retry can attempt acquisition again.
    assert manager._inflight == {}


# ---------------------------------------------------------------------------
# API error semantics
# ---------------------------------------------------------------------------

def test_infrastructure_failure_returns_502_not_no_route(tmp_path):
    manager = DynamicGraphManager(
        provider=OpenStreetMapGraphProvider(endpoints=["https://overpass.example/api"]),
        cache=RegionalGraphCache(cache_dir=tmp_path),
        elevation_provider=None,
    )
    app.dependency_overrides[get_graph_manager] = lambda: manager
    app.dependency_overrides[get_regional_cache] = lambda: manager.cache
    try:
        client = TestClient(app)
        with patch("osmnx.graph_from_bbox", side_effect=req_exc.ConnectionError("Connection refused")):
            res = client.post(
                "/api/v1/routes/alternatives",
                json={
                    "origin": {"latitude": WESTFIELD_DONCASTER[0], "longitude": WESTFIELD_DONCASTER[1]},
                    "destination": {"latitude": ROSEVILLE_AVENUE[0], "longitude": ROSEVILLE_AVENUE[1]},
                    "enrich_elevation": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 502
    assert res.json()["error_code"] == "EXTERNAL_PROVIDER_UNAVAILABLE"


def test_api_alternatives_served_from_prebuilt_graph(prebuilt_cache, overpass_forbidden):
    manager = _prod_manager(prebuilt_cache)
    app.dependency_overrides[get_graph_manager] = lambda: manager
    app.dependency_overrides[get_regional_cache] = lambda: prebuilt_cache
    try:
        client = TestClient(app)
        res = client.post(
            "/api/v1/routes/alternatives",
            json={
                "origin": {"latitude": WESTFIELD_DONCASTER[0], "longitude": WESTFIELD_DONCASTER[1]},
                "destination": {"latitude": ROSEVILLE_AVENUE[0], "longitude": ROSEVILLE_AVENUE[1]},
                "enrich_elevation": True,
                "allow_expansion": True,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["found"] is True
    assert body["cache_hit"] is True
    assert overpass_forbidden.call_count == 0


# ---------------------------------------------------------------------------
# Frontend error-state classification and fresh-load inputs (static checks)
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent / "accessroute" / "api" / "static"


def test_frontend_has_route_unavailable_state_distinct_from_constraint_conflict():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "Route data temporarily unavailable" in html
    assert "AccessRoute couldn't retrieve the map data needed to calculate this route." in html
    assert "Try Again" in html
    assert "No Route Matches Strict Constraints" in html
    assert "error.status === 502" in js
    assert "httpError.status = res.status" in js


def test_frontend_startup_does_not_populate_route_inputs():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    init_start = js.index('document.addEventListener("DOMContentLoaded"')
    init_end = js.index("function initMap()")
    init_block = js[init_start:init_end]

    assert "PRESETS.melbourne" not in init_block
    assert "setOrigin(" not in init_block.replace("setOrigin(lat, lon, false, false, candidate", "")
    assert "setDestination(" not in init_block.replace("setDestination(lat, lon, false, false, candidate", "")
