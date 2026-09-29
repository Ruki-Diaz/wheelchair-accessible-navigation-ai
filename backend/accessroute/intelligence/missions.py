"""Verification Missions Generator.

Stage 10 Architecture:
Transforms high-impact verification opportunities and stale evidence into actionable
community tasks without gamification or points.
Directly connects into the Stage 9 reporting infrastructure.
"""

from typing import Any, Dict, List, Optional
import networkx as nx

from accessroute.community.models import ObservationCategory
from accessroute.intelligence.models import (
    PriorityLevel,
    VerificationMission,
    VerificationPriorityAssessment,
)


class VerificationMissionEngine:
    """Generates structured, explainable verification missions for community contributors."""

    @staticmethod
    def create_mission_from_priority(
        priority: VerificationPriorityAssessment,
        graph: Optional[nx.MultiDiGraph] = None,
    ) -> VerificationMission:
        """Convert a prioritized verification opportunity into an actionable mission."""
        missing = priority.missing_attribute.lower()
        feature = priority.feature_type.lower()

        # Determine user-facing title and suggested actions
        if missing == "kerb":
            title = "Check Kerb Ramp at Crossing"
            category = ObservationCategory.KERB
            suggested = ["lowered", "flush", "raised", "no_kerb", "unable_to_verify"]
            action_desc = "Verify whether this crossing has dropped kerb ramps for wheelchair access."
        elif missing == "surface":
            title = "Check Footpath Surface"
            category = ObservationCategory.SURFACE
            suggested = ["asphalt", "concrete", "paved", "gravel", "dirt", "cobblestone"]
            action_desc = "Check the ground material of this footpath to verify rolling resistance."
        elif missing == "width":
            title = "Check Path Width"
            category = ObservationCategory.PATH_WIDTH
            suggested = ["adequate", "narrow", "impassable"]
            action_desc = "Check if clear width allows passage for powered wheelchairs and prams."
        elif missing in ["stairs", "entrance_step_free"]:
            title = "Check Step-Free Ramp"
            category = ObservationCategory.RAMP
            suggested = ["present", "absent", "wheelchair_designated", "too_steep"]
            action_desc = "Verify if a ramp bypass exists for this flight of steps."
        elif missing in ["entrance", "entrance_accessibility"]:
            title = "Check Entrance Step-Free Access"
            category = ObservationCategory.ENTRANCE_ACCESSIBILITY
            suggested = ["step_free", "steps_present", "ramp_present", "inaccessible"]
            action_desc = "Check whether this venue entrance is step-free or has stairs."
        elif missing in ["door_width", "entrance_width"]:
            title = "Measure Entrance Door Width"
            category = ObservationCategory.ENTRANCE_ACCESSIBILITY
            suggested = ["door_width", "adequate", "narrow"]
            action_desc = "Measure clear door width to verify passage for motorized wheelchairs."
        elif missing in ["automatic_door", "entrance_door"]:
            title = "Check Entrance Automatic Doors"
            category = ObservationCategory.ENTRANCE_ACCESSIBILITY
            suggested = ["automatic_door", "manual_door"]
            action_desc = "Check whether automatic push-button or motion sensor doors are operational."
        elif missing in ["entrance_lift", "lift_access"]:
            title = "Verify Entrance Lift Access"
            category = ObservationCategory.LIFT_STATUS
            suggested = ["operational", "out_of_service", "unknown"]
            action_desc = "Verify if elevator or platform lift to entrance is currently operational."
        elif missing in ["entrance_closure", "temporary_closure"]:
            title = "Check Entrance Temporary Closure"
            category = ObservationCategory.TEMPORARY_OBSTACLE
            suggested = ["temporary_closure", "roadworks", "footpath_closed"]
            action_desc = "Verify whether this entrance is temporarily closed or blocked by construction."
        else:
            title = f"Verify {missing.capitalize()} Accessibility"
            category = ObservationCategory.OTHER
            suggested = ["verified", "inaccessible", "other"]
            action_desc = "Check accessibility infrastructure at this location."

        # Compile concise "why it matters" explanation
        impact = priority.impact_details
        if impact and impact.routes_traversing_count > 0:
            why = (
                f"This location appears on {impact.percentage_of_sampled_routes:.0f}% of sampled routes. "
                f"Verifying this prevents up to {impact.max_detour_distance_m:.0f}m detours for wheelchair users."
            )
        elif priority.reasons:
            why = priority.reasons[0]
        else:
            why = action_desc

        est_impact = impact.max_detour_distance_m if impact else 50.0

        return VerificationMission(
            id=f"mission_{priority.id}",
            title=title,
            location_name=f"{feature.capitalize()} #{priority.osm_element_id}",
            latitude=priority.latitude,
            longitude=priority.longitude,
            osm_element_type=priority.osm_element_type,
            osm_element_id=priority.osm_element_id,
            category=category,
            missing_attribute=priority.missing_attribute,
            why_it_matters=why,
            suggested_actions=suggested,
            priority_level=priority.priority_level,
            estimated_impact_m=est_impact,
        )

    @classmethod
    def generate_missions(
        cls,
        priorities: List[VerificationPriorityAssessment],
        graph: Optional[nx.MultiDiGraph] = None,
        limit: int = 20,
    ) -> List[VerificationMission]:
        """Generate a ranked batch of community verification missions."""
        missions: List[VerificationMission] = []
        for p in priorities[:limit]:
            m = cls.create_mission_from_priority(p, graph)
            missions.append(m)
        return missions
