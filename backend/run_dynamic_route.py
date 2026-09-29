"""Stage 5 Development CLI for Arbitrary-Coordinate Routing.

Usage:
    python backend/run_dynamic_route.py --origin -37.8180 144.9671 --destination -37.8180 144.9691 --policy balanced --map dev_maps/melbourne_cbd_demo.html
"""

import argparse
from pathlib import Path
import sys

from accessroute.graph.errors import AccessRouteError
from accessroute.routing.policy import (
    BALANCED_ACCESSIBILITY_POLICY,
    CONSERVATIVE_ACCESSIBILITY_POLICY,
    DISTANCE_FIRST_POLICY,
    RoutingPolicy,
)
from accessroute.routing.service import route_between_coordinates
from accessroute.visualization.map import create_route_map


def parse_args():
    parser = argparse.ArgumentParser(
        description="AccessRoute AI — Dynamic Arbitrary-Coordinate Routing Engine"
    )
    parser.add_argument(
        "--origin",
        nargs=2,
        type=float,
        required=True,
        metavar=("LAT", "LON"),
        help="Origin coordinates: latitude longitude",
    )
    parser.add_argument(
        "--destination",
        nargs=2,
        type=float,
        required=True,
        metavar=("LAT", "LON"),
        help="Destination coordinates: latitude longitude",
    )
    parser.add_argument(
        "--policy",
        choices=["balanced", "conservative", "distance_first"],
        default="balanced",
        help="Routing policy to use (default: balanced)",
    )
    parser.add_argument(
        "--no-elevation",
        action="store_true",
        help="Skip digital elevation model enrichment",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-download from OpenStreetMap bypassing cache",
    )
    parser.add_argument(
        "--map",
        type=str,
        default=None,
        help="Optional path to output interactive Folium HTML map",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    origin = (args.origin[0], args.origin[1])
    dest = (args.destination[0], args.destination[1])

    policy_map = {
        "balanced": BALANCED_ACCESSIBILITY_POLICY,
        "conservative": CONSERVATIVE_ACCESSIBILITY_POLICY,
        "distance_first": DISTANCE_FIRST_POLICY,
    }
    selected_policy: RoutingPolicy = policy_map[args.policy]

    print("=" * 80)
    print(" ACCESSROUTE AI — STAGE 5 DYNAMIC COORDINATE ROUTING")
    print("=" * 80)
    print(f"Requested Origin:      ({origin[0]:.6f}, {origin[1]:.6f})")
    print(f"Requested Destination: ({dest[0]:.6f}, {dest[1]:.6f})")
    print(f"Active Policy:         {selected_policy.name.upper()}")
    print("-" * 80)

    try:
        result = route_between_coordinates(
            origin=origin,
            destination=dest,
            policy=selected_policy,
            enrich_elevation=not args.no_elevation,
            force_refresh=args.refresh,
        )
    except AccessRouteError as exc:
        print(f"\n[ERROR] Routing request rejected: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[UNEXPECTED ERROR] {exc}")
        sys.exit(1)

    print("\n[1] Geographic Acquisition & Cache Telemetry:")
    print(f"    • Spatial Region ID:        {result.region_id}")
    print(f"    • Regional Cache Status:    {'CACHE HIT (Instant Local Graph)' if result.cache_hit else 'CACHE MISS (Downloaded from OSM)'}")
    print(f"    • Bounding Box (S, W, N, E): {result.region_bbox}")
    print(f"    • Accessibility Enriched:   {result.accessibility_enriched}")
    print(f"    • Terrain Enriched:         {result.terrain_enriched}")

    print("\n[2] Network Snapping Quality:")
    print(f"    • Origin Snap:      Node {result.origin_node_id} ({result.snapped_origin[0]:.6f}, {result.snapped_origin[1]:.6f}) — {result.origin_snap_distance_m:.1f}m away")
    print(f"    • Destination Snap: Node {result.destination_node_id} ({result.snapped_destination[0]:.6f}, {result.snapped_destination[1]:.6f}) — {result.destination_snap_distance_m:.1f}m away")
    if result.snap_warnings:
        for warn in result.snap_warnings:
            print(f"    • ⚠️ {warn}")

    print("\n[3] Multi-Criteria Route Metrics:")
    if not result.found:
        print("    • No accessible path found between the snapped nodes under active policy.")
        sys.exit(0)

    metrics = result.route.metrics
    print(f"    • Physical Distance:       {result.physical_distance_meters:.1f} m")
    print(f"    • Accessibility Penalty:   {result.accessibility_cost:.1f} m (virtual)")
    print(f"    • Terrain Slope Penalty:   {result.terrain_cost:.1f} m (virtual)")
    print(f"    • Uncertainty Cost:        {result.uncertainty_cost:.1f} m (virtual)")
    print(f"    • Total Multi-Cost:        {result.total_cost:.1f}")
    print(f"    • Elevation Profile:       +{metrics.get('elevation_gain_m', 0.0):.1f}m / -{metrics.get('elevation_loss_m', 0.0):.1f}m (max estimated uphill: {metrics.get('max_uphill_grade_pct', 0.0):.1f}%)")
    print(f"    • Evidence Completeness:   {100.0 - metrics.get('missing_data_pct', 0.0):.1f}% known ({metrics.get('missing_data_pct', 0.0):.1f}% unrecorded)")

    print("\n[4] Deterministic Route Explanations:")
    for exp in result.explanations:
        print(f"    - {exp}")

    # Optional Folium Map Generation
    if args.map:
        from accessroute.graph.regional_cache import RegionalGraphCache

        map_path = Path(args.map)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = RegionalGraphCache()
            graph, _ = cache.load_graph(result.region_id)
            create_route_map(
                graph=graph,
                route_result=result.route,
                origin_coord=origin,
                destination_coord=dest,
                baseline_route=result.baseline_route,
                output_path=map_path,
                title=f"AccessRoute AI — Dynamic Route ({selected_policy.name.title()} Policy)",
            )
            print(f"\n[5] Visualization: Interactive route map saved to -> {map_path}")
        except Exception as exc:
            print(f"\n[5] Visualization Warning: Could not generate map: {exc}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
