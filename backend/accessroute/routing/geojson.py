"""GeoJSON serializer for AccessRoute AI routing results.

Converts CoordinatedRouteResult into standardized GeoJSON FeatureCollections
containing full-route geometries, granular segment-level evidence,
query endpoints, snapped anchors, and baseline comparisons.
"""

from typing import Any, Dict, List, Optional, Tuple
import networkx as nx
from shapely.geometry import LineString

from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.intelligence.route_quality import RouteEvidenceQualityAnalyzer
from accessroute.routing.service import CoordinatedRouteResult
from accessroute.scoring.normalizer import extract_edge_evidence, extract_node_evidence


def _format_community_obs(obs: Any) -> Dict[str, Any]:
    cat = obs.category.value if hasattr(obs.category, "value") else str(obs.category)
    stat = obs.verification_status.value if hasattr(obs.verification_status, "value") else str(obs.verification_status)
    return {
        "id": getattr(obs, "id", ""),
        "category": cat,
        "value": str(getattr(obs, "value", "")),
        "verification_status": stat,
        "confirmations_count": getattr(obs, "confirmations_count", 1),
        "disputes_count": getattr(obs, "disputes_count", 0),
        "is_temporary": getattr(obs, "is_temporary", False),
        "reported_at": obs.reported_at.isoformat() if hasattr(getattr(obs, "reported_at", None), "isoformat") else str(getattr(obs, "reported_at", "")),
        "expires_at": obs.expires_at.isoformat() if hasattr(getattr(obs, "expires_at", None), "isoformat") else (str(obs.expires_at) if getattr(obs, "expires_at", None) else None),
        "notes": getattr(obs, "notes", None),
        "source": "COMMUNITY_OBSERVATION",
    }


def _build_segment_properties(
    edge_data: Dict[str, Any],
    graph: Optional[nx.MultiDiGraph],
    u: int,
    v: int,
    idx: int,
    alternative_key: Optional[str] = None,
) -> Dict[str, Any]:
    findings_raw = edge_data.get("findings", [])
    findings_list = list(findings_raw) if isinstance(findings_raw, (set, list)) else []

    abs_grade = edge_data.get("absolute_grade")
    grade_pct = round(abs_grade * 100.0, 1) if abs_grade is not None else None

    # Community observations & conflict detection
    comm_obs = list(edge_data.get("_community_observations", []))
    node_v_data = graph.nodes.get(v, {}) if (graph is not None and v in graph) else {}
    if node_v_data:
        comm_obs.extend(node_v_data.get("_community_observations", []))

    edge_ev = edge_data.get("_accessibility_evidence")
    if edge_ev is None:
        try:
            edge_ev = extract_edge_evidence(edge_data)
        except Exception:
            edge_ev = None

    node_ev = node_v_data.get("_accessibility_evidence") if node_v_data else None
    if node_ev is None and node_v_data:
        try:
            node_ev = extract_node_evidence(v, node_v_data)
        except Exception:
            node_ev = None

    conflicts = EvidenceConflictDetector.detect_conflicts(edge_ev, node_ev, comm_obs) if comm_obs else []
    conflict_dicts = [
        {
            "attribute": c.attribute_name,
            "osm_claim": c.osm_claim,
            "community_claim": c.community_claim,
            "summary": c.conflict_summary,
            "community_observation_id": c.community_observation_id,
            "status": c.verification_status.value if hasattr(c.verification_status, "value") else str(c.verification_status),
        }
        for c in conflicts
    ]

    surface_val = str(edge_data.get("surface", "unknown"))
    highway_val = str(edge_data.get("highway", "footway"))
    wheelchair_val = str(edge_data.get("wheelchair", "unknown"))
    kerb_val = str(edge_data.get("kerb", "unknown"))
    tactile_val = str(edge_data.get("tactile_paving", "unknown"))
    is_cross = bool(edge_data.get("is_crossing", False))
    is_step = bool("steps" in str(edge_data.get("highway", "")).lower())
    has_rmp = bool(edge_data.get("has_ramp", False) or edge_data.get("has_wheelchair_ramp", False))
    slope_dir = str(edge_data.get("slope_direction", "unknown"))
    elev_src = str(edge_data.get("elevation_source", "UNKNOWN"))

    props = {
        "feature_type": "route_segment",
        "segment_index": idx,
        "from_node": u,
        "to_node": v,
        "length_m": round(float(edge_data.get("length", 0.0)), 1),
        "surface": surface_val,
        "highway": highway_val,
        "wheelchair": wheelchair_val,
        "kerb": kerb_val,
        "tactile_paving": tactile_val,
        "is_crossing": is_cross,
        "is_steps": is_step,
        "has_ramp": has_rmp,
        "estimated_grade_pct": grade_pct,
        "slope_direction": slope_dir,
        "elevation_source": elev_src,
        "findings": findings_list,
        "source": "OpenStreetMap + Copernicus DEM (30m)",
        # Stage 9 Provenance Separation
        "osm_evidence": {
            "source": "OpenStreetMap",
            "surface": surface_val,
            "highway": highway_val,
            "wheelchair": wheelchair_val,
            "kerb": kerb_val,
            "tactile_paving": tactile_val,
            "is_crossing": is_cross,
            "is_steps": is_step,
            "has_ramp": has_rmp,
        },
        "terrain_evidence": {
            "source": elev_src if elev_src != "UNKNOWN" else "Copernicus GLO-30",
            "estimated_grade_pct": grade_pct,
            "slope_direction": slope_dir,
        },
        "community_evidence": [_format_community_obs(o) for o in comm_obs],
        "conflicts": conflict_dicts,
        "evidence_conflict": len(conflict_dicts) > 0,
    }

    if alternative_key is not None:
        props["alternative_key"] = alternative_key

    return props


def route_result_to_geojson(
    result: CoordinatedRouteResult,
    graph: Optional[nx.MultiDiGraph] = None,
    include_segments: bool = True,
    include_baseline: bool = True,
) -> Dict[str, Any]:
    """Convert a CoordinatedRouteResult into a standard GeoJSON FeatureCollection.

    Features generated:
    1. Overall Accessibility-Aware Route (LineString)
    2. Segment-level Route Features with detailed evidence (LineStrings, if include_segments=True)
    3. Baseline Shortest Path (LineString, if available and include_baseline=True)
    4. Query Origin Point
    5. Query Destination Point
    6. Snapped Origin Point (with distance-to-network property)
    7. Snapped Destination Point (with distance-to-network property)

    Args:
        result: CoordinatedRouteResult instance.
        graph: Optional NetworkX MultiDiGraph to extract accurate curved geometries and segment metadata.
        include_segments: Whether to emit individual segment features for the evidence inspector.
        include_baseline: Whether to include baseline unconstrained shortest path.

    Returns:
        GeoJSON FeatureCollection dictionary conforming to RFC 7946.
    """
    features: List[Dict[str, Any]] = []

    # 1. Point Features for Origin & Destination
    features.append({
        "type": "Feature",
        "id": "requested_origin",
        "geometry": {
            "type": "Point",
            "coordinates": [result.requested_origin[1], result.requested_origin[0]],
        },
        "properties": {
            "feature_type": "requested_origin",
            "title": "Requested Origin",
            "latitude": result.requested_origin[0],
            "longitude": result.requested_origin[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "requested_destination",
        "geometry": {
            "type": "Point",
            "coordinates": [result.requested_destination[1], result.requested_destination[0]],
        },
        "properties": {
            "feature_type": "requested_destination",
            "title": "Requested Destination",
            "latitude": result.requested_destination[0],
            "longitude": result.requested_destination[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "snapped_origin",
        "geometry": {
            "type": "Point",
            "coordinates": [result.snapped_origin[1], result.snapped_origin[0]],
        },
        "properties": {
            "feature_type": "snapped_origin",
            "title": "Walkable Network Origin",
            "node_id": result.origin_node_id,
            "snap_distance_m": result.origin_snap_distance_m,
            "latitude": result.snapped_origin[0],
            "longitude": result.snapped_origin[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "snapped_destination",
        "geometry": {
            "type": "Point",
            "coordinates": [result.snapped_destination[1], result.snapped_destination[0]],
        },
        "properties": {
            "feature_type": "snapped_destination",
            "title": "Walkable Network Destination",
            "node_id": result.destination_node_id,
            "snap_distance_m": result.destination_snap_distance_m,
            "latitude": result.snapped_destination[0],
            "longitude": result.snapped_destination[1],
        },
    })

    # If no route found, return endpoints and metadata only
    if not result.found or not result.route.edges:
        return {
            "type": "FeatureCollection",
            "properties": {
                "route_found": False,
                "region_id": result.region_id,
                "explanations": result.explanations,
                "snap_warnings": result.snap_warnings,
            },
            "features": features,
        }

    # 2. Extract Coordinates and Segment Evidence
    full_route_coords: List[List[float]] = []
    segment_features: List[Dict[str, Any]] = []

    for idx, edge_data in enumerate(result.route.edges):
        u = result.route.nodes[idx] if idx < len(result.route.nodes) else 0
        v = result.route.nodes[idx + 1] if idx + 1 < len(result.route.nodes) else 0
        seg_coords: List[List[float]] = []

        geom = (
            result.route.geometries[idx]
            if idx < len(result.route.geometries)
            else edge_data.get("geometry")
        )

        if geom is not None and hasattr(geom, "coords"):
            seg_coords = [[float(lon), float(lat)] for lon, lat in geom.coords]
        elif graph is not None and u in graph and v in graph:
            u_lat, u_lon = graph.nodes[u]["y"], graph.nodes[u]["x"]
            v_lat, v_lon = graph.nodes[v]["y"], graph.nodes[v]["x"]
            seg_coords = [[float(u_lon), float(u_lat)], [float(v_lon), float(v_lat)]]

        # Append to full route coordinates without duplicating consecutive endpoints
        if seg_coords:
            if not full_route_coords:
                full_route_coords.extend(seg_coords)
            else:
                if full_route_coords[-1] == seg_coords[0]:
                    full_route_coords.extend(seg_coords[1:])
                else:
                    full_route_coords.extend(seg_coords)

        # Build Segment Feature for Evidence Inspector
        if include_segments and seg_coords:
            seg_props = _build_segment_properties(
                edge_data=edge_data,
                graph=graph,
                u=u,
                v=v,
                idx=idx,
            )

            segment_features.append({
                "type": "Feature",
                "id": f"segment_{idx}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": seg_coords,
                },
                "properties": seg_props,
            })

    # 3. Overall Accessible Route LineString Feature
    metrics = result.route.metrics
    features.append({
        "type": "Feature",
        "id": "accessible_route",
        "geometry": {
            "type": "LineString",
            "coordinates": full_route_coords,
        },
        "properties": {
            "feature_type": "accessible_route",
            "route_type": "accessibility_aware",
            "physical_distance_m": round(result.physical_distance_meters, 1),
            "total_cost": round(result.total_cost, 1),
            "accessibility_cost": round(result.accessibility_cost, 1),
            "terrain_cost": round(result.terrain_cost, 1),
            "uncertainty_cost": round(result.uncertainty_cost, 1),
            "elevation_gain_m": round(float(metrics.get("elevation_gain_m", 0.0)), 1),
            "elevation_loss_m": round(float(metrics.get("elevation_loss_m", 0.0)), 1),
            "max_uphill_grade_pct": round(float(metrics.get("max_uphill_grade_pct", 0.0)), 1),
            "missing_data_pct": round(float(metrics.get("missing_data_pct", 0.0)), 1),
            "node_count": len(result.route.nodes),
            "edge_count": len(result.route.edges),
            "evidence_quality": RouteEvidenceQualityAnalyzer.analyze_route_evidence(result).to_dict(),
        },
    })

    # 4. Baseline Route Feature (if present)
    if include_baseline and result.baseline_route and result.baseline_route.found:
        base_coords: List[List[float]] = []
        for b_idx, b_edge in enumerate(result.baseline_route.edges):
            b_u = result.baseline_route.nodes[b_idx] if b_idx < len(result.baseline_route.nodes) else 0
            b_v = result.baseline_route.nodes[b_idx + 1] if b_idx + 1 < len(result.baseline_route.nodes) else 0
            bgeom = (
                result.baseline_route.geometries[b_idx]
                if b_idx < len(result.baseline_route.geometries)
                else b_edge.get("geometry")
            )

            if bgeom is not None and hasattr(bgeom, "coords"):
                b_seg = [[float(lon), float(lat)] for lon, lat in bgeom.coords]
            elif graph is not None and b_u in graph and b_v in graph:
                b_seg = [
                    [float(graph.nodes[b_u]["x"]), float(graph.nodes[b_u]["y"])],
                    [float(graph.nodes[b_v]["x"]), float(graph.nodes[b_v]["y"])],
                ]
            else:
                b_seg = []

            if b_seg:
                if not base_coords:
                    base_coords.extend(b_seg)
                else:
                    if base_coords[-1] == b_seg[0]:
                        base_coords.extend(b_seg[1:])
                    else:
                        base_coords.extend(b_seg)

        if base_coords:
            features.append({
                "type": "Feature",
                "id": "baseline_route",
                "geometry": {
                    "type": "LineString",
                    "coordinates": base_coords,
                },
                "properties": {
                    "feature_type": "baseline_route",
                    "route_type": "distance_first_baseline",
                    "physical_distance_m": round(result.baseline_route.physical_distance_meters, 1),
                    "total_cost": round(result.baseline_route.total_cost, 1),
                },
            })

    # Add segment features after the route lines
    if include_segments:
        features.extend(segment_features)

    return {
        "type": "FeatureCollection",
        "properties": {
            "route_found": True,
            "region_id": result.region_id,
            "physical_distance_m": round(result.physical_distance_meters, 1),
            "total_cost": round(result.total_cost, 1),
            "accessibility_cost": round(result.accessibility_cost, 1),
            "terrain_cost": round(result.terrain_cost, 1),
            "uncertainty_cost": round(result.uncertainty_cost, 1),
            "cache_hit": result.cache_hit,
            "accessibility_enriched": result.accessibility_enriched,
            "terrain_enriched": result.terrain_enriched,
            "expansion_occurred": result.expansion_occurred,
            "expansion_attempts": result.expansion_attempts,
            "explanations": result.explanations,
            "snap_warnings": result.snap_warnings,
        },
        "features": features,
    }


def route_alternatives_to_geojson(
    result: Any,  # RouteAlternativesResult
    graph: Optional[nx.MultiDiGraph] = None,
    include_segments: bool = True,
    active_index: int = 0,
) -> Dict[str, Any]:
    """Convert a RouteAlternativesResult into a GeoJSON FeatureCollection.

    Includes:
    1. Origin and Destination point features (requested & snapped).
    2. Route LineString feature for each alternative with styling attributes.
    3. Granular segment-level features for the primary selected alternative.
    """
    features: List[Dict[str, Any]] = []

    # 1. Point Features
    features.append({
        "type": "Feature",
        "id": "requested_origin",
        "geometry": {
            "type": "Point",
            "coordinates": [result.requested_origin[1], result.requested_origin[0]],
        },
        "properties": {
            "feature_type": "requested_origin",
            "title": "Requested Origin",
            "latitude": result.requested_origin[0],
            "longitude": result.requested_origin[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "requested_destination",
        "geometry": {
            "type": "Point",
            "coordinates": [result.requested_destination[1], result.requested_destination[0]],
        },
        "properties": {
            "feature_type": "requested_destination",
            "title": "Requested Destination",
            "latitude": result.requested_destination[0],
            "longitude": result.requested_destination[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "snapped_origin",
        "geometry": {
            "type": "Point",
            "coordinates": [result.snapped_origin[1], result.snapped_origin[0]],
        },
        "properties": {
            "feature_type": "snapped_origin",
            "title": "Walkable Network Origin",
            "node_id": result.origin_node_id,
            "snap_distance_m": result.origin_snap_distance_m,
            "latitude": result.snapped_origin[0],
            "longitude": result.snapped_origin[1],
        },
    })

    features.append({
        "type": "Feature",
        "id": "snapped_destination",
        "geometry": {
            "type": "Point",
            "coordinates": [result.snapped_destination[1], result.snapped_destination[0]],
        },
        "properties": {
            "feature_type": "snapped_destination",
            "title": "Walkable Network Destination",
            "node_id": result.destination_node_id,
            "snap_distance_m": result.destination_snap_distance_m,
            "latitude": result.snapped_destination[0],
            "longitude": result.snapped_destination[1],
        },
    })

    if not result.found or not result.alternatives:
        return {
            "type": "FeatureCollection",
            "properties": {
                "route_found": False,
                "region_id": result.region_id,
                "snap_warnings": result.snap_warnings,
            },
            "features": features,
        }

    # Helper to extract coordinates for an alternative
    def get_alternative_coords(alt) -> List[List[float]]:
        coords: List[List[float]] = []
        for idx, edge_data in enumerate(alt.route_result.edges):
            u = alt.route_result.nodes[idx] if idx < len(alt.route_result.nodes) else 0
            v = alt.route_result.nodes[idx + 1] if idx + 1 < len(alt.route_result.nodes) else 0
            seg_coords: List[List[float]] = []

            geom = (
                alt.route_result.geometries[idx]
                if idx < len(alt.route_result.geometries)
                else edge_data.get("geometry")
            )

            if geom is not None and hasattr(geom, "coords"):
                seg_coords = [[float(lon), float(lat)] for lon, lat in geom.coords]
            elif graph is not None and u in graph and v in graph:
                seg_coords = [
                    [float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])],
                    [float(graph.nodes[v]["x"]), float(graph.nodes[v]["y"])],
                ]

            if seg_coords:
                if not coords:
                    coords.extend(seg_coords)
                else:
                    if coords[-1] == seg_coords[0]:
                        coords.extend(seg_coords[1:])
                    else:
                        coords.extend(seg_coords)
        return coords

    # 2. Add Alternative LineString Features
    for idx, alt in enumerate(result.alternatives):
        coords = get_alternative_coords(alt)
        is_selected = (idx == active_index)

        # Style based on route type and selection
        if alt.key == "accessibility_aware":
            dash = None
            weight = 6 if is_selected else 4
            color = alt.color_hex
        elif alt.key == "lower_slope":
            dash = "8, 6"
            weight = 5 if is_selected else 3.5
            color = alt.color_hex
        else:
            dash = "4, 6"
            weight = 4 if is_selected else 3
            color = alt.color_hex

        features.append({
            "type": "Feature",
            "id": f"alternative_{alt.key}",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "feature_type": "route_alternative",
                "alternative_index": idx,
                "key": alt.key,
                "title": alt.title,
                "badge": alt.badge,
                "description": alt.description,
                "policy_name": alt.policy_name,
                "physical_distance_m": alt.physical_distance_m,
                "estimated_duration_min": alt.estimated_duration_min,
                "distance_delta_m": alt.distance_delta_m,
                "elevation_gain_m": alt.elevation_gain_m,
                "max_uphill_grade_pct": alt.max_uphill_grade_pct,
                "paved_percentage": alt.paved_percentage,
                "stairs_encountered_count": alt.stairs_encountered_count,
                "crossings_count": alt.crossings_count,
                "crossings_unknown_kerb_count": alt.crossings_unknown_kerb_count,
                "missing_data_pct": alt.missing_data_pct,
                "is_selected": is_selected,
                "is_shortest": alt.is_shortest,
                "evidence_quality": RouteEvidenceQualityAnalyzer.analyze_route_evidence(alt.route_result).to_dict(),
                "style": {
                    "color": color,
                    "weight": weight,
                    "opacity": 0.95 if is_selected else 0.5,
                    "dashArray": dash,
                },
            },
        })

    # 3. Add Segment Features for the selected route (for Evidence Inspector)
    if include_segments and 0 <= active_index < len(result.alternatives):
        active_alt = result.alternatives[active_index]
        for idx, edge_data in enumerate(active_alt.route_result.edges):
            u = active_alt.route_result.nodes[idx] if idx < len(active_alt.route_result.nodes) else 0
            v = active_alt.route_result.nodes[idx + 1] if idx + 1 < len(active_alt.route_result.nodes) else 0
            seg_coords: List[List[float]] = []

            geom = (
                active_alt.route_result.geometries[idx]
                if idx < len(active_alt.route_result.geometries)
                else edge_data.get("geometry")
            )

            if geom is not None and hasattr(geom, "coords"):
                seg_coords = [[float(lon), float(lat)] for lon, lat in geom.coords]
            elif graph is not None and u in graph and v in graph:
                seg_coords = [
                    [float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])],
                    [float(graph.nodes[v]["x"]), float(graph.nodes[v]["y"])],
                ]

            if seg_coords:
                seg_props = _build_segment_properties(
                    edge_data=edge_data,
                    graph=graph,
                    u=u,
                    v=v,
                    idx=idx,
                    alternative_key=active_alt.key,
                )
                features.append({
                    "type": "Feature",
                    "id": f"segment_{active_alt.key}_{idx}",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": seg_coords,
                    },
                    "properties": seg_props,
                })

    return {
        "type": "FeatureCollection",
        "properties": {
            "route_found": True,
            "region_id": result.region_id,
            "alternatives_count": len(result.alternatives),
            "active_index": active_index,
            "cache_hit": result.cache_hit,
            "accessibility_enriched": result.accessibility_enriched,
            "terrain_enriched": result.terrain_enriched,
            "expansion_occurred": result.expansion_occurred,
            "expansion_attempts": result.expansion_attempts,
            "snap_warnings": result.snap_warnings,
        },
        "features": features,
    }

