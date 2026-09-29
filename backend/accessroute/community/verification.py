"""Deterministic verification logic for community accessibility observations.

Stage 9 Architecture:
Never invents opaque 'AI confidence scores'.
All verification transitions are transparently and deterministically calculated
from observable signals:
- Independent confirmations
- Disputes
- Expiration timestamps
- Conflicting report counts
"""

from datetime import datetime, timezone
from typing import Optional, Tuple
from accessroute.community.models import CommunityObservation, VerificationStatus


class CommunityVerificationEngine:
    """Evaluates and transitions verification statuses for community observations."""

    @staticmethod
    def evaluate_status(
        observation: CommunityObservation,
        now: Optional[datetime] = None,
    ) -> VerificationStatus:
        """Deterministically compute the verification status based on evidence counts and time."""
        current_time = now or datetime.now(timezone.utc)

        # 1. Check expiration for temporary reports
        if observation.is_temporary and observation.expires_at is not None:
            exp = (
                observation.expires_at.replace(tzinfo=timezone.utc)
                if observation.expires_at.tzinfo is None
                else observation.expires_at
            )
            if current_time > exp:
                return VerificationStatus.EXPIRED

        # 2. Check severe dispute / rejection
        if observation.disputes_count >= 3 and observation.disputes_count > (observation.confirmations_count * 2):
            return VerificationStatus.REJECTED

        # 3. Check community dispute
        if observation.disputes_count >= 2 and observation.disputes_count >= observation.confirmations_count:
            return VerificationStatus.COMMUNITY_DISPUTED

        # 4. Check high verification (multi-user consensus)
        if observation.confirmations_count >= 4 and observation.disputes_count <= 1:
            return VerificationStatus.VERIFIED

        # 5. Check community supported (initial consensus)
        if observation.confirmations_count >= 2 and observation.disputes_count == 0:
            return VerificationStatus.COMMUNITY_SUPPORTED

        if observation.confirmations_count >= 3 and observation.disputes_count <= 1:
            return VerificationStatus.COMMUNITY_SUPPORTED

        # Default state
        return VerificationStatus.UNVERIFIED

    @staticmethod
    def get_verification_explanation(
        observation: CommunityObservation,
        now: Optional[datetime] = None,
    ) -> str:
        """Return a factual, evidence-backed description of the observation's status."""
        current_time = now or datetime.now(timezone.utc)
        rep_time = (
            observation.reported_at.replace(tzinfo=timezone.utc)
            if observation.reported_at.tzinfo is None
            else observation.reported_at
        )
        age_days = max(0, (current_time - rep_time).days)
        age_str = "today" if age_days == 0 else (f"{age_days} day ago" if age_days == 1 else f"{age_days} days ago")

        if observation.verification_status == VerificationStatus.EXPIRED:
            return f"Expired temporary report (reported {age_str})"

        if observation.verification_status == VerificationStatus.REJECTED:
            return f"Rejected: {observation.disputes_count} disputes outweigh {observation.confirmations_count} confirmations."

        if observation.verification_status == VerificationStatus.COMMUNITY_DISPUTED:
            return f"Disputed: {observation.confirmations_count} confirmations vs {observation.disputes_count} disputes."

        if observation.verification_status == VerificationStatus.VERIFIED:
            return f"Verified: {observation.confirmations_count} independent confirmations (reported {age_str})."

        if observation.verification_status == VerificationStatus.COMMUNITY_SUPPORTED:
            return f"Community Supported: {observation.confirmations_count} confirmations, {observation.disputes_count} disputes (reported {age_str})."

        return f"Unverified report ({observation.confirmations_count} confirmations, reported {age_str})."
