"""Accessibility coverage and data quality analysis for OpenStreetMap networks."""

from dataclasses import dataclass, field
from typing import Any, Dict, List
import networkx as nx

from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
    TactilePaving,
    WheelchairAccess,
)
from accessroute.scoring.normalizer import (
    extract_edge_evidence,
    extract_node_evidence,
)


@dataclass
class AccessibilityCoverageReport:
    """Statistical summary of accessibility evidence and missingness in the network."""
    total_edges: int
    total_nodes: int

    # Core attribute breakdown (count, percentage)
    wheelchair_breakdown: Dict[str, int] = field(default_factory=dict)
    surface_breakdown: Dict[str, int] = field(default_factory=dict)
    kerb_breakdown: Dict[str, int] = field(default_factory=dict)
    smoothness_breakdown: Dict[str, int] = field(default_factory=dict)
    tactile_paving_breakdown: Dict[str, int] = field(default_factory=dict)
    incline_known_count: int = 0
    width_known_count: int = 0
    lit_known_count: int = 0

    # Physical features counts
    steps_count: int = 0
    crossing_count: int = 0
    ramp_count: int = 0
    wheelchair_ramp_count: int = 0

    # Node features counts
    node_kerb_known_count: int = 0
    node_tactile_paving_count: int = 0
    node_barrier_counts: Dict[str, int] = field(default_factory=dict)
    node_crossing_count: int = 0

    # Findings distribution
    findings_distribution: Dict[str, int] = field(default_factory=dict)

    # Cross-tabulated combinations
    crossings_with_kerb: int = 0
    crossings_without_kerb: int = 0
    crossings_with_tactile_paving: int = 0
    crossings_without_tactile_paving: int = 0
    steps_with_ramp: int = 0
    steps_without_ramp: int = 0
    paths_known_surface_unknown_incline: int = 0
    edges_with_explicit_wheelchair: int = 0
    edges_with_surface_only: int = 0
    edges_with_sparse_or_no_metadata: int = 0


def analyze_graph_accessibility(graph: nx.MultiDiGraph) -> AccessibilityCoverageReport:
    """Perform a deep accessibility data audit across all edges and nodes in the graph."""
    total_edges = len(graph.edges)
    total_nodes = len(graph.nodes)

    report = AccessibilityCoverageReport(
        total_edges=total_edges,
        total_nodes=total_nodes,
    )

    # 1. Edge-Level Analysis
    for _, _, data in graph.edges(data=True):
        ev: EdgeAccessibilityEvidence = extract_edge_evidence(data)

        # Breakdowns
        w_val = ev.wheelchair.value
        report.wheelchair_breakdown[w_val] = report.wheelchair_breakdown.get(w_val, 0) + 1

        s_val = ev.surface.value
        report.surface_breakdown[s_val] = report.surface_breakdown.get(s_val, 0) + 1

        k_val = ev.kerb.value
        report.kerb_breakdown[k_val] = report.kerb_breakdown.get(k_val, 0) + 1

        sm_val = ev.smoothness.value
        report.smoothness_breakdown[sm_val] = report.smoothness_breakdown.get(sm_val, 0) + 1

        tp_val = ev.tactile_paving.value
        report.tactile_paving_breakdown[tp_val] = report.tactile_paving_breakdown.get(tp_val, 0) + 1

        if ev.incline.is_known:
            report.incline_known_count += 1
        if ev.width.is_known:
            report.width_known_count += 1
        if ev.is_lit is not None:
            report.lit_known_count += 1

        if ev.is_steps:
            report.steps_count += 1
            if ev.has_ramp:
                report.steps_with_ramp += 1
            else:
                report.steps_without_ramp += 1

        if ev.has_ramp:
            report.ramp_count += 1
        if ev.has_wheelchair_ramp:
            report.wheelchair_ramp_count += 1

        if ev.is_crossing:
            report.crossing_count += 1
            if ev.kerb != KerbType.UNKNOWN:
                report.crossings_with_kerb += 1
            else:
                report.crossings_without_kerb += 1

            if ev.tactile_paving == TactilePaving.YES:
                report.crossings_with_tactile_paving += 1
            else:
                report.crossings_without_tactile_paving += 1

        # Combinations
        if ev.surface != SurfaceType.UNKNOWN and not ev.incline.is_known:
            report.paths_known_surface_unknown_incline += 1

        if ev.wheelchair != WheelchairAccess.UNKNOWN:
            report.edges_with_explicit_wheelchair += 1

        has_surface = ev.surface != SurfaceType.UNKNOWN
        has_other_acc = (
            ev.wheelchair != WheelchairAccess.UNKNOWN
            or ev.kerb != KerbType.UNKNOWN
            or ev.incline.is_known
            or ev.width.is_known
            or ev.tactile_paving != TactilePaving.UNKNOWN
            or ev.is_crossing
            or ev.is_steps
        )
        if has_surface and not has_other_acc:
            report.edges_with_surface_only += 1

        # Little or no meaningful accessibility metadata (only standard highway tag)
        if not has_surface and not has_other_acc and ev.is_lit is None:
            report.edges_with_sparse_or_no_metadata += 1

        # Findings
        for finding in ev.findings:
            f_val = finding.value
            report.findings_distribution[f_val] = (
                report.findings_distribution.get(f_val, 0) + 1
            )

    # 2. Node-Level Analysis
    for node_id, data in graph.nodes(data=True):
        nev: NodeAccessibilityEvidence = extract_node_evidence(node_id, data)

        if nev.kerb != KerbType.UNKNOWN:
            report.node_kerb_known_count += 1
        if nev.tactile_paving == TactilePaving.YES:
            report.node_tactile_paving_count += 1
        if nev.is_crossing:
            report.node_crossing_count += 1

        b_val = nev.barrier.value
        if b_val != "none":
            report.node_barrier_counts[b_val] = (
                report.node_barrier_counts.get(b_val, 0) + 1
            )

        # Include node findings in distribution
        for finding in nev.findings:
            f_val = f"NODE_{finding.value}"
            report.findings_distribution[f_val] = (
                report.findings_distribution.get(f_val, 0) + 1
            )

    return report
