"""FastAPI endpoints for Stage 10 Accessibility Evidence Intelligence."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from accessroute.api.dependencies import get_graph_manager, get_intelligence_service
from accessroute.api.schemas.intelligence import (
    ConflictClusterItem,
    ConflictClustersResponse,
    EvidenceReliabilityResponse,
    MLFeasibilityResponse,
    RegionalCoverageResponse,
    RoutingImpactSchema,
    VerificationMissionItem,
    VerificationMissionsResponse,
    VerificationPrioritiesResponse,
    VerificationPriorityItem,
    WhatIfOutcomeItem,
    WhatIfRequest,
    WhatIfResponse,
)
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.region import BoundingBox
from accessroute.intelligence.service import EvidenceIntelligenceService

router = APIRouter(prefix="/intelligence", tags=["Evidence Intelligence"])


def _resolve_graph(
    graph_manager: DynamicGraphManager,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    region_id: Optional[str] = None,
) -> tuple:
    """Helper to locate or acquire a MultiDiGraph for requested coordinates or region."""
    if region_id:
        try:
            G, meta = graph_manager.cache.load_graph(region_id)
            return G, region_id
        except Exception:
            pass

    if latitude is not None and longitude is not None:
        bbox = BoundingBox.from_coordinates(
            origin=(latitude, longitude),
            destination=(latitude, longitude),
            buffer_meters=500.0,
        )
        G, meta, _ = graph_manager.get_graph_for_bbox(bbox=bbox, enrich_elevation=False)
        return G, meta.region_id

    # Fallback to the first available cached region
    cached = graph_manager.cache.list_cached_regions()
    if cached:
        G, meta = graph_manager.cache.load_graph(cached[0].region_id)
        return G, cached[0].region_id

    # Default fallback: Vermont South center
    lat, lon = -37.865, 145.185
    bbox = BoundingBox.from_coordinates((lat, lon), (lat, lon), buffer_meters=500.0)
    G, meta, _ = graph_manager.get_graph_for_bbox(bbox=bbox, enrich_elevation=False)
    return G, meta.region_id


@router.get(
    "/coverage",
    response_model=RegionalCoverageResponse,
    summary="Get regional accessibility metadata coverage statistics",
)
def get_regional_coverage(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> RegionalCoverageResponse:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    stats = service.get_regional_coverage(G, region_id=reg_id)
    return RegionalCoverageResponse(**stats)


@router.get(
    "/coverage/geojson",
    summary="Get GeoJSON overlay of accessibility data completeness",
)
def get_coverage_geojson(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> Dict[str, Any]:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    return service.get_coverage_geojson(G, region_id=reg_id)


@router.get(
    "/verification-priorities",
    response_model=VerificationPrioritiesResponse,
    summary="Get ranked verification opportunities by routing impact",
)
def get_verification_priorities(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    limit: int = Query(30, ge=1, le=100),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> VerificationPrioritiesResponse:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    priorities = service.get_verification_priorities(G, limit=limit)

    items: List[VerificationPriorityItem] = []
    for p in priorities:
        imp_schema = None
        if p.impact_details:
            imp_schema = RoutingImpactSchema(**p.impact_details.to_dict())
        items.append(
            VerificationPriorityItem(
                id=p.id,
                latitude=p.latitude,
                longitude=p.longitude,
                osm_element_type=p.osm_element_type,
                osm_element_id=p.osm_element_id,
                missing_attribute=p.missing_attribute,
                feature_type=p.feature_type,
                priority_level=p.priority_level.value if hasattr(p.priority_level, "value") else str(p.priority_level),
                priority_score=round(p.priority_score, 2),
                routing_impact_score=round(p.routing_impact_score, 2),
                accessibility_importance_score=round(p.accessibility_importance_score, 2),
                evidence_need_score=round(p.evidence_need_score, 2),
                reasons=p.reasons,
                impact_details=imp_schema,
            )
        )

    return VerificationPrioritiesResponse(
        region_id=reg_id,
        count=len(items),
        priorities=items,
    )


@router.get(
    "/missions",
    response_model=VerificationMissionsResponse,
    summary="Get actionable community verification tasks",
)
def get_verification_missions(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    limit: int = Query(20, ge=1, le=50),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> VerificationMissionsResponse:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    missions = service.get_verification_missions(G, limit=limit)

    items: List[VerificationMissionItem] = []
    for m in missions:
        items.append(
            VerificationMissionItem(
                id=m.id,
                title=m.title,
                location_name=m.location_name,
                latitude=m.latitude,
                longitude=m.longitude,
                osm_element_type=m.osm_element_type,
                osm_element_id=m.osm_element_id,
                category=m.category.value if hasattr(m.category, "value") else str(m.category),
                missing_attribute=m.missing_attribute,
                why_it_matters=m.why_it_matters,
                suggested_actions=m.suggested_actions,
                priority_level=m.priority_level.value if hasattr(m.priority_level, "value") else str(m.priority_level),
                estimated_impact_m=m.estimated_impact_m,
            )
        )

    return VerificationMissionsResponse(
        region_id=reg_id,
        count=len(items),
        missions=items,
    )


@router.get(
    "/reliability/{observation_id}",
    response_model=EvidenceReliabilityResponse,
    summary="Assess the reliability and freshness of a specific community observation",
)
def get_observation_reliability(
    observation_id: str,
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
) -> EvidenceReliabilityResponse:
    assessment = service.assess_observation_reliability(observation_id)
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Community observation '{observation_id}' not found.",
        )

    return EvidenceReliabilityResponse(
        observation_id=assessment.observation_id,
        category=assessment.category.value if hasattr(assessment.category, "value") else str(assessment.category),
        value=assessment.value,
        verification_status=assessment.verification_status.value if hasattr(assessment.verification_status, "value") else str(assessment.verification_status),
        confirmation_count=assessment.confirmation_count,
        dispute_count=assessment.dispute_count,
        age_days=assessment.age_days,
        freshness_state=assessment.freshness_state.value if hasattr(assessment.freshness_state, "value") else str(assessment.freshness_state),
        reliability_band=assessment.reliability_band.value if hasattr(assessment.reliability_band, "value") else str(assessment.reliability_band),
        osm_agreement=assessment.osm_agreement,
        reasons=assessment.reasons,
    )


@router.post(
    "/what-if",
    response_model=WhatIfResponse,
    summary="Simulate route outcomes under hypothetical infrastructure states",
)
def simulate_what_if(
    payload: WhatIfRequest,
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> WhatIfResponse:
    bbox = BoundingBox.from_coordinates(
        origin=(payload.origin_latitude, payload.origin_longitude),
        destination=(payload.destination_latitude, payload.destination_longitude),
        buffer_meters=350.0,
    )
    try:
        G, meta, _ = graph_manager.get_graph_for_bbox(bbox=bbox, enrich_elevation=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire routing graph: {e}")

    # Snap endpoints to graph
    from accessroute.graph.snapper import snap_to_nearest_node
    orig_node = snap_to_nearest_node(G, payload.origin_latitude, payload.origin_longitude).node_id
    dest_node = snap_to_nearest_node(G, payload.destination_latitude, payload.destination_longitude).node_id

    res = service.simulate_what_if(
        graph=G,
        origin_node=orig_node,
        destination_node=dest_node,
        target_osm_type=payload.target_osm_type,
        target_osm_id=payload.target_osm_id,
        attribute_name=payload.attribute_name,
        hypothetical_states=payload.hypothetical_states,
    )

    outcomes_dict: Dict[str, WhatIfOutcomeItem] = {}
    for k, v in res.outcomes.items():
        outcomes_dict[k] = WhatIfOutcomeItem(
            state_value=v.state_value,
            route_distance_m=v.route_distance_m,
            route_changed=v.route_changed,
            distance_delta_m=v.distance_delta_m,
            selected_path_description=v.selected_path_description,
            affected_profiles=v.affected_profiles,
        )

    return WhatIfResponse(
        target_element_type=res.target_element_type,
        target_element_id=res.target_element_id,
        attribute_simulated=res.attribute_simulated,
        baseline_distance_m=res.baseline_distance_m,
        outcomes=outcomes_dict,
        max_routing_delta_m=res.max_routing_delta_m,
        summary=res.summary,
        is_hypothetical=True,
    )


@router.get(
    "/conflicts",
    response_model=ConflictClustersResponse,
    summary="Get spatial clusters of evidence disagreements",
)
def get_conflict_clusters(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    cluster_radius_m: float = Query(60.0, ge=10.0, le=500.0),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> ConflictClustersResponse:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    clusters = service.get_regional_conflict_clusters(G, cluster_radius_m=cluster_radius_m)

    items: List[ConflictClusterItem] = []
    for c in clusters:
        items.append(
            ConflictClusterItem(
                cluster_id=c.cluster_id,
                centroid_lat=c.centroid_lat,
                centroid_lon=c.centroid_lon,
                radius_m=c.radius_m,
                conflicts_count=c.conflicts_count,
                osm_vs_community_count=c.osm_vs_community_count,
                community_vs_community_count=c.community_vs_community_count,
                attributes_involved=c.attributes_involved,
                description=c.description,
            )
        )

    return ConflictClustersResponse(
        count=len(items),
        clusters=items,
    )


@router.get(
    "/ml-feasibility",
    response_model=MLFeasibilityResponse,
    summary="Evaluate feasibility of supervised machine learning on accessibility tags",
)
def get_ml_feasibility(
    latitude: Optional[float] = Query(None, description="Center latitude"),
    longitude: Optional[float] = Query(None, description="Center longitude"),
    region_id: Optional[str] = Query(None, description="Optional cached region ID"),
    service: EvidenceIntelligenceService = Depends(get_intelligence_service),
    graph_manager: DynamicGraphManager = Depends(get_graph_manager),
) -> MLFeasibilityResponse:
    try:
        G, reg_id = _resolve_graph(graph_manager, latitude, longitude, region_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to acquire graph for region: {e}")

    audit = service.audit_ml_feasibility(G)
    return MLFeasibilityResponse(**audit)

