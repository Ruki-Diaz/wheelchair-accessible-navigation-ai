"""Automated tests for Stage 9 Community Accessibility Data, Verification & Evidence Provenance.

Validates:
1. Community observation domain models and validity
2. SQLite persistence, bounding queries, and interaction deduplication
3. Deterministic verification state transitions
4. Spatial snapping and distance thresholds
5. Evidence conflict detection with OpenStreetMap
6. Routing integration:
   - Supported blocked path hard prohibition
   - Unverified obstacle soft uncertainty penalty
   - Expired temporary report ignored
   - Preference compilation with community evidence
   - Route detour and deterministic explainability
7. Verification opportunities / data gaps identification
8. GeoJSON provenance serialization
9. REST API endpoints
"""

from datetime import datetime, timedelta, timezone
import tempfile
from fastapi.testclient import TestClient
import networkx as nx
import pytest

from accessroute.api.main import app
from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.community.matcher import CommunitySpatialMatcher
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.repository import SQLiteCommunityObservationRepository
from accessroute.community.service import CommunityObservationService
from accessroute.community.verification import CommunityVerificationEngine
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.preferences.models import AvoidanceLevel, MobilityPreferences, StepPreference
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import CostBreakdown, evaluate_transition_cost, make_policy_cost_func
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.geojson import route_result_to_geojson
from accessroute.routing.policy import BALANCED_ACCESSIBILITY_POLICY, CONSERVATIVE_ACCESSIBILITY_POLICY
from accessroute.routing.service import CoordinatedRouteResult, RouteResult
from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    InclineMeasurement,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
    WidthMeasurement,
)


@pytest.fixture
def temp_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = f"{tmp_dir}/test_community.db"
        yield SQLiteCommunityObservationRepository(db_path=db_path)


@pytest.fixture
def api_client():
    return TestClient(app)


# =============================================================================
# 1. DOMAIN MODELS & EXPIRY
# =============================================================================

def test_community_model_defaults_and_validation():
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
    )
    assert obs.source == AccessibilityEvidenceSource.COMMUNITY_OBSERVATION
    assert obs.verification_status == VerificationStatus.UNVERIFIED
    assert obs.confirmations_count == 1
    assert obs.disputes_count == 0
    assert obs.is_active(now) is True
    assert obs.is_expired(now) is False


def test_community_model_active_and_expiry():
    now = datetime.now(timezone.utc)
    past_exp = now - timedelta(hours=2)
    obs = CommunityObservation(
        category=ObservationCategory.CONSTRUCTION,
        value="closed",
        latitude=-37.865,
        longitude=145.185,
        is_temporary=True,
        reported_at=now - timedelta(days=2),
        expires_at=past_exp,
    )
    assert obs.is_expired(now) is True
    assert obs.is_active(now) is False


# =============================================================================
# 2. SQLITE REPOSITORY PERSISTENCE & INTERACTIONS
# =============================================================================

def test_sqlite_repository_save_and_get_by_id(temp_repo):
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.SURFACE,
        value="gravel",
        latitude=-37.8655,
        longitude=145.1852,
        reported_at=now,
        notes="Uneven loose gravel path",
    )
    saved = temp_repo.save(obs)
    assert saved.id == obs.id

    fetched = temp_repo.get_by_id(obs.id)
    assert fetched is not None
    assert fetched.category == ObservationCategory.SURFACE
    assert fetched.value == "gravel"
    assert fetched.notes == "Uneven loose gravel path"


def test_sqlite_repository_bbox_query(temp_repo):
    now = datetime.now(timezone.utc)
    obs1 = CommunityObservation(
        category=ObservationCategory.KERB,
        value="flush",
        latitude=-37.8650,
        longitude=145.1850,
        reported_at=now,
    )
    obs2 = CommunityObservation(
        category=ObservationCategory.KERB,
        value="raised",
        latitude=-37.8800,  # Outside bbox
        longitude=145.2000,
        reported_at=now,
    )
    temp_repo.save(obs1)
    temp_repo.save(obs2)

    results = temp_repo.get_by_bbox(
        min_lat=-37.870,
        min_lon=145.180,
        max_lat=-37.860,
        max_lon=145.190,
    )
    assert len(results) == 1
    assert results[0].id == obs1.id


def test_sqlite_repository_nearby_query(temp_repo):
    now = datetime.now(timezone.utc)
    # Point ~50 meters from query point
    obs_near = CommunityObservation(
        category=ObservationCategory.STAIRS,
        value="without_ramp",
        latitude=-37.8650,
        longitude=145.1850,
        reported_at=now,
    )
    # Point ~3 km away
    obs_far = CommunityObservation(
        category=ObservationCategory.STAIRS,
        value="with_ramp",
        latitude=-37.8400,
        longitude=145.1850,
        reported_at=now,
    )
    temp_repo.save(obs_near)
    temp_repo.save(obs_far)

    nearby = temp_repo.get_nearby(latitude=-37.8653, longitude=145.1850, radius_m=200.0)
    assert len(nearby) == 1
    assert nearby[0].id == obs_near.id


def test_sqlite_repository_duplicate_interaction_prevention(temp_repo):
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.BARRIER,
        value="bollard",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
    )
    temp_repo.save(obs)

    # First interaction succeeds
    ok1 = temp_repo.record_interaction(obs.id, "contributor-101", "confirm")
    assert ok1 is True

    # Duplicate interaction from same contributor fails
    ok2 = temp_repo.record_interaction(obs.id, "contributor-101", "confirm")
    assert ok2 is False

    # Second independent contributor succeeds
    ok3 = temp_repo.record_interaction(obs.id, "contributor-202", "confirm")
    assert ok3 is True


# =============================================================================
# 3. SPATIAL MATCHING
# =============================================================================

@pytest.fixture
def simple_graph():
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node(1, x=145.1850, y=-37.8650, highway="crossing")
    G.add_node(2, x=145.1860, y=-37.8650)
    G.add_edge(1, 2, key=0, length=80.0, highway="footway", surface="asphalt", osmid=5001)
    return G


def test_spatial_matcher_snaps_to_nearest_edge(simple_graph):
    matcher = CommunitySpatialMatcher(max_match_distance_m=30.0)
    # Point 5 meters north of the midpoint of edge 1 -> 2
    res = matcher.match_point_to_graph(
        latitude=-37.86495,
        longitude=145.1855,
        graph=simple_graph,
        category="surface",
    )
    assert res.is_matched is True
    assert res.osm_element_type == "way"
    assert res.osm_element_id == 5001
    assert res.distance_m < 15.0


def test_spatial_matcher_snaps_to_nearest_node_for_kerb(simple_graph):
    matcher = CommunitySpatialMatcher(max_match_distance_m=30.0)
    # Point 3 meters from node 1
    res = matcher.match_point_to_graph(
        latitude=-37.86502,
        longitude=145.18502,
        graph=simple_graph,
        category="kerb",
    )
    assert res.is_matched is True
    assert res.osm_element_type == "node"
    assert res.osm_element_id == 1


def test_spatial_matcher_exceeds_threshold_remains_unmatched(simple_graph):
    matcher = CommunitySpatialMatcher(max_match_distance_m=30.0)
    # Point ~300 meters away from all graph elements
    res = matcher.match_point_to_graph(
        latitude=-37.8680,
        longitude=145.1850,
        graph=simple_graph,
        category="kerb",
    )
    assert res.is_matched is False
    assert res.osm_element_type is None
    assert res.osm_element_id is None


# =============================================================================
# 4. DETERMINISTIC VERIFICATION STATE TRANSITIONS
# =============================================================================

def test_verification_state_transition_unverified_to_supported():
    engine = CommunityVerificationEngine()
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        confirmations_count=2,
        disputes_count=0,
    )
    status = engine.evaluate_status(obs, now)
    assert status == VerificationStatus.COMMUNITY_SUPPORTED


def test_verification_state_transition_supported_to_verified():
    engine = CommunityVerificationEngine()
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        confirmations_count=4,
        disputes_count=0,
    )
    status = engine.evaluate_status(obs, now)
    assert status == VerificationStatus.VERIFIED


def test_verification_state_transition_to_disputed():
    engine = CommunityVerificationEngine()
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.SURFACE,
        value="cobblestone",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        confirmations_count=1,
        disputes_count=2,
    )
    status = engine.evaluate_status(obs, now)
    assert status == VerificationStatus.COMMUNITY_DISPUTED


def test_verification_state_transition_expired_temporary():
    engine = CommunityVerificationEngine()
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.CONSTRUCTION,
        value="closed",
        latitude=-37.865,
        longitude=145.185,
        is_temporary=True,
        reported_at=now - timedelta(hours=24),
        expires_at=now - timedelta(hours=2),
        confirmations_count=5,
    )
    status = engine.evaluate_status(obs, now)
    assert status == VerificationStatus.EXPIRED


# =============================================================================
# 5. EVIDENCE CONFLICT DETECTION
# =============================================================================

def test_conflict_detector_kerb_lowered_vs_raised():
    detector = EvidenceConflictDetector()
    now = datetime.now(timezone.utc)

    edge_ev = EdgeAccessibilityEvidence(
        kerb=KerbType.LOWERED,
        findings={FindingType.LOWERED_KERB_RECORDED},
    )
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="raised",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    conflicts = detector.detect_conflicts(edge_ev, None, [obs])
    assert len(conflicts) == 1
    assert conflicts[0].attribute_name == "kerb"
    assert "lowered" in conflicts[0].osm_claim
    assert "raised" in conflicts[0].community_claim


def test_conflict_detector_kerb_agreement():
    detector = EvidenceConflictDetector()
    now = datetime.now(timezone.utc)

    edge_ev = EdgeAccessibilityEvidence(
        kerb=KerbType.LOWERED,
        findings={FindingType.LOWERED_KERB_RECORDED},
    )
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="lowered",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    conflicts = detector.detect_conflicts(edge_ev, None, [obs])
    assert len(conflicts) == 0


def test_conflict_detector_surface_paved_vs_gravel():
    detector = EvidenceConflictDetector()
    now = datetime.now(timezone.utc)

    edge_ev = EdgeAccessibilityEvidence(
        surface=SurfaceType.ASPHALT,
        findings={FindingType.PAVED_SURFACE_RECORDED},
    )
    obs = CommunityObservation(
        category=ObservationCategory.SURFACE,
        value="gravel",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    conflicts = detector.detect_conflicts(edge_ev, None, [obs])
    assert len(conflicts) == 1
    assert conflicts[0].attribute_name == "surface"
    assert "asphalt" in conflicts[0].osm_claim
    assert "gravel" in conflicts[0].community_claim


# =============================================================================
# 6. ROUTING INTEGRATION
# =============================================================================

def test_routing_supported_path_blocked_prohibits_edge():
    now = datetime.now(timezone.utc)
    edge_ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)

    obs = CommunityObservation(
        category=ObservationCategory.PATH_BLOCKED,
        value="impassable",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    cost = evaluate_transition_cost(
        edge_evidence=edge_ev,
        node_evidence=None,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        physical_distance_m=50.0,
        community_observations=[obs],
    )
    assert cost.is_prohibited is True
    assert cost.total_weighted_cost == float("inf")
    assert FindingType.COMMUNITY_PATH_BLOCKED in cost.findings


def test_routing_unverified_obstacle_adds_uncertainty_penalty_without_prohibition():
    now = datetime.now(timezone.utc)
    edge_ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)

    # Single unverified report
    obs = CommunityObservation(
        category=ObservationCategory.TEMPORARY_OBSTACLE,
        value="debris",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.UNVERIFIED,
    )

    cost = evaluate_transition_cost(
        edge_evidence=edge_ev,
        node_evidence=None,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        physical_distance_m=50.0,
        community_observations=[obs],
    )
    # Must NOT prohibit
    assert cost.is_prohibited is False
    # But MUST add uncertainty penalty
    assert cost.uncertainty_penalty_m >= 80.0
    assert FindingType.COMMUNITY_UNVERIFIED_OBSTACLE in cost.findings


def test_routing_expired_temporary_report_ignored():
    now = datetime.now(timezone.utc)
    edge_ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)

    # Expired report
    obs = CommunityObservation(
        category=ObservationCategory.PATH_BLOCKED,
        value="flooded",
        latitude=-37.865,
        longitude=145.185,
        is_temporary=True,
        reported_at=now - timedelta(days=2),
        expires_at=now - timedelta(hours=4),
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    cost = evaluate_transition_cost(
        edge_evidence=edge_ev,
        node_evidence=None,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        physical_distance_m=50.0,
        community_observations=[obs],
    )
    # Expired report is ignored: not prohibited, normal cost
    assert cost.is_prohibited is False
    assert cost.total_weighted_cost < float("inf")
    assert FindingType.COMMUNITY_PATH_BLOCKED not in cost.findings


def test_routing_supported_stairs_obeys_strict_mobility_preference():
    now = datetime.now(timezone.utc)
    edge_ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)

    obs = CommunityObservation(
        category=ObservationCategory.STAIRS,
        value="without_ramp",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    # User configured strict stair avoidance
    prefs = MobilityPreferences(steps=StepPreference.NEVER)
    policy = compile_preferences_to_policy(prefs)

    cost = evaluate_transition_cost(
        edge_evidence=edge_ev,
        node_evidence=None,
        policy=policy,
        physical_distance_m=30.0,
        community_observations=[obs],
    )
    assert cost.is_prohibited is True
    assert FindingType.COMMUNITY_STAIRS_REPORTED in cost.findings


def test_routing_detour_around_community_blocked_path():
    """Scenario A: A* routes around a community-supported construction obstruction."""
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    now = datetime.now(timezone.utc)

    # Nodes: 1 (start), 2 (midpoint on short route), 3 (goal), 4 (detour waypoint)
    G.add_node(1, x=145.1850, y=-37.8650)
    G.add_node(2, x=145.1860, y=-37.8650)
    G.add_node(3, x=145.1870, y=-37.8650)
    G.add_node(4, x=145.1860, y=-37.8640)

    # Short direct path 1 -> 2 -> 3 (100m total), but segment 1->2 has active construction
    obs_blocked = CommunityObservation(
        category=ObservationCategory.CONSTRUCTION,
        value="closed",
        latitude=-37.8650,
        longitude=145.1855,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    G.add_edge(1, 2, key=0, length=50.0, highway="footway", surface="asphalt", _community_observations=[obs_blocked])
    G.add_edge(2, 3, key=0, length=50.0, highway="footway", surface="asphalt")

    # Detour path 1 -> 4 -> 3 (140m total, clear)
    G.add_edge(1, 4, key=0, length=70.0, highway="footway", surface="asphalt")
    G.add_edge(4, 3, key=0, length=70.0, highway="footway", surface="asphalt")

    route = a_star_search(G, start=1, goal=3, policy=BALANCED_ACCESSIBILITY_POLICY)
    assert route.found is True
    # Router must avoid 1->2 and choose detour 1->4->3
    assert route.nodes == [1, 4, 3]

    # Explainability check
    explanations = generate_route_explanation(
        route_metrics={"physical_distance_m": 140.0},
        findings=set(),
        baseline_metrics={"physical_distance_m": 100.0, "findings": [FindingType.COMMUNITY_CONSTRUCTION_REPORTED.value]},
    )
    assert any("blocked by construction" in exp.lower() for exp in explanations)


# =============================================================================
# 7. VERIFICATION OPPORTUNITIES & DATA GAPS
# =============================================================================

def test_verification_opportunities_identifies_missing_kerbs_and_surfaces():
    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"
    G.add_node(1, x=145.185, y=-37.865)
    G.add_node(2, x=145.186, y=-37.865)
    G.add_node(3, x=145.187, y=-37.865)

    # Edge 1: crossing with unknown kerb
    G.add_edge(1, 2, key=0, length=20.0, highway="crossing", is_crossing=True, kerb="unknown", osmid=101)
    # Edge 2: footway with unknown surface
    G.add_edge(2, 3, key=0, length=80.0, highway="footway", surface="unknown", osmid=102)

    svc = CommunityObservationService()
    opps = svc.identify_verification_opportunities(G)
    assert len(opps) == 2

    attrs = [o.missing_attribute for o in opps]
    assert "kerb" in attrs
    assert "surface" in attrs


# =============================================================================
# 8. GEOJSON PROVENANCE SERIALIZATION
# =============================================================================

def test_geojson_serialization_includes_provenance_and_conflicts():
    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="raised",
        latitude=-37.865,
        longitude=145.185,
        reported_at=now,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    from shapely.geometry import LineString
    route_res = RouteResult(
        found=True,
        start_node=1,
        goal_node=2,
        nodes=[1, 2],
        edges=[{
            "length": 40.0,
            "surface": "asphalt",
            "highway": "crossing",
            "kerb": "lowered",
            "geometry": LineString([(145.185, -37.865), (145.186, -37.865)]),
            "_community_observations": [obs],
        }],
        total_cost=40.0,
        total_distance_meters=40.0,
        metrics={},
    )

    coord_res = CoordinatedRouteResult(
        found=True,
        requested_origin=(-37.865, 145.185),
        requested_destination=(-37.865, 145.186),
        snapped_origin=(-37.865, 145.185),
        snapped_destination=(-37.865, 145.186),
        origin_node_id=1,
        destination_node_id=2,
        origin_snap_distance_m=0.0,
        destination_snap_distance_m=0.0,
        snap_warnings=[],
        route=route_res,
        baseline_route=None,
        region_id="test_reg",
        region_bbox=(-37.87, 145.18, -37.86, 145.19),
        cache_hit=True,
        accessibility_enriched=True,
        terrain_enriched=True,
    )

    geojson = route_result_to_geojson(coord_res, include_segments=True)
    seg_feat = next(f for f in geojson["features"] if f["properties"].get("feature_type") == "route_segment")
    props = seg_feat["properties"]

    # Provenance separation
    assert "osm_evidence" in props
    assert props["osm_evidence"]["source"] == "OpenStreetMap"
    assert "terrain_evidence" in props
    assert "community_evidence" in props
    assert len(props["community_evidence"]) == 1
    assert props["community_evidence"][0]["value"] == "raised"

    # Explicit conflict detected
    assert "conflicts" in props
    assert len(props["conflicts"]) == 1
    assert props["evidence_conflict"] is True


# =============================================================================
# 9. REST API ENDPOINTS
# =============================================================================

def test_api_submit_report(api_client):
    payload = {
        "latitude": -37.8651,
        "longitude": 145.1852,
        "category": "stairs",
        "value": "without_ramp",
        "is_temporary": False,
        "contributor_id": "test-contributor-1",
        "notes": "Flight of 8 concrete steps with no ramp",
    }
    res = api_client.post("/api/v1/community/reports", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["category"] == "stairs"
    assert data["value"] == "without_ramp"
    assert data["verification_status"].lower() == "unverified"
    assert data["confirmations_count"] == 1


def test_api_submit_report_invalid_category(api_client):
    payload = {
        "latitude": -37.865,
        "longitude": 145.185,
        "category": "not_a_real_category",
        "value": "lowered",
    }
    res = api_client.post("/api/v1/community/reports", json=payload)
    assert res.status_code == 422


def test_api_list_and_filter_reports(api_client):
    res = api_client.get("/api/v1/community/reports?category=stairs")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert "reports" in data


def test_api_confirm_and_dispute_report(api_client):
    # Create report
    post_res = api_client.post("/api/v1/community/reports", json={
        "latitude": -37.866,
        "longitude": 145.186,
        "category": "kerb",
        "value": "raised",
        "contributor_id": "creator-id",
    })
    obs_id = post_res.json()["id"]

    # First independent confirmation succeeds
    conf_res = api_client.post(f"/api/v1/community/reports/{obs_id}/confirm", json={
        "contributor_id": "peer-validator-1",
    })
    assert conf_res.status_code == 200
    assert conf_res.json()["success"] is True

    # Duplicate confirmation from same contributor fails
    dup_res = api_client.post(f"/api/v1/community/reports/{obs_id}/confirm", json={
        "contributor_id": "peer-validator-1",
    })
    assert dup_res.status_code == 400


def test_api_nearby_reports(api_client):
    res = api_client.get("/api/v1/community/nearby?latitude=-37.865&longitude=145.185&radius_m=500")
    assert res.status_code == 200
    data = res.json()
    assert "count" in data
    assert isinstance(data["reports"], list)


def test_api_geojson_endpoint(api_client):
    res = api_client.get("/api/v1/community/geojson")
    assert res.status_code == 200
    geojson = res.json()
    assert geojson["type"] == "FeatureCollection"
    assert "features" in geojson
