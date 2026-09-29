"""AccessRoute AI — Stage 13 Controlled Destination, Entrance & Venue Intelligence Experiments.

Executes Experiments A through J validating:
- Experiment A: Search venue -> identify multiple entrances (e.g. Westfield Doncaster)
- Experiment B: One entrance contains stairs while another is step-free; strict preference matching
- Experiment C: Venue has no mapped entrance metadata; graceful fallback to coordinate routing
- Experiment D: OSM says wheelchair=yes but community reports active closure; provenance & conflict preservation
- Experiment E: Temporary entrance closure expires; entrance becomes eligible again
- Experiment F: Manual pin override; user-selected coordinates remain authoritative
- Experiment G: Entrance route vs venue centroid; distinct final approach demonstration
- Experiment H: Unknown door width under strict width preferences; UNKNOWN is not interpreted as acceptable
- Experiment I: Saved preferred entrance reopened after evidence changes; dynamic reassessment occurs
- Experiment J: Anonymous entrance navigation; full functionality without authentication
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import sys
import time
import uuid

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL", "postgresql://localhost/accessroute_db")

from fastapi.testclient import TestClient
import networkx as nx

from accessroute.api.dependencies import get_geocoder, get_graph_manager
from accessroute.api.main import app
from accessroute.auth.security import create_access_token
from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.database.models import SavedPlace, User
from accessroute.database.session import SessionLocal
from accessroute.destinations.assessment import EntranceAssessmentEngine
from accessroute.destinations.entrances import OSMEntranceDiscovery
from accessroute.destinations.evidence import EntranceEvidenceCollector
from accessroute.destinations.models import (
    Destination,
    Entrance,
    EntranceAccessibilityEvidence,
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("stage13_experiments")


class MockStage13Geocoder(GeocoderProvider):
    @property
    def provider_name(self) -> str:
        return "mock_stage13_geocoder"

    def search(self, query: str, limit: int = 5, proximity=None, country_code=None):
        q = query.lower().strip()
        if "doncaster" in q or "westfield" in q:
            return [
                GeocodeCandidate(
                    display_name="Westfield Doncaster, 619 Doncaster Rd, Doncaster VIC 3108",
                    latitude=-37.7870,
                    longitude=145.1250,
                    place_type="shopping_centre",
                    osm_type="way",
                    osm_id=123456,
                    raw_properties={"shop": "mall", "building": "commercial"},
                )
            ]
        elif "station" in q or "flinders" in q:
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
                    display_name=f"{query}, Victoria, Australia",
                    latitude=-37.8136,
                    longitude=144.9631,
                    place_type="street_address",
                    osm_type="node",
                    osm_id=111111,
                    raw_properties={},
                )
            ]


def build_test_graph():
    """Build a synthetic spatial graph with separate nodes for entrance and venue centroid."""
    G = nx.MultiDiGraph()
    # Node 1: Origin
    G.add_node(1, y=-37.7850, x=145.1200)
    # Node 2: Intermediate Junction
    G.add_node(2, y=-37.7860, x=145.1220)
    # Node 3: Venue Centroid approach
    G.add_node(3, y=-37.7870, x=145.1250)
    # Node 4: Main Entrance approach (Doncaster Rd)
    G.add_node(4, y=-37.7878, x=145.1255)
    # Node 5: Car Park Entrance approach (has steps)
    G.add_node(5, y=-37.7874, x=145.1261)

    # Footways
    G.add_edge(1, 2, 0, length=180.0, highway="footway", surface="paved", incline_percent=1.5, steps=False)
    G.add_edge(2, 3, 0, length=240.0, highway="footway", surface="paved", incline_percent=1.0, steps=False)
    G.add_edge(2, 4, 0, length=220.0, highway="footway", surface="paved", incline_percent=1.2, steps=False, tactile_paving=True)
    G.add_edge(2, 5, 0, length=230.0, highway="steps", surface="concrete", incline_percent=14.0, steps=True, step_count=8)

    # Reverse edges
    G.add_edge(2, 1, 0, length=180.0, highway="footway", surface="paved", incline_percent=-1.5, steps=False)
    G.add_edge(3, 2, 0, length=240.0, highway="footway", surface="paved", incline_percent=-1.0, steps=False)
    G.add_edge(4, 2, 0, length=220.0, highway="footway", surface="paved", incline_percent=-1.2, steps=False, tactile_paving=True)
    G.add_edge(5, 2, 0, length=230.0, highway="steps", surface="concrete", incline_percent=-14.0, steps=True, step_count=8)

    provider = SyntheticGraphProvider(template_graph=G)
    cache = RegionalGraphCache()
    return DynamicGraphManager(
        provider=provider,
        cache=cache,
        elevation_provider=SyntheticElevationProvider(default_elevation=45.0),
    )


def run_experiment_a():
    """Experiment A: Search venue -> identify multiple entrances."""
    logger.info("=== RUNNING EXPERIMENT A: Search Venue -> Multiple Entrances ===")
    service = DestinationService()
    geocoder = MockStage13Geocoder()

    candidates = geocoder.search("Westfield Doncaster")
    assert len(candidates) > 0, "Candidate search returned empty list"
    cand = candidates[0]

    dest = service.resolve_destination_candidate(cand)
    assert dest.is_venue is True, "Destination must be classified as a venue"
    assert dest.venue is not None, "Venue entity must be populated"
    assert dest.venue.venue_type == VenueType.SHOPPING_CENTRE, f"Expected SHOPPING_CENTRE, got {dest.venue.venue_type}"

    entrances = dest.venue.entrances
    logger.info("Discovered %d entrances for %s", len(entrances), dest.name)
    assert len(entrances) >= 3, f"Expected at least 3 entrances for Westfield Doncaster, got {len(entrances)}"

    names = [e.name for e in entrances]
    logger.info("Discovered entrances: %s", names)
    assert any("Doncaster Road" in n for n in names), "Main Doncaster Rd entrance missing"
    assert any("Tower Street" in n for n in names), "Tower St entrance missing"
    assert any("Car Park" in n for n in names), "Car Park entrance missing"

    for ent in entrances:
        assert ent.latitude != 0.0 and ent.longitude != 0.0, "Entrance must have valid coordinates"
        assert ent.evidence is not None, "Entrance must have evidence object"
        assert ent.evidence_completeness is not None, "Entrance must compute evidence completeness"

    logger.info("✓ Experiment A PASSED: Venue successfully identified with multiple distinct entrances.\n")


def run_experiment_b():
    """Experiment B: One entrance contains stairs while another is step-free; strict preference matching."""
    logger.info("=== RUNNING EXPERIMENT B: Strict Preferences Reject Stair Entrance ===")
    service = DestinationService()
    geocoder = MockStage13Geocoder()
    dest = service.resolve_destination_candidate(geocoder.search("Westfield Doncaster")[0])

    # Strict wheelchair preferences: zero stairs, max incline 5%
    prefs = MobilityPreferences(
        steps=StepPreference.NEVER,
        max_preferred_uphill_grade_pct=4.0,
        max_permitted_uphill_grade_pct=5.0,
        minimum_path_width_m=0.9,
    )

    assessment = service.assess_destination(dest, prefs)
    assert assessment.has_matching_entrance is True, "Destination should have at least one matching entrance"
    assert assessment.recommended_entrance_id is not None, "Recommended entrance ID must be populated"

    # Verify Car Park entrance (has 8 steps) was blocked
    carpark_ass = next((a for a in assessment.entrance_assessments if "car park" in a.entrance_name.lower()), None)
    assert carpark_ass is not None, "Car park entrance assessment missing"
    assert carpark_ass.status == EntranceAssessmentStatus.DOES_NOT_MATCH_CURRENT_PREFERENCES, (
        f"Car park entrance status should be DOES_NOT_MATCH_CURRENT_PREFERENCES, got {carpark_ass.status}"
    )
    assert any("steps" in r.lower() or "stairs" in r.lower() for r in carpark_ass.blocking_reasons), (
        "Blocking reasons should cite mapped steps"
    )

    # Verify Main Entrance is accepted
    main_ass = next((a for a in assessment.entrance_assessments if "doncaster road" in a.entrance_name.lower()), None)
    assert main_ass is not None, "Main entrance assessment missing"
    assert main_ass.status == EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES, (
        f"Main entrance status should be MATCHES_CURRENT_PREFERENCES, got {main_ass.status}"
    )

    logger.info("✓ Experiment B PASSED: Strict mobility preferences rejected stair entrance and selected step-free entrance.\n")


def run_experiment_c():
    """Experiment C: Venue has no mapped entrance metadata; graceful fallback."""
    logger.info("=== RUNNING EXPERIMENT C: Graceful Fallback for Unmapped Venue ===")
    service = DestinationService()
    geocoder = MockStage13Geocoder()
    dest = service.resolve_destination_candidate(geocoder.search("Unmapped Community Hall")[0])

    assert dest.is_venue is True, "Should be detected as venue from place type"
    assert len(dest.venue.entrances) == 0, "Unmapped venue must have 0 entrances"

    prefs = MobilityPreferences()
    assessment = service.assess_destination(dest, prefs)

    assert assessment.entrances_count == 0, "Entrances count should be 0"
    assert assessment.has_matching_entrance is False, "No matching entrance should be reported"
    assert "No entrance accessibility information is currently recorded" in assessment.summary_explanation, (
        f"Expected exact failure explanation, got: {assessment.summary_explanation}"
    )

    logger.info("✓ Experiment C PASSED: Graceful fallback executed with exact factual explanation.\n")


def run_experiment_d():
    """Experiment D: OSM says wheelchair=yes but community reports active closure; provenance & conflict."""
    logger.info("=== RUNNING EXPERIMENT D: Provenance & Community Conflict Preservation ===")
    service = DestinationService()
    geocoder = MockStage13Geocoder()
    dest = service.resolve_destination_candidate(geocoder.search("Westfield Doncaster")[0])
    main_ent = next(e for e in dest.venue.entrances if "doncaster road" in e.name.lower())

    # Verify OSM baseline
    assert main_ent.evidence.source == EvidenceProvenance.OPENSTREETMAP
    assert main_ent.evidence.wheelchair == "yes"

    # Simulate community report: temporary closure of main entrance
    collector = EntranceEvidenceCollector()
    mock_obs = CommunityObservation(
        id="obs_test_closure_123",
        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
        category=ObservationCategory.ENTRANCE_ACCESSIBILITY,
        value="temporary_closure",
        latitude=main_ent.latitude,
        longitude=main_ent.longitude,
        contributor_id="user_auditor_99",
        notes="Main entrance automatic glass door shattered; entrance boarded up.",
        is_temporary=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        confirmations_count=3,
        disputes_count=0,
    )

    enriched_ent = collector.enrich_entrance_evidence(main_ent, observations=[mock_obs])

    # Verify both provenances are preserved independently
    assert EvidenceProvenance.OPENSTREETMAP in enriched_ent.provenance_sources, "OSM provenance must be preserved"
    assert EvidenceProvenance.COMMUNITY_OBSERVATION in enriched_ent.provenance_sources, "Community provenance must be preserved"
    assert len(enriched_ent.active_conflicts) > 0, "Active conflict between OSM yes and community closure must be recorded"
    assert enriched_ent.evidence.is_temporary is True, "Evidence must be marked temporary"

    # Assess enriched entrance
    prefs = MobilityPreferences()
    ass = EntranceAssessmentEngine.assess_entrance(enriched_ent, prefs)
    assert ass.status == EntranceAssessmentStatus.TEMPORARILY_REPORTED_UNAVAILABLE, (
        f"Expected TEMPORARILY_REPORTED_UNAVAILABLE, got {ass.status}"
    )
    assert any("temporarily unavailable" in r.lower() for r in ass.blocking_reasons)

    logger.info("✓ Experiment D PASSED: OSM baseline and community report preserved independently with conflict noted.\n")


def run_experiment_e():
    """Experiment E: Temporary entrance closure expires; entrance becomes eligible again."""
    logger.info("=== RUNNING EXPERIMENT E: Temporary Closure Expiration & Re-eligibility ===")
    service = DestinationService()
    geocoder = MockStage13Geocoder()
    dest = service.resolve_destination_candidate(geocoder.search("Westfield Doncaster")[0])
    main_ent = next(e for e in dest.venue.entrances if "doncaster road" in e.name.lower())

    collector = EntranceEvidenceCollector()
    # Expired observation: submitted 5 days ago, duration 24 hours
    past_created = datetime.now(timezone.utc) - timedelta(days=5)
    past_expires = past_created + timedelta(hours=24)

    expired_obs = CommunityObservation(
        id="obs_expired_closure",
        source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
        category=ObservationCategory.ENTRANCE_ACCESSIBILITY,
        value="temporary_closure",
        latitude=main_ent.latitude,
        longitude=main_ent.longitude,
        contributor_id="user_auditor_99",
        notes="Main entrance temporary closure (expired)",
        is_temporary=True,
        reported_at=past_created,
        expires_at=past_expires,
        verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
    )

    enriched_ent = collector.enrich_entrance_evidence(main_ent, observations=[expired_obs])

    # Since the report is expired, it must NOT block the entrance permanently
    prefs = MobilityPreferences()
    ass = EntranceAssessmentEngine.assess_entrance(enriched_ent, prefs)
    assert ass.status == EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES, (
        f"Expected entrance to become eligible again after closure expiration, got {ass.status}"
    )

    logger.info("✓ Experiment E PASSED: Expired temporary observation did not permanently affect entrance eligibility.\n")


def run_experiment_f():
    """Experiment F: Manual pin override; user-selected coordinates remain authoritative."""
    logger.info("=== RUNNING EXPERIMENT F: Manual Pin Coordinate Authority ===")
    service = DestinationService()
    # User manually placed pin at arbitrary location
    manual_lat = -37.8185
    manual_lon = 144.9675

    dest = service.resolve_coordinates(manual_lat, manual_lon, label="Custom Dropped Pin")
    assert dest.latitude == manual_lat, "Latitude must match exact dropped pin"
    assert dest.longitude == manual_lon, "Longitude must match exact dropped pin"

    # Even if near a venue, manual pin resolution must preserve coordinates
    logger.info("Resolved destination: %s at (%f, %f)", dest.name, dest.latitude, dest.longitude)
    assert dest.is_venue is False or dest.latitude == manual_lat

    logger.info("✓ Experiment F PASSED: User-selected pin coordinates remain 100% authoritative.\n")


def run_experiment_g():
    """Experiment G: Entrance route vs venue centroid produces distinct final approach."""
    logger.info("=== RUNNING EXPERIMENT G: Entrance Route vs Venue Centroid ===")
    graph_manager = build_test_graph()
    service = DestinationService(graph_manager=graph_manager)

    origin = (-37.7850, 145.1200)  # Node 1
    venue_centroid = (-37.7870, 145.1250)  # Node 3
    main_entrance = (-37.7878, 145.1255)  # Node 4

    prefs = MobilityPreferences()

    # Route to venue centroid
    res_centroid = service.route_to_entrance(
        origin=origin,
        entrance=Entrance(
            id="centroid",
            venue_id="v_test",
            name="Centroid",
            latitude=venue_centroid[0],
            longitude=venue_centroid[1],
            entrance_type=EntranceType.MAIN,
            evidence=EntranceAccessibilityEvidence(),
        ),
        preferences=prefs,
        manager=graph_manager,
    )

    # Route to entrance
    res_entrance = service.route_to_entrance(
        origin=origin,
        entrance=Entrance(
            id="main_ent",
            venue_id="v_test",
            name="Main Entrance",
            latitude=main_entrance[0],
            longitude=main_entrance[1],
            entrance_type=EntranceType.MAIN,
            evidence=EntranceAccessibilityEvidence(),
        ),
        preferences=prefs,
        manager=graph_manager,
    )

    assert res_centroid.found is True, "Centroid route should be found"
    assert res_entrance.found is True, "Entrance route should be found"

    centroid_nodes = res_centroid.alternatives[0].route_result.nodes
    entrance_nodes = res_entrance.alternatives[0].route_result.nodes

    logger.info("Centroid route path nodes: %s", centroid_nodes)
    logger.info("Entrance route path nodes: %s", entrance_nodes)

    assert centroid_nodes != entrance_nodes, "Final route path nodes must differ between centroid and entrance"
    assert entrance_nodes[-1] == 4, f"Entrance route must terminate at entrance approach node 4, got {entrance_nodes[-1]}"
    assert centroid_nodes[-1] == 3, f"Centroid route must terminate at centroid node 3, got {centroid_nodes[-1]}"

    logger.info("✓ Experiment G PASSED: Routing directly to entrance produced distinct physical approach geometry.\n")


def run_experiment_h():
    """Experiment H: Unknown door width under strict width preferences; UNKNOWN is not acceptable."""
    logger.info("=== RUNNING EXPERIMENT H: Unknown Attribute under Strict Preferences ===")
    # Entrance with unrecorded door width
    ent = Entrance(
        id="ent_unknown_width",
        venue_id="venue_test",
        name="Unknown Width Entrance",
        latitude=-37.7870,
        longitude=145.1250,
        entrance_type=EntranceType.MAIN,
        evidence=EntranceAccessibilityEvidence(
            wheelchair="yes",
            step_free=True,
            door_width_m=None,  # UNKNOWN
        ),
    )

    # Strict door width requirement: 1.0m
    strict_prefs = MobilityPreferences(minimum_path_width_m=1.0)
    ass = EntranceAssessmentEngine.assess_entrance(ent, strict_prefs)

    logger.info("Assessment status: %s", ass.status)
    logger.info("Warning reasons: %s", ass.warning_reasons)
    logger.info("Missing attributes: %s", ass.missing_attributes)

    assert any("door" in m.lower() and "width" in m.lower() for m in ass.missing_attributes), (
        "door_width must be listed in missing attributes"
    )
    assert ass.status in [EntranceAssessmentStatus.PARTIALLY_VERIFIED, EntranceAssessmentStatus.INSUFFICIENT_EVIDENCE], (
        f"Status should reflect unrecorded width, got {ass.status}"
    )
    assert ass.status != EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES, (
        "UNKNOWN door width must NOT be given full MATCHES_CURRENT_PREFERENCES under strict width constraints"
    )

    logger.info("✓ Experiment H PASSED: Unknown attribute was not silently accepted under strict constraints.\n")


def run_experiment_i():
    """Experiment I: Saved preferred entrance reopened after evidence changes; dynamic reassessment."""
    logger.info("=== RUNNING EXPERIMENT I: Saved Preferred Entrance Dynamic Reassessment ===")
    db = SessionLocal()
    try:
        # Create test user
        test_email = f"user_exp_i_{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            id=str(uuid.uuid4()),
            email=test_email,
            hashed_password="hashed_pw_test",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()

        # Save place with preferred entrance
        place = SavedPlace(
            id=str(uuid.uuid4()),
            user_id=str(user.id),
            label="My Frequent Shopping Mall",
            display_name="Westfield Doncaster",
            latitude=-37.7870,
            longitude=145.1250,
            preferred_entrance_id="ent_doncaster_doncaster_rd",
            preferred_entrance_name="Main Entrance — Doncaster Road",
            created_at=datetime.now(timezone.utc),
        )
        db.add(place)
        db.commit()

        # Reopen place: Reassess saved preferred entrance against current live evidence
        service = DestinationService()
        dest = service.resolve_coordinates(place.latitude, place.longitude, label=place.display_name or place.label)
        assert dest.venue is not None

        preferred_ent = next((e for e in dest.venue.entrances if e.id == place.preferred_entrance_id), dest.venue.entrances[0])
        initial_ass = EntranceAssessmentEngine.assess_entrance(preferred_ent, MobilityPreferences())
        assert initial_ass.status == EntranceAssessmentStatus.MATCHES_CURRENT_PREFERENCES

        # Evidence changes: New community observation reports elevator out of order
        new_obs = CommunityObservation(
            id="obs_lift_fail",
            source=AccessibilityEvidenceSource.COMMUNITY_OBSERVATION,
            category=ObservationCategory.ENTRANCE_ACCESSIBILITY,
            value="lift_unavailable",
            latitude=preferred_ent.latitude,
            longitude=preferred_ent.longitude,
            contributor_id="community_member_42",
            notes="Lift servicing Doncaster entrance is undergoing emergency repairs.",
            is_temporary=True,
            verification_status=VerificationStatus.COMMUNITY_SUPPORTED,
        )

        collector = EntranceEvidenceCollector()
        changed_ent = collector.enrich_entrance_evidence(preferred_ent, observations=[new_obs])
        reassessed = EntranceAssessmentEngine.assess_entrance(changed_ent, MobilityPreferences(steps=StepPreference.NEVER))

        logger.info("Reassessed status after evidence change: %s", reassessed.status)
        logger.info("Reassessed warnings: %s", reassessed.warning_reasons)

        assert reassessed.status != initial_ass.status or len(reassessed.warning_reasons) > 0, (
            "Reassessment must reflect updated evidence"
        )

        # Cleanup
        db.delete(place)
        db.delete(user)
        db.commit()
    finally:
        db.close()

    logger.info("✓ Experiment I PASSED: Saved preferred entrance dynamically reassessed against live evidence.\n")


def run_experiment_j():
    """Experiment J: Anonymous entrance navigation without authentication."""
    logger.info("=== RUNNING EXPERIMENT J: Anonymous Entrance Navigation ===")
    app.dependency_overrides[get_geocoder] = lambda: MockStage13Geocoder()
    client = TestClient(app)

    # 1. Anonymous search & resolve
    resp_resolve = client.get("/api/v1/destinations/resolve?query=Westfield+Doncaster")
    assert resp_resolve.status_code == 200, f"Anonymous resolve failed: {resp_resolve.text}"
    dest_data = resp_resolve.json()
    assert dest_data["is_venue"] is True
    dest_id = dest_data["id"]

    # 2. Anonymous entrance discovery
    resp_entrances = client.get(f"/api/v1/destinations/{dest_id}/entrances")
    assert resp_entrances.status_code == 200, f"Anonymous entrance list failed: {resp_entrances.text}"
    entrances = resp_entrances.json()
    assert len(entrances) >= 3, "Anonymous entrance discovery must return candidate entrances"

    # 3. Anonymous assessment
    resp_assess = client.post(
        f"/api/v1/destinations/{dest_id}/assess",
        json={
            "origin": {"latitude": -37.7850, "longitude": 145.1200},
            "mobility_preferences": {"steps": "never"},
        },
    )
    assert resp_assess.status_code == 200, f"Anonymous assessment failed: {resp_assess.text}"
    assessment = resp_assess.json()
    assert assessment["has_matching_entrance"] is True

    # 4. Anonymous route-to-entrance
    chosen_ent_id = assessment["recommended_entrance_id"] or entrances[0]["id"]
    resp_route = client.post(
        f"/api/v1/destinations/{dest_id}/routes/to-entrance",
        json={
            "origin": {"latitude": -37.7850, "longitude": 145.1200},
            "entrance_id": chosen_ent_id,
            "mobility_preferences": {"steps": "never"},
        },
    )
    assert resp_route.status_code == 200, f"Anonymous route to entrance failed: {resp_route.text}"
    route_data = resp_route.json()
    assert "routes" in route_data
    assert "entrance" in route_data

    # 5. Anonymous live navigation arrival evaluation
    ent_lat = route_data["entrance"]["latitude"]
    ent_lon = route_data["entrance"]["longitude"]
    resp_nav = client.post(
        "/api/v1/navigation/progress",
        json={
            "location": {
                "latitude": ent_lat,
                "longitude": ent_lon,
                "accuracy_m": 4.0,
                "heading": 90.0,
                "speed_mps": 1.1,
            },
            "route_coordinates": [
                {"latitude": -37.7850, "longitude": 145.1200},
                {"latitude": -37.7860, "longitude": 145.1220},
                {"latitude": ent_lat, "longitude": ent_lon},
            ],
            "entrance_id": chosen_ent_id,
            "entrance_name": route_data["entrance"]["name"],
        },
    )
    assert resp_nav.status_code == 200, f"Anonymous nav arrival evaluation failed: {resp_nav.text}"
    nav_data = resp_nav.json()
    assert nav_data["is_arrived"] is True
    assert "entrance area" in nav_data.get("arrival_message", "").lower()

    app.dependency_overrides.clear()
    logger.info("✓ Experiment J PASSED: Complete entrance navigation workflow executed anonymously without authentication.\n")


def run_all_experiments():
    start_time = time.time()
    logger.info("=================================================================")
    logger.info("  ACCESSROUTE AI — STAGE 13 CONTROLLED EXPERIMENTS (A THROUGH J) ")
    logger.info("=================================================================")

    run_experiment_a()
    run_experiment_b()
    run_experiment_c()
    run_experiment_d()
    run_experiment_e()
    run_experiment_f()
    run_experiment_g()
    run_experiment_h()
    run_experiment_i()
    run_experiment_j()

    duration = time.time() - start_time
    logger.info("=================================================================")
    logger.info("  ALL 10 STAGE 13 CONTROLLED EXPERIMENTS COMPLETED SUCCESSFULLY! ")
    logger.info("  Total Duration: %.3f seconds                                   ", duration)
    logger.info("=================================================================")


if __name__ == "__main__":
    run_all_experiments()
