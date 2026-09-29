"""Comprehensive unit and integration test suite for AccessRoute AI Stage 13.

Covers:
- Destination resolution (venues vs addresses vs coordinates)
- OSM entrance discovery and attribute parsing
- Spatial association and radius filtering
- Deterministic entrance accessibility assessment
- Mobility preference matching (stairs prohibition, width thresholds)
- Multi-source evidence provenance tracking
- Community conflict handling and temporary closure expiration
- Direct route-to-entrance path generation
- Manual map pin override coordinate authority
- Saved preferred entrance persistence and dynamic reassessment
- API contracts, validation, error handling, and anonymous access
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import uuid
from fastapi.testclient import TestClient
import networkx as nx
import pytest

from accessroute.api.dependencies import get_geocoder, get_graph_manager
from accessroute.api.main import app
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.database.models import SavedPlace, User, VenueEntranceModel
from accessroute.database.session import SessionLocal
from accessroute.destinations.assessment import EntranceAssessmentEngine
from accessroute.destinations.entrances import OSMEntranceDiscovery
from accessroute.destinations.evidence import EntranceEvidenceCollector
from accessroute.destinations.models import (
    Destination,
    DestinationAssessment,
    Entrance,
    EntranceAccessibilityEvidence,
    EntranceAssessment,
    EntranceAssessmentStatus,
    EntranceType,
    EvidenceProvenance,
    Venue,
    VenueType,
)
from accessroute.destinations.resolver import DestinationResolver
from accessroute.destinations.service import DestinationService
from accessroute.elevation.synthetic import SyntheticElevationProvider
from accessroute.geocoding.base import GeocodeCandidate, GeocoderProvider
from accessroute.graph.manager import DynamicGraphManager
from accessroute.graph.provider import SyntheticGraphProvider
from accessroute.graph.regional_cache import RegionalGraphCache
from accessroute.preferences.models import MobilityPreferences, StepPreference


class TestStage13Geocoder(GeocoderProvider):
    @property
    def provider_name(self) -> str:
        return "test_stage13_geocoder"

    def search(self, query: str, limit: int = 5, proximity=None, country_code=None):
        q = query.lower().strip()
        if "westfield" in q or "doncaster" in q:
            return [
                GeocodeCandidate(
                    display_name="Westfield Doncaster, Doncaster Rd, Doncaster VIC 3108",
                    latitude=-37.7870,
                    longitude=145.1250,
                    place_type="shopping_centre",
                    osm_type="way",
                    osm_id=123456,
                    raw_properties={"shop": "mall", "building": "commercial"},
                )
            ]
        elif "station" in q:
            return [
                GeocodeCandidate(
                    display_name="Flinders Street Railway Station, Melbourne VIC 3000",
                    latitude=-37.8180,
                    longitude=144.9671,
                    place_type="station",
                    osm_type="node",
                    osm_id=654321,
                    raw_properties={"railway": "station"},
                )
            ]
        elif "unmapped" in q:
            return [
                GeocodeCandidate(
                    display_name="Unmapped Community Hall, Victoria",
                    latitude=-37.8200,
                    longitude=144.9700,
                    place_type="public_facility",
                    osm_type="way",
                    osm_id=999999,
                    raw_properties={"amenity": "community_centre"},
                )
            ]
        else:
            return [
                GeocodeCandidate(
                    display_name=f"{query}, Melbourne, Victoria",
                    latitude=-37.8136,
                    longitude=144.9631,
                    place_type="street_address",
                    osm_type="node",
                    osm_id=111111,
                    raw_properties={},
                )
            ]


@pytest.fixture
def mock_geocoder():
    return TestStage13Geocoder()


@pytest.fixture
def test_graph_manager():
    G = nx.MultiDiGraph()
    G.add_node(1, y=-37.7850, x=145.1200)
    G.add_node(2, y=-37.7860, x=145.1220)
    G.add_node(3, y=-37.7870, x=145.1250)
    G.add_node(4, y=-37.7878, x=145.1255)

    G.add_edge(1, 2, 0, length=180.0, highway="footway", surface="paved", incline_percent=1.5, steps=False)
    G.add_edge(2, 3, 0, length=240.0, highway="footway", surface="paved", incline_percent=1.0, steps=False)
    G.add_edge(2, 4, 0, length=220.0, highway="footway", surface="paved", incline_percent=1.2, steps=False)
    G.add_edge(2, 1, 0, length=180.0, highway="footway", surface="paved", incline_percent=-1.5, steps=False)
    G.add_edge(3, 2, 0, length=240.0, highway="footway", surface="paved", incline_percent=-1.0, steps=False)
    G.add_edge(4, 2, 0, length=220.0, highway="footway", surface="paved", incline_percent=-1.2, steps=False)

    provider = SyntheticGraphProvider(template_graph=G)
    cache = RegionalGraphCache()
    return DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=45.0),
    )


# 1. Destination Resolution Tests
def test_destination_resolver_venue_detection(mock_geocoder):
    cand = mock_geocoder.search("Westfield Doncaster")[0]
    dest = DestinationResolver.resolve_candidate(cand)
    assert dest.is_venue is True
    assert dest.venue is not None
    assert dest.venue.venue_type == VenueType.SHOPPING_CENTRE
    assert dest.latitude == -37.7870
    assert dest.longitude == 145.1250


def test_destination_resolver_street_address():
    cand = GeocodeCandidate(
        display_name="250 Flinders Street, Melbourne VIC 3000",
        latitude=-37.8175,
        longitude=144.9660,
        place_type="house",
        raw_properties={},
    )
    dest = DestinationResolver.resolve_candidate(cand)
    assert dest.is_venue is False
    assert dest.venue is None
    assert dest.name == "250 Flinders Street"


def test_destination_resolver_raw_coordinates():
    dest = DestinationResolver.resolve_coordinates(-37.8136, 144.9631, label="Custom Pin")
    assert dest.is_venue is False
    assert dest.latitude == -37.8136
    assert dest.longitude == 144.9631
    assert dest.name == "Custom Pin"


# 2. OSM Entrance Parsing & Discovery Tests
def test_osm_entrance_discovery_synthesizes_known_venue(mock_geocoder):
    cand = mock_geocoder.search("Westfield Doncaster")[0]
    dest = DestinationResolver.resolve_candidate(cand)
    discovery = OSMEntranceDiscovery()
    entrances = discovery.discover_entrances(dest.venue)
    assert len(entrances) >= 3

    main_ent = next((e for e in entrances if "doncaster" in e.name.lower()), None)
    assert main_ent is not None
    assert main_ent.evidence.step_free is True
    assert main_ent.evidence.automatic_door is True
    assert main_ent.evidence.door_width_m == 1.2
    assert main_ent.evidence.source == EvidenceProvenance.OPENSTREETMAP


def test_osm_entrance_discovery_graph_node_extraction():
    G = nx.MultiDiGraph()
    # Add entrance node near venue
    G.add_node(
        1001,
        y=-37.8181,
        x=144.9672,
        entrance="main",
        door="sliding",
        automatic_door="yes",
        wheelchair="yes",
        width="1.1",
        step_free="yes",
        step_count="0",
        name="Main Glass Entrance",
    )
    discovery = OSMEntranceDiscovery()
    venue = Venue(
        id="ven_test",
        name="Test Building",
        venue_type=VenueType.BUSINESS,
        latitude=-37.8180,
        longitude=144.9670,
    )
    extracted = discovery._extract_from_graph(venue, G, radius_m=100.0)
    assert len(extracted) == 1
    ent = extracted[0]
    assert ent.name == "Main Glass Entrance"
    assert ent.evidence.step_free is True
    assert ent.evidence.door_width_m == 1.1
    assert ent.evidence.door_type == "sliding"


def test_osm_entrance_radius_filtering():
    G = nx.MultiDiGraph()
    # Distant entrance node (>200m away)
    G.add_node(
        2001,
        y=-37.8100,
        x=144.9670,
        entrance="yes",
        wheelchair="yes",
    )
    discovery = OSMEntranceDiscovery()
    venue = Venue(
        id="ven_test_radius",
        name="Test Venue",
        venue_type=VenueType.BUSINESS,
        latitude=-37.8180,
        longitude=144.9670,
    )
    extracted = discovery._extract_from_graph(venue, G, radius_m=150.0)
    assert len(extracted) == 0


# 3. Deterministic Assessment Tests
def test_assessment_matches_preferences():
    ent = Entrance(
        id="ent_test_match",
        venue_id="ven_1",
        name="Accessible Gate",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(
            wheelchair="yes",
            step_free=True,
            steps_count=0,
            ramp="yes",
            automatic_door=True,
            door_width_m=1.2,
        ),
    )
    prefs = MobilityPreferences(steps=StepPreference.NEVER, minimum_path_width_m=0.9)
    ass = EntranceAssessmentEngine.assess_entrance(ent, prefs)
    assert ass.status == EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES
    assert len(ass.blocking_reasons) == 0
    assert any("step-free" in m.lower() for m in ass.matching_reasons)


def test_assessment_rejects_steps():
    ent = Entrance(
        id="ent_test_steps",
        venue_id="ven_1",
        name="Stairs Only Entrance",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.SECONDARY,
        evidence=EntranceAccessibilityEvidence(
            wheelchair="no",
            step_free=False,
            steps_count=12,
            ramp="no",
        ),
    )
    prefs = MobilityPreferences(steps=StepPreference.NEVER)
    ass = EntranceAssessmentEngine.assess_entrance(ent, prefs)
    assert ass.status == EntranceAssessmentStatus.DOES_NOT_MATCH_CURRENT_PREFERENCES
    assert any("steps" in r.lower() or "stairs" in r.lower() for r in ass.blocking_reasons)


def test_assessment_unknown_door_width():
    ent = Entrance(
        id="ent_test_unknown",
        venue_id="ven_1",
        name="Unrecorded Door Width Entrance",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(
            wheelchair="yes",
            step_free=True,
            door_width_m=None,
        ),
    )
    prefs = MobilityPreferences(minimum_path_width_m=1.1)
    ass = EntranceAssessmentEngine.assess_entrance(ent, prefs)
    assert ass.status != EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES
    assert any("door" in m.lower() and "width" in m.lower() for m in ass.missing_attributes)


# 4. Multi-Source Provenance & Community Conflict Tests
def test_evidence_collector_preserves_provenance():
    ent = Entrance(
        id="ent_prov",
        venue_id="ven_prov",
        name="Main Entry",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(
            source=EvidenceProvenance.OPENSTREETMAP,
            wheelchair="yes",
            step_free=True,
        ),
        provenance_sources=[EvidenceProvenance.OPENSTREETMAP],
    )
    obs = CommunityObservation(
        id="obs_test_closure",
        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
        category=ObservationCategory.ENTRANCE_ACCESSIBILITY,
        value="temporary_closure",
        latitude=-37.7870,
        longitude=145.1250,
        contributor_id="auditor_1",
        is_temporary=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )
    collector = EntranceEvidenceCollector()
    enriched = collector.enrich_entrance_evidence(ent, observations=[obs])

    assert EvidenceProvenance.OPENSTREETMAP in enriched.provenance_sources
    assert EvidenceProvenance.COMMUNITY_OBSERVATION in enriched.provenance_sources
    assert enriched.community_reports_count == 1
    assert len(enriched.active_conflicts) > 0


def test_temporary_closure_expiration():
    ent = Entrance(
        id="ent_exp",
        venue_id="ven_exp",
        name="Temporary Entry",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(
            source=EvidenceProvenance.OPENSTREETMAP,
            step_free=True,
        ),
    )
    past_created = datetime.now(timezone.utc) - timedelta(days=2)
    past_expires = past_created + timedelta(hours=12)
    expired_obs = CommunityObservation(
        id="obs_exp",
        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
        category=ObservationCategory.ENTRANCE_ACCESSIBILITY,
        value="temporary_closure",
        latitude=-37.7870,
        longitude=145.1250,
        is_temporary=True,
        reported_at=past_created,
        expires_at=past_expires,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )
    collector = EntranceEvidenceCollector()
    enriched = collector.enrich_entrance_evidence(ent, observations=[expired_obs])
    ass = EntranceAssessmentEngine.assess_entrance(enriched, MobilityPreferences())
    assert ass.status != EntranceAssessmentStatus.TEMPORARILY_REPORTED_UNAVAILABLE
    assert len(ass.blocking_reasons) == 0


# 5. Route to Entrance Tests
def test_route_to_entrance_snapping(test_graph_manager):
    service = DestinationService(graph_manager=test_graph_manager)
    ent = Entrance(
        id="ent_snap",
        venue_id="ven_snap",
        name="Approach Entrance",
        latitude=-37.7878,
        longitude=145.1255,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(),
    )
    origin = (-37.7850, 145.1200)
    result = service.route_to_entrance(origin, ent, MobilityPreferences(), manager=test_graph_manager)
    assert result.found is True
    assert len(result.alternatives) > 0
    route = result.alternatives[0]
    assert route.route_result.nodes[-1] == 4


# 6. Database & Preferred Entrance Persistence Tests
def test_saved_place_preferred_entrance_persistence():
    db = SessionLocal()
    try:
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            email=f"pref_ent_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pw_test",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()

        place_id = str(uuid.uuid4())
        place = SavedPlace(
            id=place_id,
            user_id=user_id,
            label="Workplace",
            display_name="Tech Park Level 2",
            latitude=-37.7870,
            longitude=145.1250,
            preferred_entrance_id="ent_doncaster_doncaster_rd",
            preferred_entrance_name="Main Accessible Entrance",
            created_at=datetime.now(timezone.utc),
        )
        db.add(place)
        db.commit()

        fetched = db.query(SavedPlace).filter_by(id=place_id).first()
        assert fetched is not None
        assert fetched.preferred_entrance_id == "ent_doncaster_doncaster_rd"
        assert fetched.preferred_entrance_name == "Main Accessible Entrance"

        db.delete(place)
        db.delete(user)
        db.commit()
    finally:
        db.close()


# 7. API Endpoints and Anonymous Access Tests
def test_api_destination_resolution_anonymous(mock_geocoder):
    app.dependency_overrides[get_geocoder] = lambda: mock_geocoder
    client = TestClient(app)
    resp = client.get("/api/v1/destinations/resolve?query=Westfield+Doncaster")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_venue"] is True
    assert data["venue"]["venue_type"] == "shopping_centre"
    assert len(data["venue"]["entrances"]) >= 3
    app.dependency_overrides.clear()


def test_api_destination_entrances_list(mock_geocoder):
    app.dependency_overrides[get_geocoder] = lambda: mock_geocoder
    client = TestClient(app)
    # 1. Resolve to populate in-memory session cache
    res = client.get("/api/v1/destinations/resolve?query=Westfield+Doncaster").json()
    dest_id = res["id"]

    # 2. Get entrances
    resp = client.get(f"/api/v1/destinations/{dest_id}/entrances")
    assert resp.status_code == 200
    entrances = resp.json()
    assert isinstance(entrances, list)
    assert len(entrances) >= 3
    app.dependency_overrides.clear()


def test_api_assess_destination_anonymous(mock_geocoder):
    app.dependency_overrides[get_geocoder] = lambda: mock_geocoder
    client = TestClient(app)
    res = client.get("/api/v1/destinations/resolve?query=Westfield+Doncaster").json()
    dest_id = res["id"]

    resp = client.post(
        f"/api/v1/destinations/{dest_id}/assess",
        json={"mobility_preferences": {"steps": "never"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_venue"] is True
    assert data["has_matching_entrance"] is True
    assert len(data["entrance_assessments"]) >= 3
    app.dependency_overrides.clear()


def test_api_route_to_entrance_contract(mock_geocoder, test_graph_manager):
    app.dependency_overrides[get_geocoder] = lambda: mock_geocoder
    app.dependency_overrides[get_graph_manager] = lambda: test_graph_manager
    client = TestClient(app)

    res = client.get("/api/v1/destinations/resolve?query=Westfield+Doncaster").json()
    dest_id = res["id"]
    ent_id = res["venue"]["entrances"][0]["id"]

    resp = client.post(
        "/api/v1/routes/to-entrance",
        json={
            "origin": {"latitude": -37.7850, "longitude": 145.1200},
            "entrance_id": ent_id,
            "mobility_preferences": {"steps": "never"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "routes" in data
    assert "entrance" in data
    assert data["entrance"]["id"] == ent_id
    app.dependency_overrides.clear()


def test_api_malformed_coordinates_validation():
    client = TestClient(app)
    # Latitude out of bounds
    resp = client.get("/api/v1/destinations/resolve?lat=195.0&lon=144.0")
    assert resp.status_code in [400, 422]
