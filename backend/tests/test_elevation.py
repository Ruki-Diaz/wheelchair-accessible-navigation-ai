"""Unit and integration tests for elevation provider abstraction, caching, and enrichment."""

from pathlib import Path
import networkx as nx
import pytest

from accessroute.elevation import (
    CachedElevationProvider,
    ElevationEnrichmentSummary,
    MIN_RELIABLE_EDGE_LENGTH_M,
    OpenMeteoElevationProvider,
    SyntheticElevationProvider,
    enrich_graph_with_elevation,
)
from accessroute.scoring.models import FindingType, SlopeDirection


# ============================================================================
# 1. PROVIDER & CACHE TESTS
# ============================================================================

def test_synthetic_provider_exact_and_gradient():
    """Verify synthetic provider resolves exact coordinates and mathematical gradients."""
    provider = SyntheticElevationProvider(
        elevation_map={(-37.8500, 145.1700): 110.0},
        gradient_fn=lambda lat, lon: 100.0 + (lat - (-37.85)) * 1000.0,
        default_elevation=50.0,
    )

    # Exact match
    assert provider.get_elevation(-37.8500, 145.1700) == 110.0

    # Gradient fallback
    grad_val = provider.get_elevation(-37.8400, 145.1700)
    assert grad_val == pytest.approx(110.0, 1e-3)

    # Default fallback
    no_grad_provider = SyntheticElevationProvider(default_elevation=42.0)
    assert no_grad_provider.get_elevation(0.0, 0.0) == 42.0


def test_cached_provider_sqlite_persistence(tmp_path: Path):
    """Verify SQLite cache stores lookups, avoids redundant calls, and reports hit/miss stats."""
    db_file = tmp_path / "test_elev_cache.sqlite"

    calls = 0

    def mock_fetch(lat, lon):
        nonlocal calls
        calls += 1
        return 95.5

    mock_provider = SyntheticElevationProvider(
        gradient_fn=mock_fetch,
        source_name="mock_source",
    )

    cached = CachedElevationProvider(backend=mock_provider, db_path=db_file)

    # Initial query -> Cache miss
    coords = [(-37.851234, 145.171234), (-37.852000, 145.172000)]
    elevs1 = cached.get_elevations(coords)
    assert elevs1 == [95.5, 95.5]
    assert cached.cache_stats["misses"] == 2
    assert cached.cache_stats["hits"] == 0
    assert calls == 2

    # Second query for identical coordinates -> Cache hit, 0 backend calls
    elevs2 = cached.get_elevations(coords)
    assert elevs2 == [95.5, 95.5]
    assert cached.cache_stats["hits"] == 2
    assert calls == 2  # Backend not called again!

    # Create new CachedElevationProvider instance pointing to same file on disk
    cached_reloaded = CachedElevationProvider(backend=mock_provider, db_path=db_file)
    elevs3 = cached_reloaded.get_elevations(coords)
    assert elevs3 == [95.5, 95.5]
    assert cached_reloaded.cache_stats["hits"] == 2
    assert calls == 2


def test_open_meteo_provider_resilience():
    """Verify OpenMeteoElevationProvider handles invalid or offline endpoints without crashing."""
    broken_provider = OpenMeteoElevationProvider(
        api_url="https://invalid-nonexistent-domain-xyz123.com/elevation",
        timeout_seconds=0.5,
    )
    result = broken_provider.get_elevation(-37.85, 145.17)
    assert result is None


# ============================================================================
# 2. GRAPH ELEVATION ENRICHMENT TESTS
# ============================================================================

def test_graph_enrichment_node_and_edge_grades():
    """Verify graph enrichment attaches node elevations and computes signed directional grades."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850)

    # Forward edge 1 -> 2 (100m)
    G.add_edge(1, 2, key=0, length=100.0, highway="footway")
    # Reverse edge 2 -> 1 (100m)
    G.add_edge(2, 1, key=0, length=100.0, highway="footway")

    # Node 1 at 100m, Node 2 at 108m -> +8.0m elevation change over 100m = +8% grade
    provider = SyntheticElevationProvider(
        elevation_map={
            (-37.850, 145.170): 100.0,
            (-37.850, 145.171): 108.0,
        }
    )

    summary = enrich_graph_with_elevation(G, provider)
    assert summary.total_nodes == 2
    assert summary.nodes_with_elevation == 2
    assert summary.elevation_coverage_pct == 100.0
    assert summary.min_elevation_m == 100.0
    assert summary.max_elevation_m == 108.0

    # Node elevation attributes
    assert G.nodes[1]["elevation_m"] == 100.0
    assert G.nodes[2]["elevation_m"] == 108.0

    # Directional forward edge 1 -> 2
    edge_fwd = G[1][2][0]
    assert edge_fwd["grade"] == pytest.approx(0.08, 1e-4)
    assert edge_fwd["slope_direction"] == SlopeDirection.UPHILL.value
    assert edge_fwd["elevation_change_m"] == 8.0
    assert FindingType.STEEP_UPHILL_RECORDED.value in edge_fwd["findings"]

    # Directional reverse edge 2 -> 1 (must invert sign)
    edge_rev = G[2][1][0]
    assert edge_rev["grade"] == pytest.approx(-0.08, 1e-4)
    assert edge_rev["slope_direction"] == SlopeDirection.DOWNHILL.value
    assert edge_rev["elevation_change_m"] == -8.0
    assert FindingType.STEEP_DOWNHILL_RECORDED.value in edge_rev["findings"]


def test_flat_segment_classification():
    """Verify flat segment (|grade| < 2%) is classified as FLAT."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850)
    G.add_edge(1, 2, key=0, length=100.0, highway="footway")

    # 1.0m change over 100m = 1% grade -> FLAT
    provider = SyntheticElevationProvider(
        elevation_map={
            (-37.850, 145.170): 100.0,
            (-37.850, 145.171): 101.0,
        }
    )
    enrich_graph_with_elevation(G, provider)
    assert G[1][2][0]["slope_direction"] == SlopeDirection.FLAT.value


def test_suspicious_short_edge_grade_safeguard():
    """Verify short edges (< 10m) with sudden elevation jumps are flagged as suspicious DEM jitter."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.1701, y=-37.850)  # Very short edge: 3 meters

    G.add_edge(1, 2, key=0, length=3.0, highway="footway")

    # 1.2m elevation jump over 3m (40% slope) on standard footway
    provider = SyntheticElevationProvider(
        elevation_map={
            (-37.850, 145.170): 100.0,
            (-37.850, 145.1701): 101.2,
        }
    )

    summary = enrich_graph_with_elevation(G, provider)
    assert summary.suspicious_edges_count == 1
    edge_data = G[1][2][0]
    assert edge_data["is_grade_suspicious"] is True
    assert FindingType.SUSPICIOUS_GRADE_FLAGGED.value in edge_data["findings"]


def test_missing_elevation_preserves_unknown():
    """Verify missing node elevations are recorded as UNKNOWN and flagged on edges."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.170, y=-37.850)
    G.add_node(2, x=145.171, y=-37.850)
    G.add_edge(1, 2, key=0, length=50.0, highway="footway")

    provider = SyntheticElevationProvider(elevation_map={})  # Returns None for all

    summary = enrich_graph_with_elevation(G, provider)
    assert summary.nodes_with_elevation == 0
    assert summary.elevation_coverage_pct == 0.0

    assert G.nodes[1]["elevation_m"] is None
    assert G.nodes[1]["elevation_status"] == "MISSING"

    edge_data = G[1][2][0]
    assert edge_data["grade"] is None
    assert FindingType.ELEVATION_EVIDENCE_MISSING.value in edge_data["findings"]
