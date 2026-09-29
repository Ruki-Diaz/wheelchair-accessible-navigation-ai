"""Comprehensive automated tests for Stage 11 live GPS navigation, progress tracking, and re-routing."""

import math
import time
import pytest
from fastapi.testclient import TestClient

from accessroute.api.main import app
from accessroute.navigation.deviation import RouteDeviationDetector
from accessroute.navigation.models import (
    AccuracyQualityBand,
    DeviationState,
    GPSLocation,
    NavigationState,
    RerouteRequest,
    RerouteResult,
    UpcomingAccessibilityEvent,
    UpcomingEventType,
)
from accessroute.navigation.reroute import AccessibilityAwareRerouter
from accessroute.navigation.service import LiveNavigationService
from accessroute.navigation.simulation import SimulatedLocationProvider
from accessroute.navigation.tracker import RouteProgressTracker
from accessroute.preferences.models import (
    AvoidanceLevel,
    KerbPreference,
    MobilityPreferences,
    MobilityPresetName,
    StepPreference,
    get_preset_preferences,
)
from accessroute.routing.directions import DirectionStep


# =============================================================================
# 1. GPS ACCURACY & LOCATION MODEL TESTS
# =============================================================================

def test_gps_accuracy_quality_bands():
    """Verify classification of raw GPS accuracy into observable quality bands."""
    assert AccuracyQualityBand.from_accuracy_meters(4.0) == AccuracyQualityBand.HIGH_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(10.0) == AccuracyQualityBand.HIGH_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(15.0) == AccuracyQualityBand.MODERATE_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(25.0) == AccuracyQualityBand.MODERATE_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(35.0) == AccuracyQualityBand.LOW_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(50.0) == AccuracyQualityBand.LOW_ACCURACY
    assert AccuracyQualityBand.from_accuracy_meters(65.0) == AccuracyQualityBand.VERY_LOW_ACCURACY


def test_gps_location_serialization():
    """Verify GPSLocation serialization retains all fields with proper rounding."""
    loc = GPSLocation(
        latitude=-37.8651234,
        longitude=145.1856789,
        accuracy_m=7.42,
        heading=124.8,
        speed_mps=1.15,
        timestamp=1700000000.0,
    )
    d = loc.to_dict()
    assert d["latitude"] == -37.8651234
    assert d["longitude"] == 145.1856789
    assert d["accuracy_m"] == 7.4
    assert d["heading"] == 124.8
    assert d["speed_mps"] == 1.15
    assert d["quality_band"] == "HIGH_ACCURACY"


# =============================================================================
# 2. ROUTE PROGRESS & GEOMETRY PROJECTION TESTS
# =============================================================================

@pytest.fixture
def sample_route_coordinates():
    """A straight 3-segment L-shaped route in Vermont South (~220m total)."""
    return [
        (-37.8650, 145.1850),  # Node 0
        (-37.8650, 145.1860),  # Node 1 (~88m east)
        (-37.8660, 145.1860),  # Node 2 (~111m south)
        (-37.8660, 145.1865),  # Node 3 (~44m east)
    ]


@pytest.fixture
def sample_directions():
    """Turn-by-turn guidance steps corresponding to the sample route."""
    return [
        DirectionStep(
            step_index=0,
            instruction="Depart east along Hanover Road shared path.",
            maneuver="depart",
            street_name="Hanover Road",
            distance_m=88.0,
            cumulative_distance_m=88.0,
            latitude=-37.8650,
            longitude=145.1850,
        ),
        DirectionStep(
            step_index=1,
            instruction="Turn right onto Hawthorn Road footway.",
            maneuver="right",
            street_name="Hawthorn Road",
            distance_m=111.0,
            cumulative_distance_m=199.0,
            latitude=-37.8650,
            longitude=145.1860,
        ),
        DirectionStep(
            step_index=2,
            instruction="Turn left onto Community Lane.",
            maneuver="left",
            street_name="Community Lane",
            distance_m=44.0,
            cumulative_distance_m=243.0,
            latitude=-37.8660,
            longitude=145.1860,
        ),
        DirectionStep(
            step_index=3,
            instruction="Arrive at your destination.",
            maneuver="arrive",
            street_name="Community Lane",
            distance_m=0.0,
            cumulative_distance_m=243.0,
            latitude=-37.8660,
            longitude=145.1865,
        ),
    ]


def test_progress_tracker_initial_start(sample_route_coordinates, sample_directions):
    """Verify progress calculation when user is at the exact origin."""
    tracker = RouteProgressTracker(
        route_coordinates=sample_route_coordinates,
        directions=sample_directions,
    )
    loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=5.0)
    progress = tracker.update_progress(loc)

    assert progress.distance_along_route_m == 0.0
    assert progress.remaining_distance_m == pytest.approx(tracker.total_route_distance_m, abs=1.0)
    assert progress.completion_percentage == 0.0
    assert progress.current_step_index == 0
    assert "Depart" in progress.next_instruction
    assert not progress.is_arrived


def test_progress_tracker_mid_route_advancement(sample_route_coordinates, sample_directions):
    """Verify advancement along route and next instruction countdown."""
    tracker = RouteProgressTracker(
        route_coordinates=sample_route_coordinates,
        directions=sample_directions,
    )

    # Position midway on segment 0 (approx 44m along)
    loc_mid = GPSLocation(latitude=-37.8650, longitude=145.1855, accuracy_m=6.0)
    p_mid = tracker.update_progress(loc_mid)

    assert p_mid.distance_along_route_m > 35.0
    assert p_mid.distance_along_route_m < 55.0
    assert p_mid.completion_percentage > 10.0
    assert p_mid.cross_track_distance_m < 5.0
    assert p_mid.next_maneuver == "right"
    assert p_mid.distance_to_next_maneuver_m < 50.0


def test_progress_arrival_detection(sample_route_coordinates, sample_directions):
    """Verify arrival is only declared after consecutive updates near destination."""
    tracker = RouteProgressTracker(
        route_coordinates=sample_route_coordinates,
        directions=sample_directions,
    )

    dest_lat, dest_lon = sample_route_coordinates[-1]
    loc_dest = GPSLocation(latitude=dest_lat, longitude=dest_lon, accuracy_m=5.0)

    # 1st update near destination: not yet confirmed (requires consecutive readings)
    p1 = tracker.update_progress(loc_dest)
    assert not p1.is_arrived

    # 2nd consecutive update near destination: confirmed arrival
    p2 = tracker.update_progress(loc_dest)
    assert p2.is_arrived
    assert p2.remaining_distance_m < 5.0


# =============================================================================
# 3. ROUTE DEVIATION & OFF-ROUTE DETECTION TESTS
# =============================================================================

def test_deviation_detector_on_route():
    """Verify user within corridor is ON_ROUTE."""
    detector = RouteDeviationDetector(base_corridor_meters=20.0, consecutive_required=3)
    loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=6.0)

    # Cross track = 8m (well within max(20, 6*1.5) = 20m)
    state = detector.evaluate_deviation(cross_track_distance_m=8.0, location=loc)
    assert state == DeviationState.ON_ROUTE


def test_deviation_detector_gps_noise_tolerance():
    """Verify single noisy GPS reading does not immediately trigger OFF_ROUTE."""
    detector = RouteDeviationDetector(base_corridor_meters=20.0, consecutive_required=3)
    loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=8.0)

    # 1st spike outside corridor (28m > 20m)
    s1 = detector.evaluate_deviation(cross_track_distance_m=28.0, location=loc)
    assert s1 == DeviationState.POSSIBLY_OFF_ROUTE

    # Next reading returns inside corridor
    s2 = detector.evaluate_deviation(cross_track_distance_m=10.0, location=loc)
    assert s2 == DeviationState.ON_ROUTE


def test_deviation_detector_confirmed_off_route():
    """Verify 3 consecutive off-corridor readings confirm OFF_ROUTE."""
    detector = RouteDeviationDetector(base_corridor_meters=20.0, consecutive_required=3)
    loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=6.0)

    s1 = detector.evaluate_deviation(cross_track_distance_m=35.0, location=loc)
    assert s1 == DeviationState.POSSIBLY_OFF_ROUTE

    s2 = detector.evaluate_deviation(cross_track_distance_m=42.0, location=loc)
    assert s2 == DeviationState.POSSIBLY_OFF_ROUTE

    s3 = detector.evaluate_deviation(cross_track_distance_m=48.0, location=loc)
    assert s3 == DeviationState.OFF_ROUTE


def test_deviation_detector_very_low_accuracy_damping():
    """Verify very poor accuracy (>50m) never aggressively declares confirmed OFF_ROUTE."""
    detector = RouteDeviationDetector(base_corridor_meters=20.0, consecutive_required=3)
    poor_loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=65.0)

    for _ in range(5):
        state = detector.evaluate_deviation(cross_track_distance_m=120.0, location=poor_loc)
        # Stays at POSSIBLY_OFF_ROUTE, never escalates to hard OFF_ROUTE
        assert state == DeviationState.POSSIBLY_OFF_ROUTE


# =============================================================================
# 4. ACCESSIBILITY-AWARE RE-ROUTING TESTS
# =============================================================================

def test_reroute_cooldown_enforcement():
    """Verify rapid recalculation loops are suppressed by the cooldown window."""
    rerouter = AccessibilityAwareRerouter(cooldown_seconds=10.0, min_movement_meters=15.0)
    rerouter.last_reroute_time = time.time() - 2.0  # Only 2s ago
    rerouter.last_reroute_position = (-37.8650, 145.1850)

    # Attempt reroute after moving only 2 meters
    req = RerouteRequest(
        current_position=(-37.86501, 145.18501),
        destination=(-37.8660, 145.1865),
    )
    res = rerouter.reroute(req)

    assert not res.success
    assert res.reroute_reason == "cooldown_active"
    assert "suppressed" in res.explanation.lower()


def test_reroute_preserves_strict_preferences():
    """Verify that re-routing strictly preserves personal mobility preferences."""
    rerouter = AccessibilityAwareRerouter(cooldown_seconds=0.0)

    strict_prefs = MobilityPreferences(
        preset_name=MobilityPresetName.MANUAL_WHEELCHAIR,
        steps=StepPreference.NEVER,
        unpaved_surfaces=AvoidanceLevel.PREFER_AVOID,
        kerb_preference=KerbPreference.AVOID_RAISED,
        max_permitted_uphill_grade_pct=6.0,
    )

    req = RerouteRequest(
        current_position=(-37.8650, 145.1850),
        destination=(-37.8655, 145.1855),
        mobility_preferences=strict_prefs,
        original_route_distance_m=100.0,
        reroute_token="token-abc-123",
    )

    res = rerouter.reroute(req, force=True)

    assert res.reroute_token == "token-abc-123"
    # Even if no regional network is loaded or mock is used, preferences must be preserved
    if res.success:
        assert res.new_route is not None
        assert "manual_wheelchair" in res.explanation


# =============================================================================
# 5. UPCOMING ACCESSIBILITY EVENTS TESTS
# =============================================================================

def test_upcoming_accessibility_events_detection(sample_route_coordinates, sample_directions):
    """Verify detection and plain-language formatting of upcoming route events."""
    metadata = [
        {
            "osmid": 101,
            "highway": "crossing",
            "is_crossing": True,
            "kerb": "unknown",
            "surface": "asphalt",
            "estimated_grade_pct": 2.0,
        },
        {
            "osmid": 102,
            "highway": "steps",
            "is_steps": True,
            "surface": "concrete",
            "estimated_grade_pct": 12.0,
        },
        {
            "osmid": 103,
            "highway": "footway",
            "surface": "gravel",
            "estimated_grade_pct": 7.5,
        },
    ]

    tracker = RouteProgressTracker(
        route_coordinates=sample_route_coordinates,
        directions=sample_directions,
        edge_metadata=metadata,
    )

    loc = GPSLocation(latitude=-37.8650, longitude=145.1850, accuracy_m=5.0)
    progress = tracker.update_progress(loc)

    events = progress.upcoming_events
    assert len(events) >= 2

    # Check kerb unknown event
    kerb_events = [e for e in events if e.type == UpcomingEventType.KERB_UNKNOWN.value]
    assert len(kerb_events) == 1
    assert "kerb ramp status unrecorded" in kerb_events[0].description
    assert kerb_events[0].severity == "warning"

    # Check stairs event
    stairs_events = [e for e in events if e.type == UpcomingEventType.STAIRS.value]
    assert len(stairs_events) == 1
    assert stairs_events[0].severity == "critical"

    # Verify events are ordered by distance ahead
    for i in range(len(events) - 1):
        assert events[i].distance_ahead_m <= events[i + 1].distance_ahead_m


# =============================================================================
# 6. SIMULATED GPS PROVIDER TESTS
# =============================================================================

def test_simulated_location_provider_normal_stream(sample_route_coordinates):
    """Verify deterministic GPS generator walks along route smoothly."""
    provider = SimulatedLocationProvider(
        route_coordinates=sample_route_coordinates,
        speed_mps=1.0,
        update_interval_s=1.0,
    )
    points = list(provider.generate_normal_stream())

    assert len(points) > 10
    # First point near start
    assert abs(points[0].latitude - sample_route_coordinates[0][0]) < 0.001
    assert abs(points[0].longitude - sample_route_coordinates[0][1]) < 0.001
    # Last point near destination
    assert abs(points[-1].latitude - sample_route_coordinates[-1][0]) < 0.0001
    assert abs(points[-1].longitude - sample_route_coordinates[-1][1]) < 0.0001


def test_simulated_location_provider_deviation_stream(sample_route_coordinates):
    """Verify generator produces points that deviate substantially from route."""
    provider = SimulatedLocationProvider(route_coordinates=sample_route_coordinates)
    dev_points = provider.generate_deviation_stream(divergence_meters=60.0, consecutive_points=4)

    assert len(dev_points) == 4
    for pt in dev_points:
        assert pt.accuracy_m == 6.0  # High accuracy, legitimately off-route


# =============================================================================
# 7. FASTAPI API INTEGRATION TESTS
# =============================================================================

client = TestClient(app)


def test_api_navigation_progress():
    """Verify POST /api/v1/navigation/progress endpoint."""
    payload = {
        "location": {
            "latitude": -37.8650,
            "longitude": 145.1850,
            "accuracy_m": 5.0,
            "heading": 90.0,
            "speed_mps": 1.0,
            "timestamp": 1700000000.0,
        },
        "route_coordinates": [
            {"latitude": -37.8650, "longitude": 145.1850},
            {"latitude": -37.8650, "longitude": 145.1860},
            {"latitude": -37.8660, "longitude": 145.1860},
        ],
    }

    res = client.post("/api/v1/navigation/progress", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "distance_along_route_m" in data
    assert "remaining_distance_m" in data
    assert "completion_percentage" in data
    assert "deviation_state" in data
    assert data["deviation_state"] == "ON_ROUTE"
    assert data["accuracy_band"] == "HIGH_ACCURACY"


def test_api_navigation_simulation_trace():
    """Verify GET /api/v1/navigation/simulation-trace endpoint."""
    res = client.get("/api/v1/navigation/simulation-trace?scenario=jitter")
    assert res.status_code == 200
    data = res.json()

    assert data["scenario"] == "jitter"
    assert data["points_count"] == 6
    assert len(data["locations"]) == 6
    assert data["locations"][0]["accuracy_m"] >= 20.0
