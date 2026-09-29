"""Pydantic schemas for the Geocoding API."""

from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class GeocodeCandidateSchema(BaseModel):
    """Candidate geographic location matching a search query."""

    display_name: str = Field(..., description="Descriptive human-readable place name.")
    latitude: float = Field(..., description="WGS-84 Latitude in decimal degrees.", ge=-90.0, le=90.0)
    longitude: float = Field(..., description="WGS-84 Longitude in decimal degrees.", ge=-180.0, le=180.0)
    place_type: Optional[str] = Field(None, description="OSM place category or amenity type.")
    street: Optional[str] = Field(None, description="Street name if applicable.")
    city: Optional[str] = Field(None, description="City, town, or suburb name.")
    state: Optional[str] = Field(None, description="State, province, or region.")
    country: Optional[str] = Field(None, description="Country name.")
    postcode: Optional[str] = Field(None, description="Postal code.")
    extent: Optional[Tuple[float, float, float, float]] = Field(
        None, description="Geographic bounding box (south, west, north, east)."
    )


class GeocodeSearchResponse(BaseModel):
    """Response envelope for place search queries."""

    query: str = Field(..., description="Original search query string.")
    count: int = Field(..., description="Number of candidate matches returned.")
    candidates: List[GeocodeCandidateSchema] = Field(..., description="Ordered list of candidate locations.")


class GeocodeReverseResponse(BaseModel):
    """Response envelope for reverse geocoding queries."""

    latitude: float = Field(..., description="Queried latitude.")
    longitude: float = Field(..., description="Queried longitude.")
    candidate: Optional[GeocodeCandidateSchema] = Field(None, description="Resolved geographic place or address.")
    display_name: str = Field(..., description="Best available human-readable name or coordinate fallback.")
