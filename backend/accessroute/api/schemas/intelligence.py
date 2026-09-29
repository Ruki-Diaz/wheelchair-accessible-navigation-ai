"""Pydantic schemas for Stage 10 Accessibility Evidence Intelligence API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RegionalCoverageResponse(BaseModel):
    """Regional accessibility metadata coverage and completeness statistics."""
    region_id: str
    total_edges: int
    total_network_length_m: float
    surface_completeness_pct: float
    kerb_completeness_pct: float
    crossings_count: int
    crossings_with_kerb_info_count: int
    wheelchair_completeness_pct: float
    width_completeness_pct: float
    barrier_completeness_pct: float
    terrain_coverage_pct: float
    overall_completeness_pct: float
    coverage_band: str
    active_community_observations_count: int


class RoutingImpactSchema(BaseModel):
    """Quantified routing impact of a specific feature."""
    feature_id: str
    osm_element_type: str
    osm_element_id: int
    missing_attribute: str
    sampled_routes_count: int
    routes_traversing_count: int
    percentage_of_sampled_routes: float
    shortest_path_frequency: int
    accessible_route_frequency: int
    profiles_affected_count: int
    max_detour_distance_m: float
    disconnect_risk: bool
    affected_profiles: List[str]


class VerificationPriorityItem(BaseModel):
    """Prioritised verification opportunity item."""
    id: str
    latitude: float
    longitude: float
    osm_element_type: str
    osm_element_id: int
    missing_attribute: str
    feature_type: str
    priority_level: str
    priority_score: float
    routing_impact_score: float
    accessibility_importance_score: float
    evidence_need_score: float
    reasons: List[str]
    impact_details: Optional[RoutingImpactSchema] = None


class VerificationPrioritiesResponse(BaseModel):
    """Ranked list of verification opportunities."""
    region_id: str
    count: int
    priorities: List[VerificationPriorityItem]


class VerificationMissionItem(BaseModel):
    """Actionable community task."""
    id: str
    title: str
    location_name: str
    latitude: float
    longitude: float
    osm_element_type: str
    osm_element_id: int
    category: str
    missing_attribute: str
    why_it_matters: str
    suggested_actions: List[str]
    priority_level: str
    estimated_impact_m: float


class VerificationMissionsResponse(BaseModel):
    """List of actionable verification missions."""
    region_id: str
    count: int
    missions: List[VerificationMissionItem]


class EvidenceReliabilityResponse(BaseModel):
    """Detailed reliability and freshness assessment for an observation."""
    observation_id: str
    category: str
    value: str
    verification_status: str
    confirmation_count: int
    dispute_count: int
    age_days: int
    freshness_state: str
    reliability_band: str
    osm_agreement: Optional[bool]
    reasons: List[str]


class WhatIfRequest(BaseModel):
    """Request payload for simulating hypothetical infrastructure verification."""
    origin_latitude: float = Field(..., ge=-90.0, le=90.0)
    origin_longitude: float = Field(..., ge=-180.0, le=180.0)
    destination_latitude: float = Field(..., ge=-90.0, le=90.0)
    destination_longitude: float = Field(..., ge=-180.0, le=180.0)
    target_osm_type: str = Field(default="way", description="'way' or 'node'")
    target_osm_id: int = Field(..., description="Target OSM element ID")
    attribute_name: str = Field(default="kerb", description="'kerb', 'surface', etc.")
    hypothetical_states: List[str] = Field(default=["lowered", "raised"], min_length=1)


class WhatIfOutcomeItem(BaseModel):
    """Hypothetical outcome under a specific simulated state."""
    state_value: str
    route_distance_m: float
    route_changed: bool
    distance_delta_m: float
    selected_path_description: str
    affected_profiles: List[str]


class WhatIfResponse(BaseModel):
    """Response containing simulation results under hypothetical states."""
    target_element_type: str
    target_element_id: int
    attribute_simulated: str
    baseline_distance_m: float
    outcomes: Dict[str, WhatIfOutcomeItem]
    max_routing_delta_m: float
    summary: str
    is_hypothetical: bool = True


class ConflictClusterItem(BaseModel):
    """Spatial cluster of evidence disagreements."""
    cluster_id: str
    centroid_lat: float
    centroid_lon: float
    radius_m: float
    conflicts_count: int
    osm_vs_community_count: int
    community_vs_community_count: int
    attributes_involved: List[str]
    description: str


class ConflictClustersResponse(BaseModel):
    """List of geographic evidence disagreement clusters."""
    count: int
    clusters: List[ConflictClusterItem]


class MLFeasibilityResponse(BaseModel):
    """Machine learning feasibility evaluation."""
    total_crossings: int
    total_labeled_crossings: int
    labeled_percentage: float
    unknown_percentage: float
    class_distribution: Dict[str, int]
    is_supervised_learning_defensible: bool
    scientific_conclusion: str
    recommendation: str
