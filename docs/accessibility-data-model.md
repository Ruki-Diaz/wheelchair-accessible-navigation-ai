# AccessRoute AI — Accessibility Data Model Specification (Stage 2)

---

## 1. Overview and Core Philosophy

AccessRoute AI decouples physical geographic network representation (Stage 1) from accessibility evidence extraction (Stage 2) and routing cost evaluation (Stage 3).

The purpose of Stage 2 is to construct a **factual, evidence-based accessibility layer** on top of the OpenStreetMap pedestrian network. It operates on four strict engineering principles:

1. **No Invented Values**: Missing data is represented explicitly as `UNKNOWN`. It is never defaulted to `False`, `0.0`, `accessible`, or `inaccessible`.
2. **Physical Surface $\ne$ Wheelchair Accessible**: A smooth asphalt or concrete path can contain stairs, high kerbs, steep slopes, restrictive barriers, or dangerous street crossings. Paved surfaces are recorded as physical facts, not as guarantees of accessibility.
3. **No Arbitrary Numerical Scores**: No unjustified scores (such as `confidence_score = 0.8` or `accessibility_score = 85`) are manufactured.
4. **Resilience to Real-World OSM Data**: The parser accommodates semicolon-separated strings, lists, stringified Python representations, conflicting capitalization, and unknown community tags without failing.

---

## 2. Architecture: Raw $\rightarrow$ Normalized $\rightarrow$ Findings

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. Raw OSM Evidence                         │
│  Examples: surface='asphalt', highway=['steps', 'footway'],     │
│            wheelchair='no', kerb='lowered', incline='5%'        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   2. Normalized Domain Models                   │
│  - WheelchairAccess (YES, DESIGNATED, LIMITED, NO, UNKNOWN)     │
│  - SurfaceType (ASPHALT, CONCRETE, PAVED, GRAVEL, UNKNOWN)     │
│  - KerbType (FLUSH, LOWERED, RAISED, ROLLED, UNKNOWN)           │
│  - InclineMeasurement (percentage=5.0, direction=None)          │
│  - WidthMeasurement (width_meters=1.8, is_parsed=True)          │
│  - Missing Fields Catalog (['smoothness', 'tactile_paving'])    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 3. Deterministic Findings                       │
│  - STEPS_PRESENT                                                │
│  - PAVED_SURFACE_RECORDED                                       │
│  - WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED                     │
│  - LOWERED_KERB_RECORDED                                        │
│  - PEDESTRIAN_CROSSING_RECORDED                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Normalized Domain Enums & Value Objects

### 3.1 Wheelchair Access (`WheelchairAccess`)
| Enum Value | Raw OSM Tag Triggers | Semantic Meaning |
| :--- | :--- | :--- |
| `YES` | `"yes"` | Wheelchair access is formally permitted/available |
| `DESIGNATED` | `"designated"` | Purpose-built/prioritized for wheelchair users |
| `LIMITED` | `"limited"` | Wheelchair access possible with limitations/assistance |
| `NO` | `"no"` | Wheelchair access explicitly forbidden or physically impossible |
| `UNKNOWN` | Missing, `null`, empty | No wheelchair data tagged in OpenStreetMap |
| `OTHER` | Unrecognized values | Unfamiliar tag preserved in `raw_tags` |

### 3.2 Surface Material (`SurfaceType`)
| Enum Value | Category | Common Materials |
| :--- | :--- | :--- |
| `ASPHALT` | Paved | Asphalt roads, bitumen shared paths |
| `CONCRETE` | Paved | Standard concrete sidewalk slabs |
| `CONCRETE_PLATES` | Paved | Large precast concrete panels |
| `PAVED` | Paved | Generic sealed or paved surface |
| `PAVING_STONES` | Paved | Interlocking pavers or brick walkways |
| `COMPACTED` | Semi-Paved | Compacted crusher dust or stabilized gravel |
| `FINE_GRAVEL` | Unpaved | Fine pea gravel |
| `GRAVEL` | Unpaved | Loose crushed rock/gravel paths |
| `DIRT` | Unpaved | Hard-packed natural dirt trails |
| `GROUND` | Unpaved | Raw unimproved earth |
| `GRASS` | Unpaved | Lawn, park turf |
| `COBBLESTONE` | Rough | Irregular stone blocks, setts |
| `UNKNOWN` | Missing | Unrecorded in OpenStreetMap |
| `OTHER` | Unclassified | Wood, rubber, metal grating, etc. |

### 3.3 Kerb Height Profile (`KerbType`)
| Enum Value | Description |
| :--- | :--- |
| `FLUSH` | Continuous transition with 0mm step |
| `LOWERED` | Ramped kerb cut (typically $\le 15\text{mm}$) |
| `ROLLED` | Gradual vehicular mountable kerb |
| `RAISED` | Standard unramped barrier kerb ($100 - 150\text{mm}$) |
| `NO` | No kerb exists along this boundary |
| `UNKNOWN` | Kerb profile not recorded |
| `OTHER` | Non-standard kerb construction |

### 3.4 Incline Measurement (`InclineMeasurement`)
- `raw`: Original unparsed string (e.g. `"5%"`, `"-8%"`, `"up"`, `"steep"`, `"1:12"`).
- `percentage`: Signed float representation (e.g. `5.0`, `-8.0`, `8.33`).
- `direction`: Directional semantic indicator (`"up"`, `"down"`).
- `is_parsed`: Boolean flag verifying successful parsing without guessing.

### 3.5 Passage Width (`WidthMeasurement`)
- `raw`: Original unparsed string (e.g. `"1.5"`, `"1.8 m"`, `"120 cm"`).
- `width_meters`: Normalized clearance width in meters (e.g. `1.5`, `1.8`, `1.2`).
- `is_parsed`: Boolean flag indicating confident dimensional extraction.

---

## 4. Deterministic Findings Catalog

Findings represent **irrefutable physical or regulatory observations** derived from the presence of confirmed tags. They avoid subjective scoring:

```python
class FindingType(str, Enum):
    WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED = "WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED"
    WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED    = "WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED"
    WHEELCHAIR_ACCESS_LIMITED               = "WHEELCHAIR_ACCESS_LIMITED"

    STEPS_PRESENT                           = "STEPS_PRESENT"
    RAMP_PRESENT                            = "RAMP_PRESENT"
    RAMP_WHEELCHAIR_DESIGNATED              = "RAMP_WHEELCHAIR_DESIGNATED"
    HANDRAIL_PRESENT                        = "HANDRAIL_PRESENT"

    FLUSH_KERB_RECORDED                     = "FLUSH_KERB_RECORDED"
    LOWERED_KERB_RECORDED                   = "LOWERED_KERB_RECORDED"
    RAISED_KERB_RECORDED                    = "RAISED_KERB_RECORDED"
    ROLLED_KERB_RECORDED                    = "ROLLED_KERB_RECORDED"

    PAVED_SURFACE_RECORDED                  = "PAVED_SURFACE_RECORDED"
    UNPAVED_SURFACE_RECORDED                = "UNPAVED_SURFACE_RECORDED"
    ROUGH_SURFACE_RECORDED                  = "ROUGH_SURFACE_RECORDED"

    PEDESTRIAN_CROSSING_RECORDED            = "PEDESTRIAN_CROSSING_RECORDED"
    SIGNALIZED_CROSSING_RECORDED            = "SIGNALIZED_CROSSING_RECORDED"
    MARKED_CROSSING_RECORDED                = "MARKED_CROSSING_RECORDED"
    TACTILE_PAVING_RECORDED                 = "TACTILE_PAVING_RECORDED"
    LIT_AT_NIGHT                            = "LIT_AT_NIGHT"

    STEEP_INCLINE_RECORDED                  = "STEEP_INCLINE_RECORDED"
    RESTRICTIVE_BARRIER_RECORDED            = "RESTRICTIVE_BARRIER_RECORDED"
    PASSABLE_BARRIER_RECORDED               = "PASSABLE_BARRIER_RECORDED"
    RESTRICTED_ACCESS_RECORDED              = "RESTRICTED_ACCESS_RECORDED"
```

---

## 5. Critical Non-Equivalences

### 5.1 Why Paved $\ne$ Wheelchair Accessible
In suburban networks, many footpaths and outdoor stairways are constructed from asphalt or concrete. 
- Example from Vermont South: Edge `(594545542 -> 594547432)` has `surface: 'asphalt'` and `highway: ['steps', 'footway']`.
- If an algorithm assumed `surface=asphalt` implied wheelchair accessibility, it would navigate wheelchair users onto a staircase.
- **Rule**: `SurfaceType.ASPHALT` generates `PAVED_SURFACE_RECORDED`. It does **not** generate `WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED`.

### 5.2 Why Missing Wheelchair Tag $\ne$ Inaccessible
In the 11,924 edges of Vermont South, **99.98% of edges do not carry an explicit `wheelchair=*` tag**.
- Most footpaths are standard public concrete footpaths where mappers simply omitted the tag.
- Treating un-tagged edges as inaccessible would render 99.9% of the pedestrian network impassable, making navigation impossible.
- **Rule**: Missing tags are classified as `WheelchairAccess.UNKNOWN`. They are added to `missing_fields` for Stage 3 multi-criteria evaluation.

---

## 6. Real-World Data Quality (Vermont South Benchmark)

Audit conducted across **4,114 nodes** and **11,924 edges**:

| Feature Category | Count in Graph | Completeness | Primary Finding |
| :--- | :--- | :--- | :--- |
| **Highway Type** | 11,924 edges | 100.0% | Complete pedestrian network topology |
| **Physical Surface** | 3,538 edges | 29.7% | 3,439 paved (asphalt/concrete), 97 unpaved (gravel/dirt) |
| **Pedestrian Crossings** | 2,084 edges / 467 nodes | 17.5% | Crossing infrastructure identified |
| **Stairs (Steps)** | 14 edges | 0.12% | All 14 lack ramp metadata |
| **Kerb Profile on Edges** | 0 edges / 2 nodes | < 0.1% | Kerb heights are severely under-mapped |
| **Tactile Paving** | 12 edges / 4 nodes | 0.1% | Tactile indicators rarely recorded |
| **Incline / Slope** | 10 edges | 0.08% | Slopes almost completely absent in 2D OSM ways |
| **Passage Width** | 0 edges | 0.0% | Sidewalk widths not mapped |
| **Explicit Wheelchair Tag** | 2 edges / 3 nodes | 0.02% | 99.98% missing in suburban area |

---

## 7. How Stage 2 Data Informs Stage 3 Routing

Stage 3 will formulate accessibility-aware routing as a **multi-criteria cost evaluation**:

$$\text{edge\_cost}(u, v) = \text{distance}(u, v) + \text{accessibility\_penalties}(u, v) + \text{uncertainty\_penalties}(u, v)$$

1. **Hard Barriers**: Edges with `STEPS_PRESENT` (without `RAMP_PRESENT`), `WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED`, or `RESTRICTIVE_BARRIER_RECORDED` receive an infinite cost ($\infty$), guaranteeing exclusion from wheelchair routes.
2. **Surface Penalties**: `UNPAVED_SURFACE_RECORDED` or `ROUGH_SURFACE_RECORDED` add moderate traversability penalties depending on the active mobility profile (manual vs powered wheelchair).
3. **Kerb Transitions**: Crossing edges lacking lowered kerbs or confirmed flush kerbs incur penalties or require user-specified kerb-climbing limits.
4. **Uncertainty Buffer**: Edges where `missing_fields` is high receive a gentle uncertainty factor, encouraging the router to prefer footways with confirmed positive infrastructure when alternative routes of comparable distance exist.
