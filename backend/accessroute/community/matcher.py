"""Spatial matching layer linking community reports to OpenStreetMap nodes and ways.

Stage 9 Architecture:
Given a submitted point (latitude, longitude, category):
1. Identifies the nearest relevant OSM node or edge within a configurable distance threshold.
2. Computes the perpendicular or point-to-point distance and matching confidence.
3. If beyond the distance threshold, explicitly preserves the observation as UNMATCHED
   rather than making false assumptions.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx
from shapely.geometry import LineString, Point


@dataclass
class MatchResult:
    """Outcome of spatial snapping for a community observation."""
    is_matched: bool
    osm_element_type: Optional[str] = None  # 'way' | 'node' | None
    osm_element_id: Optional[int] = None
    distance_m: Optional[float] = None
    match_confidence: Optional[float] = None
    matched_u: Optional[int] = None
    matched_v: Optional[int] = None
    matched_key: Optional[int] = None


class CommunitySpatialMatcher:
    """Matches coordinates to physical OpenStreetMap network infrastructure."""

    def __init__(self, max_match_distance_m: float = 30.0):
        """Initialize matcher with distance threshold.

        Args:
            max_match_distance_m: Maximum acceptable distance in meters to attach to OSM element.
        """
        self.max_match_distance_m = max_match_distance_m

    def match_point_to_graph(
        self,
        latitude: float,
        longitude: float,
        graph: nx.MultiDiGraph,
        category: Optional[str] = None,
    ) -> MatchResult:
        """Snap a geographic observation coordinate to the nearest edge or node in a pedestrian graph.

        Args:
            latitude: WGS-84 latitude.
            longitude: WGS-84 longitude.
            graph: NetworkX MultiDiGraph with node x, y attributes and edge geometries.
            category: Optional observation category to guide node vs way snapping priority.

        Returns:
            MatchResult containing match details or explicitly unmatched indicator.
        """
        if graph is None or len(graph.nodes) == 0:
            return MatchResult(is_matched=False)

        best_edge_dist = float("inf")
        best_edge_info: Optional[Tuple[int, int, Any, Dict[str, Any]]] = None

        best_node_dist = float("inf")
        best_node_id: Optional[int] = None

        pt = Point(longitude, latitude)

        # 1. Check nearest node
        for node_id, data in graph.nodes(data=True):
            nx_lat = data.get("y")
            nx_lon = data.get("x")
            if nx_lat is None or nx_lon is None:
                continue
            dist_m = self._haversine(latitude, longitude, nx_lat, nx_lon)
            if dist_m < best_node_dist:
                best_node_dist = dist_m
                best_node_id = node_id

        # 2. Check nearest edge geometry
        for u, v, k, data in graph.edges(keys=True, data=True):
            geom = data.get("geometry")
            if geom is not None and isinstance(geom, LineString):
                # Approximate distance via Shapely projection in local meters
                # 1 deg lat ~ 111,320m; 1 deg lon ~ 111,320m * cos(lat)
                cos_lat = math.cos(math.radians(latitude))
                pt_m = Point(longitude * 111320.0 * cos_lat, latitude * 111320.0)
                coords_m = [(x * 111320.0 * cos_lat, y * 111320.0) for x, y in geom.coords]
                geom_m = LineString(coords_m)
                dist_m = pt_m.distance(geom_m)
            else:
                u_lat, u_lon = graph.nodes[u]["y"], graph.nodes[u]["x"]
                v_lat, v_lon = graph.nodes[v]["y"], graph.nodes[v]["x"]
                dist_m = self._point_to_segment_distance_m(latitude, longitude, u_lat, u_lon, v_lat, v_lon)

            if dist_m < best_edge_dist:
                best_edge_dist = dist_m
                best_edge_info = (u, v, k, data)

        # Category affinity: Kerb, Lift, and Entrance tend to attach to nodes/crossings,
        # while Surface, Slope, and Path Blocked attach to edges/ways.
        prefer_node = category in ("kerb", "lift_status", "entrance_accessibility")

        if prefer_node and best_node_dist <= self.max_match_distance_m and best_node_dist <= best_edge_dist * 1.5:
            conf = round(max(0.1, 1.0 - (best_node_dist / self.max_match_distance_m)), 2)
            return MatchResult(
                is_matched=True,
                osm_element_type="node",
                osm_element_id=best_node_id,
                distance_m=round(best_node_dist, 1),
                match_confidence=conf,
                matched_u=best_node_id,
            )

        if best_edge_dist <= self.max_match_distance_m and best_edge_info is not None:
            u, v, k, data = best_edge_info
            osmid = data.get("osmid")
            if isinstance(osmid, list) and len(osmid) > 0:
                osmid = osmid[0]
            try:
                way_id = int(osmid) if osmid is not None else None
            except (ValueError, TypeError):
                way_id = None

            conf = round(max(0.1, 1.0 - (best_edge_dist / self.max_match_distance_m)), 2)
            return MatchResult(
                is_matched=True,
                osm_element_type="way",
                osm_element_id=way_id,
                distance_m=round(best_edge_dist, 1),
                match_confidence=conf,
                matched_u=u,
                matched_v=v,
                matched_key=k,
            )

        if best_node_dist <= self.max_match_distance_m:
            conf = round(max(0.1, 1.0 - (best_node_dist / self.max_match_distance_m)), 2)
            return MatchResult(
                is_matched=True,
                osm_element_type="node",
                osm_element_id=best_node_id,
                distance_m=round(best_node_dist, 1),
                match_confidence=conf,
                matched_u=best_node_id,
            )

        # Beyond threshold -> preserved as geographically located but unmatched
        return MatchResult(
            is_matched=False,
            distance_m=round(min(best_edge_dist, best_node_dist), 1),
            match_confidence=0.0,
        )

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    @staticmethod
    def _point_to_segment_distance_m(
        plat: float, plon: float, ulat: float, ulon: float, vlat: float, vlon: float
    ) -> float:
        """Distance in meters from point P to segment U-V."""
        cos_lat = math.cos(math.radians(plat))
        px, py = plon * 111320.0 * cos_lat, plat * 111320.0
        ux, uy = ulon * 111320.0 * cos_lat, ulat * 111320.0
        vx, vy = vlon * 111320.0 * cos_lat, vlat * 111320.0

        dx = vx - ux
        dy = vy - uy
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-6:
            return math.hypot(px - ux, py - uy)

        t = max(0.0, min(1.0, ((px - ux) * dx + (py - uy) * dy) / seg_len_sq))
        proj_x = ux + t * dx
        proj_y = uy + t * dy
        return math.hypot(px - proj_x, py - proj_y)
