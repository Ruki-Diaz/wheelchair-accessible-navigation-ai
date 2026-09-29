"""Multi-criteria cost evaluator decomposing distance, accessibility, and uncertainty.

Evaluates both edge evidence and destination node evidence for every network transition.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Set
import networkx as nx

from accessroute.routing.policy import RoutingPolicy
from accessroute.scoring.models import (
    EdgeAccessibilityEvidence,
    FindingType,
    KerbType,
    NodeAccessibilityEvidence,
    SurfaceType,
)
from accessroute.scoring.normalizer import (
    extract_edge_evidence,
    extract_node_evidence,
)


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed decomposition of traversal costs for a single transition u -> v."""
    physical_distance_m: float
    accessibility_penalty_m: float
    terrain_penalty_m: float
    uncertainty_penalty_m: float
    total_weighted_cost: float
    is_prohibited: bool = False
    prohibition_reason: str = ""
    findings: Set[FindingType] = field(default_factory=set)
    community_observations: list = field(default_factory=list)


def evaluate_transition_cost(
    edge_evidence: EdgeAccessibilityEvidence,
    node_evidence: Optional[NodeAccessibilityEvidence],
    policy: RoutingPolicy,
    physical_distance_m: float,
    terrain_evidence: Optional[Any] = None,
    community_observations: Optional[list] = None,
) -> CostBreakdown:
    """Evaluate transition cost across distance, known accessibility, terrain, and contextual uncertainty.

    Args:
        edge_evidence: Extracted accessibility evidence for the traversing way.
        node_evidence: Optional extracted accessibility evidence for the target arrival node.
        policy: The active RoutingPolicy governing weights and prohibitions.
        physical_distance_m: Physical traversal length in meters.
        terrain_evidence: Optional EdgeTerrainEvidence with directional grade and elevation stats.
        community_observations: Optional list of active CommunityObservation instances.

    Returns:
        CostBreakdown containing separated metrics and total weighted cost.
    """
    # Aggregate all findings from edge, target node, and terrain
    findings: Set[FindingType] = set(edge_evidence.findings)
    if node_evidence:
        findings.update(node_evidence.findings)

    # Filter to active community observations (not expired, not rejected)
    active_comm_obs = [
        obs for obs in (community_observations or [])
        if hasattr(obs, "is_active") and obs.is_active()
    ]

    # Evaluate community hard prohibitions and findings
    for c_obs in active_comm_obs:
        cat_val = getattr(c_obs.category, "value", str(c_obs.category)).lower()
        obs_val = str(c_obs.value).lower()
        stat_val = getattr(c_obs.verification_status, "value", str(c_obs.verification_status)).lower()

        is_supported_or_verified = stat_val in ("community_supported", "verified")

        if is_supported_or_verified:
            # 1. Path Blocked / Construction
            if cat_val in ("path_blocked", "construction"):
                findings.add(FindingType.COMMUNITY_PATH_BLOCKED)
                if cat_val == "construction":
                    findings.add(FindingType.COMMUNITY_CONSTRUCTION_REPORTED)
                return CostBreakdown(
                    physical_distance_m=physical_distance_m,
                    accessibility_penalty_m=float("inf"),
                    terrain_penalty_m=0.0,
                    uncertainty_penalty_m=float("inf"),
                    total_weighted_cost=float("inf"),
                    is_prohibited=True,
                    prohibition_reason=f"Footpath is currently reported blocked by community observation ({cat_val}={obs_val}, status: {stat_val}).",
                    findings=findings,
                    community_observations=active_comm_obs,
                )

            # 2. Impassable temporary obstacle
            if cat_val == "temporary_obstacle" and obs_val in ("impassable", "blocked"):
                findings.add(FindingType.COMMUNITY_PATH_BLOCKED)
                return CostBreakdown(
                    physical_distance_m=physical_distance_m,
                    accessibility_penalty_m=float("inf"),
                    terrain_penalty_m=0.0,
                    uncertainty_penalty_m=float("inf"),
                    total_weighted_cost=float("inf"),
                    is_prohibited=True,
                    prohibition_reason=f"Impassable temporary obstacle reported by community ({obs_val}).",
                    findings=findings,
                    community_observations=active_comm_obs,
                )

            # 3. Community-supported Stairs
            if cat_val == "stairs":
                findings.add(FindingType.COMMUNITY_STAIRS_REPORTED)
                findings.add(FindingType.STEPS_PRESENT)
                if policy.prohibit_steps_without_ramp:
                    return CostBreakdown(
                        physical_distance_m=physical_distance_m,
                        accessibility_penalty_m=float("inf"),
                        terrain_penalty_m=0.0,
                        uncertainty_penalty_m=float("inf"),
                        total_weighted_cost=float("inf"),
                        is_prohibited=True,
                        prohibition_reason="Community-supported observation reports stairs present without ramp.",
                        findings=findings,
                        community_observations=active_comm_obs,
                    )

            # 4. Restrictive Barrier
            if cat_val == "barrier" and obs_val in ("turnstile", "cycle_barrier", "construction_barrier"):
                findings.add(FindingType.RESTRICTIVE_BARRIER_RECORDED)
                if policy.prohibit_known_restrictive_barriers:
                    return CostBreakdown(
                        physical_distance_m=physical_distance_m,
                        accessibility_penalty_m=float("inf"),
                        terrain_penalty_m=0.0,
                        uncertainty_penalty_m=float("inf"),
                        total_weighted_cost=float("inf"),
                        is_prohibited=True,
                        prohibition_reason=f"Community-supported observation reports restrictive barrier ({obs_val}).",
                        findings=findings,
                        community_observations=active_comm_obs,
                    )

            # 5. Raised Kerb
            if cat_val == "kerb" and obs_val == "raised":
                findings.add(FindingType.RAISED_KERB_RECORDED)

            # 6. Unpaved Surface
            if cat_val == "surface" and obs_val in ("gravel", "dirt", "grass", "cobblestone"):
                findings.add(FindingType.UNPAVED_SURFACE_RECORDED)
                if policy.prohibit_unpaved_surfaces:
                    return CostBreakdown(
                        physical_distance_m=physical_distance_m,
                        accessibility_penalty_m=float("inf"),
                        terrain_penalty_m=0.0,
                        uncertainty_penalty_m=float("inf"),
                        total_weighted_cost=float("inf"),
                        is_prohibited=True,
                        prohibition_reason=f"Community-supported observation reports unpaved surface ({obs_val}).",
                        findings=findings,
                        community_observations=active_comm_obs,
                    )
        elif stat_val in ("unverified", "community_disputed"):
            findings.add(FindingType.COMMUNITY_UNVERIFIED_OBSTACLE)

    # =========================================================================
    # 1. HARD PROHIBITIONS (Returns Infinite Cost)
    # =========================================================================
    if policy.prohibit_wheelchair_no and (
        FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED in findings
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=float("inf"),
            terrain_penalty_m=0.0,
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason="Wheelchair access is explicitly prohibited (wheelchair=no).",
            findings=findings,
        )

    if policy.prohibit_steps_without_ramp and (
        FindingType.STEPS_PRESENT in findings
    ):
        has_ramp = (
            FindingType.RAMP_PRESENT in findings
            or FindingType.RAMP_WHEELCHAIR_DESIGNATED in findings
        )
        if not has_ramp:
            return CostBreakdown(
                physical_distance_m=physical_distance_m,
                accessibility_penalty_m=float("inf"),
                terrain_penalty_m=0.0,
                uncertainty_penalty_m=float("inf"),
                total_weighted_cost=float("inf"),
                is_prohibited=True,
                prohibition_reason="Stairs present without wheelchair ramp.",
                findings=findings,
            )

    if policy.prohibit_known_restrictive_barriers and (
        FindingType.RESTRICTIVE_BARRIER_RECORDED in findings
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=float("inf"),
            terrain_penalty_m=0.0,
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason="Restrictive physical barrier (e.g. turnstile or cycle barrier) present.",
            findings=findings,
        )

    if policy.prohibit_unpaved_surfaces and (
        FindingType.UNPAVED_SURFACE_RECORDED in findings
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=float("inf"),
            terrain_penalty_m=0.0,
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason="Unpaved surface prohibited by active policy.",
            findings=findings,
        )

    if (
        policy.prohibit_below_min_width
        and policy.minimum_path_width_m is not None
        and edge_evidence.width.is_known
        and edge_evidence.width.meters < policy.minimum_path_width_m
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=float("inf"),
            terrain_penalty_m=0.0,
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason=(
                f"Recorded path width of {edge_evidence.width.meters:.2f}m is below minimum requirement "
                f"of {policy.minimum_path_width_m:.2f}m."
            ),
            findings=findings,
        )

    # Unknown kerb crossing hard prohibition
    if policy.prohibit_unknown_kerb_crossings and FindingType.PEDESTRIAN_CROSSING_RECORDED in findings:
        has_known_kerb = (
            edge_evidence.kerb != KerbType.UNKNOWN
            or (node_evidence is not None and node_evidence.kerb != KerbType.UNKNOWN)
        )
        if not has_known_kerb:
            return CostBreakdown(
                physical_distance_m=physical_distance_m,
                accessibility_penalty_m=float("inf"),
                terrain_penalty_m=0.0,
                uncertainty_penalty_m=float("inf"),
                total_weighted_cost=float("inf"),
                is_prohibited=True,
                prohibition_reason="Crossing lacks recorded kerb ramp information and policy strictly prohibits unknown kerbs.",
                findings=findings,
            )

    # Determine signed grade from terrain evidence or OSM incline tag
    signed_grade: Optional[float] = None
    if terrain_evidence is not None and getattr(terrain_evidence, "is_known", False):
        signed_grade = getattr(terrain_evidence, "signed_grade", None)
    elif edge_evidence.incline.percentage is not None:
        signed_grade = edge_evidence.incline.percentage / 100.0

    # Hard slope prohibition (policy-configurable, e.g. strict uphill limits)
    if (
        policy.prohibit_steep_incline
        and policy.max_permitted_uphill_grade_pct is not None
        and signed_grade is not None
        and (signed_grade * 100.0) > policy.max_permitted_uphill_grade_pct
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=0.0,
            terrain_penalty_m=float("inf"),
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason=(
                f"Uphill slope of {signed_grade * 100.0:.1f}% exceeds policy limit "
                f"of {policy.max_permitted_uphill_grade_pct:.1f}%."
            ),
            findings=findings,
        )

    if (
        policy.max_tolerable_incline_pct is not None
        and edge_evidence.incline.percentage is not None
        and abs(edge_evidence.incline.percentage) > policy.max_tolerable_incline_pct
    ):
        return CostBreakdown(
            physical_distance_m=physical_distance_m,
            accessibility_penalty_m=float("inf"),
            terrain_penalty_m=0.0,
            uncertainty_penalty_m=float("inf"),
            total_weighted_cost=float("inf"),
            is_prohibited=True,
            prohibition_reason=(
                f"Slope of {edge_evidence.incline.percentage:.1f}% exceeds policy limit "
                f"of {policy.max_tolerable_incline_pct:.1f}%."
            ),
            findings=findings,
        )

    # =========================================================================
    # 2. SOFT ACCESSIBILITY PENALTIES (Virtual Meters)
    # =========================================================================
    acc_penalty = 0.0

    # Steps penalty when stairs are not strictly prohibited
    if not policy.prohibit_steps_without_ramp and policy.penalty_steps_without_ramp_m > 0:
        if FindingType.STEPS_PRESENT in findings:
            has_ramp = (
                FindingType.RAMP_PRESENT in findings
                or FindingType.RAMP_WHEELCHAIR_DESIGNATED in findings
            )
            if not has_ramp:
                acc_penalty += policy.penalty_steps_without_ramp_m

    # Path width penalty (when path is narrower than preferred)
    if (
        policy.penalty_below_min_width_m > 0
        and policy.minimum_path_width_m is not None
        and edge_evidence.width.is_known
        and edge_evidence.width.meters < policy.minimum_path_width_m
    ):
        acc_penalty += policy.penalty_below_min_width_m

    # Surface penalties
    if edge_evidence.surface == SurfaceType.GRASS:
        acc_penalty += policy.penalty_grass_surface_m
    elif FindingType.UNPAVED_SURFACE_RECORDED in findings:
        acc_penalty += policy.penalty_unpaved_surface_m

    if FindingType.ROUGH_SURFACE_RECORDED in findings:
        acc_penalty += policy.penalty_rough_surface_m

    # Kerb penalties (evaluated from either way or arriving crossing node)
    if FindingType.RAISED_KERB_RECORDED in findings:
        acc_penalty += policy.penalty_raised_kerb_m
    elif FindingType.ROLLED_KERB_RECORDED in findings:
        acc_penalty += policy.penalty_rolled_kerb_m

    # Uncontrolled street crossing penalty
    if (
        FindingType.PEDESTRIAN_CROSSING_RECORDED in findings
        and FindingType.SIGNALIZED_CROSSING_RECORDED not in findings
    ):
        acc_penalty += policy.penalty_uncontrolled_crossing_m

    # Passable barriers (e.g. opening a gate or maneuvering between bollards)
    if FindingType.PASSABLE_BARRIER_RECORDED in findings:
        acc_penalty += policy.penalty_passable_barrier_m

    # Legacy OSM incline penalty if no terrain evidence
    if terrain_evidence is None and edge_evidence.incline.percentage is not None and edge_evidence.incline.percentage > 0:
        acc_penalty += edge_evidence.incline.percentage * policy.penalty_per_incline_pct_m

    # =========================================================================
    # 3. DIRECTIONAL TERRAIN & GRADE PENALTIES
    # =========================================================================
    terrain_penalty = 0.0
    if signed_grade is not None:
        grade_pct = signed_grade * 100.0
        if signed_grade > 0:
            # Uphill travel: penalize slope exceeding preferred threshold
            if grade_pct > policy.max_preferred_uphill_grade_pct:
                excess_uphill = grade_pct - policy.max_preferred_uphill_grade_pct
                terrain_penalty += (
                    (physical_distance_m / 100.0)
                    * excess_uphill
                    * policy.penalty_per_uphill_grade_pct_m
                )
        elif signed_grade < 0:
            # Downhill travel: penalize steep slopes where wheelchair braking/control is challenging
            downhill_pct = abs(grade_pct)
            if downhill_pct > policy.max_preferred_downhill_grade_pct:
                excess_downhill = downhill_pct - policy.max_preferred_downhill_grade_pct
                terrain_penalty += (
                    (physical_distance_m / 100.0)
                    * excess_downhill
                    * policy.penalty_steep_downhill_pct_m
                )

    # =========================================================================
    # 4. CONTEXTUAL UNCERTAINTY PENALTIES (Missing Data Risk)
    # =========================================================================
    unc_penalty = 0.0

    # Context 1: Pedestrian crossing lacking kerb ramp information
    is_crossing = FindingType.PEDESTRIAN_CROSSING_RECORDED in findings
    has_known_kerb = (
        edge_evidence.kerb != KerbType.UNKNOWN
        or (node_evidence is not None and node_evidence.kerb != KerbType.UNKNOWN)
    )
    if is_crossing and not has_known_kerb:
        unc_penalty += policy.uncertainty_missing_crossing_kerb_m

    # Context 2: Footpath with unknown surface
    if edge_evidence.surface == SurfaceType.UNKNOWN:
        unc_penalty += policy.uncertainty_missing_surface_m

    # Context 3: Unknown slope
    if not edge_evidence.incline.is_known and signed_grade is None and not is_crossing:
        unc_penalty += policy.uncertainty_missing_incline_m

    # Context 4: Suspicious short-edge grade (DEM jitter safeguard)
    if terrain_evidence is not None and getattr(terrain_evidence, "is_grade_suspicious", False):
        unc_penalty += 10.0

    # Context 5: Missing elevation data
    if (
        (terrain_evidence is not None and not getattr(terrain_evidence, "is_known", False))
        or FindingType.ELEVATION_EVIDENCE_MISSING.value in [f if isinstance(f, str) else f.value for f in findings]
    ):
        unc_penalty += policy.uncertainty_missing_elevation_m

    # Context 6: Unknown path width
    if policy.uncertainty_missing_width_m > 0 and not edge_evidence.width.is_known and not is_crossing:
        unc_penalty += policy.uncertainty_missing_width_m

    # Context 7: General missing fields count
    minor_missing_count = sum(
        1 for f in edge_evidence.missing_fields if f in ("lit", "smoothness")
    )
    unc_penalty += minor_missing_count * policy.uncertainty_general_missing_field_m

    # Context 8: Community unverified or disputed reports (Uncertainty risk)
    for c_obs in active_comm_obs:
        stat_val = getattr(c_obs.verification_status, "value", str(c_obs.verification_status)).lower()
        cat_val = getattr(c_obs.category, "value", str(c_obs.category)).lower()
        if stat_val == "unverified":
            if cat_val in ("path_blocked", "construction"):
                unc_penalty += 120.0
            else:
                unc_penalty += 80.0
        elif stat_val == "community_disputed":
            unc_penalty += 30.0

    # =========================================================================
    # 5. TOTAL WEIGHTED COST
    # =========================================================================
    total_cost = (
        (policy.distance_weight * physical_distance_m)
        + (policy.accessibility_weight * acc_penalty)
        + (policy.terrain_weight * terrain_penalty)
        + (policy.uncertainty_weight * unc_penalty)
    )

    return CostBreakdown(
        physical_distance_m=physical_distance_m,
        accessibility_penalty_m=acc_penalty,
        terrain_penalty_m=terrain_penalty,
        uncertainty_penalty_m=unc_penalty,
        total_weighted_cost=total_cost,
        is_prohibited=False,
        findings=findings,
        community_observations=active_comm_obs,
    )


def make_policy_cost_func(
    graph: nx.MultiDiGraph, policy: RoutingPolicy
) -> Callable[[int, int, Dict[str, Any]], float]:
    """Generate an A*-compatible edge cost callable (u, v, edge_data) -> float.

    Evaluates edge attributes and destination node v attributes simultaneously.
    Returns infinite cost for prohibited transitions, or total weighted cost.
    Also handles NetworkX MultiDiGraph calls where edge_data is a dictionary of {key: data}.
    """
    def _eval_single(u: int, v: int, data: Dict[str, Any]) -> float:
        length = data.get("length")
        if length is None:
            return float("inf")
        try:
            phys_dist = float(length)
        except (ValueError, TypeError):
            return float("inf")

        if "_accessibility_evidence" in data and isinstance(
            data["_accessibility_evidence"], EdgeAccessibilityEvidence
        ):
            edge_ev = data["_accessibility_evidence"]
        else:
            edge_ev = extract_edge_evidence(data)

        node_v_data = graph.nodes.get(v, {})
        if "_accessibility_evidence" in node_v_data and isinstance(
            node_v_data["_accessibility_evidence"], NodeAccessibilityEvidence
        ):
            node_ev = node_v_data["_accessibility_evidence"]
        else:
            node_ev = extract_node_evidence(v, node_v_data)

        terrain_ev = data.get("terrain_evidence")
        if terrain_ev is None or not hasattr(terrain_ev, "signed_grade"):
            # Check if graph nodes have elevation_m for on-the-fly calculation
            elev_u = graph.nodes[u].get("elevation_m")
            elev_v = graph.nodes[v].get("elevation_m")
            if elev_u is not None and elev_v is not None:
                delta_z = float(elev_v) - float(elev_u)
                sg = delta_z / max(phys_dist, 0.1)
                from accessroute.scoring.models import EdgeTerrainEvidence, SlopeDirection
                terrain_ev = EdgeTerrainEvidence(
                    elevation_start_m=elev_u,
                    elevation_end_m=elev_v,
                    elevation_change_m=delta_z,
                    length_m=phys_dist,
                    signed_grade=sg,
                    absolute_grade=abs(sg),
                    direction=SlopeDirection.UPHILL if sg >= 0.02 else (SlopeDirection.DOWNHILL if sg <= -0.02 else SlopeDirection.FLAT),
                    is_known=True,
                )

        # Extract attached community observations from edge and node
        comm_obs = list(data.get("_community_observations", []))
        node_comm = list(node_v_data.get("_community_observations", []))
        all_comm = comm_obs + node_comm

        breakdown = evaluate_transition_cost(
            edge_evidence=edge_ev,
            node_evidence=node_ev,
            policy=policy,
            physical_distance_m=phys_dist,
            terrain_evidence=terrain_ev,
            community_observations=all_comm,
        )
        return breakdown.total_weighted_cost

    def cost_func(u: int, v: int, edge_data: Dict[str, Any]) -> float:
        if not edge_data:
            return float("inf")

        # Detect if NetworkX passed a MultiDiGraph dictionary of {key: edge_data}
        first_val = next(iter(edge_data.values()))
        if isinstance(first_val, dict) and "length" in first_val:
            best_cost = float("inf")
            for sub_data in edge_data.values():
                c = _eval_single(u, v, sub_data)
                if c < best_cost:
                    best_cost = c
            return best_cost

        return _eval_single(u, v, edge_data)

    return cost_func

