"""Interactive route elevation profile generator for AccessRoute AI.

Interpolates and samples elevation points along route geometry to provide
distance-versus-elevation profiles, cumulative vertical statistics,
and map-chart coordinate synchronization.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx
from shapely.geometry import LineString


@dataclass
class ElevationPoint:
    """Individual elevation coordinate along a route's distance progression."""

    distance_m: float
    elevation_m: float
    latitude: float
    longitude: float
    grade_pct: Optional[float] = None


@dataclass
class RouteElevationSummary:
    """Complete elevation profile and terrain statistics for a route."""

    points: List[ElevationPoint]
    elevation_gain_m: float
    elevation_loss_m: float
    max_uphill_grade_pct: float
    max_downhill_grade_pct: float
    min_elevation_m: float
    max_elevation_m: float
    elevation_source: str = "Copernicus GLO-30 DEM (30m)"


def generate_elevation_profile(
    nodes: List[int],
    edges: List[Dict[str, Any]],
    geometries: Optional[List[Any]] = None,
    graph: Optional[nx.MultiDiGraph] = None,
) -> RouteElevationSummary:
    """Generate distance-versus-elevation points and statistics for a route.

    Args:
        nodes: Sequence of node IDs in traversal order.
        edges: Edge attribute dictionaries for each step.
        geometries: Optional sequence of Shapely LineStrings corresponding to each edge.
        graph: Optional NetworkX graph to look up node coordinates and elevations.

    Returns:
        RouteElevationSummary containing sampled points and cumulative metrics.
    """
    if not edges or len(nodes) < 2:
        return RouteElevationSummary(
            points=[],
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            max_uphill_grade_pct=0.0,
            max_downhill_grade_pct=0.0,
            min_elevation_m=0.0,
            max_elevation_m=0.0,
        )

    # Helper to resolve node elevation and coordinate
    def get_node_info(node_id: int) -> Tuple[float, float, float]:
        lat, lon, elev = 0.0, 0.0, 0.0
        if graph is not None and node_id in graph:
            node_data = graph.nodes[node_id]
            lat = float(node_data.get("y", 0.0))
            lon = float(node_data.get("x", 0.0))
            elev_val = node_data.get("elevation_m")
            if elev_val is not None:
                elev = float(elev_val)
        return lat, lon, elev

    # Start at origin
    first_lat, first_lon, first_elev = get_node_info(nodes[0])
    points: List[ElevationPoint] = [
        ElevationPoint(
            distance_m=0.0,
            elevation_m=round(first_elev, 1),
            latitude=round(first_lat, 6),
            longitude=round(first_lon, 6),
            grade_pct=0.0,
        )
    ]

    cumulative_distance = 0.0
    cumulative_gain = 0.0
    cumulative_loss = 0.0
    max_uphill = 0.0
    max_downhill = 0.0
    all_elevations: List[float] = [first_elev]

    for idx, edge_data in enumerate(edges):
        u = nodes[idx]
        v = nodes[idx + 1]
        u_lat, u_lon, u_elev = get_node_info(u)
        v_lat, v_lon, v_elev = get_node_info(v)

        length_m = float(edge_data.get("length", 1.0))
        geom = geometries[idx] if geometries and idx < len(geometries) else edge_data.get("geometry")

        delta_elev = v_elev - u_elev
        if delta_elev > 0:
            cumulative_gain += delta_elev
        else:
            cumulative_loss += abs(delta_elev)

        grade_pct = (delta_elev / max(length_m, 0.5)) * 100.0
        if grade_pct > max_uphill:
            max_uphill = grade_pct
        if grade_pct < -max_downhill:
            max_downhill = abs(grade_pct)

        # Check if curved geometry provides intermediate coordinates
        if geom is not None and hasattr(geom, "coords") and len(geom.coords) > 2:
            num_coords = len(geom.coords)
            seg_len_step = length_m / (num_coords - 1)
            for c_idx in range(1, num_coords):
                frac = c_idx / (num_coords - 1)
                interp_elev = u_elev + frac * delta_elev
                curr_dist = cumulative_distance + c_idx * seg_len_step
                lon_c, lat_c = geom.coords[c_idx]
                points.append(
                    ElevationPoint(
                        distance_m=round(curr_dist, 1),
                        elevation_m=round(interp_elev, 1),
                        latitude=round(float(lat_c), 6),
                        longitude=round(float(lon_c), 6),
                        grade_pct=round(grade_pct, 1),
                    )
                )
                all_elevations.append(interp_elev)
        else:
            # Single straight step to v
            curr_dist = cumulative_distance + length_m
            points.append(
                ElevationPoint(
                    distance_m=round(curr_dist, 1),
                    elevation_m=round(v_elev, 1),
                    latitude=round(v_lat, 6),
                    longitude=round(v_lon, 6),
                    grade_pct=round(grade_pct, 1),
                )
            )
            all_elevations.append(v_elev)

        cumulative_distance += length_m

    min_elev = min(all_elevations) if all_elevations else 0.0
    max_elev = max(all_elevations) if all_elevations else 0.0

    return RouteElevationSummary(
        points=points,
        elevation_gain_m=round(cumulative_gain, 1),
        elevation_loss_m=round(cumulative_loss, 1),
        max_uphill_grade_pct=round(max_uphill, 1),
        max_downhill_grade_pct=round(max_downhill, 1),
        min_elevation_m=round(min_elev, 1),
        max_elevation_m=round(max_elev, 1),
        elevation_source="Copernicus GLO-30 DEM (30m)",
    )
