"""Elevation and terrain intelligence modules."""

from accessroute.elevation.base import (
    DEM_DEFAULT_VERTICAL_ACCURACY_M,
    ElevationProvider,
    ElevationResult,
    MIN_RELIABLE_EDGE_LENGTH_M,
    SUSPICIOUS_GRADE_THRESHOLD,
)
from accessroute.elevation.cache import CachedElevationProvider
from accessroute.elevation.enricher import (
    ElevationEnrichmentSummary,
    enrich_graph_with_elevation,
)
from accessroute.elevation.open_meteo import OpenMeteoElevationProvider
from accessroute.elevation.synthetic import SyntheticElevationProvider

__all__ = [
    "DEM_DEFAULT_VERTICAL_ACCURACY_M",
    "MIN_RELIABLE_EDGE_LENGTH_M",
    "SUSPICIOUS_GRADE_THRESHOLD",
    "ElevationProvider",
    "ElevationResult",
    "CachedElevationProvider",
    "OpenMeteoElevationProvider",
    "SyntheticElevationProvider",
    "ElevationEnrichmentSummary",
    "enrich_graph_with_elevation",
]
