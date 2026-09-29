"""Verification Priority Engine.

Stage 10 Architecture:
Ranks geographic verification opportunities and stale evidence by combining:
1. Routing Impact (sampled route frequency, detour risk)
2. Physical Accessibility Significance (kerbs > stairs > surface > width)
3. Evidence Need (active conflicts > unrecorded unknowns > stale observations)

Never outputs an unexplained arbitrary score. Every priority assessment exposes
transparent factors, component scores, and human-readable reasons.
"""

from typing import Any, Dict, List, Optional
import networkx as nx

from accessroute.community.models import VerificationOpportunity
from accessroute.intelligence.impact import RoutingImpactAnalyzer
from accessroute.intelligence.models import (
    PriorityLevel,
    RoutingImpact,
    VerificationPriorityAssessment,
)

# Relative accessibility barrier importance weights
ACCESSIBILITY_WEIGHTS: Dict[str, float] = {
    "kerb": 3.0,               # Crossings lacking kerb ramps pose vertical trip hazards / barriers
    "path_blocked": 3.0,       # Obstructions completely sever traversability
    "construction": 3.0,       # Active construction works
    "stairs": 2.8,             # Steps without ramps block wheeled devices
    "ramp": 2.8,               # Ramp presence / designated status
    "lift_status": 2.5,        # Vertical interchange access
    "surface": 2.0,            # Unpaved / rough surfaces increase rolling resistance
    "width": 1.8,              # Pinch points restrict wider chairs and scooters
    "slope": 1.8,              # Steep grades exceed mechanical/manual thresholds
    "barrier": 1.5,            # Gates, bollards, chicanes
    "other": 1.0,
}


class VerificationPriorityEngine:
    """Computes transparent verification priority scores and explainable rationale."""

    def __init__(self, impact_analyzer: Optional[RoutingImpactAnalyzer] = None):
        self.impact_analyzer = impact_analyzer or RoutingImpactAnalyzer()

    def prioritize_opportunity(
        self,
        opportunity: VerificationOpportunity,
        graph: nx.MultiDiGraph,
        is_conflict: bool = False,
        is_stale: bool = False,
        candidate_u: Optional[int] = None,
        candidate_v: Optional[int] = None,
    ) -> VerificationPriorityAssessment:
        """Evaluate a verification opportunity and determine its priority."""
        # 1. Routing Impact Analysis
        impact = self.impact_analyzer.analyze_feature_impact(
            graph=graph,
            target_osm_type=opportunity.osm_element_type,
            target_osm_id=opportunity.osm_element_id,
            missing_attribute=opportunity.missing_attribute,
            candidate_u=candidate_u,
            candidate_v=candidate_v,
        )

        # Baseline impact score mapped between 0.2 and 1.5 based on traffic frequency
        if impact.percentage_of_sampled_routes > 30.0:
            routing_impact_score = 1.5
        elif impact.percentage_of_sampled_routes > 15.0:
            routing_impact_score = 1.2
        elif impact.percentage_of_sampled_routes > 5.0:
            routing_impact_score = 1.0
        elif impact.routes_traversing_count > 0:
            routing_impact_score = 0.6
        else:
            routing_impact_score = 0.3

        # Add bonus if avoidance causes significant detours or disconnects
        if impact.disconnect_risk:
            routing_impact_score += 0.5
        elif impact.max_detour_distance_m > 200.0:
            routing_impact_score += 0.3

        # 2. Accessibility Importance Score
        accessibility_importance_score = ACCESSIBILITY_WEIGHTS.get(
            opportunity.missing_attribute.lower(),
            1.5,
        )

        # 3. Evidence Need Score
        if is_conflict:
            evidence_need_score = 2.5
        elif is_stale:
            evidence_need_score = 1.6
        else:
            evidence_need_score = 2.0  # Complete unknown

        # Final Priority Score
        priority_score = routing_impact_score * accessibility_importance_score * evidence_need_score

        # Priority Level
        if priority_score >= 5.0:
            priority_level = PriorityLevel.CRITICAL
        elif priority_score >= 3.0:
            priority_level = PriorityLevel.HIGH
        elif priority_score >= 1.5:
            priority_level = PriorityLevel.MEDIUM
        else:
            priority_level = PriorityLevel.LOW

        # Generate Explainable Reasons
        reasons: List[str] = []
        if is_conflict:
            reasons.append("Conflicting evidence detected between OpenStreetMap and Community reports.")
        elif is_stale:
            reasons.append("Existing community observations have exceeded category freshness lifespan.")
        else:
            reasons.append(f"{opportunity.missing_attribute.capitalize()} status is completely unrecorded in OpenStreetMap.")

        if impact.routes_traversing_count > 0:
            reasons.append(
                f"Feature appears on {impact.routes_traversing_count}/{impact.sampled_routes_count} "
                f"({impact.percentage_of_sampled_routes:.1f}%) sampled pedestrian routes."
            )
        else:
            reasons.append("Feature is located on a local path with low sampled transit traffic.")

        if impact.profiles_affected_count > 0:
            profiles_str = ", ".join(p.replace("_", " ").title() for p in impact.affected_profiles[:3])
            reasons.append(f"Directly impacts {impact.profiles_affected_count} mobility profiles (including {profiles_str}).")

        if impact.disconnect_risk:
            reasons.append("High disconnect risk: Strict preference avoidance leaves no alternative path for some trips.")
        elif impact.max_detour_distance_m > 50.0:
            reasons.append(f"Uncertainty causes up to {impact.max_detour_distance_m:.0f}m detours under cautious routing.")

        return VerificationPriorityAssessment(
            id=opportunity.id,
            latitude=opportunity.latitude,
            longitude=opportunity.longitude,
            osm_element_type=opportunity.osm_element_type,
            osm_element_id=opportunity.osm_element_id,
            missing_attribute=opportunity.missing_attribute,
            feature_type=opportunity.feature_type,
            priority_level=priority_level,
            priority_score=priority_score,
            routing_impact_score=routing_impact_score,
            accessibility_importance_score=accessibility_importance_score,
            evidence_need_score=evidence_need_score,
            reasons=reasons,
            impact_details=impact,
        )

    def prioritize_opportunities(
        self,
        opportunities: List[VerificationOpportunity],
        graph: nx.MultiDiGraph,
        limit: int = 50,
    ) -> List[VerificationPriorityAssessment]:
        """Rank and return prioritised verification opportunities."""
        assessments: List[VerificationPriorityAssessment] = []
        for opp in opportunities[:limit]:
            ass = self.prioritize_opportunity(opp, graph)
            assessments.append(ass)

        # Sort descending by priority score
        return sorted(assessments, key=lambda a: a.priority_score, reverse=True)
