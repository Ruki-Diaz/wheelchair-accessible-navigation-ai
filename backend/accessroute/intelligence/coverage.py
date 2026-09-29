"""Regional Accessibility Data Coverage Analyzer.

Stage 10 Architecture:
Audits pedestrian graphs and persistent community databases to quantify:
- Surface metadata completeness
- Kerb ramp transition completeness
- Wheelchair tag completeness
- Clear path width completeness
- Barrier accessibility completeness
- Elevation/terrain coverage
- Conflict and stale evidence density

Generates GeoJSON FeatureCollections for rendering interactive data coverage maps.
"""

from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from accessroute.community.models import ObservationCategory
from accessroute.community.repository import CommunityObservationRepository
from accessroute.scoring.models import KerbType, SurfaceType


class RegionalCoverageAnalyzer:
    """Computes comprehensive accessibility data coverage and completeness statistics."""

    @staticmethod
    def analyze_graph_coverage(
        graph: nx.MultiDiGraph,
        community_repo: Optional[CommunityObservationRepository] = None,
        region_id: str = "unknown_region",
    ) -> Dict[str, Any]:
        """Compute accessibility completeness percentages across a pedestrian network."""
        total_edges = 0
        total_length_m = 0.0

        surface_known_len = 0.0
        wheelchair_known_len = 0.0
        width_known_len = 0.0
        terrain_known_len = 0.0

        crossings_total = 0
        crossings_known_kerb = 0

        barriers_total = 0
        barriers_known = 0

        for u, v, k, d in graph.edges(keys=True, data=True):
            total_edges += 1
            length = float(d.get("length", 0.0))
            total_length_m += length

            # Surface completeness
            surf = str(d.get("surface", "unknown")).lower()
            ev = d.get("_accessibility_evidence")
            if (ev and ev.surface != SurfaceType.UNKNOWN) or (surf not in ("unknown", "none", "nan", "")):
                surface_known_len += length

            # Wheelchair tag
            wc = str(d.get("wheelchair", "unknown")).lower()
            if wc not in ("unknown", "none", "nan", ""):
                wheelchair_known_len += length

            # Width tag
            w = d.get("width")
            if w is not None and str(w).lower() not in ("unknown", "none", "nan", ""):
                width_known_len += length

            # Terrain
            elev_src = str(d.get("elevation_source", "UNKNOWN"))
            if elev_src != "UNKNOWN" or d.get("absolute_grade") is not None:
                terrain_known_len += length

            # Crossings & kerbs
            hw = str(d.get("highway", "")).lower()
            is_cross = bool(d.get("is_crossing")) or hw == "crossing"
            if is_cross:
                crossings_total += 1
                kerb = str(d.get("kerb", "unknown")).lower()
                if (ev and ev.kerb != KerbType.UNKNOWN) or (kerb not in ("unknown", "none", "nan", "")):
                    crossings_known_kerb += 1

        # Check barrier nodes
        for n, nd in graph.nodes(data=True):
            if "barrier" in nd:
                barriers_total += 1
                if "wheelchair" in nd or "maxwidth" in nd:
                    barriers_known += 1

        # Avoid zero division
        tot_len = max(1.0, total_length_m)
        surface_pct = (surface_known_len / tot_len) * 100.0
        wheelchair_pct = (wheelchair_known_len / tot_len) * 100.0
        width_pct = (width_known_len / tot_len) * 100.0
        terrain_pct = (terrain_known_len / tot_len) * 100.0
        kerb_pct = (crossings_known_kerb / max(1, crossings_total)) * 100.0 if crossings_total > 0 else 100.0
        barrier_pct = (barriers_known / max(1, barriers_total)) * 100.0 if barriers_total > 0 else 100.0

        # Weighted overall completeness
        overall_completeness = (
            surface_pct * 0.30 +
            kerb_pct * 0.35 +
            terrain_pct * 0.15 +
            wheelchair_pct * 0.10 +
            width_pct * 0.10
        )

        if overall_completeness >= 80.0:
            coverage_band = "High metadata coverage"
        elif overall_completeness >= 50.0:
            coverage_band = "Moderate metadata coverage"
        elif overall_completeness >= 25.0:
            coverage_band = "Limited metadata coverage"
        else:
            coverage_band = "Critical verification needed"

        # Community repository metrics
        comm_count = 0
        if community_repo:
            comm_count = community_repo.count(include_expired=False)

        return {
            "region_id": region_id,
            "total_edges": total_edges,
            "total_network_length_m": round(total_length_m, 1),
            "surface_completeness_pct": round(surface_pct, 1),
            "kerb_completeness_pct": round(kerb_pct, 1),
            "crossings_count": crossings_total,
            "crossings_with_kerb_info_count": crossings_known_kerb,
            "wheelchair_completeness_pct": round(wheelchair_pct, 1),
            "width_completeness_pct": round(width_pct, 1),
            "barrier_completeness_pct": round(barrier_pct, 1),
            "terrain_coverage_pct": round(terrain_pct, 1),
            "overall_completeness_pct": round(overall_completeness, 1),
            "coverage_band": coverage_band,
            "active_community_observations_count": comm_count,
        }

    @staticmethod
    def generate_coverage_geojson(
        graph: nx.MultiDiGraph,
        region_id: str = "coverage_region",
        sample_step: int = 5,
    ) -> Dict[str, Any]:
        """Generate GeoJSON lines colored by completeness level for visualization."""
        features: List[Dict[str, Any]] = []

        edge_list = list(graph.edges(keys=True, data=True))
        for idx in range(0, len(edge_list), sample_step):
            u, v, k, d = edge_list[idx]
            u_node = graph.nodes.get(u, {})
            v_node = graph.nodes.get(v, {})

            geom = d.get("geometry")
            coords: List[List[float]] = []
            if geom is not None and hasattr(geom, "coords"):
                coords = [[float(lon), float(lat)] for lon, lat in geom.coords]
            elif "x" in u_node and "y" in u_node and "x" in v_node and "y" in v_node:
                coords = [
                    [float(u_node["x"]), float(u_node["y"])],
                    [float(v_node["x"]), float(v_node["y"])],
                ]

            if not coords:
                continue

            surf = str(d.get("surface", "unknown")).lower()
            kerb = str(d.get("kerb", "unknown")).lower()
            hw = str(d.get("highway", "footway")).lower()
            is_cross = bool(d.get("is_crossing")) or hw == "crossing"

            # Completeness score for this edge [0 to 3]
            score = 0
            if surf != "unknown":
                score += 1
            if is_cross:
                if kerb != "unknown":
                    score += 2
            else:
                score += 1
            if d.get("absolute_grade") is not None:
                score += 1

            # Style mapping
            if score >= 3:
                color = "#10b981"  # Emerald: verified/complete
                status = "complete"
            elif score == 2:
                color = "#3b82f6"  # Blue: moderate
                status = "moderate"
            elif score == 1:
                color = "#f59e0b"  # Amber: partial
                status = "partial"
            else:
                color = "#ef4444"  # Red: missing/unknown
                status = "unknown"

            features.append({
                "type": "Feature",
                "id": f"coverage_edge_{idx}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
                "properties": {
                    "feature_type": "coverage_edge",
                    "status": status,
                    "surface": surf,
                    "highway": hw,
                    "is_crossing": is_cross,
                    "kerb": kerb,
                    "completeness_score": score,
                    "style": {
                        "color": color,
                        "weight": 3,
                        "opacity": 0.8,
                    },
                },
            })

        return {
            "type": "FeatureCollection",
            "properties": {
                "region_id": region_id,
                "coverage_edges_count": len(features),
            },
            "features": features,
        }
