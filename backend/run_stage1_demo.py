"""Stage 1 Demonstration CLI for AccessRoute AI.

Loads the Vermont South pedestrian network, snaps origin and destination coordinates,
executes the refactored A* algorithm, benchmarks against Dijkstra, and outputs
an interactive development Folium map.
"""

import argparse
import sys
import time
from pathlib import Path

# Add backend directory to sys.path so accessroute can be imported directly
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import networkx as nx
from accessroute.config import PROTOTYPE_FIXTURE_COORDINATES
from accessroute.graph.loader import get_graph_metadata, get_pedestrian_graph
from accessroute.graph.snapper import snap_to_nearest_node
from accessroute.routing.astar import a_star_search
from accessroute.visualization.map import create_route_map


def run_stage1_demo(
    orig_lat: float = -37.8568,
    orig_lon: float = 145.1735,
    dest_lat: float = -37.8587,
    dest_lon: float = 145.1785,
    force_refresh: bool = False,
    output_map_path: str = "dev_maps/vermont_south_stage1_route.html",
):
    print("=" * 70)
    print("AccessRoute AI — Stage 1 Pedestrian Routing Demonstration")
    print("=" * 70)

    # 1. Load or download the Vermont South pedestrian graph
    print("\n[1/5] Loading OpenStreetMap pedestrian graph for Vermont South...")
    start_time = time.time()
    G = get_pedestrian_graph(area_id="vermont_south", force_refresh=force_refresh)
    load_duration = time.time() - start_time
    print(f"      Graph loaded in {load_duration:.2f} seconds.")

    metadata = get_graph_metadata(G)
    print(f"      Graph Type: {metadata['graph_type']}")
    print(f"      Node Count: {metadata['node_count']:,}")
    print(f"      Edge Count: {metadata['edge_count']:,}")
    print(
        f"      Bounding Box: Lat [{metadata['bounding_box']['min_lat']:.4f}, {metadata['bounding_box']['max_lat']:.4f}], "
        f"Lon [{metadata['bounding_box']['min_lon']:.4f}, {metadata['bounding_box']['max_lon']:.4f}]"
    )

    # 2. Snap coordinates
    print(f"\n[2/5] Snapping query coordinates to pedestrian network...")
    print(f"      Origin Query: ({orig_lat:.6f}, {orig_lon:.6f})")
    print(f"      Destination Query: ({dest_lat:.6f}, {dest_lon:.6f})")

    snapped_orig = snap_to_nearest_node(G, orig_lat, orig_lon)
    snapped_dest = snap_to_nearest_node(G, dest_lat, dest_lon)

    print(
        f"      Snapped Origin: OSM Node {snapped_orig.node_id} "
        f"({snapped_orig.latitude:.6f}, {snapped_orig.longitude:.6f}) "
        f"— Snap offset: {snapped_orig.distance_meters:.1f}m"
    )
    print(
        f"      Snapped Destination: OSM Node {snapped_dest.node_id} "
        f"({snapped_dest.latitude:.6f}, {snapped_dest.longitude:.6f}) "
        f"— Snap offset: {snapped_dest.distance_meters:.1f}m"
    )

    # 3. Execute Custom A* Search
    print("\n[3/5] Calculating route with refactored A* algorithm...")
    a_star_start = time.time()
    route_result = a_star_search(G, snapped_orig.node_id, snapped_dest.node_id)
    a_star_duration = time.time() - a_star_start

    if not route_result.found:
        print(f"      ❌ {route_result.message}")
        return

    print(f"      ✅ Route Found in {a_star_duration * 1000:.2f} ms")
    print(f"      Total Distance: {route_result.total_distance_meters:.2f} meters")
    print(f"      Nodes in Path: {len(route_result.nodes)}")
    print(f"      Nodes Expanded: {route_result.nodes_expanded}")

    # 4. Correctness Benchmark vs NetworkX Dijkstra
    print("\n[4/5] Running NetworkX Dijkstra correctness benchmark...")
    dijkstra_start = time.time()
    try:
        dijkstra_len = nx.dijkstra_path_length(
            G, snapped_orig.node_id, snapped_dest.node_id, weight="length"
        )
        dijkstra_path = nx.dijkstra_path(
            G, snapped_orig.node_id, snapped_dest.node_id, weight="length"
        )
        dijkstra_duration = time.time() - dijkstra_start
        print(f"      Dijkstra Distance: {dijkstra_len:.2f} meters (computed in {dijkstra_duration * 1000:.2f} ms)")
        print(f"      Dijkstra Nodes: {len(dijkstra_path)}")

        diff = abs(route_result.total_distance_meters - dijkstra_len)
        print(f"      Difference (|A* - Dijkstra|): {diff:.4f} meters")
        if diff < 0.05:
            print("      🎯 Perfect optimality match (difference < 5cm)!")
        else:
            print(f"      ⚠️ Note: Difference is {diff:.2f}m")
    except Exception as e:
        print(f"      Dijkstra benchmark error: {e}")

    # 5. Generate Folium Interactive Route Map
    print(f"\n[5/5] Generating development Folium route map...")
    map_file = backend_dir.parent / output_map_path
    create_route_map(
        graph=G,
        route_result=route_result,
        origin_coord=(orig_lat, orig_lon),
        destination_coord=(dest_lat, dest_lon),
        snapped_origin=snapped_orig,
        snapped_destination=snapped_dest,
        output_path=map_file,
    )
    print(f"      ✅ Interactive map saved to: {map_file.resolve()}")
    print("\n" + "=" * 70)
    print("Stage 1 Demonstration Complete.")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AccessRoute AI Stage 1 Demo")
    parser.add_argument("--orig-lat", type=float, default=-37.8568, help="Origin latitude")
    parser.add_argument("--orig-lon", type=float, default=145.1735, help="Origin longitude")
    parser.add_argument("--dest-lat", type=float, default=-37.8587, help="Destination latitude")
    parser.add_argument("--dest-lon", type=float, default=145.1785, help="Destination longitude")
    parser.add_argument("--refresh", action="store_true", help="Force refresh OSM cache")
    parser.add_argument("--output", type=str, default="dev_maps/vermont_south_stage1_route.html", help="Output HTML map")
    args = parser.parse_args()

    run_stage1_demo(
        orig_lat=args.orig_lat,
        orig_lon=args.orig_lon,
        dest_lat=args.dest_lat,
        dest_lon=args.dest_lon,
        force_refresh=args.refresh,
        output_map_path=args.output,
    )
