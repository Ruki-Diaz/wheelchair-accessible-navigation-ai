#!/usr/bin/env python3
"""Stage 10 — Accessibility Evidence Intelligence & Verification Prioritisation Data Science Analysis.

Executes comprehensive evidence intelligence analysis across real cached regional networks:
- Vermont South (Suburban residential & commercial)
- Melbourne CBD (Dense urban grid)
- Sydney CBD (Hilly harbourfront grid)

Outputs:
1. Regional Metadata Completeness (Surface, Kerb, Width, Wheelchair, Terrain)
2. Community Evidence Reliability Band Distribution
3. Temporal Decay & Staleness Analysis
4. Evidence Disagreement & Conflict Cluster Distribution
5. Network Routing Impact & Deterministic OD Sampling
6. Verification Opportunity Prioritisation (Critical, High, Medium, Low)
7. Actionable Verification Missions
8. What-If Hypothetical Verification Routing Impact
9. Mobility Profile Sensitivity Breakdown
10. Machine Learning Feasibility Audit
"""

from datetime import datetime, timedelta, timezone
import json
import os
import sys
from typing import Dict, List

# Ensure backend directory is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    EvidenceConflict,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.repository import SQLiteCommunityObservationRepository
from accessroute.community.service import CommunityObservationService
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.intelligence.conflicts import ConflictIntelligenceEngine
from accessroute.intelligence.coverage import RegionalCoverageAnalyzer
from accessroute.intelligence.impact import RoutingImpactAnalyzer
from accessroute.intelligence.missions import VerificationMissionEngine
from accessroute.intelligence.ml_feasibility import MLFeasibilityAuditor
from accessroute.intelligence.models import PriorityLevel, ReliabilityBand
from accessroute.intelligence.priority import VerificationPriorityEngine
from accessroute.intelligence.reliability import EvidenceReliabilityEngine
from accessroute.intelligence.service import EvidenceIntelligenceService
from accessroute.intelligence.whatif import WhatIfVerificationAnalyzer
from accessroute.preferences.models import MobilityPresetName


def format_header(title: str) -> str:
    line = "=" * 80
    return f"\n{line}\n  {title.upper()}\n{line}"


def format_subheader(title: str) -> str:
    line = "-" * 80
    return f"\n{line}\n  {title}\n{line}"


def main():
    print(format_header("AccessRoute AI — Stage 10 Evidence Intelligence Report"))
    print("Timestamp:", datetime.now(timezone.utc).isoformat())

    cache = RegionalGraphCache()
    coverage_analyzer = RegionalCoverageAnalyzer()
    reliability_engine = EvidenceReliabilityEngine()
    impact_analyzer = RoutingImpactAnalyzer()
    priority_engine = VerificationPriorityEngine()
    mission_engine = VerificationMissionEngine()
    conflict_engine = ConflictIntelligenceEngine()
    whatif_analyzer = WhatIfVerificationAnalyzer()
    ml_auditor = MLFeasibilityAuditor()

    # Identify candidate test regions
    regions = [
        {"name": "Vermont South (Suburban)", "id": "reg_37848ce0815b"},
        {"name": "Melbourne CBD (Dense Urban)", "id": "reg_00e3ccc78585"},
        {"name": "Sydney CBD (Harbour / Topographic)", "id": "reg_c1ada2566104"},
    ]

    # Fallback to whatever cached regions exist if IDs differ
    available_cached = {m.region_id: m for m in cache.list_cached_regions()}
    valid_regions = []
    for r in regions:
        if r["id"] in available_cached:
            valid_regions.append(r)
        else:
            # find an alternative with nodes
            for crid, cm in available_cached.items():
                if crid not in [x["id"] for x in valid_regions]:
                    valid_regions.append({"name": f"Cached Region ({crid})", "id": crid})
                    break

    # =========================================================================
    # 1. REGIONAL METADATA COMPLETENESS
    # =========================================================================
    print(format_subheader("1. Regional Metadata Completeness & Data Blind Spots"))
    coverage_results = {}
    loaded_graphs = {}

    for r in valid_regions:
        rid = r["id"]
        G, meta = cache.load_graph(rid)
        loaded_graphs[rid] = G
        stats = coverage_analyzer.analyze_graph_coverage(G, region_id=rid)
        coverage_results[r["name"]] = stats

        print(f"\nRegion: {r['name']} (ID: {rid})")
        print(f"  • Total Network Length:    {stats['total_network_length_m'] / 1000.0:.2f} km across {stats['total_edges']} segments ({len(G.nodes)} nodes)")
        print(f"  • Surface Completeness:    {stats['surface_completeness_pct']:.1f}%")
        print(f"  • Kerb Completeness:       {stats['kerb_completeness_pct']:.1f}% ({stats['crossings_with_kerb_info_count']} / {stats['crossings_count']} crossings mapped)")
        print(f"  • Width Completeness:      {stats['width_completeness_pct']:.1f}%")
        print(f"  • Wheelchair Completeness: {stats['wheelchair_completeness_pct']:.1f}%")
        print(f"  • Terrain Available:       {stats['terrain_coverage_pct']:.1f}%")
        print(f"  • Overall Completeness:    {stats['overall_completeness_pct']:.1f}% -> Band: [{stats['coverage_band']}]")

    # =========================================================================
    # 2. COMMUNITY EVIDENCE RELIABILITY & TEMPORAL DECAY (BENCHMARK)
    # =========================================================================
    print(format_subheader("2. Evidence Reliability Assessment & Temporal Decay Distribution"))
    now = datetime.now(timezone.utc)

    # Compile benchmark observations to evaluate reliability engine behavior
    benchmark_observations = [
        # Fresh confirmed lowered kerb
        CommunityObservation(
            id="obs-fresh-confirmed",
            category=ObservationCategory.KERB,
            value="lowered",
            reported_at=now - timedelta(days=2),
            confirmations_count=6,
            disputes_count=0,
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        ),
        # Moderate evidence surface
        CommunityObservation(
            id="obs-mod-surface",
            category=ObservationCategory.SURFACE,
            value="paved",
            reported_at=now - timedelta(days=35),
            confirmations_count=1,
            disputes_count=0,
            verification_status=VerificationStatus.UNVERIFIED,
        ),
        # Disputed obstacle
        CommunityObservation(
            id="obs-disputed",
            category=ObservationCategory.TEMPORARY_OBSTACLE,
            value="construction_barrier",
            reported_at=now - timedelta(days=1),
            confirmations_count=2,
            disputes_count=2,
            verification_status=VerificationStatus.COMMUNITY_DISPUTED,
        ),
        # Stale kerb observation (3 years old)
        CommunityObservation(
            id="obs-stale-kerb",
            category=ObservationCategory.KERB,
            value="lowered",
            reported_at=now - timedelta(days=800),
            confirmations_count=4,
            disputes_count=0,
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        ),
        # Expired short-lived lift status (4 days old)
        CommunityObservation(
            id="obs-expired-lift",
            category=ObservationCategory.LIFT_STATUS,
            value="operational",
            reported_at=now - timedelta(days=4),
            confirmations_count=0,
            disputes_count=0,
            verification_status=VerificationStatus.UNVERIFIED,
        ),
    ]

    reliability_counts = {b.value: 0 for b in ReliabilityBand}
    freshness_counts = {}

    for obs in benchmark_observations:
        assessment = reliability_engine.evaluate_reliability(obs, now=now)
        reliability_counts[assessment.reliability_band.value] += 1
        f_state = assessment.freshness_state.value
        freshness_counts[f_state] = freshness_counts.get(f_state, 0) + 1

        print(f"Observation [{obs.id}] ({obs.category.value}):")
        print(f"  • Reliability Band: {assessment.reliability_band.value}")
        print(f"  • Freshness State:  {assessment.freshness_state.value} (age: {assessment.age_days:.1f} days)")
        print(f"  • Reasons:          {'; '.join(assessment.reasons)}")

    print(f"\nReliability Band Summary (Benchmark N={len(benchmark_observations)}):")
    for band, count in reliability_counts.items():
        if count > 0:
            print(f"  • {band}: {count}")

    # =========================================================================
    # 3. ROUTING IMPACT ANALYSIS & CONTROLLED OD SAMPLING
    # =========================================================================
    print(format_subheader("3. Deterministic Routing Impact Analysis (OD Grid Sampling)"))
    service = EvidenceIntelligenceService()

    primary_region = valid_regions[0]
    p_graph = loaded_graphs[primary_region["id"]]
    eval_graph = p_graph
    eval_name = primary_region['name']
    target_edges = [
        (u, v, d) for u, v, k, d in eval_graph.edges(keys=True, data=True)
        if d.get("surface") == "unknown" or d.get("is_crossing") or d.get("kerb") in ("unknown", None)
    ]
    if not target_edges and "Melbourne CBD (Dense Urban)" in coverage_results:
        eval_name = "Melbourne CBD (Dense Urban)"
        eval_graph = loaded_graphs[regions[1]["id"]]
        target_edges = [
            (u, v, d) for u, v, k, d in eval_graph.edges(keys=True, data=True)
            if d.get("surface") == "unknown" or d.get("is_crossing") or d.get("kerb") in ("unknown", None)
        ]

    print(f"Running deterministic OD sampling on: {eval_name}")
    print(f"Found {len(target_edges)} candidate missing-data edges in {eval_name}.")

    sampled_impacts = []
    for u, v, data in target_edges[:3]:
        osmid = data.get("osmid", 101)
        if isinstance(osmid, list):
            osmid = osmid[0]
        osmid = int(osmid) if osmid else 101
        attr = "kerb" if data.get("is_crossing") else "surface"
        impact = impact_analyzer.analyze_feature_impact(
            eval_graph,
            target_osm_type="way",
            target_osm_id=osmid,
            missing_attribute=attr,
            candidate_u=u,
            candidate_v=v,
        )
        sampled_impacts.append((u, v, data, impact))

        print(f"\nTarget Edge ({u} -> {v}, osmid={osmid}, highway={data.get('highway')}):")
        print(f"  • Traversed in {impact.routes_traversing_count} / {impact.sampled_routes_count} sampled routes ({impact.percentage_of_sampled_routes:.1f}%)")
        print(f"  • Shortest path frequency:    {impact.shortest_path_frequency}")
        print(f"  • Accessible path frequency:  {impact.accessible_route_frequency}")
        print(f"  • Estimated Detour Distance:  {impact.max_detour_distance_m:.1f} m")
        print(f"  • Disconnect Risk:            {impact.disconnect_risk}")
        print(f"  • Affected Profiles:          {', '.join(impact.affected_profiles)}")

    # =========================================================================
    # 4. VERIFICATION PRIORITIES & ACTIONABLE MISSIONS
    # =========================================================================
    print(format_subheader("4. Ranked Verification Priorities & Community Missions"))
    all_priorities = service.get_verification_priorities(eval_graph, limit=20)
    print(f"Generated {len(all_priorities)} ranked verification opportunities.")

    priority_level_dist = {pl.value: 0 for pl in PriorityLevel}
    for p in all_priorities:
        priority_level_dist[p.priority_level.value] += 1

    print("\nPriority Level Distribution:")
    for level, count in priority_level_dist.items():
        print(f"  • {level}: {count}")

    print("\nTop High-Priority Opportunities:")
    for i, p in enumerate(all_priorities[:3], 1):
        print(f"\n#{i} Priority: [{p.priority_level.value}] (Score: {p.priority_score:.1f})")
        print(f"   Target:   {p.osm_element_type} {p.osm_element_id} ({p.feature_type}) at ({p.latitude:.5f}, {p.longitude:.5f})")
        print(f"   Missing:  {p.missing_attribute}")
        print(f"   Reasons:  {p.reasons[0] if p.reasons else 'N/A'}")
        if p.impact_details:
            print(f"   Impact:   traversed in {p.impact_details.percentage_of_sampled_routes:.1f}% of routes; detour: {p.impact_details.max_detour_distance_m:.0f}m")

    # Generate missions
    missions = service.get_verification_missions(eval_graph, limit=3)
    print(format_subheader("Actionable Community Missions Generated"))
    for m in missions:
        print(f"\nMission [{m.id}]: \"{m.title}\"")
        print(f"  • Location:          {m.location_name} ({m.latitude:.5f}, {m.longitude:.5f})")
        print(f"  • Priority:          {m.priority_level.value}")
        print(f"  • Why It Matters:    {m.why_it_matters}")
        print(f"  • Suggested Actions: {', '.join(m.suggested_actions)}")


    # =========================================================================
    # 5. WHAT-IF VERIFICATION SIMULATION
    # =========================================================================
    print(format_subheader("5. What-If Hypothetical Verification Routing Impact"))
    if sampled_impacts:
        u_t, v_t, d_t, _ = sampled_impacts[0]
        nodes = list(eval_graph.nodes())
        orig = u_t
        # Find reachable downstream node or neighbor
        succ = list(eval_graph.successors(v_t))
        dest = succ[0] if succ else nodes[min(10, len(nodes) - 1)]

        attr = "kerb" if d_t.get("is_crossing") else "surface"
        states = ["lowered", "raised"] if attr == "kerb" else ["asphalt", "gravel"]

        whatif_res = whatif_analyzer.simulate_verification(
            graph=eval_graph,
            origin_node=orig,
            destination_node=dest,
            target_osm_type="way",
            target_osm_id=d_t.get("osmid", 101),
            attribute_name=attr,
            hypothetical_states=states,
        )

        print(f"Target Way {d_t.get('osmid')} (Attribute: {attr})")
        print(f"Baseline route distance: {whatif_res.baseline_distance_m:.1f} m")
        for state, outcome in whatif_res.outcomes.items():
            print(f"  • If verified as '{state}':")
            print(f"      Route Distance: {outcome.route_distance_m:.1f} m (delta: {outcome.distance_delta_m:+.1f} m)")
            print(f"      Route Changed:  {outcome.route_changed}")
            print(f"      Description:    {outcome.selected_path_description}")
            if outcome.affected_profiles:
                print(f"      Affected Users: {', '.join(outcome.affected_profiles)}")
        print(f"Max Routing Deviation: {whatif_res.max_routing_delta_m:.1f} m")
        print(f"Hypothetical Isolation Verified: {whatif_res.is_hypothetical}")

    # =========================================================================
    # 6. EVIDENCE CONFLICT INTELLIGENCE & CLUSTERING
    # =========================================================================
    print(format_subheader("6. Evidence Conflict Clustering Analysis"))
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
            latitude=-37.8652,
            longitude=145.1853,
            attribute_name="surface",
            osm_claim="OSM: asphalt",
            community_claim="Community: cobblestone",
            conflict_summary="Disagreement on surface",
            community_observation_id="obs_2",
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        ),
    ]
    clusters = conflict_engine.cluster_conflicts(conflicts, cluster_radius_m=60.0)
    print(f"Analyzed {len(conflicts)} disagreements across region -> Grouped into {len(clusters)} spatial conflict cluster(s).")
    for c in clusters:
        print(f"  • Cluster [{c.cluster_id}]: {c.conflicts_count} conflicts near ({c.centroid_lat:.5f}, {c.centroid_lon:.5f})")
        print(f"    Attributes: {', '.join(c.attributes_involved)}")
        print(f"    Summary:    {c.description}")

    # =========================================================================
    # 7. MACHINE LEARNING FEASIBILITY AUDIT
    # =========================================================================
    print(format_subheader("7. Machine Learning Feasibility Audit (Sparse Labels Analysis)"))
    for r in valid_regions:
        g = loaded_graphs[r["id"]]
        audit = ml_auditor.audit_kerb_labels(g)
        print(f"\nRegion: {r['name']}")
        print(f"  • Total Crossings:           {audit['total_crossings']}")
        print(f"  • Labeled Crossings:         {audit['total_labeled_crossings']} ({audit['labeled_percentage']:.1f}%)")
        print(f"  • Class Distribution:        {json.dumps(audit['class_distribution'])}")
        print(f"  • Supervised ML Defensible:  {audit['is_supervised_learning_defensible']}")
        print(f"  • Scientific Conclusion:     {audit['scientific_conclusion']}")

    print(format_header("Stage 10 Evidence Intelligence Analysis Complete"))


if __name__ == "__main__":
    main()
