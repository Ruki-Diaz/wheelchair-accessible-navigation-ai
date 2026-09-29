"""Offline Route and Mission Packaging Service.

Extracts complete, self-contained snapshots of calculated routes, entrance metadata,
elevation profiles, maneuvers, and active community observations for offline use.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from accessroute.community.models import CommunityObservation
from accessroute.community.repository import CommunityObservationRepository
from accessroute.intelligence.missions import VerificationMissionEngine
from accessroute.intelligence.priority import VerificationPriorityEngine
from accessroute.offline.models import OfflineMissionPackage, OfflineRoutePackage

logger = logging.getLogger(__name__)


class OfflinePackageManager:
    """Constructs offline route and mission packages adhering to schema versioning."""

    @staticmethod
    def build_route_package(
        route_data: Dict[str, Any],
        origin: Dict[str, float],
        destination: Dict[str, float],
        destination_name: str = "Destination",
        selected_entrance: Optional[Dict[str, Any]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        community_repo: Optional[CommunityObservationRepository] = None,
        route_id: Optional[str] = None,
    ) -> OfflineRoutePackage:
        """Serialize a calculated route alternative or plan into an OfflineRoutePackage."""
        now_str = datetime.now(timezone.utc).isoformat()
        route_id_val = route_id or route_data.get("route_id") or route_data.get("key") or "route_offline"

        # Coordinates & geometry
        route_geometry: List[List[float]] = []
        if "geojson" in route_data and isinstance(route_data["geojson"], dict):
            features = route_data["geojson"].get("features", [])
            for feat in features:
                geom = feat.get("geometry", {})
                if geom.get("type") == "LineString":
                    # GeoJSON is [lon, lat], convert to [lat, lon]
                    for pt in geom.get("coordinates", []):
                        if len(pt) >= 2:
                            route_geometry.append([float(pt[1]), float(pt[0])])
        elif "geometry" in route_data and isinstance(route_data["geometry"], list):
            route_geometry = route_data["geometry"]

        origin_lat = float(origin.get("latitude") if "latitude" in origin else origin.get("lat", 0.0))
        origin_lon = float(origin.get("longitude") if "longitude" in origin else origin.get("lon", 0.0))
        dest_lat = float(destination.get("latitude") if "latitude" in destination else destination.get("lat", 0.0))
        dest_lon = float(destination.get("longitude") if "longitude" in destination else destination.get("lon", 0.0))

        # Calculate bounding box from geometry or origin/dest
        lats = [pt[0] for pt in route_geometry] if route_geometry else [origin_lat, dest_lat]
        lons = [pt[1] for pt in route_geometry] if route_geometry else [origin_lon, dest_lon]
        min_lat = min(lats) - 0.005
        max_lat = max(lats) + 0.005
        min_lon = min(lons) - 0.005
        max_lon = max(lons) + 0.005
        region_bounds = [min_lat, min_lon, max_lat, max_lon]

        # Maneuvers
        maneuvers: List[Dict[str, Any]] = []
        directions = route_data.get("directions") or route_data.get("maneuvers") or []
        for step in directions:
            if hasattr(step, "model_dump"):
                maneuvers.append(step.model_dump())
            elif isinstance(step, dict):
                maneuvers.append(step)

        # Elevation profile
        elevation_profile = route_data.get("elevation_profile") or route_data.get("elevation_summary")
        if hasattr(elevation_profile, "model_dump"):
            elevation_profile = elevation_profile.model_dump()

        # Physical metrics
        distance_m = float(route_data.get("physical_distance_m", route_data.get("distance_m", 0.0)))
        duration_min = int(route_data.get("estimated_duration_min", max(1, int(distance_m / 65.0))))

        # Entrance
        entrance_coords = None
        if selected_entrance:
            ent_lat = selected_entrance.get("latitude") if "latitude" in selected_entrance else selected_entrance.get("lat", dest_lat)
            ent_lon = selected_entrance.get("longitude") if "longitude" in selected_entrance else selected_entrance.get("lon", dest_lon)
            if isinstance(selected_entrance, (list, tuple)) and len(selected_entrance) >= 2:
                ent_lat, ent_lon = selected_entrance[0], selected_entrance[1]
            entrance_coords = {
                "latitude": float(ent_lat),
                "longitude": float(ent_lon),
            }

        # Community observations snapshot along the route corridor
        community_snapshot: List[Dict[str, Any]] = []
        if community_repo:
            try:
                obs_list = community_repo.get_by_bbox(min_lat, min_lon, max_lat, max_lon, include_expired=False)
                community_snapshot = [obs.to_dict() for obs in obs_list if obs.is_active()]
            except Exception as e:
                logger.warning("Could not fetch community observations for offline route package: %s", e)

        # Route segments
        route_segments = route_data.get("route_segments") or []

        # Upcoming accessibility events derived from maneuvers or findings
        upcoming_events = []
        for m in maneuvers:
            if m.get("accessibility_cues") or m.get("barrier_warnings"):
                upcoming_events.append({
                    "step_index": m.get("step_index"),
                    "instruction": m.get("instruction"),
                    "latitude": m.get("latitude"),
                    "longitude": m.get("longitude"),
                    "cues": m.get("accessibility_cues", []),
                    "warnings": m.get("barrier_warnings", []),
                })

        return OfflineRoutePackage(
            route_id=route_id_val,
            created_at=now_str,
            downloaded_at=now_str,
            origin=origin,
            destination=destination,
            destination_name=destination_name,
            selected_entrance=selected_entrance,
            entrance_coordinates=entrance_coords,
            mobility_preferences_snapshot=preferences or {},
            route_geometry=route_geometry,
            route_segments=route_segments,
            maneuvers=maneuvers,
            distance_m=distance_m,
            estimated_duration_min=duration_min,
            elevation_profile=elevation_profile,
            accessibility_findings=route_data.get("explanations", route_data.get("accessibility_findings", [])),
            upcoming_accessibility_events=upcoming_events,
            evidence_quality=route_data.get("evidence_quality"),
            osm_evidence=route_data.get("osm_evidence", []),
            terrain_evidence=route_data.get("terrain_evidence"),
            community_evidence_snapshot=community_snapshot,
            known_conflicts=route_data.get("known_conflicts", []),
            data_timestamp=now_str,
            region_bounds=region_bounds,
            package_version="1.0.0",
            schema_version="stage14_v1",
        )

    @staticmethod
    def build_mission_packages(
        missions_data: List[Dict[str, Any]],
    ) -> List[OfflineMissionPackage]:
        """Convert a list of verification missions into offline packages."""
        now_str = datetime.now(timezone.utc).isoformat()
        packages: List[OfflineMissionPackage] = []

        for m in missions_data:
            coords = m.get("target_coordinates") or m.get("coordinates") or {"latitude": 0.0, "longitude": 0.0}
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                coords = {"latitude": float(coords[0]), "longitude": float(coords[1])}

            pkg = OfflineMissionPackage(
                mission_id=m.get("mission_id", f"msn_{len(packages) + 1}"),
                coordinates=coords,
                feature_type=m.get("feature_type", "crossing"),
                missing_attribute=m.get("missing_attribute", "kerb"),
                priority=str(m.get("priority", "HIGH")),
                why_it_matters=m.get("why_it_matters", "Critical infrastructure accessibility verification."),
                suggested_actions=m.get("suggested_actions", m.get("suggested_values", ["lowered", "flush", "raised"])),
                osm_element_id=m.get("target_element_id") or m.get("osm_element_id"),
                existing_evidence=m.get("existing_evidence", {}),
                downloaded_at=now_str,
            )
            packages.append(pkg)

        return packages
