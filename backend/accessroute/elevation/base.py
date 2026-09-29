"""Abstract base class and core contracts for elevation providers.

Allows AccessRoute AI to source elevation data from different backends (Copernicus DEM,
local raster GeoTIFFs, national services like ELVIS, or synthetic test providers) without
coupling routing or spatial domain logic to an external vendor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# Quality and reliability constants
MIN_RELIABLE_EDGE_LENGTH_M = 10.0  # Edges shorter than this risk exaggerated slopes due to DEM grid jitter
DEM_DEFAULT_VERTICAL_ACCURACY_M = 1.5  # Typical vertical accuracy for 30m Copernicus DEM
SUSPICIOUS_GRADE_THRESHOLD = 0.25  # Absolute grade > 25% on non-stair pedestrian ways flagged as suspicious


@dataclass(frozen=True)
class ElevationResult:
    """Elevation lookup result for a geographic coordinate."""
    latitude: float
    longitude: float
    elevation_m: Optional[float]
    source: str
    status: str  # "MEASURED", "INTERPOLATED", "MISSING"
    resolution_m: Optional[float] = None

    @property
    def is_known(self) -> bool:
        return self.elevation_m is not None and self.status != "MISSING"


class ElevationProvider(ABC):
    """Abstract interface for elevation retrieval services."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifying name of the elevation source/dataset."""
        ...

    @property
    def resolution_meters(self) -> float:
        """Nominal horizontal grid resolution in meters (e.g. 30.0 for Copernicus GLO-30)."""
        return 30.0

    @property
    def vertical_accuracy_meters(self) -> float:
        """Estimated vertical accuracy (1-sigma) in meters."""
        return DEM_DEFAULT_VERTICAL_ACCURACY_M

    @abstractmethod
    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]:
        """Retrieve elevation in meters above sea level for a single coordinate point.

        Args:
            latitude: WGS84 latitude.
            longitude: WGS84 longitude.

        Returns:
            Elevation in meters, or None if unavailable.
        """
        ...

    @abstractmethod
    def get_elevations(
        self, coordinates: Sequence[Tuple[float, float]]
    ) -> List[Optional[float]]:
        """Batch retrieve elevations in meters for an ordered sequence of (lat, lon) coordinates.

        Implementations should perform bulk queries where supported by the underlying API.

        Args:
            coordinates: Sequence of (latitude, longitude) tuples.

        Returns:
            List of elevation values in meters (or None where missing), matching input order.
        """
        ...
