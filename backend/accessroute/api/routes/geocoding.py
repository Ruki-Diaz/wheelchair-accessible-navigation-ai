"""Geocoding search endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from accessroute.api.dependencies import get_geocoder
from accessroute.api.schemas.geocoding import (
    GeocodeCandidateSchema,
    GeocodeReverseResponse,
    GeocodeSearchResponse,
)
from accessroute.geocoding.base import GeocoderProvider

router = APIRouter(prefix="/geocode", tags=["Geocoding"])


@router.get(
    "/search",
    response_model=GeocodeSearchResponse,
    summary="Search Place Candidates",
    description="Search for candidate geographical locations matching a free-text place name or address query.",
)
def search_places(
    q: str = Query(..., min_length=1, description="Location search query (e.g. 'Flinders Street Station')."),
    limit: int = Query(default=5, ge=1, le=15, description="Maximum candidate matches to return."),
    proximity_lat: Optional[float] = Query(default=None, ge=-90.0, le=90.0, description="Optional center latitude for ranking bias."),
    proximity_lon: Optional[float] = Query(default=None, ge=-180.0, le=180.0, description="Optional center longitude for ranking bias."),
    country_code: Optional[str] = Query(default=None, max_length=2, description="Optional 2-letter ISO country code."),
    geocoder: GeocoderProvider = Depends(get_geocoder),
) -> GeocodeSearchResponse:
    proximity = (proximity_lat, proximity_lon) if proximity_lat is not None and proximity_lon is not None else None
    candidates = geocoder.search(
        query=q,
        limit=limit,
        proximity=proximity,
        country_code=country_code,
    )
    schema_candidates = [
        GeocodeCandidateSchema(
            display_name=c.display_name,
            latitude=c.latitude,
            longitude=c.longitude,
            place_type=c.place_type,
            street=c.street,
            city=c.city,
            state=c.state,
            country=c.country,
            postcode=c.postcode,
            extent=c.extent,
        )
        for c in candidates
    ]
    return GeocodeSearchResponse(
        query=q,
        count=len(schema_candidates),
        candidates=schema_candidates,
    )


@router.get(
    "/reverse",
    response_model=GeocodeReverseResponse,
    summary="Reverse Geocode Coordinates",
    description="Resolve coordinates to a human-readable street or place address with graceful fallback.",
)
def reverse_geocode(
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="WGS-84 Latitude"),
    lon: Optional[float] = Query(None, ge=-180.0, le=180.0, description="WGS-84 Longitude"),
    latitude: Optional[float] = Query(None, ge=-90.0, le=90.0, description="WGS-84 Latitude (alias)"),
    longitude: Optional[float] = Query(None, ge=-180.0, le=180.0, description="WGS-84 Longitude (alias)"),
    geocoder: GeocoderProvider = Depends(get_geocoder),
) -> GeocodeReverseResponse:
    actual_lat = lat if lat is not None else latitude
    actual_lon = lon if lon is not None else longitude
    if actual_lat is None or actual_lon is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both latitude and longitude must be provided (e.g. ?lat=..&lon=.. or ?latitude=..&longitude=..)",
        )
    candidate = geocoder.reverse(latitude=actual_lat, longitude=actual_lon)
    if candidate:
        schema_candidate = GeocodeCandidateSchema(
            display_name=candidate.display_name,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            place_type=candidate.place_type,
            street=candidate.street,
            city=candidate.city,
            state=candidate.state,
            country=candidate.country,
            postcode=candidate.postcode,
            extent=candidate.extent,
        )
        return GeocodeReverseResponse(
            latitude=lat,
            longitude=lon,
            candidate=schema_candidate,
            display_name=f"Near {candidate.display_name}" if not candidate.display_name.lower().startswith("near") else candidate.display_name,
        )
    return GeocodeReverseResponse(
        latitude=lat,
        longitude=lon,
        candidate=None,
        display_name=f"Location ({lat:.5f}, {lon:.5f})",
    )
