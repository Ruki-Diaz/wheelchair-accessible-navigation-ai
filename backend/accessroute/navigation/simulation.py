"""Simulated location provider generating deterministic GPS test streams."""

import math
import random
from typing import Generator, List, Optional, Tuple

from accessroute.navigation.models import GPSLocation
from accessroute.navigation.tracker import latlon_to_meters_factor
from accessroute.routing.heuristics import haversine_distance


class SimulatedLocationProvider:
    """Generates deterministic simulated GPS streams for testing live navigation."""

    def __init__(
        self,
        route_coordinates: List[Tuple[float, float]],
        speed_mps: float = 1.0,  # 3.6 km/h pedestrian pace
        update_interval_s: float = 1.0,
        random_seed: int = 42,
    ):
        if len(route_coordinates) < 2:
            raise ValueError("Route must have at least 2 coordinates.")

        self.coordinates = route_coordinates
        self.speed_mps = speed_mps
        self.interval_s = update_interval_s
        self.step_distance_m = speed_mps * update_interval_s
        self.rng = random.Random(random_seed)

    def generate_normal_stream(self, noise_m: float = 3.0) -> Generator[GPSLocation, None, None]:
        """Generate smooth GPS readings walking the full route from start to finish."""
        curr_time = 1000000.0

        for i in range(len(self.coordinates) - 1):
            p1 = self.coordinates[i]
            p2 = self.coordinates[i + 1]
            seg_dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])

            if seg_dist <= 1e-3:
                continue

            num_steps = max(1, int(seg_dist / self.step_distance_m))
            m_lat, m_lon = latlon_to_meters_factor(p1[0])

            # Calculate segment bearing
            d_lat = p2[0] - p1[0]
            d_lon = p2[1] - p1[1]
            heading = math.degrees(math.atan2(d_lon * m_lon, d_lat * m_lat)) % 360.0

            for s in range(num_steps):
                t = s / num_steps
                lat = p1[0] + t * (p2[0] - p1[0])
                lon = p1[1] + t * (p2[1] - p1[1])

                # Add small realistic measurement jitter
                j_lat = (self.rng.uniform(-noise_m, noise_m)) / m_lat
                j_lon = (self.rng.uniform(-noise_m, noise_m)) / m_lon

                yield GPSLocation(
                    latitude=lat + j_lat,
                    longitude=lon + j_lon,
                    accuracy_m=round(self.rng.uniform(4.0, 8.0), 1),
                    heading=heading,
                    speed_mps=self.speed_mps,
                    timestamp=curr_time,
                )
                curr_time += self.interval_s

        # Final arrival coordinate
        final_pt = self.coordinates[-1]
        for _ in range(3):
            yield GPSLocation(
                latitude=final_pt[0],
                longitude=final_pt[1],
                accuracy_m=5.0,
                heading=0.0,
                speed_mps=0.0,
                timestamp=curr_time,
            )
            curr_time += self.interval_s

    def generate_jitter_stream(
        self,
        jitter_radius_m: float = 30.0,
        num_updates: int = 5,
    ) -> List[GPSLocation]:
        """Generate high-jitter readings around a stationary on-route point."""
        p = self.coordinates[len(self.coordinates) // 2]
        m_lat, m_lon = latlon_to_meters_factor(p[0])
        locations = []
        curr_time = 1000000.0

        for _ in range(num_updates):
            angle = self.rng.uniform(0, 2 * math.pi)
            rad = self.rng.uniform(10.0, jitter_radius_m)
            d_lat = (rad * math.cos(angle)) / m_lat
            d_lon = (rad * math.sin(angle)) / m_lon

            locations.append(
                GPSLocation(
                    latitude=p[0] + d_lat,
                    longitude=p[1] + d_lon,
                    accuracy_m=round(self.rng.uniform(25.0, 45.0), 1),  # Low accuracy
                    heading=None,
                    speed_mps=0.2,
                    timestamp=curr_time,
                )
            )
            curr_time += self.interval_s

        return locations

    def generate_deviation_stream(
        self,
        divergence_meters: float = 60.0,
        consecutive_points: int = 5,
    ) -> List[GPSLocation]:
        """Generate deliberate off-route deviation points well outside corridor."""
        p = self.coordinates[min(len(self.coordinates) - 1, 2)]
        m_lat, m_lon = latlon_to_meters_factor(p[0])
        locations = []
        curr_time = 1000000.0

        for i in range(1, consecutive_points + 1):
            offset = divergence_meters + (i * 5.0)
            # Offset to north-east
            d_lat = offset / m_lat
            d_lon = offset / m_lon

            locations.append(
                GPSLocation(
                    latitude=p[0] + d_lat,
                    longitude=p[1] + d_lon,
                    accuracy_m=6.0,  # High accuracy, legitimately off-route
                    heading=45.0,
                    speed_mps=self.speed_mps,
                    timestamp=curr_time,
                )
            )
            curr_time += self.interval_s

        return locations
