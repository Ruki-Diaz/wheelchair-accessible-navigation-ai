"""Automated tests for Stage 10 Accessibility Evidence Intelligence & Verification Prioritisation.

Validates:
1. Evidence reliability classification and reason compilation
2. Category-specific freshness decay and staleness policies
3. Routing impact analysis (sampled route frequency, detour risk)
4. Verification priority scoring, level assignment, and explainability
5. Regional data coverage analysis and completeness statistics
6. Coverage GeoJSON generation and choropleth properties
7. Route evidence quality breakdown (data completeness, NOT accessibility %)
8. What-if hypothetical verification simulation and isolation
9. Conflict intelligence and spatial clustering
10. Verification mission generation and suggested actions
11. Machine learning feasibility evaluation
12. FastAPI intelligence endpoints (/api/v1/intelligence/...)
"""

from datetime import datetime, timedelta, timezone
import tempfile
from fastapi.testclient import TestClient
import networkx as nx
import pytest

from accessroute.api.dependencies import get_graph_manager, get_intelligence_service
from accessroute.api.main import app
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    EvidenceConflict,
    ObservationCategory,
    VerificationOpportunity,
    VerificationStatus,
)
from accessroute.community.repository import SQLiteCommunityObservationRepository
from accessroute.community.service import CommunityObservationService
from accessroute.intelligence.conflicts import ConflictIntelligenceEngine
from accessroute.intelligence.coverage import RegionalCoverageAnalyzer
from accessroute.intelligence.impact import RoutingImpactAnalyzer
from accessroute.intelligence.missions import VerificationMissionEngine
from accessroute.intelligence.ml_feasibility import MLFeasibilityAuditor
from accessroute.intelligence.models import (
    FreshnessState,
    PriorityLevel,
    ReliabilityBand,
    RouteEvidenceQuality,
    WhatIfResult,
)
from accessroute.intelligence.priority import VerificationPriorityEngine
from accessroute.intelligence.reliability import EvidenceReliabilityEngine
from accessroute.intelligence.route_quality import RouteEvidenceQualityAnalyzer
from accessroute.intelligence.service import EvidenceIntelligenceService
from accessroute.intelligence.whatif import WhatIfVerificationAnalyzer
from accessroute.routing.service import RouteResult
from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
)


class MockGraphManager:
    """Mock GraphManager returning synthetic graph for instant offline API testing."""

    def __init__(self, G, region_id="synthetic_test_region"):
        self.G = G
        self.region_id = region_id

        class MockCache:
            def list_cached_regions(self):
                return []

            def load_graph(self, rid):
                return G, None

        self.cache = MockCache()

    def get_graph_for_bbox(self, bbox, enrich_elevation=False, force_refresh=False):
        class MockMeta:
            def __init__(self, rid):
                self.region_id = rid
        return self.G, MockMeta(self.region_id), True

    def get_graph_for_route(self, origin, destination, buffer_meters=350.0, enrich_elevation=False):
        class MockMeta:
            def __init__(self, rid):
                self.region_id = rid
        return self.G, MockMeta(self.region_id), True


@pytest.fixture
def synthetic_graph():
    """Construct a clean 5-node test network with varied accessibility metadata."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    # Coordinates spanning a 200m block
    G.add_node(1, x=145.1850, y=-37.8650)
    G.add_node(2, x=145.1860, y=-37.8650)

    G.add_node(3, x=145.1870, y=-37.8650)
    G.add_node(4, x=145.1860, y=-37.8640)
    G.add_node(5, x=145.1870, y=-37.8640)

    # Edge 1->2: Thoroughfare crossing with unknown kerb
    ev_1_2 = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT, kerb=KerbType.UNKNOWN)
    G.add_edge(1, 2, key=0, length=50.0, highway="crossing", is_crossing=True, kerb="unknown", surface="asphalt", osmid=101, _accessibility_evidence=ev_1_2)

    # Edge 2->3: Paved footway with lowered kerb
    ev_2_3 = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT, kerb=KerbType.LOWERED)
    G.add_edge(2, 3, key=0, length=50.0, highway="footway", surface="asphalt", kerb="lowered", osmid=102, _accessibility_evidence=ev_2_3)

    # Edge 1->4: Detour path with gravel surface
    ev_1_4 = EdgeAccessibilityEvidence(surface=SurfaceType.GRAVEL)
    G.add_edge(1, 4, key=0, length=60.0, highway="path", surface="gravel", osmid=103, _accessibility_evidence=ev_1_4)

    # Edge 4->5: Paved connector
    ev_4_5 = EdgeAccessibilityEvidence(surface=SurfaceType.CONCRETE)
    G.add_edge(4, 5, key=0, length=50.0, highway="footway", surface="concrete", osmid=104, _accessibility_evidence=ev_4_5)

    # Edge 5->3: Connector back to destination
    ev_5_3 = EdgeAccessibilityEvidence(surface=SurfaceType.CONCRETE)
    G.add_edge(5, 3, key=0, length=60.0, highway="footway", surface="concrete", osmid=105, _accessibility_evidence=ev_5_3)

    return G


@pytest.fixture
def api_client(synthetic_graph):
    mock_mgr = MockGraphManager(synthetic_graph)
    service = EvidenceIntelligenceService(graph_manager=mock_mgr)

    app.dependency_overrides[get_graph_manager] = lambda: mock_mgr
    app.dependency_overrides[get_intelligence_service] = lambda: service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()



# =============================================================================
# 1. EVIDENCE RELIABILITY & TEMPORAL DECAY
# =============================================================================

def test_reliability_strong_community_evidence():
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        reported_at=now - timedelta(days=5),
        confirmations_count=4,
        disputes_count=0,
    )
    osm_ev = EdgeAccessibilityEvidence(kerb=KerbType.LOWERED)

    engine = EvidenceReliabilityEngine()
    assessment = engine.evaluate_reliability(obs, osm_edge_evidence=osm_ev, now=now)

    assert assessment.reliability_band == ReliabilityBand.STRONG_COMMUNITY_EVIDENCE
    assert assessment.freshness_state == FreshnessState.ACTIVE
    assert assessment.osm_agreement is True
    assert len(assessment.reasons) >= 3
    assert any("4 independent peer" in r for r in assessment.reasons)
    assert any("Agrees with mapped OpenStreetMap" in r for r in assessment.reasons)


def test_reliability_conflicting_evidence():
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="raised",
        reported_at=now - timedelta(days=10),
        confirmations_count=2,
        disputes_count=0,
    )
    osm_ev = EdgeAccessibilityEvidence(kerb=KerbType.LOWERED)

    engine = EvidenceReliabilityEngine()
    assessment = engine.evaluate_reliability(obs, osm_edge_evidence=osm_ev, now=now)

    assert assessment.reliability_band == ReliabilityBand.CONFLICTING_EVIDENCE
    assert assessment.osm_agreement is False
    assert any("Disagrees with OpenStreetMap" in r for r in assessment.reasons)


def test_category_specific_freshness_decay():
    now = datetime.now(timezone.utc)
    engine = EvidenceReliabilityEngine()

    # 1. Kerb ramp: 400 days old -> AGING (active window is 365d, stale threshold is 730d)
    obs_kerb = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        reported_at=now - timedelta(days=400),
    )
    fresh_kerb, _ = engine.evaluate_freshness(obs_kerb, now=now)
    assert fresh_kerb == FreshnessState.AGING

    # 2. Construction: 45 days old -> STALE (active is 14d, stale threshold is 30d)
    obs_const = CommunityObservation(
        category=ObservationCategory.CONSTRUCTION,
        value="footpath_closed",
        reported_at=now - timedelta(days=45),
    )
    fresh_const, _ = engine.evaluate_freshness(obs_const, now=now)
    assert fresh_const == FreshnessState.STALE

    # 3. Lift status: 3 days old -> STALE (active is 1d, stale threshold is 2d)
    obs_lift = CommunityObservation(
        category=ObservationCategory.LIFT_STATUS,
        value="operational",
        reported_at=now - timedelta(days=3),
    )
    fresh_lift, _ = engine.evaluate_freshness(obs_lift, now=now)
    assert fresh_lift == FreshnessState.STALE


def test_temporary_condition_operational_expiry():
    now = datetime.now(timezone.utc)
    engine = EvidenceReliabilityEngine()

    obs_temp = CommunityObservation(
        category=ObservationCategory.TEMPORARY_OBSTACLE,
        value="debris",
        is_temporary=True,
        reported_at=now - timedelta(hours=30),
        expires_at=now - timedelta(hours=6),  # Expired 6h ago
    )
    fresh, reason = engine.evaluate_freshness(obs_temp, now=now)
    assert fresh == FreshnessState.EXPIRED
    assert "expired" in reason.lower()


# =============================================================================
# 2. ROUTING IMPACT ANALYSIS
# =============================================================================

def test_routing_impact_on_thoroughfare_crossing(synthetic_graph):
    analyzer = RoutingImpactAnalyzer(sample_od_pairs_count=10)

    # Edge 101 is the direct crossing on edge 1->2
    impact = analyzer.analyze_feature_impact(
        graph=synthetic_graph,
        target_osm_type="way",
        target_osm_id=101,
        missing_attribute="kerb",
        candidate_u=1,
        candidate_v=2,
    )

    assert impact.routes_traversing_count > 0
    assert impact.percentage_of_sampled_routes > 0.0
    assert impact.profiles_affected_count >= 3
    assert "manual_wheelchair" in impact.affected_profiles
    assert "mobility_scooter" in impact.affected_profiles


def test_routing_impact_on_isolated_edge(synthetic_graph):
    # Add a dead-end isolated spur 5->99
    synthetic_graph.add_node(99, x=145.1870, y=-37.8630)
    synthetic_graph.add_edge(5, 99, key=0, length=20.0, highway="footway", osmid=999)

    analyzer = RoutingImpactAnalyzer(sample_od_pairs_count=10)
    impact = analyzer.analyze_feature_impact(
        graph=synthetic_graph,
        target_osm_type="way",
        target_osm_id=999,
        missing_attribute="surface",
        candidate_u=5,
        candidate_v=99,
    )

    # Dead end spur should have very low or zero transit routes
    assert impact.routes_traversing_count <= 2
    assert impact.percentage_of_sampled_routes <= 30.0


# =============================================================================
# 3. VERIFICATION PRIORITY & EXPLAINABILITY
# =============================================================================

def test_verification_priority_thoroughfare_crossing_ranked_critical_or_high(synthetic_graph):
    opp = VerificationOpportunity(
        latitude=-37.865,
        longitude=145.1855,
        osm_element_type="way",
        osm_element_id=101,
        missing_attribute="kerb",
        feature_type="crossing",
        importance_reason="Crossing lacks kerb ramp profile.",
    )

    engine = VerificationPriorityEngine()
    priority = engine.prioritize_opportunity(
        opportunity=opp,
        graph=synthetic_graph,
        candidate_u=1,
        candidate_v=2,
    )

    assert priority.priority_level in (PriorityLevel.CRITICAL, PriorityLevel.HIGH)
    assert priority.accessibility_importance_score == 3.0  # Kerb weight
    assert len(priority.reasons) >= 2
    assert any("sampled pedestrian routes" in r or "Kerb status is completely unrecorded" in r for r in priority.reasons)


def test_prioritize_opportunities_batch_sorting(synthetic_graph):
    opp1 = VerificationOpportunity(osm_element_id=101, missing_attribute="kerb", feature_type="crossing")
    opp2 = VerificationOpportunity(osm_element_id=103, missing_attribute="surface", feature_type="footway")

    engine = VerificationPriorityEngine()
    priorities = engine.prioritize_opportunities([opp2, opp1], synthetic_graph)

    assert len(priorities) == 2
    # Kerb at crossing has higher accessibility weight than surface on detour
    assert priorities[0].priority_score >= priorities[1].priority_score


# =============================================================================
# 4. REGIONAL DATA COVERAGE
# =============================================================================

def test_regional_coverage_statistics(synthetic_graph):
    analyzer = RegionalCoverageAnalyzer()
    stats = analyzer.analyze_graph_coverage(synthetic_graph, region_id="test_box")

    assert stats["total_edges"] == 5
    assert stats["total_network_length_m"] == 270.0
    assert stats["crossings_count"] == 1
    assert stats["surface_completeness_pct"] == 100.0  # All edges have surface tags
    assert stats["kerb_completeness_pct"] == 0.0      # Crossing 101 has unknown kerb
    assert "coverage_band" in stats
    assert isinstance(stats["coverage_band"], str)


def test_coverage_geojson_feature_collection(synthetic_graph):
    analyzer = RegionalCoverageAnalyzer()
    geojson = analyzer.generate_coverage_geojson(synthetic_graph, sample_step=1)

    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0
    f0 = geojson["features"][0]
    assert f0["properties"]["feature_type"] == "coverage_edge"
    assert "completeness_score" in f0["properties"]
    assert "style" in f0["properties"]
    assert "color" in f0["properties"]["style"]


# =============================================================================
# 5. VERIFICATION MISSIONS
# =============================================================================

def test_verification_mission_generation(synthetic_graph):
    opp = VerificationOpportunity(
        latitude=-37.865,
        longitude=145.1855,
        osm_element_type="way",
        osm_element_id=101,
        missing_attribute="kerb",
        feature_type="crossing",
    )
    p_engine = VerificationPriorityEngine()
    priority = p_engine.prioritize_opportunity(opp, synthetic_graph, candidate_u=1, candidate_v=2)

    m_engine = VerificationMissionEngine()
    mission = m_engine.create_mission_from_priority(priority, synthetic_graph)

    assert "Check Kerb Ramp" in mission.title
    assert mission.category == ObservationCategory.KERB
    assert "lowered" in mission.suggested_actions
    assert "raised" in mission.suggested_actions
    assert mission.why_it_matters != ""
    assert mission.priority_level in (PriorityLevel.CRITICAL, PriorityLevel.HIGH)


# =============================================================================
# 6. ROUTE EVIDENCE QUALITY
# =============================================================================

def test_route_evidence_quality_calculation():
    # Build a simulated RouteResult
    ev1 = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT, kerb=KerbType.LOWERED)
    ev2 = EdgeAccessibilityEvidence(surface=SurfaceType.UNKNOWN, kerb=KerbType.UNKNOWN)

    edges = [
        {"length": 100.0, "surface": "asphalt", "highway": "footway", "elevation_source": "Copernicus GLO-30", "_accessibility_evidence": ev1},
        {"length": 100.0, "surface": "unknown", "highway": "crossing", "is_crossing": True, "kerb": "unknown", "elevation_source": "UNKNOWN", "_accessibility_evidence": ev2},
    ]

    mock_route = RouteResult(
        found=True,
        start_node=1,
        goal_node=3,
        nodes=[1, 2, 3],
        edges=edges,
        total_cost=200.0,
        total_distance_meters=200.0,
        metrics={},
    )

    quality = RouteEvidenceQualityAnalyzer.analyze_route_evidence(mock_route)

    assert quality.total_distance_m == 200.0
    assert quality.strong_evidence_distance_m == 100.0
    assert quality.strong_evidence_pct == 50.0
    assert quality.limited_evidence_distance_m == 100.0
    assert quality.limited_evidence_pct == 50.0
    assert quality.unknown_kerbs_count == 1
    assert quality.unknown_surface_distance_m == 100.0
    assert quality.unrecorded_elevation_distance_m == 100.0
    assert len(quality.summary_notes) >= 2


# =============================================================================
# 7. WHAT-IF VERIFICATION ANALYSIS & ISOLATION
# =============================================================================

def test_what_if_simulation_and_isolation(synthetic_graph):
    analyzer = WhatIfVerificationAnalyzer()

    # Simulate what happens if crossing 101 is verified as lowered vs raised
    res = analyzer.simulate_verification(
        graph=synthetic_graph,
        origin_node=1,
        destination_node=3,
        target_osm_type="way",
        target_osm_id=101,
        attribute_name="kerb",
        hypothetical_states=["lowered", "raised"],
    )

    assert res.is_hypothetical is True
    assert "lowered" in res.outcomes
    assert "raised" in res.outcomes

    # Lowered: stays on 100m direct path 1->2->3
    assert res.outcomes["lowered"].route_distance_m == 100.0
    assert res.outcomes["lowered"].route_changed is False

    # Raised: forces detour via 1->4->5->3 (length: 60+50+60 = 170m)
    assert res.outcomes["raised"].route_distance_m == 170.0
    assert res.outcomes["raised"].route_changed is True
    assert res.outcomes["raised"].distance_delta_m == 70.0
    assert "manual_wheelchair" in res.outcomes["raised"].affected_profiles

    # Check isolation: underlying graph edges must NOT have been modified
    assert synthetic_graph[1][2][0]["kerb"] == "unknown"


# =============================================================================
# 8. CONFLICT INTELLIGENCE & CLUSTERING
# =============================================================================

def test_conflict_clustering():
    engine = ConflictIntelligenceEngine()

    conflicts = [
        EvidenceConflict(
            osm_element_type="way",
            osm_element_id=101,
            latitude=-37.8650,
            longitude=145.1850,
            attribute_name="kerb",
            osm_claim="OSM: lowered",
            community_claim="Community: raised",
            conflict_summary="Disagreement on kerb",
            community_observation_id="obs_1",
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        ),
        EvidenceConflict(
            osm_element_type="way",
            osm_element_id=101,
            latitude=-37.8651,
            longitude=145.1851,  # 15m away
            attribute_name="surface",
            osm_claim="OSM: paved",
            community_claim="Community: gravel",
            conflict_summary="Disagreement on surface",
            community_observation_id="obs_2",
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        ),
        EvidenceConflict(
            osm_element_type="way",
            osm_element_id=202,
            latitude=-37.8750,
            longitude=145.1950,  # 1.5km away
            attribute_name="kerb",
            osm_claim="OSM: flush",
            community_claim="Community: raised",
            conflict_summary="Isolated disagreement",
            community_observation_id="obs_3",
            verification_status=VerificationStatus.COMMUNITY_DISPUTED,
        ),
    ]

    clusters = engine.cluster_conflicts(conflicts, cluster_radius_m=60.0)

    # Nearby conflicts 1 and 2 should group into 1 cluster; conflict 3 into separate cluster
    assert len(clusters) == 2
    assert clusters[0].conflicts_count == 2
    assert "kerb" in clusters[0].attributes_involved
    assert "surface" in clusters[0].attributes_involved


# =============================================================================
# 9. MACHINE LEARNING FEASIBILITY AUDIT
# =============================================================================

def test_ml_feasibility_detects_sparse_labels(synthetic_graph):
    auditor = MLFeasibilityAuditor()
    audit = auditor.audit_kerb_labels(synthetic_graph)

    assert audit["total_crossings"] == 1
    assert audit["total_labeled_crossings"] == 0
    assert audit["is_supervised_learning_defensible"] is False
    assert "Insufficient labelled accessibility data" in audit["scientific_conclusion"]


# =============================================================================
# 10. FASTAPI INTELLIGENCE REST ENDPOINTS
# =============================================================================

def test_api_coverage_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/coverage?latitude=-37.865&longitude=145.185")
    assert res.status_code == 200
    data = res.json()
    assert "surface_completeness_pct" in data
    assert "kerb_completeness_pct" in data
    assert "overall_completeness_pct" in data
    assert "coverage_band" in data


def test_api_coverage_geojson_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/coverage/geojson?latitude=-37.865&longitude=145.185")
    assert res.status_code == 200
    geojson = res.json()
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson


def test_api_verification_priorities_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/verification-priorities?latitude=-37.865&longitude=145.185&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "priorities" in data
    if data["count"] > 0:
        p0 = data["priorities"][0]
        assert "priority_score" in p0
        assert "priority_level" in p0
        assert "reasons" in p0


def test_api_verification_missions_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/missions?latitude=-37.865&longitude=145.185&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "missions" in data
    if data["count"] > 0:
        m0 = data["missions"][0]
        assert "suggested_actions" in m0
        assert "why_it_matters" in m0


def test_api_what_if_endpoint(api_client):
    payload = {
        "origin_latitude": -37.865,
        "origin_longitude": 145.185,
        "destination_latitude": -37.866,
        "destination_longitude": 145.186,
        "target_osm_type": "way",
        "target_osm_id": 101,
        "attribute_name": "kerb",
        "hypothetical_states": ["lowered", "raised"],
    }
    res = api_client.post("/api/v1/intelligence/what-if", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_hypothetical"] is True
    assert "outcomes" in data
    assert "max_routing_delta_m" in data


def test_api_conflicts_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/conflicts?latitude=-37.865&longitude=145.185")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "clusters" in data


def test_api_ml_feasibility_endpoint(api_client):
    res = api_client.get("/api/v1/intelligence/ml-feasibility?latitude=-37.865&longitude=145.185")
    assert res.status_code == 200
    data = res.json()
    assert "scientific_conclusion" in data
    assert "is_supervised_learning_defensible" in data
