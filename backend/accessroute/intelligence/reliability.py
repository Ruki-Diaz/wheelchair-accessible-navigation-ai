"""Evidence Reliability and Temporal Decay Engine.

Stage 10 Architecture:
1. Evaluates evidence reliability using transparent, observable factors:
   - Independent peer confirmations
   - Disputes
   - Observation age and category-specific decay policies
   - Agreement / disagreement with OpenStreetMap
2. Classifies reliability into explainable bands:
   - STRONG_COMMUNITY_EVIDENCE
   - MODERATE_EVIDENCE
   - LOW_EVIDENCE
   - CONFLICTING_EVIDENCE
   - STALE
3. Implements category-specific freshness policies without deleting historical data.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from accessroute.community.models import (
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.intelligence.models import (
    EvidenceReliabilityAssessment,
    FreshnessState,
    ReliabilityBand,
)
from accessroute.scoring.models import EdgeAccessibilityEvidence, KerbType, NodeAccessibilityEvidence, SurfaceType


@dataclass(frozen=True)
class CategoryFreshnessPolicy:
    """Configurable freshness thresholds in days for a specific infrastructure category."""
    active_days: float
    aging_days: float
    stale_days: float


# Category-specific freshness windows reflecting physical infrastructure longevity
FRESHNESS_POLICIES: Dict[ObservationCategory, CategoryFreshnessPolicy] = {
    ObservationCategory.KERB: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.SURFACE: CategoryFreshnessPolicy(active_days=180.0, aging_days=365.0, stale_days=365.0),
    ObservationCategory.PATH_WIDTH: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.STAIRS: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.RAMP: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.BARRIER: CategoryFreshnessPolicy(active_days=180.0, aging_days=365.0, stale_days=365.0),
    ObservationCategory.SLOPE: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.ENTRANCE_ACCESSIBILITY: CategoryFreshnessPolicy(active_days=365.0, aging_days=730.0, stale_days=730.0),
    ObservationCategory.CONSTRUCTION: CategoryFreshnessPolicy(active_days=14.0, aging_days=30.0, stale_days=30.0),
    ObservationCategory.PATH_BLOCKED: CategoryFreshnessPolicy(active_days=7.0, aging_days=14.0, stale_days=14.0),
    ObservationCategory.TEMPORARY_OBSTACLE: CategoryFreshnessPolicy(active_days=2.0, aging_days=7.0, stale_days=7.0),
    ObservationCategory.LIFT_STATUS: CategoryFreshnessPolicy(active_days=1.0, aging_days=2.0, stale_days=2.0),
    ObservationCategory.OTHER: CategoryFreshnessPolicy(active_days=90.0, aging_days=180.0, stale_days=180.0),
}


class EvidenceReliabilityEngine:
    """Computes transparent reliability and freshness assessments for accessibility observations."""

    @staticmethod
    def evaluate_freshness(
        observation: CommunityObservation,
        now: Optional[datetime] = None,
    ) -> Tuple[FreshnessState, str]:
        """Determine the temporal decay state of an observation based on its category."""
        current_time = now or datetime.now(timezone.utc)
        rep_time = (
            observation.reported_at.replace(tzinfo=timezone.utc)
            if observation.reported_at.tzinfo is None
            else observation.reported_at
        )
        age_days = max(0.0, (current_time - rep_time).total_seconds() / 86400.0)

        # 1. Temporary conditions check operational expiration first
        if observation.is_temporary and observation.expires_at is not None:
            exp_time = (
                observation.expires_at.replace(tzinfo=timezone.utc)
                if observation.expires_at.tzinfo is None
                else observation.expires_at
            )
            if current_time > exp_time:
                return FreshnessState.EXPIRED, f"Temporary condition expired {int((current_time - exp_time).total_seconds() / 3600)} hours ago."

        # 2. Retrieve category decay policy
        policy = FRESHNESS_POLICIES.get(
            observation.category,
            CategoryFreshnessPolicy(active_days=90.0, aging_days=180.0, stale_days=180.0),
        )

        if age_days <= policy.active_days:
            return FreshnessState.ACTIVE, f"Recent observation ({int(age_days)} days old, within {int(policy.active_days)}d active window)."
        elif age_days <= policy.aging_days:
            return FreshnessState.AGING, f"Aging observation ({int(age_days)} days old; nearing {int(policy.aging_days)}d staleness threshold)."
        else:
            return FreshnessState.STALE, f"Stale observation ({int(age_days)} days old exceeds {int(policy.stale_days)}d staleness policy; re-verification needed)."

    @classmethod
    def evaluate_reliability(
        cls,
        observation: CommunityObservation,
        osm_edge_evidence: Optional[EdgeAccessibilityEvidence] = None,
        osm_node_evidence: Optional[NodeAccessibilityEvidence] = None,
        now: Optional[datetime] = None,
    ) -> EvidenceReliabilityAssessment:
        """Deterministically assess observation reliability and compile human-readable reasons."""
        current_time = now or datetime.now(timezone.utc)
        rep_time = (
            observation.reported_at.replace(tzinfo=timezone.utc)
            if observation.reported_at.tzinfo is None
            else observation.reported_at
        )
        age_days = max(0, int((current_time - rep_time).total_seconds() / 86400.0))

        freshness, freshness_reason = cls.evaluate_freshness(observation, now=current_time)
        reasons: List[str] = [freshness_reason]

        # Check OSM agreement
        osm_agreement: Optional[bool] = None
        if observation.category == ObservationCategory.KERB:
            osm_kerb = KerbType.UNKNOWN
            if osm_edge_evidence and osm_edge_evidence.kerb != KerbType.UNKNOWN:
                osm_kerb = osm_edge_evidence.kerb
            elif osm_node_evidence and osm_node_evidence.kerb != KerbType.UNKNOWN:
                osm_kerb = osm_node_evidence.kerb

            if osm_kerb != KerbType.UNKNOWN:
                osm_accessible = osm_kerb in (KerbType.LOWERED, KerbType.FLUSH)
                comm_accessible = observation.value in ("lowered", "flush")
                if osm_accessible == comm_accessible:
                    osm_agreement = True
                    reasons.append(f"Agrees with mapped OpenStreetMap kerb ({osm_kerb.value}).")
                else:
                    osm_agreement = False
                    reasons.append(f"Disagrees with OpenStreetMap (OSM records {osm_kerb.value}, community reports {observation.value}).")

        elif observation.category == ObservationCategory.SURFACE and osm_edge_evidence:
            osm_surf = osm_edge_evidence.surface
            if osm_surf != SurfaceType.UNKNOWN:
                osm_paved = osm_surf in (SurfaceType.ASPHALT, SurfaceType.CONCRETE, SurfaceType.PAVED, SurfaceType.PAVING_STONES)
                comm_paved = observation.value in ("asphalt", "concrete", "paved", "paving_stones")
                if osm_paved == comm_paved:
                    osm_agreement = True
                    reasons.append(f"Agrees with OpenStreetMap surface material ({osm_surf.value}).")
                else:
                    osm_agreement = False
                    reasons.append(f"Disagrees with OpenStreetMap (OSM records {osm_surf.value}, community reports {observation.value}).")

        # Consensus breakdown
        conf_count = observation.confirmations_count
        disp_count = observation.disputes_count

        if conf_count >= 1:
            reasons.append(f"{conf_count} independent peer confirmation(s).")
        if disp_count > 0:
            reasons.append(f"{disp_count} peer dispute(s) recorded.")

        # Determine reliability band
        if freshness in (FreshnessState.STALE, FreshnessState.EXPIRED):
            band = ReliabilityBand.STALE
            reasons.append("Marked stale due to elapsed category-specific validity window.")
        elif osm_agreement is False or disp_count >= 2:
            band = ReliabilityBand.CONFLICTING_EVIDENCE
            reasons.append("Flagged as conflicting evidence requiring peer resolution.")
        elif conf_count >= 3 and disp_count <= 1:
            band = ReliabilityBand.STRONG_COMMUNITY_EVIDENCE
            reasons.append("Strong multi-peer community consensus with negligible dispute.")
        elif conf_count >= 2 and disp_count == 0:
            band = ReliabilityBand.MODERATE_EVIDENCE
            reasons.append("Established community consensus without disputes.")
        else:
            band = ReliabilityBand.LOW_EVIDENCE
            reasons.append("Single observation or unverified peer support.")

        return EvidenceReliabilityAssessment(
            observation_id=observation.id,
            category=observation.category,
            value=observation.value,
            verification_status=observation.verification_status,
            confirmation_count=conf_count,
            dispute_count=disp_count,
            age_days=age_days,
            freshness_state=freshness,
            reliability_band=band,
            osm_agreement=osm_agreement,
            reasons=reasons,
        )
