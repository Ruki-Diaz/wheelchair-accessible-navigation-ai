"""Deterministic route progress tracker and geometry projection engine."""

import math
from typing import Any, Dict, List, Optional, Tuple

from accessroute.navigation.models import (
    AccuracyQualityBand,
    DeviationState,
    GPSLocation,
    RouteProgress,
    UpcomingAccessibilityEvent,
    UpcomingEventType,
)
from accessroute.routing.directions import DirectionStep
from accessroute.routing.heuristics import haversine_distance

STANDARD_PACE_METERS_PER_MIN = 60.0  # 3.6 km/h wheelchair / pedestrian pace
ARRIVAL_RADIUS_METERS = 20.0
ARRIVAL_MAX_ACCURACY_METERS = 35.0
LOOKAHEAD_WINDOW_METERS = 180.0


def latlon_to_meters_factor(lat_deg: float) -> Tuple[float, float]:
    """Calculate meters per degree for latitude and longitude at a given latitude."""
    lat_rad = math.radians(lat_deg)
    m_per_deg_lat = 111132.954 - 559.822 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lat, m_per_deg_lon


def project_point_to_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> Tuple[float, float, float, float]:
    """Project 2D metric point P onto segment AB.

    Returns:
        (proj_x, proj_y, t, distance_m) where t is clamped to [0, 1].
    """
    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq <= 1e-9:
        dist = math.hypot(px - ax, py - ay)
        return ax, ay, 0.0, dist

    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))

    proj_x = ax + t_clamped * dx
    proj_y = ay + t_clamped * dy
    dist = math.hypot(px - proj_x, py - proj_y)
    return proj_x, proj_y, t_clamped, dist


class RouteProgressTracker:
    """Tracks live progress along a selected route using geometric projection."""

    def __init__(
        self,
        route_coordinates: List[Tuple[float, float]],
        directions: Optional[List[DirectionStep]] = None,
        edge_metadata: Optional[List[Dict[str, Any]]] = None,
        pace_meters_per_min: float = STANDARD_PACE_METERS_PER_MIN,
    ):
        if len(route_coordinates) < 2:
            raise ValueError("Route coordinates must contain at least 2 points.")

        self.coordinates = route_coordinates
        self.directions = directions or []
        self.edge_metadata = edge_metadata or []
        self.pace_m_per_min = pace_meters_per_min

        # Precompute segment lengths and cumulative distances
        self.segment_lengths: List[float] = []
        self.cumulative_segment_distances: List[float] = [0.0]
        total_len = 0.0

        for i in range(len(self.coordinates) - 1):
            p1 = self.coordinates[i]
            p2 = self.coordinates[i + 1]
            seg_len = haversine_distance(p1[0], p1[1], p2[0], p2[1])
            self.segment_lengths.append(seg_len)
            total_len += seg_len
            self.cumulative_segment_distances.append(total_len)

        self.total_route_distance_m = total_len
        self.destination_point = self.coordinates[-1]

        # State tracking
        self.last_segment_idx = 0
        self.max_distance_along_route_m = 0.0
        self.consecutive_arrival_count = 0

    def update_progress(
        self,
        location: GPSLocation,
        deviation_state: Optional[DeviationState] = None,
    ) -> RouteProgress:
        """Calculate route progress for a new GPS location."""
        lat = location.latitude
        lon = location.longitude
        accuracy = location.accuracy_m

        # Destination arrival check
        dist_to_dest = haversine_distance(lat, lon, self.destination_point[0], self.destination_point[1])
        if dist_to_dest <= ARRIVAL_RADIUS_METERS and accuracy <= ARRIVAL_MAX_ACCURACY_METERS:
            self.consecutive_arrival_count += 1
        else:
            self.consecutive_arrival_count = max(0, self.consecutive_arrival_count - 1)

        is_arrived = self.consecutive_arrival_count >= 2

        # 1. Project onto route geometry
        m_lat, m_lon = latlon_to_meters_factor(lat)
        px = lon * m_lon
        py = lat * m_lat

        best_dist = float("inf")
        best_seg_idx = self.last_segment_idx
        best_t = 0.0
        best_proj_lat = self.coordinates[0][0]
        best_proj_lon = self.coordinates[0][1]

        # Scan candidate segments (windowed search around last position to avoid backward loop snapping)
        start_idx = max(0, self.last_segment_idx - 1)
        end_idx = min(len(self.segment_lengths), self.last_segment_idx + 10)
        
        # If searching locally yields high distance, expand to entire route
        candidate_indices = list(range(start_idx, end_idx))
        if len(candidate_indices) < len(self.segment_lengths):
            candidate_indices += [i for i in range(len(self.segment_lengths)) if i not in candidate_indices]

        for i in candidate_indices:
            p1 = self.coordinates[i]
            p2 = self.coordinates[i + 1]

            ax = p1[1] * m_lon
            ay = p1[0] * m_lat
            bx = p2[1] * m_lon
            by = p2[0] * m_lat

            proj_x, proj_y, t, dist = project_point_to_segment(px, py, ax, ay, bx, by)

            if dist < best_dist:
                best_dist = dist
                best_seg_idx = i
                best_t = t
                best_proj_lat = proj_y / m_lat
                best_proj_lon = proj_x / m_lon

        # Distance along route
        seg_start_dist = self.cumulative_segment_distances[best_seg_idx]
        seg_len = self.segment_lengths[best_seg_idx]
        calc_distance_along = seg_start_dist + (best_t * seg_len)

        # Monotonic forward progress dampening (don't jump backward on noisy points unless deviation confirmed)
        if deviation_state != DeviationState.OFF_ROUTE:
            if calc_distance_along >= self.max_distance_along_route_m - 15.0:
                self.max_distance_along_route_m = max(self.max_distance_along_route_m, calc_distance_along)
                self.last_segment_idx = best_seg_idx
                distance_along = self.max_distance_along_route_m
            else:
                distance_along = self.max_distance_along_route_m
        else:
            distance_along = calc_distance_along
            self.last_segment_idx = best_seg_idx

        distance_along = min(self.total_route_distance_m, max(0.0, distance_along))
        remaining_dist = max(0.0, self.total_route_distance_m - distance_along)
        completion_pct = (
            (distance_along / self.total_route_distance_m * 100.0)
            if self.total_route_distance_m > 0
            else 100.0
        )

        # 2. Next instruction and distance
        current_step_idx = 0
        next_maneuver = "straight"
        next_instruction = "Continue straight along path."
        dist_to_next_step = remaining_dist

        for idx, step in enumerate(self.directions):
            if step.cumulative_distance_m > distance_along + 2.0:
                current_step_idx = idx
                dist_to_next_step = max(0.0, step.cumulative_distance_m - distance_along)
                if idx == 0 and distance_along < 10.0:
                    # At the beginning of route, announce the departure step
                    next_maneuver = step.maneuver
                    next_instruction = step.instruction
                elif idx + 1 < len(self.directions):
                    next_maneuver = self.directions[idx + 1].maneuver
                    next_instruction = f"In {dist_to_next_step:.0f}m, {self.directions[idx + 1].instruction.lower()}"
                else:
                    next_maneuver = step.maneuver
                    next_instruction = step.instruction
                break
        else:
            if self.directions:
                current_step_idx = len(self.directions) - 1
                next_maneuver = self.directions[-1].maneuver
                next_instruction = self.directions[-1].instruction
                dist_to_next_step = remaining_dist

        # 3. Estimated duration remaining (minutes)
        est_duration_min = max(1, math.ceil(remaining_dist / self.pace_m_per_min)) if remaining_dist > 5.0 else 0

        # 4. Upcoming accessibility events
        upcoming_events = self._detect_upcoming_events(distance_along)

        effective_dev_state = deviation_state or (
            DeviationState.ON_ROUTE if best_dist <= max(20.0, accuracy * 1.5) else DeviationState.POSSIBLY_OFF_ROUTE
        )

        return RouteProgress(
            distance_along_route_m=distance_along,
            remaining_distance_m=remaining_dist,
            completion_percentage=completion_pct,
            nearest_point=(best_proj_lat, best_proj_lon),
            cross_track_distance_m=best_dist,
            current_segment_index=best_seg_idx,
            current_step_index=current_step_idx,
            next_maneuver=next_maneuver,
            next_instruction=next_instruction,
            distance_to_next_maneuver_m=dist_to_next_step,
            estimated_remaining_duration_min=est_duration_min,
            deviation_state=effective_dev_state,
            accuracy_band=location.quality_band,
            is_arrived=is_arrived,
            upcoming_events=upcoming_events,
        )

    def _detect_upcoming_events(self, current_distance_along_m: float) -> List[UpcomingAccessibilityEvent]:
        """Scan ahead along route to identify upcoming physical infrastructure findings."""
        events: List[UpcomingAccessibilityEvent] = []
        lookahead_limit = current_distance_along_m + LOOKAHEAD_WINDOW_METERS

        # Inspect edge metadata
        for idx, edge in enumerate(self.edge_metadata):
            if idx >= len(self.cumulative_segment_distances) - 1:
                break
            seg_start = self.cumulative_segment_distances[idx]
            seg_end = self.cumulative_segment_distances[idx + 1]

            # If segment is ahead within lookahead window
            if seg_end >= current_distance_along_m and seg_start <= lookahead_limit:
                distance_ahead = max(0.0, seg_start - current_distance_along_m)
                highway = edge.get("highway", "path")
                is_crossing = edge.get("is_crossing", False)
                kerb = edge.get("kerb", "unknown")
                surface = edge.get("surface", "unknown")
                grade = edge.get("estimated_grade_pct", 0.0)

                # Kerb unknown at crossing
                if is_crossing and kerb in ("unknown", None, ""):
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.KERB_UNKNOWN.value,
                            distance_ahead_m=distance_ahead,
                            severity="warning",
                            evidence_source="osm",
                            description=f"Road crossing in {distance_ahead:.0f}m — kerb ramp status unrecorded in OpenStreetMap.",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )
                elif is_crossing and kerb == "lowered":
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.KERB_LOWERED.value,
                            distance_ahead_m=distance_ahead,
                            severity="info",
                            evidence_source="osm",
                            description=f"Mapped lowered kerb in {distance_ahead:.0f}m.",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )
                elif is_crossing and kerb == "raised":
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.KERB_RAISED.value,
                            distance_ahead_m=distance_ahead,
                            severity="critical",
                            evidence_source="osm",
                            description=f"Mapped raised kerb barrier in {distance_ahead:.0f}m.",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )

                # Stairs
                if edge.get("is_steps") or highway == "steps":
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.STAIRS.value,
                            distance_ahead_m=distance_ahead,
                            severity="critical",
                            evidence_source="osm",
                            description=f"Mapped stairs in {distance_ahead:.0f}m.",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )

                # Unpaved surface
                if surface in ("gravel", "fine_gravel", "dirt", "ground", "grass", "earth", "mud", "sand"):
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.UNPAVED_SURFACE.value,
                            distance_ahead_m=distance_ahead,
                            severity="warning",
                            evidence_source="osm",
                            description=f"Mapped unpaved surface ({surface}) begins in {distance_ahead:.0f}m.",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )

                # Steep estimated grade
                if grade is not None and abs(grade) >= 6.0:
                    events.append(
                        UpcomingAccessibilityEvent(
                            type=UpcomingEventType.STEEP_ESTIMATED_GRADE.value,
                            distance_ahead_m=distance_ahead,
                            severity="warning",
                            evidence_source="copernicus_dem",
                            description=f"Estimated {abs(grade):.1f}% slope begins in {distance_ahead:.0f}m (Copernicus DEM).",
                            segment_id=str(edge.get("osmid", idx)),
                        )
                    )

                # Active community observations attached to segment
                comm_obs = edge.get("community_evidence", [])
                for obs in comm_obs:
                    cat = obs.get("category", "")
                    val = obs.get("value", "")
                    status = obs.get("verification_status", "unverified")
                    if cat in ("path_blocked", "construction"):
                        events.append(
                            UpcomingAccessibilityEvent(
                                type=UpcomingEventType.COMMUNITY_BLOCKAGE.value if cat == "path_blocked" else UpcomingEventType.CONSTRUCTION.value,
                                distance_ahead_m=distance_ahead,
                                severity="critical" if status in ("verified", "community_supported") else "warning",
                                evidence_source="community",
                                description=f"Community reported {cat.replace('_', ' ')} ({val}) {distance_ahead:.0f}m ahead [{status.upper()}].",
                                segment_id=str(obs.get("id", idx)),
                                verification_status=status,
                            )
                        )

        # Sort by distance ahead
        events.sort(key=lambda e: e.distance_ahead_m)
        return events[:5]  # Limit to top 5 immediate upcoming events
