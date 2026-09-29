from typing import Tuple
import networkx as nx

from accessroute.graph.region import EARTH_RADIUS_METERS, haversine_distance


def make_graph_haversine_heuristic(graph: nx.Graph, scale: float = 1.0):
    """Factory creating an A* heuristic callable h(u, v) bound to a NetworkX graph.

    Args:
        graph: NetworkX graph containing 'y' (latitude) and 'x' (longitude) node attributes.
        scale: Scaling multiplier (defaults to 1.0, typically policy.distance_weight).

    Returns:
        Callable h(u, v) -> float returning distance in meters scaled by scale factor.
    """
    nodes = graph.nodes

    def heuristic(u, v) -> float:
        node_u = nodes[u]
        node_v = nodes[v]
        return scale * haversine_distance(
            node_u["y"], node_u["x"], node_v["y"], node_v["x"]
        )

    return heuristic
