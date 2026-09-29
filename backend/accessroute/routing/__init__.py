"""Pathfinding, routing policies, cost evaluation, explainability, and service orchestration modules."""

from accessroute.routing.astar import RouteResult, a_star_search, default_distance_cost
from accessroute.routing.cost_evaluator import (
    CostBreakdown,
    evaluate_transition_cost,
    make_policy_cost_func,
)
from accessroute.routing.explainability import generate_route_explanation
from accessroute.routing.heuristics import haversine_distance, make_graph_haversine_heuristic
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    PolicyName,
    RoutingPolicy,
)
from accessroute.routing.router import (
    RouteComparison,
    compare_routes,
    generate_policy_alternatives,
    plan_route,
)
from accessroute.routing.service import (
    CoordinatedRouteResult,
    route_between_coordinates,
)

__all__ = [
    "BALANCED_ACCESSIBILITY_POLICY",
    "CONSERVATIVE_ACCESSIBILITY_POLICY",
    "CostBreakdown",
    "DISTANCE_FIRST_POLICY",
    "PolicyName",
    "RouteComparison",
    "RouteResult",
    "RoutingPolicy",
    "a_star_search",
    "compare_routes",
    "default_distance_cost",
    "evaluate_transition_cost",
    "generate_policy_alternatives",
    "generate_route_explanation",
    "haversine_distance",
    "make_graph_haversine_heuristic",
    "make_policy_cost_func",
    "plan_route",
    "CoordinatedRouteResult",
    "route_between_coordinates",
]
