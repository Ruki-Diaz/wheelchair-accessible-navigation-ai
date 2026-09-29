"""High-level service orchestrating community observations, verification, and graph enrichment.

Stage 9 Architecture:
Coordinates:
1. Report submission and spatial snapping
2. Confirmation and dispute lifecycle
3. Graph enrichment for multi-criteria routing
4. Deterministic verification opportunity discovery (data gaps)
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx

from accessroute.community.conflicts import EvidenceConflictDetector
from accessroute.community.matcher import CommunitySpatialMatcher, MatchResult
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    EvidenceConflict,
    ObservationCategory,
    STRUCTURED_VALUES,
    VerificationOpportunity,
    VerificationStatus,
)
from accessroute.community.repository import CommunityObservationRepository, SQLiteCommunityObservationRepository
from accessroute.community.verification import CommunityVerificationEngine

logger = logging.getLogger(__name__)


class CommunityObservationService:
    """Core domain service for community accessibility reporting and verification."""

    def __init__(
        self,
        repository: Optional[CommunityObservationRepository] = None,
        matcher: Optional[CommunitySpatialMatcher] = None,
        verification_engine: Optional[CommunityVerificationEngine] = None,
    ):
        if repository is not None:
            self.repository = repository
        else:
            try:
                from accessroute.database.config import db_settings
                if db_settings.is_postgres:
                    from accessroute.database.repository import PostgresCommunityObservationRepository
                    self.repository = PostgresCommunityObservationRepository()
                else:
                    self.repository = SQLiteCommunityObservationRepository()
            except Exception as e:
                logger.warning("Failed to initialize database repository from config: %s. Falling back to SQLite.", e)
                self.repository = SQLiteCommunityObservationRepository()

        self.matcher = matcher or CommunitySpatialMatcher(max_match_distance_m=30.0)
        self.verification_engine = verification_engine or CommunityVerificationEngine()

    def submit_report(
        self,
        category: ObservationCategory,
        value: str,
        latitude: float,
        longitude: float,
        is_temporary: bool = False,
        expected_duration_hours: Optional[float] = None,
        expires_at: Optional[datetime] = None,
        contributor_id: Optional[str] = None,
        notes: Optional[str] = None,
        photo_url: Optional[str] = None,
        graph: Optional[nx.MultiDiGraph] = None,
    ) -> CommunityObservation:
        """Create, validate, snap, and persist a community accessibility report."""
        # Value validation & normalization
        normalized_val = str(value).strip().lower()
        valid_values = STRUCTURED_VALUES.get(category, ["other"])
        if normalized_val not in valid_values:
            # Fall back to other if unrecognized
            normalized_val = "other" if "other" in valid_values else valid_values[0]

        now = datetime.now(timezone.utc)
        final_expires_at: Optional[datetime] = expires_at

        if is_temporary:
            if final_expires_at is None:
                duration = expected_duration_hours if expected_duration_hours is not None else 168.0  # Default 7 days
                final_expires_at = now + timedelta(hours=max(1.0, duration))
        else:
            final_expires_at = None

        obs = CommunityObservation(
            source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
            category=category,
            value=normalized_val,
            latitude=latitude,
            longitude=longitude,
            is_temporary=is_temporary,
            reported_at=now,
            expected_end_at=final_expires_at,
            expires_at=final_expires_at,
            verification_status=VerificationStatus.UNVERIFIED,
            confirmations_count=1,  # Submitter is first confirmation
            disputes_count=0,
            contributor_id=contributor_id,
            notes=notes.strip() if notes else None,
            photo_url=photo_url,
        )

        # Spatial Matching to Graph if available
        if graph is not None:
            match_res: MatchResult = self.matcher.match_point_to_graph(
                latitude=latitude,
                longitude=longitude,
                graph=graph,
                category=category.value,
            )
            if match_res.is_matched:
                obs.osm_element_type = match_res.osm_element_type
                obs.osm_element_id = match_res.osm_element_id
                obs.matched_distance_m = match_res.distance_m
                obs.match_confidence = match_res.match_confidence

        saved = self.repository.save(obs)

        # Record submitter interaction to prevent duplicate self-confirmations
        if contributor_id:
            self.repository.record_interaction(saved.id, contributor_id, "confirm", increment_count=False)

        return saved

    def confirm_report(
        self,
        observation_id: str,
        contributor_id: str,
    ) -> Tuple[bool, Optional[CommunityObservation], str]:
        """Add an independent confirmation to an existing report."""
        obs = self.repository.get_by_id(observation_id)
        if not obs:
            return False, None, "Observation not found."

        if not obs.is_active():
            return False, obs, "Cannot confirm an expired or rejected observation."

        recorded = self.repository.record_interaction(observation_id, contributor_id, "confirm")
        if not recorded:
            return False, obs, "You have already confirmed or disputed this report."

        # Fetch refreshed observation
        refreshed = self.repository.get_by_id(observation_id)
        if refreshed:
            new_status = self.verification_engine.evaluate_status(refreshed)
            refreshed.verification_status = new_status
            if hasattr(self.repository, "update_status"):
                self.repository.update_status(observation_id, new_status)
            else:
                self.repository.update(refreshed)
            return True, refreshed, "Confirmation recorded successfully."

        return True, obs, "Confirmation recorded."

    def dispute_report(
        self,
        observation_id: str,
        contributor_id: str,
    ) -> Tuple[bool, Optional[CommunityObservation], str]:
        """Record a dispute against an observation."""
        obs = self.repository.get_by_id(observation_id)
        if not obs:
            return False, None, "Observation not found."

        recorded = self.repository.record_interaction(observation_id, contributor_id, "dispute")
        if not recorded:
            return False, obs, "You have already confirmed or disputed this report."

        refreshed = self.repository.get_by_id(observation_id)
        if refreshed:
            new_status = self.verification_engine.evaluate_status(refreshed)
            refreshed.verification_status = new_status
            if hasattr(self.repository, "update_status"):
                self.repository.update_status(observation_id, new_status)
            else:
                self.repository.update(refreshed)
            return True, refreshed, "Dispute recorded successfully."

        return True, obs, "Dispute recorded."

    def get_nearby_observations(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Retrieve nearby observations within radius."""
        return self.repository.get_nearby(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            include_expired=include_expired,
        )

    def get_bbox_observations(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Retrieve observations inside a geographic bounding box."""
        return self.repository.get_by_bbox(
            min_lat=min_lat,
            min_lon=min_lon,
            max_lat=max_lat,
            max_lon=max_lon,
            include_expired=include_expired,
        )

    def enrich_graph_with_observations(
        self,
        graph: nx.MultiDiGraph,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ) -> int:
        """Attach active community observations to graph edges and nodes for instant routing evaluation.

        Args:
            graph: NetworkX MultiDiGraph.
            bbox: Optional (south, west, north, east) bounding box. If None, derived from graph nodes.

        Returns:
            Count of community observations attached to the graph.
        """
        if graph is None or len(graph.nodes) == 0:
            return 0

        if bbox is None:
            lats = [d["y"] for _, d in graph.nodes(data=True) if "y" in d]
            lons = [d["x"] for _, d in graph.nodes(data=True) if "x" in d]
            if not lats or not lons:
                return 0
            bbox = (min(lats) - 0.002, min(lons) - 0.002, max(lats) + 0.002, max(lons) + 0.002)

        south, west, north, east = bbox
        observations = self.repository.get_by_bbox(
            min_lat=south,
            min_lon=west,
            max_lat=north,
            max_lon=east,
            include_expired=False,
        )

        attached_count = 0

        # Build index of OSM element IDs to graph edges
        way_to_edges: Dict[int, List[Tuple[int, int, Any]]] = {}
        for u, v, k, d in graph.edges(keys=True, data=True):
            d["_community_observations"] = []  # Initialize empty list
            osmid = d.get("osmid")
            if osmid is not None:
                ids = osmid if isinstance(osmid, list) else [osmid]
                for raw_id in ids:
                    try:
                        int_id = int(raw_id)
                        way_to_edges.setdefault(int_id, []).append((u, v, k))
                    except (ValueError, TypeError):
                        pass

        for node_id, d in graph.nodes(data=True):
            d["_community_observations"] = []

        for obs in observations:
            # 1. Direct OSM ID match
            if obs.osm_element_type == "way" and obs.osm_element_id in way_to_edges:
                for u, v, k in way_to_edges[obs.osm_element_id]:
                    graph.edges[u, v, k]["_community_observations"].append(obs)
                attached_count += 1
            elif obs.osm_element_type == "node" and obs.osm_element_id in graph.nodes:
                graph.nodes[obs.osm_element_id]["_community_observations"].append(obs)
                attached_count += 1
            else:
                # 2. Spatial proximity match if within threshold
                match_res = self.matcher.match_point_to_graph(
                    latitude=obs.latitude,
                    longitude=obs.longitude,
                    graph=graph,
                    category=obs.category.value,
                )
                if match_res.is_matched:
                    if match_res.osm_element_type == "way" and match_res.matched_u is not None and match_res.matched_v is not None:
                        graph.edges[match_res.matched_u, match_res.matched_v, match_res.matched_key]["_community_observations"].append(obs)
                        attached_count += 1
                    elif match_res.osm_element_type == "node" and match_res.matched_u in graph.nodes:
                        graph.nodes[match_res.matched_u]["_community_observations"].append(obs)
                        attached_count += 1

        return attached_count

    def identify_verification_opportunities(
        self,
        graph: nx.MultiDiGraph,
        max_count: int = 50,
    ) -> List[VerificationOpportunity]:
        """Deterministically identify accessibility data gaps in a pedestrian network."""
        opportunities: List[VerificationOpportunity] = []
        if graph is None:
            return opportunities

        # 1. Missing kerb ramp transitions at crossings
        for u, v, k, d in graph.edges(keys=True, data=True):
            if len(opportunities) >= max_count:
                break
            hw = str(d.get("highway", "")).lower()
            is_crossing = bool(d.get("is_crossing")) or hw == "crossing"
            kerb = str(d.get("kerb", "unknown")).lower()

            if is_crossing and kerb == "unknown":
                u_node = graph.nodes.get(u, {})
                lat = u_node.get("y", 0.0)
                lon = u_node.get("x", 0.0)
                osmid = d.get("osmid")
                way_id = int(osmid[0] if isinstance(osmid, list) else osmid) if osmid else 0

                opportunities.append(
                    VerificationOpportunity(
                        latitude=lat,
                        longitude=lon,
                        osm_element_type="way",
                        osm_element_id=way_id,
                        missing_attribute="kerb",
                        feature_type="crossing",
                        importance_reason="Pedestrian crossing lacks recorded kerb ramp profile in OpenStreetMap.",
                    )
                )

        # 2. Footpaths with unknown surface material
        for u, v, k, d in graph.edges(keys=True, data=True):
            if len(opportunities) >= max_count:
                break
            hw = str(d.get("highway", "")).lower()
            surf = str(d.get("surface", "unknown")).lower()
            if hw in ("footway", "path", "pedestrian") and surf == "unknown":
                u_node = graph.nodes.get(u, {})
                lat = u_node.get("y", 0.0)
                lon = u_node.get("x", 0.0)
                osmid = d.get("osmid")
                way_id = int(osmid[0] if isinstance(osmid, list) else osmid) if osmid else 0

                opportunities.append(
                    VerificationOpportunity(
                        latitude=lat,
                        longitude=lon,
                        osm_element_type="way",
                        osm_element_id=way_id,
                        missing_attribute="surface",
                        feature_type="footway",
                        importance_reason="Footpath has unrecorded surface material; user preferences cannot be verified.",
                    )
                )

        return opportunities
