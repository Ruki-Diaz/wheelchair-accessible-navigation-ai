"""Controlled demonstration of Stage 9 Scenarios A–E.

Demonstrates:
Scenario A: Temporary Construction Detour & Deterministic Explanation
Scenario B: Unverified Obstacle Soft Penalty Without False Prohibition
Scenario C: Evidence Conflict (OSM lowered vs Community raised)
Scenario D: Expired Temporary Report Ignored by Routing Engine
Scenario E: Missing Kerb Verification Opportunities (Data Gaps)
"""

from datetime import datetime, timedelta, timezone
from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.service import CommunityObservationService
from accessroute.preferences.models import AvoidanceLevel, MobilityPreferences
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import evaluate_transition_cost, make_policy_cost_func
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.policy import BALANCED_ACCESSIBILITY_POLICY
from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
)
import networkx as nx


def demo_scenario_a():
    print("=" * 80)
    print("SCENARIO A — TEMPORARY CONSTRUCTION DETOUR & EXPLANATION")
    print("=" * 80)
    # 3-node graph: direct path 1->2 (length 50m) blocked by construction; detour 1->3->2 (length 70m)
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.185, y=-37.865)
    G.add_node(2, x=145.186, y=-37.865)
    G.add_node(3, x=145.1855, y=-37.864)

    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.CONSTRUCTION,
        value="footpath_closed",
        latitude=-37.865,
        longitude=145.1855,
        is_temporary=True,
        reported_at=now,
        expires_at=now + timedelta(days=2),
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        confirmations_count=3,
        disputes_count=0,
    )

    ev_direct = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)
    ev_detour1 = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)
    ev_detour2 = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)

    G.add_edge(1, 2, key=0, length=50.0, _accessibility_evidence=ev_direct, _community_observations=[obs])
    G.add_edge(1, 3, key=0, length=35.0, _accessibility_evidence=ev_detour1)
    G.add_edge(3, 2, key=0, length=35.0, _accessibility_evidence=ev_detour2)

    cost_func = make_policy_cost_func(G, BALANCED_ACCESSIBILITY_POLICY)
    route = a_star_search(G, 1, 2, cost_func=cost_func)

    baseline_metrics = {
        "physical_distance_m": 50.0,
        "findings": [FindingType.COMMUNITY_CONSTRUCTION_REPORTED.value],
    }
    route_metrics = {
        "physical_distance_m": route.total_distance_meters,
        "paved_distance_pct": 100.0,
    }
    exps = generate_route_explanation(
        route_metrics=route_metrics,
        findings=set(),
        baseline_metrics=baseline_metrics,
        policy_name="balanced",
    )
    exp = exps[0] if exps else ""

    print(f"Direct path length: 50.0 m (Reported blocked by construction)")
    print(f"Detour path chosen: {route.nodes}")
    print(f"Total distance: {route.total_distance_meters} m")
    print(f"Explanation produced: '{exp}'")
    assert route.nodes == [1, 3, 2]
    assert "construction" in exp.lower()
    print("✓ Scenario A verified: Router cleanly diverted around construction and produced deterministic explanation.\n")


def demo_scenario_b():
    print("=" * 80)
    print("SCENARIO B — UNVERIFIED OBSTACLE (SOFT UNCERTAINTY PENALTY)")
    print("=" * 80)
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.185, y=-37.865)
    G.add_node(2, x=145.186, y=-37.865)

    now = datetime.now(timezone.utc)
    obs = CommunityObservation(
        category=ObservationCategory.TEMPORARY_OBSTACLE,
        value="debris",
        latitude=-37.865,
        longitude=145.1855,
        is_temporary=True,
        reported_at=now,
        expires_at=now + timedelta(hours=12),
        verification_status=VerificationStatus.UNVERIFIED,
        confirmations_count=1,
        disputes_count=0,
    )

    ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)
    G.add_edge(1, 2, key=0, length=50.0, _accessibility_evidence=ev, _community_observations=[obs])

    cost_func = make_policy_cost_func(G, BALANCED_ACCESSIBILITY_POLICY)
    route = a_star_search(G, 1, 2, cost_func=cost_func)

    # Edge cost includes uncertainty penalty
    cost_bd = evaluate_transition_cost(
        edge_evidence=ev,
        node_evidence=None,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        physical_distance_m=50.0,
        community_observations=[obs],
    )

    print(f"Physical distance: {route.total_distance_meters} m")
    print(f"Traversal found: {route.found}")
    print(f"Base edge length: 50.0 m")
    print(f"Total weighted cost with unverified penalty: {cost_bd.total_weighted_cost:.1f}")
    print(f"Uncertainty penalty component: {cost_bd.uncertainty_penalty_m:.1f} m")
    assert route.found is True
    assert cost_bd.uncertainty_penalty_m > 0.0
    print("✓ Scenario B verified: Single unverified report was NOT falsely prohibited; added transparent uncertainty penalty.\n")


def demo_scenario_c():
    print("=" * 80)
    print("SCENARIO C — EVIDENCE CONFLICT (OSM lowered vs COMMUNITY raised)")
    print("=" * 80)
    osm_node = NodeAccessibilityEvidence(node_id=1, latitude=-37.865, longitude=145.185, kerb=KerbType.LOWERED, is_crossing=True)
    comm_obs = CommunityObservation(
        category=ObservationCategory.KERB,
        value="raised",
        latitude=-37.865,
        longitude=145.185,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        confirmations_count=3,
        disputes_count=0,
    )

    conflicts = EvidenceConflictDetector.detect_conflicts(None, osm_node, [comm_obs])
    print(f"Conflicts detected: {len(conflicts)}")
    for c in conflicts:
        print(f"  Attribute: {c.attribute_name}")
        print(f"  OSM claim: {c.osm_claim}")
        print(f"  Community claim: {c.community_claim}")
        print(f"  Summary: {c.conflict_summary}")
        print(f"  Status: {c.verification_status.value}")

    assert len(conflicts) == 1
    assert "lowered" in conflicts[0].osm_claim
    assert "raised" in conflicts[0].community_claim
    print("✓ Scenario C verified: Both sources preserved; explicit disagreement flagged without silent overwrite.\n")


def demo_scenario_d():
    print("=" * 80)
    print("SCENARIO D — EXPIRED REPORT IGNORED BY ROUTING")
    print("=" * 80)
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.185, y=-37.865)
    G.add_node(2, x=145.186, y=-37.865)

    now = datetime.now(timezone.utc)
    expired_obs = CommunityObservation(
        category=ObservationCategory.PATH_BLOCKED,
        value="construction",
        latitude=-37.865,
        longitude=145.1855,
        is_temporary=True,
        reported_at=now - timedelta(days=5),
        expires_at=now - timedelta(days=1),  # Expired yesterday
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        confirmations_count=5,
    )

    ev = EdgeAccessibilityEvidence(surface=SurfaceType.ASPHALT)
    G.add_edge(1, 2, key=0, length=50.0, _accessibility_evidence=ev, _community_observations=[expired_obs])

    cost_bd = evaluate_transition_cost(
        edge_evidence=ev,
        node_evidence=None,
        policy=BALANCED_ACCESSIBILITY_POLICY,
        physical_distance_m=50.0,
        community_observations=[expired_obs],
    )

    print(f"Observation reported at: {expired_obs.reported_at}")
    print(f"Observation expired at:  {expired_obs.expires_at}")
    print(f"Is observation active:   {expired_obs.is_active(now)}")
    print(f"Edge traversal prohibited: {cost_bd.is_prohibited}")
    print(f"Edge total weighted cost: {cost_bd.total_weighted_cost:.1f} (nominal edge cost)")
    assert expired_obs.is_active(now) is False
    assert cost_bd.is_prohibited is False
    print("✓ Scenario D verified: Expired temporary report retained in history but ignored by routing engine.\n")


def demo_scenario_e():
    print("=" * 80)
    print("SCENARIO E — MISSING KERB VERIFICATION OPPORTUNITY")
    print("=" * 80)
    G = nx.MultiDiGraph()
    G.add_node(10, x=145.185, y=-37.865)
    G.add_node(20, x=145.186, y=-37.865)
    G.add_node(30, x=145.187, y=-37.865)
    G.add_edge(10, 20, key=0, length=20.0, highway="crossing", is_crossing=True, kerb="unknown", osmid=101)
    G.add_edge(20, 30, key=0, length=80.0, highway="footway", surface="unknown", osmid=102)

    srv = CommunityObservationService()
    opportunities = srv.identify_verification_opportunities(G)

    print(f"Identified verification opportunities: {len(opportunities)}")
    for opp in opportunities:
        print(f"  Feature Type:      {opp.feature_type}")
        print(f"  Missing Attribute: {opp.missing_attribute}")
        print(f"  Importance Reason: {opp.importance_reason}")
        print(f"  OSM Element:       {opp.osm_element_type} #{opp.osm_element_id}")

    assert any(o.missing_attribute == "kerb" for o in opportunities)
    assert any(o.missing_attribute == "surface" for o in opportunities)
    print("✓ Scenario E verified: Deterministic data gaps flagged for targeted community verification.\n")


if __name__ == "__main__":
    demo_scenario_a()
    demo_scenario_b()
    demo_scenario_c()
    demo_scenario_d()
    demo_scenario_e()
    print("=" * 80)
    print("ALL 5 CONTROLLED DEMONSTRATION SCENARIOS SUCCESSFULLY VERIFIED!")
    print("=" * 80)
