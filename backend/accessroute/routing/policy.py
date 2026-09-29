"""Configurable routing policies and development penalty parameters.

IMPORTANT DISCLAIMER:
The penalty weights and parameter defaults in this module are PROVISIONAL DEVELOPMENT
PARAMETERS for algorithmic evaluation, sensitivity testing, and system design.
They do NOT represent universal medical thresholds or clinical standards for all wheelchair users.
Mobility capabilities vary widely between individuals, device types, and environments.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set


class PolicyName(str, Enum):
    """Identifies standard development routing policies."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    DISTANCE_FIRST = "distance_first"
    CUSTOM = "custom"


@dataclass(frozen=True)
class RoutingPolicy:
    """Configurable routing policy governing hard prohibitions, soft penalties, and uncertainty.

    All penalty values represent 'virtual meters' of equivalent traversal resistance
    added to the actual physical distance in meters during pathfinding.
    """
    name: str = "custom"
    description: str = "Custom accessibility routing policy"

    # --- 1. Hard Prohibitions (Unusable Edges / Nodes) ---
    prohibit_steps_without_ramp: bool = True
    prohibit_wheelchair_no: bool = True
    prohibit_known_restrictive_barriers: bool = True  # e.g., turnstiles, narrow cycle barriers
    prohibit_unpaved_surfaces: bool = False  # If True, gravel/dirt are strictly blocked
    prohibit_below_min_width: bool = False  # If True, ways narrower than minimum_path_width_m are blocked
    prohibit_unknown_kerb_crossings: bool = False  # If True, crossings with unknown kerb status are blocked
    minimum_path_width_m: Optional[float] = None  # User-configured minimum width in meters
    max_tolerable_incline_pct: Optional[float] = 12.0  # None = no hard limit; slopes exceeding this are blocked

    # --- 2. Soft Accessibility Penalties (Provisional Virtual Meters) ---
    # Step penalties when stairs are not hard-prohibited
    penalty_steps_without_ramp_m: float = 0.0    # Virtual meters added per unramped stair edge when allow/prefer_avoid is set
    penalty_below_min_width_m: float = 0.0       # Virtual meters added if recorded width is narrower than preferred

    # Surface traversal resistance penalties
    penalty_unpaved_surface_m: float = 120.0     # Virtual meters added per unpaved edge (gravel, dirt)
    penalty_rough_surface_m: float = 80.0        # Virtual meters added for cobblestone / bad smoothness
    penalty_grass_surface_m: float = 200.0       # Virtual meters added for grass tracks

    # Kerb traversal penalties
    penalty_raised_kerb_m: float = 150.0         # Virtual meters for traversing a recorded raised kerb
    penalty_rolled_kerb_m: float = 25.0          # Virtual meters for a rolled/mountable kerb
    preference_lowered_kerb_m: float = 0.0       # Baseline neutral for ramped kerb cuts
    preference_flush_kerb_m: float = 0.0         # Baseline neutral for flush transitions

    # Incline penalties
    penalty_per_incline_pct_m: float = 15.0      # Virtual meters per 1% grade slope above baseline

    # Crossing penalties
    penalty_uncontrolled_crossing_m: float = 20.0 # Caution factor for crossing roadways without signals

    # Barrier penalties (for passable barriers like gates or bollards)
    penalty_passable_barrier_m: float = 30.0     # Virtual meters for opening a gate or navigating bollard spacing

    # --- 3. Terrain & Slope Parameters (Provisional Virtual Meters) ---
    terrain_weight: float = 1.0                  # Multiplier for directional terrain traversal cost
    prohibit_steep_incline: bool = False         # If True, hard prunes edges with uphill grade > max_permitted_uphill_grade_pct
    max_permitted_uphill_grade_pct: Optional[float] = 12.0  # Slope % triggering hard exclusion if prohibit_steep_incline=True
    max_preferred_uphill_grade_pct: float = 5.0  # Baseline slope threshold above which uphill grade adds virtual meters
    max_preferred_downhill_grade_pct: float = 8.0 # Steep downhill threshold above which downhill risk penalty adds virtual meters
    penalty_per_uphill_grade_pct_m: float = 20.0 # Virtual meters added per 1% uphill grade above preferred threshold (per 100m)
    penalty_steep_downhill_pct_m: float = 15.0   # Virtual meters added per 1% steep downhill grade above threshold (per 100m)
    uncertainty_missing_elevation_m: float = 15.0 # Contextual uncertainty when elevation data is unrecorded/missing

    # --- 4. Contextual Uncertainty Weights (Missing Data Handling) ---
    # Missing information is NOT treated as inaccessible or accessible;
    # instead it adds an uncertainty factor reflecting risk in that specific context.
    uncertainty_missing_crossing_kerb_m: float = 60.0  # High risk: road crossing with unknown kerb ramp status
    uncertainty_missing_surface_m: float = 20.0        # Moderate risk: footpath with unrecorded surface material
    uncertainty_missing_incline_m: float = 15.0        # Moderate risk: path in rolling topography with unknown slope
    uncertainty_missing_width_m: float = 0.0          # Risk factor when path width is unrecorded
    uncertainty_general_missing_field_m: float = 5.0   # Minor risk: generic missing tag (e.g. lighting)

    # --- 5. Multi-Objective Dimension Weights ---
    distance_weight: float = 1.0       # Weight multiplier for physical travel distance in meters
    accessibility_weight: float = 1.0  # Weight multiplier for known accessibility resistance penalties
    uncertainty_weight: float = 1.0    # Weight multiplier for missing-data uncertainty risk


# ============================================================================
# STANDARD PRE-CONFIGURED DEVELOPMENT POLICIES
# ============================================================================

CONSERVATIVE_ACCESSIBILITY_POLICY = RoutingPolicy(
    name=PolicyName.CONSERVATIVE.value,
    description=(
        "Conservative policy: Strongly avoids steps, explicit prohibitions, and rough terrain. "
        "Applies strict caution to crossings with unknown kerb ramps and prioritizes documented infrastructure."
    ),
    prohibit_steps_without_ramp=True,
    prohibit_wheelchair_no=True,
    prohibit_known_restrictive_barriers=True,
    prohibit_unpaved_surfaces=False,
    max_tolerable_incline_pct=8.0,
    penalty_unpaved_surface_m=200.0,
    penalty_rough_surface_m=120.0,
    penalty_raised_kerb_m=250.0,
    penalty_rolled_kerb_m=40.0,
    penalty_per_incline_pct_m=25.0,
    penalty_uncontrolled_crossing_m=35.0,
    penalty_passable_barrier_m=50.0,
    terrain_weight=1.5,
    prohibit_steep_incline=False,
    max_preferred_uphill_grade_pct=4.0,
    max_permitted_uphill_grade_pct=10.0,
    max_preferred_downhill_grade_pct=7.0,
    penalty_per_uphill_grade_pct_m=25.0,
    penalty_steep_downhill_pct_m=18.0,
    uncertainty_missing_elevation_m=20.0,
    uncertainty_missing_crossing_kerb_m=100.0,  # Highly cautious at unverified crossings
    uncertainty_missing_surface_m=30.0,
    uncertainty_missing_incline_m=25.0,
    uncertainty_general_missing_field_m=10.0,
    distance_weight=1.0,
    accessibility_weight=1.5,
    uncertainty_weight=1.2,
)

BALANCED_ACCESSIBILITY_POLICY = RoutingPolicy(
    name=PolicyName.BALANCED.value,
    description=(
        "Balanced policy: Strictly prohibits major confirmed barriers (stairs, wheelchair=no, turnstiles) "
        "while accepting moderate surface roughness and unverified crossings to prevent excessive detours."
    ),
    prohibit_steps_without_ramp=True,
    prohibit_wheelchair_no=True,
    prohibit_known_restrictive_barriers=True,
    prohibit_unpaved_surfaces=False,
    max_tolerable_incline_pct=12.0,
    penalty_unpaved_surface_m=100.0,
    penalty_rough_surface_m=60.0,
    penalty_raised_kerb_m=150.0,
    penalty_rolled_kerb_m=20.0,
    penalty_per_incline_pct_m=15.0,
    penalty_uncontrolled_crossing_m=15.0,
    penalty_passable_barrier_m=25.0,
    terrain_weight=1.0,
    prohibit_steep_incline=False,
    max_preferred_uphill_grade_pct=6.0,
    max_permitted_uphill_grade_pct=12.0,
    max_preferred_downhill_grade_pct=8.0,
    penalty_per_uphill_grade_pct_m=15.0,
    penalty_steep_downhill_pct_m=10.0,
    uncertainty_missing_elevation_m=10.0,
    uncertainty_missing_crossing_kerb_m=40.0,
    uncertainty_missing_surface_m=15.0,
    uncertainty_missing_incline_m=10.0,
    uncertainty_general_missing_field_m=5.0,
    distance_weight=1.0,
    accessibility_weight=1.0,
    uncertainty_weight=0.7,
)

DISTANCE_FIRST_POLICY = RoutingPolicy(
    name=PolicyName.DISTANCE_FIRST.value,
    description=(
        "Distance-first policy: Primarily minimizes physical distance while respecting explicit hard prohibitions "
        "(stairs and wheelchair=no). Ignores surface roughness and data missingness."
    ),
    prohibit_steps_without_ramp=True,
    prohibit_wheelchair_no=True,
    prohibit_known_restrictive_barriers=True,
    prohibit_unpaved_surfaces=False,
    max_tolerable_incline_pct=None,
    penalty_unpaved_surface_m=10.0,
    penalty_rough_surface_m=5.0,
    penalty_raised_kerb_m=20.0,
    penalty_rolled_kerb_m=0.0,
    penalty_per_incline_pct_m=0.0,
    penalty_uncontrolled_crossing_m=0.0,
    penalty_passable_barrier_m=0.0,
    terrain_weight=0.0,
    prohibit_steep_incline=False,
    uncertainty_missing_elevation_m=0.0,
    uncertainty_missing_crossing_kerb_m=0.0,  # Ignores missing data
    uncertainty_missing_surface_m=0.0,
    uncertainty_missing_incline_m=0.0,
    uncertainty_general_missing_field_m=0.0,
    distance_weight=1.0,
    accessibility_weight=0.2,
    uncertainty_weight=0.0,
)
