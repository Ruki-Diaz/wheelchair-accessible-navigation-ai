"""High-level live navigation and re-routing service."""

from typing import Any, Dict, List, Optional, Tuple

from accessroute.graph.manager import DynamicGraphManager
from accessroute.navigation.deviation import RouteDeviationDetector
from accessroute.navigation.models import (
    GPSLocation,
    RerouteRequest,
    RerouteResult,
    RouteProgress,
)
from accessroute.navigation.reroute import AccessibilityAwareRerouter
from accessroute.navigation.tracker import RouteProgressTracker
from accessroute.routing.directions import DirectionStep


class LiveNavigationService:
    """Orchestrates live location processing, progress projection, and accessibility rerouting."""

    def __init__(self, graph_manager: Optional[DynamicGraphManager] = None):
        self.graph_manager = graph_manager
        self.rerouter = AccessibilityAwareRerouter(graph_manager=graph_manager)

    def track_progress(
        self,
        route_coordinates: List[Tuple[float, float]],
        location: GPSLocation,
        directions: Optional[List[DirectionStep]] = None,
        edge_metadata: Optional[List[Dict[str, Any]]] = None,
        detector: Optional[RouteDeviationDetector] = None,
    ) -> RouteProgress:
        """Evaluate route progress and deviation for a GPS location reading."""
        tracker = RouteProgressTracker(
            route_coordinates=route_coordinates,
            directions=directions,
            edge_metadata=edge_metadata,
        )

        # Temporary initial progress to get cross-track distance
        raw_progress = tracker.update_progress(location)

        # Evaluate deviation state
        dev_detector = detector or RouteDeviationDetector()
        deviation_state = dev_detector.evaluate_deviation(
            cross_track_distance_m=raw_progress.cross_track_distance_m,
            location=location,
        )

        # Re-evaluate with confirmed deviation state
        return tracker.update_progress(location, deviation_state=deviation_state)

    def reroute(self, request: RerouteRequest, force: bool = False) -> RerouteResult:
        """Execute an accessibility-aware reroute calculation."""
        return self.rerouter.reroute(request=request, force=force)
