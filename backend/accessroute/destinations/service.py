"""High-level Destination and Entrance Management Service.

Stage 13 Architecture:
Orchestrates destination resolution, entrance discovery, community evidence
enrichment, preference-aware assessment, and direct entrance routing.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.service import CommunityObservationService
from accessroute.destinations.assessment import EntranceAssessmentEngine
from accessroute.destinations.entrances import OSMEntranceDiscovery
from accessroute.destinations.evidence import EntranceEvidenceCollector
from accessroute.destinations.models import (
    Destination,
    DestinationAssessment,
    Entrance,
    EntranceAccessibilityEvidence,
    EntranceAssessment,
    EntranceType,
    EvidenceProvenance,
    Venue,
)
from accessroute.destinations.resolver import DestinationResolver
from accessroute.geocoding.base import GeocodeCandidate
from accessroute.graph.manager import DynamicGraphManager
from accessroute.preferences.models import MobilityPreferences
from accessroute.routing.alternatives import (
    RouteAlternativesResult,
    calculate_route_alternatives,
)

logger = logging.getLogger(__name__)


class DestinationService:
    """Coordinates destination resolution, entrance discovery, evaluation, and entrance routing."""

    def __init__(
        self,
        community_service: Optional[CommunityObservationService] = None,
        graph_manager: Optional[DynamicGraphManager] = None,
    ) -> None:
        self.community_service = community_service
        self.graph_manager = graph_manager
        self.discovery = OSMEntranceDiscovery()
        self.collector = EntranceEvidenceCollector(
            community_repo=community_service.repository if community_service else None
        )

    def resolve_destination_candidate(self, candidate: GeocodeCandidate) -> Destination:
        """Resolve a geocode candidate and discover entrances if it is a venue."""
        destination = DestinationResolver.resolve_candidate(candidate)
        if destination.is_venue and destination.venue:
            # Discover entrances
            entrances = self.discovery.discover_entrances(destination.venue)
            # Enrich with community evidence
            enriched = [self.collector.enrich_entrance_evidence(e) for e in entrances]
            destination.venue.entrances = enriched
        return destination

    def resolve_coordinates(
        self,
        latitude: float,
        longitude: float,
        label: Optional[str] = None,
    ) -> Destination:
        """Resolve raw coordinates into a Destination entity."""
        destination = DestinationResolver.resolve_coordinates(latitude, longitude, label=label)
        if destination.is_venue and destination.venue:
            entrances = self.discovery.discover_entrances(destination.venue)
            enriched = [self.collector.enrich_entrance_evidence(e) for e in entrances]
            destination.venue.entrances = enriched
        return destination

    def get_venue_entrances(self, venue: Venue) -> List[Entrance]:
        """Fetch and enrich all entrances for a given venue."""
        entrances = self.discovery.discover_entrances(venue)
        return [self.collector.enrich_entrance_evidence(e) for e in entrances]

    def assess_destination(
        self,
        destination: Destination,
        preferences: MobilityPreferences,
        origin: Optional[Tuple[float, float]] = None,
    ) -> DestinationAssessment:
        """Evaluate all entrances of a destination venue against user mobility preferences."""
        if not destination.is_venue or not destination.venue:
            return EntranceAssessmentEngine.assess_destination_venue(destination, preferences)

        venue = destination.venue
        route_summaries: Dict[str, Dict[str, Any]] = {}

        # If origin coordinate is supplied and graph manager is available, calculate approach routes
        if origin and self.graph_manager and venue.entrances:
            for ent in venue.entrances:
                try:
                    alt_res = calculate_route_alternatives(
                        origin=origin,
                        destination=(ent.latitude, ent.longitude),
                        manager=self.graph_manager,
                        preferences=preferences,
                        enrich_elevation=False,
                        allow_expansion=True,
                    )
                    if alt_res.found and alt_res.alternatives:
                        best = alt_res.alternatives[0]
                        route_summaries[ent.id] = {
                            "found": True,
                            "physical_distance_m": best.physical_distance_m,
                            "estimated_duration_min": round(best.physical_distance_m / 60.0, 1),
                            "route_id": best.route_id,
                            "snap_distance_m": alt_res.destination_snap_distance_m,
                        }
                    else:
                        route_summaries[ent.id] = {
                            "found": False,
                            "blocking_reasons": alt_res.blocking_reasons,
                        }
                except Exception as exc:
                    logger.debug("Failed to calculate approach route for entrance %s: %s", ent.id, exc)

        return EntranceAssessmentEngine.assess_destination_venue(
            destination=destination,
            preferences=preferences,
            route_summaries_by_entrance=route_summaries,
        )

    def route_to_entrance(
        self,
        origin: Tuple[float, float],
        entrance: Entrance,
        preferences: MobilityPreferences,
        manager: Optional[DynamicGraphManager] = None,
    ) -> RouteAlternativesResult:
        """Calculate accessibility-aware routes terminating directly at the entrance approach point."""
        active_manager = manager or self.graph_manager
        if not active_manager:
            raise ValueError("DynamicGraphManager must be provided for entrance routing")

        # Plan route directly to entrance coordinate
        result = calculate_route_alternatives(
            origin=origin,
            destination=(entrance.latitude, entrance.longitude),
            manager=active_manager,
            preferences=preferences,
            enrich_elevation=True,
            allow_expansion=True,
        )

        return result

    def report_entrance_issue(
        self,
        entrance_id: str,
        category: ObservationCategory,
        value: str,
        latitude: float,
        longitude: float,
        contributor_id: str,
        notes: Optional[str] = None,
        is_temporary: bool = False,
        expected_duration_hours: Optional[float] = None,
    ) -> Tuple[bool, Optional[CommunityObservation], str]:
        """Submit a community report specifically attached to an entrance."""
        if not self.community_service:
            return False, None, "Community observation service is unavailable."

        return self.community_service.submit_report(
            source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
            category=category,
            value=value,
            latitude=latitude,
            longitude=longitude,
            contributor_id=contributor_id,
            notes=notes,
            is_temporary=is_temporary,
            expected_duration_hours=expected_duration_hours,
        )
