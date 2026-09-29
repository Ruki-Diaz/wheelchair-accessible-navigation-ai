"""Deterministic Entrance and Destination Assessment Engine.

Stage 13 Architecture:
Evaluates entrance options against user MobilityPreferences (Stage 8) without
opaque AI scoring or silent relaxation.
Produces factual, evidence-based classifications:
- MATCHES_CURRENT_PREFERENCES
- PARTIALLY_VERIFIED
- INSUFFICIENT_EVIDENCE
- CONFLICTING_EVIDENCE
- DOES_NOT_MATCH_CURRENT_PREFERENCES
- TEMPORARILY_REPORTED_UNAVAILABLE
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from accessroute.destinations.models import (
    Destination,
    DestinationAssessment,
    Entrance,
    EntranceAssessment,
    EntranceAssessmentStatus,
    EntranceType,
    Venue,
)
from accessroute.preferences.models import MobilityPreferences, StepPreference

logger = logging.getLogger(__name__)


class EntranceAssessmentEngine:
    """Evaluates entrances against user MobilityPreferences using strict, deterministic criteria."""

    @classmethod
    def assess_entrance(
        cls,
        entrance: Entrance,
        preferences: MobilityPreferences,
        route_summary: Optional[Dict[str, Any]] = None,
    ) -> EntranceAssessment:
        """Assess an individual entrance against user mobility constraints."""
        ev = entrance.evidence
        matching: List[str] = []
        blocking: List[str] = []
        warnings: List[str] = []
        missing: List[str] = []

        # 1. Check temporary closure / blockage
        if ev.is_temporary and (not ev.notes or any(w in ev.notes.lower() for w in ["closed", "closure", "blockage", "blocked", "out_of_service", "broken", "unavailable"])):
            blocking.append(f"Entrance is temporarily unavailable: {ev.notes or 'Temporary closure reported.'}")
            return EntranceAssessment(
                entrance_id=entrance.id,
                entrance_name=entrance.name,
                entrance_type=entrance.entrance_type,
                status=EntranceAssessmentStatus.TEMPORARILY_REPORTED_UNAVAILABLE,
                matching_reasons=[],
                blocking_reasons=blocking,
                warning_reasons=warnings,
                missing_attributes=[],
                route_summary=route_summary,
                combined_summary="Temporarily reported unavailable due to active blockage or closure.",
            )

        # 2. Check conflicts
        if entrance.active_conflicts:
            for conflict in entrance.active_conflicts:
                warnings.append(f"Conflicting community evidence: {conflict}")

        # 3. Check steps and stair constraints
        stairs_prohibited = (
            getattr(preferences, "stairs_prohibited", False)
            or getattr(preferences, "steps", None) in [StepPreference.NEVER, "never"]
        )
        if stairs_prohibited:
            if ev.step_free is False or (ev.steps_count is not None and ev.steps_count > 0 and ev.ramp != "yes"):
                steps_desc = f"{ev.steps_count} steps" if ev.steps_count else "Mapped stairs"
                blocking.append(f"{steps_desc} recorded at entrance without ramp bypass, and your preferences prohibit stairs.")
            elif ev.step_free is True:
                matching.append("Step-free entrance recorded.")
            elif ev.ramp == "yes":
                matching.append("Ramp bypass recorded for entrance.")
            else:
                missing.append("Step-free status unrecorded.")
                warnings.append("Entrance has unrecorded stair / step status.")
        else:
            if ev.step_free is True:
                matching.append("Step-free access recorded.")

        # 4. Check door width constraints
        min_width = getattr(preferences, "minimum_path_width_m", None) or getattr(preferences, "min_path_width_m", None)
        if min_width is not None and min_width > 0:
            if ev.door_width_m is not None:
                if ev.door_width_m < min_width:
                    blocking.append(
                        f"Recorded door width ({ev.door_width_m:.2f}m) is narrower than your required width ({min_width:.2f}m)."
                    )
                else:
                    matching.append(f"Door width ({ev.door_width_m:.2f}m) meets your required width ({min_width:.2f}m).")
            else:
                missing.append("Door clear width unrecorded.")
                warnings.append(f"Clear door width is not recorded (your preference requires ≥ {min_width:.2f}m).")

        # 5. Check automatic door preference
        if ev.automatic_door is True:
            matching.append("Automatic power doors recorded.")
        elif ev.automatic_door is False:
            warnings.append("Manual door recorded (not automatic).")
        else:
            missing.append("Door automation type unrecorded.")

        # 6. Check wheelchair designation
        if ev.wheelchair == "yes":
            matching.append("Designated wheelchair-accessible entrance.")
        elif ev.wheelchair == "no":
            if not blocking:
                blocking.append("Marked in OpenStreetMap as not wheelchair accessible.")
        elif ev.wheelchair == "limited":
            warnings.append("Marked as having limited accessibility (assistance may be required).")

        # 7. Check elevator / lift status if multi-level
        if ev.lift_access == "out_of_service":
            blocking.append("Elevator / lift to entrance is reported out of service.")
        elif ev.lift_access == "operational":
            matching.append("Elevator / lift access is operational.")

        # 8. Check approach route if provided
        if route_summary:
            if not route_summary.get("found", True):
                blocking.append("No accessible pedestrian path could be found from your origin to this entrance.")
            else:
                route_dist = route_summary.get("physical_distance_m", 0)
                matching.append(f"Accessible path found to entrance approach ({route_dist:.0f}m).")

        # Determine overall classification
        if blocking:
            status = EntranceAssessmentStatus.DOES_NOT_MATCH_CURRENT_PREFERENCES
            combined_summary = f"Does not match preferences: {blocking[0]}"
        elif entrance.active_conflicts:
            status = EntranceAssessmentStatus.CONFLICTING_EVIDENCE
            combined_summary = f"Conflicting evidence present ({len(entrance.active_conflicts)} active conflicts)."
        elif missing and len(matching) == 0:
            status = EntranceAssessmentStatus.INSUFFICIENT_EVIDENCE
            combined_summary = "Insufficient accessibility evidence recorded for this entrance."
        elif missing and len(matching) > 0:
            status = EntranceAssessmentStatus.PARTIALLY_VERIFIED
            combined_summary = f"Partially verified: {', '.join(matching[:2])}, with {len(missing)} unrecorded attributes."
        else:
            status = EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES
            combined_summary = "Entrance accessibility evidence matches your current preferences."

        return EntranceAssessment(
            entrance_id=entrance.id,
            entrance_name=entrance.name,
            entrance_type=entrance.entrance_type,
            status=status,
            matching_reasons=matching,
            blocking_reasons=blocking,
            warning_reasons=warnings,
            missing_attributes=missing,
            route_summary=route_summary,
            combined_summary=combined_summary,
        )

    @classmethod
    def assess_destination_venue(
        cls,
        destination: Destination,
        preferences: MobilityPreferences,
        route_summaries_by_entrance: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> DestinationAssessment:
        """Assess all candidate entrances of a destination venue and produce a ranked evaluation."""
        if not destination.is_venue or not destination.venue or not destination.venue.entrances:
            headline = "No Entrance Information" if destination.is_venue else "Standard Destination"
            explanation = (
                "No entrance accessibility information is currently recorded for this destination."
                if destination.is_venue
                else "Standard address destination; routing directly to destination point."
            )
            return DestinationAssessment(
                destination_id=destination.id,
                destination_name=destination.name,
                is_venue=bool(destination.is_venue),
                entrances_count=0,
                recommended_entrance_id=None,
                entrance_assessments=[],
                has_matching_entrance=False,
                summary_headline=headline,
                summary_explanation=explanation,
            )

        venue = destination.venue
        route_map = route_summaries_by_entrance or {}
        assessments: List[EntranceAssessment] = []

        for ent in venue.entrances:
            r_sum = route_map.get(ent.id)
            ass = cls.assess_entrance(ent, preferences, route_summary=r_sum)
            assessments.append(ass)

        # Deterministic ranking:
        # 1. MATCHES_CURRENT_PREFERENCES
        # 2. PARTIALLY_VERIFIED
        # 3. INSUFFICIENT_EVIDENCE
        # 4. CONFLICTING_EVIDENCE
        # 5. DOES_NOT_MATCH_CURRENT_PREFERENCES
        # 6. TEMPORARILY_REPORTED_UNAVAILABLE
        rank_order = {
            EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES: 0,
            EntranceAssessmentStatus.PARTIALLY_VERIFIED: 1,
            EntranceAssessmentStatus.INSUFFICIENT_EVIDENCE: 2,
            EntranceAssessmentStatus.CONFLICTING_EVIDENCE: 3,
            EntranceAssessmentStatus.DOES_NOT_MATCH_CURRENT_PREFERENCES: 4,
            EntranceAssessmentStatus.TEMPORARILY_REPORTED_UNAVAILABLE: 5,
        }

        # Sort assessments by rank order, then route distance if available
        def sort_key(a: EntranceAssessment):
            r_rank = rank_order.get(a.status, 99)
            dist = a.route_summary.get("physical_distance_m", 999999.0) if a.route_summary else 999999.0
            return (r_rank, dist)

        sorted_assessments = sorted(assessments, key=sort_key)

        recommended_id = None
        has_matching = False
        matching_count = sum(
            1 for a in sorted_assessments
            if a.status in [EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES, EntranceAssessmentStatus.PARTIALLY_VERIFIED]
        )

        if matching_count > 0:
            recommended_id = sorted_assessments[0].entrance_id
            has_matching = True
            headline = f"✓ {matching_count} entrance option{'s' if matching_count > 1 else ''} matching your preferences"
            explanation = f"Recommended entrance: {sorted_assessments[0].entrance_name}."
        else:
            headline = "⚠ No entrance fully matching your current accessibility preferences"
            explanation = "Available entrances have recorded barriers, active closures, or missing data."

        return DestinationAssessment(
            destination_id=destination.id,
            destination_name=destination.name,
            is_venue=True,
            entrances_count=len(venue.entrances),
            recommended_entrance_id=recommended_id,
            entrance_assessments=sorted_assessments,
            has_matching_entrance=has_matching,
            summary_headline=headline,
            summary_explanation=explanation,
        )
