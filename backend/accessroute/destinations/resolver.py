"""Destination Resolver for AccessRoute AI.

Analyzes geocode candidates, place metadata, and coordinates to determine
whether a destination represents a venue (e.g. shopping centre, hospital,
train station, university campus, public building) or an arbitrary street address.
Preserves original search result coordinates and attributes.
"""

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from accessroute.destinations.models import Destination, Venue, VenueType
from accessroute.geocoding.base import GeocodeCandidate

logger = logging.getLogger(__name__)

# Keywords mapping to VenueType
VENUE_KEYWORD_MAP: Dict[VenueType, List[str]] = {
    VenueType.SHOPPING_CENTRE: [
        "westfield", "shopping centre", "shopping center", "mall", "plaza",
        "market", "bazaar", "arcade", "retail center"
    ],
    VenueType.STATION: [
        "station", "railway station", "train station", "metro station",
        "subway", "transit centre", "bus interchange", "tram stop"
    ],
    VenueType.HOSPITAL: [
        "hospital", "medical centre", "clinic", "health service", "infirmary"
    ],
    VenueType.UNIVERSITY: [
        "university", "campus", "college", "institute of technology",
        "library", "faculty", "academy"
    ],
    VenueType.PUBLIC_FACILITY: [
        "town hall", "community centre", "council", "civic centre",
        "museum", "gallery", "court", "police station", "post office", "theatre", "opera house"
    ],
    VenueType.PARK: [
        "park", "gardens", "botanic gardens", "reserve", "playground", "oval"
    ],
    VenueType.BUSINESS: [
        "centre", "center", "tower", "office", "hotel", "bank", "supermarket"
    ],
}


def _generate_destination_id(name: str, lat: float, lon: float) -> str:
    """Generate a deterministic ID from place name and coordinates."""
    key = f"{name.strip().lower()}_{lat:.5f}_{lon:.5f}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"dst_{digest}"


class DestinationResolver:
    """Resolves geocode candidates and arbitrary coordinates into normalized Destination models."""

    @classmethod
    def resolve_candidate(cls, candidate: GeocodeCandidate) -> Destination:
        """Resolve a GeocodeCandidate from the geocoding provider."""
        name = candidate.display_name.split(",")[0].strip() or candidate.display_name
        dest_id = _generate_destination_id(name, candidate.latitude, candidate.longitude)
        
        venue_type, is_venue = cls._detect_venue_type(
            name=name,
            place_type=candidate.place_type,
            raw_props=candidate.raw_properties,
            osm_type=candidate.osm_type,
        )

        venue_obj = None
        if is_venue:
            venue_id = f"ven_{dest_id[4:]}"
            venue_obj = Venue(
                id=venue_id,
                name=name,
                venue_type=venue_type,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                bbox=candidate.extent,
                osm_type=candidate.osm_type,
                osm_id=candidate.osm_id,
                address=candidate.display_name,
            )

        return Destination(
            id=dest_id,
            name=name,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            is_venue=is_venue,
            venue=venue_obj,
            display_name=candidate.display_name,
            place_type=candidate.place_type,
            raw_properties=candidate.raw_properties,
        )

    @classmethod
    def resolve_coordinates(
        cls,
        latitude: float,
        longitude: float,
        label: Optional[str] = None,
    ) -> Destination:
        """Resolve raw coordinates into a Destination entity."""
        name = label.strip() if label and label.strip() else f"Point ({latitude:.4f}, {longitude:.4f})"
        dest_id = _generate_destination_id(name, latitude, longitude)

        # Check if label hints at a known venue
        venue_type, is_venue = cls._detect_venue_type(name=name)

        venue_obj = None
        if is_venue:
            venue_id = f"ven_{dest_id[4:]}"
            venue_obj = Venue(
                id=venue_id,
                name=name,
                venue_type=venue_type,
                latitude=latitude,
                longitude=longitude,
                address=name,
            )

        return Destination(
            id=dest_id,
            name=name,
            latitude=latitude,
            longitude=longitude,
            is_venue=is_venue,
            venue=venue_obj,
            display_name=name,
            place_type="coordinate" if not is_venue else venue_type.value,
        )

    @classmethod
    def _detect_venue_type(
        cls,
        name: str,
        place_type: Optional[str] = None,
        raw_props: Optional[Dict[str, Any]] = None,
        osm_type: Optional[str] = None,
    ) -> Tuple[VenueType, bool]:
        """Detect whether destination is a venue and classify its VenueType."""
        name_lower = name.lower()
        props = raw_props or {}

        # 1. Inspect OSM category tags if present
        osm_value = str(props.get("osm_value", props.get("shop", props.get("amenity", "")))).lower()
        osm_key = str(props.get("osm_key", "")).lower()

        if osm_value in ["mall", "department_store", "supermarket"]:
            return VenueType.SHOPPING_CENTRE, True
        if osm_value in ["station", "subway_entrance", "halt", "train_station"] or osm_key == "railway":
            return VenueType.STATION, True
        if osm_value in ["hospital", "clinic"]:
            return VenueType.HOSPITAL, True
        if osm_value in ["university", "college", "library", "school"]:
            return VenueType.UNIVERSITY, True
        if osm_value in ["townhall", "civic_centre", "theatre", "museum", "arts_centre", "community_centre"]:
            return VenueType.PUBLIC_FACILITY, True
        if osm_value in ["park", "garden", "nature_reserve"]:
            return VenueType.PARK, True

        # 2. Check keyword patterns in place name
        for vtype, keywords in VENUE_KEYWORD_MAP.items():
            for kw in keywords:
                # Word boundary match for short keywords like "mall", "park", "station"
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, name_lower):
                    return vtype, True

        # 3. Check place_type string from geocoder
        ptype_str = (place_type or "").lower()
        if ptype_str in [
            "amenity", "railway", "aeroway", "leisure", "tourism", "commercial",
            "shopping_centre", "public_facility", "hospital", "university", "station", "park", "landmark",
        ]:
            if "station" in ptype_str:
                return VenueType.STATION, True
            if "shopping" in ptype_str:
                return VenueType.SHOPPING_CENTRE, True
            if "hospital" in ptype_str:
                return VenueType.HOSPITAL, True
            if "public" in ptype_str:
                return VenueType.PUBLIC_FACILITY, True
            if "park" in ptype_str:
                return VenueType.PARK, True
            return VenueType.BUSINESS, True

        # 4. Check if standard street address pattern (e.g. "123 Collins Street")
        if re.match(r"^\d+\s+[a-z]+(\s+[a-z]+)*(street|road|avenue|crescent|lane|way|highway|parade|court|close|drive|circuit)\b", name_lower):
            return VenueType.ADDRESS, False

        return VenueType.ARBITRARY_COORDINATE, False
