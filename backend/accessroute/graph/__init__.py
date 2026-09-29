"""Graph ingestion, dynamic acquisition, regional caching, and spatial snapping modules."""

from accessroute.graph.errors import (
    AccessRouteError,
    CacheCorruptionError,
    CoordinateValidationError,
    GraphAcquisitionError,
    InsufficientCoverageError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
    RouteRegionTooLargeError,
    SnappingDistanceWarning,
)
from accessroute.graph.loader import get_pedestrian_graph, validate_graph
from accessroute.graph.manager import DynamicGraphManager, get_graph_for_route
from accessroute.graph.provider import (
    GraphProvider,
    OpenStreetMapGraphProvider,
    SyntheticGraphProvider,
)
from accessroute.graph.region import (
    DEFAULT_BUFFER_METERS,
    DEFAULT_BUFFER_RATIO,
    DEFAULT_MAX_BOUNDING_BOX_AREA_KM2,
    DEFAULT_MAX_ROUTE_DISTANCE_METERS,
    BoundingBox,
    validate_coordinates,
)
from accessroute.graph.regional_cache import (
    CURRENT_ACCESSIBILITY_VERSION,
    CURRENT_TERRAIN_VERSION,
    RegionMetadata,
    RegionalGraphCache,
)
from accessroute.graph.snapper import SnappedNode, snap_to_nearest_node

__all__ = [
    # Existing Stage 1-4 exports
    "get_pedestrian_graph",
    "validate_graph",
    "snap_to_nearest_node",
    "SnappedNode",
    # Stage 5 Dynamic Acquisition & Regional Caching
    "AccessRouteError",
    "CoordinateValidationError",
    "RouteRegionTooLargeError",
    "GraphAcquisitionError",
    "NetworkDownloadError",
    "NoPedestrianNetworkError",
    "InsufficientCoverageError",
    "CacheCorruptionError",
    "SnappingDistanceWarning",
    "BoundingBox",
    "validate_coordinates",
    "DEFAULT_BUFFER_METERS",
    "DEFAULT_BUFFER_RATIO",
    "DEFAULT_MAX_ROUTE_DISTANCE_METERS",
    "DEFAULT_MAX_BOUNDING_BOX_AREA_KM2",
    "GraphProvider",
    "OpenStreetMapGraphProvider",
    "SyntheticGraphProvider",
    "RegionMetadata",
    "RegionalGraphCache",
    "CURRENT_ACCESSIBILITY_VERSION",
    "CURRENT_TERRAIN_VERSION",
    "DynamicGraphManager",
    "get_graph_for_route",
]
