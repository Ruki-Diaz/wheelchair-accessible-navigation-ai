"""Geocoding abstractions and data models for AccessRoute AI.

Isolates geocoding providers from the routing engine, ensuring zero coupling
to specific external search vendors.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class GeocodeCandidate:
    """Standardized geographic location candidate returned by a geocoder."""

    display_name: str
    latitude: float
    longitude: float
    place_type: Optional[str] = None
    osm_id: Optional[int] = None
    osm_type: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postcode: Optional[str] = None
    extent: Optional[Tuple[float, float, float, float]] = None  # (south, west, north, east)
    raw_properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "place_type": self.place_type,
            "osm_id": self.osm_id,
            "osm_type": self.osm_type,
            "street": self.street,
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "postcode": self.postcode,
            "extent": self.extent,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GeocodeCandidate":
        return cls(
            display_name=str(data["display_name"]),
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            place_type=data.get("place_type"),
            osm_id=data.get("osm_id"),
            osm_type=data.get("osm_type"),
            street=data.get("street"),
            city=data.get("city"),
            state=data.get("state"),
            country=data.get("country"),
            postcode=data.get("postcode"),
            extent=tuple(data["extent"]) if data.get("extent") else None,
            raw_properties=data.get("raw_properties", {}),
        )


class GeocoderProvider(ABC):
    """Abstract interface for geographic place and address search."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the geocoding service provider."""
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        limit: int = 5,
        proximity: Optional[Tuple[float, float]] = None,
        country_code: Optional[str] = None,
    ) -> List[GeocodeCandidate]:
        """Search for candidate locations matching a free-text query.

        Args:
            query: Free-text place name, address, or landmark query.
            limit: Maximum candidate results to return (default 5).
            proximity: Optional (latitude, longitude) center to bias ranking.
            country_code: Optional ISO 3166-1 alpha-2 country code filter.

        Returns:
            List of GeocodeCandidate models matching the query.
        """
        pass

    def reverse(
        self,
        latitude: float,
        longitude: float,
    ) -> Optional[GeocodeCandidate]:
        """Reverse geocode geographic coordinates to a human-readable place or address.

        Args:
            latitude: WGS-84 latitude.
            longitude: WGS-84 longitude.

        Returns:
            GeocodeCandidate if resolved, or None.
        """
        return None
