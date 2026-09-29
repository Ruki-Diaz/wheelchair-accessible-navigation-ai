"""Stage 2 Accessibility Coverage and Data Quality Analysis CLI.

Analyzes the real OpenStreetMap Vermont South pedestrian graph,
reports frequencies of raw and normalized attributes, combinations, and missingness,
and inspects real representative edges/nodes.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from accessroute.graph.loader import get_pedestrian_graph
from accessroute.scoring.analyzer import analyze_graph_accessibility
from accessroute.scoring.models import BarrierType, KerbType, SurfaceType, WheelchairAccess
from accessroute.scoring.normalizer import extract_edge_evidence, extract_node_evidence


def run_stage2_analysis():
    print("=" * 75)
    print("AccessRoute AI — Stage 2: Accessibility Coverage & Data Quality Analysis")
    print("=" * 75)

    print("\nLoading Vermont South pedestrian graph from cache...")
    G = get_pedestrian_graph("vermont_south")
    total_edges = len(G.edges)
    total_nodes = len(G.nodes)
    print(f"Graph loaded: {total_nodes:,} nodes, {total_edges:,} edges.\n")

    print("Analyzing accessibility coverage across the entire network...")
    report = analyze_graph_accessibility(G)

    # 1. Core Feature Coverage
    print("\n" + "-" * 75)
    print("1. CORE ACCESSIBILITY ATTRIBUTES BREAKDOWN (EDGES)")
    print("-" * 75)

    print(f"Total Edges: {total_edges:,}")

    def print_breakdown(title: str, data: dict):
        print(f"\n  [{title}]")
        for k, count in sorted(data.items(), key=lambda x: -x[1]):
            pct = (count / total_edges) * 100
            print(f"    {k:20s}: {count:6,d} ({pct:5.2f}%)")

    print_breakdown("Wheelchair Tag", report.wheelchair_breakdown)
    print_breakdown("Surface Type", report.surface_breakdown)
    print_breakdown("Kerb Type", report.kerb_breakdown)
    print_breakdown("Smoothness", report.smoothness_breakdown)
    print_breakdown("Tactile Paving", report.tactile_paving_breakdown)

    print("\n  [Numeric / Boolean Measurements]")
    incline_pct = (report.incline_known_count / total_edges) * 100
    width_pct = (report.width_known_count / total_edges) * 100
    lit_pct = (report.lit_known_count / total_edges) * 100
    print(f"    Incline Known       : {report.incline_known_count:6,d} ({incline_pct:5.2f}%)")
    print(f"    Width Known         : {report.width_known_count:6,d} ({width_pct:5.2f}%)")
    print(f"    Lighting Known      : {report.lit_known_count:6,d} ({lit_pct:5.2f}%)")

    # 2. Physical Infrastructure Features
    print("\n" + "-" * 75)
    print("2. PHYSICAL INFRASTRUCTURE & BARRIERS")
    print("-" * 75)
    print(f"    Pedestrian Crossings: {report.crossing_count:6,d} ({(report.crossing_count/total_edges)*100:5.2f}%)")
    print(f"    Steps               : {report.steps_count:6,d} ({(report.steps_count/total_edges)*100:5.2f}%)")
    print(f"    Ramps Present       : {report.ramp_count:6,d} ({(report.ramp_count/total_edges)*100:5.2f}%)")
    print(f"    Wheelchair Ramps    : {report.wheelchair_ramp_count:6,d} ({(report.wheelchair_ramp_count/total_edges)*100:5.2f}%)")

    print(f"\n  [Node Physical Features] (Total Nodes: {total_nodes:,})")
    print(f"    Crossing Nodes      : {report.node_crossing_count:6,d} ({(report.node_crossing_count/total_nodes)*100:5.2f}%)")
    print(f"    Kerb Defined Nodes  : {report.node_kerb_known_count:6,d} ({(report.node_kerb_known_count/total_nodes)*100:5.2f}%)")
    print(f"    Tactile Paving Nodes: {report.node_tactile_paving_count:6,d} ({(report.node_tactile_paving_count/total_nodes)*100:5.2f}%)")
    for barrier, count in sorted(report.node_barrier_counts.items(), key=lambda x: -x[1]):
        print(f"    Barrier ({barrier:10s}): {count:6,d} ({(count/total_nodes)*100:5.2f}%)")

    # 3. Cross-Tabulated Combinations & Missingness
    print("\n" + "-" * 75)
    print("3. ACCESSIBILITY COMBINATIONS & DATA QUALITY")
    print("-" * 75)
    print(f"    Crossings with Kerb Info      : {report.crossings_with_kerb:6,d} / {report.crossing_count:,}")
    print(f"    Crossings WITHOUT Kerb Info   : {report.crossings_without_kerb:6,d} / {report.crossing_count:,}")
    print(f"    Crossings with Tactile Paving : {report.crossings_with_tactile_paving:6,d} / {report.crossing_count:,}")
    print(f"    Crossings WITHOUT Tactile     : {report.crossings_without_tactile_paving:6,d} / {report.crossing_count:,}")
    print(f"    Steps with Ramp               : {report.steps_with_ramp:6,d} / {report.steps_count:,}")
    print(f"    Steps WITHOUT Ramp            : {report.steps_without_ramp:6,d} / {report.steps_count:,}")
    print(f"    Known Surface / UNKNOWN Slope : {report.paths_known_surface_unknown_incline:6,d} ({(report.paths_known_surface_unknown_incline/total_edges)*100:5.2f}%)")
    print(f"    Explicit Wheelchair Tag       : {report.edges_with_explicit_wheelchair:6,d} ({(report.edges_with_explicit_wheelchair/total_edges)*100:5.2f}%)")
    print(f"    Surface Only (No Other Info)  : {report.edges_with_surface_only:6,d} ({(report.edges_with_surface_only/total_edges)*100:5.2f}%)")
    print(f"    Sparse / No Accessibility Info: {report.edges_with_sparse_or_no_metadata:6,d} ({(report.edges_with_sparse_or_no_metadata/total_edges)*100:5.2f}%)")

    # 4. Deterministic Findings Distribution
    print("\n" + "-" * 75)
    print("4. DETERMINISTIC FINDINGS DISTRIBUTION")
    print("-" * 75)
    for finding, count in sorted(report.findings_distribution.items(), key=lambda x: -x[1]):
        print(f"    {finding:40s}: {count:6,d}")

    # 5. Real Data Examples
    print("\n" + "-" * 75)
    print("5. REAL DATA VERIFICATION EXAMPLES (RAW -> NORMALIZED -> FINDINGS)")
    print("-" * 75)

    # Example 1: Well-described edge
    print("\n[Example 1: Well-Described Pedestrian Edge]")
    found_well_described = False
    for u, v, k, data in G.edges(keys=True, data=True):
        ev = extract_edge_evidence(data)
        if ev.surface != SurfaceType.UNKNOWN and ev.footway_type:
            print(f"  Edge ({u} -> {v}, key {k}):")
            print(f"  Raw OSM Tags: {dict(data)}")
            print(f"  Normalized Evidence: surface={ev.surface.value}, footway={ev.footway_type}, width={ev.width.width_meters}, incline={ev.incline.percentage}%")
            print(f"  Deterministic Findings: {[f.value for f in ev.findings]}")
            print(f"  Missing Fields: {ev.missing_fields}")
            found_well_described = True
            break

    # Example 2: Sparse pedestrian edge
    print("\n[Example 2: Sparse Pedestrian Edge]")
    for u, v, k, data in G.edges(keys=True, data=True):
        ev = extract_edge_evidence(data)
        if len(ev.missing_fields) >= 7 and ev.surface == SurfaceType.UNKNOWN:
            print(f"  Edge ({u} -> {v}, key {k}):")
            print(f"  Raw OSM Tags: {dict(data)}")
            print(f"  Normalized Evidence: highway={ev.highway_type}, surface={ev.surface.value}, wheelchair={ev.wheelchair.value}")
            print(f"  Deterministic Findings: {[f.value for f in ev.findings]}")
            print(f"  Missing Fields: {ev.missing_fields}")
            break

    # Example 3: Pedestrian crossing edge
    print("\n[Example 3: Pedestrian Crossing Edge]")
    for u, v, k, data in G.edges(keys=True, data=True):
        ev = extract_edge_evidence(data)
        if ev.is_crossing:
            print(f"  Edge ({u} -> {v}, key {k}):")
            print(f"  Raw OSM Tags: {dict(data)}")
            print(f"  Normalized Evidence: is_crossing={ev.is_crossing}, surface={ev.surface.value}, kerb={ev.kerb.value}, signals={ev.crossing_signals}")
            print(f"  Deterministic Findings: {[f.value for f in ev.findings]}")
            print(f"  Missing Fields: {ev.missing_fields}")
            break

    # Example 4: Steps edge (or search)
    print("\n[Example 4: Steps Edge Inspection]")
    found_steps = False
    for u, v, k, data in G.edges(keys=True, data=True):
        ev = extract_edge_evidence(data)
        if ev.is_steps:
            print(f"  Edge ({u} -> {v}, key {k}):")
            print(f"  Raw OSM Tags: {dict(data)}")
            print(f"  Normalized Evidence: is_steps=True, step_count={ev.step_count}, has_ramp={ev.has_ramp}")
            print(f"  Deterministic Findings: {[f.value for f in ev.findings]}")
            found_steps = True
            break
    if not found_steps:
        print("  (Note: No highway=steps edge exists within this 1500m suburban area of Vermont South)")

    # Example 5: Barrier node
    print("\n[Example 5: Barrier Node Inspection]")
    found_barrier = False
    for node_id, data in G.nodes(data=True):
        nev = extract_node_evidence(node_id, data)
        if nev.barrier != BarrierType.NONE:
            print(f"  Node {node_id}:")
            print(f"  Raw OSM Node Tags: {dict(data)}")
            print(f"  Normalized Evidence: barrier={nev.barrier.value}, kerb={nev.kerb.value}, wheelchair={nev.wheelchair.value}")
            print(f"  Deterministic Findings: {[f.value for f in nev.findings]}")
            found_barrier = True
            break
    if not found_barrier:
        print("  (No barrier node found in Vermont South graph)")

    print("\n" + "=" * 75)
    print("Stage 2 Analysis Complete.")
    print("=" * 75)


if __name__ == "__main__":
    run_stage2_analysis()
