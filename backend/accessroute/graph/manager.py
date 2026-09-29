"""Dynamic graph acquisition and enrichment manager for arbitrary geographic coordinates."""

from datetime import datetime, timezone
import logging
from typing import Optional, Tuple
import networkx as nx

from accessroute.elevation import (
    CachedElevationProvider,
    ElevationProvider,
    OpenMeteoElevationProvider,
    enrich_graph_with_elevation,
)
from accessroute.graph.enricher import enrich_graph_accessibility
from accessroute.graph.provider import GraphProvider, OpenStreetMapGraphProvider
from accessroute.graph.region import (
    DEFAULT_BUFFER_METERS,
    DEFAULT_BUFFER_RATIO,
    BoundingBox,
)
from accessroute.graph.regional_cache import (
    CURRENT_ACCESSIBILITY_VERSION,
    CURRENT_TERRAIN_VERSION,
    RegionMetadata,
    RegionalGraphCache,
)

logger = logging.getLogger(__name__)


class DynamicGraphManager:
    """Orchestrates coordinate-driven regional graph discovery, acquisition, enrichment, and caching."""

    def __init__(
        self,
        provider: Optional[GraphProvider] = None,
        cache: Optional[RegionalGraphCache] = None,
        elevation_provider: Optional[ElevationProvider] = None,
    ) -> None:
        self._provider = provider or OpenStreetMapGraphProvider()
        self._cache = cache or RegionalGraphCache()
        self._elevation_provider = elevation_provider or CachedElevationProvider(
            backend=OpenMeteoElevationProvider()
        )

    @property
    def provider(self) -> GraphProvider:
        return self._provider

    @property
    def cache(self) -> RegionalGraphCache:
        return self._cache

    @property
    def elevation_provider(self) -> ElevationProvider:
        return self._elevation_provider

    def get_graph_for_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        buffer_meters: float = DEFAULT_BUFFER_METERS,
        buffer_ratio: float = DEFAULT_BUFFER_RATIO,
        enrich_elevation: bool = True,
        force_refresh: bool = False,
    ) -> Tuple[nx.MultiDiGraph, RegionMetadata, bool]:
        """Obtain an enriched pedestrian network covering the route between origin and destination.

        Workflow:
        1. Generates buffered bounding box covering both coordinates.
        2. Evaluates regional cache for existing spatial coverage.
        3. If cache hit: reuses cached network instantly.
        4. If cache miss: downloads pedestrian network, runs Stage 2 accessibility
           normalization, optionally runs Stage 4 elevation enrichment, and caches atomically.

        Args:
            origin: (latitude, longitude) of origin point.
            destination: (latitude, longitude) of destination point.
            buffer_meters: Safety padding around endpoints.
            buffer_ratio: Proportional padding based on separation distance.
            enrich_elevation: Whether to attach elevation/grade evidence.
            force_refresh: If True, bypasses cache and re-downloads fresh network.

        Returns:
            Tuple of (MultiDiGraph, RegionMetadata, is_cache_hit).
        """
        # 1. Determine geographic routing region
        bbox = BoundingBox.from_coordinates(
            origin=origin,
            destination=destination,
            buffer_meters=buffer_meters,
            buffer_ratio=buffer_ratio,
        )
        return self.get_graph_for_bbox(
            bbox=bbox,
            enrich_elevation=enrich_elevation,
            force_refresh=force_refresh,
        )

    def get_graph_for_bbox(
        self,
        bbox: BoundingBox,
        enrich_elevation: bool = True,
        force_refresh: bool = False,
    ) -> Tuple[nx.MultiDiGraph, RegionMetadata, bool]:
        """Obtain an enriched pedestrian network covering a specific BoundingBox.

        Checks spatial cache, acquires from GraphProvider on miss, normalizes accessibility,
        optionally enriches terrain, and saves to regional cache.
        """
        # 1. Check regional graph cache
        if not force_refresh:
            hit = self._cache.find_covering_region(
                query_bbox=bbox,
                require_terrain=enrich_elevation,
            )
            if hit is not None:
                region_id, meta = hit
                try:
                    G, loaded_meta = self._cache.load_graph(region_id)
                    # Re-attach runtime accessibility model objects if missing from serialized GraphML
                    enrich_graph_accessibility(G)
                    return G, loaded_meta, True
                except Exception as exc:
                    logger.warning("Cache read failed for region %s: %s. Re-acquiring...", region_id, exc)

        # 2. Cache Miss: Acquire from GraphProvider
        logger.info(
            "Cache miss for bbox %s (area=%.2f km²). Acquiring via %s...",
            bbox.spatial_id,
            bbox.area_km2,
            self._provider.provider_name,
        )
        G = self._provider.get_pedestrian_network(bbox)

        # 3. Automatic Stage 2 Accessibility Normalization
        enrich_graph_accessibility(G)

        # 4. Optional Stage 4 Elevation & Terrain Enrichment (with graceful failure fallback)
        terrain_enriched = False
        if enrich_elevation and self._elevation_provider is not None:
            try:
                enrich_summary = enrich_graph_with_elevation(G, self._elevation_provider)
                terrain_enriched = True
                logger.info(
                    "Elevation enrichment complete (coverage=%.1f%%, source=%s).",
                    enrich_summary.elevation_coverage_pct,
                    enrich_summary.elevation_source,
                )
            except Exception as exc:
                logger.warning(
                    "Elevation enrichment failed (%s); proceeding with UNKNOWN elevation.",
                    exc,
                )
                terrain_enriched = False

        # 5. Build Metadata & Persist to Cache
        metadata = RegionMetadata(
            region_id=bbox.spatial_id,
            bbox=bbox,
            created_at=datetime.now(timezone.utc).isoformat(),
            node_count=len(G.nodes),
            edge_count=G.number_of_edges(),
            osm_loaded=True,
            accessibility_enriched=True,
            accessibility_model_version=CURRENT_ACCESSIBILITY_VERSION,
            terrain_enriched=terrain_enriched,
            terrain_model_version=CURRENT_TERRAIN_VERSION if terrain_enriched else "none",
            source=self._provider.provider_name,
        )

        try:
            self._cache.save_graph(G, metadata)
        except Exception as exc:
            logger.warning("Failed to cache newly acquired region: %s", exc)

        return G, metadata, False


# Module-level convenience function
_DEFAULT_MANAGER: Optional[DynamicGraphManager] = None


def get_graph_for_route(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    buffer_meters: float = DEFAULT_BUFFER_METERS,
    buffer_ratio: float = DEFAULT_BUFFER_RATIO,
    enrich_elevation: bool = True,
    force_refresh: bool = False,
    provider: Optional[GraphProvider] = None,
    cache: Optional[RegionalGraphCache] = None,
) -> Tuple[nx.MultiDiGraph, RegionMetadata, bool]:
    """Convenience function to acquire or retrieve an enriched pedestrian network."""
    global _DEFAULT_MANAGER
    if provider is not None or cache is not None:
        manager = DynamicGraphManager(provider=provider, cache=cache)
        return manager.get_graph_for_route(
            origin=origin,
            destination=destination,
            buffer_meters=buffer_meters,
            buffer_ratio=buffer_ratio,
            enrich_elevation=enrich_elevation,
            force_refresh=force_refresh,
        )

    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = DynamicGraphManager()

    return _DEFAULT_MANAGER.get_graph_for_route(
        origin=origin,
        destination=destination,
        buffer_meters=buffer_meters,
        buffer_ratio=buffer_ratio,
        enrich_elevation=enrich_elevation,
        force_refresh=force_refresh,
    )
