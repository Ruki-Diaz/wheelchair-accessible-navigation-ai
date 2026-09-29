"""Route Evidence Quality and Confidence Analyzer.

Stage 10 Architecture:
Computes factual data quality summaries along calculated routes.

CRITICAL SCIENTIFIC SAFETY RULE:
Describes evidence completeness and metadata quality — NEVER states '87% accessible'.
Provides transparent metrics across strong, partial, and limited evidence coverage.
"""

from typing import Any, Dict, List, Optional
from accessroute.intelligence.models import RouteEvidenceQuality
from accessroute.scoring.models import KerbType, SurfaceType


class RouteEvidenceQualityAnalyzer:
    """Evaluates the data completeness and empirical backing of a calculated route."""

    @staticmethod
    def analyze_route_evidence(route_result: Any) -> RouteEvidenceQuality:
        """Calculate evidence quality metrics for a RouteResult or CoordinatedRouteResult."""
        # Handle both RouteResult and CoordinatedRouteResult
        route = getattr(route_result, "route", route_result)
        edges = getattr(route, "edges", [])

        total_dist_m = max(0.1, float(getattr(route, "total_distance_meters", 0.0)))
        if total_dist_m <= 0.1 and edges:
            total_dist_m = sum(float(e.get("length", 0.0)) for e in edges)

        strong_dist = 0.0
        partial_dist = 0.0
        limited_dist = 0.0

        unknown_kerbs = 0
        unknown_surf_dist = 0.0
        unrecorded_elev_dist = 0.0
        comm_supported = 0
        conflicts_count = 0
        stale_count = 0

        for edge in edges:
            length = float(edge.get("length", 0.0))
            ev = edge.get("_accessibility_evidence")
            comm_list = edge.get("_community_observations", [])

            # Check community support and conflicts
            for obs in comm_list:
                status = getattr(obs, "verification_status", None)
                stat_val = status.value if hasattr(status, "value") else str(status)
                if stat_val in ("community_supported", "verified"):
                    comm_supported += 1
                elif stat_val == "community_disputed":
                    conflicts_count += 1
                elif stat_val == "stale":
                    stale_count += 1

            # Check surface
            surf = str(edge.get("surface", "unknown")).lower()
            surf_known = (ev and ev.surface != SurfaceType.UNKNOWN) or (surf not in ("unknown", "none", "nan", ""))
            if not surf_known:
                unknown_surf_dist += length

            # Check kerb at crossings
            hw = str(edge.get("highway", "")).lower()
            is_cross = bool(edge.get("is_crossing")) or hw == "crossing"
            kerb = str(edge.get("kerb", "unknown")).lower()
            kerb_known = (ev and ev.kerb != KerbType.UNKNOWN) or (kerb not in ("unknown", "none", "nan", ""))
            if is_cross and not kerb_known:
                unknown_kerbs += 1

            # Check elevation
            elev_src = str(edge.get("elevation_source", "UNKNOWN"))
            elev_known = elev_src != "UNKNOWN" or edge.get("absolute_grade") is not None
            if not elev_known:
                unrecorded_elev_dist += length

            # Evidence level classification for this segment
            # Strong: Known surface + known elevation + (known kerb if crossing)
            if surf_known and elev_known and (not is_cross or kerb_known):
                strong_dist += length
            # Partial: At least surface or elevation known
            elif surf_known or elev_known:
                partial_dist += length
            else:
                limited_dist += length

        strong_pct = (strong_dist / total_dist_m) * 100.0
        partial_pct = (partial_dist / total_dist_m) * 100.0
        limited_pct = (limited_dist / total_dist_m) * 100.0

        if strong_pct >= 75.0:
            quality_band = "HIGH_EVIDENCE_COVERAGE"
        elif strong_pct >= 40.0:
            quality_band = "MODERATE_EVIDENCE_COVERAGE"
        else:
            quality_band = "LIMITED_EVIDENCE_COVERAGE"

        summary_notes: List[str] = []
        summary_notes.append(f"Strong evidence recorded for {strong_pct:.0f}% of total route distance.")
        if unknown_kerbs > 0:
            summary_notes.append(f"{unknown_kerbs} road crossing(s) lack recorded kerb ramp data.")
        if unknown_surf_dist > 1.0:
            summary_notes.append(f"{unknown_surf_dist:.0f}m of path has unrecorded surface material.")
        if comm_supported > 0:
            summary_notes.append(f"{comm_supported} community-supported observation(s) active on this route.")
        if conflicts_count > 0:
            summary_notes.append(f"{conflicts_count} active evidence conflict(s) flagged along this path.")

        return RouteEvidenceQuality(
            total_distance_m=total_dist_m,
            strong_evidence_distance_m=strong_dist,
            strong_evidence_pct=strong_pct,
            partial_evidence_distance_m=partial_dist,
            partial_evidence_pct=partial_pct,
            limited_evidence_distance_m=limited_dist,
            limited_evidence_pct=limited_pct,
            unknown_kerbs_count=unknown_kerbs,
            unknown_surface_distance_m=unknown_surf_dist,
            unrecorded_elevation_distance_m=unrecorded_elev_dist,
            community_supported_count=comm_supported,
            conflicting_evidence_count=conflicts_count,
            stale_observations_count=stale_count,
            quality_band=quality_band,
            summary_notes=summary_notes,
        )
