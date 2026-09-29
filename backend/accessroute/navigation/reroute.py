"""Accessibility-aware re-routing engine preserving personal mobility preferences."""

import logging
import time
from typing import Dict, List, Optional, Tuple

from accessroute.graph.manager import DynamicGraphManager
from accessroute.navigation.models import RerouteRequest, RerouteResult
from accessroute.preferences.models import MobilityPreferences
from accessroute.routing.alternatives import RouteAlternativesResult, calculate_route_alternatives
from accessroute.routing.heuristics import haversine_distance

logger = logging.getLogger(__name__)

DEFAULT_REROUTE_COOLDOWN_SECONDS = 10.0
DEFAULT_MIN_MOVEMENT_METERS = 15.0


class AccessibilityAwareRerouter:
    """Manages re-routing from current GPS position while strictly preserving user preferences."""

    def __init__(
        self,
        graph_manager: Optional[DynamicGraphManager] = None,
        cooldown_seconds: float = DEFAULT_REROUTE_COOLDOWN_SECONDS,
        min_movement_meters: float = DEFAULT_MIN_MOVEMENT_METERS,
    ):
        self.graph_manager = graph_manager
        self.cooldown_seconds = cooldown_seconds
        self.min_movement_meters = min_movement_meters

        self.last_reroute_time: float = 0.0
        self.last_reroute_position: Optional[Tuple[float, float]] = None
        self.active_request_token: Optional[str] = None

    def reroute(
        self,
        request: RerouteRequest,
        force: bool = False,
    ) -> RerouteResult:
        """Calculate a new route from current position to destination.

        Guarantees:
        1. Cooldown enforcement prevents recalculation loops.
        2. Mobility preferences are NEVER silently relaxed.
        3. Stale responses are tagged with request token.
        """
        now = time.time()
        curr_pos = request.current_position
        dest_pos = request.destination

        # 1. Cooldown & minimal movement check
        if not force and self.last_reroute_position is not None:
            time_elapsed = now - self.last_reroute_time
            dist_moved = haversine_distance(
                self.last_reroute_position[0],
                self.last_reroute_position[1],
                curr_pos[0],
                curr_pos[1],
            )
            if time_elapsed < self.cooldown_seconds and dist_moved < self.min_movement_meters:
                logger.info("Reroute suppressed by cooldown (elapsed=%.1fs, moved=%.1fm)", time_elapsed, dist_moved)
                return RerouteResult(
                    success=False,
                    reroute_reason="cooldown_active",
                    explanation=f"Re-route suppressed: please wait {self.cooldown_seconds - time_elapsed:.0f}s or move further.",
                    reroute_token=request.reroute_token,
                )

        self.active_request_token = request.reroute_token

        # 2. Calculate new route alternatives using the user's SAME preferences
        try:
            alt_res: RouteAlternativesResult = calculate_route_alternatives(
                origin=curr_pos,
                destination=dest_pos,
                preferences=request.mobility_preferences,
                manager=self.graph_manager,
                enrich_elevation=True,
                allow_expansion=True,
            )
        except Exception as e:
            logger.error("Rerouting calculation failed: %s", e)
            return RerouteResult(
                success=False,
                reroute_reason=request.reroute_reason,
                explanation=f"Re-routing error: {str(e)}",
                reroute_token=request.reroute_token,
            )

        # 3. Handle preference conflict (no route found under strict constraints)
        if not alt_res.found or not alt_res.alternatives:
            blocking = getattr(alt_res, "blocking_reasons", [])
            logger.warning("No route found satisfying strict accessibility preferences during rerouting.")
            return RerouteResult(
                success=False,
                reroute_reason=request.reroute_reason,
                explanation=(
                    "No route matching your current accessibility preferences was found "
                    "from your present location within the searched area."
                ),
                blocking_reasons=blocking,
                reroute_token=request.reroute_token,
            )

        # 4. Select recommended primary route alternative
        chosen_alt = alt_res.alternatives[0]
        self.last_reroute_time = now
        self.last_reroute_position = curr_pos

        delta_m = 0.0
        if request.original_route_distance_m is not None:
            delta_m = chosen_alt.physical_distance_m - request.original_route_distance_m

        pref_summary = "standard accessible"
        if request.mobility_preferences:
            val = request.mobility_preferences.preset_name
            pref_summary = val.value if hasattr(val, "value") else str(val)

        explanation = (
            f"Re-routed from your current location to destination "
            f"({chosen_alt.physical_distance_m:.0f}m, {delta_m:+.0f}m vs original). "
            f"Preserving your {pref_summary} preferences."
        )

        return RerouteResult(
            success=True,
            new_route=chosen_alt,
            reroute_reason=request.reroute_reason,
            distance_delta_m=delta_m,
            explanation=explanation,
            reroute_token=request.reroute_token,
        )
