"""Development map visualizer using Folium supporting comparative multi-criteria routes."""

from pathlib import Path
from typing import Optional, Tuple
import folium
from folium import plugins
import networkx as nx
from shapely.geometry import LineString

from accessroute.graph.snapper import SnappedNode
from accessroute.routing.astar import RouteResult


def create_route_map(
    graph: nx.MultiDiGraph,
    route_result: RouteResult,
    origin_coord: Tuple[float, float],
    destination_coord: Tuple[float, float],
    baseline_route: Optional[RouteResult] = None,
    snapped_origin: Optional[SnappedNode] = None,
    snapped_destination: Optional[SnappedNode] = None,
    output_path: Optional[Path | str] = None,
    title: str = "AccessRoute AI — Accessibility-Aware Route",
) -> folium.Map:
    """Generate an interactive Folium map comparing baseline and accessibility-aware routes.

    Renders:
    - Real OpenStreetMap cartography basemap
    - Exact query origin and destination markers
    - Snapped network node locations with dotted lead lines
    - Baseline shortest path (orange dashed line, if provided)
    - Accessibility-aware route (blue solid line along true curved OSM footpath geometries)
    - Comprehensive comparative HUD card displaying distance delta, barriers avoided, and uncertainty

    Args:
        graph: NetworkX pedestrian MultiDiGraph.
        route_result: Output from a_star_search for the accessible route.
        origin_coord: (latitude, longitude) of original user origin.
        destination_coord: (latitude, longitude) of original user destination.
        baseline_route: Optional RouteResult from unconstrained shortest path for comparison.
        snapped_origin: Optional SnappedNode for the start.
        snapped_destination: Optional SnappedNode for the goal.
        output_path: Filepath where HTML map should be saved.
        title: Title string shown on the map header.

    Returns:
        Configured folium.Map instance.
    """
    orig_lat, orig_lon = origin_coord
    dest_lat, dest_lon = destination_coord

    center_lat = (orig_lat + dest_lat) / 2.0
    center_lon = (orig_lon + dest_lon) / 2.0

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=16,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # 1. Query Origin Marker
    folium.Marker(
        location=[orig_lat, orig_lon],
        popup=f"<b>Query Origin</b><br>Lat: {orig_lat:.6f}<br>Lon: {orig_lon:.6f}",
        tooltip="Origin (Query Point)",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)

    # 2. Query Destination Marker
    folium.Marker(
        location=[dest_lat, dest_lon],
        popup=f"<b>Query Destination</b><br>Lat: {dest_lat:.6f}<br>Lon: {dest_lon:.6f}",
        tooltip="Destination (Query Point)",
        icon=folium.Icon(color="red", icon="flag", prefix="fa"),
    ).add_to(m)

    # 3. Snapped Origin Marker & Connector
    if snapped_origin:
        folium.CircleMarker(
            location=[snapped_origin.latitude, snapped_origin.longitude],
            radius=6,
            color="#059669",
            fill=True,
            fill_color="#10B981",
            fill_opacity=0.9,
            popup=(
                f"<b>Snapped Origin Node</b><br>"
                f"OSM ID: {snapped_origin.node_id}<br>"
                f"Snap Distance: {snapped_origin.distance_meters:.1f}m"
            ),
            tooltip=f"Snapped Origin (OSM: {snapped_origin.node_id})",
        ).add_to(m)

        folium.PolyLine(
            locations=[
                [orig_lat, orig_lon],
                [snapped_origin.latitude, snapped_origin.longitude],
            ],
            color="#059669",
            weight=3,
            dash_array="5, 5",
            opacity=0.7,
            tooltip=f"Origin Snapping Offset: {snapped_origin.distance_meters:.1f}m",
        ).add_to(m)

    # 4. Snapped Destination Marker & Connector
    if snapped_destination:
        folium.CircleMarker(
            location=[snapped_destination.latitude, snapped_destination.longitude],
            radius=6,
            color="#DC2626",
            fill=True,
            fill_color="#EF4444",
            fill_opacity=0.9,
            popup=(
                f"<b>Snapped Destination Node</b><br>"
                f"OSM ID: {snapped_destination.node_id}<br>"
                f"Snap Distance: {snapped_destination.distance_meters:.1f}m"
            ),
            tooltip=f"Snapped Destination (OSM: {snapped_destination.node_id})",
        ).add_to(m)

        folium.PolyLine(
            locations=[
                [dest_lat, dest_lon],
                [snapped_destination.latitude, snapped_destination.longitude],
            ],
            color="#DC2626",
            weight=3,
            dash_array="5, 5",
            opacity=0.7,
            tooltip=f"Destination Snapping Offset: {snapped_destination.distance_meters:.1f}m",
        ).add_to(m)

    # 5. Render Baseline Shortest Route (if provided)
    if baseline_route and baseline_route.found and baseline_route.geometries:
        base_group = folium.FeatureGroup(
            name=f"Baseline Shortest Route ({baseline_route.total_distance_meters:.1f}m)",
            show=True,
        )
        for geom in baseline_route.geometries:
            if isinstance(geom, LineString):
                coords = [[lat, lon] for lon, lat in geom.coords]
                folium.PolyLine(
                    locations=coords,
                    color="#F59E0B",  # Amber/Orange dashed line
                    weight=5,
                    dash_array="7, 7",
                    opacity=0.75,
                    tooltip=f"Baseline Shortest Segment (Total: {baseline_route.total_distance_meters:.1f}m)",
                ).add_to(base_group)
        base_group.add_to(m)

    # 6. Render Accessibility-Aware Route
    if route_result.found and route_result.geometries:
        acc_label = (
            f"Accessibility-Aware Route ({route_result.total_distance_meters:.1f}m)"
        )
        route_group = folium.FeatureGroup(name=acc_label, show=True)

        for geom in route_result.geometries:
            if isinstance(geom, LineString):
                coords = [[lat, lon] for lon, lat in geom.coords]
                folium.PolyLine(
                    locations=coords,
                    color="#2563EB",  # Vibrant blue solid line
                    weight=6,
                    opacity=0.9,
                    tooltip=f"Accessible Footpath (Total: {route_result.total_distance_meters:.1f}m)",
                ).add_to(route_group)

        route_group.add_to(m)

    # Layer control for toggling between baseline and accessible route
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    # 7. Comparative Information Overlay Header (Floating HTML Card)
    status_color = "#10B981" if route_result.found else "#EF4444"
    status_text = "Route Found" if route_result.found else "No Route"

    # Comparison metrics
    comp_html = ""
    if baseline_route and baseline_route.found:
        diff_m = route_result.total_distance_meters - baseline_route.total_distance_meters
        diff_pct = (
            (diff_m / baseline_route.total_distance_meters * 100.0)
            if baseline_route.total_distance_meters > 0
            else 0.0
        )
        comp_html = f"""
        <div style="background: #F8FAFC; border: 1px solid #E2E8F0; padding: 8px 10px; border-radius: 6px; margin: 8px 0;">
            <div style="display: flex; justify-content: space-between; font-size: 12px;">
                <span><b>Baseline (Shortest):</b></span>
                <span style="color: #D97706; font-weight: bold;">{baseline_route.total_distance_meters:.1f}m</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; margin-top: 2px;">
                <span><b>Accessible Route:</b></span>
                <span style="color: #2563EB; font-weight: bold;">{route_result.total_distance_meters:.1f}m</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 4px; color: #64748B;">
                <span>Distance Delta:</span>
                <span>+{diff_m:.1f}m (+{diff_pct:.1f}%)</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 2px; color: #475569;">
                <span>Terrain Profile:</span>
                <span>+{route_result.metrics.get('elevation_gain_m', 0.0):.1f}m climb | Max {route_result.metrics.get('max_uphill_grade_pct', 0.0):.1f}%</span>
            </div>
        </div>
        """

    # Explanation bullets
    exp_items = "".join(
        f"<li style='margin-bottom: 3px;'>{exp}</li>"
        for exp in route_result.explanations[:4]
    )
    exp_html = f"<ul style='margin: 6px 0 0 0; padding-left: 18px; font-size: 11.5px; color: #334155;'>{exp_items}</ul>" if exp_items else ""

    info_html = f"""
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(8px);
        padding: 16px 20px;
        border-radius: 10px;
        box-shadow: 0 4px 18px rgba(0,0,0,0.22);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        max-width: 420px;
        font-size: 13px;
        line-height: 1.45;
        border-left: 5px solid {status_color};
    ">
        <h3 style="margin: 0 0 4px 0; font-size: 15px; color: #1E293B;">{title}</h3>
        <div style="font-size: 11px; color: #64748B; margin-bottom: 6px;">
            Policy: <b>{route_result.policy_name.upper()}</b> | Status: <b style="color: {status_color};">{status_text}</b>
        </div>
        {comp_html}
        {exp_html}
        <div style="font-size: 11px; color: #64748B; background: #F1F5F9; padding: 6px 8px; border-radius: 6px; margin-top: 8px;">
            ℹ️ <b>Accessibility Notice:</b> Accessibility-aware route based on available map evidence. Physical conditions and temporary obstacles may vary.
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        m.save(str(out))

    return m
