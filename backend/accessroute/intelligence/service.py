"""Master Evidence Intelligence Service.

Stage 10 Architecture:
Coordinates:
1. Reliability and freshness assessments
2. Routing impact analysis
3. Verification prioritization and mission generation
4. Regional data coverage analysis and GeoJSON mapping
5. What-if verification simulation
6. Conflict clustering
7. Machine learning feasibility evaluation
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from accessroute.community.models import CommunityObservation, EvidenceConflict, VerificationOpportunity
from accessroute.community.repository import CommunityObservationRepository, SQLiteCommunityObservationRepository
from accessroute.community.service import CommunityObservationService
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.region import BoundingBox
from accessroute.intelligence.conflicts import ConflictIntelligenceEngine
from accessroute.intelligence.coverage import RegionalCoverageAnalyzer
from accessroute.intelligence.impact import RoutingImpactAnalyzer
from accessroute.intelligence.missions import VerificationMissionEngine
from accessroute.intelligence.ml_feasibility import MLFeasibilityAuditor
from accessroute.intelligence.models import (
    ConflictCluster,
    EvidenceReliabilityAssessment,
    RouteEvidenceQuality,
    VerificationMission,
    VerificationPriorityAssessment,
    WhatIfResult,
)
from accessroute.intelligence.priority import VerificationPriorityEngine
from accessroute.intelligence.reliability import EvidenceReliabilityEngine
from accessroute.intelligence.route_quality import RouteEvidenceQualityAnalyzer
from accessroute.intelligence.whatif import WhatIfVerificationAnalyzer

logger = logging.getLogger(__name__)


class EvidenceIntelligenceService:
    """Unified service for accessibility evidence intelligence and verification prioritization."""

    def __init__(
        self,
        community_service: Optional[CommunityObservationService] = None,
        graph_manager: Optional[DynamicGraphManager] = None,
    ):
        self.community_service = community_service or CommunityObservationService()
        self.graph_manager = graph_manager or DynamicGraphManager()
        self.reliability_engine = EvidenceReliabilityEngine()
        self.impact_analyzer = RoutingImpactAnalyzer()
        self.priority_engine = VerificationPriorityEngine(impact_analyzer=self.impact_analyzer)
        self.coverage_analyzer = RegionalCoverageAnalyzer()
        self.mission_engine = VerificationMissionEngine()
        self.whatif_analyzer = WhatIfVerificationAnalyzer()
        self.conflict_engine = ConflictIntelligenceEngine()
        self.quality_analyzer = RouteEvidenceQualityAnalyzer()

    def assess_observation_reliability(
        self,
        observation_id: str,
    ) -> Optional[EvidenceReliabilityAssessment]:
        """Fetch an observation from repository and compute its reliability assessment."""
        obs = self.community_service.repository.get_by_id(observation_id)
        if not obs:
            return None
        return self.reliability_engine.evaluate_reliability(obs)

    def get_regional_coverage(
        self,
        graph: nx.MultiDiGraph,
        region_id: str = "custom_region",
    ) -> Dict[str, Any]:
        """Calculate accessibility metadata coverage percentages for a pedestrian network."""
        return self.coverage_analyzer.analyze_graph_coverage(
            graph=graph,
            community_repo=self.community_service.repository,
            region_id=region_id,
        )

    def get_coverage_geojson(
        self,
        graph: nx.MultiDiGraph,
        region_id: str = "custom_region",
    ) -> Dict[str, Any]:
        """Generate GeoJSON lines for data coverage choropleth rendering."""
        return self.coverage_analyzer.generate_coverage_geojson(graph, region_id=region_id)

    def get_verification_priorities(
        self,
        graph: nx.MultiDiGraph,
        limit: int = 50,
    ) -> List[VerificationPriorityAssessment]:
        """Discover data gaps and rank them by verified routing impact and barrier significance."""
        # 1. Identify raw verification opportunities from graph
        raw_opps = self.community_service.identify_verification_opportunities(graph, max_count=limit * 2)

        # 2. Prioritize using the multi-factor priority engine
        return self.priority_engine.prioritize_opportunities(raw_opps, graph, limit=limit)

    def get_verification_missions(
        self,
        graph: nx.MultiDiGraph,
        limit: int = 20,
    ) -> List[VerificationMission]:
        """Generate actionable community tasks from the top-priority verification gaps."""
        priorities = self.get_verification_priorities(graph, limit=limit)
        return self.mission_engine.generate_missions(priorities, graph=graph, limit=limit)

    def simulate_what_if(
        self,
        graph: nx.MultiDiGraph,
        origin_node: int,
        destination_node: int,
        target_osm_type: str,
        target_osm_id: int,
        attribute_name: str,
        hypothetical_states: List[str],
    ) -> WhatIfResult:
        """Run simulated routing queries under multiple hypothetical states."""
        return self.whatif_analyzer.simulate_verification(
            graph=graph,
            origin_node=origin_node,
            destination_node=destination_node,
            target_osm_type=target_osm_type,
            target_osm_id=target_osm_id,
            attribute_name=attribute_name,
            hypothetical_states=hypothetical_states,
        )

    def get_regional_conflict_clusters(
        self,
        graph: nx.MultiDiGraph,
        cluster_radius_m: float = 60.0,
    ) -> List[ConflictCluster]:
        """Identify geographic clusters of repeated evidence disagreements in the region."""
        # Detect active conflicts between graph and stored observations
        bbox_obs = self.community_service.repository.list_all(limit=500, include_expired=False)
        all_conflicts: List[EvidenceConflict] = []

        from accessroute.community.conflicts import EvidenceConflictDetector
        for u, v, k, d in graph.edges(keys=True, data=True):
            edge_obs = d.get("_community_observations", [])
            edge_ev = d.get("_accessibility_evidence")
            if edge_obs:
                confs = EvidenceConflictDetector.detect_conflicts(edge_ev, None, edge_obs)
                all_conflicts.extend(confs)

        return self.conflict_engine.cluster_conflicts(all_conflicts, cluster_radius_m=cluster_radius_m)

    def evaluate_route_quality(self, route_result: Any) -> RouteEvidenceQuality:
        """Evaluate evidence completeness and data quality for a calculated route."""
        return self.quality_analyzer.analyze_route_evidence(route_result)

    def audit_ml_feasibility(self, graph: nx.MultiDiGraph) -> Dict[str, Any]:
        """Audit real ground-truth label coverage for machine learning feasibility."""
        return MLFeasibilityAuditor.audit_kerb_labels(graph)
