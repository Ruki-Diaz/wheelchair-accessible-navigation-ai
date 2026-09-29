"""Configuration settings for AccessRoute AI."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class GeographicArea:
    """Represents a geographic bounding area for pedestrian network extraction."""
    area_id: str
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 1500
    description: str = ""


# Default cache directory location
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = BASE_DIR / "data" / "cache"

# Configured Geographic Areas (Stage 1 uses Vermont South test area)
AREAS: Dict[str, GeographicArea] = {
    "vermont_south": GeographicArea(
        area_id="vermont_south",
        name="Vermont South, Victoria, Australia",
        latitude=-37.8570,
        longitude=145.1740,
        radius_meters=1500,
        description="Controlled suburban test area centered on Vermont South Shopping Centre & Community Hub",
    )
}

# Raw OSM tags to preserve on edges during graph download (for Stage 2 normalisation)
ACCESSIBILITY_WAY_TAGS: List[str] = [
    "wheelchair",
    "kerb",
    "curb",
    "surface",
    "smoothness",
    "incline",
    "width",
    "tactile_paving",
    "highway",
    "footway",
    "crossing",
    "crossing:signals",
    "crossing:markings",
    "steps",
    "step_count",
    "ramp",
    "ramp:wheelchair",
    "sidewalk",
    "lit",
    "access",
    "handrail",
    "incline:direction",
]

# Raw OSM tags to preserve on nodes
ACCESSIBILITY_NODE_TAGS: List[str] = [
    "highway",
    "kerb",
    "wheelchair",
    "tactile_paving",
    "crossing",
    "traffic_signals",
    "barrier",
]

# Prototype reference coordinates (from original university project Cell 5)
# Used as test fixtures and validation benchmarks — not assumed to be authoritative ground truth.
PROTOTYPE_FIXTURE_COORDINATES: Dict[str, Tuple[float, float]] = {
    "Library": (-37.8568, 145.1735),
    "Shopping Centre": (-37.8572, 145.1750),
    "Parking Space": (-37.8575, 145.1762),
    "Medical Centre": (-37.8580, 145.1755),
    "Park Entrance": (-37.8585, 145.1770),
    "Pathway": (-37.8579, 145.1743),
    "Bus Stop": (-37.8565, 145.1728),
    "Mall Entrance": (-37.8590, 145.1780),
    "Pharmacy": (-37.8577, 145.1768),
    "Pedestrian Ramp": (-37.8569, 145.1730),
    "Water Taps": (-37.8573, 145.1748),
    "Accessible ATM": (-37.8571, 145.1752),
    "Supermarket": (-37.8566, 145.1725),
    "Multi-level Parking": (-37.8574, 145.1742),
    "Hospital": (-37.8578, 145.1757),
    "Cinema": (-37.8582, 145.1765),
    "Restaurant": (-37.8584, 145.1778),
    "Public Restroom": (-37.8567, 145.1738),
    "School Entrance": (-37.8587, 145.1785),
    "Community Centre": (-37.8576, 145.1759),
    "Post Office": (-37.8570, 145.1757),
    "Playground (Accessible)": (-37.8588, 145.1772),
    "Tactile Crossing": (-37.8564, 145.1741),
    "Kerb Ramp - Market Street": (-37.8579, 145.1737),
    "Bicycle Parking": (-37.8583, 145.1761),
    "Community Garden": (-37.8581, 145.1749),
    "Wheelchair Drop-off Point": (-37.8572, 145.1733),
    "Rehab Clinic Entrance": (-37.8586, 145.1756),
    "Indoor Pool Ramp": (-37.8592, 145.1769),
    "Childcare Access Path": (-37.8575, 145.1727),
}
