"""Routing Impact Analyzer.

Stage 10 Data Science Component:
Quantifies the actual network significance of missing or conflicting accessibility attributes.
Determines whether an unknown feature is located on a critical thoroughfare or an isolated alley.

Key Metrics:
- Sampled routes traversing the feature
- Percentage of regional accessibility-aware traffic
- Shortest-path vs Accessible-path frequency
- Number of mobility presets affected (Manual, Powered, Scooter, Walker, Pram)
- Potential detour distance caused by uncertainty/avoidance
- Disconnect risk under strict avoidance constraints
"""

import hashlib
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx

from accessroute.intelligence.models import RoutingImpact
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.preferences.models import MobilityPresetName, get_preset_preferences
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import make_policy_cost_func
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
)

logger = logging.getLogger(__name__)


class RoutingImpactAnalyzer:
    """Evaluates the structural importance of network segments to pedestrian mobility."""

    def __init__(self, sample_od_pairs_count: int = 25):
        self.sample_od_pairs_count = sample_od_pairs_count
        self._cache: Dict[str, RoutingImpact] = {}

    def _generate_sample_od_pairs(self, graph: nx.MultiDiGraph) -> List[Tuple[int, int]]:
        """Deterministically select representative origin-destination pairs across the graph."""
        nodes = sorted(list(graph.nodes()))
        if len(nodes) < 2:
            return []

        od_pairs: List[Tuple[int, int]] = []
        n = len(nodes)
        step = max(1, n // (self.sample_od_pairs_count + 1))

        # Sample across dispersed indices to span the geographic extent
        for i in range(0, n - step, step):
            origin = nodes[i]
            dest_idx = (i + n // 2) % n
            destination = nodes[dest_idx]
            if origin != destination and (origin, destination) not in od_pairs:
                od_pairs.append((origin, destination))
            if len(od_pairs) >= self.sample_od_pairs_count:
                break

        # Ensure network diameter / boundary endpoints are represented
        boundary_pairs = [
            (nodes[0], nodes[n // 2]),
            (nodes[0], nodes[-1]),
            (nodes[n // 2], nodes[-1]),
        ]
        for bp in boundary_pairs:
            if bp[0] != bp[1] and bp not in od_pairs:
                od_pairs.append(bp)

        return od_pairs

    def analyze_feature_impact(
        self,
        graph: nx.MultiDiGraph,
        target_osm_type: str,  # 'way' | 'node'
        target_osm_id: int,
        missing_attribute: str = "kerb",
        candidate_u: Optional[int] = None,
        candidate_v: Optional[int] = None,
    ) -> RoutingImpact:
        """Analyze routing significance of a specific network element."""
        cache_key = f"{len(graph)}_{target_osm_type}_{target_osm_id}_{missing_attribute}_{candidate_u}_{candidate_v}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Identify all graph edges corresponding to this OSM element
        matching_edges: Set[Tuple[int, int, int]] = set()
        matching_nodes: Set[int] = set()

        if target_osm_type == "node":
            if candidate_u is not None:
                matching_nodes.add(candidate_u)
            if candidate_v is not None:
                matching_nodes.add(candidate_v)
            for node, d in graph.nodes(data=True):
                osmid = d.get("osmid")
                if osmid == target_osm_id or (isinstance(osmid, list) and target_osm_id in osmid):
                    matching_nodes.add(node)
        else:
            if candidate_u is not None and candidate_v is not None:
                if graph.has_edge(candidate_u, candidate_v):
                    for k in graph[candidate_u][candidate_v]:
                        matching_edges.add((candidate_u, candidate_v, k))
                if graph.has_edge(candidate_v, candidate_u):
                    for k in graph[candidate_v][candidate_u]:
                        matching_edges.add((candidate_v, candidate_u, k))
            for u, v, k, d in graph.edges(keys=True, data=True):
                osmid = d.get("osmid")
                if osmid == target_osm_id or (isinstance(osmid, list) and target_osm_id in osmid):
                    matching_edges.add((u, v, k))

        od_pairs = self._generate_sample_od_pairs(graph)
        total_samples = len(od_pairs)
        if total_samples == 0:
            return RoutingImpact(
                feature_id=f"{target_osm_type}_{target_osm_id}",
                osm_element_type=target_osm_type,
                osm_element_id=target_osm_id,
                missing_attribute=missing_attribute,
                sampled_routes_count=0,
                routes_traversing_count=0,
                percentage_of_sampled_routes=0.0,
                shortest_path_frequency=0,
                accessible_route_frequency=0,
                profiles_affected_count=0,
                max_detour_distance_m=0.0,
                disconnect_risk=False,
                affected_profiles=[],
            )

        # Multi-criteria routing cost functions
        accessible_cost_func = make_policy_cost_func(graph, BALANCED_ACCESSIBILITY_POLICY)
        shortest_cost_func = make_policy_cost_func(graph, DISTANCE_FIRST_POLICY)

        routes_traversing = 0
        shortest_freq = 0
        accessible_freq = 0
        max_detour_m = 0.0
        disconnect_count = 0

        def route_uses_feature(nodes_list: List[int]) -> bool:
            if not nodes_list or len(nodes_list) < 2:
                return False
            # Check node match
            if matching_nodes and any(n in matching_nodes for n in nodes_list):
                return True
            # Check edge match
            for idx in range(len(nodes_list) - 1):
                u, v = nodes_list[idx], nodes_list[idx + 1]
                if any(me[0] == u and me[1] == v for me in matching_edges):
                    return True
            return False

        for orig, dest in od_pairs:
            # 1. Accessible route
            route_acc = a_star_search(graph, orig, dest, cost_func=accessible_cost_func)
            acc_hit = False
            if route_acc.found and route_uses_feature(route_acc.nodes):
                acc_hit = True
                accessible_freq += 1

            # 2. Shortest route
            route_short = a_star_search(graph, orig, dest, cost_func=shortest_cost_func)
            short_hit = False
            if route_short.found and route_uses_feature(route_short.nodes):
                short_hit = True
                shortest_freq += 1

            if acc_hit or short_hit:
                routes_traversing += 1

                # Measure detour distance if this feature were avoided
                # Simulate avoiding matching edges
                def avoiding_cost_func(u, v, d):
                    if (target_osm_type == "node" and (u in matching_nodes or v in matching_nodes)) or \
                       any(me[0] == u and me[1] == v for me in matching_edges):
                        return float("inf")
                    return accessible_cost_func(u, v, d)

                route_avoided = a_star_search(graph, orig, dest, cost_func=avoiding_cost_func)
                if route_avoided.found:
                    detour = max(0.0, route_avoided.total_distance_meters - route_acc.total_distance_meters)
                    if detour > max_detour_m:
                        max_detour_m = detour
                else:
                    disconnect_count += 1

        pct_traversing = (routes_traversing / total_samples) * 100.0 if total_samples > 0 else 0.0

        # Assess profile sensitivity
        affected_profiles: List[str] = []
        if missing_attribute == "kerb":
            affected_profiles = [
                MobilityPresetName.MANUAL_WHEELCHAIR.value,
                MobilityPresetName.POWERED_WHEELCHAIR.value,
                MobilityPresetName.MOBILITY_SCOOTER.value,
                MobilityPresetName.PRAM.value,
            ]
        elif missing_attribute == "surface":
            affected_profiles = [
                MobilityPresetName.MANUAL_WHEELCHAIR.value,
                MobilityPresetName.MOBILITY_SCOOTER.value,
                MobilityPresetName.WALKER.value,
            ]
        elif missing_attribute == "width":
            affected_profiles = [
                MobilityPresetName.POWERED_WHEELCHAIR.value,
                MobilityPresetName.MOBILITY_SCOOTER.value,
                MobilityPresetName.PRAM.value,
            ]
        else:
            affected_profiles = [
                MobilityPresetName.MANUAL_WHEELCHAIR.value,
                MobilityPresetName.POWERED_WHEELCHAIR.value,
            ]

        impact = RoutingImpact(
            feature_id=f"{target_osm_type}_{target_osm_id}",
            osm_element_type=target_osm_type,
            osm_element_id=target_osm_id,
            missing_attribute=missing_attribute,
            sampled_routes_count=total_samples,
            routes_traversing_count=routes_traversing,
            percentage_of_sampled_routes=pct_traversing,
            shortest_path_frequency=shortest_freq,
            accessible_route_frequency=accessible_freq,
            profiles_affected_count=len(affected_profiles),
            max_detour_distance_m=max_detour_m,
            disconnect_risk=disconnect_count > 0,
            affected_profiles=affected_profiles,
        )

        self._cache[cache_key] = impact
        return impact
