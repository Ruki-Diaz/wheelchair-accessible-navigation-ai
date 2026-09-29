"""Tests for deterministic turn-by-turn navigation guidance in Stage 7."""

import math
import networkx as nx
import pytest
from shapely.geometry import LineString

from accessroute.routing.directions import (
    calculate_bearing,
    calculate_turn_angle,
    classify_maneuver,
    extract_edge_accessibility_cues,
    extract_street_name,
    generate_turn_by_turn_directions,
    get_bearing_cardinal,
)


def test_bearing_calculation():
    # Due North: (0, 0) -> (1, 0)
    assert round(calculate_bearing(0.0, 0.0, 1.0, 0.0)) == 0
    # Due East: (0, 0) -> (0, 1)
    assert round(calculate_bearing(0.0, 0.0, 0.0, 1.0)) == 90
    # Due South: (1, 0) -> (0, 0)
    assert round(calculate_bearing(1.0, 0.0, 0.0, 0.0)) == 180
    # Due West: (0, 1) -> (0, 0)
    assert round(calculate_bearing(0.0, 1.0, 0.0, 0.0)) == 270


def test_turn_angle_calculation():
    # Straight (0 deg difference)
    assert calculate_turn_angle(0.0, 0.0) == 0.0
    # 90 deg right turn (North to East)
    assert calculate_turn_angle(0.0, 90.0) == 90.0
    # 90 deg left turn (North to West)
    assert calculate_turn_angle(0.0, 270.0) == -90.0
    # Sharp turn (North to South-West: 0 to 225 deg -> -135 deg)
    assert calculate_turn_angle(0.0, 225.0) == -135.0


def test_classify_maneuver():
    assert classify_maneuver(0.0) == "straight"
    assert classify_maneuver(10.0) == "straight"
    assert classify_maneuver(30.0) == "slight_right"
    assert classify_maneuver(90.0) == "right"
    assert classify_maneuver(150.0) == "sharp_right"
    assert classify_maneuver(-30.0) == "slight_left"
    assert classify_maneuver(-90.0) == "left"
    assert classify_maneuver(-150.0) == "sharp_left"
    # Crossing override
    assert classify_maneuver(0.0, is_crossing=True) == "cross"


def test_cardinal_directions():
    assert get_bearing_cardinal(0.0) == "north"
    assert get_bearing_cardinal(45.0) == "northeast"
    assert get_bearing_cardinal(90.0) == "east"
    assert get_bearing_cardinal(180.0) == "south"
    assert get_bearing_cardinal(270.0) == "west"


def test_extract_street_name():
    assert extract_street_name({"name": "Swanston Street"}) == "Swanston Street"
    assert extract_street_name({"name": ["Burwood Hwy", "State Route 26"]}) == "Burwood Hwy"
    assert extract_street_name({"highway": "footway", "footway": "sidewalk"}) == "Sidewalk / Footpath"
    assert extract_street_name({"is_crossing": True}) == "Pedestrian crossing"
    assert extract_street_name({"highway": "steps"}) == "Stairway"
    assert extract_street_name({}) == "Footpath"


def test_extract_accessibility_cues():
    edge_paved = {
        "surface": "asphalt",
        "is_crossing": True,
        "kerb": "lowered",
        "absolute_grade": 0.045,
        "slope_direction": "uphill",
    }
    cues, warnings = extract_edge_accessibility_cues(edge_paved)
    assert any("paved surface" in c for c in cues)
    assert any("Lowered/flush kerb" in c for c in cues)
    assert any("moderate uphill grade" in c for c in cues)
    assert len(warnings) == 0

    edge_rough = {
        "surface": "gravel",
        "is_crossing": True,
        "kerb": "unknown",
        "highway": "steps",
        "has_ramp": False,
        "absolute_grade": 0.08,
        "slope_direction": "uphill",
    }
    cues2, warnings2 = extract_edge_accessibility_cues(edge_rough)
    assert any("unpaved surface" in w for w in warnings2)
    assert any("Kerb ramp status unrecorded" in w for w in warnings2)
    assert any("Mapped stairs" in w for w in warnings2)
    assert any("steep uphill grade" in w for w in warnings2)


def test_generate_turn_by_turn_directions():
    # Build synthetic 3-edge route: North along Footpath, Turn Right onto Main St, Cross Roadway
    nodes = [101, 102, 103, 104]
    edges = [
        {
            "name": "Library Footpath",
            "highway": "footway",
            "length": 80.0,
            "surface": "concrete",
            "geometry": LineString([(145.170, -37.850), (145.170, -37.849)]),
        },
        {
            "name": "Main Street",
            "highway": "footway",
            "length": 120.0,
            "surface": "asphalt",
            "geometry": LineString([(145.170, -37.849), (145.172, -37.849)]),
        },
        {
            "name": "Main Street Crossing",
            "is_crossing": True,
            "highway": "crossing",
            "kerb": "lowered",
            "length": 15.0,
            "surface": "asphalt",
            "geometry": LineString([(145.172, -37.849), (145.172, -37.8488)]),
        },
    ]

    steps = generate_turn_by_turn_directions(nodes, edges)
    assert len(steps) >= 3
    # Step 1: Departure on Library Footpath
    assert "Library Footpath" in steps[0].street_name
    assert steps[0].distance_m == 80.0
    # Subsequent Step: Turn onto Main Street
    main_step = next(s for s in steps if "Main Street" in s.street_name)
    assert main_step.distance_m == 120.0
    # Final step: Arrive
    assert steps[-1].maneuver == "arrive"
    assert steps[-1].distance_m == 0.0
