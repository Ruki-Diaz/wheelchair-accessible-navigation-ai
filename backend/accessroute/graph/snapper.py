"""Spatial snapping of geographic coordinates to the pedestrian network."""

from dataclasses import dataclass
from typing import Tuple
import networkx as nx
import osmnx as ox

from accessroute.graph.region import haversine_distance


@dataclass(frozen=True)
class SnappedNode:
    """Represents the result of snapping a coordinate to the nearest pedestrian network node."""
    node_id: int
    latitude: float
    longitude: float
    distance_meters: float
    query_latitude: float
    query_longitude: float


def snap_to_nearest_node(
    graph: nx.MultiDiGraph,
    latitude: float,
    longitude: float,
) -> SnappedNode:
    """Find the nearest pedestrian network node to the given coordinates.

    Leverages OSMnx's spatial indexing (BallTree / k-d tree) for efficient lookup,
    and computes the exact great-circle distance in meters from the query point.

    Args:
        graph: NetworkX MultiDiGraph containing pedestrian ways and nodes.
        latitude: Query point latitude in decimal degrees.
        longitude: Query point longitude in decimal degrees.

    Returns:
        SnappedNode with node ID, node coordinates, and snapping distance in meters.

    Raises:
        ValueError: If graph is empty or has no nodes.
    """
    if len(graph.nodes) == 0:
        raise ValueError("Cannot snap coordinate to an empty graph.")

    if "crs" not in graph.graph:
        graph.graph["crs"] = "EPSG:4326"

    # OSMnx nearest_nodes expects X (longitude), Y (latitude)
    nearest_node_id = ox.distance.nearest_nodes(
        graph, X=float(longitude), Y=float(latitude), return_dist=False
    )
    # Ensure standard Python int for the node ID
    nearest_node_id = int(nearest_node_id)

    node_data = graph.nodes[nearest_node_id]
    node_lat = float(node_data["y"])
    node_lon = float(node_data["x"])

    dist_meters = haversine_distance(latitude, longitude, node_lat, node_lon)

    return SnappedNode(
        node_id=nearest_node_id,
        latitude=node_lat,
        longitude=node_lon,
        distance_meters=dist_meters,
        query_latitude=latitude,
        query_longitude=longitude,
    )
