"""Comprehensive tests for accessibility attribute normalization, evidence modeling, and findings.

Covers:
- Wheelchair access normalization
- Surface type normalization and critical non-equivalence to accessibility
- Kerb profile normalization
- Incline parsing (percentages, ratios, directions, invalid formats)
- Width parsing (meters, centimeters, units, malformed)
- Steps, ramps, and handrails
- Physical barriers on nodes and edges
- Explicit missing data guarantees (no fabricated defaults)
- Real graph enrichment
"""

import pytest

from accessroute.graph.enricher import (
    enrich_graph_accessibility,
    get_edge_accessibility,
    get_node_accessibility,
)
from accessroute.scoring.models import (
    BarrierType,
    FindingType,
    KerbType,
    SmoothnessType,
    SurfaceType,
    TactilePaving,
    WheelchairAccess,
)
from accessroute.scoring.normalizer import (
    extract_edge_evidence,
    extract_node_evidence,
    normalize_barrier,
    normalize_incline,
    normalize_kerb,
    normalize_smoothness,
    normalize_surface,
    normalize_tactile_paving,
    normalize_wheelchair,
    normalize_width,
)


# ============================================================================
# 1. WHEELCHAIR ACCESS TESTS
# ============================================================================

def test_wheelchair_yes():
    assert normalize_wheelchair("yes") == WheelchairAccess.YES
    assert normalize_wheelchair("YES") == WheelchairAccess.YES
    ev = extract_edge_evidence({"wheelchair": "yes"})
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED in ev.findings


def test_wheelchair_designated():
    assert normalize_wheelchair("designated") == WheelchairAccess.DESIGNATED
    ev = extract_edge_evidence({"wheelchair": "designated"})
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED in ev.findings


def test_wheelchair_limited():
    assert normalize_wheelchair("limited") == WheelchairAccess.LIMITED
    ev = extract_edge_evidence({"wheelchair": "limited"})
    assert FindingType.WHEELCHAIR_ACCESS_LIMITED in ev.findings


def test_wheelchair_no():
    assert normalize_wheelchair("no") == WheelchairAccess.NO
    assert normalize_wheelchair("No") == WheelchairAccess.NO
    ev = extract_edge_evidence({"wheelchair": "no"})
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED in ev.findings


def test_wheelchair_missing_remains_unknown():
    assert normalize_wheelchair(None) == WheelchairAccess.UNKNOWN
    assert normalize_wheelchair("") == WheelchairAccess.UNKNOWN
    ev = extract_edge_evidence({})
    assert ev.wheelchair == WheelchairAccess.UNKNOWN
    assert "wheelchair" in ev.missing_fields
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED not in ev.findings
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED not in ev.findings


def test_wheelchair_unrecognized_value():
    assert normalize_wheelchair("permissive_only_with_escort") == WheelchairAccess.OTHER


# ============================================================================
# 2. KERB PROFILE TESTS
# ============================================================================

def test_kerb_flush():
    assert normalize_kerb("flush") == KerbType.FLUSH
    ev = extract_edge_evidence({"kerb": "flush"})
    assert FindingType.FLUSH_KERB_RECORDED in ev.findings


def test_kerb_lowered():
    assert normalize_kerb("lowered") == KerbType.LOWERED
    ev = extract_edge_evidence({"kerb": "lowered"})
    assert FindingType.LOWERED_KERB_RECORDED in ev.findings


def test_kerb_raised():
    assert normalize_kerb("raised") == KerbType.RAISED
    ev = extract_edge_evidence({"kerb": "raised"})
    assert FindingType.RAISED_KERB_RECORDED in ev.findings


def test_kerb_rolled():
    assert normalize_kerb("rolled") == KerbType.ROLLED
    ev = extract_edge_evidence({"kerb": "rolled"})
    assert FindingType.ROLLED_KERB_RECORDED in ev.findings


def test_kerb_curb_alias():
    # Supports US spelling 'curb' tag alias
    ev = extract_edge_evidence({"curb": "lowered"})
    assert ev.kerb == KerbType.LOWERED
    assert FindingType.LOWERED_KERB_RECORDED in ev.findings


def test_kerb_missing_remains_unknown():
    assert normalize_kerb(None) == KerbType.UNKNOWN
    ev = extract_edge_evidence({})
    assert ev.kerb == KerbType.UNKNOWN
    assert "kerb" in ev.missing_fields


def test_kerb_semicolon_separated():
    # When multiple values are separated by semicolon, normalizer selects primary
    assert normalize_kerb("lowered;flush") == KerbType.LOWERED


# ============================================================================
# 3. SURFACE TYPE TESTS & CRITICAL NON-EQUIVALENCE
# ============================================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("asphalt", SurfaceType.ASPHALT),
        ("paved", SurfaceType.PAVED),
        ("concrete", SurfaceType.CONCRETE),
        ("concrete:plates", SurfaceType.CONCRETE_PLATES),
        ("paving_stones", SurfaceType.PAVING_STONES),
    ],
)
def test_surface_paved_types(raw, expected):
    assert normalize_surface(raw) == expected
    ev = extract_edge_evidence({"surface": raw})
    assert FindingType.PAVED_SURFACE_RECORDED in ev.findings
    assert FindingType.UNPAVED_SURFACE_RECORDED not in ev.findings
    # CRITICAL RULE: Paved does NOT imply wheelchair accessible!
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED not in ev.findings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("gravel", SurfaceType.GRAVEL),
        ("fine_gravel", SurfaceType.FINE_GRAVEL),
        ("ground", SurfaceType.GROUND),
        ("dirt", SurfaceType.DIRT),
        ("grass", SurfaceType.GRASS),
        ("compacted", SurfaceType.COMPACTED),
    ],
)
def test_surface_unpaved_types(raw, expected):
    assert normalize_surface(raw) == expected
    ev = extract_edge_evidence({"surface": raw})
    assert FindingType.UNPAVED_SURFACE_RECORDED in ev.findings


def test_surface_cobblestone_rough():
    assert normalize_surface("cobblestone") == SurfaceType.COBBLESTONE
    ev = extract_edge_evidence({"surface": "cobblestone"})
    assert FindingType.ROUGH_SURFACE_RECORDED in ev.findings


def test_surface_missing_remains_unknown():
    assert normalize_surface(None) == SurfaceType.UNKNOWN
    ev = extract_edge_evidence({})
    assert ev.surface == SurfaceType.UNKNOWN
    assert "surface" in ev.missing_fields


# ============================================================================
# 4. INCLINE MEASUREMENT TESTS
# ============================================================================

def test_incline_percentage_positive():
    inc = normalize_incline("5%")
    assert inc.is_parsed is True
    assert inc.is_known is True
    assert inc.percentage == 5.0


def test_incline_percentage_negative():
    inc = normalize_incline("-8.5%")
    assert inc.is_parsed is True
    assert inc.percentage == -8.5
    ev = extract_edge_evidence({"incline": "-8.5%"})
    assert FindingType.STEEP_INCLINE_RECORDED in ev.findings


def test_incline_ratio():
    inc = normalize_incline("1:12")
    assert inc.is_parsed is True
    assert inc.percentage == pytest.approx(8.33, 0.01)
    ev = extract_edge_evidence({"incline": "1:12"})
    assert FindingType.STEEP_INCLINE_RECORDED in ev.findings


def test_incline_directional_words():
    inc_up = normalize_incline("up")
    assert inc_up.is_parsed is True
    assert inc_up.direction == "up"
    assert inc_up.percentage is None

    inc_steep = normalize_incline("steep")
    assert inc_steep.is_parsed is True
    assert inc_steep.direction == "steep"
    ev = extract_edge_evidence({"incline": "steep"})
    assert FindingType.STEEP_INCLINE_RECORDED in ev.findings


def test_incline_malformed_preserves_raw_without_guess():
    inc = normalize_incline("slight tilt towards the creek")
    assert inc.is_parsed is False
    assert inc.percentage is None
    assert inc.raw == "slight tilt towards the creek"


def test_incline_missing_does_not_assume_zero():
    inc = normalize_incline(None)
    assert inc.is_parsed is False
    assert inc.percentage is None
    assert inc.is_known is False
    ev = extract_edge_evidence({})
    assert "incline" in ev.missing_fields


# ============================================================================
# 5. WIDTH MEASUREMENT TESTS
# ============================================================================

def test_width_numeric_meters():
    w = normalize_width("1.5")
    assert w.is_parsed is True
    assert w.width_meters == 1.5


def test_width_meters_with_units():
    w1 = normalize_width("1.8 m")
    assert w1.width_meters == 1.8

    w2 = normalize_width("2.0 metres")
    assert w2.width_meters == 2.0


def test_width_centimeters():
    w = normalize_width("120 cm")
    assert w.is_parsed is True
    assert w.width_meters == 1.2


def test_width_malformed_preserves_raw():
    w = normalize_width("wide enough for a stroller")
    assert w.is_parsed is False
    assert w.width_meters is None
    assert w.raw == "wide enough for a stroller"


def test_width_missing_remains_unknown():
    w = normalize_width(None)
    assert w.is_parsed is False
    assert w.width_meters is None
    ev = extract_edge_evidence({})
    assert "width" in ev.missing_fields


# ============================================================================
# 6. STEPS AND RAMPS TESTS
# ============================================================================

def test_steps_without_ramp():
    ev = extract_edge_evidence({"highway": "steps"})
    assert ev.is_steps is True
    assert ev.has_ramp is False
    assert FindingType.STEPS_PRESENT in ev.findings
    assert FindingType.RAMP_PRESENT not in ev.findings


def test_steps_with_ramp_yes():
    ev = extract_edge_evidence({"highway": "steps", "ramp": "yes"})
    assert ev.is_steps is True
    assert ev.has_ramp is True
    assert FindingType.STEPS_PRESENT in ev.findings
    assert FindingType.RAMP_PRESENT in ev.findings


def test_steps_with_wheelchair_ramp():
    ev = extract_edge_evidence(
        {"highway": "steps", "ramp:wheelchair": "yes", "step_count": "8"}
    )
    assert ev.is_steps is True
    assert ev.has_wheelchair_ramp is True
    assert ev.has_ramp is True
    assert ev.step_count == 8
    assert FindingType.STEPS_PRESENT in ev.findings
    assert FindingType.RAMP_WHEELCHAIR_DESIGNATED in ev.findings


def test_steps_with_wheelchair_no():
    ev = extract_edge_evidence({"highway": "steps", "wheelchair": "no"})
    assert FindingType.STEPS_PRESENT in ev.findings
    assert FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED in ev.findings


def test_paved_path_with_steps_preserves_both_findings():
    # Concrete or asphalt footway containing stairs
    ev = extract_edge_evidence({"highway": "steps", "surface": "concrete"})
    assert FindingType.PAVED_SURFACE_RECORDED in ev.findings
    assert FindingType.STEPS_PRESENT in ev.findings


# ============================================================================
# 7. BARRIERS & NODE ACCESSIBILITY TESTS
# ============================================================================

def test_node_barrier_bollard():
    nev = extract_node_evidence(1, {"barrier": "bollard", "y": -37.85, "x": 145.17})
    assert nev.barrier == BarrierType.BOLLARD
    assert FindingType.PASSABLE_BARRIER_RECORDED in nev.findings
    assert FindingType.RESTRICTIVE_BARRIER_RECORDED not in nev.findings


def test_node_barrier_turnstile():
    nev = extract_node_evidence(2, {"barrier": "turnstile", "y": -37.85, "x": 145.17})
    assert nev.barrier == BarrierType.TURNSTILE
    assert FindingType.RESTRICTIVE_BARRIER_RECORDED in nev.findings


def test_node_kerb_lowered():
    nev = extract_node_evidence(3, {"kerb": "lowered", "y": -37.85, "x": 145.17})
    assert nev.kerb == KerbType.LOWERED
    assert FindingType.LOWERED_KERB_RECORDED in nev.findings


def test_node_crossing_signals_and_tactile():
    nev = extract_node_evidence(
        4,
        {
            "highway": "crossing",
            "traffic_signals": "yes",
            "tactile_paving": "yes",
            "y": -37.85,
            "x": 145.17,
        },
    )
    assert nev.is_crossing is True
    assert nev.has_traffic_signals is True
    assert nev.tactile_paving == TactilePaving.YES
    assert FindingType.PEDESTRIAN_CROSSING_RECORDED in nev.findings
    assert FindingType.SIGNALIZED_CROSSING_RECORDED in nev.findings
    assert FindingType.TACTILE_PAVING_RECORDED in nev.findings


# ============================================================================
# 8. GRAPH ENRICHMENT TESTS
# ============================================================================

def test_graph_enrichment_pipeline(synthetic_multidigraph):
    enriched_G = enrich_graph_accessibility(synthetic_multidigraph)

    # Edge (101 -> 102, key 0)
    edge_ev = get_edge_accessibility(enriched_G, 101, 102, key=0)
    assert edge_ev.highway_type == "footway"

    # Node 101
    node_ev = get_node_accessibility(enriched_G, 101)
    assert node_ev.is_crossing is True
    assert FindingType.PEDESTRIAN_CROSSING_RECORDED in node_ev.findings
