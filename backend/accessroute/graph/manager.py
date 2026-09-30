"""Dynamic graph acquisition and enrichment manager for arbitrary geographic coordinates."""

from concurrent.futures import Future
from datetime import datetime, timezone
import logging
import threading
from typing import Dict, Optional, Tuple
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

_AcquiredGraph = Tuple[nx.MultiDiGraph, RegionMetadata]


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
        # Single-flight registry: in-process acquisitions currently running, keyed by
        # region spatial_id. Concurrent requests for a region already being acquired
        # wait on the leader instead of issuing a duplicate Overpass download.
        self._inflight_lock = threading.Lock()
        self._inflight: Dict[str, Tuple[BoundingBox, "Future[_AcquiredGraph]"]] = {}

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

        Checks the spatial cache (including bundled prebuilt regions), acquires from
        GraphProvider on miss, normalizes accessibility, optionally enriches terrain,
        and saves to regional cache. Concurrent misses for a region already being
        acquired share that single acquisition (in-process single-flight).
        """
        if not force_refresh:
            hit = self._load_covering_region(bbox, enrich_elevation)
            if hit is not None:
                return hit

        # Cache miss: join an in-flight acquisition covering this bbox, or lead a new one.
        with self._inflight_lock:
            joined = next(
                (
                    future
                    for inflight_bbox, future in self._inflight.values()
                    if inflight_bbox.contains_box(bbox)
                ),
                None,
            )
            if joined is None:
                leader: "Future[_AcquiredGraph]" = Future()
                self._inflight[bbox.spatial_id] = (bbox, leader)

        if joined is not None:
            logger.info(
                "Graph acquisition for bbox %s already in flight; waiting for it instead of re-downloading.",
                bbox.spatial_id,
            )
            G, metadata = joined.result()  # re-raises the leader's error (e.g. NetworkDownloadError)
            # Each request gets its own graph: routing mutates graphs (community evidence).
            hit = self._load_covering_region(bbox, enrich_elevation)
            if hit is not None:
                return hit
            return G.copy(), metadata, False

        try:
            G, metadata = self._acquire_and_cache(bbox, enrich_elevation)
        except BaseException as exc:
            leader.set_exception(exc)
            raise
        else:
            # Waiters load their own copy from the cache (or copy this graph if saving failed).
            leader.set_result((G, metadata))
            return G, metadata, False
        finally:
            with self._inflight_lock:
                self._inflight.pop(bbox.spatial_id, None)

    def _load_covering_region(
        self, bbox: BoundingBox, enrich_elevation: bool
    ) -> Optional[Tuple[nx.MultiDiGraph, RegionMetadata, bool]]:
        """Load a cached or bundled prebuilt region enclosing bbox, or None on miss."""
        hit = self._cache.find_covering_region(
            query_bbox=bbox,
            require_terrain=enrich_elevation,
        )
        if hit is None:
            return None
        region_id, _ = hit
        try:
            G, loaded_meta = self._cache.load_graph(region_id)
        except Exception as exc:
            logger.warning("Cache read failed for region %s: %s. Re-acquiring...", region_id, exc)
            return None
        # Re-attach runtime accessibility model objects if missing from serialized GraphML
        enrich_graph_accessibility(G)
        if self._cache.is_prebuilt(region_id):
            logger.info("Serving bbox %s from prebuilt region %s (no external acquisition).", bbox.spatial_id, region_id)
        return G, loaded_meta, True

    def _acquire_and_cache(self, bbox: BoundingBox, enrich_elevation: bool) -> _AcquiredGraph:
        """Download, enrich and persist the pedestrian network for bbox."""
        logger.info(
            "Cache miss for bbox %s (area=%.2f km²). Acquiring via %s...",
            bbox.spatial_id,
            bbox.area_km2,
            self._provider.provider_name,
        )
        G = self._provider.get_pedestrian_network(bbox)

        # Automatic Stage 2 Accessibility Normalization
        enrich_graph_accessibility(G)

        # Optional Stage 4 Elevation & Terrain Enrichment (with graceful failure fallback)
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

        # Build Metadata & Persist to Cache
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

        return G, metadata


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
