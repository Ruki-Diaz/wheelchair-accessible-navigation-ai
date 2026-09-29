# AccessRoute AI — Stage 10: Accessibility Evidence Intelligence, Reliability & Verification Prioritisation

## 1. Executive Summary

Stage 10 transforms the Stage 9 community evidence layer into an explainable **Accessibility Evidence Intelligence System**. Rather than treating accessibility as binary or inventing unmapped infrastructure via opaque probabilistic models, Stage 10 introduces deterministic, scientifically rigorous analytics that answer:

1. **Evidence Reliability**: Which physical accessibility observations have strong community consensus versus single-observer or disputed status?
2. **Temporal Decay & Freshness**: How do different infrastructure types age over time (e.g. multi-year permanence for kerbs vs days for construction and hours for temporary obstacles)?
3. **Routing Impact**: Which missing accessibility attributes actually matter to pedestrian routes through controlled Origin-Destination (OD) sampling?
4. **Verification Prioritisation**: Where should community surveyors focus their verification efforts first to yield the highest impact on mobility routing?
5. **Regional Data Coverage**: Where are accessibility blind spots concentrated across a city?
6. **Route Evidence Quality**: How well-documented is an individual route alternative across OSM, Copernicus DEM terrain, and community evidence (measured in distance percentages, never an arbitrary "87% accessible" claim)?
7. **What-If Verification Analysis**: What route changes occur under hypothetical physical states (e.g. lowered vs raised kerb), strictly isolated from production data?
8. **Spatial Conflict Intelligence**: Where do repeated disagreements between OSM and community reports cluster geographically?
9. **Machine Learning Feasibility Audit**: An honest evaluation of real ground-truth label sparsity, maintaining the scientific conclusion of *"Insufficient labelled accessibility data for defensible supervised learning"* rather than manufacturing synthetic labels.

---

## 2. Core Architecture

The Stage 10 intelligence system is located in `backend/accessroute/intelligence/` and consists of modular, decoupled components:

```
backend/accessroute/intelligence/
├── __init__.py                # Package exports
├── models.py                  # Pydantic data models & explainable bands
├── reliability.py             # EvidenceReliabilityEngine & category decay
├── impact.py                  # RoutingImpactAnalyzer (deterministic OD sampling)
├── priority.py                # VerificationPriorityEngine
├── coverage.py                # RegionalCoverageAnalyzer (metrics & GeoJSON)
├── missions.py                # VerificationMissionEngine (actionable tasks)
├── route_quality.py           # RouteEvidenceQualityAnalyzer (distance breakdown)
├── whatif.py                  # WhatIfVerificationAnalyzer (hypothetical isolation)
├── conflicts.py               # ConflictIntelligenceEngine (spatial clustering)
├── ml_feasibility.py          # MLFeasibilityAuditor (honest label density audit)
└── service.py                 # EvidenceIntelligenceService orchestrator
```

---

## 3. Evidence Reliability & Temporal Decay

### 3.1 Explainable Reliability Bands

Rather than presenting an uncalibrated pseudo-probability percentage, observations are classified into transparent, reason-backed bands:

* **STRONG_COMMUNITY_EVIDENCE**: $\ge 3$ independent confirmations, dispute ratio $< 0.1$, not stale.
* **MODERATE_EVIDENCE**: $\ge 1$ confirmation, no disputes, not stale.
* **LOW_EVIDENCE**: Single unverified report, or unconfirmed observation.
* **CONFLICTING_EVIDENCE**: Disputed by peers ($\ge 1$ dispute) or directly contradicts verified OpenStreetMap data.
* **STALE**: Age exceeds category-specific freshness policy.

Every assessment exposes a list of plain-language `reasons` explaining why the band was assigned.

### 3.2 Category-Specific Freshness Policies

Infrastructure types decay at vastly different rates:

| Infrastructure Category | Active Window (Days) | Aging Threshold (Days) | Stale Threshold (Days) | Decay Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **KERB** | 365 | 730 | 1095 | Concrete civil infrastructure changes slowly over multiple years. |
| **PATH_WIDTH** | 365 | 730 | 1095 | Physical footpath corridors rarely widen or narrow quickly. |
| **SURFACE** | 180 | 365 | 730 | Paving degrades moderately over seasons and freeze/thaw cycles. |
| **STAIRS / RAMP** | 365 | 730 | 1095 | Structural stairs/ramps remain permanent unless renovated. |
| **CONSTRUCTION** | 7 | 14 | 30 | Active roadworks and footpath closures resolve over weeks. |
| **LIFT_STATUS** | 1 | 2 | 7 | Elevator outages and maintenance can be fixed within days. |
| **TEMPORARY_OBSTACLE** | 1 | 2 | 5 | Bins, parked delivery vehicles, and street furniture clear quickly. |

**Scientific Guardrail**: Stale evidence is **never deleted**. It is preserved historically with its full provenance and classified as `STALE`, signalling that community re-verification is warranted.

---

## 4. Deterministic Routing Impact Analysis

The `RoutingImpactAnalyzer` measures how missing or conflicting accessibility attributes actually impact pedestrian journeys.

### 4.1 Controlled Origin-Destination Sampling

To avoid fabricating unverified user demand, the system uses deterministic OD sampling across the regional pedestrian graph:
* Sample nodes are chosen deterministically at uniform strides across the graph index.
* Network diameter pairs $(u_{0}, u_{\text{mid}})$, $(u_{0}, u_{-1})$, and $(u_{\text{mid}}, u_{-1})$ are included to ensure thoroughfare traffic is captured.
* Synthetic experiments are explicitly labelled `SYNTHETIC`.

### 4.2 Computed Impact Metrics

* `routes_traversing_count`: Number of sampled paths traversing the feature.
* `percentage_of_sampled_routes`: Traversal frequency percentage ($0.0 - 100.0\%$).
* `shortest_path_frequency`: Traversal frequency under physical distance minimization.
* `accessible_route_frequency`: Traversal frequency under balanced accessibility routing.
* `max_detour_distance_m`: Potential detour required if the feature is avoided due to uncertainty or barrier status.
* `disconnect_risk`: True if avoiding the missing attribute disconnects any origin-destination pair under strict personal mobility preferences.
* `affected_profiles`: List of mobility profiles impacted (e.g. Manual Wheelchair, Mobility Scooter, Pram).

---

## 5. Multi-Factor Verification Priority Model

Missing data verification priorities are evaluated as a transparent product of three explainable components:

$$\text{Priority Score} = \text{RoutingImpactScore} \times \text{AccessibilityImportanceScore} \times \text{EvidenceNeedScore}$$

### 5.1 Component Definitions

1. **Routing Impact Score** ($0.2 - 2.5$):
   * Derived from network traversal percentage, detour penalty, and disconnect risk.
2. **Accessibility Importance Score** ($1.0 - 2.0$):
   * Kerb transition: $2.0$ (critical barrier for wheeled mobility).
   * Steps/stairs: $1.9$ (impassable for wheelchairs).
   * Surface: $1.4$ (affects manual wheelchair rolling resistance).
   * Path width: $1.5$ (affects wide powerchairs and scooters).
3. **Evidence Need Score** ($0.5 - 2.0$):
   * $2.0$ if completely missing in OSM and unobserved in community data.
   * $1.8$ if existing evidence is conflicting or disputed.
   * $1.5$ if existing evidence is stale.
   * $0.5$ if strongly supported by multiple independent peers.

### 5.2 Priority Bands

* **CRITICAL**: Thoroughfare with high transit frequency, steep detour/disconnect risk, and high accessibility importance (Score $\ge 6.0$).
* **HIGH**: Moderate traversal or significant detour risk affecting multiple wheeled mobility profiles (Score $3.0 - 5.9$).
* **MEDIUM**: Local connector with moderate accessibility relevance (Score $1.5 - 2.9$).
* **LOW**: Peripheral or dead-end spur with minimal transit traffic (Score $< 1.5$).

---

## 6. Actionable Community Verification Missions

Rather than abstract data gaps, the system synthesizes `VerificationMission` objects that can be directly addressed by community members:

* **Mission Title**: E.g., *"Check Kerb Ramp Transition"*, *"Check Footpath Surface"*.
* **Location Description**: Physical street name or crossing coordinate.
* **Why It Matters**: Transparent explanation (e.g., *"This crossing appears on 22% of sampled accessibility routes in Vermont South"*).
* **Routing Impact Summary**: E.g., *"Avoiding this feature adds a 140m detour for wheelchair users."*
* **Suggested Actions**: Structured buttons (*Lowered*, *Flush*, *Raised*, *No Kerb*).
* **Direct Hand-off to Stage 9**: Clicking *"Verify this location"* pre-fills the Stage 9 anonymous reporting dialog with coordinates and category.
* **No Premature Gamification**: No points, leaderboards, or artificial badges in Stage 10.

---

## 7. Route Evidence Quality Breakdown

In adherence to scientific integrity, AccessRoute AI **never** outputs pseudo-statistical claims like *"87% accessible"*. Instead, individual route alternatives provide a structured `RouteEvidenceQuality` breakdown:

```json
{
  "strong_evidence_distance_pct": 52.4,
  "partial_evidence_distance_pct": 31.8,
  "limited_evidence_distance_pct": 15.8,
  "community_supported_count": 3,
  "conflicting_evidence_count": 0,
  "stale_observations_count": 1,
  "important_unknowns": [
    "2 crossings missing kerb ramp data",
    "140m path missing surface information",
    "Copernicus GLO-30 DEM estimated slope"
  ],
  "quality_summary": "Strong evidence: 52% | Partial: 32% | Limited: 16%"
}
```

---

## 8. What-If Hypothetical Verification Analysis

The `WhatIfVerificationAnalyzer` enables researchers and urban planners to simulate:
> *"What changes to routing if this unverified kerb is lowered versus raised?"*

### Scientific Isolation Guarantee

Hypothetical analysis uses temporary deep-copies of graph edge attributes with `is_hypothetical = True`. It **never** mutates the persistent OpenStreetMap cache or SQLite community repository. If a hypothetical state causes a detour, the delta is reported in meters and affected profiles are listed.

---

## 9. Spatial Conflict Intelligence

The `ConflictIntelligenceEngine` clusters disagreements between OpenStreetMap and community observations within configurable geographic radii (default: 30m).

### Observable Reporting Without Guesswork

The system reports strictly observable facts:
* *"2 conflicting observations recorded within 17m concerning kerb and surface infrastructure."*
* No speculation about motives, vandalism, or contractor quality is fabricated.

---

## 10. Machine Learning Feasibility Audit

AccessRoute AI adheres to scientific honesty regarding machine learning:

1. **Audit Methodology**: The `MLFeasibilityAuditor` inspects all road crossings in cached regional graphs (Vermont South, Melbourne CBD, Sydney CBD).
2. **Defensibility Criteria**: Supervised learning is deemed defensible only if $\ge 250$ verified physical kerb labels exist, with label coverage $\ge 20\%$ and balanced class distribution.
3. **Empirical Finding**: Real OpenStreetMap pedestrian networks in the tested regions currently possess near-zero kerb transition tags ($0.0\%$ in raw samples).
4. **Defensible Conclusion**:
   > *"Insufficient labelled accessibility data for defensible supervised learning."*
5. **Architectural Rule**: Any future ML models must remain classified as `RESEARCH_PREDICTION` and kept strictly isolated from ground-truth OSM and community-verified evidence.

---

## 11. REST API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/intelligence/coverage` | `GET` | Regional metadata completeness stats (surface, kerb, width, wheelchair). |
| `/api/v1/intelligence/coverage/geojson` | `GET` | GeoJSON LineStrings colored by completeness score for map rendering. |
| `/api/v1/intelligence/verification-priorities` | `GET` | Ranked list of verification opportunities with explainable priorities. |
| `/api/v1/intelligence/missions` | `GET` | Actionable community verification tasks sorted by urgency. |
| `/api/v1/intelligence/reliability/{observation_id}` | `GET` | Transparent reliability band and explainable reasons for an observation. |
| `/api/v1/intelligence/what-if` | `POST` | Deterministic simulation of route impact under hypothetical attribute states. |
| `/api/v1/intelligence/conflicts` | `GET` | Spatially clustered OSM vs community evidence disagreements. |
| `/api/v1/intelligence/ml-feasibility` | `GET` | Empirical audit of ground-truth label density and ML defensibility. |

---

## 12. Automated Test Suite

Stage 10 introduces 22 comprehensive automated tests in `backend/tests/test_intelligence.py` covering:
* Reliability band assignment and explainable reasons.
* Category-specific temporal decay and staleness preservation.
* Deterministic OD routing impact analysis and detour calculation.
* Priority scoring and explainability without arbitrary numbers.
* Actionable verification mission generation and action mapping.
* Route evidence quality breakdown.
* What-if hypothetical isolation (`is_hypothetical = True`).
* Spatial conflict clustering.
* Machine learning feasibility auditing.
* End-to-end REST API integration.

**Regression Status**: All 189 baseline tests from Stages 1–9 and all 22 Stage 10 tests pass (**211 passed, 0 failures**).
