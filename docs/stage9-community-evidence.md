# AccessRoute AI — Stage 9: Community Accessibility Data, Verification & Evidence Provenance

## 1. Overview & Architectural Vision

Stage 9 introduces a structured, privacy-preserving **Community Accessibility Data & Verification Layer** to AccessRoute AI. 

OpenStreetMap (OSM) pedestrian networks provide a rich global foundation, but real-world accessibility infrastructure is constantly evolving:
* Kerb ramps are often unmapped or recorded as unknown.
* Construction works temporarily sever critical footpaths.
* Lifts at transit interchanges experience unscheduled outages.
* Physical barriers or steep ramps may have been installed or modified.

### The Fundamental Stage 9 Principle:
> **AccessRoute AI must maintain explicit, unblurred provenance. The system must never silently overwrite OpenStreetMap data with community submissions, nor treat community observations as infallible ground truth without verification.**

The architecture maintains an unambiguous separation between:
1. **OpenStreetMap Evidence**: Authoritative pedestrian infrastructure geometry and mapped tags.
2. **Community Observations**: Peer-reported conditions with timestamps, consensus metrics, and validity windows.
3. **Terrain Models**: Copernicus GLO-30 DEM directional slope estimates.
4. **Derived Insights / Conflicts**: Explicit flags when evidence sources contradict each other.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EVIDENCE PROVENANCE LAYER                       │
├─────────────────────────┬──────────────────────┬───────────────────────┤
│    OpenStreetMap (OSM)  │ Community Observation│  Copernicus DEM (30m) │
│  - surface=asphalt      │ - kerb=raised        │  - slope=+4.2% uphill │
│  - highway=crossing     │ - 3 confirmations    │  - elevation gain=12m │
│  - kerb=lowered         │ - status: SUPPORTED  │                       │
├─────────────────────────┴──────────────────────┴───────────────────────┤
│                          CONFLICT DETECTOR                             │
│       OSM says kerb=lowered vs Community reports kerb=raised           │
│       -> Disagreement surfaced transparently without silent overwrite  │
├────────────────────────────────────────────────────────────────────────┤
│                       MULTI-CRITERIA A* ROUTER                         │
│       Evaluates physical distance, user mobility preferences,          │
│       OSM infrastructure, active community claims, and DEM slopes      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Evidence Architecture & Domain Models

The domain models are encapsulated in the dedicated package `backend/accessroute/community/`:

### 2.1 Evidence Sources (`AccessibilityEvidenceSource`)
- `OPENSTREETMAP`: Official OSM tags extracted from way and node geometries.
- `COMMUNITY_OBSERVATION`: Crowd-sourced peer observations submitted by users.
- `TERRAIN_ESTIMATE`: Satellite DEM elevation and directional slope calculations.
- `SYSTEM_DERIVED`: Synthesized cross-segment findings or spatial interpolations.
- `FUTURE_AUTHORITY_DATA`: Reserved for municipal council feeds and transit authority APIs.

### 2.2 Observation Categories & Structured Values
To prevent ambiguities and maintain structured query capability, reports use normalized categorical values:

| Category | Typical Structured Values | Description |
| :--- | :--- | :--- |
| **`KERB`** | `lowered`, `flush`, `raised`, `no_kerb`, `unknown` | Kerb ramp profile at pedestrian crossings |
| **`STAIRS`** | `present`, `absent`, `without_ramp`, `with_ramp`, `steep_flight` | Flight of steps and ramp availability |
| **`RAMP`** | `present`, `absent`, `wheelchair_designated`, `too_steep` | Wheelchair access ramps |
| **`SURFACE`** | `asphalt`, `concrete`, `paved`, `paving_stones`, `compacted`, `gravel`, `dirt`, `grass`, `cobblestone` | Footway surface material |
| **`BARRIER`** | `gate`, `bollard`, `cycle_barrier`, `turnstile`, `construction_barrier` | Physical obstacles restricting passage |
| **`PATH_BLOCKED`** | `construction`, `fallen_tree`, `flooding`, `event_fencing`, `parked_vehicle`, `overgrowth` | Impassable obstructions |
| **`TEMPORARY_OBSTACLE`**| `construction`, `roadworks`, `debris`, `event_barrier`, `scaffolding` | Temporary impediments |
| **`CONSTRUCTION`** | `footpath_closed`, `crossing_closed`, `scaffolding_narrowed`, `roadworks` | Active civic or utility works |
| **`LIFT_STATUS`** | `operational`, `out_of_service`, `unknown` | Station/interchange elevators |
| **`ENTRANCE_ACCESSIBILITY`** | `level_entry`, `ramped`, `steps_only`, `inaccessible` | Building / facility ingress points |
| **`PATH_WIDTH`** | `adequate`, `narrow`, `impassable` | Clear width passage dimensions |
| **`SLOPE`** | `gentle`, `moderate`, `steep` | Locally perceived path inclination |

Optional free-text notes and photo reference URLs provide human context without compromising automated routing filters.

---

## 3. Persistent Observation Storage & Future Migration

To preserve graph cache boundaries, community evidence is **never stored inside cached GraphML files**. Graph caches remain purely geometric and topological reflections of OSM data.

### 3.1 Repository Abstraction
Defined in `backend/accessroute/community/repository.py`:
- `CommunityObservationRepository` (abstract protocol)
- `SQLiteCommunityObservationRepository` (MVP implementation)
- Future: `PostgresCommunityObservationRepository` (Stage 12 PostGIS migration target)

### 3.2 SQLite Storage Engine
- **Database Location**: `backend/accessroute/data/community_observations.db`
- **Concurrency Mode**: Write-Ahead Logging (`PRAGMA journal_mode=WAL;`) with busy timeouts for seamless concurrent read/write operations.
- **Tables**:
  - `community_observations`: Persistent record of all submitted reports, OSM link IDs, spatial coordinates, temporal expiration timestamps, and consensus counters.
  - `community_interactions`: Interaction log recording `(observation_id, contributor_id, interaction_type, created_at)` with `UNIQUE(observation_id, contributor_id)` to prevent duplicate voting or fraudulent confirmation inflation.
- **Safe Upserts**: Uses `INSERT ... ON CONFLICT(id) DO UPDATE SET ...` to guarantee that updating consensus counters does not trigger foreign key deletions on the interaction table.
- **Indices**: Dedicated B-Tree indices on `(latitude, longitude)`, `(category)`, `(verification_status)`, and `(osm_element_type, osm_element_id)`.

---

## 4. Spatial Matching & Distance Safeguards

Users submit reports by tapping on map coordinates without knowing internal OpenStreetMap IDs. The `CommunitySpatialMatcher` (`backend/accessroute/community/matcher.py`) resolves geographic points to the graph:

1. **Category Affinity**:
   - `KERB`, `LIFT_STATUS`, `BARRIER`: Prioritizes nearest network nodes (e.g. crossing vertices, bollard nodes) within 15 meters.
   - `SURFACE`, `PATH_BLOCKED`, `CONSTRUCTION`, `PATH_WIDTH`, `STAIRS`: Snaps to the nearest edge line segment within 30 meters.
2. **Configurable Thresholds**:
   - Strict 30-meter maximum snapping distance safeguard (`max_match_distance_m=30.0`).
   - If no pedestrian infrastructure is within 30 meters, the report is saved as **`UNMATCHED`** (`osm_element_id = None`). Unmatched reports remain fully visible in nearby queries and on map visualizations, but never arbitrarily corrupt unrelated path segments.
3. **Deterministic Match Confidence**:
   Calculated proportionally to proximity:
   $$\text{Confidence} = 1.0 - \left(\frac{\text{Distance}}{30.0}\right)^{1.5}$$

---

## 5. Deterministic Verification State Machine

AccessRoute AI strictly avoids opaque, arbitrary "AI confidence percentages". All verification transitions are governed by an observable, deterministic state machine (`backend/accessroute/community/verification.py`):

```
       [ Submission ]
             │
             ▼
        UNVERIFIED (1 report)
       /          \
      / 2+ confirms \ 2+ disputes
     ▼              ▼
COMMUNITY_SUPPORTED  COMMUNITY_DISPUTED
     │              │
     │ 4+ confirms  │ 3+ disputes (> 2x confirms)
     ▼              ▼
  VERIFIED       REJECTED
     │
     │ (If temporary and current_time > expires_at)
     ▼
  EXPIRED
```

- **`UNVERIFIED`**: Single submitter observation (default).
- **`COMMUNITY_SUPPORTED`**: $\ge 2$ independent confirmations with 0 disputes, or $\ge 3$ confirmations with $\le 1$ dispute.
- **`VERIFIED`**: $\ge 4$ independent peer confirmations with $\le 1$ dispute.
- **`COMMUNITY_DISPUTED`**: $\ge 2$ disputes and disputes $\ge$ confirmations.
- **`REJECTED`**: $\ge 3$ disputes and disputes $> 2 \times$ confirmations.
- **`EXPIRED`**: Temporary observation whose validity window has elapsed.

---

## 6. Temporary Accessibility Conditions & Expiration

Temporary infrastructure impairments (construction, roadworks, lift repairs, floodings, event fencing) must not permanently brand an area inaccessible.

- **Temporal Attributes**: `is_temporary: bool`, `reported_at: datetime`, `expected_end_at: Optional[datetime]`, `expires_at: Optional[datetime]`.
- **Automatic Default Windows**:
  - Construction / Roadworks: Default 7 days (168 hours) unless custom duration specified.
  - Obstacles / Flooding: Configurable between 1 and 72 hours.
- **Routing Engine Enforcement**:
  Every edge evaluation checks `obs.is_active(current_time)`. When `now > expires_at`, the report is classified as `EXPIRED`. Expired reports are retained in the historical database for analysis, but are **immediately ignored** during graph cost evaluation.

---

## 7. Evidence Conflict Detection

Defined in `backend/accessroute/community/conflicts.py`:
When an active community report disagrees with normalized OpenStreetMap evidence on the same segment or crossing, the system constructs a typed `EvidenceConflict` object:

```json
{
  "attribute": "kerb",
  "osm_claim": "OpenStreetMap records kerb=lowered",
  "community_claim": "Community reports kerb=raised",
  "summary": "OSM records a lowered kerb, but community report indicates a raised kerb.",
  "community_observation_id": "745b8472-8ec4-4041-a2eb-48c92ebe62da",
  "status": "community_supported"
}
```

Disagreements are evaluated for:
1. **Kerb Transitions**: OSM lowered/flush vs Community raised/no_kerb.
2. **Surfaces**: OSM paved vs Community gravel/dirt/cobblestone.
3. **Stairs**: OSM step-free path vs Community stairs present.
4. **Width**: OSM wide way vs Community impassable narrow barrier.

The system never arbitrarily silences or overrides either source. Both are surfaced to the user.

---

## 8. Multi-Criteria Routing Integration

Community evidence is evaluated in `backend/accessroute/routing/cost_evaluator.py`:

| Community Condition | Status | Routing Action |
| :--- | :--- | :--- |
| **`PATH_BLOCKED` / `CONSTRUCTION`** | `COMMUNITY_SUPPORTED` or `VERIFIED` | **Prohibits traversal** ($cost = \infty$). Router plans a safe detour. |
| **`PATH_BLOCKED` / `CONSTRUCTION`** | `UNVERIFIED` | Applies heavy uncertainty penalty ($+250\text{ m}$). Prefers detours if available, but avoids trapping user if no alternative exists. |
| **`STAIRS`** | `COMMUNITY_SUPPORTED` | Triggers strict mobility preference exclusion if user selected `Never use stairs`. |
| **`TEMPORARY_OBSTACLE`** | `UNVERIFIED` | Soft uncertainty penalty ($+90\text{ m}$). Surfaced as warning. |
| **`CONFLICT` Flagged** | Active | Soft contextual uncertainty penalty ($+35\text{ m}$). Emits conflict explanation. |
| **`EXPIRED` Report** | Any | **Zero penalty**. Traversal cost determined purely by baseline OSM and terrain data. |

---

## 9. REST API Reference

All community endpoints follow RESTful conventions under `/api/v1/community/`:

* **`POST /api/v1/community/reports`**: Submit an accessibility report. Snaps to graph within 30m if graph available; records submitter confirmation.
* **`GET /api/v1/community/reports`**: List observations with optional filters (`category`, `verification_status`, `include_expired`, `limit`).
* **`GET /api/v1/community/reports/{id}`**: Fetch detailed observation metadata.
* **`POST /api/v1/community/reports/{id}/confirm`**: Submit an independent confirmation. Enforces single-vote rule per contributor ID.
* **`POST /api/v1/community/reports/{id}/dispute`**: Submit an independent dispute.
* **`GET /api/v1/community/nearby`**: Haversine distance search within a given radius (`latitude`, `longitude`, `radius_m`).
* **`GET /api/v1/community/verification-opportunities`**: Discovers data gaps (crossings lacking kerbs, footways lacking surface) for community auditing.
* **`GET /api/v1/community/geojson`**: GeoJSON FeatureCollection of community reports formatted with custom marker styling.

---

## 10. Privacy & Contributor Protection

1. **No Account Required**: Anonymous submissions supported. Client generates random persistent UUIDs stored in browser `localStorage`.
2. **No Movement History**: Origin/destination routing queries are never linked to community observation IDs.
3. **No Public Contributor Exposure**: Contributor identifiers are strictly isolated in backend validation and stripped from public responses.
4. **Future-Proof**: Built with clean interfaces to support verified cryptographic sign-ins (Stage 12) without breaking changes.

---

## 11. User Experience & Reporting UI

1. **"Report Accessibility Issue" Button**: Prominently accessible in the map viewport controls.
2. **Interactive Tap-to-Report**: User clicks the map at the exact obstacle location. A pulsating report pin identifies coordinates.
3. **Accessible Modal Form**:
   - Semantic `<dialog id="community-report-modal">` with ARIA focus traps and `Escape` key support.
   - Dynamic structured value options tailored to the selected category.
   - Permanent vs Temporary toggle with duration selectors.
   - Live confirmation feedback.
4. **Interactive Leaflet Markers**:
   - Color-coded and icon-differentiated markers (Warning Amber for unverified, Danger Red for blocked, Success Teal for confirmed amenities).
   - Interactive popups allowing one-click peer confirmation or disputing directly from the map.
5. **Upgraded Segment Evidence Inspector**:
   The inspector features four explicitly separated evidence cards:
   - **OpenStreetMap Evidence** (surface, highway, kerb, wheelchair tags)
   - **Terrain Model** (Copernicus DEM grade percentage, slope direction)
   - **Community Evidence** (condition, age, consensus count, verification status badge)
   - **Evidence Disagreements** (highlighted warning card detailing OSM vs Community discrepancies)

---

## 12. Controlled Demonstration Scenarios

Verified in `backend/demo_stage9_scenarios.py`:

- **Scenario A (Temporary Construction Detour)**: Shortest 50m path blocked by community-supported construction report. Router diverts to a 70m detour and explains: *"Route avoids a footpath currently reported blocked by construction."*
- **Scenario B (Unverified Obstacle)**: Single unverified report does not falsely declare the path impassable; applies $+90\text{ m}$ uncertainty penalty and surfaces warning.
- **Scenario C (Evidence Conflict)**: OSM records `kerb=lowered`, community reports `kerb=raised`. Segment inspector flags explicit conflict without silent overwrite.
- **Scenario D (Expired Report)**: Temporary report past expiration window is immediately ignored by cost evaluator. Nominal path traversal cost restored.
- **Scenario E (Verification Opportunities)**: System deterministically locates crossings without kerb data and footpaths without surface tags to invite targeted community contributions.

---

## 13. Data Quality & Spatial Scaling Benchmark

Benchmarked using `backend/run_stage9_analysis.py` on an OSM pedestrian graph of 4,114 nodes and 11,924 edges:

| Scale (Total DB Reports) | Nearby Search (300m) | Graph BBox Enrichment | A* Routing Search Time | Routing Overhead |
| :--- | :--- | :--- | :--- | :--- |
| **0 reports** | 0.07 ms | 5.94 ms | 9.80 ms | 0.0% (baseline) |
| **100 reports** | 0.12 ms | 6.74 ms | 9.75 ms | -0.6% |
| **1,000 reports** | 0.20 ms | 8.24 ms | 9.65 ms | -1.5% |
| **10,000 reports** | 1.83 ms | 28.02 ms | 15.06 ms | +53.6% |

Even with 10,000 synthetic observations across the metropolitan area, localized spatial bounding queries and B-Tree indexing ensure graph enrichment completes in under 29 ms, with total A* routing latency remaining ~15 ms.

---

## 14. Scientific & Safety Boundaries

1. **Never Claim Absolute Safety**: The system never uses deceptive terms like *"Guaranteed Accessible"* or *"Wheelchair Safe"*.
2. **Defensible Terminology**: Uses precise descriptors: *"Community-supported observation"*, *"Mapped lowered kerb"*, *"Reported temporary obstruction"*, *"Sources disagree"*.
3. **No Arbitrary AI Guessing**: Missing infrastructure remains explicitly **UNKNOWN**. The system never invents accessibility metadata where none exists.
4. **Evidence Attribution**: Every piece of data in the UI and API explicitly displays its source (`OpenStreetMap`, `Community Reports`, `Copernicus DEM`).
