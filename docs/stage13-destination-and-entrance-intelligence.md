# AccessRoute AI — Stage 13 Architecture Document
## Accessible Destination, Entrance & Venue Intelligence

### 1. Overview & Objective
In real-world pedestrian navigation, reaching the geographic centroid of a venue (such as a shopping center, transit station, hospital, or university campus) does not guarantee reaching an entrance that a wheelchair user or person with reduced mobility can actually navigate. Often, central coordinates lead to loading bays, sheer walls, service alleys, or entrances obstructed by flights of stairs without ramp bypasses.

**Stage 13** extends AccessRoute AI's end-to-end routing pipeline by transforming destinations from single geographic points into intelligent places with multiple, distinct, accessibility-characterized entrance options.

```
Search Destination
        ↓
Identify Venue / Destination (DestinationResolver)
        ↓
Discover Known Entrances (OSMEntranceDiscovery)
        ↓
Collect Multi-Source Accessibility Evidence (EntranceEvidenceCollector)
        ↓
Compare Entrances Against User Preferences (EntranceAssessmentEngine)
        ↓
Present Entrance Options on Map & Summary Card
        ↓
Route to Selected Accessible Entrance (DynamicGraphManager + Snapper)
        ↓
Navigate to Entrance Area (LiveNavigationService)
```

The user maintains absolute authority: they can override suggested entrances, select another entrance, route directly to the centroid, or drop and drag map pins anywhere.

---

### 2. Destination Intelligence Domain Models
Located in `backend/accessroute/destinations/models.py`:

- **`VenueType`**: Standardized enumeration covering `SHOPPING_CENTRE`, `STATION`, `HOSPITAL`, `UNIVERSITY`, `PUBLIC_FACILITY`, `PARK`, `BUSINESS`, `ADDRESS`, and `ARBITRARY_COORDINATE`.
- **`EntranceType`**: Classifies entrances into `MAIN`, `SECONDARY`, `SERVICE`, `EMERGENCY`, `CAR_PARK`, and `ACCESSIBLE`.
- **`EvidenceProvenance`**: Authoritative data origin tags: `OPENSTREETMAP`, `COMMUNITY_OBSERVATION`, `VENUE_DATA`, `SYSTEM_DERIVED`, and `UNKNOWN`.
- **`EntranceAssessmentStatus`**: Deterministic, non-opaque classifications:
  - `MATCHES_CURRENT_PREFERENCES`: Verified step-free, compliant dimensions, and no active obstacles.
  - `PARTIALLY_VERIFIED`: Step-free verified, but secondary attributes (width, automation) unrecorded.
  - `INSUFFICIENT_EVIDENCE`: Critical accessibility attributes unrecorded.
  - `CONFLICTING_EVIDENCE`: Contradictory reports between baseline and community data.
  - `DOES_NOT_MATCH_CURRENT_PREFERENCES`: Hard physical barriers (stairs, narrow doors, steep slopes).
  - `TEMPORARILY_REPORTED_UNAVAILABLE`: Active temporary closure, maintenance, or blockage.
- **`EntranceAccessibilityEvidence`**: Factual physical metrics: `wheelchair`, `step_free`, `steps_count`, `ramp`, `automatic_door`, `door_type`, `door_width_m`, `threshold_height_cm`, `lift_access`, `opening_hours`, `notes`, `is_temporary`, `expires_at`.
- **`Entrance`**: Individual entrance point with ID, coordinates, physical evidence, completeness metrics, provenance sources, and snap distance.
- **`Venue`**: Complex destination containing an array of candidate entrances, spatial bounds, and category attributes.
- **`Destination`**: Top-level entity representing either a multi-entrance venue or a standard street address / coordinate.

---

### 3. Venue Resolution
`backend/accessroute/destinations/resolver.py`:
- `DestinationResolver.resolve_candidate(candidate: GeocodeCandidate) -> Destination`
- Deterministically identifies venue types from:
  1. OSM category tags (`mall`, `station`, `hospital`, `university`, `community_centre`, etc.).
  2. Structured place types from the geocoder (`shopping_centre`, `station`, `public_facility`, `hospital`).
  3. Curated keyword patterns (`westfield`, `plaza`, `station`, `hospital`, `campus`, `hall`).
  4. Street address pattern matching (`123 Collins Street` correctly classified as non-venue address).
- Preserves original search coordinates, bounding boxes, and raw geocoder attributes.

---

### 4. OpenStreetMap Entrance Discovery
`backend/accessroute/destinations/entrances.py`:
- Inspects OpenStreetMap pedestrian network nodes and ways within a controlled search radius (default 200m).
- Extracts physical tags:
  - `entrance=*`, `wheelchair=*`, `door=*`, `automatic_door=*`
  - `width=*` (parses meters, cm), `step_count=*`, `ramp=*`
  - `level=*`, `access=*`, `opening_hours=*`
- Fallback synthesis for representative public landmarks (e.g. Westfield Doncaster, Flinders Street Station) with persistent disk caching (`data/cache/destinations/`) to ensure fast, offline-resilient operation.

---

### 5. Multi-Source Evidence Provenance & Expiration
`backend/accessroute/destinations/evidence.py`:
- In accordance with Stages 9–10 architecture, community reports **never silently overwrite** OpenStreetMap baseline evidence.
- An entrance tracks independent provenance sources: `[OPENSTREETMAP, COMMUNITY_OBSERVATION]`.
- Active conflicts (e.g. OSM tags `wheelchair=yes` while 2 community reports state `temporary_closure`) are explicitly isolated and highlighted in warnings.
- Temporal awareness: Expired temporary observations (`expires_at < now`) automatically cease affecting routing eligibility without manual administrative intervention.

---

### 6. Deterministic Preference-Aware Assessment
`backend/accessroute/destinations/assessment.py`:
- Evaluates candidate entrances against Stage 8 `MobilityPreferences` without opaque probabilistic scores.
- Answers key physical questions:
  1. Are mapped stairs present without ramp bypass?
  2. Is door clear width recorded, and does it meet user minimum requirements?
  3. Are automatic doors available?
  4. Is lift access operational?
  5. Are there active community obstacle reports?
  6. Is the approach path connected and accessible?
- Deterministic ranking sorts candidate entrances by suitability, recommending the best matching entrance while exposing all alternatives.

---

### 7. Direct Route-to-Entrance Architecture
- Calculates pedestrian routes terminating directly at the entrance's mapped approach point rather than the venue centroid.
- Snaps entrance coordinates to the pedestrian graph and verifies snap distance ($< 25\text{m}$).
- Re-evaluates entire journey: Origin $\rightarrow$ Walkable Network $\rightarrow$ Entrance Approach $\rightarrow$ Entrance Doorway.

---

### 8. Arrival Behavior & Navigation Integration
`backend/accessroute/navigation/service.py`:
- Replaces generic arrival notifications with entrance-specific factual cues:
  - *"You've reached the selected entrance area: Main Entrance — Doncaster Road. Step-free access recorded, automatic sliding doors recorded."*
- Cautions users when GPS horizontal accuracy is insufficient to guarantee doorway alignment.

---

### 9. Saved Preferred Entrances
`backend/accessroute/database/models.py`:
- Extended `SavedPlace` with `preferred_entrance_id` and `preferred_entrance_name`.
- Authenticated users can store a specific preferred entrance (e.g. "Work — South Ramp Entrance").
- Reopening a saved place triggers dynamic reassessment against live community evidence rather than relying on stale cached data.

---

### 10. WCAG 2.2 AA Compliance & UI Design
`backend/accessroute/api/static/`:
- **Destination Summary Card**: Displays Entrance section with status badges, evidence completeness breakdown, and entrance options toggle.
- **Non-Color-Only Map Markers**: Distinct shapes and unicode indicators:
  - ♿ Matching Entrance (Green circular pill)
  - ? Partial / Insufficient Evidence (Amber diamond)
  - ⛔ Does Not Match Preferences (Red square pill)
  - ! Conflicting Evidence (Orange hexagon)
- Touch targets $\ge 44 \times 44\text{px}$, visible focus states, ARIA live region announcements, and keyboard navigability.
- Manual pin override: Dragging or clicking a custom point clears venue constraints and restores direct coordinate routing.
