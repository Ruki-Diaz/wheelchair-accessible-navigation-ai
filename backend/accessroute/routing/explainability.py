"""Deterministic, reproducible route explanation engine.

Generates factual, evidence-backed route rationales without relying on language models.
Strictly bases all explanation statements on confirmed graph attributes, route findings,
and comparisons against baseline distance paths.
"""

from typing import Any, Dict, List, Optional, Set
from accessroute.scoring.models import FindingType


def generate_route_explanation(
    route_metrics: Dict[str, Any],
    findings: Set[str],
    baseline_metrics: Optional[Dict[str, Any]] = None,
    policy_name: str = "balanced",
    preferences: Optional[Any] = None,  # MobilityPreferences
) -> List[str]:
    """Generate deterministic factual explanations for a calculated route.

    Args:
        route_metrics: Dictionary of aggregated route metrics (distance, crossings, surfaces, etc.)
        findings: Set of finding strings encountered along the path.
        baseline_metrics: Optional metrics from the unconstrained shortest baseline path.
        policy_name: Name of the active routing policy.

    Returns:
        List of factual, transparent explanation sentences.
    """
    explanations: List[str] = []

    # 1. Comparison with Baseline Shortest Route (Why did the route divert?)
    if baseline_metrics:
        base_dist = baseline_metrics.get("physical_distance_m", 0.0)
        curr_dist = route_metrics.get("physical_distance_m", 0.0)
        dist_diff = curr_dist - base_dist

        base_findings = set(baseline_metrics.get("findings", []))
        curr_findings = set(findings)

        # Did the accessible route avoid steps present on baseline?
        if (
            FindingType.STEPS_PRESENT.value in base_findings
            and FindingType.STEPS_PRESENT.value not in curr_findings
        ):
            if preferences and getattr(preferences, "steps", None) and str(getattr(preferences.steps, "value", preferences.steps)) == "never":
                explanations.append(
                    f"You selected 'Never use mapped stairs'. This route avoids the mapped staircase used by the shorter path (adds {dist_diff:.1f}m)."
                )
            else:
                explanations.append(
                    f"Route diverts around outdoor stairs found on the shortest path (adds {dist_diff:.1f}m)."
                )

        # Did the route avoid wheelchair=no?
        if (
            FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED.value in base_findings
            and FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED.value not in curr_findings
        ):
            explanations.append(
                "Route actively avoids a segment where wheelchair access is explicitly prohibited."
            )

        # Did the route avoid a community reported blocked footpath or construction?
        if (
            (
                FindingType.COMMUNITY_PATH_BLOCKED.value in base_findings
                or FindingType.COMMUNITY_CONSTRUCTION_REPORTED.value in base_findings
            )
            and FindingType.COMMUNITY_PATH_BLOCKED.value not in curr_findings
        ):
            explanations.append(
                "Route avoids a footpath currently reported blocked by construction."
            )

        # Did the route avoid unpaved surfaces?
        if (
            FindingType.UNPAVED_SURFACE_RECORDED.value in base_findings
            and FindingType.UNPAVED_SURFACE_RECORDED.value not in curr_findings
        ):
            if preferences and getattr(preferences, "unpaved_surfaces", None) and str(getattr(preferences.unpaved_surfaces, "value", preferences.unpaved_surfaces)) in ("prefer_avoid", "strictly_avoid"):
                explanations.append(
                    f"You selected to avoid unpaved surfaces. This route chooses paved pathways instead of gravel/dirt (adds {dist_diff:.1f}m)."
                )
            else:
                explanations.append(
                    f"Route avoids unpaved/gravel surfaces in favor of paved pathways (adds {dist_diff:.1f}m)."
                )

        # Did the route avoid a steep uphill section on the baseline?
        base_max_up = baseline_metrics.get("max_uphill_grade_pct", 0.0)
        curr_max_up = route_metrics.get("max_uphill_grade_pct", 0.0)
        if base_max_up >= 6.0 and curr_max_up < base_max_up - 1.5:
            if preferences and getattr(preferences, "max_preferred_uphill_grade_pct", None):
                pref_up = preferences.max_preferred_uphill_grade_pct
                explanations.append(
                    f"You selected a preferred uphill slope of ≤{pref_up:.1f}%. This route reduces maximum estimated uphill grade from {base_max_up:.1f}% to {curr_max_up:.1f}%."
                )
            else:
                explanations.append(
                    f"Route avoids a steep uphill slope (reduces maximum estimated uphill grade from {base_max_up:.1f}% to {curr_max_up:.1f}%)."
                )

        # General detour note if distance increased without known major barrier
        if dist_diff > 1.0 and not explanations:
            explanations.append(
                f"Route follows a path with stronger available accessibility evidence, adding {dist_diff:.1f}m compared to the shortest baseline path."
            )
        elif dist_diff <= 0.05 and not explanations:
            explanations.append(
                "The accessibility-aware route coincides with the shortest physical walking path based on available evidence."
            )

    # 2. Surface Infrastructure Explanations
    paved_pct = route_metrics.get("paved_distance_pct", 0.0)
    unpaved_count = route_metrics.get("unpaved_segments_count", 0)
    unknown_surface_count = route_metrics.get("unknown_surface_segments_count", 0)

    if paved_pct >= 95.0:
        explanations.append(
            f"Recorded as paved surfaces (concrete/asphalt) for {paved_pct:.0f}% of route distance."
        )
    elif unpaved_count > 0:
        explanations.append(
            f"Includes {unpaved_count} unpaved segment(s) recorded in OpenStreetMap (gravel, dirt, or natural ground)."
        )

    if unknown_surface_count > 0:
        explanations.append(
            f"Surface material is unrecorded in OpenStreetMap for {unknown_surface_count} segment(s)."
        )

    # 3. Kerbs & Crossings
    crossings_count = route_metrics.get("crossings_count", 0)
    crossings_without_kerb = route_metrics.get("crossings_without_kerb_info_count", 0)
    raised_kerbs = route_metrics.get("raised_kerbs_count", 0)
    lowered_kerbs = route_metrics.get("lowered_kerbs_count", 0)

    if crossings_count > 0:
        if crossings_without_kerb == crossings_count:
            explanations.append(
                f"Traverses {crossings_count} road crossing(s); kerb ramp availability is unrecorded in map data."
            )
        elif crossings_without_kerb > 0:
            explanations.append(
                f"Traverses {crossings_count} road crossing(s) ({crossings_without_kerb} lack recorded kerb ramp data)."
            )
        else:
            explanations.append(
                f"Recorded kerb data is available for all {crossings_count} road crossing(s)."
            )

    if lowered_kerbs > 0:
        explanations.append(
            f"Ramped or flush kerbs recorded at {lowered_kerbs} transition point(s)."
        )

    if raised_kerbs > 0:
        explanations.append(
            f"Caution: Encountered {raised_kerbs} recorded raised kerb(s)."
        )

    # 4. Incline, Steps, and Terrain Intelligence
    gain_m = route_metrics.get("elevation_gain_m", 0.0)
    loss_m = route_metrics.get("elevation_loss_m", 0.0)
    max_up = route_metrics.get("max_uphill_grade_pct", 0.0)
    max_down = route_metrics.get("max_downhill_grade_pct", 0.0)
    known_elev_pct = route_metrics.get("known_elevation_pct", 100.0)

    if gain_m > 1.0 or loss_m > 1.0 or max_up > 2.0:
        explanations.append(
            f"Elevation profile: +{gain_m:.1f}m climb, -{loss_m:.1f}m descent (max estimated uphill grade: {max_up:.1f}%)."
        )

    if FindingType.STEPS_PRESENT.value in findings:
        explanations.append("Warning: Route contains recorded outdoor stairs.")
    if FindingType.STEEP_UPHILL_RECORDED.value in findings:
        explanations.append(f"Warning: Route includes estimated steep uphill sections (up to {max_up:.1f}% grade).")
    elif FindingType.STEEP_INCLINE_RECORDED.value in findings:
        explanations.append("Warning: Route includes recorded steep slope sections.")

    if FindingType.STEEP_DOWNHILL_RECORDED.value in findings:
        explanations.append(f"Caution: Route includes estimated steep downhill descent (grade {max_down:.1f}%).")

    # 5. Missing Data & Uncertainty Summary
    missing_data_pct = route_metrics.get("missing_data_pct", 0.0)
    if missing_data_pct > 50.0:
        explanations.append(
            f"Data notice: Accessibility metadata is incomplete for {missing_data_pct:.0f}% of this route."
        )

    if known_elev_pct < 85.0:
        explanations.append(
            f"Terrain notice: Elevation data is unrecorded for {100.0 - known_elev_pct:.0f}% of route distance."
        )

    # 6. Community Evidence & Conflict Notices
    if FindingType.COMMUNITY_PATH_BLOCKED.value in findings:
        explanations.append(
            "Caution: Route traverses a segment with an active community report of a path obstruction."
        )
    if FindingType.COMMUNITY_UNVERIFIED_OBSTACLE.value in findings:
        explanations.append(
            "Caution: One or more unverified community reports indicate potential obstacles along this route."
        )
    if FindingType.COMMUNITY_CONFLICT_FLAGGED.value in findings:
        explanations.append(
            "Notice: Community reports conflict with OpenStreetMap information along one or more segments."
        )

    return explanations
