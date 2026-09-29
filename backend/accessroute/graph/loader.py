"""OpenStreetMap pedestrian network loader with persistent GraphML caching."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import networkx as nx
import osmnx as ox

from accessroute.config import (
    ACCESSIBILITY_NODE_TAGS,
    ACCESSIBILITY_WAY_TAGS,
    AREAS,
    DEFAULT_CACHE_DIR,
    GeographicArea,
)

logger = logging.getLogger(__name__)


def validate_graph(graph: nx.MultiDiGraph) -> None:
    """Validate that a loaded or downloaded graph meets basic pedestrian routing assumptions.

    Args:
        graph: NetworkX graph to inspect.

    Raises:
        TypeError: If graph is not a networkx.MultiDiGraph.
        ValueError: If graph is empty or missing essential routing attributes.
    """
    if not isinstance(graph, nx.MultiDiGraph):
        raise TypeError(
            f"Expected networkx.MultiDiGraph, got {type(graph).__name__}. "
            "Stage 1 requires MultiDiGraph to preserve parallel pedestrian ways."
        )

    node_count = len(graph.nodes)
    edge_count = len(graph.edges)

    if node_count == 0 or edge_count == 0:
        raise ValueError(
            f"Invalid graph: empty network (nodes={node_count}, edges={edge_count})."
        )

    # Check sample of nodes for required spatial attributes (x=lon, y=lat)
    sample_nodes = list(graph.nodes(data=True))[: min(50, node_count)]
    for node_id, data in sample_nodes:
        if "x" not in data or "y" not in data:
            raise ValueError(
                f"Node {node_id} is missing spatial coordinates ('x' or 'y' attribute)."
            )

    # Check sample of edges for physical traversal length
    sample_edges = list(graph.edges(data=True))[: min(50, edge_count)]
    for u, v, data in sample_edges:
        if "length" not in data:
            raise ValueError(
                f"Edge ({u}, {v}) is missing required 'length' attribute."
            )


def get_graph_metadata(graph: nx.MultiDiGraph) -> Dict[str, Any]:
    """Extract summary metrics and accessibility tag presence from the pedestrian graph.

    Args:
        graph: The pedestrian MultiDiGraph.

    Returns:
        Dictionary containing node/edge counts, bounding box, and tag availability.
    """
    nodes_data = [data for _, data in graph.nodes(data=True)]
    lats = [d["y"] for d in nodes_data if "y" in d]
    lons = [d["x"] for d in nodes_data if "x" in d]

    bbox = {
        "min_lat": min(lats) if lats else 0.0,
        "max_lat": max(lats) if lats else 0.0,
        "min_lon": min(lons) if lons else 0.0,
        "max_lon": max(lons) if lons else 0.0,
    }

    # Count accessibility tag frequencies across edges
    tag_counts: Dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        for tag in ACCESSIBILITY_WAY_TAGS:
            if tag in data:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "graph_type": type(graph).__name__,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "bounding_box": bbox,
        "accessibility_tag_counts": tag_counts,
        "crs": graph.graph.get("crs", "EPSG:4326"),
    }


def get_pedestrian_graph(
    area_id: str = "vermont_south",
    force_refresh: bool = False,
    cache_dir: Optional[Path] = None,
) -> nx.MultiDiGraph:
    """Retrieve the pedestrian graph for a specified area using local cache or OSMnx.

    Behaviour:
    - If cache exists and force_refresh is False: Loads locally from disk (< 200ms).
    - If cache missing or force_refresh is True:
        1. Configures OSMnx to preserve all accessibility-relevant tags.
        2. Queries OpenStreetMap pedestrian network (network_type='walk').
        3. Validates graph structure and attributes.
        4. Serializes graph to GraphML in the local cache.
        5. Returns the MultiDiGraph.

    Args:
        area_id: Key identifying the configured area (e.g. 'vermont_south').
        force_refresh: If True, bypasses cache and re-downloads from OSM.
        cache_dir: Optional override for cache directory path.

    Returns:
        Validated networkx.MultiDiGraph.
    """
    if area_id not in AREAS:
        available = ", ".join(AREAS.keys())
        raise ValueError(
            f"Unknown area_id '{area_id}'. Available areas: {available}"
        )

    area: GeographicArea = AREAS[area_id]
    target_cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    target_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = target_cache_dir / f"{area_id}_walk.graphml"

    # Step 1: Attempt to load from local cache
    if cache_file.exists() and not force_refresh:
        logger.info(f"Loading cached pedestrian graph from {cache_file}")
        try:
            G = ox.load_graphml(filepath=cache_file)
            validate_graph(G)
            return G
        except Exception as e:
            logger.warning(
                f"Failed to load or validate cache ({cache_file}): {e}. Re-downloading from OSM..."
            )

    # Step 2: Download fresh graph via OSMnx
    logger.info(
        f"Downloading pedestrian graph for {area.name} (radius={area.radius_meters}m) from OpenStreetMap..."
    )

    # Configure OSMnx to preserve accessibility tags on ways and nodes
    ox.settings.useful_tags_way = list(
        set(ox.settings.useful_tags_way + ACCESSIBILITY_WAY_TAGS)
    )
    ox.settings.useful_tags_node = list(
        set(ox.settings.useful_tags_node + ACCESSIBILITY_NODE_TAGS)
    )

    G = ox.graph_from_point(
        center_point=(area.latitude, area.longitude),
        dist=area.radius_meters,
        dist_type="bbox",
        network_type="walk",
        retain_all=False,
        simplify=True,
    )

    # Validate downloaded graph
    validate_graph(G)

    # Save to local cache
    try:
        ox.save_graphml(G, filepath=cache_file)
        logger.info(f"Successfully cached pedestrian graph to {cache_file}")
    except Exception as e:
        logger.warning(f"Could not write graph to cache ({cache_file}): {e}")

    return G
