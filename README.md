# AccessRoute AI — Wheelchair-Accessible Pedestrian Navigation System

> **🟢 CURRENT STAGE STATUS (STAGE 14 COMPLETE):**  
> AccessRoute AI has completed **Stages 1 through 14**.  
> The system features **Installable Mobile PWA, Offline Navigation & Field Surveying** (`backend/accessroute/offline/`, `backend/accessroute/api/static/`, service worker, manifest, and offline store). Capabilities include: Full Progressive Web App compliance (Web App Manifest, standalone display, home-screen installation, adaptive icons, and system shortcuts); Multi-tiered service worker caching (`accessroute-shell-v1`, `accessroute-routes-v1`, `accessroute-map-v1`) with cache-first shell and network-first dynamic fallbacks; Self-contained `OfflineRoutePackage` (`stage14_v1`) capturing multi-criteria A* geometry, maneuvers, elevation profiles, entrance intelligence, and community evidence snapshots; Asynchronous IndexedDB storage (`routes`, `routeEvidence`, `communityQueue`, `verificationMissions`, `mapRegions`, `syncMetadata`); Real-time offline GPS navigation via `navigator.geolocation.watchPosition` with client-side cross-track projection, maneuver countdown, and lookahead accessibility alerts; Safe offline deviation detection with honest user guidance preventing fabricated or unvalidated reroutes; Multi-state `ConnectivityManager` (ONLINE, DEGRADED, OFFLINE, SYNCING) with non-color-only UI indicators; Idempotent batch synchronization protecting against duplicate community reports via client UUID keys; Dedicated Field Survey Mode with one-touch observations, distance tracking, and client-side compressed photo evidence; Adaptive `OfflineMapProvider` featuring Mode C high-contrast vector canvas fallback when raster tiles are unavailable; Screen Wake Lock API integration during active navigation; update deferral during active transit; All 12 controlled experiments (A through L) passing; and **271 passing automated tests** with zero regressions.

---

## 1. Project Overview

**AccessRoute AI** is an advanced pedestrian navigation system engineered specifically for wheelchair users, mobility scooter riders, and individuals with physical accessibility requirements. 

Traditional navigation services (such as Google Maps or Apple Maps) prioritize travel time and distance, often routing pedestrians across stairs, steep grades, unramped kerbs, or impassable terrain. AccessRoute AI addresses this by building an accessibility-aware routing engine that distinguishes between confirmed accessible paths, confirmed barriers, potentially difficult surfaces, and unknown terrain.

### Academic Origin
The project originated as an academic research prototype in **SIT215 Computational Intelligence** by Angodavidanelage Rukshan Anthony Dias (Deakin University). The prototype demonstrated heuristic-based pathfinding using a custom A* algorithm on a manually constructed 35-node graph of Vermont South, Victoria. AccessRoute AI evolves this proven algorithmic foundation into a production-grade, real-world navigation system using open spatial data.

---

## 2. Dynamic Regional & Multi-Criteria Architecture (Stage 5)

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Query & Routing Policy                  │
│       Origin / Destination + RoutingPolicy (e.g. Balanced)       │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│     Dynamic Graph Manager & Spatial Regional Cache (Stage 5)    │
│  - Adaptive bounding box buffering: max(350m, dist * 0.25)      │
│  - Spatial containment check: cached_bbox.contains_box(query)   │
│  - Instant cache reuse (< 20ms) or on-demand OSM acquisition    │
│  - Atomic POSIX file writes with metadata versioning            │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│      Accessibility & Elevation Enrichment Pipelines (Stages 2/4)│
│  - Stage 2: Normalizes wheelchair, kerb, surface, crossings     │
│  - Stage 4: Copernicus DEM elevations & directional grade       │
│  - Graceful fallback to UNKNOWN if elevation API unavailable    │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│      Multi-Criteria Cost Evaluator (accessroute.routing)         │
│  Total Cost C(e) = w_d·D(e) + C_access(e) + C_terrain(e) + C_unc(e)
│  - D: Physical Distance (m)                                     │
│  - C_access: Soft Accessibility Cost (unpaved, raised kerbs)    │
│  - C_terrain: Directional Uphill/Downhill Slope Penalties       │
│  - C_unc: Contextual Uncertainty Cost (missing kerbs/elevation) │
│  - Prunes hard exclusions (wheelchair=no, unramped stairs/slopes)│
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│           Custom Admissible A* Engine (accessroute.routing)     │
│  - Dynamic MultiDiGraph parallel edge selection                 │
│  - Admissible heuristic: h(u, G) = w_d · haversine(u, G)        │
│  - Verified identical to Dijkstra optimal cost (Δ = 0.0000m)    │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│             Explainability & Route Comparison Engine             │
│  - Baseline (Distance-Only) vs Accessible Route comparison      │
│  - Directionality proof: A -> B != B -> A under grade evaluation│
│  - Deterministic findings: barriers avoided, elevation gain/loss│
│  - Folium layered comparison map with terrain telemetry HUD     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
wheelchair-accessible-navigation-ai/
├── backend/
│   ├── accessroute/                      # Core Python routing package
│   │   ├── __init__.py
│   │   ├── config.py                     # Geographic areas, raw OSM tags, prototype coordinates
│   │   ├── destinations/                 # Stage 13 Accessible Destination & Entrance Intelligence
│   │   │   ├── __init__.py
│   │   │   ├── models.py                 # Venue, Entrance, Assessment domain models
│   │   │   ├── resolver.py               # DestinationResolver (venue vs address vs coords)
│   │   │   ├── entrances.py              # OSMEntranceDiscovery with disk caching & synthesis
│   │   │   ├── evidence.py               # EntranceEvidenceCollector (OSM + Community)
│   │   │   ├── assessment.py             # Deterministic EntranceAssessmentEngine
│   │   │   └── service.py                # DestinationService orchestrator
│   │   ├── elevation/                    # Stage 4 Elevation & Terrain Intelligence
│   │   │   ├── __init__.py
│   │   │   ├── base.py                   # ElevationProvider ABC & reliability thresholds
│   │   │   ├── cache.py                  # Persistent SQLite coordinate cache (elevation_cache.sqlite)
│   │   │   ├── enricher.py               # Graph node elevation & edge directional grade enrichment
│   │   │   ├── open_meteo.py             # Copernicus DEM GLO-30 API provider with circuit breaker
│   │   │   └── synthetic.py              # Offline deterministic elevation provider for testing
│   │   ├── graph/                        # Stage 5 Dynamic Ingestion & Regional Caching
│   │   │   ├── __init__.py
│   │   │   ├── enricher.py               # Graph enrichment pipeline with accessibility evidence
│   │   │   ├── errors.py                 # Structured domain exceptions (bounds, size, download)
│   │   │   ├── loader.py                 # GraphML caching & validation (legacy areas)
│   │   │   ├── manager.py                # DynamicGraphManager orchestrating route graph retrieval
│   │   │   ├── provider.py               # GraphProvider ABC, OpenStreetMapGraphProvider & Synthetic
│   │   │   ├── region.py                 # BoundingBox, metric adaptive buffer, spatial indexing
│   │   │   ├── regional_cache.py         # RegionalGraphCache with atomic writes & versioning
│   │   │   └── snapper.py                # Coordinate-to-node snapping with quality thresholds
│   │   ├── routing/                      # Multi-criteria pathfinding & policies
│   │   │   ├── __init__.py
│   │   │   ├── astar.py                  # Custom A* operating on MultiDiGraphs (terrain-aware)
│   │   │   ├── cost_evaluator.py         # Multi-criteria edge cost calculation, terrain & pruning
│   │   │   ├── explainability.py         # Deterministic route rationale & barrier avoidance engine
│   │   │   ├── heuristics.py             # Great-circle Haversine heuristic (admissible)
│   │   │   ├── policy.py                 # Configurable RoutingPolicy definitions & presets
│   │   │   ├── router.py                 # High-level route planning, comparison & alternatives
│   │   │   └── service.py                # Stage 5 end-to-end route_between_coordinates service
│   │   ├── scoring/                      # Accessibility data extraction & normalisation
│   │   │   ├── __init__.py
│   │   │   ├── analyzer.py               # Network-wide accessibility coverage & missingness auditor
│   │   │   ├── models.py                 # Enums & dataclasses (WheelchairAccess, EdgeTerrainEvidence, etc.)
│   │   │   └── normalizer.py             # Resilient raw OSM tag normalization & findings extractor
│   │   └── visualization/                # Folium mapping
│   │       ├── __init__.py
│   │       └── map.py                    # Multi-route comparison & layered visualization with HUD
│   ├── data/
│   │   └── cache/                        # Cached .graphml networks, regional DBs & SQLite (gitignored)
│   ├── tests/                            # Automated pytest suite (257 passing tests)
│   │   ├── __init__.py
│   │   ├── conftest.py                   # Synthetic & real graph fixtures
│   │   ├── test_accessible_routing.py    # Multi-criteria routing, policies, and A* optimality
│   │   ├── test_astar.py                 # Core A* correctness, parallel edges & Dijkstra benchmarks
│   │   ├── test_dynamic_graph.py         # Stage 5 dynamic acquisition, bounding boxes, spatial caching
│   │   ├── test_elevation.py             # Elevation providers, SQLite caching, short-edge safeguards
│   │   ├── test_graph_loader.py          # Loader, cache & validation tests
│   │   ├── test_route_service.py         # Stage 5 coordinate-to-coordinate routing service & snapping
│   │   ├── test_scoring.py               # Accessibility normalization & deterministic findings
│   │   ├── test_snapper.py               # Coordinate snapping tests
│   │   ├── test_stage12_platform.py      # Stage 12 PostGIS, auth, sync, and isolation tests
│   │   ├── test_stage13_destinations.py  # Stage 13 destination & entrance intelligence tests
│   │   └── test_terrain_routing.py       # Terrain penalties, directionality, and steep slope pruning
│   ├── requirements.txt                  # Python dependencies
│   ├── pyproject.toml                    # Modern packaging configuration
│   ├── run_stage1_demo.py                # Stage 1 baseline demo CLI script
│   ├── run_stage2_analysis.py            # Stage 2 accessibility coverage auditor CLI script
│   ├── run_stage3_experiments.py         # Stage 3 real-world routing experiments CLI script
│   ├── run_stage4_analysis.py            # Stage 4 elevation & grade distribution auditor
│   ├── run_stage4_experiments.py         # Stage 4 terrain-aware routing experiments CLI script
│   ├── run_dynamic_route.py              # Stage 5 arbitrary-coordinate routing CLI tool
│   ├── run_stage5_analysis.py            # Stage 5 multi-city acquisition & cross-region audit
│   ├── run_stage12_platform_experiments.py # Stage 12 platform experiments CLI script
│   └── run_stage13_destination_experiments.py # Stage 13 destination & entrance experiments CLI script
├── dev_maps/                             # Generated development HTML maps (gitignored)
│   ├── vermont_south_stage1_route.html   # Baseline Stage 1 map
│   ├── experiment_a_steps_avoidance.html # Real stairs avoidance comparison map
│   ├── experiment_b_surface_preference.html # Real unpaved surface avoidance map
│   ├── vermont_south_stage4_terrain_route.html # Stage 4 terrain comparison map
│   ├── stage5_melbourne_cbd_route.html   # Stage 5 dynamic Melbourne route
│   └── stage5_london_westminster_route.html # Stage 5 dynamic London route
├── docs/                                 # Architectural specifications
│   ├── accessibility-data-model.md       # Stage 2 data model and normalizer specification
│   ├── accessibility-routing-model.md    # Stage 3 multi-criteria routing & explainability model
│   ├── elevation-terrain-model.md        # Stage 4 elevation & terrain intelligence model
│   ├── dynamic-regional-graphs.md        # Stage 5 dynamic acquisition & regional caching model
│   └── stage13-destination-and-entrance-intelligence.md # Stage 13 destination & entrance model
├── HD level s224326349.ipynb             # Preserved original university prototype
├── README.txt                            # Preserved original prototype instructions
├── assign1problemsolving_report.pdf      # Preserved academic report
├── wheelchair_accessible_map.html        # Preserved prototype map export (5 markers)
├── wheelchair_accessible_map 30.html     # Preserved prototype map export (35 markers)
├── .gitignore                            # Git exclusion rules
└── README.md                             # This document
```

---

## 4. Setup & Installation

### Prerequisites
- Python 3.10 or higher (tested on Python 3.13.9 macOS / Linux)

### Installation
Clone the repository and install dependencies:

```bash
cd wheelchair-accessible-navigation-ai
pip install -r backend/requirements.txt
```

Alternatively, install in editable mode:
```bash
pip install -e backend/
```

---

## 5. Running the Stage 3 Real-World Routing Experiments

Run the Stage 3 experiment suite against the real Vermont South OpenStreetMap network:

```bash
python3 backend/run_stage3_experiments.py
```

This utility executes controlled real-world experiments:
- **Experiment A (Stairs Avoidance)**: Demonstrates that the baseline shortest path routes across a 26.2m outdoor staircase (Node 629887508 $\rightarrow$ 629887848), while the accessibility-aware router prunes the stairs and discovers a safe 182.4m paved ramp detour (+156.2m), explicitly reporting `Barriers avoided: ['Outdoor Stairs']`. Map output: `dev_maps/experiment_a_steps_avoidance.html`.
- **Experiment B (Surface Preference)**: Demonstrates that under the Conservative policy, the router bypasses a 16.7m unpaved grass path in favor of a 37.2m smooth paved path (+20.5m detour). Map output: `dev_maps/experiment_b_surface_preference.html`.
- **Experiment C & D (Crossing Uncertainty)**: Demonstrates that crossings with missing kerb evidence are penalized relative to verified flush/lowered kerb crossings.
- **Experiment E (Parallel MultiDiGraph Edges)**: Proves that between two parallel edges connecting the same nodes, the engine selects the accessible ramp over the stairs.

---

## 6. Running the System Locally (Stage 7 Public MVP)

### Launch the FastAPI Service & Browser Application
```bash
PYTHONPATH=backend uvicorn accessroute.api.main:app --host 127.0.0.1 --port 8000 --reload
```
- **Public Navigation App**: Visit `http://127.0.0.1:8000/` to test place search, route alternatives comparison, turn-by-turn guidance, interactive elevation profiles, and the segment evidence inspector on desktop or mobile viewports.
- **Interactive OpenAPI Documentation**: Visit `http://127.0.0.1:8000/docs`.

---

## 7. Running the Automated Test Suite

Run `pytest` across all **257 passing unit and integration tests**:

```bash
DATABASE_URL="postgresql://localhost/accessroute_db" PYTHONPATH=backend pytest backend/tests/ -v
```

The test suite covers:
- **Stage 13 Destination & Entrance Intelligence (18 tests)**: Destination resolution (venues vs addresses vs coordinates), OSM entrance discovery, tag normalization, radius gating, multi-source evidence collection, temporary outage expiration, deterministic entrance accessibility assessment, direct route-to-entrance pathfinding, and API contracts.
- **Stage 12 Platform & PostGIS (11 tests)**: Reverse geocoding, password hashing, JWT tokens, user registration/login, mobility preference sync, saved places/routes CRUD with cross-user isolation, contributor anti-spoofing, and PostGIS repository contract.
- **Stage 7–11 Public MVP, Navigation, Community & Offline (100+ tests)**: Turn-by-turn guidance, GPS snapping, off-route rerouting, speech synthesis prompts, community observations, and offline pack management.
- **Stage 4 & 5 Dynamic Regional Graphs & Terrain (30+ tests)**: Bounding box expansion, Open-Meteo elevation queries, directional slope classification, and 30m Copernicus DEM enrichment.
- **Stage 3 Multi-Criteria Routing (40+ tests)**: Custom admissible A*, barrier exclusions, uncertainty penalties, Dijkstra cost equivalence benchmark.
- **Stage 2 Accessibility Normalization (35+ tests)**: Wheelchair attributes, kerb transitions, surface categories, incline parsing, and explicit missing-data modeling.
- **Stage 1 Geographic Routing Foundation (20+ tests)**: OSMnx pedestrian graphs, spatial caching, coordinate snapping, and Haversine heuristic admissibility.

---

## 8. Running Controlled Experiments

- **Stage 14 PWA, Offline Navigation & Field Mode Experiments (A through L)**:
  ```bash
  python backend/run_stage14_offline_experiments.py
  ```
- **Stage 13 Destination & Entrance Experiments (A through J)**:
  ```bash
  DATABASE_URL="postgresql://localhost/accessroute_db" PYTHONPATH=backend python backend/run_stage13_destination_experiments.py
  ```
- **Stage 12 Platform & PostGIS Experiments (A through N)**:
  ```bash
  DATABASE_URL="postgresql://localhost/accessroute_db" PYTHONPATH=backend python backend/run_stage12_platform_experiments.py
  ```
- **Stage 3 Real-World Routing Experiments**:
  ```bash
  python3 backend/run_stage3_experiments.py
  ```
- **Stage 1 Baseline Demo**:
  ```bash
  python3 backend/run_stage1_demo.py
  ```
- **Stage 2 Accessibility Coverage Audit**:
  ```bash
  python3 backend/run_stage2_analysis.py
  ```

---

## 9. Development Policies (Not Medical Claims)

AccessRoute AI provides three pre-configured routing policies:
1. **Conservative Accessibility**: Maximizes safety and confidence. Strongly avoids rough or unpaved terrain, penalizes raised kerbs and missing crossing kerbs, and rejects unverified paths when alternatives exist.
2. **Balanced Accessibility**: Balances physical accessibility and travel distance. Strictly enforces hard barriers (no stairs, no `wheelchair=no`), but accepts minor surface variations and moderate data uncertainty to prevent excessive detours.
3. **Distance-First**: Optimizes travel distance while honoring hard legal and physical exclusions.

*Disclaimer: These policies represent configurable computational development parameters for testing and comparison, not clinical or universal prescriptions for specific wheelchair users.*
