# AccessRoute AI — Stage 8: Personal Mobility Profiles & User-Controlled Accessibility Preferences

## 1. Overview & Vision

Stage 8 transforms AccessRoute AI from an engine that makes universal assumptions about accessibility into a **user-controlled, preference-driven navigation system**. 

### The Core Principle:
> **"The user tells AccessRoute what conditions they personally want to avoid, tolerate, or prefer."**

Wheelchairs and mobility aids have vastly different capabilities, dimensions, and user requirements. A manual wheelchair user navigating independently may require gentle gradients (e.g., ≤4%) and strict avoidance of unramped stairs. A powered wheelchair user with electric curb-climbing capabilities may tolerate higher uphill slopes (e.g., up to 12%) while requiring a minimum clear path width of 0.85m to navigate between obstacles. A parent pushing a twin stroller may tolerate unpaved park paths but need step-free dropped kerbs at road crossings.

AccessRoute AI does not prescribe what an individual can or should do. Instead, the user's explicitly chosen preferences are **authoritative**.

---

## 2. Architecture & Data Flow

User preferences compile deterministically into the existing multi-criteria routing architecture rather than creating a separate routing engine:

```
┌────────────────────────────────────────┐
│             User Input / UI            │
│  (Starting Presets, Dual Sliders, etc) │
└───────────────────┬────────────────────┘
                    │ JSON Payload / localStorage
                    ▼
┌────────────────────────────────────────┐
│         MobilityPreferences            │
│   (Validated Pydantic Domain Model)    │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│            Policy Compiler             │
│   (Maps semantic levels to penalties & │
│       hard mathematical exclusions)    │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│             RoutingPolicy              │
│  (prohibit_steps, max_slope, weights)  │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│        Multi-Criteria A* Engine        │
│  (Evaluates distance, terrain, access, │
│        and uncertainty costs)          │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│      Personalized Alternatives         │
│  - Candidate 1: "Your Preferred Route" │
│  - Candidate 2: Lower Estimated Slope  │
│  - Candidate 3: Shortest Available     │
└────────────────────────────────────────┘
```

---

## 3. MobilityPreferences Domain Model

The domain model is defined in `backend/accessroute/preferences/models.py`.

### Constraint Enums
- **`StepPreference`**:
  - `NEVER`: Unramped mapped stairs become an absolute mathematical prohibition ($cost = \infty$).
  - `AVOID_WHEN_POSSIBLE`: Stairs are permitted only as a last resort, carrying a heavy penalty ($+600\text{ m}$).
  - `ALLOW`: Stairs are treated as standard pedestrian links.
- **`AvoidanceLevel`**:
  - `ALLOW`: No penalty applied.
  - `PREFER_AVOID`: Soft virtual distance penalty applied.
  - `STRICTLY_AVOID`: Hard graph prohibition ($cost = \infty$).
- **`KerbPreference`**:
  - `PREFER_LOWERED`: Virtual penalty applied to unlowered transitions.
  - `AVOID_RAISED`: Explicit avoidance of recorded raised kerbs.
  - `ALLOW_ANY`: No transition preference.
- **`DataConfidenceLevel`**:
  - `FLEXIBLE`: Low uncertainty weight multiplier ($0.4\times$); minimizes detours when metadata is sparse.
  - `BALANCED`: Default recommended multiplier ($1.0\times$).
  - `CAUTIOUS`: High uncertainty multiplier ($1.8\times$); strongly prefers paths with verified OSM attributes.

### Key Validation Rules
1. **Finite Numerical Guards**: All numeric values must be finite floats (rejecting NaN, Infinity).
2. **Gradient Ordering Invariant**: `max_preferred_uphill_grade_pct <= max_permitted_uphill_grade_pct`.
3. **Downhill Gradient Ordering Invariant**: `max_preferred_downhill_grade_pct <= max_permitted_downhill_grade_pct`.
4. **Dimension Constraints**: Path width clearance `minimum_path_width_m` must be $\ge 0.0\text{ m}$ and $\le 3.0\text{ m}$.

---

## 4. Starting Presets (Provisional Templates)

> [!IMPORTANT]
> **Scientific & Medical Boundary**:
> Starting presets are provisional product templates designed solely for convenience. They are **never** presented as clinical, medical, or universally safe recommendations. Every single underlying parameter can be customized by the user.

| Preset Key | Intended Device Template | Steps | Uphill (Pref / Max) | Downhill (Pref / Max) | Unpaved | Min Width | Data Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `manual_wheelchair` | Manual wheelchair | `never` | 4.0% / 8.0% | 6.0% / 10.0% | Prefer avoid | Unset | Balanced |
| `powered_wheelchair` | Powered wheelchair | `never` | 7.0% / 12.0% | 8.0% / 14.0% | Prefer avoid | 0.80 m | Balanced |
| `mobility_scooter` | Mobility scooter | `never` | 6.0% / 10.0% | 7.0% / 12.0% | Prefer avoid | 0.85 m | Balanced |
| `walker` | Walker / mobility aid | `avoid` | 5.0% / 9.0% | 6.0% / 10.0% | Prefer avoid | Unset | Flexible |
| `pram` | Stroller / Pram | `avoid` | 6.0% / 10.0% | 7.0% / 12.0% | Allow | 0.75 m | Flexible |
| `custom` | Full user control | User | User-defined | User-defined | User | User | User |

---

## 5. The Policy Compiler

The backend compiler (`backend/accessroute/preferences/compiler.py`) maps semantic user preferences into mathematical `RoutingPolicy` parameters. 

This architecture guarantees API security: **clients cannot inject raw multipliers or break A* admissibility heuristics**. The backend controls the cost algebra.

### Mapping Mechanics:
1. **Stairs**:
   - `NEVER` $\to$ `prohibit_steps_without_ramp = True`, `penalty_steps_without_ramp_m = 0.0`.
   - `AVOID_WHEN_POSSIBLE` $\to$ `prohibit_steps_without_ramp = False`, `penalty_steps_without_ramp_m = 600.0`.
   - `ALLOW` $\to$ `prohibit_steps_without_ramp = False`, `penalty_steps_without_ramp_m = 0.0`.
2. **Terrain Slopes**:
   - Compiles user `max_preferred_uphill_grade_pct` and `max_permitted_uphill_grade_pct`.
   - Edges with estimated slopes exceeding `max_permitted_uphill_grade_pct` receive infinite cost when evaluated.
   - Slopes exceeding preferred thresholds receive progressive penalties proportional to excess gradient.
3. **Surfaces**:
   - `STRICTLY_AVOID` unpaved $\to$ `prohibit_unpaved_surfaces = True`.
   - `PREFER_AVOID` unpaved $\to$ penalty of $250.0\text{ m}$.
4. **Path Width**:
   - `STRICTLY_AVOID` narrow $\to$ paths recorded with `width < min_width` receive infinite cost.
   - `STRICTLY_AVOID` unknown width $\to$ paths with unrecorded width receive infinite cost.
5. **Data Confidence**:
   - Scales the global uncertainty weight multiplier $\lambda_{\text{unc}} \in [0.4, 1.8]$.

---

## 6. Preference Conflict Diagnosis (No Silent Relaxation)

Previous systems often "silently fell back" to unsafe routes when constraints could not be satisfied. **AccessRoute AI strictly rejects silent constraint relaxation.**

If a user's strict constraints (e.g. `steps=never`, `max_permitted_uphill_grade_pct=4.0%`) make it impossible to connect the origin and destination:
1. The search terminates with `found: false`.
2. A secondary unconstrained diagnostic probe inspects the shortest physical connection.
3. Deterministic **`blocking_reasons`** are extracted and returned to the user:
   - *"The shortest physical connection uses mapped stairs without ramps, which your personal settings strictly prohibit."*
   - *"The available path has an estimated uphill slope of 8.4%, exceeding your strict limit of 4.0%."*
   - *"Available road crossings lack recorded kerb information, and you chose to strictly avoid unknown kerbs."*
4. The frontend displays the **Conflict Notification Card** (`#conflict-card`) with an actionable button to adjust preferences.

---

## 7. Preference-Aware Explainability

The explainability engine (`backend/accessroute/routing/explainability.py`) incorporates user preferences directly into natural language route justifications:

- **Stairs**: *"You selected 'Never use mapped stairs'. This route avoids the mapped staircase used by the shorter route."*
- **Surfaces**: *"You selected 'Prefer paved surfaces'. This route uses recorded paved surfaces for 94% of its distance."*
- **Terrain**: *"You selected a preferred estimated uphill limit of 4.0%. This route reduces the maximum estimated uphill gradient compared with the shorter alternative."*
- **Crossings**: *"Kerb information is unavailable at 2 crossings, so this route cannot be confirmed to satisfy your kerb preference at those locations."*

---

## 8. Client UI/UX & Accessibility

- **Modal Dialog (`<dialog id="preferences-modal">`)**: Full WCAG 2.2 AA keyboard operability, ARIA attributes (`aria-labelledby`, `aria-modal="true"`), and focus trapping.
- **Dual Controls**: Range sliders are paired with accessible `<input type="number">` controls to ensure users who cannot perform drag interactions can type numeric values directly.
- **Summary Chips (`#pref-chips-list`)**: Active preferences are summarized in 5 scannable chips above the route search button.
- **Local Persistence**: Preferences are serialized to browser `localStorage` under `accessroute_mobility_preferences` so settings persist across sessions without requiring accounts or backend databases.

---

## 9. Scientific & Technical Boundaries

1. **Unknown $\neq$ Accessible / Inaccessible**: Missing OSM metadata is never assumed to be accessible or inaccessible.
2. **Paved $\neq$ Wheelchair Accessible**: A paved asphalt path may still feature steep slopes, tree roots, or unramped kerbs.
3. **DEM Slope Caveats**: Terrain grades are derived from Copernicus GLO-30 DEM elevation data (30m grid) and may not capture localized sidewalk ramps, driveway dips, or single-step thresholds.
4. **No Route Found $\neq$ No Physical Path**: "No route found" indicates that no path satisfying all hard constraints exists within the acquired OpenStreetMap network.
