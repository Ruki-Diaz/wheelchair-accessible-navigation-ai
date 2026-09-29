"""Policy compiler transforming semantic user preferences into mathematical RoutingPolicy.

Translates human-understandable constraint levels (ALLOW, PREFER_AVOID, STRICTLY_AVOID)
into calibrated virtual meter penalties, hard graph exclusions, and uncertainty multipliers.
"""

from typing import Optional
from accessroute.preferences.models import (
    AvoidanceLevel,
    DataConfidenceLevel,
    KerbPreference,
    MobilityPreferences,
    StepPreference,
)
from accessroute.routing.policy import RoutingPolicy


def compile_preferences_to_policy(preferences: MobilityPreferences) -> RoutingPolicy:
    """Compile a user's MobilityPreferences into an active RoutingPolicy.

    Ensures that frontend clients cannot inject arbitrary mathematical multipliers
    or break admissibility invariants, while translating user constraints into
    authoritative algorithmic behavior.

    Args:
        preferences: Validated MobilityPreferences instance.

    Returns:
        RoutingPolicy ready for multi-criteria pathfinding.
    """
    policy_name = f"user_profile_{preferences.preset_name.value}"
    desc = f"Personalized routing policy derived from {preferences.preset_name.value} preferences."

    # 1. Stairs & Steps
    if preferences.steps == StepPreference.NEVER:
        prohibit_steps = True
        penalty_steps = 0.0
    elif preferences.steps in (StepPreference.PREFER_AVOID, StepPreference.AVOID_WHEN_POSSIBLE):
        prohibit_steps = False
        penalty_steps = 600.0  # Substantial penalty to avoid stairs unless no alternative exists
    else:  # ALLOW
        prohibit_steps = False
        penalty_steps = 0.0

    # 2. Surfaces
    if preferences.unpaved_surfaces == AvoidanceLevel.STRICTLY_AVOID:
        prohibit_unpaved = True
        penalty_unpaved = 0.0
        penalty_grass = 0.0
    elif preferences.unpaved_surfaces == AvoidanceLevel.PREFER_AVOID:
        prohibit_unpaved = False
        penalty_unpaved = 160.0
        penalty_grass = 250.0
    else:  # ALLOW
        prohibit_unpaved = False
        penalty_unpaved = 0.0
        penalty_grass = 20.0

    if preferences.rough_surfaces == AvoidanceLevel.STRICTLY_AVOID:
        penalty_rough = 1000.0
    elif preferences.rough_surfaces == AvoidanceLevel.PREFER_AVOID:
        penalty_rough = 80.0
    else:  # ALLOW
        penalty_rough = 0.0

    if preferences.unknown_surfaces == AvoidanceLevel.STRICTLY_AVOID:
        uncertainty_surface = 500.0
    elif preferences.unknown_surfaces == AvoidanceLevel.PREFER_AVOID:
        uncertainty_surface = 45.0
    else:  # ALLOW
        uncertainty_surface = 5.0

    # 3. Kerbs & Crossings
    if preferences.kerb_preference == KerbPreference.AVOID_RAISED:
        penalty_raised = 250.0
        penalty_rolled = 35.0
    elif preferences.kerb_preference == KerbPreference.PREFER_LOWERED:
        penalty_raised = 150.0
        penalty_rolled = 25.0
    else:  # ALLOW_ANY
        penalty_raised = 15.0
        penalty_rolled = 5.0

    prohibit_unknown_kerb = False
    if preferences.unknown_kerbs == AvoidanceLevel.STRICTLY_AVOID:
        prohibit_unknown_kerb = True
        uncertainty_kerb = 2000.0  # Virtually prohibitive unless no alternative exists
    elif preferences.unknown_kerbs == AvoidanceLevel.PREFER_AVOID:
        uncertainty_kerb = 80.0
    else:  # ALLOW
        uncertainty_kerb = 0.0

    # 4. Path Width & Barriers
    prohibit_width = False
    penalty_width = 0.0
    if preferences.minimum_path_width_m is not None:
        if preferences.narrow_paths == AvoidanceLevel.STRICTLY_AVOID:
            prohibit_width = True
            penalty_width = 250.0
        elif preferences.narrow_paths == AvoidanceLevel.PREFER_AVOID:
            prohibit_width = False
            penalty_width = 150.0
        else:
            prohibit_width = False
            penalty_width = 0.0

    if preferences.unknown_width == AvoidanceLevel.STRICTLY_AVOID:
        uncertainty_width = 800.0
    elif preferences.unknown_width == AvoidanceLevel.PREFER_AVOID:
        uncertainty_width = 50.0
    else:  # ALLOW
        uncertainty_width = 0.0

    if preferences.avoid_restrictive_barriers == AvoidanceLevel.STRICTLY_AVOID:
        prohibit_barriers = True
        penalty_passable_barrier = 50.0
    elif preferences.avoid_restrictive_barriers == AvoidanceLevel.PREFER_AVOID:
        prohibit_barriers = False
        penalty_passable_barrier = 120.0
    else:  # ALLOW
        prohibit_barriers = False
        penalty_passable_barrier = 0.0

    # 5. Global Uncertainty Weight
    if preferences.data_confidence == DataConfidenceLevel.FLEXIBLE:
        unc_weight = 0.3
    elif preferences.data_confidence == DataConfidenceLevel.CAUTIOUS:
        unc_weight = 2.2
    else:  # BALANCED
        unc_weight = 1.0

    # 6. Slopes
    prohibit_steep = preferences.max_permitted_uphill_grade_pct is not None

    return RoutingPolicy(
        name=policy_name,
        description=desc,
        prohibit_steps_without_ramp=prohibit_steps,
        prohibit_wheelchair_no=True,
        prohibit_known_restrictive_barriers=prohibit_barriers,
        prohibit_unpaved_surfaces=prohibit_unpaved,
        prohibit_below_min_width=prohibit_width,
        prohibit_unknown_kerb_crossings=prohibit_unknown_kerb,
        minimum_path_width_m=preferences.minimum_path_width_m,
        max_tolerable_incline_pct=preferences.max_permitted_uphill_grade_pct,
        penalty_steps_without_ramp_m=penalty_steps,
        penalty_below_min_width_m=penalty_width,
        penalty_unpaved_surface_m=penalty_unpaved,
        penalty_rough_surface_m=penalty_rough,
        penalty_grass_surface_m=penalty_grass,
        penalty_raised_kerb_m=penalty_raised,
        penalty_rolled_kerb_m=penalty_rolled,
        preference_lowered_kerb_m=0.0,
        preference_flush_kerb_m=0.0,
        penalty_per_incline_pct_m=15.0,
        penalty_uncontrolled_crossing_m=20.0,
        penalty_passable_barrier_m=penalty_passable_barrier,
        terrain_weight=1.2,
        prohibit_steep_incline=prohibit_steep,
        max_preferred_uphill_grade_pct=preferences.max_preferred_uphill_grade_pct,
        max_permitted_uphill_grade_pct=preferences.max_permitted_uphill_grade_pct,
        max_preferred_downhill_grade_pct=preferences.max_preferred_downhill_grade_pct,
        penalty_per_uphill_grade_pct_m=20.0,
        penalty_steep_downhill_pct_m=15.0,
        uncertainty_missing_elevation_m=15.0,
        uncertainty_missing_crossing_kerb_m=uncertainty_kerb,
        uncertainty_missing_surface_m=uncertainty_surface,
        uncertainty_missing_incline_m=15.0,
        uncertainty_missing_width_m=uncertainty_width,
        uncertainty_general_missing_field_m=5.0,
        distance_weight=1.0,
        accessibility_weight=1.2,
        uncertainty_weight=unc_weight,
    )


# Convenient alias
compile_preferences = compile_preferences_to_policy

