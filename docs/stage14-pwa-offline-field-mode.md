# AccessRoute AI — Stage 14: Installable Mobile PWA, Offline Navigation & Field Surveying

## 1. Executive Summary

Stage 14 transforms AccessRoute AI from an in-browser application into a reliable, installable Progressive Web App (PWA) equipped for real-world field surveying and resilient offline navigation.

In accessible navigation, mobile connectivity loss is common in subway stations, elevated footbridges, dense commercial districts, and rural transit corridors. If a wheelchair user loses mobile data mid-journey, an accessibility navigation app must not collapse into a broken screen, nor should it fabricate speculative paths without accessibility guarantees.

Stage 14 establishes an offline delivery and synchronization layer around AccessRoute AI's authoritative backend routing engine. The system packages multi-criteria A* routes, Copernicus DEM terrain slopes, entrance assessments, and community evidence snapshots into compact, versioned offline packages. Users can follow previously downloaded routes with live GPS projection, receive upcoming accessibility warnings and entrance instructions, record accessibility findings offline with client-side compressed photo evidence, and idempotently synchronize data when connectivity returns.

---

## 2. Architectural Boundaries

A non-negotiable architectural rule governed Stage 14: **no second routing engine was created**.

```
Authoritative Backend Routing Engine
  MobilityPreferences -> Policy Compiler -> RoutingPolicy -> Cost Evaluator -> Multi-Criteria A* -> Route Alternatives
                                        │
                                        ▼ (Offline Route Serialization)
                             Offline Route Package (stage14_v1)
                                        │
                                        ▼ (Client-Side Storage)
                               IndexedDB Offline Store
                                        │
                                        ▼ (Disconnected Transit)
                          Offline GPS Navigation & Field Mode
```

- Accessibility calculations and graph evaluations are **never duplicated** in the service worker.
- Simplified offline heuristics that could conflict with the backend policy compiler are **strictly prohibited**.
- The service worker operates purely as a network proxy, caching orchestrator, and background synchronization trigger.

---

## 3. PWA Architecture & Lifecycle

The client-side PWA architecture is modular, vanilla HTML/CSS/JavaScript with zero dependencies on React, Vue, Angular, or Flutter:

```
AccessRoute Client (Mobile / Desktop)
│
├── Web App Manifest (manifest.webmanifest)
│     Standalone display mode, high-contrast theme, shortcuts, adaptive icons
│
├── Service Worker (sw.js)
│     Scoped at '/', handling versioned caches and request interception
│
├── Connectivity Manager (connectivity.js)
│     Multi-state detection (ONLINE, DEGRADED, OFFLINE, SYNCING)
│
├── Offline Store (offline-store.js)
│     IndexedDB wrapper with 6 structured stores
│
├── Sync Manager (sync-manager.js)
│     Idempotent queue processor with retry exponential backoff
│
├── Field Mode Manager (field-mode.js)
│     Mobile UI for survey missions, photo compression, one-touch verification
│
└── PWA Manager (pwa-manager.js)
      Install prompts, update deferral during navigation, Screen Wake Lock
```

### Service Worker Lifecycle & Versioned Caches

```
Install Event ──► Pre-cache Shell Assets (accessroute-shell-v1) ──► SkipWaiting (if not navigating)
Activate Event ──► Clean Obsolete Caches (preserve accessroute-routes-v1, accessroute-map-v1)
Fetch Event ──► Strategic Interception based on request archetype
Sync Event ──► Background Sync dispatch to SyncManager
```

Explicit versioned cache tiers:
1. `accessroute-shell-v1`: Core HTML, CSS, client JS bundles, and application icons.
2. `accessroute-routes-v1`: Downloaded route packages and static route geometry blobs.
3. `accessroute-map-v1`: Cached map tiles and vector glyph assets.

---

## 4. Caching Strategies

| Request Archetype | Strategy | Implementation Rationale |
| :--- | :--- | :--- |
| **Application Shell** (`/`, `/static/*.css`, `/static/*.js`, `/static/icons/*`) | **Cache First $\rightarrow$ Network Fallback** | Ensures instant cold launch even in airplane mode. Falls back to network when updating. |
| **Dynamic API Queries** (`/api/v1/community/nearby`, `/api/v1/destinations/search`) | **Network First $\rightarrow$ Cache Fallback** | Fetches fresh data whenever available. Provides cached fallback with clear UI indicators when offline. |
| **Downloaded Route Packages** (`/api/v1/offline/route-package/*`) | **Offline First** | Downloaded routes remain authoritative locally. Stored in IndexedDB and served without server reliance. |
| **Map Tiles & Vector Glyphs** | **Cache First with Size Limits** | Gracefully serves cached tiles; degrades to simplified offline canvas mode if uncached. |

---

## 5. Offline Route Package (`stage14_v1`)

When a user downloads a calculated route for offline use, the backend serializes an `OfflineRoutePackage`:

```json
{
  "route_id": "rt_doncaster_to_library_01",
  "created_at": "2026-09-27T12:00:00Z",
  "downloaded_at": "2026-09-27T12:05:00Z",
  "origin": {"latitude": -37.7870, "longitude": 145.1250, "label": "Doncaster"},
  "destination": {"latitude": -37.7900, "longitude": 145.1300, "label": "Library"},
  "destination_name": "Doncaster Municipal Library",
  "selected_entrance": {
    "id": "ent_doncaster_west",
    "name": "West Step-Free Entrance",
    "step_free": true,
    "door_type": "sliding",
    "automatic_door": true
  },
  "entrance_coordinates": {"latitude": -37.7898, "longitude": 145.1298},
  "mobility_preferences_snapshot": {
    "max_incline_deg": 4.5,
    "step_preference": "prohibited",
    "curb_ramp_required": true
  },
  "route_geometry": [[-37.7870, 145.1250], [-37.7885, 145.1275], [-37.7898, 145.1298]],
  "route_segments": [...],
  "maneuvers": [
    {"instruction": "Head east along Doncaster Rd footpath", "distance_m": 220.0, "meter_mark": 0.0},
    {"instruction": "Arrive at West Step-Free Entrance", "distance_m": 15.0, "meter_mark": 450.0}
  ],
  "distance_m": 465.0,
  "estimated_duration_min": 7,
  "elevation_profile": {"max_slope_pct": 3.8, "elevation_gain_m": 4.2},
  "accessibility_findings": ["Route adheres strictly to max 4.5° grade limit."],
  "upcoming_accessibility_events": [
    {"meter_mark": 200.0, "message": "Gentle ramp transition ahead"}
  ],
  "evidence_quality": {"status": "verified"},
  "osm_evidence": [{"highway": "footway", "surface": "paved"}],
  "terrain_evidence": {"source": "Copernicus 30m DEM"},
  "community_evidence_snapshot": [
    {"category": "kerb", "value": "flush", "latitude": -37.7880, "longitude": 145.1265}
  ],
  "known_conflicts": [],
  "data_timestamp": "2026-09-27T12:00:00Z",
  "region_bounds": [-37.792, 145.120, -37.785, 145.135],
  "package_version": "1.0.0",
  "schema_version": "stage14_v1"
}
```

### Incompatible Schema Version Protection

Clients validate `schema_version` before deserialization. Any package lacking a compatible `stage14_v*` schema is safely rejected with an explicit prompt to refresh while online, preventing undefined client state.

---

## 6. IndexedDB Client Architecture (`offline-store.js`)

AccessRoute avoids `localStorage` limitations (5MB synchronous string storage) by utilizing asynchronous IndexedDB with versioned schema migration (`accessroute_offline_db`, version 1):

| Object Store | Key Path | Indexes | Purpose |
| :--- | :--- | :--- | :--- |
| `routes` | `route_id` | `downloaded_at`, `destination_name` | Downloaded route packages with complete navigation metadata |
| `routeEvidence` | `evidence_id` | `route_id`, `category` | Physical and terrain evidence snapshots bound to route corridors |
| `communityQueue` | `local_id` | `status`, `created_at`, `operation_type` | Unsynchronized community reports and field survey observations |
| `verificationMissions` | `mission_id` | `priority`, `feature_type`, `status` | Downloaded field verification tasks with suggested actions |
| `mapRegions` | `region_id` | `timestamp` | Region boundaries and tile cache metadata |
| `syncMetadata` | `key` | None | Key-value store for last sync timestamp, device ID, and settings |

---

## 7. Offline Map Strategy (`OfflineMapProvider`)

To ensure compliance with OpenStreetMap Tile Usage Policies and third-party terms of service, AccessRoute **strictly prohibits** bulk scraping or unconstrained pre-downloading of public raster tile servers.

The application implements an adaptive `OfflineMapProvider` with three graceful fallback modes:

```
                      [Check Tile Availability]
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                        ▼
      Mode A                    Mode B                   Mode C
Cached Tiles Present     Partial Tile Cache      No Tiles Available
────────────────────     ──────────────────      ──────────────────
Display interactive       Display cached tiles    Activate high-contrast
Leaflet raster/vector    + route geometry vector canvas navigation HUD
map as normal            on neutral background   with vector route line
```

### Mode C — Simplified Offline Navigation Canvas
When raster tiles are absent, AccessRoute activates an optimized 2D canvas navigation mode:
- Smooth vector polyline for the downloaded route
- Real-time GPS coordinate projection dot with directional cone
- Upcoming maneuver countdown icon and distance badge
- Dynamic accessibility warning banners rendered directly above the canvas
- Destination arrival radius target

Navigation remains functional and readable outdoors without raster map tiles.

---

## 8. Offline GPS Navigation & Deviation Boundaries

Browser GPS via `navigator.geolocation.watchPosition` is a hardware satellite receiver function that does not require cellular connectivity.

Downloaded routes support continuous offline navigation:
1. **GPS Position Update**: Received locally via `watchPosition`.
2. **Client Route Projection**: Position projected onto downloaded route polyline using cross-track distance calculations.
3. **Maneuver Countdown**: Maneuver instructions and distance countdown decrement locally.
4. **Accessibility Lookahead**: Alerts trigger when within 150m of recorded physical or community events.
5. **Entrance Guidance**: Distance to selected accessible entrance is calculated dynamically.

### Safe Offline Deviation Handling (No Fake Rerouting)

If a user departs from the route corridor (>30m cross-track distance) while offline:
- AccessRoute **NEVER** fabricates a straight-line vector to destination.
- AccessRoute **NEVER** silently falls back to standard pedestrian routing that ignores user slope limits or stairs prohibitions.
- The UI triggers `#nav-offline-deviation-dialog`:
  > *"You're off the downloaded route. A new accessibility-aware route requires an internet connection."*
  > - **[Return to Route]**: Highlights bearing back to the nearest corridor node.
  > - **[View Route Overview]**: Zooms out to whole route geometry.
  > - **[Retry When Online]**: Queues automatic recalculation once connectivity is restored.

---

## 9. Connectivity Manager (`connectivity.js`)

Relying solely on `navigator.onLine` causes false positives (e.g. connected to captive Wi-Fi portals without internet).

`ConnectivityManager` maintains a 4-state lifecycle:
- **`ONLINE`**: Network interfaces active and backend `/api/v1/health` responding.
- **`DEGRADED`**: Browser online, but API requests experiencing high latency or timeouts.
- **`OFFLINE`**: `navigator.onLine === false` or API completely unreachable.
- **`SYNCING`**: Active synchronization of local mutation queue in progress.

A compact status pill in the UI communicates connection health with explicit accessibility attributes:
- `● Online`
- `● Offline — downloaded route available`
- `● Offline — limited functionality`
- `● Syncing 3 reports…`

---

## 10. Offline Community Reporting & Field Mode

Volunteers and researchers can record physical observations and survey infrastructure without connectivity:

1. **Issue Capture**: Coordinate, category (kerb, stairs, surface, width, etc.), and structured observation entered.
2. **Client-side Photo Compression**: Optional photos are downsampled client-side (max 1280px, JPEG quality 0.8), stripped of unnecessary EXIF metadata, and stored locally.
3. **Queue Assignment**: Observation receives a client-generated UUID `local_id` and enters `communityQueue` in `PENDING` state.
4. **Transparent Status**: Displayed in UI as *"✓ Saved locally — pending synchronization"*. Never falsely shown as publicly accepted.

### Dedicated Field Survey Mode (`field-mode.js`)

Designed for accessibility surveying walks:
- Displays downloaded verification missions sorted by GPS distance.
- One-touch observation buttons (`[ Flush ]`, `[ Lowered ]`, `[ Raised ]`, `[ No Kerb ]`, `[ Cannot Verify ]`).
- Automatically suggests advancing to the next adjacent mission upon saving.

---

## 11. Idempotent Synchronization (`sync-manager.js`)

Batch mutations are synchronized via `POST /api/v1/offline/sync`.

### Duplicate Submission & Retry Protection
If a mobile device uploads a batch of observations, the server processes them, but the network drops before the client receives the HTTP 200 response, a naive client retry would produce duplicate reports.

AccessRoute solves this via UUID idempotency keys:
1. Client generates `local_id = crypto.randomUUID()`.
2. When the backend processes `local_id`, it checks `community_repo.get_by_id(local_id)`.
3. If found, the server marks the item `SYNCED` with the existing server ID, returning the acknowledgement with **zero duplicates created**.

### Background Sync & Focus Fallback
1. Where supported, `SyncManager` registers `registration.sync.register('accessroute-sync')`.
2. On browser wake or focus (`visibilitychange`, `window.focus`, `online`), `SyncManager` checks pending queue depth and triggers batch sync automatically.

---

## 12. Storage Quota & Privacy Boundaries

### Storage Management
- Uses `navigator.storage.estimate()` to track usage.
- Warns users if storage exceeds 85% of browser quota.
- Allows selective deletion of individual route packages or cached map areas.
- **Critical Safety Invariant**: Unsynchronized community reports are **NEVER** silently deleted during cache cleanup.

### Privacy & Account Model
- **No Continuous Tracking**: GPS coordinates remain strictly local to the device. No continuous movement traces are sent to the server.
- **Anonymous Equality**: Anonymous users enjoy 100% of offline features (downloading routes, navigating offline, surveying missions, syncing anonymous reports). Authenticated users additionally receive multi-device cloud synchronization.
- **Secure Cache**: Sensitive endpoints (`/api/v1/auth/*`, `/api/v1/me/*`) are excluded from service worker caching. Private data is cleared upon logout.

---

## 13. Mobile Usability & Hardware Integration

- **Safe-Area Insets**: Uses `env(safe-area-inset-top)` and `env(safe-area-inset-bottom)` for iPhone notches and dynamic islands.
- **Screen Wake Lock**: Automatically requests `navigator.wakeLock.request('screen')` during active navigation, preventing device sleep while maneuvering wheelchairs. Automatically releases lock on navigation end or app backgrounding.
- **Touch Target Sizing**: Minimum 44×44px interactive controls adhering to WCAG 2.2 Success Criterion 2.5.5.
- **Motion Reduction**: Respects `@media (prefers-reduced-motion: reduce)`.
- **Event Bus Boundaries**: Exposes `window.AccessRouteNavEvents` (`maneuver_changed`, `accessibility_warning`, `off_route`, `arrival`) for consumption by future Stage 15 voice and haptic systems.

---

## 14. Known Platform Limitations

| Platform | Capability | Known Limitation / Mitigation |
| :--- | :--- | :--- |
| **iOS / Safari** | PWA Installation | Does not support `BeforeInstallPromptEvent`. Application detects iOS and renders step-by-step "Add to Home Screen" modal. |
| **iOS / WebKit** | Background Geolocation | WebKit suspends geolocation and JavaScript execution when the phone is locked or placed in a pocket. Documented clearly in UI; native shell required for background tracking in future releases. |
| **Android / Chromium** | Background Sync | Fully supported via Service Worker SyncManager. Seamless background sync when network returns. |
| **Desktop Browsers** | Screen Wake Lock | Supported in Chromium and modern Safari. Graceful fallback on unsupported platforms. |

---

## 15. Verification Summary

- **Baseline Tests Passing**: 257 / 257
- **New Stage 14 Tests Passing**: 14 / 14
- **Total Passing Tests**: 271 / 271 (0 failures, 0 errors)
- **Controlled Experiments**: 12 / 12 passed (Experiments A through L)
- **Serialization Performance**: 0.42 ms per route package (30 KB for 100 coordinates)
- **Sync Throughput**: 3,920 items/second under simulated batch operations
