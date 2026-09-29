"""Community accessibility evidence, verification, and provenance package."""

from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.community.matcher import CommunitySpatialMatcher, MatchResult
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    EvidenceConflict,
    ObservationCategory,
    STRUCTURED_VALUES,
    VerificationOpportunity,
    VerificationStatus,
)
from accessroute.community.repository import (
    CommunityObservationRepository,
    SQLiteCommunityObservationRepository,
)
from accessroute.community.service import CommunityObservationService
from accessroute.community.verification import CommunityVerificationEngine

__all__ = [
    "AccessibilityEvidenceSource",
    "CommunityObservation",
    "ObservationCategory",
    "VerificationStatus",
    "EvidenceConflict",
    "VerificationOpportunity",
    "STRUCTURED_VALUES",
    "CommunityObservationRepository",
    "SQLiteCommunityObservationRepository",
    "CommunitySpatialMatcher",
    "MatchResult",
    "CommunityVerificationEngine",
    "EvidenceConflictDetector",
    "CommunityObservationService",
]
