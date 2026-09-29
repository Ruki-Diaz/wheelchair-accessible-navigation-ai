"""Pydantic schemas for the Coordinate Routing API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from accessroute.preferences.models import MobilityPreferences


class CoordinatePair(BaseModel):
    """WGS-84 geographic coordinate pair."""

    latitude: float = Field(..., description="Latitude in decimal degrees [-90.0, 90.0].", ge=-90.0, le=90.0)
    longitude: float = Field(..., description="Longitude in decimal degrees [-180.0, 180.0].", ge=-180.0, le=180.0)


class RoutePlanRequest(BaseModel):
    """Request payload for route planning between arbitrary coordinates."""

    origin: CoordinatePair = Field(..., description="Starting location coordinate.")
    destination: CoordinatePair = Field(..., description="Target destination coordinate.")
    policy: str = Field(
        default="balanced",
        description="Routing policy: 'balanced', 'conservative', or 'distance_first'.",
        examples=["balanced", "conservative", "distance_first"],
    )
    enrich_elevation: bool = Field(
        default=True,
        description="Whether to incorporate DEM terrain elevation and slope intelligence.",
    )
    compare_baseline: bool = Field(
        default=True,
        description="Whether to calculate baseline shortest path for factual comparison.",
    )
    allow_expansion: bool = Field(
        default=True,
        description="Whether to automatically expand the search region if routing fails initially.",
    )
    preferences: Optional[MobilityPreferences] = Field(
        default=None,
        description="Optional user-controlled personal mobility preferences and constraint levels.",
    )

    @model_validator(mode="before")
    @classmethod
    def map_preferences_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "mobility_preferences" in data and "preferences" not in data:
            data["preferences"] = data["mobility_preferences"]
        return data


class RouteMetricsSchema(BaseModel):
    """Multi-criteria metrics for the planned route."""

    physical_distance_m: float = Field(..., description="Physical traversal length in meters.")
    total_cost: float = Field(..., description="Weighted multi-criteria objective cost.")
    accessibility_cost: float = Field(..., description="Virtual penalty in meters for rough or unramped surfaces.")
    terrain_cost: float = Field(..., description="Virtual penalty in meters for steep uphill or downhill slopes.")
    uncertainty_cost: float = Field(..., description="Virtual penalty in meters for unrecorded or ambiguous attributes.")
    elevation_gain_m: float = Field(default=0.0, description="Cumulative vertical elevation climb in meters.")
    elevation_loss_m: float = Field(default=0.0, description="Cumulative vertical elevation descent in meters.")
    max_uphill_grade_pct: float = Field(default=0.0, description="Maximum estimated uphill slope percentage.")
    missing_data_pct: float = Field(default=0.0, description="Percentage of traversal distance lacking complete accessibility tags.")


class BaselineComparisonSchema(BaseModel):
    """Factual comparative metrics against the unconstrained shortest path."""

    baseline_distance_m: float = Field(..., description="Shortest physical walking distance in meters.")
    accessible_distance_m: float = Field(..., description="Accessibility-aware route distance in meters.")
    distance_delta_m: float = Field(..., description="Additional walking distance compared to baseline.")
    distance_delta_pct: float = Field(..., description="Percentage distance difference vs baseline.")
    barriers_avoided_count: int = Field(default=0, description="Recorded stairs, turnstiles, or barriers avoided by the detour.")


class ExpansionMetadataSchema(BaseModel):
    """Telemetry describing regional boundary expansion."""

    expansion_occurred: bool = Field(..., description="Whether the initial search region was expanded.")
    attempts: int = Field(..., description="Number of regional search attempts performed.")
    initial_bbox: Optional[List[float]] = Field(None, description="Initial bounding box [S, W, N, E].")
    final_bbox: Optional[List[float]] = Field(None, description="Final searched bounding box [S, W, N, E].")


class RoutePlanResponse(BaseModel):
    """Complete structured response for a coordinate route planning query."""

    route_id: str = Field(..., description="Unique route identifier.")
    found: bool = Field(..., description="True if an accessible route was found.")
    policy: str = Field(..., description="Active routing policy name.")
    requested_origin: CoordinatePair = Field(..., description="Original requested origin.")
    requested_destination: CoordinatePair = Field(..., description="Original requested destination.")
    snapped_origin: CoordinatePair = Field(..., description="Nearest walkable network node for origin.")
    snapped_destination: CoordinatePair = Field(..., description="Nearest walkable network node for destination.")
    origin_snap_distance_m: float = Field(..., description="Distance in meters from requested origin to mapped network.")
    destination_snap_distance_m: float = Field(..., description="Distance in meters from requested destination to mapped network.")
    snap_warnings: List[str] = Field(default_factory=list, description="Warnings if coordinate is distant from mapped paths.")
    metrics: RouteMetricsSchema = Field(..., description="Multi-criteria metrics.")
    baseline_comparison: Optional[BaselineComparisonSchema] = Field(None, description="Factual comparison against shortest path.")
    explanations: List[str] = Field(default_factory=list, description="Deterministic factual reasons for the route.")
    expansion: ExpansionMetadataSchema = Field(..., description="Regional expansion telemetry.")
    region_id: str = Field(..., description="Spatial region identifier.")
    cache_hit: bool = Field(..., description="Whether the pedestrian network was retrieved from regional cache.")
    accessibility_enriched: bool = Field(..., description="Whether Stage 2 accessibility normalization was completed.")
    terrain_enriched: bool = Field(..., description="Whether Stage 4 elevation was applied.")
    geojson: Dict[str, Any] = Field(..., description="RFC 7946 GeoJSON FeatureCollection containing route geometry and segment evidence.")
    directions: Optional[List["DirectionStepSchema"]] = Field(default=None, description="Optional turn-by-turn navigation guidance.")
    elevation_profile: Optional["ElevationSummarySchema"] = Field(default=None, description="Optional detailed elevation profile.")
    blocking_reasons: List[str] = Field(default_factory=list, description="Reasons explaining why strict constraints could not be satisfied.")


class DirectionStepSchema(BaseModel):
    """Individual step in turn-by-turn navigation instructions."""

    step_index: int = Field(..., description="1-indexed sequence order of maneuver.")
    instruction: str = Field(..., description="Plain-language navigation instruction.")
    maneuver: str = Field(..., description="Maneuver identifier: depart, straight, turn, cross, arrive, etc.")
    street_name: str = Field(..., description="Name of street, footway, or crossing.")
    distance_m: float = Field(..., description="Distance in meters along this step.")
    cumulative_distance_m: float = Field(..., description="Cumulative distance from start in meters.")
    latitude: float = Field(..., description="Latitude where this maneuver starts.")
    longitude: float = Field(..., description="Longitude where this maneuver starts.")
    accessibility_cues: List[str] = Field(default_factory=list, description="Factual accessibility findings along this step.")
    barrier_warnings: List[str] = Field(default_factory=list, description="Accessibility barrier warnings (e.g. stairs, raised kerbs).")


class ElevationPointSchema(BaseModel):
    """Sampled coordinate along route with distance and elevation."""

    distance_m: float = Field(..., description="Cumulative distance along path in meters.")
    elevation_m: float = Field(..., description="Estimated elevation in meters above sea level.")
    latitude: float = Field(..., description="Sample point latitude.")
    longitude: float = Field(..., description="Sample point longitude.")
    grade_pct: Optional[float] = Field(default=None, description="Local slope grade percentage.")


class ElevationSummarySchema(BaseModel):
    """Terrain elevation summary and distance profile."""

    points: List[ElevationPointSchema] = Field(default_factory=list, description="Sampled distance-elevation points.")
    elevation_gain_m: float = Field(default=0.0, description="Cumulative uphill elevation gain in meters.")
    elevation_loss_m: float = Field(default=0.0, description="Cumulative downhill elevation loss in meters.")
    max_uphill_grade_pct: float = Field(default=0.0, description="Maximum estimated uphill slope %.")
    max_downhill_grade_pct: float = Field(default=0.0, description="Maximum estimated downhill slope %.")
    min_elevation_m: float = Field(default=0.0, description="Lowest elevation along route.")
    max_elevation_m: float = Field(default=0.0, description="Highest elevation along route.")
    elevation_source: str = Field(default="Copernicus GLO-30 DEM (30m)", description="Terrain data source.")


class RouteAlternativeSchema(BaseModel):
    """A distinct user-facing route option with plain-language metrics."""

    key: str = Field(..., description="Alternative key: accessibility_aware, lower_slope, or shortest.")
    title: str = Field(..., description="User-facing title, e.g. 'Accessibility-Aware'.")
    badge: str = Field(..., description="Highlight badge, e.g. 'Recommended', 'Lower Slope', 'Shortest'.")
    description: str = Field(..., description="Plain-language explanation of this route's priority.")
    policy_name: str = Field(..., description="Underlying algorithmic routing policy.")
    physical_distance_m: float = Field(..., description="Total physical distance in meters.")
    estimated_duration_min: int = Field(..., description="Estimated travel duration in minutes at standard pedestrian/wheelchair pace.")
    distance_delta_m: float = Field(..., description="Additional meters compared to shortest available option.")
    distance_delta_pct: float = Field(..., description="Percentage distance difference vs shortest option.")
    elevation_gain_m: float = Field(..., description="Estimated elevation gain in meters.")
    elevation_loss_m: float = Field(..., description="Estimated elevation loss in meters.")
    max_uphill_grade_pct: float = Field(..., description="Maximum estimated uphill slope %.")
    stairs_encountered_count: int = Field(..., description="Mapped stairways along route.")
    unpaved_distance_m: float = Field(..., description="Distance over unpaved surfaces (gravel, dirt, grass).")
    paved_percentage: float = Field(..., description="Percentage of route with recorded paved surface.")
    crossings_count: int = Field(..., description="Total road crossings.")
    crossings_unknown_kerb_count: int = Field(..., description="Crossings where kerb ramp evidence is unrecorded.")
    missing_data_pct: float = Field(..., description="Percentage of path distance lacking complete accessibility tags.")
    explanations: List[str] = Field(default_factory=list, description="Deterministic reasons why this route was formed.")
    directions: List[DirectionStepSchema] = Field(default_factory=list, description="Turn-by-turn guidance steps.")
    elevation_summary: ElevationSummarySchema = Field(..., description="Elevation profile and terrain stats.")
    color_hex: str = Field(..., description="Suggested visualization stroke color.")
    is_shortest: bool = Field(default=False, description="Whether this alternative is the shortest distance option.")
    evidence_quality: Optional[Dict[str, Any]] = Field(default=None, description="Stage 10 Route Evidence Quality breakdown.")


class RouteAlternativesRequest(BaseModel):
    """Request payload for comparing multiple accessible route alternatives."""

    origin: CoordinatePair = Field(..., description="Starting location coordinate.")
    destination: CoordinatePair = Field(..., description="Target destination coordinate.")
    enrich_elevation: bool = Field(default=True, description="Whether to incorporate DEM terrain elevation.")
    allow_expansion: bool = Field(default=True, description="Whether to expand search region if routing fails initially.")
    preferences: Optional[MobilityPreferences] = Field(
        default=None,
        description="Optional user-controlled personal mobility preferences and constraint levels.",
    )

    @model_validator(mode="before")
    @classmethod
    def map_preferences_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "mobility_preferences" in data and "preferences" not in data:
            data["preferences"] = data["mobility_preferences"]
        return data


class RouteAlternativesResponse(BaseModel):
    """Structured response containing multiple distinct route options."""

    found: bool = Field(..., description="True if at least one accessible route was found.")
    requested_origin: CoordinatePair = Field(..., description="Original requested origin.")
    requested_destination: CoordinatePair = Field(..., description="Original requested destination.")
    snapped_origin: CoordinatePair = Field(..., description="Nearest walkable network node for origin.")
    snapped_destination: CoordinatePair = Field(..., description="Nearest walkable network node for destination.")
    origin_snap_distance_m: float = Field(..., description="Distance in meters from origin to mapped network.")
    destination_snap_distance_m: float = Field(..., description="Distance in meters from destination to mapped network.")
    snap_warnings: List[str] = Field(default_factory=list, description="Warnings if coordinate is distant from mapped paths.")
    alternatives: List[RouteAlternativeSchema] = Field(default_factory=list, description="List of distinct route options.")
    region_id: str = Field(..., description="Spatial region identifier.")
    cache_hit: bool = Field(..., description="Whether the pedestrian network was retrieved from cache.")
    accessibility_enriched: bool = Field(..., description="Whether accessibility normalization was applied.")
    terrain_enriched: bool = Field(..., description="Whether DEM terrain intelligence was applied.")
    expansion_occurred: bool = Field(default=False, description="Whether regional boundary expansion occurred.")
    expansion_attempts: int = Field(default=1, description="Number of search attempts.")
    geojson: Dict[str, Any] = Field(default_factory=dict, description="RFC 7946 GeoJSON FeatureCollection with all route geometries.")
    blocking_reasons: List[str] = Field(
        default_factory=list,
        description="Identified blocking conditions when strict constraints prevent finding a route.",
    )

