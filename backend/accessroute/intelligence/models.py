"""Domain models for Stage 10 Accessibility Evidence Intelligence & Reliability.

Architecture:
Provides transparent, explainable data intelligence structures:
1. Evidence Reliability Assessments (reasons, reliability bands, freshness states)
2. Temporal Staleness and Freshness Classifications
3. Routing Impact Metrics
4. Verification Priorities and Explanations
5. Verification Missions (actionable community tasks)
6. Route Evidence Quality Breakdown (data quality, NOT accessibility percentages)
7. What-If Verification Impact (hypothetical route sensitivity)
8. Conflict Clusters (spatial disagreement concentrations)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from accessroute.community.models import ObservationCategory, VerificationStatus


class FreshnessState(str, Enum):
    """Categorical freshness and temporal decay state of an accessibility observation."""
    ACTIVE = "active"          # Recent observation well within freshness window
    AGING = "aging"            # In secondary window; still usable but nearing staleness
    STALE = "stale"            # Significantly aged; requires re-verification
    EXPIRED = "expired"        # Temporary observation whose lifespan has ended


class ReliabilityBand(str, Enum):
    """Transparent, explainable evidence reliability classification.

    Note: These are qualitative evidence bands derived deterministically from
    observable consensus and recency signals, NOT arbitrary AI percentages.
    """
    STRONG_COMMUNITY_EVIDENCE = "strong_community_evidence"  # Multi-peer confirmed, fresh, consistent
    MODERATE_EVIDENCE = "moderate_evidence"                  # Initial consensus, fresh
    LOW_EVIDENCE = "low_evidence"                            # Single unverified or disputed
    CONFLICTING_EVIDENCE = "conflicting_evidence"            # Explicit disagreement with OSM or peers
    STALE = "stale"                                          # Age exceeds freshness threshold


class PriorityLevel(str, Enum):
    """Deterministic urgency level for community verification."""
    CRITICAL = "critical"      # High routing impact + severe barrier risk + data missing/conflicting
    HIGH = "high"              # High routing impact or steep barrier potential
    MEDIUM = "medium"          # Moderate routing presence
    LOW = "low"                # Low routing presence or minor attribute


@dataclass
class EvidenceReliabilityAssessment:
    """Detailed reliability and freshness assessment for an observation."""
    observation_id: str
    category: ObservationCategory
    value: str
    verification_status: VerificationStatus
    confirmation_count: int
    dispute_count: int
    age_days: int
    freshness_state: FreshnessState
    reliability_band: ReliabilityBand
    osm_agreement: Optional[bool] = None  # True if agrees with OSM, False if conflicts, None if unmapped
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "category": self.category.value if hasattr(self.category, "value") else str(self.category),
            "value": self.value,
            "verification_status": self.verification_status.value if hasattr(self.verification_status, "value") else str(self.verification_status),
            "confirmation_count": self.confirmation_count,
            "dispute_count": self.dispute_count,
            "age_days": self.age_days,
            "freshness_state": self.freshness_state.value if hasattr(self.freshness_state, "value") else str(self.freshness_state),
            "reliability_band": self.reliability_band.value if hasattr(self.reliability_band, "value") else str(self.reliability_band),
            "osm_agreement": self.osm_agreement,
            "reasons": self.reasons,
        }


@dataclass
class RoutingImpact:
    """Quantified routing impact of a specific network feature or missing attribute."""
    feature_id: str
    osm_element_type: str   # 'way' | 'node'
    osm_element_id: int
    missing_attribute: str  # 'kerb' | 'surface' | 'width' | 'incline' | 'conflict'
    sampled_routes_count: int
    routes_traversing_count: int
    percentage_of_sampled_routes: float
    shortest_path_frequency: int
    accessible_route_frequency: int
    profiles_affected_count: int
    max_detour_distance_m: float
    disconnect_risk: bool
    affected_profiles: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "missing_attribute": self.missing_attribute,
            "sampled_routes_count": self.sampled_routes_count,
            "routes_traversing_count": self.routes_traversing_count,
            "percentage_of_sampled_routes": round(self.percentage_of_sampled_routes, 1),
            "shortest_path_frequency": self.shortest_path_frequency,
            "accessible_route_frequency": self.accessible_route_frequency,
            "profiles_affected_count": self.profiles_affected_count,
            "max_detour_distance_m": round(self.max_detour_distance_m, 1),
            "disconnect_risk": self.disconnect_risk,
            "affected_profiles": self.affected_profiles,
        }


@dataclass
class VerificationPriorityAssessment:
    """Prioritised verification opportunity with transparent routing impact factors."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    latitude: float = 0.0
    longitude: float = 0.0
    osm_element_type: str = "way"
    osm_element_id: int = 0
    missing_attribute: str = "kerb"
    feature_type: str = "crossing"
    priority_level: PriorityLevel = PriorityLevel.MEDIUM
    priority_score: float = 1.0
    routing_impact_score: float = 1.0
    accessibility_importance_score: float = 1.0
    evidence_need_score: float = 1.0
    reasons: List[str] = field(default_factory=list)
    impact_details: Optional[RoutingImpact] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "missing_attribute": self.missing_attribute,
            "feature_type": self.feature_type,
            "priority_level": self.priority_level.value if hasattr(self.priority_level, "value") else str(self.priority_level),
            "priority_score": round(self.priority_score, 2),
            "routing_impact_score": round(self.routing_impact_score, 2),
            "accessibility_importance_score": round(self.accessibility_importance_score, 2),
            "evidence_need_score": round(self.evidence_need_score, 2),
            "reasons": self.reasons,
            "impact_details": self.impact_details.to_dict() if self.impact_details else None,
        }


@dataclass
class VerificationMission:
    """An actionable community mission targeting a high-impact accessibility gap."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Check Kerb Ramp"
    location_name: str = "Pedestrian Crossing"
    latitude: float = 0.0
    longitude: float = 0.0
    osm_element_type: str = "way"
    osm_element_id: int = 0
    category: ObservationCategory = ObservationCategory.KERB
    missing_attribute: str = "kerb"
    why_it_matters: str = "Appears on frequent accessible routes."
    suggested_actions: List[str] = field(default_factory=list)
    priority_level: PriorityLevel = PriorityLevel.HIGH
    estimated_impact_m: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "osm_element_type": self.osm_element_type,
            "osm_element_id": self.osm_element_id,
            "category": self.category.value if hasattr(self.category, "value") else str(self.category),
            "missing_attribute": self.missing_attribute,
            "why_it_matters": self.why_it_matters,
            "suggested_actions": self.suggested_actions,
            "priority_level": self.priority_level.value if hasattr(self.priority_level, "value") else str(self.priority_level),
            "estimated_impact_m": round(self.estimated_impact_m, 1),
        }


@dataclass
class RouteEvidenceQuality:
    """Factual evaluation of accessibility evidence completeness along a specific route.

    CRITICAL SAFETY NOTE:
    Describes metadata completeness and evidence quality — NEVER claims '87% accessible'.
    """
    total_distance_m: float
    strong_evidence_distance_m: float
    strong_evidence_pct: float
    partial_evidence_distance_m: float
    partial_evidence_pct: float
    limited_evidence_distance_m: float
    limited_evidence_pct: float
    unknown_kerbs_count: int
    unknown_surface_distance_m: float
    unrecorded_elevation_distance_m: float
    community_supported_count: int
    conflicting_evidence_count: int
    stale_observations_count: int
    quality_band: str  # 'HIGH_EVIDENCE_COVERAGE' | 'MODERATE_EVIDENCE_COVERAGE' | 'LIMITED_EVIDENCE_COVERAGE'
    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_distance_m": round(self.total_distance_m, 1),
            "strong_evidence_distance_m": round(self.strong_evidence_distance_m, 1),
            "strong_evidence_pct": round(self.strong_evidence_pct, 1),
            "partial_evidence_distance_m": round(self.partial_evidence_distance_m, 1),
            "partial_evidence_pct": round(self.partial_evidence_pct, 1),
            "limited_evidence_distance_m": round(self.limited_evidence_distance_m, 1),
            "limited_evidence_pct": round(self.limited_evidence_pct, 1),
            "unknown_kerbs_count": self.unknown_kerbs_count,
            "unknown_surface_distance_m": round(self.unknown_surface_distance_m, 1),
            "unrecorded_elevation_distance_m": round(self.unrecorded_elevation_distance_m, 1),
            "community_supported_count": self.community_supported_count,
            "conflicting_evidence_count": self.conflicting_evidence_count,
            "stale_observations_count": self.stale_observations_count,
            "quality_band": self.quality_band,
            "summary_notes": self.summary_notes,
        }


@dataclass
class WhatIfOutcome:
    """Hypothetical route outcome under a simulated infrastructure state."""
    state_value: str
    route_distance_m: float
    route_changed: bool
    distance_delta_m: float
    selected_path_description: str
    affected_profiles: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_value": self.state_value,
            "route_distance_m": round(self.route_distance_m, 1),
            "route_changed": self.route_changed,
            "distance_delta_m": round(self.distance_delta_m, 1),
            "selected_path_description": self.selected_path_description,
            "affected_profiles": self.affected_profiles,
        }


@dataclass
class WhatIfResult:
    """Complete hypothetical verification simulation result."""
    target_element_type: str
    target_element_id: int
    attribute_simulated: str
    baseline_distance_m: float
    outcomes: Dict[str, WhatIfOutcome]
    max_routing_delta_m: float
    summary: str
    is_hypothetical: bool = True  # Strict architectural guard

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_element_type": self.target_element_type,
            "target_element_id": self.target_element_id,
            "attribute_simulated": self.attribute_simulated,
            "baseline_distance_m": round(self.baseline_distance_m, 1),
            "outcomes": {k: v.to_dict() for k, v in self.outcomes.items()},
            "max_routing_delta_m": round(self.max_routing_delta_m, 1),
            "summary": self.summary,
            "is_hypothetical": self.is_hypothetical,
        }


@dataclass
class ConflictCluster:
    """Geographic cluster of repeated evidence disputes between OSM and Community."""
    cluster_id: str
    centroid_lat: float
    centroid_lon: float
    radius_m: float
    conflicts_count: int
    osm_vs_community_count: int
    community_vs_community_count: int
    attributes_involved: List[str]
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "centroid_lat": round(self.centroid_lat, 6),
            "centroid_lon": round(self.centroid_lon, 6),
            "radius_m": round(self.radius_m, 1),
            "conflicts_count": self.conflicts_count,
            "osm_vs_community_count": self.osm_vs_community_count,
            "community_vs_community_count": self.community_vs_community_count,
            "attributes_involved": self.attributes_involved,
            "description": self.description,
        }
