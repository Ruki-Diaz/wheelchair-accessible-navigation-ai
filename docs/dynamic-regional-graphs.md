# AccessRoute AI — Stage 5: Arbitrary-Location Dynamic Graph Acquisition & Regional Caching

## 1. Executive Summary

Prior to Stage 5, AccessRoute AI operated exclusively on pre-downloaded, static bounding graphs (principally Vermont South, Victoria). Stage 5 removes this geographic boundary, transforming AccessRoute into a **location-independent routing engine** capable of dynamically discovering, downloading, normalizing, enriching, and caching pedestrian networks for arbitrary geographic coordinates worldwide.

---

## 2. End-to-End Dynamic Routing Pipeline

When a user requests a route between two arbitrary coordinates:

```
Origin (lat, lon)  &  Destination (lat, lon)
                     │
                     ▼
      1. Coordinate Validation & Safeguards
         - Physical bounds check: lat in [-90, 90], lon in [-180, 180]
         - Numerical safety: NaN / inf rejection
         - Operational limits: max separation (10 km), max area (50 km²)
                     │
                     ▼
      2. Dynamic Bounding Box & Adaptive Buffer Generation
         - Calculates minimum bounding box
         - Adds adaptive buffer: max(350m, separation * 0.25)
         - Preserves detour alternatives around inaccessible barriers
                     │
                     ▼
      3. Spatial Regional Cache Lookup
         - Scans cached regions in backend/data/cache/regions/
         - Evaluates spatial containment: cached_bbox.contains_box(query_bbox)
         - Verifies model version compatibility (accessibility_v2.0, terrain_v4.0)
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
    [CACHE HIT]             [CACHE MISS]
   Reuses cached            Acquires network via
   MultiDiGraph             GraphProvider (OSM Overpass)
   instantly                     │
   (< 20ms)                      ▼
                     4. Automatic Stage 2 Accessibility Normalization
                        - Standardizes wheelchair, kerb, surface, crossings
                        - Extracts deterministic findings
                                 │
                                 ▼
                     5. Optional Stage 4 Terrain Enrichment
                        - Queries Copernicus DEM via CachedElevationProvider
                        - Calculates directional grades
                        - Falls back gracefully to UNKNOWN if API unavailable
                                 │
                                 ▼
                     6. Atomic Cache Persistence
                        - Writes GraphML and JSON metadata with unique tmp tokens
                        - Executes POSIX atomic rename (prevents corruption)
                     │
         ┌───────────┘
         ▼
      7. Spatial Network Snapping & Quality Audit
         - Snaps origin & destination to nearest walkable nodes
         - Flags snapping distance warning if distance > 150m
                     │
                     ▼
      8. Multi-Criteria A* Search & Factual Explainability
         - Computes accessible route under active policy
         - Computes distance-first baseline for comparative rationales
         - Returns CoordinatedRouteResult with complete spatial telemetry
```

---

## 3. Geographic Region Generation & Adaptive Buffering

### The Boundary Truncation Risk
A naive bounding box constructed strictly between origin and destination coordinates truncates alternative routes. If the direct path contains stairs or impassable obstacles, the router requires lateral detours. If the bounding box tightly clips the direct corridor, valid accessible detours are pruned by the network boundary.

### Adaptive Buffering Formulation

$$\text{effective\_buffer} = \max(\text{buffer\_meters}, d_{\text{separation}} \cdot \text{buffer\_ratio})$$

Where:
- $\text{buffer\_meters} = 350.0\text{m}$ (fixed minimum safety margin)
- $\text{buffer\_ratio} = 0.25$ (25% proportional expansion)

Metric distances are converted to geographic degree deltas:

$$\Delta \text{lat} = \frac{\text{effective\_buffer}}{111,000\text{m}}$$

$$\Delta \text{lon} = \frac{\text{effective\_buffer}}{111,000\text{m} \cdot \max(0.01, \cos(\text{center\_lat}))}$$

### Operational Development Safeguards
To prevent denial-of-service or memory exhaustion from accidental long-distance queries:
- **Maximum Straight-Line Separation**: `10,000m` (10 km). Queries exceeding this trigger `RouteRegionTooLargeError`.
- **Maximum Bounding Box Area**: `50.0 km²`.
- *Note*: Long-distance multi-kilometer pedestrian routing in production will leverage hierarchical spatial tiling rather than single-bounding-box Overpass queries.

---

## 4. Graph Provider Abstraction

To decouple the routing engine from OpenStreetMap and OSMnx, network retrieval is mediated through an abstract interface:

```python
class GraphProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph: ...
```

### Implementations
1. **`OpenStreetMapGraphProvider`**:
   - Queries OpenStreetMap via OSMnx 2.x `graph_from_bbox(bbox=(west, south, east, north), network_type="walk", simplify=True)`.
   - Injects required accessibility tags (`ACCESSIBILITY_WAY_TAGS` and `ACCESSIBILITY_NODE_TAGS`) into OSMnx settings.
   - Converts Overpass 504 / timeout / network failures into structured domain errors (`NetworkDownloadError`, `NoPedestrianNetworkError`).
2. **`SyntheticGraphProvider`**:
   - Deterministic offline mock used for automated tests and isolated regression suites without network dependencies.

---

## 5. Spatial Regional Graph Cache

Cached networks are stored under `backend/data/cache/regions/` (gitignored). Rather than naming files by human addresses, regions are indexed by their geographic bounding boxes and deterministic spatial IDs:

### Cache Metadata Schema (`RegionMetadata`)

```json
{
  "region_id": "reg_7a9f2b8c4d1e",
  "bbox": {
    "south": -37.8250,
    "west": 144.9600,
    "north": -37.8100,
    "east": 144.9750
  },
  "created_at": "2026-09-24T14:30:00Z",
  "node_count": 842,
  "edge_count": 2150,
  "osm_loaded": true,
  "accessibility_enriched": true,
  "accessibility_model_version": "2.0",
  "terrain_enriched": true,
  "terrain_model_version": "4.0",
  "graph_format_version": "1.0",
  "source": "openstreetmap:walk"
}
```

### Spatial Containment Reuse
When a route is requested:
1. `RegionalGraphCache.find_covering_region(query_bbox)` inspects existing cached metadata.
2. If `cached_bbox.contains_box(query_bbox)` is `True` and model versions match:
   - **Cache Hit**: Reuses the cached network immediately.
   - If multiple cached regions cover the query, the engine selects the region with the smallest area to minimize memory footprint.
3. If partial overlap occurs, the engine acquires a new region covering the query bounding box (deferring risky in-memory graph stitching to avoid topological inconsistencies).

### Atomic File Persistence
To ensure concurrency safety and prevent corrupt reads:
1. GraphML is written to `{region_id}_{uuid}.graphml.tmp`.
2. Metadata is written to `{region_id}_{uuid}.json.tmp`.
3. Files are renamed via `os.replace` (POSIX atomic replacement).

---

## 6. Snapping Quality & Distance Safeguards

For arbitrary locations, coordinate-to-network snapping quality is critical:
- `origin_snap_distance_m`: Distance in meters from requested origin to nearest network node.
- `destination_snap_distance_m`: Distance in meters from requested destination to nearest network node.
- **Warning Threshold (`150.0m`)**: If either snapping distance exceeds 150m, AccessRoute flags a snapping notice:
  - `"Notice: Requested coordinate is 182m from nearest mapped pedestrian path."`
  - Prevents users from being misled when starting from an unmapped park interior or private lot.

---

## 7. Terrain Source Transparency & Estimation Caveat

Following Stage 4 findings, digital elevation models (Copernicus DEM 30m) introduce vertical quantization ($\pm 1.5\text{m}$) that can produce misleading slope artifacts on short pedestrian links (< 10m).

Stage 5 strictly enforces evidence-based phrasing:
- Grades derived from digital elevation models are labeled **"estimated grade"**, **"DEM-derived grade"**, or **"estimated terrain gradient"**.
- The term **"recorded grade"** is reserved strictly for explicit OpenStreetMap survey tags (`incline=*`).
