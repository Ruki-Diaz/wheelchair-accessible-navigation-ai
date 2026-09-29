"""Elevation and terrain enrichment pipeline for pedestrian MultiDiGraphs.

Calculates directional edge grades, cumulative gains/losses, geometry-aware profiles,
short-edge safeguards, and deterministic terrain findings.
"""

from dataclasses import dataclass
import logging
import math
from typing import Dict, List, Optional, Tuple
import networkx as nx

from accessroute.elevation.base import (
    DEM_DEFAULT_VERTICAL_ACCURACY_M,
    ElevationProvider,
    MIN_RELIABLE_EDGE_LENGTH_M,
    SUSPICIOUS_GRADE_THRESHOLD,
)
from accessroute.scoring.models import (
    EdgeTerrainEvidence,
    FindingType,
    NodeElevationEvidence,
    SlopeDirection,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ElevationEnrichmentSummary:
    """Statistical summary of graph elevation enrichment."""
    total_nodes: int
    nodes_with_elevation: int
    elevation_coverage_pct: float
    total_edges: int
    edges_with_grade: int
    suspicious_edges_count: int
    min_elevation_m: Optional[float]
    max_elevation_m: Optional[float]
    elevation_source: str


def enrich_graph_with_elevation(
    graph: nx.MultiDiGraph,
    provider: ElevationProvider,
    sample_geometry: bool = True,
    min_reliable_edge_length_m: float = MIN_RELIABLE_EDGE_LENGTH_M,
    dem_vertical_accuracy_m: float = DEM_DEFAULT_VERTICAL_ACCURACY_M,
) -> ElevationEnrichmentSummary:
    """Enrich all nodes and edges of an OSMnx MultiDiGraph with elevation and terrain intelligence.

    Args:
        graph: Input networkx MultiDiGraph with 'x' (lon) and 'y' (lat) node attributes.
        provider: ElevationProvider to supply elevation values.
        sample_geometry: If True, samples intermediate coordinates along curved edge geometries.
        min_reliable_edge_length_m: Minimum edge length for reliable slope estimation.
        dem_vertical_accuracy_m: Nominal 1-sigma vertical accuracy of DEM.

    Returns:
        ElevationEnrichmentSummary with coverage and elevation distribution stats.
    """
    if len(graph) == 0:
        return ElevationEnrichmentSummary(
            total_nodes=0,
            nodes_with_elevation=0,
            elevation_coverage_pct=0.0,
            total_edges=0,
            edges_with_grade=0,
            suspicious_edges_count=0,
            min_elevation_m=None,
            max_elevation_m=None,
            elevation_source=provider.source_name,
        )

    # =========================================================================
    # 1. BULK COORDINATE COLLECTION & BATCH ELEVATION QUERY
    # =========================================================================
    node_ids: List[int] = list(graph.nodes())
    node_coords_raw: List[Tuple[float, float]] = [
        (round(float(graph.nodes[n]["y"]), 6), round(float(graph.nodes[n]["x"]), 6))
        for n in node_ids
    ]

    edge_geom_map: Dict[Tuple[Any, Any, Any], List[Tuple[float, float]]] = {}
    if sample_geometry:
        for u, v, k, edge_data in graph.edges(keys=True, data=True):
            length_m = float(edge_data.get("length", 1.0))
            geom = edge_data.get("geometry")
            if (
                geom is not None
                and hasattr(geom, "coords")
                and len(geom.coords) > 2
                and length_m >= 40.0
            ):
                pts = [
                    (round(float(lat), 6), round(float(lon), 6))
                    for lon, lat in geom.coords
                ]
                edge_geom_map[(u, v, k)] = pts

    # Collect unique coordinates across both nodes and curved edge geometries
    unique_coords_dict: Dict[Tuple[float, float], None] = {}
    for pt in node_coords_raw:
        unique_coords_dict[pt] = None
    for pts in edge_geom_map.values():
        for pt in pts:
            unique_coords_dict[pt] = None

    unique_coords_list = list(unique_coords_dict.keys())
    logger.info(
        "Batch querying elevations for %d unique locations (%d nodes, %d curved edge geometries) via %s",
        len(unique_coords_list),
        len(node_ids),
        len(edge_geom_map),
        provider.source_name,
    )
    raw_elevations = provider.get_elevations(unique_coords_list)
    elev_lookup: Dict[Tuple[float, float], Optional[float]] = {
        coord: elev for coord, elev in zip(unique_coords_list, raw_elevations)
    }

    # Populate node elevation attributes
    known_elevations: List[float] = []
    for node_id, coord in zip(node_ids, node_coords_raw):
        node_data = graph.nodes[node_id]
        elev = elev_lookup.get(coord)
        if elev is not None and not math.isnan(elev):
            node_data["elevation_m"] = float(elev)
            node_data["elevation_source"] = provider.source_name
            node_data["elevation_status"] = "MEASURED"
            node_data["elevation_evidence"] = NodeElevationEvidence(
                elevation_m=float(elev),
                source=provider.source_name,
                status="MEASURED",
                is_known=True,
            )
            known_elevations.append(float(elev))
        else:
            node_data["elevation_m"] = None
            node_data["elevation_source"] = "UNKNOWN"
            node_data["elevation_status"] = "MISSING"
            node_data["elevation_evidence"] = NodeElevationEvidence(
                elevation_m=None,
                source="UNKNOWN",
                status="MISSING",
                is_known=False,
            )

    # =========================================================================
    # 2. EDGE GRADE & DIRECTIONAL TERRAIN CALCULATION
    # =========================================================================
    edges_with_grade = 0
    suspicious_edges_count = 0

    for u, v, k, edge_data in graph.edges(keys=True, data=True):
        elev_u = graph.nodes[u].get("elevation_m")
        elev_v = graph.nodes[v].get("elevation_m")
        length_m = float(edge_data.get("length", 1.0))

        # Check existing findings set or create new
        findings_set = set(edge_data.get("findings", []))
        if isinstance(edge_data.get("findings"), set):
            findings_set = edge_data["findings"]

        if elev_u is None or elev_v is None:
            # Elevation is unrecorded/missing for at least one endpoint
            findings_set.add(FindingType.ELEVATION_EVIDENCE_MISSING.value)
            terrain_evidence = EdgeTerrainEvidence(
                length_m=length_m,
                is_known=False,
                elevation_source="UNKNOWN",
            )
        else:
            edges_with_grade += 1
            delta_z = elev_v - elev_u
            signed_grade = delta_z / max(length_m, 0.1)
            abs_grade = abs(signed_grade)

            # Classify directional slope relative to traversal
            if signed_grade >= 0.02:
                direction = SlopeDirection.UPHILL
            elif signed_grade <= -0.02:
                direction = SlopeDirection.DOWNHILL
            else:
                direction = SlopeDirection.FLAT

            # Detect suspicious or jittered grades on short edges (Requirement 8)
            is_steps_or_ramp = (
                "steps" in str(edge_data.get("highway", "")).lower()
                or bool(edge_data.get("has_ramp", False))
                or bool(edge_data.get("has_wheelchair_ramp", False))
            )
            is_short = length_m < min_reliable_edge_length_m
            is_suspicious = False

            if is_short and abs(delta_z) > 0.4 and not is_steps_or_ramp:
                is_suspicious = True
            elif abs_grade > SUSPICIOUS_GRADE_THRESHOLD and not is_steps_or_ramp:
                is_suspicious = True

            if is_suspicious:
                suspicious_edges_count += 1
                findings_set.add(FindingType.SUSPICIOUS_GRADE_FLAGGED.value)

            # Estimated 1-sigma uncertainty on grade
            grade_uncertainty = (2.0 * dem_vertical_accuracy_m) / max(length_m, 1.0)

            # Geometry-aware intermediate climb / descent sampling (Requirement 9)
            gain_m = max(0.0, delta_z)
            loss_m = max(0.0, -delta_z)
            max_intermediate_grade = abs_grade
            sample_count = 2

            if (u, v, k) in edge_geom_map:
                intermediate_coords = edge_geom_map[(u, v, k)]
                sample_count = len(intermediate_coords)
                intermediate_elevs = [elev_lookup.get(pt) for pt in intermediate_coords]
                valid_elevs = [e for e in intermediate_elevs if e is not None]

                if len(valid_elevs) == len(intermediate_coords):
                    # Compute piecewise elevation gain and loss
                    calc_gain = 0.0
                    calc_loss = 0.0
                    max_sub_grade = 0.0

                    for i in range(len(valid_elevs) - 1):
                        dz = valid_elevs[i + 1] - valid_elevs[i]
                        p1 = intermediate_coords[i]
                        p2 = intermediate_coords[i + 1]
                        # Approximate sub-segment distance
                        dlat = (p2[0] - p1[0]) * 111139.0
                        dlon = (p2[1] - p1[1]) * (111139.0 * math.cos(math.radians(p1[0])))
                        sub_dist = max(math.hypot(dlat, dlon), 1.0)
                        sub_grade = abs(dz) / sub_dist

                        if dz > 0:
                            calc_gain += dz
                        else:
                            calc_loss += abs(dz)

                        if sub_grade > max_sub_grade:
                            max_sub_grade = sub_grade

                    gain_m = calc_gain
                    loss_m = calc_loss
                    max_intermediate_grade = max(max_sub_grade, abs_grade)

            findings_set.add(FindingType.ELEVATION_EVIDENCE_AVAILABLE.value)

            # Incline category findings
            if signed_grade >= 0.08:
                findings_set.add(FindingType.STEEP_UPHILL_RECORDED.value)
                findings_set.add(FindingType.STEEP_INCLINE_RECORDED.value)
            elif signed_grade >= 0.05:
                findings_set.add(FindingType.MODERATE_UPHILL_RECORDED.value)

            if signed_grade <= -0.08:
                findings_set.add(FindingType.STEEP_DOWNHILL_RECORDED.value)
                findings_set.add(FindingType.STEEP_INCLINE_RECORDED.value)
            elif signed_grade <= -0.05:
                findings_set.add(FindingType.MODERATE_DOWNHILL_RECORDED.value)

            terrain_evidence = EdgeTerrainEvidence(
                elevation_start_m=elev_u,
                elevation_end_m=elev_v,
                elevation_change_m=delta_z,
                length_m=length_m,
                signed_grade=signed_grade,
                absolute_grade=abs_grade,
                direction=direction,
                is_grade_suspicious=is_suspicious,
                grade_uncertainty=grade_uncertainty,
                elevation_source=provider.source_name,
                elevation_gain_m=gain_m,
                elevation_loss_m=loss_m,
                max_intermediate_grade=max_intermediate_grade,
                sample_count=sample_count,
                is_known=True,
            )

        # Attach to edge dictionary
        edge_data["terrain_evidence"] = terrain_evidence
        edge_data["findings"] = findings_set
        edge_data["grade"] = terrain_evidence.signed_grade
        edge_data["elevation_change_m"] = terrain_evidence.elevation_change_m
        edge_data["slope_direction"] = terrain_evidence.direction.value
        edge_data["is_grade_suspicious"] = terrain_evidence.is_grade_suspicious

    total_nodes = len(graph.nodes)
    nodes_with_elev = len(known_elevations)
    coverage_pct = (nodes_with_elev / total_nodes * 100.0) if total_nodes > 0 else 0.0

    return ElevationEnrichmentSummary(
        total_nodes=total_nodes,
        nodes_with_elevation=nodes_with_elev,
        elevation_coverage_pct=round(coverage_pct, 2),
        total_edges=graph.number_of_edges(),
        edges_with_grade=edges_with_grade,
        suspicious_edges_count=suspicious_edges_count,
        min_elevation_m=min(known_elevations) if known_elevations else None,
        max_elevation_m=max(known_elevations) if known_elevations else None,
        elevation_source=provider.source_name,
    )
