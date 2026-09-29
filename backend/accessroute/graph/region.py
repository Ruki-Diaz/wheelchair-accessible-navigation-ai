from dataclasses import dataclass
import hashlib
import math
from typing import Any, Dict, Tuple

from accessroute.graph.errors import CoordinateValidationError, RouteRegionTooLargeError

# Mean Earth radius in meters (WGS84 spherical approximation)
EARTH_RADIUS_METERS = 6371000.0


def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate the great-circle distance in meters between two points on Earth."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    sin_half_dphi = math.sin(delta_phi / 2.0)
    sin_half_dlambda = math.sin(delta_lambda / 2.0)

    a = (
        sin_half_dphi * sin_half_dphi
        + math.cos(phi1) * math.cos(phi2) * sin_half_dlambda * sin_half_dlambda
    )
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


# Operational development limits to prevent accidental multi-gigabyte queries
DEFAULT_MAX_ROUTE_DISTANCE_METERS = 10000.0  # 10 km straight-line separation
DEFAULT_MAX_BOUNDING_BOX_AREA_KM2 = 50.0     # 50 km² bounding region
DEFAULT_BUFFER_METERS = 350.0                # 350m safety margin around endpoints
DEFAULT_BUFFER_RATIO = 0.25                  # 25% of O-D distance as additional margin


def validate_coordinates(lat: float, lon: float, name: str = "coordinate") -> None:
    """Validate that coordinates are physically meaningful decimal degrees.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        name: Name of the point for descriptive error messages.

    Raises:
        CoordinateValidationError: If values are NaN, inf, or out of range.
    """
    if lat is None or lon is None:
        raise CoordinateValidationError(f"{name.capitalize()} cannot be None.")

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError) as exc:
        raise CoordinateValidationError(f"Invalid non-numeric {name}: ({lat}, {lon})") from exc

    if math.isnan(lat) or math.isnan(lon):
        raise CoordinateValidationError(f"{name.capitalize()} contains NaN values: ({lat}, {lon})")

    if math.isinf(lat) or math.isinf(lon):
        raise CoordinateValidationError(f"{name.capitalize()} contains infinite values: ({lat}, {lon})")

    if not (-90.0 <= lat <= 90.0):
        raise CoordinateValidationError(
            f"{name.capitalize()} latitude {lat} is out of valid bounds [-90.0, 90.0]."
        )

    if not (-180.0 <= lon <= 180.0):
        raise CoordinateValidationError(
            f"{name.capitalize()} longitude {lon} is out of valid bounds [-180.0, 180.0]."
        )


@dataclass(frozen=True)
class BoundingBox:
    """Represents a geographic bounding box in WGS-84 decimal degrees."""

    south: float  # min_lat
    west: float   # min_lon
    north: float  # max_lat
    east: float   # max_lon

    def __post_init__(self) -> None:
        validate_coordinates(self.south, self.west, name="bounding box SW corner")
        validate_coordinates(self.north, self.east, name="bounding box NE corner")
        if self.south > self.north:
            raise CoordinateValidationError(
                f"Bounding box south ({self.south}) exceeds north ({self.north})."
            )
        if self.west > self.east:
            # Note: Antimeridian crossing can be supported in future; rejected for Stage 5
            raise CoordinateValidationError(
                f"Bounding box west ({self.west}) exceeds east ({self.east})."
            )

    @classmethod
    def from_coordinates(
        cls,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        buffer_meters: float = DEFAULT_BUFFER_METERS,
        buffer_ratio: float = DEFAULT_BUFFER_RATIO,
        max_distance_meters: float = DEFAULT_MAX_ROUTE_DISTANCE_METERS,
        max_area_km2: float = DEFAULT_MAX_BOUNDING_BOX_AREA_KM2,
    ) -> "BoundingBox":
        """Construct a buffered geographic bounding box covering an origin and destination.

        Calculates an adaptive buffer: max(buffer_meters, separation * buffer_ratio)
        so that alternative accessible detours around barriers are not truncated.

        Args:
            origin: (latitude, longitude) of origin point.
            destination: (latitude, longitude) of destination point.
            buffer_meters: Fixed minimum padding in meters.
            buffer_ratio: Proportional padding based on straight-line distance.
            max_distance_meters: Operational safeguard on maximum separation.
            max_area_km2: Operational safeguard on maximum bounding box area.

        Returns:
            Padded BoundingBox enclosing both coordinates.

        Raises:
            CoordinateValidationError: If coordinates are invalid.
            RouteRegionTooLargeError: If distance or area exceeds development limits.
        """
        orig_lat, orig_lon = origin
        dest_lat, dest_lon = destination
        validate_coordinates(orig_lat, orig_lon, name="origin")
        validate_coordinates(dest_lat, dest_lon, name="destination")

        separation_m = haversine_distance(orig_lat, orig_lon, dest_lat, dest_lon)
        if separation_m > max_distance_meters:
            raise RouteRegionTooLargeError(
                f"Route straight-line separation ({separation_m:.0f}m) exceeds "
                f"operational development limit ({max_distance_meters:.0f}m). "
                "For wide-area routes, tiled acquisition will be added in future stages."
            )

        # Minimum bounding box
        min_lat = min(orig_lat, dest_lat)
        max_lat = max(orig_lat, dest_lat)
        min_lon = min(orig_lon, dest_lon)
        max_lon = max(orig_lon, dest_lon)

        # Adaptive metric buffer
        effective_buffer = max(buffer_meters, separation_m * buffer_ratio)

        # Convert meters to degrees approximately
        # 1 degree latitude ~= 111,000 meters
        lat_buffer_deg = effective_buffer / 111000.0

        # Longitude degree width depends on latitude
        center_lat = (min_lat + max_lat) / 2.0
        cos_lat = max(0.01, math.cos(math.radians(center_lat)))
        lon_buffer_deg = effective_buffer / (111000.0 * cos_lat)

        south = max(-90.0, min_lat - lat_buffer_deg)
        north = min(90.0, max_lat + lat_buffer_deg)
        west = max(-180.0, min_lon - lon_buffer_deg)
        east = min(180.0, max_lon + lon_buffer_deg)

        bbox = cls(south=round(south, 6), west=round(west, 6), north=round(north, 6), east=round(east, 6))

        if bbox.area_km2 > max_area_km2:
            raise RouteRegionTooLargeError(
                f"Requested bounding box area ({bbox.area_km2:.1f} km²) exceeds "
                f"operational development limit ({max_area_km2:.1f} km²)."
            )

        return bbox

    @property
    def area_km2(self) -> float:
        """Approximate planar area of the bounding box in square kilometers."""
        lat_dist_km = (self.north - self.south) * 111.0
        center_lat = (self.north + self.south) / 2.0
        cos_lat = max(0.01, math.cos(math.radians(center_lat)))
        lon_dist_km = (self.east - self.west) * 111.0 * cos_lat
        return abs(lat_dist_km * lon_dist_km)

    @property
    def center(self) -> Tuple[float, float]:
        """Center coordinate (latitude, longitude)."""
        return ((self.south + self.north) / 2.0, (self.west + self.east) / 2.0)

    @property
    def spatial_id(self) -> str:
        """Deterministic spatial hash identifying this geographic region."""
        # Quantize to 4 decimal places (~11m precision) to compute hash
        raw = f"{self.south:.4f}_{self.west:.4f}_{self.north:.4f}_{self.east:.4f}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"reg_{digest}"

    def contains_point(self, lat: float, lon: float) -> bool:
        """Check if a coordinate lies strictly within the bounding box."""
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    def contains_box(self, other: "BoundingBox", tolerance_deg: float = 0.0001) -> bool:
        """Check if this bounding box completely encloses another bounding box.

        Args:
            other: The candidate sub-region BoundingBox.
            tolerance_deg: Floating-point margin (~10m).

        Returns:
            True if other is completely enclosed within self.
        """
        return (
            self.south <= (other.south + tolerance_deg)
            and self.north >= (other.north - tolerance_deg)
            and self.west <= (other.west + tolerance_deg)
            and self.east >= (other.east - tolerance_deg)
        )

    def as_osmnx_bbox(self) -> Tuple[float, float, float, float]:
        """Return tuple formatted for OSMnx 2.x `graph_from_bbox`: (left, bottom, right, top)."""
        return (self.west, self.south, self.east, self.north)

    def expand(
        self,
        factor: float = 1.5,
        min_expansion_m: float = 300.0,
        max_area_km2: float = DEFAULT_MAX_BOUNDING_BOX_AREA_KM2,
    ) -> "BoundingBox":
        """Expand this bounding box outwards by a scale factor and minimum margin.

        Args:
            factor: Multiplier applied to existing lat/lon extents.
            min_expansion_m: Minimum metric expansion added to each side.
            max_area_km2: Maximum permitted area safeguard.

        Returns:
            New expanded BoundingBox instance.

        Raises:
            RouteRegionTooLargeError: If expanded box exceeds max_area_km2.
        """
        center_lat, center_lon = self.center
        cos_lat = max(0.01, math.cos(math.radians(center_lat)))
        min_lat_deg = min_expansion_m / 111000.0
        min_lon_deg = min_expansion_m / (111000.0 * cos_lat)

        half_lat = max((self.north - self.south) * 0.5 * factor, (self.north - self.south) * 0.5 + min_lat_deg)
        half_lon = max((self.east - self.west) * 0.5 * factor, (self.east - self.west) * 0.5 + min_lon_deg)

        south = max(-90.0, center_lat - half_lat)
        north = min(90.0, center_lat + half_lat)
        west = max(-180.0, center_lon - half_lon)
        east = min(180.0, center_lon + half_lon)

        bbox = BoundingBox(
            south=round(south, 6),
            west=round(west, 6),
            north=round(north, 6),
            east=round(east, 6),
        )
        if bbox.area_km2 > max_area_km2:
            raise RouteRegionTooLargeError(
                f"Expanded bounding box area ({bbox.area_km2:.1f} km²) exceeds "
                f"operational development limit ({max_area_km2:.1f} km²)."
            )
        return bbox

    def to_dict(self) -> Dict[str, float]:
        return {
            "south": self.south,
            "west": self.west,
            "north": self.north,
            "east": self.east,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        return cls(
            south=float(data["south"]),
            west=float(data["west"]),
            north=float(data["north"]),
            east=float(data["east"]),
        )
