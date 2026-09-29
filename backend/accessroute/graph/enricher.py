"""Graph enrichment pipeline attaching normalized accessibility evidence to NetworkX graphs.

Operates deterministically without overwriting raw OpenStreetMap data or introducing
routing penalties/arbitrary numerical scores.
"""

from typing import Dict, Optional, Tuple
import networkx as nx

from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    NodeAccessibilityEvidence,
)
from accessroute.scoring.normalizer import (
    extract_edge_evidence,
    extract_node_evidence,
)


def enrich_graph_accessibility(
    graph: nx.MultiDiGraph, in_place: bool = False
) -> nx.MultiDiGraph:
    """Enrich all nodes and edges in a MultiDiGraph with normalized accessibility evidence.

    Preserves all existing raw OSM attributes.
    Attaches structured EdgeAccessibilityEvidence and NodeAccessibilityEvidence
    to each edge and node without corrupting GraphML serialization.

    Args:
        graph: Input pedestrian MultiDiGraph.
        in_place: If True, modifies the graph in place; otherwise creates a copy.

    Returns:
        The enriched MultiDiGraph.
    """
    G = graph if in_place else graph.copy()

    # 1. Enrich Edges
    for u, v, key, data in G.edges(keys=True, data=True):
        evidence = extract_edge_evidence(data)
        # In-memory structured object
        data["_accessibility_evidence"] = evidence
        # Flat strings for GraphML serialization safety
        data["acc_wheelchair"] = evidence.wheelchair.value
        data["acc_surface"] = evidence.surface.value
        data["acc_kerb"] = evidence.kerb.value
        data["acc_findings"] = ",".join(sorted(f.value for f in evidence.findings))
        data["acc_missing_count"] = len(evidence.missing_fields)

    # 2. Enrich Nodes
    for node_id, data in G.nodes(data=True):
        node_evidence = extract_node_evidence(node_id, data)
        data["_accessibility_evidence"] = node_evidence
        data["acc_kerb"] = node_evidence.kerb.value
        data["acc_tactile_paving"] = node_evidence.tactile_paving.value
        data["acc_barrier"] = node_evidence.barrier.value
        data["acc_findings"] = ",".join(sorted(f.value for f in node_evidence.findings))

    return G


def get_edge_accessibility(
    graph: nx.MultiDiGraph, u: int, v: int, key: Optional[int] = None
) -> EdgeAccessibilityEvidence:
    """Retrieve normalized accessibility evidence for an edge.

    Extracts cached evidence if enriched, or computes on the fly from raw tags.
    """
    edge_dict = graph.get_edge_data(u, v)
    if not edge_dict:
        raise KeyError(f"No edge exists between node {u} and node {v}.")

    if key is not None and key in edge_dict:
        data = edge_dict[key]
    else:
        # Default to first available key
        data = next(iter(edge_dict.values()))

    if "_accessibility_evidence" in data and isinstance(
        data["_accessibility_evidence"], EdgeAccessibilityEvidence
    ):
        return data["_accessibility_evidence"]

    return extract_edge_evidence(data)


def get_node_accessibility(
    graph: nx.MultiDiGraph, node_id: int
) -> NodeAccessibilityEvidence:
    """Retrieve normalized accessibility evidence for a node.

    Extracts cached evidence if enriched, or computes on the fly from raw tags.
    """
    if node_id not in graph.nodes:
        raise KeyError(f"Node {node_id} does not exist in graph.")

    data = graph.nodes[node_id]
    if "_accessibility_evidence" in data and isinstance(
        data["_accessibility_evidence"], NodeAccessibilityEvidence
    ):
        return data["_accessibility_evidence"]

    return extract_node_evidence(node_id, data)
