"""Entrance Evidence Aggregation and Provenance Tracker.

Stage 13 Architecture:
Combines OpenStreetMap baseline data with community observations (Stage 9-10),
venue-provided data, and system-derived approach metrics.
Maintains multi-source provenance: community reports never silently overwrite
OSM tags; conflicting observations remain independently visible with expiration tracking.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.repository import CommunityObservationRepository
from accessroute.destinations.models import (
    Entrance,
    EntranceAccessibilityEvidence,
    EvidenceProvenance,
)

logger = logging.getLogger(__name__)


class EntranceEvidenceCollector:
    """Aggregates multi-source evidence for an entrance while preserving provenance."""

    def __init__(self, community_repo: Optional[CommunityObservationRepository] = None) -> None:
        self.community_repo = community_repo

    def enrich_entrance_evidence(
        self,
        entrance: Entrance,
        now: Optional[datetime] = None,
        observations: Optional[List[CommunityObservation]] = None,
    ) -> Entrance:
        """Enrich an entrance with recent community observations and detect conflicts."""
        current_time = now or datetime.now(timezone.utc)

        if observations is not None:
            nearby_obs = observations
        elif self.community_repo:
            # 1. Fetch community observations within 35m of entrance point
            try:
                nearby_obs = self.community_repo.get_nearby(
                    latitude=entrance.latitude,
                    longitude=entrance.longitude,
                    radius_m=35.0,
                    include_expired=False,
                )
            except Exception as exc:
                logger.warning("Could not query community observations for entrance %s: %s", entrance.id, exc)
                nearby_obs = []
        else:
            return entrance

        active_conflicts: List[str] = []
        community_ids: List[str] = []
        is_temporarily_closed = False
        temporary_closure_reason = ""
        lift_out_of_service = False
        steps_reported = False

        for obs in nearby_obs:
            if not obs.is_active(current_time):
                continue

            community_ids.append(obs.id)

            # Check for temporary obstacle or closure
            if obs.category in [
                ObservationCategory.PATH_BLOCKED,
                ObservationCategory.TEMPORARY_OBSTACLE,
                ObservationCategory.CONSTRUCTION,
            ]:
                if obs.value in ["construction", "roadworks", "scaffolding", "footpath_closed", "temporary_closure"]:
                    is_temporarily_closed = True
                    temporary_closure_reason = f"Community report indicates temporary entrance blockage ({obs.value}): {obs.notes or 'No details'}"
                    active_conflicts.append(temporary_closure_reason)

            # Check for entrance accessibility reports
            elif obs.category == ObservationCategory.ENTRANCE_ACCESSIBILITY:
                val = obs.value.lower()
                if val in ["inaccessible", "steps_only", "temporary_closure", "steps_present", "lift_unavailable"]:
                    if val == "temporary_closure":
                        is_temporarily_closed = True
                        temporary_closure_reason = f"Community report indicates temporary entrance closure: {obs.notes or 'Closed'}"
                    elif val == "lift_unavailable":
                        lift_out_of_service = True
                    steps_reported = True
                    active_conflicts.append(f"Community report indicates entrance issue: {val}")
                elif val in ["level_entry", "ramped", "step_free"]:
                    if entrance.evidence.step_free is False:
                        active_conflicts.append("Community report reports step-free entry conflicting with mapped stairs")

            # Check lift status
            elif obs.category == ObservationCategory.LIFT_STATUS:
                if obs.value in ["out_of_service", "broken", "lift_unavailable"]:
                    lift_out_of_service = True
                    active_conflicts.append("Community report indicates elevator/lift is out of service")

            # Check steps
            elif obs.category == ObservationCategory.STAIRS:
                if obs.value in ["present", "without_ramp", "steps_present"]:
                    steps_reported = True
                    active_conflicts.append("Community report indicates steps at entrance")

        # 2. Update entrance evidence non-destructively
        updated_evidence = EntranceAccessibilityEvidence.from_dict(entrance.evidence.to_dict())
        updated_evidence.community_observation_ids = community_ids

        # Track sources
        sources = list(entrance.provenance_sources)
        if community_ids and EvidenceProvenance.COMMUNITY_OBSERVATION not in sources:
            sources.append(EvidenceProvenance.COMMUNITY_OBSERVATION)

        # Flag temporary conditions
        if is_temporarily_closed:
            updated_evidence.is_temporary = True
            updated_evidence.notes = temporary_closure_reason
        elif lift_out_of_service:
            updated_evidence.lift_access = "out_of_service"
            updated_evidence.is_temporary = True

        entrance.evidence = updated_evidence
        entrance.provenance_sources = sources
        entrance.community_reports_count = len(community_ids)
        entrance.active_conflicts = active_conflicts

        return entrance

    @staticmethod
    def compute_completeness_summary(entrance: Entrance) -> Dict[str, Any]:
        """Compute structured completeness statistics and human-readable breakdown."""
        breakdown = entrance.evidence_completeness
        total_fields = len(breakdown)
        recorded_fields = sum(1 for status in breakdown.values() if status == "recorded")
        percentage = round((recorded_fields / total_fields) * 100.0, 1) if total_fields > 0 else 0.0

        return {
            "percentage": percentage,
            "recorded_count": recorded_fields,
            "total_count": total_fields,
            "breakdown": breakdown,
            "sources": [s.value if isinstance(s, EvidenceProvenance) else str(s) for s in entrance.provenance_sources],
            "community_reports_count": entrance.community_reports_count,
            "conflicts_count": len(entrance.active_conflicts),
        }
