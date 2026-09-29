"""Stage 4 Terrain and Elevation Analysis Utility for Vermont South.

Loads the real Vermont South OpenStreetMap pedestrian graph, enriches all 4,114 nodes
with Copernicus GLO-30 DEM elevations via CachedElevationProvider, audits directional
grades, flags suspicious short-edge calculations, and compares calculated slope against
existing OSM incline=* tags.
"""

import math
from typing import Dict, List, Tuple
import numpy as np

from accessroute.elevation import (
    CachedElevationProvider,
    OpenMeteoElevationProvider,
    enrich_graph_with_elevation,
)
from accessroute.graph.enricher import enrich_graph_accessibility
from accessroute.graph.loader import get_pedestrian_graph
from accessroute.scoring.models import FindingType, SlopeDirection


def run_vermont_south_terrain_analysis() -> None:
    print("=" * 80)
    print(" ACCESSROUTE AI — STAGE 4 TERRAIN & ELEVATION AUDIT (VERMONT SOUTH)")
    print("=" * 80)

    # 1. Load and enrich base graph
    print("\n[1/4] Loading cached Vermont South pedestrian MultiDiGraph...")
    G = get_pedestrian_graph("vermont_south")
    enrich_graph_accessibility(G)
    print(f"      Loaded {len(G.nodes):,} nodes and {G.number_of_edges():,} edges.")

    # 2. Enrich with Copernicus DEM elevations via persistent SQLite cache
    print("\n[2/4] Enriching graph nodes & edges with Copernicus DEM elevations...")
    provider = CachedElevationProvider(backend=OpenMeteoElevationProvider())
    summary = enrich_graph_with_elevation(G, provider)
    print(f"      Enrichment complete via: {summary.elevation_source}")
    print(f"      Elevation coverage: {summary.nodes_with_elevation:,}/{summary.total_nodes:,} nodes ({summary.elevation_coverage_pct:.1f}%)")
    print(f"      Elevation range: {summary.min_elevation_m:.1f}m to {summary.max_elevation_m:.1f}m (relief: {summary.max_elevation_m - summary.min_elevation_m:.1f}m)")
    print(f"      Cache performance: {provider.cache_stats}")

    # 3. Elevation distribution statistics
    node_elevs = [
        float(data["elevation_m"])
        for _, data in G.nodes(data=True)
        if data.get("elevation_m") is not None
    ]
    if node_elevs:
        p10, p25, p50, p75, p90 = np.percentile(node_elevs, [10, 25, 50, 75, 90])
        print("\n[3/4] Elevation Distribution (Metres above Sea Level):")
        print(f"      • Minimum: {np.min(node_elevs):.1f} m")
        print(f"      • 10th Percentile: {p10:.1f} m")
        print(f"      • 25th Percentile: {p25:.1f} m")
        print(f"      • Median (50th):  {p50:.1f} m")
        print(f"      • 75th Percentile: {p75:.1f} m")
        print(f"      • 90th Percentile: {p90:.1f} m")
        print(f"      • Maximum: {np.max(node_elevs):.1f} m")
        print(f"      • Mean ± Std: {np.mean(node_elevs):.1f} m ± {np.std(node_elevs):.1f} m")

    # 4. Grade & Directional Slope Analysis
    grades: List[float] = []
    short_edge_grades: List[float] = []
    medium_edge_grades: List[float] = []
    long_edge_grades: List[float] = []
    suspicious_count = 0
    slope_direction_counts = {
        SlopeDirection.FLAT.value: 0,
        SlopeDirection.UPHILL.value: 0,
        SlopeDirection.DOWNHILL.value: 0,
    }

    osm_comparisons: List[Dict[str, float]] = []

    for u, v, k, data in G.edges(keys=True, data=True):
        g = data.get("grade")
        length = float(data.get("length", 1.0))
        if g is not None:
            grades.append(g * 100.0)
            if length < 10.0:
                short_edge_grades.append(g * 100.0)
            elif length < 30.0:
                medium_edge_grades.append(g * 100.0)
            else:
                long_edge_grades.append(g * 100.0)

            sd = data.get("slope_direction")
            if sd in slope_direction_counts:
                slope_direction_counts[sd] += 1

            if data.get("is_grade_suspicious"):
                suspicious_count += 1

            # Check if edge has explicit OSM incline tag for comparison
            ev = data.get("_accessibility_evidence")
            if ev and ev.incline.percentage is not None:
                osm_comparisons.append({
                    "u": u,
                    "v": v,
                    "length": length,
                    "osm_incline_pct": ev.incline.percentage,
                    "calculated_grade_pct": g * 100.0,
                    "diff_pct": abs(ev.incline.percentage - (g * 100.0)),
                })

    abs_grades = [abs(g) for g in grades]
    print("\n[4/4] Directional Grade & Slope Analysis:")
    print(f"      Total edges with calculated grade: {len(grades):,}")
    print(f"      • Flat segments (|grade| < 2%):   {slope_direction_counts[SlopeDirection.FLAT.value]:,} ({slope_direction_counts[SlopeDirection.FLAT.value]/len(grades)*100:.1f}%)")
    print(f"      • Uphill segments (grade >= +2%): {slope_direction_counts[SlopeDirection.UPHILL.value]:,} ({slope_direction_counts[SlopeDirection.UPHILL.value]/len(grades)*100:.1f}%)")
    print(f"      • Downhill segments (grade <= -2%): {slope_direction_counts[SlopeDirection.DOWNHILL.value]:,} ({slope_direction_counts[SlopeDirection.DOWNHILL.value]/len(grades)*100:.1f}%)")
    print(f"      • Suspicious short-edge / jittered grades: {suspicious_count:,} ({suspicious_count/len(grades)*100:.1f}%)")

    if abs_grades:
        print(f"\n      Absolute Grade Distribution (%):")
        print(f"      • Median Grade: {np.median(abs_grades):.2f}%")
        print(f"      • 90th Percentile: {np.percentile(abs_grades, 90):.2f}%")
        print(f"      • 99th Percentile: {np.percentile(abs_grades, 99):.2f}%")

    print("\n      Edge Length vs. Slope Reliability (DEM Grid Sensitivity):")
    if short_edge_grades:
        print(f"      • Short edges (< 10m, n={len(short_edge_grades):,}):  mean abs grade = {np.mean(np.abs(short_edge_grades)):.2f}% (max = {np.max(np.abs(short_edge_grades)):.1f}%)")
    if medium_edge_grades:
        print(f"      • Medium edges (10-30m, n={len(medium_edge_grades):,}): mean abs grade = {np.mean(np.abs(medium_edge_grades)):.2f}% (max = {np.max(np.abs(medium_edge_grades)):.1f}%)")
    if long_edge_grades:
        print(f"      • Long edges (>= 30m, n={len(long_edge_grades):,}):  mean abs grade = {np.mean(np.abs(long_edge_grades)):.2f}% (max = {np.max(np.abs(long_edge_grades)):.1f}%)")

    # Comparison with OSM incline tags
    print(f"\n      Comparison with Explicit OSM incline=* Tags (n={len(osm_comparisons)}):")
    if osm_comparisons:
        for idx, comp in enumerate(osm_comparisons[:5], 1):
            print(
                f"      [{idx}] Edge ({comp['u']} -> {comp['v']}), L={comp['length']:.1f}m: "
                f"OSM tag = {comp['osm_incline_pct']:.1f}% vs DEM grade = {comp['calculated_grade_pct']:.1f}% "
                f"(Δ = {comp['diff_pct']:.1f}%)"
            )
        mean_diff = np.mean([c["diff_pct"] for c in osm_comparisons])
        print(f"      Mean absolute discrepancy across OSM-tagged edges: {mean_diff:.2f}%")
    else:
        print("      No explicit numeric incline=* tags found in this bounding area.")

    print("\n" + "=" * 80)
    print(" STAGE 4 ELEVATION AUDIT COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_vermont_south_terrain_analysis()
