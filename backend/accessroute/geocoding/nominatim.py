"""OpenStreetMap Nominatim geocoder provider implementation.

Adheres strictly to the OSM Nominatim Usage Policy:
- Custom, identifiable User-Agent header
- Maximum 1 request per second throttling
- Results caching to minimize server load
"""

import json
import logging
import time
from typing import List, Optional, Tuple
import urllib.error
import urllib.parse
import urllib.request

from accessroute.geocoding.base import GeocodeCandidate, GeocoderProvider
from accessroute.geocoding.cache import GeocodingCache

logger = logging.getLogger(__name__)

DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_TIMEOUT_SECONDS = 10.0


class NominatimGeocoderProvider(GeocoderProvider):
    """Geocoder implementation using OpenStreetMap Nominatim with rate limiting."""

    def __init__(
        self,
        api_url: str = DEFAULT_NOMINATIM_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = "AccessRouteAI/1.0 (Accessibility Navigation System; research@accessroute.org)",
        cache: Optional[GeocodingCache] = None,
    ):
        self._api_url = api_url
        self._timeout = timeout_seconds
        self._user_agent = user_agent
        self._cache = cache or GeocodingCache()
        self._last_request_time = 0.0

    @property
    def provider_name(self) -> str:
        return "openstreetmap:nominatim"

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

        # Check local cache first
        cached = self._cache.get(q_clean, proximity, country_code)
        if cached is not None:
            return cached[:limit]

        # Respect OSM Nominatim 1 request per second rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)

        params = {
            "q": q_clean,
            "format": "jsonv2",
            "addressdetails": "1",
            "limit": str(max(1, min(limit, 20))),
        }
        if country_code:
            params["countrycodes"] = country_code.lower()

        url = f"{self._api_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )

        candidates: List[GeocodeCandidate] = []
        try:
            self._last_request_time = time.time()
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                items = json.loads(response.read().decode("utf-8"))
                for item in items:
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    display_name = item.get("display_name", "")
                    addr = item.get("address", {})

                    extent = None
                    bbox = item.get("boundingbox")
                    if bbox and len(bbox) == 4:
                        # Nominatim returns [s, n, w, e]
                        s, n, w, e = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                        extent = (s, w, n, e)

                    candidates.append(
                        GeocodeCandidate(
                            display_name=display_name,
                            latitude=lat,
                            longitude=lon,
                            place_type=item.get("type"),
                            osm_id=int(item["osm_id"]) if "osm_id" in item else None,
                            osm_type=item.get("osm_type"),
                            street=addr.get("road"),
                            city=addr.get("city") or addr.get("suburb"),
                            state=addr.get("state"),
                            country=addr.get("country"),
                            postcode=addr.get("postcode"),
                            extent=extent,
                            raw_properties=item,
                        )
                    )
        except Exception as exc:
            logger.warning("Nominatim geocoding error: %s", exc)

        if candidates:
            self._cache.set(q_clean, candidates, proximity, country_code)

        return candidates[:limit]

    def reverse(
        self,
        latitude: float,
        longitude: float,
    ) -> Optional[GeocodeCandidate]:
        """Reverse geocode coordinates using Nominatim /reverse endpoint."""
        cache_key = f"nom_rev:{round(latitude, 5)}:{round(longitude, 5)}"
        cached = self._cache.get(cache_key)
        if cached and len(cached) > 0:
            return cached[0]

        # Respect OSM Nominatim 1 request per second rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)

        reverse_base = self._api_url.replace("/search", "/reverse")
        params = {
            "lat": str(round(latitude, 6)),
            "lon": str(round(longitude, 6)),
            "format": "jsonv2",
            "addressdetails": "1",
        }
        url = f"{reverse_base}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        try:
            self._last_request_time = time.time()
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                item = json.loads(response.read().decode("utf-8"))
                if "error" in item:
                    return None
                lat = float(item.get("lat", latitude))
                lon = float(item.get("lon", longitude))
                display_name = item.get("display_name", "")
                addr = item.get("address", {})

                candidate = GeocodeCandidate(
                    display_name=display_name or f"Location ({lat:.4f}, {lon:.4f})",
                    latitude=lat,
                    longitude=lon,
                    place_type=item.get("type"),
                    osm_id=int(item["osm_id"]) if "osm_id" in item else None,
                    osm_type=item.get("osm_type"),
                    street=addr.get("road"),
                    city=addr.get("city") or addr.get("suburb"),
                    state=addr.get("state"),
                    country=addr.get("country"),
                    postcode=addr.get("postcode"),
                    raw_properties=item,
                )
                self._cache.set(cache_key, [candidate])
                return candidate
        except Exception as exc:
            logger.warning("Nominatim reverse geocoding error: %s", exc)
            return None
