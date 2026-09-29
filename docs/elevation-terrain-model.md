# AccessRoute AI — Stage 4: Elevation & Terrain Intelligence Model

## 1. Executive Summary

In OpenStreetMap pedestrian networks, explicit slope and incline annotations (`incline=*`) are sparse—covering under 0.1% of edges in suburban environments such as Vermont South, Victoria. Without elevation data, routing engines blindly direct wheeled-mobility users into steep, physically exhausting, or hazardous ascents and descents.

Stage 4 establishes a **location-independent, vendor-neutral elevation enrichment and terrain analysis engine** for AccessRoute AI. Nodes and edges are enriched with physical elevation and directional grade without conflating terrain physics with subjective routing decisions.

---

## 2. Elevation Source Research & Evaluation

Before implementation, four major elevation sources and access architectures were evaluated:

| Source | Horizontal Resolution | Vertical Accuracy | Coverage | Licensing & Access | Pedestrian Routing Suitability | Selection Decision |
|---|---|---|---|---|---|---|
| **Geoscience Australia / ELVIS** | 1m – 5m (LiDAR DEM) | < 0.2m | Australia only (major urban/coastal corridors) | Creative Commons (CC-BY 4.0). Requires bulk raster GeoTIFF downloads or ArcGIS REST tile services. | Exceptional vertical and horizontal precision for footpaths; however, no lightweight global keyless API. High storage overhead for multi-region scale. | **Primary National Target** for Australian offline tile deployments in future production stages. |
| **Copernicus DEM (GLO-30)** | 30m (1 arc-second) | ~1.5m RMSE | Global (excluding poles) | Free & open public access. Accessible via open endpoints (Open-Meteo, AWS Registry). | High global consistency. Well-suited for general street and path gradient profiling; requires safeguards for short edges (< 10m). | **Selected Global Baseline** for Stage 4 development and global arbitrary-location routing. |
| **SRTM (Shuttle Radar Topography Mission)** | 30m – 90m | ~6.0m – 10.0m | Global (60°N to 56°S) | Public domain (NASA / USGS). | High vertical noise in urban canyons, canopy voids, and older sensor artifacts. Less accurate than Copernicus GLO-30. | **Rejected** in favor of Copernicus GLO-30. |
| **Open-Meteo Elevation API** | 30m (Copernicus DEM GLO-30 + national DEMs) | 1.5m – 2.0m | Global | Keyless, free open-access JSON API with batch coordinate support. | Efficient for on-demand network enrichment; provides instant location-independence across Australia and internationally without gigabytes of raster dependencies. | **Selected Provider Implementation** for Stage 4 live enrichment with local SQLite caching. |

### Architectural Decision

To ensure AccessRoute AI is **strictly location-independent** while allowing drop-in upgrades (e.g., swapping to Geoscience Australia 1m LiDAR DEM in Melbourne or USGS 3DEP 1m DEM in the US), all elevation logic is isolated behind a clean provider abstraction (`ElevationProvider`).

---

## 3. Elevation Provider Abstraction & Caching

The elevation subsystem is packaged under `accessroute.elevation`:

```
backend/accessroute/elevation/
├── __init__.py           # Unified exports
├── base.py               # Abstract ElevationProvider and reliability metrics
├── cache.py              # SQLite persistent caching layer
├── open_meteo.py         # Copernicus DEM REST provider with circuit breaker
├── synthetic.py          # Deterministic offline mock for testing
└── enricher.py           # Graph enrichment pipeline
```

### ElevationProvider Interface (`base.py`)

```python
class ElevationProvider(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str: ...

    @property
    @abstractmethod
    def resolution_meters(self) -> float: ...

    @abstractmethod
    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]: ...

    @abstractmethod
    def get_elevations(self, coordinates: Sequence[Tuple[float, float]]) -> List[Optional[float]]: ...
```

### Persistent SQLite Caching (`cache.py`)

Repeated network queries for the same physical points waste bandwidth and risk external rate limits. `CachedElevationProvider` implements a transparent proxy:
1. **Deterministic Coordinate Normalization**: Coordinates are rounded to 6 decimal places (~10cm precision).
2. **Transaction-Safe Batch Lookups**: Checks SQLite in a single parameterized SQL query. Only missing coordinates are dispatched to the underlying provider.
3. **Confirmed Data Caching**: Only verified, measured elevations are written to SQLite. Transient network failures or `429 Too Many Requests` remain uncached (`MISSING`), ensuring automatic retry on subsequent sessions.
4. **Circuit Breaker**: When external APIs enforce burst or hourly quotas, an internal circuit breaker backs off gracefully without crashing or thrashing.
5. **Git-Ignored Storage**: Cached databases (`backend/data/cache/*.sqlite`) are excluded from version control.

---

## 4. Directional Grade & Physical Modeling

A pedestrian path is represented in OSMnx as a directed multigraph (`MultiDiGraph`). Incline is intrinsically directional:

$$\Delta h = h_v - h_u$$

$$\text{grade}_{u \to v} = \frac{\Delta h}{L_{uv}}$$

$$\text{grade}_{v \to u} = \frac{-\Delta h}{L_{uv}} \approx -\text{grade}_{u \to v}$$

Where:
- $h_u, h_v$: Node elevations above sea level in metres.
- $L_{uv}$: Physical edge length in horizontal metres.
- $\text{grade}$: Signed decimal slope ($+0.05 = +5\%$ uphill, $-0.05 = -5\%$ downhill).

### Slope Direction Classification

- **Flat**: $|\text{grade}| < 0.02$ ($< 2.0\%$)
- **Uphill**: $\text{grade} \ge +0.02$ ($\ge +2.0\%$)
- **Downhill**: $\text{grade} \le -0.02$ ($\le -2.0\%$)

---

## 5. Short-Edge Safeguards & Uncertainty Management

### The DEM Jitter Problem

On a pedestrian network, edges can be very short (e.g., kerb cuts, crossing stubs, intersection junctions measuring 2m to 6m). Given a DEM vertical resolution with $\pm 1.5\text{m}$ RMSE:

$$\Delta h = 1.5\text{m} \implies \text{grade} = \frac{1.5}{3.0\text{m}} = 50\%$$

A flat crossing stub could erroneously calculate as a 50% cliff purely due to grid discretization and vertical noise.

### Safeguards Implemented

1. **Short-Edge Flagging (`MIN_RELIABLE_EDGE_LENGTH_M = 10.0m`)**:
   Any edge shorter than 10 metres whose calculated absolute grade exceeds 10% is marked with `is_grade_suspicious = True` and tagged with `SUSPICIOUS_GRADE_FLAGGED`.
2. **Plausibility Threshold (`SUSPICIOUS_GRADE_THRESHOLD = 0.25`)**:
   Calculated grades exceeding 25% (or 35% on very short links) are flagged as suspicious.
3. **No Silent Clamping**:
   Suspicious slopes are never silently clamped or disguised. The true raw measurement is retained in `EdgeTerrainEvidence` alongside explicit quality flags and uncertainty findings.
4. **Explicit Unknown Handling**:
   If either endpoint node lacks elevation, the edge grade is explicitly `None` (`grade_availability = UNKNOWN`). Zero elevation is **never** assumed.

---

## 6. Multi-Criteria Cost Separation

AccessRoute AI maintains a strictly separated, four-part additive cost model:

$$\text{Cost}(e) = w_d \cdot D(e) + C_{\text{access}}(e) + C_{\text{terrain}}(e) + C_{\text{uncertainty}}(e)$$

### Terrain Cost Formulation

$$C_{\text{terrain}}(e) = w_{\text{terrain}} \cdot \left[ P_{\text{uphill}}(e) + P_{\text{downhill}}(e) \right]$$

1. **Uphill Penalty ($P_{\text{uphill}}$)**:
   For an uphill slope with grade $g > 0$:
   - If $g \le g_{\text{pref}}$: No penalty ($0\text{m}$).
   - If $g > g_{\text{pref}}$: Penalty scales linearly with steepness and distance:
     $$P_{\text{uphill}} = (g - g_{\text{pref}}) \cdot 100 \cdot k_{\text{uphill}} \cdot \frac{L(e)}{100\text{m}}$$
   - If $g > g_{\text{perm}}$ and `prohibit_steep_incline = True`: Edge is strictly prohibited ($\text{Cost} = \infty$).
2. **Downhill Steepness Penalty ($P_{\text{downhill}}$)**:
   Steep descents present severe runaway or brake-failure risks for wheeled devices. If $|g| > 0.08$ ($-8\%$ downhill):
   $$P_{\text{downhill}} = (|g| - 0.08) \cdot 100 \cdot k_{\text{downhill}} \cdot \frac{L(e)}{100\text{m}}$$
3. **Missing Elevation Uncertainty**:
   If an edge lacks elevation evidence, an uncertainty cost is added:
   $$C_{\text{uncertainty}}(e) += U_{\text{missing\_elevation}} \cdot \frac{L(e)}{100\text{m}}$$

### Policy Presets

| Parameter | Distance-First | Balanced (Default) | Conservative |
|---|---|---|---|
| `terrain_weight` | 0.0 | 1.0 | 2.0 |
| `max_preferred_uphill_grade_pct` | 15.0% | 5.0% | 4.0% |
| `max_permitted_uphill_grade_pct` | 25.0% | 12.0% | 8.33% (1:12 AS 1428.1 ramp standard) |
| `prohibit_steep_incline` | False | False | True |
| `penalty_per_uphill_grade_pct_m` | 0.0m | 10.0m | 25.0m |
| `penalty_steep_downhill_pct_m` | 0.0m | 5.0m | 15.0m |
| `uncertainty_missing_elevation_m` | 0.0m | 3.0m | 10.0m |

---

## 7. Directionality Proof ($A \to B \ne B \to A$)

Because $C_{\text{terrain}}(e)$ evaluates signed directional grade:
- Ascending a hill incurs high uphill grade penalties.
- Descending the identical hill incurs negligible penalties (or a modest steep-descent caution).
- In the Vermont South validation tests, routing from Node 27170599 $\to$ 628395211 (uphill) incurs **131.4 virtual metres** of terrain cost, whereas the reverse direction (downhill) incurs **111.6 virtual metres** ($\Delta = 19.8\text{m}$).

---

## 8. Deterministic, Evidence-Based Explanations

In accordance with Stage 3 corrections, all explanations are strictly tied to recorded evidence and avoid ungrounded superlatives:

| Evidence Condition | Generated Explanation |
|---|---|
| Baseline has steep uphill ($>8\%$), accessible route is gentler | `"Route avoids a recorded steep uphill slope (reduces maximum uphill grade from 46.0% to 15.0%)."` |
| Route has recorded elevation profile | `"Elevation profile: +5.0m climb, -3.0m descent (max recorded uphill grade: 15.0%)."` |
| Route includes recorded steep segment ($>8\%$) | `"Warning: Route includes recorded steep uphill sections (up to 15.0% grade)."` |
| Route includes recorded steep descent ($<-10\%$) | `"Caution: Route includes steep downhill descent (grade -26.7%)."` |
| Partial elevation coverage | `"Data notice: Elevation information is unrecorded for 32% of this route."` |
| Questionable short-edge grades | `"Data notice: 2 segment(s) have uncertain slope calculations due to short segment length."` |
