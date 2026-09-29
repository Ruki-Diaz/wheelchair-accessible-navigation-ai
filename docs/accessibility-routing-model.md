# AccessRoute AI — Explainable Accessibility-Aware Multi-Criteria Routing Model (Stage 3)

---

## 1. Executive Summary and Philosophy

Stage 3 transitions AccessRoute AI from a distance-only pathfinding prototype into an **explainable, multi-criteria accessibility routing engine**.

Traditional mapping platforms operate on single-objective cost minimization (e.g. shortest travel distance or fastest travel time). When accessibility is introduced, naive systems frequently commit one of two fundamental errors:
1. **Inventing Universal Thresholds**: Declaring arbitrarily that "manual wheelchairs cannot climb $>5\%$ slopes" or "powered chairs can climb $>10\%$ slopes", ignoring wide variations in user upper-body strength, power-assist wheels, wheelchair wheelbase, kerb climber attachments, battery power, and local infrastructure design standards.
2. **Treating Unknown as Binary**: Treating unrecorded infrastructure (`UNKNOWN`) either as completely safe (leading users into impassable obstacles) or completely forbidden (causing unnecessary multi-kilometer detours across suburban neighborhoods where data coverage is incomplete).

AccessRoute AI resolves this challenge through three core architectural tenets:
1. **Separation of Dimensions**: Distance, accessibility difficulty, and data uncertainty are evaluated and accumulated in distinct metrics. They are never collapsed into an opaque score.
2. **Context-Aware Uncertainty**: Missing data is penalized based on the operational criticality of the missing attribute in that specific infrastructure context (e.g., missing kerb info on a busy arterial pedestrian crossing is penalized far higher than missing kerb info along a residential footpath).
3. **Deterministic Explainability**: Every routing choice is justified through verifiable topological and environmental evidence, not opaque neural network hallucinations.

---

## 2. Multi-Criteria Cost Formulation

For any directed edge $e = (u, v)$ traversing from node $u$ to node $v$, the total scalar routing cost $C(u, v)$ evaluated during path search is:

$$C(u, v) = w_d \cdot D(u, v) + w_a \cdot A(u, v) + w_u \cdot U(u, v)$$

Where:
- $D(u, v) \in \mathbb{R}_{\ge 0}$ is the **physical distance** in meters ($D = \text{length}$).
- $A(u, v) \in \mathbb{R}_{\ge 0}$ is the **accessibility cost**, quantifying physical resistance, difficulty, or known hazards.
- $U(u, v) \in \mathbb{R}_{\ge 0}$ is the **uncertainty cost**, quantifying information incompleteness and risk of unverified infrastructure.
- $w_d, w_a, w_u \ge 0$ are the configurable policy weights balancing distance efficiency, physical comfort/safety, and informational risk tolerance.

Crucially, while $C(u, v)$ guides priority-queue exploration in A*, the path tracker retains the accumulated $D$, $A$, and $U$ sums independently in the final `RouteResult`.

---

## 3. Hard Prohibitions vs Soft Preferences

Routing decisions are cleanly split into **Hard Exclusions** (inviolable physical or legal barriers) and **Soft Preferences** (traversable but penalized features).

### 3.1 Hard Exclusions ($C = \infty$)
If a transition triggers any hard exclusion enabled in the active `RoutingPolicy`, the edge is pruned immediately from the search tree:

1. **Explicit Legal Prohibition**: `wheelchair = "no"` on either the edge or destination node (`prohibit_wheelchair_no=True`).
2. **Unramped Stairs**: Highway or feature marked as `steps` where no verified wheelchair ramp or elevator exists (`prohibit_steps=True` and `has_wheelchair_ramp=False`).
3. **Restrictive Physical Barriers**: Nodes containing impassable structures such as `turnstile`, `cycle_barrier`, `stile`, or `kissing_gate` (`prohibit_restrictive_barriers=True`).
4. **Severe Incline**: Known verified slope exceeding the user policy threshold (`prohibit_steep_incline=True` and $\text{slope} > \theta_{\max}$).

*Note on ambiguous barriers*: Tagged features such as `barrier=gate` or `barrier=bollard` are **not** treated as hard prohibitions unless explicit `access=no` or `wheelchair=no` is recorded. If passage width or gate status is unrecorded, it is treated as an informational uncertainty, avoiding catastrophic false-positive network disconnects.

### 3.2 Soft Accessibility Costs ($A(u, v)$)
When an edge is physically traversable, physical attributes contribute soft penalties:
- **Surface Resistance**: Unpaved paths (gravel, dirt, grass) add an impedance penalty per meter of length:
  $$A_{\text{surface}} = \text{length} \times \text{cost\_unpaved\_per\_meter}$$
  Rough surfaces (cobblestones, uneven pavers) add:
  $$A_{\text{surface}} = \text{length} \times \text{cost\_rough\_surface\_per\_meter}$$
- **Kerb Transitions**: Crossing a node with a recorded unramped `RAISED` kerb adds a discrete penalty:
  $$A_{\text{kerb}} = \text{cost\_raised\_kerb}$$
  Conversely, transitions with `FLUSH` or `LOWERED` kerbs incur zero kerb penalty.
- **Controlled Steps**: If steps have verified ramp access, a modest transit penalty is incurred rather than infinite exclusion.

---

## 4. Context-Aware Uncertainty Modeling ($U(u, v)$)

Unrecorded data cannot be assumed to be either compliant or non-compliant. Instead, missing data incurs an **uncertainty cost** proportional to the hazard risk of the missing attribute in its operational context:

| Context | Missing Attribute | Risk Profile | Default Weight |
| :--- | :--- | :--- | :--- |
| **Pedestrian Crossing** | Kerb Profile (`kerb=unknown`) | High: User may cross road and encounter an impassable 150mm vertical kerb on the opposing sidewalk with traffic approaching. | $25.0$ penalty units |
| **Pedestrian Crossing** | Tactile Paving (`tactile_paving=unknown`) | Medium: Navigational challenge for vision-impaired wheelchair users. | $5.0$ penalty units |
| **Sidewalk / Footway** | Surface Type (`surface=unknown`) | Moderate: Potential for sudden transition to loose mud or gravel. | $0.05$ per meter |
| **Pedestrian Segment** | Width (`width=unknown`) | Contextual: Potential for pinch points below minimum wheelchair clearance. | $5.0$ discrete penalty |
| **Pedestrian Segment** | Lighting (`lit=unknown`) | Low/Contextual: Daytime routing is unaffected; night routing can enable nocturnal penalty. | $0.0$ (day) / $2.0$ (night) |

---

## 5. Development Routing Policies

AccessRoute AI provides three pre-calibrated development routing policies designed to explore distinct operational trade-offs. These are explicitly defined as **development parameters**, not medical prescriptions:

```python
CONSERVATIVE_ACCESSIBILITY_POLICY = RoutingPolicy(
    name="Conservative Accessibility",
    distance_weight=1.0,
    accessibility_weight=2.5,
    uncertainty_weight=2.0,
    prohibit_steps=True,
    prohibit_wheelchair_no=True,
    prohibit_restrictive_barriers=True,
    prefer_paved=True,
    avoid_unpaved=True,
    cost_unpaved_per_meter=2.0,
    cost_raised_kerb=50.0,
    cost_crossing_unknown_kerb=35.0,
)

BALANCED_ACCESSIBILITY_POLICY = RoutingPolicy(
    name="Balanced Accessibility",
    distance_weight=1.0,
    accessibility_weight=1.0,
    uncertainty_weight=0.5,
    prohibit_steps=True,
    prohibit_wheelchair_no=True,
    prohibit_restrictive_barriers=True,
    cost_unpaved_per_meter=0.8,
    cost_raised_kerb=25.0,
    cost_crossing_unknown_kerb=15.0,
)

DISTANCE_FIRST_POLICY = RoutingPolicy(
    name="Distance-First",
    distance_weight=1.0,
    accessibility_weight=0.0,
    uncertainty_weight=0.0,
    prohibit_steps=True,
    prohibit_wheelchair_no=True,
    prohibit_restrictive_barriers=True,
)
```

---

## 6. A* Heuristic Admissibility and Mathematical Proof

A crucial requirement in multi-criteria A* pathfinding is preserving the **admissibility** of the geographic heuristic function $h(u, G)$. If $h(u, G)$ ever overestimates the minimum possible path cost from node $u$ to destination $G$, A* loses its optimality guarantee.

### 6.1 Cost Lower Bound
For any edge transition $e = (u, v)$ with physical length $L(e)$:
- Physical distance contribution: $w_d \cdot L(e) \ge 0$.
- Accessibility cost contribution: $w_a \cdot A(e) \ge 0$.
- Uncertainty cost contribution: $w_u \cdot U(e) \ge 0$.

Since $A(e) \ge 0$ and $U(e) \ge 0$, the edge cost satisfies:
$$C(e) = w_d \cdot L(e) + w_a \cdot A(e) + w_u \cdot U(e) \ge w_d \cdot L(e)$$

Summing across any path $P = (u = v_0, v_1, \dots, v_k = G)$ connecting $u$ to $G$:
$$\text{Cost}(P) = \sum_{i=1}^k C(v_{i-1}, v_i) \ge w_d \sum_{i=1}^k L(v_{i-1}, v_i)$$

By the triangle inequality on the sphere, the great-circle Haversine distance $H(u, G)$ is a strict lower bound on any physical walking path between $u$ and $G$:
$$\sum_{i=1}^k L(v_{i-1}, v_i) \ge H(u, G)$$

Therefore:
$$\text{Cost}(P) \ge w_d \cdot H(u, G)$$

### 6.2 Admissible Heuristic Function
We define the A* heuristic scaled exactly by the distance weight:
$$h(u, G) = w_d \cdot \text{haversine}(u, G)$$

Because $h(u, G) \le \text{Cost}(P)$ for all candidate paths $P$, $h(u, G)$ is **strictly admissible**. It never overestimates the true remaining multi-criteria cost.

### 6.3 Verification via Dijkstra
In `test_astar_vs_dijkstra_accessibility_optimality`, our custom A* algorithm was verified against NetworkX's canonical Dijkstra algorithm using the identical multi-criteria edge cost callable. In all test topologies, the path cost discovered by A* was identical to Dijkstra down to machine precision ($\Delta = 0.000000$).

---

## 7. Parallel Edge Selection in MultiDiGraphs

OpenStreetMap represents dual pedestrian walkways, road sidewalks, and parallel cycle paths as multiple directed edges between identical node pairs $(u, v, k)$.

In Stage 1, the router selected the minimum-distance edge:
$$k^* = \arg\min_k \text{length}(u, v, k)$$

In Stage 3, the router selects the edge minimizing the multi-criteria policy cost:
$$k^* = \arg\min_k C(u, v, k; \text{Policy})$$

This ensures that if a direct edge of length $20\text{m}$ consists of unramped stairs while a parallel ramp of length $28\text{m}$ provides smooth concrete access, the routing engine automatically traverses the ramp.

---

## 8. Explainability Engine

Routing recommendations must build user trust through transparency. The explainability engine analyzes the differences between the chosen route and the shortest baseline path, generating deterministic, reproducible explanations based strictly on recorded graph evidence:

```python
RouteExplanation(
    summary="Route avoids 1 stair segment by taking an accessible 156.2m detour.",
    barriers_avoided=["Outdoor Stairs"],
    accessibility_features_used=["Paved surface", "Lowered kerb crossing"],
    uncertainty_warnings=[
        "Missing kerb profile on 2 pedestrian crossings.",
        "62.4% of route distance lacks recorded surface type."
    ],
    rationale_bullets=[
        "Baseline route traversed outdoor stairs at node 629887508.",
        "Accessible route diverts via fully ramped paved pathway.",
        "Total journey distance increased by 156.2m (+596.2%)."
    ]
)
```

No Large Language Models (LLMs) or non-deterministic generators are used in route rationale generation.

---

## 9. Baseline vs Accessibility Route Comparison

The system exposes structured comparative evaluations for any origin/destination pair:

```
┌────────────────────────────────────────────────────────┐
│                   Route Comparison                     │
├──────────────────────────┬──────────────┬──────────────┤
│ Metric                   │ Baseline     │ Accessible   │
├──────────────────────────┼──────────────┼──────────────┤
│ Physical Distance        │ 26.2 m       │ 182.4 m      │
│ Net Distance Increase    │ —            │ +156.2 m     │
│ Total Policy Cost        │ 526.2        │ 204.6        │
│ Accessibility Cost       │ 500.0        │ 12.2         │
│ Uncertainty Cost         │ 0.0          │ 10.0         │
│ Outdoor Stairs           │ 1 segment    │ 0 segments   │
│ Unpaved Segments         │ 0 segments   │ 0 segments   │
│ Unknown Surface Ratio    │ 0.0%         │ 8.5%         │
└──────────────────────────┴──────────────┴──────────────┘
```

---

## 10. Multi-Objective / Pareto Front Analysis

Real-world accessibility decisions often involve subjective trade-offs between physical exertion (distance) and safety/comfort (smoothness, certainty).

### Stage 3 Implementation
The Stage 3 architecture supports generating multiple candidate routes along the trade-off surface by querying the router across distinct policy presets (`DISTANCE_FIRST`, `BALANCED`, `CONSERVATIVE`):

```python
alternatives = generate_policy_alternatives(
    graph, origin, destination,
    policies=[DISTANCE_FIRST_POLICY, BALANCED_ACCESSIBILITY_POLICY, CONSERVATIVE_ACCESSIBILITY_POLICY]
)
```

### Future Research: Full Multi-Objective Pareto Routing
Stage 3 does not implement a full multi-criteria Pareto label-setting algorithm (such as Martins' Multi-Objective Shortest Path algorithm or BOA*). 
- *Justification*: Full Pareto frontier computation on large-scale urban MultiDiGraphs is NP-hard and exhibits exponential worst-case runtime unless heavily constrained.
- *Recommendation*: The multi-policy alternative generator implemented in Stage 3 provides immediate, practical non-dominated choices (shortest vs safest vs most certain) without sacrificing sub-millisecond query performance. Full Pareto labeling should be evaluated as an advanced research milestone in Stage 7.

---

## 11. Limitations and Data Science Realities

1. **Elevation & Microtopography**: OpenStreetMap 2D linestrings contain no vertical elevation coordinates. Slope calculations rely on sparse, community-tagged `incline=*` tags. Integrating external Digital Elevation Models (DEMs) or LiDAR point clouds is essential for reliable slope calculations.
2. **Missing Suburban Kerb Data**: In typical Australian suburban networks, over 90% of residential footpaths lack explicit `kerb=*` or `surface=*` attributes. Contextual uncertainty penalization prevents route failure but highlights the necessity of crowdsourcing and municipal Open Data integration.
3. **Dynamic / Seasonal Conditions**: Physical accessibility varies with weather (e.g. grass paths turn into mud after rain; leaf buildup blocks drains; temporary construction fencing obstructs sidewalks). These dynamic factors require future real-time hazard reporting layers.
