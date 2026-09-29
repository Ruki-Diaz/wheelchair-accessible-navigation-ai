"""FastAPI dependency injection providers."""

from typing import Optional
from accessroute.elevation.cache import CachedElevationProvider
from accessroute.elevation.open_meteo import OpenMeteoElevationProvider
from accessroute.geocoding.base import GeocoderProvider
from accessroute.geocoding.photon import PhotonGeocoderProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import OpenStreetMapGraphProvider
from accessroute.graph.regional_cache import RegionalGraphCache

_cached_elevation_provider = CachedElevationProvider(OpenMeteoElevationProvider())
_regional_cache = RegionalGraphCache()
_osm_provider = OpenStreetMapGraphProvider()
_graph_manager = DynamicGraphManager(
    provider=_osm_provider,
    cache=_regional_cache,
    elevation_provider=_cached_elevation_provider,
)
_geocoder: GeocoderProvider = PhotonGeocoderProvider()
_intelligence_service = None


def get_graph_manager() -> DynamicGraphManager:
    """Dependency providing singleton DynamicGraphManager instance."""
    return _graph_manager


def get_regional_cache() -> RegionalGraphCache:
    """Dependency providing RegionalGraphCache instance."""
    return _regional_cache


def get_geocoder() -> GeocoderProvider:
    """Dependency providing active GeocoderProvider."""
    return _geocoder


def get_intelligence_service() -> "EvidenceIntelligenceService":
    """Dependency providing singleton EvidenceIntelligenceService."""
    global _intelligence_service
    if _intelligence_service is None:
        from accessroute.intelligence.service import EvidenceIntelligenceService
        _intelligence_service = EvidenceIntelligenceService(graph_manager=_graph_manager)
    return _intelligence_service


_navigation_service = None


def get_navigation_service() -> "LiveNavigationService":
    """Dependency providing singleton LiveNavigationService."""
    global _navigation_service
    if _navigation_service is None:
        from accessroute.navigation.service import LiveNavigationService
        _navigation_service = LiveNavigationService(graph_manager=_graph_manager)
    return _navigation_service


_community_service = None


def get_community_service() -> "CommunityObservationService":
    """Dependency providing singleton CommunityObservationService."""
    global _community_service
    if _community_service is None:
        from accessroute.community.service import CommunityObservationService
        _community_service = CommunityObservationService()
    return _community_service

