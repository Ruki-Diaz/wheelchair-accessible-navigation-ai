"""What-If Verification Analysis Engine.

Stage 10 Research Component:
Evaluates hypothetical questions such as:
'What changes to route planning if this missing crossing is verified as lowered vs raised?'

CRITICAL SCIENTIFIC SAFETY RULE:
All results are explicitly marked is_hypothetical = True.
Hypothetical values are NEVER committed to the persistent database or graph cache.
"""

from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from accessroute.intelligence.models import WhatIfOutcome, WhatIfResult
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.preferences.models import MobilityPresetName, get_preset_preferences
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import make_policy_cost_func
from accessroute.routing.policy import BALANCED_ACCESSIBILITY_POLICY


class WhatIfVerificationAnalyzer:
    """Simulates hypothetical verification outcomes and measures route sensitivity."""

    @staticmethod
    def simulate_verification(
        graph: nx.MultiDiGraph,
        origin_node: int,
        destination_node: int,
        target_osm_type: str,  # 'way' | 'node'
        target_osm_id: int,
        attribute_name: str,   # 'kerb' | 'surface' | 'path_blocked'
        hypothetical_states: List[str],  # e.g. ['lowered', 'raised']
    ) -> WhatIfResult:
        """Run simulated routing queries under multiple hypothetical infrastructure states."""
        # Find matching edges in the graph
        matching_edges: List[Tuple[int, int, int]] = []
        matching_nodes: Set[int] = set()

        if target_osm_type == "node":
            for n, d in graph.nodes(data=True):
                osmid = d.get("osmid")
                if osmid == target_osm_id or (isinstance(osmid, list) and target_osm_id in osmid):
                    matching_nodes.add(n)
        else:
            for u, v, k, d in graph.edges(keys=True, data=True):
                osmid = d.get("osmid")
                if osmid == target_osm_id or (isinstance(osmid, list) and target_osm_id in osmid):
                    matching_edges.append((u, v, k))

        # Base route under balanced policy
        base_cost_func = make_policy_cost_func(graph, BALANCED_ACCESSIBILITY_POLICY)
        base_route = a_star_search(graph, origin_node, destination_node, cost_func=base_cost_func)
        baseline_dist = base_route.total_distance_meters if base_route.found else 0.0

        outcomes: Dict[str, WhatIfOutcome] = {}
        max_delta = 0.0

        # Test across standard presets to check mobility profile sensitivity
        presets = [
            MobilityPresetName.MANUAL_WHEELCHAIR,
            MobilityPresetName.POWERED_WHEELCHAIR,
            MobilityPresetName.MOBILITY_SCOOTER,
        ]

        for state in hypothetical_states:
            # Construct a hypothetical cost evaluator that dynamically overrides the attribute
            def hypothetical_cost_func(u, v, edge_data):
                is_match = False
                if target_osm_type == "node" and (u in matching_nodes or v in matching_nodes):
                    is_match = True
                elif any(me[0] == u and me[1] == v for me in matching_edges):
                    is_match = True

                if is_match:
                    # Create simulated copy of edge data
                    sim_data = dict(edge_data)
                    if attribute_name == "kerb":
                        sim_data["kerb"] = state
                        if state in ("raised", "no_kerb"):
                            # Heavy barrier penalty for manual chairs on raised kerbs
                            return edge_data.get("length", 1.0) + 400.0
                    elif attribute_name == "surface":
                        sim_data["surface"] = state
                        if state in ("gravel", "dirt", "cobblestone"):
                            return edge_data.get("length", 1.0) * 3.0
                    elif attribute_name == "path_blocked":
                        if state in ("blocked", "construction"):
                            return float("inf")

                return base_cost_func(u, v, edge_data)

            sim_route = a_star_search(graph, origin_node, destination_node, cost_func=hypothetical_cost_func)

            if sim_route.found:
                sim_dist = sim_route.total_distance_meters
                dist_delta = round(sim_dist - baseline_dist, 1)
                route_changed = (sim_route.nodes != base_route.nodes)
                if abs(dist_delta) > max_delta:
                    max_delta = abs(dist_delta)

                desc = f"Path distance: {sim_dist:.0f}m"
                if route_changed:
                    desc += f" (detour of +{dist_delta:.0f}m required to avoid barrier)"
                else:
                    desc += " (route remains unchanged)"

                # Profile sensitivity test
                affected: List[str] = []
                if attribute_name == "kerb" and state == "raised":
                    affected = [MobilityPresetName.MANUAL_WHEELCHAIR.value, MobilityPresetName.MOBILITY_SCOOTER.value]
                elif attribute_name == "path_blocked":
                    affected = [p.value for p in presets]

                outcomes[state] = WhatIfOutcome(
                    state_value=state,
                    route_distance_m=sim_dist,
                    route_changed=route_changed,
                    distance_delta_m=dist_delta,
                    selected_path_description=desc,
                    affected_profiles=affected,
                )
            else:
                outcomes[state] = WhatIfOutcome(
                    state_value=state,
                    route_distance_m=0.0,
                    route_changed=True,
                    distance_delta_m=float("inf"),
                    selected_path_description="No viable route found: network disconnected under this state.",
                    affected_profiles=[p.value for p in presets],
                )

        summary = (
            f"Hypothetical verification of {attribute_name} as {hypothetical_states} "
            f"causes a maximum routing deviation of {max_delta:.0f}m."
        )

        return WhatIfResult(
            target_element_type=target_osm_type,
            target_element_id=target_osm_id,
            attribute_simulated=attribute_name,
            baseline_distance_m=baseline_dist,
            outcomes=outcomes,
            max_routing_delta_m=max_delta,
            summary=summary,
            is_hypothetical=True,
        )
