"""High-level routing orchestrator and comparative multi-objective analysis."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import networkx as nx

from accessroute.routing.astar import a_star_search, RouteResult
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.scoring.models import FindingType


@dataclass
class RouteComparison:
    """Detailed comparative evaluation between baseline shortest route and accessibility route."""
    start_node: int
    goal_node: int
    policy_name: str
    baseline_route: RouteResult
    accessible_route: RouteResult
    distance_difference_m: float = 0.0
    distance_increase_pct: float = 0.0
    barriers_avoided: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)
    pareto_tradeoffs: Dict[str, Any] = field(default_factory=dict)


def plan_route(
    graph: nx.MultiDiGraph,
    start_node: int,
    goal_node: int,
    policy: Optional[RoutingPolicy] = None,
) -> RouteResult:
    """Calculate an accessibility-aware route between two nodes under a policy.

    If policy is None, calculates the baseline physical distance route.
    """
    return a_star_search(
        graph=graph,
        start=start_node,
        goal=goal_node,
        policy=policy,
    )


def compare_routes(
    graph: nx.MultiDiGraph,
    start_node: int,
    goal_node: int,
    policy: RoutingPolicy = BALANCED_ACCESSIBILITY_POLICY,
) -> RouteComparison:
    """Calculate both the baseline shortest route and the accessibility-aware route, comparing trade-offs.

    Args:
        graph: NetworkX MultiDiGraph pedestrian network.
        start_node: Starting node ID.
        goal_node: Goal node ID.
        policy: Active routing policy for the accessible route.

    Returns:
        RouteComparison containing both routes, deltas, barriers avoided, and factual rationales.
    """
    # 1. Baseline Route (Pure Physical Distance)
    baseline = a_star_search(
        graph=graph,
        start=start_node,
        goal=goal_node,
        policy=None,  # No accessibility constraints
    )

    # 2. Accessibility-Aware Route
    accessible = a_star_search(
        graph=graph,
        start=start_node,
        goal=goal_node,
        policy=policy,
    )

    if not accessible.found:
        return RouteComparison(
            start_node=start_node,
            goal_node=goal_node,
            policy_name=policy.name,
            baseline_route=baseline,
            accessible_route=accessible,
            distance_difference_m=0.0,
            distance_increase_pct=0.0,
            barriers_avoided=[],
            explanations=[
                f"No traversable accessible route found under policy '{policy.name}'."
            ],
        )

    # 3. Compute Differences
    base_dist = baseline.total_distance_meters
    acc_dist = accessible.total_distance_meters
    diff_m = acc_dist - base_dist
    pct_increase = (diff_m / base_dist * 100.0) if base_dist > 0 else 0.0

    # 4. Identify Barriers Avoided
    barriers_avoided: List[str] = []
    base_findings = baseline.findings_encountered
    acc_findings = accessible.findings_encountered

    if (
        FindingType.STEPS_PRESENT.value in base_findings
        and FindingType.STEPS_PRESENT.value not in acc_findings
    ):
        barriers_avoided.append("Outdoor Stairs")

    if (
        FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED.value in base_findings
        and FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED.value not in acc_findings
    ):
        barriers_avoided.append("Prohibited Wheelchair Access Segment")

    if (
        FindingType.RESTRICTIVE_BARRIER_RECORDED.value in base_findings
        and FindingType.RESTRICTIVE_BARRIER_RECORDED.value not in acc_findings
    ):
        barriers_avoided.append("Restrictive Barrier (Turnstile / Cycle Barrier)")

    if (
        FindingType.UNPAVED_SURFACE_RECORDED.value in base_findings
        and FindingType.UNPAVED_SURFACE_RECORDED.value not in acc_findings
    ):
        barriers_avoided.append("Unpaved / Gravel Surface")

    if (
        FindingType.STEEP_UPHILL_RECORDED.value in base_findings
        and FindingType.STEEP_UPHILL_RECORDED.value not in acc_findings
    ):
        barriers_avoided.append("Steep Uphill Slope")

    # 5. Generate Comparative Explanation
    explanations = generate_route_explanation(
        route_metrics=accessible.metrics,
        findings=accessible.findings_encountered,
        baseline_metrics=baseline.metrics,
        policy_name=policy.name,
    )

    # 6. Multi-Objective Trade-Off Summary
    tradeoffs = {
        "baseline_distance_m": base_dist,
        "accessible_distance_m": acc_dist,
        "additional_distance_m": diff_m,
        "distance_overhead_pct": pct_increase,
        "accessible_accessibility_cost_m": accessible.accessibility_cost,
        "accessible_terrain_cost_m": accessible.terrain_cost,
        "accessible_uncertainty_cost_m": accessible.uncertainty_cost,
        "barriers_avoided_count": len(barriers_avoided),
    }

    return RouteComparison(
        start_node=start_node,
        goal_node=goal_node,
        policy_name=policy.name,
        baseline_route=baseline,
        accessible_route=accessible,
        distance_difference_m=diff_m,
        distance_increase_pct=pct_increase,
        barriers_avoided=barriers_avoided,
        explanations=explanations,
        pareto_tradeoffs=tradeoffs,
    )


def generate_policy_alternatives(
    graph: nx.MultiDiGraph, start_node: int, goal_node: int
) -> Dict[str, RouteResult]:
    """Generate route alternatives across standard policies (Distance-First, Balanced, Conservative).

    Enables multi-objective trade-off comparison between distance, accessibility difficulty,
    and data certainty.
    """
    policies = [
        DISTANCE_FIRST_POLICY,
        BALANCED_ACCESSIBILITY_POLICY,
        CONSERVATIVE_ACCESSIBILITY_POLICY,
    ]
    results: Dict[str, RouteResult] = {}
    for p in policies:
        results[p.name] = plan_route(graph, start_node, goal_node, policy=p)
    return results
