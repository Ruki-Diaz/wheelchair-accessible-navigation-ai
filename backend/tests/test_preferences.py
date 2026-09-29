"""Tests for Stage 8: Personal Mobility Profiles & User-Controlled Accessibility Preferences."""

import math
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from accessroute.api.main import app
from accessroute.preferences.models import (
    AvoidanceLevel,
    DataConfidenceLevel,
    KerbPreference,
    MobilityPreferences,
    MobilityPresetName,
    StepPreference,
    get_preset_preferences,
)
from accessroute.preferences.compiler import compile_preferences_to_policy
from accessroute.routing.alternatives import calculate_route_alternatives
from accessroute.routing.astar import a_star_search
from accessroute.routing.cost_evaluator import evaluate_transition_cost
from accessroute.routing.policy import RoutingPolicy
from accessroute.scoring.models import EdgeAccessibilityEvidence, FindingType, KerbType, SurfaceType, WidthMeasurement
import networkx as nx


# =============================================================================
# 1. DOMAIN MODEL & VALIDATION TESTS
# =============================================================================

def test_default_preferences_creation():
    """Verify default preferences are initialized to Manual Wheelchair defaults."""
    pref = MobilityPreferences()
    assert pref.preset == MobilityPresetName.MANUAL_WHEELCHAIR
    assert pref.avoid_steps == StepPreference.NEVER
    assert pref.unpaved_surfaces == AvoidanceLevel.PREFER_AVOID
    assert pref.preferred_maximum_uphill_grade_pct == 6.0
    assert pref.maximum_permitted_uphill_grade_pct == 10.0
    assert pref.data_confidence == DataConfidenceLevel.BALANCED


def test_validation_preferred_slope_exceeds_maximum_permitted():
    """Validates that preferred maximum slope cannot exceed hard maximum slope."""
    with pytest.raises(ValidationError) as exc_info:
        MobilityPreferences(
            preferred_maximum_uphill_grade_pct=12.0,
            maximum_permitted_uphill_grade_pct=8.0,
        )
    assert "cannot exceed" in str(exc_info.value)


def test_validation_downhill_preferred_exceeds_maximum():
    """Validates downhill preferred slope cannot exceed hard maximum."""
    with pytest.raises(ValidationError) as exc_info:
        MobilityPreferences(
            preferred_maximum_downhill_grade_pct=15.0,
            maximum_permitted_downhill_grade_pct=10.0,
        )
    assert "cannot exceed" in str(exc_info.value)


def test_validation_negative_slope_rejected():
    """Validates negative slope thresholds are rejected."""
    with pytest.raises(ValidationError):
        MobilityPreferences(preferred_maximum_uphill_grade_pct=-2.0)
    with pytest.raises(ValidationError):
        MobilityPreferences(maximum_permitted_uphill_grade_pct=-5.0)


def test_validation_negative_width_rejected():
    """Validates negative minimum path width is rejected."""
    with pytest.raises(ValidationError):
        MobilityPreferences(minimum_path_width_m=-0.5)


def test_validation_non_finite_values_rejected():
    """Validates NaN and Infinity are strictly rejected."""
    with pytest.raises(ValidationError):
        MobilityPreferences(preferred_maximum_uphill_grade_pct=float("nan"))
    with pytest.raises(ValidationError):
        MobilityPreferences(maximum_permitted_uphill_grade_pct=float("inf"))


# =============================================================================
# 2. PRESETS AND CUSTOMIZATION TESTS
# =============================================================================

def test_all_presets_available_and_editable():
    """Verify all starting presets exist and can be freely customized."""
    for preset_name in MobilityPresetName:
        pref = get_preset_preferences(preset_name)
        assert pref.preset == preset_name
        # Test customization
        pref.preferred_maximum_uphill_grade_pct = 4.5
        assert pref.preferred_maximum_uphill_grade_pct == 4.5


def test_preset_semantics_contrast():
    """Verify presets have distinct, meaningful starting configurations."""
    manual = get_preset_preferences(MobilityPresetName.MANUAL_WHEELCHAIR)
    powered = get_preset_preferences(MobilityPresetName.POWERED_WHEELCHAIR)
    walker = get_preset_preferences(MobilityPresetName.WALKER)
    pram = get_preset_preferences(MobilityPresetName.PRAM)

    # Manual has lower slope limit than Powered
    assert manual.maximum_permitted_uphill_grade_pct < powered.maximum_permitted_uphill_grade_pct
    # Walker tolerates stairs when necessary, whereas wheelchair presets never use mapped stairs
    assert manual.avoid_steps == StepPreference.NEVER
    assert walker.avoid_steps in (StepPreference.AVOID_WHEN_POSSIBLE, StepPreference.PREFER_AVOID)
    # Pram is flexible on unpaved surfaces compared to wheelchair
    assert pram.unpaved_surfaces == AvoidanceLevel.ALLOW


# =============================================================================
# 3. POLICY COMPILER TESTS
# =============================================================================

def test_compiler_step_preferences():
    """Verify compile_preferences_to_policy maps step preferences correctly."""
    # NEVER -> prohibit
    p_never = compile_preferences_to_policy(MobilityPreferences(avoid_steps=StepPreference.NEVER))
    assert p_never.prohibit_steps_without_ramp is True

    # AVOID_WHEN_POSSIBLE -> soft penalty, no hard prohibition
    p_avoid = compile_preferences_to_policy(MobilityPreferences(avoid_steps=StepPreference.AVOID_WHEN_POSSIBLE))
    assert p_avoid.prohibit_steps_without_ramp is False
    assert p_avoid.penalty_steps_without_ramp_m > 0

    # ALLOW -> no prohibition, no penalty
    p_allow = compile_preferences_to_policy(MobilityPreferences(avoid_steps=StepPreference.ALLOW))
    assert p_allow.prohibit_steps_without_ramp is False
    assert p_allow.penalty_steps_without_ramp_m == 0.0


def test_compiler_surface_avoidance_levels():
    """Verify unpaved surface avoidance levels translate to hard vs soft costs."""
    # STRICTLY_AVOID -> prohibit
    p_strict = compile_preferences_to_policy(MobilityPreferences(unpaved_surfaces=AvoidanceLevel.STRICTLY_AVOID))
    assert p_strict.prohibit_unpaved_surfaces is True

    # PREFER_AVOID -> soft penalty
    p_prefer = compile_preferences_to_policy(MobilityPreferences(unpaved_surfaces=AvoidanceLevel.PREFER_AVOID))
    assert p_prefer.prohibit_unpaved_surfaces is False
    assert p_prefer.penalty_unpaved_surface_m > 0

    # ALLOW -> zero penalty
    p_allow = compile_preferences_to_policy(MobilityPreferences(unpaved_surfaces=AvoidanceLevel.ALLOW))
    assert p_allow.prohibit_unpaved_surfaces is False
    assert p_allow.penalty_unpaved_surface_m == 0.0


def test_compiler_kerb_preferences():
    """Verify kerb preferences compilation."""
    # STRICTLY_AVOID unknown kerbs -> hard prohibition
    p_strict = compile_preferences_to_policy(MobilityPreferences(unknown_kerbs=AvoidanceLevel.STRICTLY_AVOID))
    assert p_strict.prohibit_unknown_kerb_crossings is True

    # PREFER_AVOID -> soft penalty
    p_prefer = compile_preferences_to_policy(MobilityPreferences(unknown_kerbs=AvoidanceLevel.PREFER_AVOID))
    assert p_prefer.prohibit_unknown_kerb_crossings is False
    assert p_prefer.uncertainty_missing_crossing_kerb_m > 0


def test_compiler_data_confidence_scaling():
    """Verify data confidence scaling affects uncertainty weight deterministically."""
    p_flex = compile_preferences_to_policy(MobilityPreferences(data_confidence=DataConfidenceLevel.FLEXIBLE))
    p_bal = compile_preferences_to_policy(MobilityPreferences(data_confidence=DataConfidenceLevel.BALANCED))
    p_caut = compile_preferences_to_policy(MobilityPreferences(data_confidence=DataConfidenceLevel.CAUTIOUS))

    assert p_flex.uncertainty_weight < p_bal.uncertainty_weight
    assert p_bal.uncertainty_weight < p_caut.uncertainty_weight


def test_compiler_slope_limits():
    """Verify slope limits compile accurately."""
    pref = MobilityPreferences(
        preferred_maximum_uphill_grade_pct=4.0,
        maximum_permitted_uphill_grade_pct=7.5,
        preferred_maximum_downhill_grade_pct=5.0,
        maximum_permitted_downhill_grade_pct=8.0,
    )
    policy = compile_preferences_to_policy(pref)
    assert policy.max_preferred_uphill_grade_pct == 4.0
    assert policy.max_permitted_uphill_grade_pct == 7.5
    assert policy.max_preferred_downhill_grade_pct == 5.0


# =============================================================================
# 4. ROUTING BEHAVIOR WITH PREFERENCES ON SYNTHETIC GRAPHS
# =============================================================================

def test_routing_strict_stairs_avoidance():
    """Test that StepPreference.NEVER strictly blocks stairs in routing."""
    G = nx.MultiDiGraph()
    # Route 1: Short with stairs (10m)
    G.add_node(1, x=145.0, y=-37.0)
    G.add_node(2, x=145.0001, y=-37.0)
    ev_stairs = EdgeAccessibilityEvidence(
        highway_type="steps",
        is_steps=True,
        findings={FindingType.STEPS_PRESENT},
    )
    G.add_edge(1, 2, length=10.0, highway="steps", evidence=ev_stairs)

    # Route 2: Detour via flat paved path (30m)
    G.add_node(3, x=145.0, y=-37.0002)
    ev_flat = EdgeAccessibilityEvidence(
        highway_type="footway",
        surface=SurfaceType.ASPHALT,
        findings={FindingType.PAVED_SURFACE_RECORDED},
    )
    G.add_edge(1, 3, length=15.0, highway="footway", evidence=ev_flat)
    G.add_edge(3, 2, length=15.0, highway="footway", evidence=ev_flat)

    # NEVER use mapped stairs -> takes detour via node 3
    pref_never = MobilityPreferences(avoid_steps=StepPreference.NEVER)
    policy_never = compile_preferences_to_policy(pref_never)
    res_never = a_star_search(G, 1, 2, policy=policy_never)
    assert res_never.found is True
    assert res_never.nodes == [1, 3, 2]

    # ALLOW stairs -> takes direct 10m stairs
    pref_allow = MobilityPreferences(avoid_steps=StepPreference.ALLOW)
    policy_allow = compile_preferences_to_policy(pref_allow)
    res_allow = a_star_search(G, 1, 2, policy=policy_allow)
    assert res_allow.found is True
    assert res_allow.nodes == [1, 2]


def test_routing_soft_stairs_avoidance_when_no_alternative():
    """When StepPreference is AVOID_WHEN_POSSIBLE and no alternative exists, route is still found with penalty."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.0, y=-37.0)
    G.add_node(2, x=145.0001, y=-37.0)
    ev_stairs = EdgeAccessibilityEvidence(
        highway_type="steps",
        is_steps=True,
        findings={FindingType.STEPS_PRESENT},
    )
    G.add_edge(1, 2, length=10.0, highway="steps", evidence=ev_stairs)

    # NEVER -> route not found
    pref_never = MobilityPreferences(avoid_steps=StepPreference.NEVER)
    res_never = a_star_search(G, 1, 2, policy=compile_preferences_to_policy(pref_never))
    assert res_never.found is False

    # AVOID_WHEN_POSSIBLE -> route found despite stairs
    pref_avoid = MobilityPreferences(avoid_steps=StepPreference.AVOID_WHEN_POSSIBLE)
    res_avoid = a_star_search(G, 1, 2, policy=compile_preferences_to_policy(pref_avoid))
    assert res_avoid.found is True
    assert res_avoid.nodes == [1, 2]


def test_routing_width_strict_prohibition():
    """Test that paths narrower than minimum width are strictly avoided when configured."""
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.0, y=-37.0)
    G.add_node(2, x=145.0001, y=-37.0)
    ev_narrow = EdgeAccessibilityEvidence(
        highway_type="footway",
        width=WidthMeasurement(width_meters=0.7, is_parsed=True),
        surface=SurfaceType.ASPHALT,
    )
    G.add_edge(1, 2, length=10.0, width=0.7, evidence=ev_narrow)

    # Strict avoidance with min width 0.9m -> blocked
    pref_strict = MobilityPreferences(
        minimum_path_width_m=0.9,
        narrow_paths=AvoidanceLevel.STRICTLY_AVOID,
    )
    res_strict = a_star_search(G, 1, 2, policy=compile_preferences_to_policy(pref_strict))
    assert res_strict.found is False

    # ALLOW -> path allowed
    pref_allow = MobilityPreferences(
        minimum_path_width_m=0.9,
        narrow_paths=AvoidanceLevel.ALLOW,
    )
    res_allow = a_star_search(G, 1, 2, policy=compile_preferences_to_policy(pref_allow))
    assert res_allow.found is True


# =============================================================================
# 5. PREFERENCE CONFLICT DIAGNOSIS & NO SILENT RELAXATION
# =============================================================================

def test_conflict_diagnosis_mapped_stairs():
    """Verify conflict diagnosis identifies mapped stairs as the blocking cause."""
    pref = MobilityPreferences(avoid_steps=StepPreference.NEVER)
    G = nx.MultiDiGraph()
    G.add_node(1, x=145.0, y=-37.0)
    G.add_node(2, x=145.0001, y=-37.0)
    ev_stairs = EdgeAccessibilityEvidence(
        highway_type="steps",
        is_steps=True,
        findings={FindingType.STEPS_PRESENT},
    )
    G.add_edge(1, 2, length=10.0, highway="steps", evidence=ev_stairs)

    policy = compile_preferences_to_policy(pref)
    res = a_star_search(G, 1, 2, policy=policy)
    assert res.found is False  # Never silently relaxed!


# =============================================================================
# 6. API INTEGRATION TESTS
# =============================================================================

client = TestClient(app)


def test_api_route_alternatives_with_preferences():
    """Test POST /api/v1/routes/alternatives with personal mobility preferences."""
    payload = {
        "origin": {"latitude": -37.868, "longitude": 145.185},
        "destination": {"latitude": -37.871, "longitude": 145.189},
        "enrich_elevation": False,
        "preferences": {
            "preset": "manual_wheelchair",
            "avoid_steps": "never",
            "unpaved_surfaces": "prefer_avoid",
            "preferred_maximum_uphill_grade_pct": 5.0,
            "maximum_permitted_uphill_grade_pct": 8.0,
            "data_confidence": "balanced",
        },
    }
    resp = client.post("/api/v1/routes/alternatives", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert len(data["alternatives"]) >= 1

    # Candidate 1 should be the user's preferred route
    pref_alt = data["alternatives"][0]
    assert "Preferred" in pref_alt["badge"] or "Preferred" in pref_alt["title"]
    assert "customised to your" in pref_alt["description"].lower() or "manual wheelchair" in pref_alt["description"].lower()


def test_api_route_alternatives_rejects_invalid_preferences():
    """Test that API cleanly rejects invalid preference combinations with 422."""
    payload = {
        "origin": {"latitude": -37.868, "longitude": 145.185},
        "destination": {"latitude": -37.871, "longitude": 145.189},
        "preferences": {
            "preferred_maximum_uphill_grade_pct": 12.0,
            "maximum_permitted_uphill_grade_pct": 6.0,  # Invalid: preferred > maximum
        },
    }
    resp = client.post("/api/v1/routes/alternatives", json=payload)
    assert resp.status_code == 422


def test_api_route_plan_with_preferences():
    """Test POST /api/v1/routes/plan accepts mobility preferences."""
    payload = {
        "origin": {"latitude": -37.868, "longitude": 145.185},
        "destination": {"latitude": -37.871, "longitude": 145.189},
        "enrich_elevation": False,
        "preferences": {
            "preset": "powered_wheelchair",
            "preferred_maximum_uphill_grade_pct": 7.0,
            "maximum_permitted_uphill_grade_pct": 12.0,
        },
    }
    resp = client.post("/api/v1/routes/plan", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert "preferences:powered_wheelchair" in data["policy"]
