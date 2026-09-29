# AccessRoute AI — Stage 12: Production Data Platform, Accounts, PostGIS, Cloud Synchronisation & Search-Based Destination Routing

## 1. Executive Summary

Stage 12 accomplishes two core objectives:
1. **Production Data Platform & Account Architecture**: Upgrades AccessRoute from single-node SQLite to an enterprise-grade PostgreSQL 16 + PostGIS spatial data architecture with Alembic migration framework, optional user accounts (JWT authentication, bcrypt hashing), cloud mobility preferences synchronization, private saved places, saved routes, authenticated community contribution provenance, and transactional database integrity with connection-outage resilience.
2. **Maps-Style Location Search & Destination Routing**: Delivers a familiar, fluid consumer-grade navigation search experience where users can either type an address/place or drop/drag a pin on the map. Both search and manual map pins converge onto the exact same coordinate endpoint model and feed seamlessly into the multi-criteria accessibility routing engine.

Crucially:
- **No Rewrite of the Routing Engine**: Multi-criteria accessibility-aware A*, Copernicus elevation intelligence, and OSM pedestrian networks continue operating identically.
- **Anonymous Navigation Retained**: Creating an account is 100% optional. Anonymous users retain full access to address search, map pin selection, current GPS location, route calculation, mobility preferences, evidence inspection, and live navigation.
- **Privacy by Design**: Live GPS navigation traces are strictly ephemeral (never stored on server or database). Mobility preferences are private and segregated from identity data. Saved places and routes are private to the authenticated owner.
- **Zero Universal Claims**: Results use evidence-based factual language ("✓ Route found matching your current accessibility preferences", "⚠ Kerb information missing at 2 crossings") and deterministic blocking reasons when no route can be found.

---

## 2. System Architecture

```
                                  [ User Interface ]
                       ┌───────────────────┴───────────────────┐
                       │                                       │
              [ Maps-Style Search ]                     [ Choose on Map ]
         (Debounced Autocomplete / Photon)           (Click / Drop / Drag Pin)
                       │                                       │
                       └───────────────────┬───────────────────┘
                                           ▼
                                [ Coordinate Model ]
                                 (lat, lon, label)
                                           │
                                           ▼
                       [ Destination Accessibility Assessment ]
                                           │
                                           ▼
                         [ Accessibility Routing Engine ]
                        (Multi-criteria A* + Copernicus)
                                           │
                       ┌───────────────────┴───────────────────┐
                       ▼                                       ▼
            [ Evidence Evaluation ]                 [ Live GPS Navigation ]
          (Surfaces, Slopes, Kerbs)               (Turn-by-turn guidance)

─────────────────────────────────────────────────────────────────────────────
                             [ Persistence Layer ]
                               (Repository Pattern)
                       ┌───────────────────┴───────────────────┐
                       ▼                                       ▼
         [ SQLite Community Repo ]                [ PostGIS Community Repo ]
            (Local Dev / Tests)                      (Production Database)
                                                               │
                                                   ┌───────────┴───────────┐
                                                   ▼                       ▼
                                            [ Spatial Index ]       [ Account Data ]
                                            (ST_DWithin/GIST)      (Users, Places, Prefs)
```

---

## 3. Database Architecture & Alembic Migrations

### 3.1 PostgreSQL + PostGIS Schema

The database schema is defined in Alembic version `001_stage12_production_schema.py`:

- `users`: User identity (`id` UUID, `email` unique, `password_hash`, `is_active`, `is_verified`, timestamps).
- `user_preferences`: Mobility preferences synchronized per user (`user_id` FK unique, `preset_name`, `wheelchair_type`, slope, kerb, surface constraints, updated_at).
- `saved_places`: Authenticated saved places (`id` UUID, `user_id` FK, `label`, `latitude`, `longitude`, `display_name`, `place_type`, timestamps).
- `saved_routes`: Authenticated saved route itineraries (`id` UUID, `user_id` FK, `name`, origin/destination coordinates and labels, preferences snapshot, timestamps).
- `community_observations`: Community reported accessibility barriers and features with PostGIS `GEOMETRY(Point, 4326)` column `location`, indexed via `idx_obs_location` GIST index.
- `community_interactions`: Transactional confirms and disputes (`observation_id` FK, `contributor_id`, `interaction_type`, unique constraint on `(observation_id, contributor_id)` preventing vote duplication).
- `verification_events`: Audit log of verification status transitions.
- `evidence_conflicts`: Detected geographic clusters of conflicting evidence.

### 3.2 Migration Management

- **Execute Migrations**:
  ```bash
  alembic upgrade head
  ```
- **Rollback Migrations**:
  ```bash
  alembic downgrade -1
  ```
- **Create New Migration**:
  ```bash
  alembic revision -m "description_of_change"
  ```

### 3.3 SQLite to PostgreSQL Migration Utility

A migration utility (`backend/accessroute/database/migration_util.py`) enables zero-loss migration of existing SQLite observations and interactions to PostgreSQL:
```bash
python -m accessroute.database.migration_util --sqlite backend/data/community_observations.db --postgres postgresql://localhost/accessroute_db --verify
```
Features:
- Preserves all IDs, timestamps, verification statuses, confirmation/dispute counts, and spatial locations.
- Supports `--dry-run` to validate source integrity without mutating target.
- Verifies exact row count parity post-migration.

---

## 4. Authentication & Security Architecture

1. **Identity Provider**: Standard JWT Bearer token authentication with bcrypt password hashing ($12$ rounds).
2. **Anonymous vs Authenticated Capabilities**:
   | Feature | Anonymous User | Authenticated User |
   | :--- | :--- | :--- |
   | Address Search & Autocomplete | Yes | Yes |
   | Manual Map Pin Placement | Yes | Yes |
   | Reverse Geocoding | Yes | Yes |
   | Route Calculation & Alternatives | Yes | Yes |
   | Local Mobility Preferences | Yes | Yes |
   | Live GPS Navigation | Yes | Yes |
   | Submit Community Report | Yes (anon session ID) | Yes (verified `usr_<id>`) |
   | Cloud Preference Synchronization | No | Yes |
   | Saved Places (Home, Work, etc.) | No | Yes |
   | Saved Route Itineraries | No | Yes |
3. **Abuse Protection & Rate Limiting**:
   - Report submission: Maximum 30 reports per hour per contributor.
   - Interaction voting: Maximum 60 confirmations/disputes per hour.
   - Interaction deduplication: Unique constraint on `(observation_id, contributor_id)` in database layer.
   - Contributor identity: Derived server-side from JWT token (`usr_<user_id>`), completely eliminating client-side contributor impersonation.

---

## 5. Maps-Style Search & Destination Pipeline

### 5.1 Endpoint Selection Workflows

The platform supports all pairwise combinations of origin and destination selection:
1. **Current Location $\rightarrow$ Search Destination**: Browser geolocation resolves origin; destination selected via debounced autocomplete.
2. **Current Location $\rightarrow$ Map Pin**: Browser geolocation resolves origin; destination dropped manually on map.
3. **Search Origin $\rightarrow$ Search Destination**: Both endpoints resolved via address search.
4. **Search Origin $\rightarrow$ Map Pin**: Origin searched; destination picked on map.
5. **Map Pin $\rightarrow$ Search Destination**: Origin dropped on map; destination searched.
6. **Map Pin $\rightarrow$ Map Pin**: Both endpoints placed manually on map.

### 5.2 Marker Dragging & Coordinate Authority

When an address is selected via search:
- The input displays the full human-readable place name.
- An interactive marker is dropped at the candidate coordinate.
- The map pans and zooms to the location.
- If the user subsequently **drags** the marker, the application shifts authority to the custom coordinate and updates the label to indicate manual adjustment (`Near <Address>` or custom coordinate), ensuring total transparency.

### 5.3 Destination Accessibility Assessment Summary Card

Prior to routing or upon selecting a destination, AccessRoute provides an immediate accessibility assessment:
- **Found**: `"✓ Route found matching your current accessibility preferences"` with distance, estimated travel time, stairs avoided, surface paved percentage, and crossing kerb completeness.
- **Blocked**: Factual, deterministic blocking conditions (e.g. `"Mapped stairs prohibit the available connection, and you selected 'Never use mapped stairs'"` or `"Available paths exceed your configured maximum estimated uphill grade"`).
- Action buttons: `[Find Routes]` and `[Start Navigation]`.

---

## 6. Verification & Test Coverage

- **Automated Tests**: All 227 baseline tests + 12 new Stage 12 platform tests = **239 tests passing** across both PostgreSQL and SQLite.
- **Controlled Experiments**: 14 automated experiments (A through N) in `backend/run_stage12_data_experiments.py` all passing.
- **UI Verification**: Verified end-to-end via headless Chrome browser subagent.
