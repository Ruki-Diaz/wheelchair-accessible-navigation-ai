"""Robust route corridor deviation and off-route detector with GPS noise tolerance."""

from typing import Optional

from accessroute.navigation.models import AccuracyQualityBand, DeviationState, GPSLocation

DEFAULT_BASE_CORRIDOR_METERS = 20.0
DEFAULT_CONSECUTIVE_REQUIRED = 3
VERY_LOW_ACCURACY_THRESHOLD_M = 50.0


class RouteDeviationDetector:
    """Detects when a pedestrian has deviated from the planned route corridor."""

    def __init__(
        self,
        base_corridor_meters: float = DEFAULT_BASE_CORRIDOR_METERS,
        consecutive_required: int = DEFAULT_CONSECUTIVE_REQUIRED,
    ):
        self.base_corridor_m = base_corridor_meters
        self.consecutive_required = consecutive_required
        self.consecutive_off_count = 0
        self.last_state = DeviationState.ON_ROUTE

    def evaluate_deviation(
        self,
        cross_track_distance_m: float,
        location: GPSLocation,
    ) -> DeviationState:
        """Evaluate deviation state based on distance from route and GPS accuracy.

        Rules:
        1. If GPS accuracy is very poor (>50m), do NOT aggressively trigger OFF_ROUTE.
           Return POSSIBLY_OFF_ROUTE at most to prevent false rerouting.
        2. Dynamic corridor = max(base_corridor_m, accuracy_m * 1.5).
        3. If cross_track_distance <= dynamic corridor:
           user is within corridor -> ON_ROUTE (reset consecutive count).
        4. If cross_track_distance > dynamic corridor:
           increment consecutive_off_count.
           - If consecutive_off_count >= consecutive_required -> OFF_ROUTE.
           - Else -> POSSIBLY_OFF_ROUTE.
        """
        accuracy = location.accuracy_m

        # Dynamic corridor threshold accounts for GPS noise
        dynamic_corridor = max(self.base_corridor_m, accuracy * 1.5)

        # Very low accuracy damping: never declare confirmed OFF_ROUTE on uncalibrated GPS spikes
        if accuracy > VERY_LOW_ACCURACY_THRESHOLD_M:
            if cross_track_distance_m > dynamic_corridor:
                # Do not increment toward hard OFF_ROUTE
                self.last_state = DeviationState.POSSIBLY_OFF_ROUTE
                return DeviationState.POSSIBLY_OFF_ROUTE
            else:
                self.consecutive_off_count = 0
                self.last_state = DeviationState.ON_ROUTE
                return DeviationState.ON_ROUTE

        if cross_track_distance_m <= dynamic_corridor:
            # User is on route
            self.consecutive_off_count = max(0, self.consecutive_off_count - 1)
            self.last_state = DeviationState.ON_ROUTE
            return DeviationState.ON_ROUTE
        else:
            # User is outside corridor
            self.consecutive_off_count += 1
            if self.consecutive_off_count >= self.consecutive_required:
                self.last_state = DeviationState.OFF_ROUTE
                return DeviationState.OFF_ROUTE
            else:
                self.last_state = DeviationState.POSSIBLY_OFF_ROUTE
                return DeviationState.POSSIBLY_OFF_ROUTE

    def reset(self):
        """Reset deviation counters upon re-routing or route reset."""
        self.consecutive_off_count = 0
        self.last_state = DeviationState.ON_ROUTE
