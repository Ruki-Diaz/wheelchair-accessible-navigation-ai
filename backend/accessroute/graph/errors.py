"""Domain exceptions for coordinate validation, graph acquisition, and caching."""


class AccessRouteError(Exception):
    """Base exception for all AccessRoute errors."""
    pass


class CoordinateValidationError(AccessRouteError):
    """Raised when query coordinates are geographically invalid or physically ill-formed."""
    pass


class RouteRegionTooLargeError(AccessRouteError):
    """Raised when requested route coordinates exceed operational development limits."""
    pass


class GraphAcquisitionError(AccessRouteError):
    """Base exception for graph acquisition failures."""
    pass


class NetworkDownloadError(GraphAcquisitionError):
    """Raised when an external geospatial provider (e.g. Overpass / OSMnx) fails to download."""
    pass


class NoPedestrianNetworkError(GraphAcquisitionError):
    """Raised when the queried bounding box contains no walkable pedestrian ways."""
    pass


class InsufficientCoverageError(GraphAcquisitionError):
    """Raised when a cached or provided network does not sufficiently cover query coordinates."""
    pass


class CacheCorruptionError(AccessRouteError):
    """Raised when a cached regional graph or metadata file is unreadable or malformed."""
    pass


class SnappingDistanceWarning(AccessRouteError):
    """Raised or flagged when query point is far from any mapped pedestrian pathway."""
    pass
