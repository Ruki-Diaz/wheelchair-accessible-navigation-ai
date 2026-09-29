"""Spatial regional graph caching with metadata versioning and atomic persistence."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid
import networkx as nx
import osmnx as ox

from accessroute.config import DEFAULT_CACHE_DIR
from accessroute.graph.errors import CacheCorruptionError
from accessroute.graph.loader import validate_graph
from accessroute.graph.region import BoundingBox

logger = logging.getLogger(__name__)

CURRENT_ACCESSIBILITY_VERSION = "2.0"
CURRENT_TERRAIN_VERSION = "4.0"
CURRENT_FORMAT_VERSION = "1.0"

DEFAULT_REGIONAL_CACHE_DIR = DEFAULT_CACHE_DIR / "regions"


@dataclass
class RegionMetadata:
    """Metadata describing a cached geographic pedestrian network region."""

    region_id: str
    bbox: BoundingBox
    created_at: str
    node_count: int
    edge_count: int
    osm_loaded: bool = True
    accessibility_enriched: bool = True
    accessibility_model_version: str = CURRENT_ACCESSIBILITY_VERSION
    terrain_enriched: bool = False
    terrain_model_version: str = CURRENT_TERRAIN_VERSION
    graph_format_version: str = CURRENT_FORMAT_VERSION
    source: str = "openstreetmap:walk"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "bbox": self.bbox.to_dict(),
            "created_at": self.created_at,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "osm_loaded": self.osm_loaded,
            "accessibility_enriched": self.accessibility_enriched,
            "accessibility_model_version": self.accessibility_model_version,
            "terrain_enriched": self.terrain_enriched,
            "terrain_model_version": self.terrain_model_version,
            "graph_format_version": self.graph_format_version,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegionMetadata":
        bbox = BoundingBox.from_dict(data["bbox"])
        return cls(
            region_id=data["region_id"],
            bbox=bbox,
            created_at=data["created_at"],
            node_count=int(data["node_count"]),
            edge_count=int(data["edge_count"]),
            osm_loaded=bool(data.get("osm_loaded", True)),
            accessibility_enriched=bool(data.get("accessibility_enriched", True)),
            accessibility_model_version=str(data.get("accessibility_model_version", "1.0")),
            terrain_enriched=bool(data.get("terrain_enriched", False)),
            terrain_model_version=str(data.get("terrain_model_version", "1.0")),
            graph_format_version=str(data.get("graph_format_version", "1.0")),
            source=str(data.get("source", "unknown")),
        )


def _sanitize_graph_for_graphml(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Prepare a graph for GraphML serialization by stripping None values and non-primitive objects."""
    G_clean = graph.copy()
    for _, data in G_clean.nodes(data=True):
        to_del = [k for k, v in list(data.items()) if v is None or k.startswith("_")]
        for k in to_del:
            del data[k]
    for _, _, data in G_clean.edges(data=True):
        to_del = [k for k, v in list(data.items()) if v is None or k.startswith("_")]
        for k in to_del:
            del data[k]
    return G_clean


class RegionalGraphCache:
    """Manages on-disk caching, spatial indexing, and atomic writes of regional pedestrian graphs."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_REGIONAL_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def find_covering_region(
        self,
        query_bbox: BoundingBox,
        require_terrain: bool = False,
        min_accessibility_version: str = CURRENT_ACCESSIBILITY_VERSION,
        min_terrain_version: str = CURRENT_TERRAIN_VERSION,
    ) -> Optional[Tuple[str, RegionMetadata]]:
        """Search existing cached regions for one that completely encloses query_bbox.

        Args:
            query_bbox: The requested bounding box including route buffers.
            require_terrain: If True, candidate must have compatible terrain enrichment.
            min_accessibility_version: Minimum accepted accessibility model version.
            min_terrain_version: Minimum accepted terrain model version.

        Returns:
            Tuple of (region_id, RegionMetadata) if a covering region is found, else None.
        """
        candidates: List[Tuple[float, str, RegionMetadata]] = []

        for meta_path in self._cache_dir.glob("*.json"):
            if meta_path.name.endswith(".tmp.json"):
                continue

            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = RegionMetadata.from_dict(data)
            except Exception as exc:
                logger.warning("Could not read metadata from %s: %s", meta_path, exc)
                continue

            # Verify version compatibility
            if meta.accessibility_model_version < min_accessibility_version:
                continue

            if require_terrain:
                if not meta.terrain_enriched or meta.terrain_model_version < min_terrain_version:
                    continue

            # Check spatial containment
            if meta.bbox.contains_box(query_bbox):
                # Prefer the most tightly bounded covering region to minimize graph size
                candidates.append((meta.bbox.area_km2, meta.region_id, meta))

        if not candidates:
            return None

        # Sort by area ascending so we pick the most localized covering graph
        candidates.sort(key=lambda c: c[0])
        best_area, best_id, best_meta = candidates[0]
        logger.info(
            "Spatial cache HIT: Query bbox (area=%.2f km²) covered by region %s (area=%.2f km²).",
            query_bbox.area_km2,
            best_id,
            best_area,
        )
        return (best_id, best_meta)

    def load_graph(self, region_id: str) -> Tuple[nx.MultiDiGraph, RegionMetadata]:
        """Load a cached regional graph and its metadata from disk.

        Args:
            region_id: Identifier of the region.

        Returns:
            Tuple of (MultiDiGraph, RegionMetadata).

        Raises:
            CacheCorruptionError: If files are missing, unreadable, or corrupted.
        """
        graph_path = self._cache_dir / f"{region_id}.graphml"
        meta_path = self._cache_dir / f"{region_id}.json"

        if not graph_path.exists() or not meta_path.exists():
            raise CacheCorruptionError(
                f"Cached region '{region_id}' is missing required files ({graph_path} or {meta_path})."
            )

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = RegionMetadata.from_dict(json.load(f))
        except Exception as exc:
            raise CacheCorruptionError(f"Failed to read metadata for region {region_id}: {exc}") from exc

        try:
            G = ox.load_graphml(filepath=graph_path)
            validate_graph(G)
        except Exception as exc:
            raise CacheCorruptionError(f"Failed to load or validate GraphML for {region_id}: {exc}") from exc

        return G, meta

    def save_graph(self, graph: nx.MultiDiGraph, metadata: RegionMetadata) -> None:
        """Persist a regional graph and its metadata to disk using atomic file replacements.

        Args:
            graph: The enriched pedestrian MultiDiGraph.
            metadata: Metadata describing the region.

        Raises:
            IOError: If files cannot be written.
        """
        region_id = metadata.region_id
        unique_token = uuid.uuid4().hex[:8]

        tmp_graph = self._cache_dir / f"{region_id}_{unique_token}.graphml.tmp"
        tmp_meta = self._cache_dir / f"{region_id}_{unique_token}.json.tmp"

        final_graph = self._cache_dir / f"{region_id}.graphml"
        final_meta = self._cache_dir / f"{region_id}.json"

        try:
            # Step 1: Sanitize graph to strip None and internal objects before GraphML write
            clean_graph = _sanitize_graph_for_graphml(graph)
            ox.save_graphml(clean_graph, filepath=tmp_graph)

            # Step 2: Write JSON metadata to temporary file
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(metadata.to_dict(), f, indent=2)

            # Step 3: Atomic rename (POSIX atomic replacement)
            os.replace(tmp_graph, final_graph)
            os.replace(tmp_meta, final_meta)

            logger.info(
                "Successfully cached regional graph '%s' (%d nodes, %d edges) to %s",
                region_id,
                metadata.node_count,
                metadata.edge_count,
                self._cache_dir,
            )

        except Exception as exc:
            # Clean up temporary files on failure
            if tmp_graph.exists():
                tmp_graph.unlink(missing_ok=True)
            if tmp_meta.exists():
                tmp_meta.unlink(missing_ok=True)
            raise IOError(f"Failed to atomically persist regional graph {region_id}: {exc}") from exc

    def list_regions(self) -> List[RegionMetadata]:
        """List metadata for all valid cached regions."""
        results: List[RegionMetadata] = []
        for meta_path in self._cache_dir.glob("*.json"):
            if meta_path.name.endswith(".tmp.json"):
                continue
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    results.append(RegionMetadata.from_dict(json.load(f)))
            except Exception:
                continue
        return results

    list_cached_regions = list_regions


    def clear_cache(self) -> None:
        """Remove all regional graphs and metadata files from the cache directory."""
        for path in self._cache_dir.glob("reg_*"):
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Could not delete %s: %s", path, exc)
