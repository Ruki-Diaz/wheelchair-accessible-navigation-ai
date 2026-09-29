"""Graph provider abstraction for pedestrian network acquisition."""

from abc import ABC, abstractmethod
import logging
from typing import Optional
import networkx as nx
import osmnx as ox

from accessroute.config import ACCESSIBILITY_NODE_TAGS, ACCESSIBILITY_WAY_TAGS
from accessroute.graph.errors import (
    GraphAcquisitionError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
)
from accessroute.graph.loader import validate_graph
from accessroute.graph.region import BoundingBox

logger = logging.getLogger(__name__)


class GraphProvider(ABC):
    """Abstract interface for acquiring pedestrian graphs across geographic regions."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifying name of the network source."""
        pass

    @abstractmethod
    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        """Download or construct a pedestrian MultiDiGraph for the specified bounding box.

        Args:
            bbox: Geographic bounding box to query.

        Returns:
            Validated networkx.MultiDiGraph with pedestrian nodes and ways.

        Raises:
            NetworkDownloadError: If external network request fails or times out.
            NoPedestrianNetworkError: If the region contains no walkable edges.
            GraphAcquisitionError: On other unexpected acquisition failures.
        """
        pass


class OpenStreetMapGraphProvider(GraphProvider):
    """Acquires pedestrian networks directly from OpenStreetMap via OSMnx/Overpass."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "openstreetmap:walk"

    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        logger.info(
            "Querying OpenStreetMap pedestrian network for bbox: S=%.4f, W=%.4f, N=%.4f, E=%.4f (area=%.2f km²)...",
            bbox.south,
            bbox.west,
            bbox.north,
            bbox.east,
            bbox.area_km2,
        )

        # Configure OSMnx to preserve all accessibility tags
        ox.settings.useful_tags_way = list(
            set(ox.settings.useful_tags_way + ACCESSIBILITY_WAY_TAGS)
        )
        ox.settings.useful_tags_node = list(
            set(ox.settings.useful_tags_node + ACCESSIBILITY_NODE_TAGS)
        )
        ox.settings.requests_timeout = self._timeout_seconds
        ox.settings.overpass_rate_limit = False

        try:
            # OSMnx 2.x expects bbox as (left, bottom, right, top) = (west, south, east, north)
            osmnx_bbox = bbox.as_osmnx_bbox()
            G = ox.graph_from_bbox(
                bbox=osmnx_bbox,
                network_type="walk",
                simplify=True,
                retain_all=False,
            )
        except ox._errors.EmptyOverpassResponse as exc:
            raise NoPedestrianNetworkError(
                f"No pedestrian network found within requested region: {bbox.to_dict()}."
            ) from exc
        except (ox._errors.Response200Error, TimeoutError, ConnectionError) as exc:
            raise NetworkDownloadError(
                f"Failed to download network from OpenStreetMap/Overpass: {exc}"
            ) from exc
        except Exception as exc:
            # Check for empty response or connection errors wrapped in other exceptions
            msg = str(exc).lower()
            if "empty" in msg or "no data" in msg:
                raise NoPedestrianNetworkError(
                    f"No walkable paths found in region: {bbox.to_dict()}."
                ) from exc
            if "timeout" in msg or "connection" in msg:
                raise NetworkDownloadError(
                    f"OpenStreetMap query timed out or connection failed: {exc}"
                ) from exc
            raise GraphAcquisitionError(f"Unexpected OSM graph acquisition failure: {exc}") from exc

        try:
            validate_graph(G)
        except Exception as exc:
            raise GraphAcquisitionError(f"Downloaded graph failed validation: {exc}") from exc

        return G


class SyntheticGraphProvider(GraphProvider):
    """Deterministic offline graph provider for testing without external network calls."""

    def __init__(self, template_graph: Optional[nx.MultiDiGraph] = None) -> None:
        self._template = template_graph

    @property
    def provider_name(self) -> str:
        return "synthetic:offline_test"

    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        if self._template is not None:
            return self._template.copy()

        # Build a minimal synthetic 4-node grid centered within the bbox
        G = nx.MultiDiGraph()
        G.graph["crs"] = "EPSG:4326"
        c_lat, c_lon = bbox.center
        d_lat = 0.001
        d_lon = 0.001

        nodes = {
            1: {"y": c_lat - d_lat, "x": c_lon - d_lon},
            2: {"y": c_lat - d_lat, "x": c_lon + d_lon},
            3: {"y": c_lat + d_lat, "x": c_lon + d_lon},
            4: {"y": c_lat + d_lat, "x": c_lon - d_lon},
        }
        for n_id, data in nodes.items():
            G.add_node(n_id, **data)

        edges = [
            (1, 2, 100.0, "paved"),
            (2, 1, 100.0, "paved"),
            (2, 3, 100.0, "paved"),
            (3, 2, 100.0, "paved"),
            (3, 4, 100.0, "paved"),
            (4, 3, 100.0, "paved"),
            (4, 1, 100.0, "paved"),
            (1, 4, 100.0, "paved"),
            (1, 3, 141.4, "gravel"),
            (3, 1, 141.4, "gravel"),
        ]
        for u, v, length, surface in edges:
            G.add_edge(u, v, key=0, length=length, surface=surface, highway="footway")

        validate_graph(G)
        return G
