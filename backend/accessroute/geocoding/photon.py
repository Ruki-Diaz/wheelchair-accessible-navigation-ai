"""Photon (OSM Elasticsearch) geocoder provider implementation.

Photon is an open-source, keyless geocoder developed by Komoot built on
OpenStreetMap data. It is optimized for fast search-as-you-type and global
address lookup with proximity bias support.
"""

import json
import logging
from typing import List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from accessroute.geocoding.base import GeocodeCandidate, GeocoderProvider
from accessroute.geocoding.cache import GeocodingCache

logger = logging.getLogger(__name__)

DEFAULT_PHOTON_URL = "https://photon.komoot.io/api"
DEFAULT_TIMEOUT_SECONDS = 8.0


class PhotonGeocoderProvider(GeocoderProvider):
    """Geocoder implementation using Komoot's open Photon API."""

    def __init__(
        self,
        api_url: str = DEFAULT_PHOTON_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        cache: Optional[GeocodingCache] = None,
    ):
        self._api_url = api_url
        self._timeout = timeout_seconds
        self._cache = cache or GeocodingCache()

    @property
    def provider_name(self) -> str:
        return "photon:komoot_osm"

    def search(
        self,
        query: str,
        limit: int = 5,
        proximity: Optional[Tuple[float, float]] = None,
        country_code: Optional[str] = None,
    ) -> List[GeocodeCandidate]:
        if not query or not query.strip():
            return []

        q_clean = query.strip()

        # 1. Check local cache
        cached = self._cache.get(q_clean, proximity, country_code)
        if cached is not None:
            logger.debug("Geocoding cache hit for query: '%s'", q_clean)
            return cached[:limit]

        # 2. Build Photon query parameters
        params = {
            "q": q_clean,
            "limit": str(max(1, min(limit, 20))),
        }
        if proximity is not None:
            params["lat"] = str(round(proximity[0], 6))
            params["lon"] = str(round(proximity[1], 6))

        url = f"{self._api_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AccessRouteAI/1.0 (Pedestrian Accessibility Navigation Research)",
                "Accept": "application/json",
            },
        )

        candidates: List[GeocodeCandidate] = []
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                features = payload.get("features", [])

                for feat in features:
                    geom = feat.get("geometry", {})
                    coords = geom.get("coordinates", [])
                    if len(coords) < 2:
                        continue
                    lon, lat = float(coords[0]), float(coords[1])

                    props = feat.get("properties", {})
                    name = props.get("name", "")
                    street = props.get("street")
                    city = props.get("city") or props.get("town") or props.get("village")
                    state = props.get("state")
                    country = props.get("country")
                    postcode = props.get("postcode")
                    osm_id = props.get("osm_id")
                    osm_type = props.get("osm_type")
                    osm_value = props.get("osm_value")

                    # Filter by country if requested
                    if country_code and props.get("countrycode", "").lower() != country_code.lower():
                        continue

                    # Construct descriptive display name
                    parts = [p for p in [name, street, city, state, country] if p]
                    display_name = ", ".join(parts) if parts else f"Location ({lat:.4f}, {lon:.4f})"

                    extent = None
                    if "extent" in props and len(props["extent"]) == 4:
                        # Photon returns [min_lon, max_lat, max_lon, min_lat]
                        w, n, e, s = props["extent"]
                        extent = (float(s), float(w), float(n), float(e))

                    candidate = GeocodeCandidate(
                        display_name=display_name,
                        latitude=lat,
                        longitude=lon,
                        place_type=osm_value or props.get("type"),
                        osm_id=osm_id,
                        osm_type=osm_type,
                        street=street,
                        city=city,
                        state=state,
                        country=country,
                        postcode=postcode,
                        extent=extent,
                        raw_properties=props,
                    )
                    candidates.append(candidate)

        except urllib.error.URLError as exc:
            logger.warning("Photon geocoding request failed: %s", exc)
        except Exception as exc:
            logger.warning("Unexpected error during Photon geocoding: %s", exc)

        # 3. Store in cache
        if candidates:
            self._cache.set(q_clean, candidates, proximity, country_code)

        return candidates[:limit]

    def reverse(
        self,
        latitude: float,
        longitude: float,
    ) -> Optional[GeocodeCandidate]:
        """Reverse geocode coordinates using Photon /reverse endpoint."""
        cache_key = f"rev:{round(latitude, 5)}:{round(longitude, 5)}"
        cached = self._cache.get(cache_key)
        if cached and len(cached) > 0:
            return cached[0]

        reverse_base = self._api_url.replace("/api", "/reverse")
        params = {
            "lat": str(round(latitude, 6)),
            "lon": str(round(longitude, 6)),
        }
        url = f"{reverse_base}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AccessRouteAI/1.0 (Pedestrian Accessibility Navigation Research)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                features = payload.get("features", [])
                if not features:
                    return None

                feat = features[0]
                geom = feat.get("geometry", {})
                coords = geom.get("coordinates", [])
                lon = float(coords[0]) if len(coords) > 0 else longitude
                lat = float(coords[1]) if len(coords) > 1 else latitude

                props = feat.get("properties", {})
                name = props.get("name", "")
                street = props.get("street")
                housenumber = props.get("housenumber")
                city = props.get("city") or props.get("town") or props.get("village")
                state = props.get("state")
                country = props.get("country")
                postcode = props.get("postcode")
                osm_id = props.get("osm_id")
                osm_type = props.get("osm_type")
                osm_value = props.get("osm_value")

                street_part = f"{housenumber} {street}" if (housenumber and street) else (street or name)
                parts = [p for p in [street_part, city, state, country] if p and p != street_part or p == street_part]
                display_name = ", ".join(dict.fromkeys(parts)) if parts else f"Location ({lat:.4f}, {lon:.4f})"

                candidate = GeocodeCandidate(
                    display_name=display_name,
                    latitude=lat,
                    longitude=lon,
                    place_type=osm_value or props.get("type"),
                    osm_id=osm_id,
                    osm_type=osm_type,
                    street=street,
                    city=city,
                    state=state,
                    country=country,
                    postcode=postcode,
                    raw_properties=props,
                )
                self._cache.set(cache_key, [candidate])
                return candidate
        except Exception as exc:
            logger.warning("Photon reverse geocoding failed: %s", exc)
            return None
