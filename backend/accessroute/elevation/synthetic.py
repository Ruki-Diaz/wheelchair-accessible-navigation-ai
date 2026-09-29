"""Synthetic and deterministic mock elevation provider for offline unit testing and experiments."""

from typing import Callable, Dict, List, Optional, Sequence, Tuple
from accessroute.elevation.base import ElevationProvider


class SyntheticElevationProvider(ElevationProvider):
    """Deterministic elevation provider for testing and controlled experiments.

    Can supply elevations via an explicit lookup dictionary, a mathematical slope function,
    or a constant default elevation.
    """

    def __init__(
        self,
        elevation_map: Optional[Dict[Tuple[float, float], Optional[float]]] = None,
        gradient_fn: Optional[Callable[[float, float], Optional[float]]] = None,
        default_elevation: Optional[float] = None,
        source_name: str = "synthetic:deterministic",
        resolution_meters: float = 1.0,
        vertical_accuracy_meters: float = 0.05,
    ):
        self._elevation_map = elevation_map or {}
        self._gradient_fn = gradient_fn
        self._default_elevation = default_elevation
        self._source_name = source_name
        self._resolution_meters = resolution_meters
        self._vertical_accuracy_meters = vertical_accuracy_meters

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def resolution_meters(self) -> float:
        return self._resolution_meters

    @property
    def vertical_accuracy_meters(self) -> float:
        return self._vertical_accuracy_meters

    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]:
        # 1. Check exact dictionary
        key = (latitude, longitude)
        if key in self._elevation_map:
            return self._elevation_map[key]

        # Check rounded dictionary (6 decimals)
        rounded_key = (round(latitude, 6), round(longitude, 6))
        if rounded_key in self._elevation_map:
            return self._elevation_map[rounded_key]

        # 2. Check gradient function
        if self._gradient_fn is not None:
            return self._gradient_fn(latitude, longitude)

        # 3. Fallback to default
        return self._default_elevation

    def get_elevations(
        self, coordinates: Sequence[Tuple[float, float]]
    ) -> List[Optional[float]]:
        return [self.get_elevation(lat, lon) for lat, lon in coordinates]
