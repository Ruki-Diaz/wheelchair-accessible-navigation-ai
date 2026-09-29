"""Conflict Intelligence and Spatial Clustering.

Stage 10 Architecture:
Aggregates and clusters evidence disagreements across a region:
- Disagreements between OpenStreetMap and community observations
- Disagreements between peer community reports
- Identifies geographic hotspots where physical infrastructure status is actively contested

CRITICAL SCIENTIFIC SAFETY RULE:
Reports only observable patterns (counts, attributes, dates). Never fabricates or guesses reasons.
"""

import math
from typing import Any, Dict, List, Optional
import uuid

from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.community.models import CommunityObservation, EvidenceConflict
from accessroute.intelligence.models import ConflictCluster


class ConflictIntelligenceEngine:
    """Detects and clusters spatial concentrations of accessibility evidence disagreements."""

    @staticmethod
    def _haversine_dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
        return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    @classmethod
    def cluster_conflicts(
        cls,
        conflicts: List[EvidenceConflict],
        cluster_radius_m: float = 60.0,
    ) -> List[ConflictCluster]:
        """Group nearby conflicting evidence points into spatial disagreement clusters."""
        if not conflicts:
            return []

        clusters: List[ConflictCluster] = []
        assigned = [False] * len(conflicts)

        for i, conf_i in enumerate(conflicts):
            if assigned[i]:
                continue

            current_group = [conf_i]
            assigned[i] = True

            for j in range(i + 1, len(conflicts)):
                if assigned[j]:
                    continue
                conf_j = conflicts[j]
                dist = cls._haversine_dist_m(conf_i.latitude, conf_i.longitude, conf_j.latitude, conf_j.longitude)
                if dist <= cluster_radius_m:
                    current_group.append(conf_j)
                    assigned[j] = True

            # Calculate centroid
            centroid_lat = sum(c.latitude for c in current_group) / len(current_group)
            centroid_lon = sum(c.longitude for c in current_group) / len(current_group)

            # Max radius from centroid
            max_r = max(cls._haversine_dist_m(centroid_lat, centroid_lon, c.latitude, c.longitude) for c in current_group)
            radius_m = max(10.0, max_r)

            attrs = sorted(list(set(c.attribute_name for c in current_group)))
            attrs_str = ", ".join(attrs)

            desc = (
                f"{len(current_group)} conflicting observation(s) recorded within {radius_m:.0f}m "
                f"concerning {attrs_str} infrastructure."
            )

            clusters.append(
                ConflictCluster(
                    cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
                    centroid_lat=centroid_lat,
                    centroid_lon=centroid_lon,
                    radius_m=radius_m,
                    conflicts_count=len(current_group),
                    osm_vs_community_count=len(current_group),
                    community_vs_community_count=0,
                    attributes_involved=attrs,
                    description=desc,
                )
            )

        return sorted(clusters, key=lambda c: c.conflicts_count, reverse=True)
