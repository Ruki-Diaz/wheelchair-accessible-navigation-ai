"""Pydantic schemas for AccessRoute AI Community Accessibility Reporting & Verification API.

Stage 9 Architecture:
Validates incoming community observations, interactions (confirm/dispute),
nearby geographic queries, and verification opportunities with strict type checking.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CommunityReportCreate(BaseModel):
    """Schema for submitting a new community accessibility observation."""

    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS84 latitude coordinate.")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS84 longitude coordinate.")
    category: str = Field(..., min_length=2, max_length=50, description="Observation category (e.g. kerb, surface, stairs, path_blocked, construction).")
    value: str = Field(..., min_length=1, max_length=100, description="Structured observation value (e.g. lowered, raised, asphalt, blocked).")
    is_temporary: bool = Field(False, description="Whether this report represents a temporary condition.")
    expected_duration_hours: Optional[float] = Field(None, ge=0.5, le=8760.0, description="Optional expected duration in hours for temporary conditions.")
    expires_at: Optional[datetime] = Field(None, description="Optional explicit ISO expiration timestamp for temporary conditions.")
    contributor_id: Optional[str] = Field(None, max_length=128, description="Anonymous session/device token to prevent duplicate confirmations.")
    notes: Optional[str] = Field(None, max_length=500, description="Optional factual notes describing the accessibility condition.")
    photo_url: Optional[str] = Field(None, max_length=2000, description="Optional reference URL or placeholder for photographic evidence.")


class CommunityReportResponse(BaseModel):
    """Schema representing a stored community accessibility observation."""

    id: str = Field(..., description="Unique observation UUID.")
    source: str = Field("COMMUNITY_OBSERVATION", description="Evidence provenance source.")
    category: str = Field(..., description="Observation category.")
    value: str = Field(..., description="Normalized structured condition value.")
    latitude: float = Field(..., description="WGS84 latitude.")
    longitude: float = Field(..., description="WGS84 longitude.")
    osm_element_type: Optional[str] = Field(None, description="Matched OSM element type (way or node).")
    osm_element_id: Optional[int] = Field(None, description="Matched OpenStreetMap feature identifier.")
    matched_distance_m: Optional[float] = Field(None, description="Distance from submitted point to matched feature in meters.")
    match_confidence: Optional[float] = Field(None, description="Spatial snapping confidence metric.")
    is_temporary: bool = Field(..., description="True if temporary condition.")
    reported_at: str = Field(..., description="ISO 8601 timestamp of original submission.")
    expected_end_at: Optional[str] = Field(None, description="ISO 8601 timestamp of expected resolution.")
    expires_at: Optional[str] = Field(None, description="ISO 8601 timestamp when report ceases to affect routing.")
    verification_status: str = Field(..., description="Deterministic status: UNVERIFIED, COMMUNITY_SUPPORTED, COMMUNITY_DISPUTED, VERIFIED, EXPIRED, REJECTED.")
    confirmations_count: int = Field(..., description="Count of independent community confirmations.")
    disputes_count: int = Field(..., description="Count of community disputes.")
    notes: Optional[str] = Field(None, description="Optional notes.")
    photo_url: Optional[str] = Field(None, description="Optional photo reference.")
    is_active: bool = Field(..., description="Whether this report is currently active for routing.")


class CommunityReportsListResponse(BaseModel):
    """Collection response containing multiple community observations."""

    count: int = Field(..., description="Total count of returned reports.")
    reports: List[CommunityReportResponse] = Field(..., description="List of observation records.")


class InteractionRequest(BaseModel):
    """Request payload for confirming or disputing an observation."""

    contributor_id: str = Field(..., min_length=1, max_length=128, description="Anonymous contributor/session identifier.")


class InteractionResponse(BaseModel):
    """Response returned following a confirm or dispute interaction."""

    success: bool = Field(..., description="True if the interaction was successfully recorded.")
    observation_id: str = Field(..., description="Observation UUID.")
    new_status: str = Field(..., description="Updated verification status after applying deterministic rules.")
    confirmations_count: int = Field(..., description="Updated count of confirmations.")
    disputes_count: int = Field(..., description="Updated count of disputes.")
    message: str = Field(..., description="Descriptive status message.")


class VerificationOpportunityItem(BaseModel):
    """A single deterministic data gap opportunity identified in the map."""

    latitude: float = Field(..., description="WGS84 latitude.")
    longitude: float = Field(..., description="WGS84 longitude.")
    osm_element_type: str = Field(..., description="OSM element type (e.g. way, node).")
    osm_element_id: int = Field(..., description="OSM ID.")
    missing_attribute: str = Field(..., description="Missing attribute name (e.g. kerb, surface, width).")
    feature_type: str = Field(..., description="Physical feature classification (e.g. crossing, footway).")
    importance_reason: str = Field(..., description="Deterministic rationale why this missing attribute matters.")


class VerificationOpportunitiesResponse(BaseModel):
    """Collection of identified data gap opportunities."""

    count: int = Field(..., description="Count of opportunities returned.")
    opportunities: List[VerificationOpportunityItem] = Field(..., description="List of verification opportunities.")
