"""Deterministic turn-by-turn guidance generator for AccessRoute AI.

Derives human-readable, factual navigation instructions and accessibility cues
directly from OSM pedestrian network topology, edge geometries, and normalized findings.
Does NOT rely on external LLMs or black-box navigation services.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx
from shapely.geometry import LineString

from accessroute.scoring.models import FindingType


@dataclass
class DirectionStep:
    """Individual turn-by-turn navigation maneuver step."""

    step_index: int
    instruction: str
    maneuver: str  # "depart", "straight", "slight_left", "left", "sharp_left", "slight_right", "right", "sharp_right", "cross", "arrive"
    street_name: str
    distance_m: float
    cumulative_distance_m: float
    latitude: float
    longitude: float
    accessibility_cues: List[str] = field(default_factory=list)
    barrier_warnings: List[str] = field(default_factory=list)


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate forward azimuth in degrees [0, 360) from point 1 to point 2."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    diff_lon_rad = math.radians(lon2 - lon1)

    x = math.sin(diff_lon_rad) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(diff_lon_rad)

    bearing_deg = math.degrees(math.atan2(x, y))
    return (bearing_deg + 360.0) % 360.0


def calculate_turn_angle(bearing_in: float, bearing_out: float) -> float:
    """Calculate relative turn angle in degrees [-180, 180) from entry to exit bearing.

    Positive = right turn, Negative = left turn.
    """
    diff = bearing_out - bearing_in
    return (diff + 180.0) % 360.0 - 180.0


def classify_maneuver(turn_angle_deg: float, is_crossing: bool = False) -> str:
    """Classify relative turn angle into standard pedestrian maneuvers."""
    if is_crossing:
        return "cross"

    abs_angle = abs(turn_angle_deg)
    if abs_angle <= 20.0:
        return "straight"
    if turn_angle_deg > 0:
        if turn_angle_deg <= 45.0:
            return "slight_right"
        if turn_angle_deg <= 135.0:
            return "right"
        return "sharp_right"
    else:
        if turn_angle_deg >= -45.0:
            return "slight_left"
        if turn_angle_deg >= -135.0:
            return "left"
        return "sharp_left"


def get_bearing_cardinal(bearing_deg: float) -> str:
    """Convert bearing degrees into 8-point compass cardinal direction."""
    points = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    idx = round(bearing_deg / 45.0) % 8
    return points[idx]


def extract_street_name(edge_data: Dict[str, Any]) -> str:
    """Extract or infer a clear, human-understandable name for a pedestrian path segment."""
    raw_name = edge_data.get("name")
    if raw_name:
        if isinstance(raw_name, list) and raw_name:
            return str(raw_name[0]).strip()
        return str(raw_name).strip()

    highway = str(edge_data.get("highway", "")).lower()
    is_crossing = bool(edge_data.get("is_crossing", False)) or highway == "crossing"

    if is_crossing:
        return "Pedestrian crossing"
    if "step" in highway:
        return "Stairway"
    if highway in ("footway", "path", "pedestrian"):
        footway = str(edge_data.get("footway", "")).lower()
        if footway == "crossing":
            return "Pedestrian crossing"
        if footway == "sidewalk":
            return "Sidewalk / Footpath"
        return "Footpath"
    if highway == "cycleway":
        return "Shared pedestrian & cycle path"
    if highway in ("living_street", "residential"):
        return "Pedestrian-shared roadway"

    return "Footpath"


def extract_edge_accessibility_cues(edge_data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Extract factual accessibility cues and warnings from normalized edge attributes."""
    cues: List[str] = []
    warnings: List[str] = []

    # 1. Surface Evidence
    surface = str(edge_data.get("surface", "unknown")).lower()
    if surface in ("asphalt", "concrete", "paved", "concrete:plates", "paving_stones"):
        cues.append(f"Recorded paved surface ({surface})")
    elif surface in ("gravel", "fine_gravel", "ground", "dirt", "grass", "compacted"):
        warnings.append(f"Recorded unpaved surface ({surface})")
    elif surface == "unknown":
        cues.append("Surface material unrecorded")

    # 2. Kerb Ramp Evidence (especially at crossings)
    is_crossing = bool(edge_data.get("is_crossing", False))
    kerb = str(edge_data.get("kerb", "unknown")).lower()
    if is_crossing:
        if kerb in ("lowered", "flush"):
            cues.append("Lowered/flush kerb recorded at crossing")
        elif kerb == "raised":
            warnings.append("Raised kerb recorded at crossing")
        elif kerb == "unknown":
            warnings.append("Kerb ramp status unrecorded at crossing")

    # 3. Stairs & Ramps
    highway = str(edge_data.get("highway", "")).lower()
    has_ramp = bool(edge_data.get("has_ramp", False) or edge_data.get("has_wheelchair_ramp", False))
    if "step" in highway:
        if has_ramp:
            cues.append("Stairs with ramp facility recorded")
        else:
            warnings.append("Mapped stairs without ramp facility")

    # 4. Slope / Grade
    abs_grade = edge_data.get("absolute_grade")
    slope_direction = str(edge_data.get("slope_direction", "")).lower()
    if abs_grade is not None:
        grade_pct = abs_grade * 100.0
        if grade_pct >= 6.0 and slope_direction == "uphill":
            warnings.append(f"Estimated steep uphill grade: {grade_pct:.1f}%")
        elif grade_pct >= 4.0 and slope_direction == "uphill":
            cues.append(f"Estimated moderate uphill grade: {grade_pct:.1f}%")
        elif grade_pct >= 8.0 and slope_direction == "downhill":
            warnings.append(f"Estimated steep downhill grade: {grade_pct:.1f}%")

    return cues, warnings


def generate_turn_by_turn_directions(
    nodes: List[int],
    edges: List[Dict[str, Any]],
    geometries: Optional[List[Any]] = None,
    graph: Optional[nx.MultiDiGraph] = None,
) -> List[DirectionStep]:
    """Generate deterministic, step-by-step turn instructions along an accessible route.

    Args:
        nodes: Sequence of node IDs in traversal order.
        edges: Edge attribute dictionaries for each step.
        geometries: Optional sequence of Shapely LineStrings corresponding to each edge.
        graph: Optional NetworkX graph to look up node coordinates if geometries are absent.

    Returns:
        List of DirectionStep instances.
    """
    if not edges or len(nodes) < 2:
        return []

    # Helper to resolve coordinates for each edge
    def get_edge_endpoints(idx: int) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        geom = geometries[idx] if geometries and idx < len(geometries) else edges[idx].get("geometry")
        if geom is not None and hasattr(geom, "coords") and len(geom.coords) >= 2:
            start_coord = (float(geom.coords[0][1]), float(geom.coords[0][0]))
            end_coord = (float(geom.coords[-1][1]), float(geom.coords[-1][0]))
            return start_coord, end_coord
        u = nodes[idx]
        v = nodes[idx + 1]
        if graph is not None and u in graph and v in graph:
            u_lat = float(graph.nodes[u]["y"])
            u_lon = float(graph.nodes[u]["x"])
            v_lat = float(graph.nodes[v]["y"])
            v_lon = float(graph.nodes[v]["x"])
            return (u_lat, u_lon), (v_lat, v_lon)
        return (0.0, 0.0), (0.0, 0.0)

    # 1. Calculate edge bearings and lengths
    edge_metrics: List[Dict[str, Any]] = []
    for idx, edge_data in enumerate(edges):
        start_pt, end_pt = get_edge_endpoints(idx)
        length_m = float(edge_data.get("length", 0.0))
        bearing = calculate_bearing(start_pt[0], start_pt[1], end_pt[0], end_pt[1])
        street_name = extract_street_name(edge_data)
        is_crossing = bool(edge_data.get("is_crossing", False)) or "crossing" in street_name.lower()
        cues, warnings = extract_edge_accessibility_cues(edge_data)

        edge_metrics.append({
            "index": idx,
            "start_pt": start_pt,
            "end_pt": end_pt,
            "length_m": length_m,
            "bearing": bearing,
            "street_name": street_name,
            "is_crossing": is_crossing,
            "cues": cues,
            "warnings": warnings,
        })

    # 2. Synthesize guidance steps by grouping or detecting significant maneuvers
    steps: List[DirectionStep] = []
    cumulative_dist = 0.0

    # Step 0: Departure
    first_edge = edge_metrics[0]
    first_cardinal = get_bearing_cardinal(first_edge["bearing"])
    depart_inst = f"Head {first_cardinal} on {first_edge['street_name']}"
    if first_edge["is_crossing"]:
        depart_inst = f"Cross at pedestrian crossing heading {first_cardinal}"

    current_street = first_edge["street_name"]
    current_maneuver = "cross" if first_edge["is_crossing"] else "depart"
    current_dist = first_edge["length_m"]
    step_start_pt = first_edge["start_pt"]
    step_cues = list(first_edge["cues"])
    step_warnings = list(first_edge["warnings"])

    for i in range(1, len(edge_metrics)):
        prev_edge = edge_metrics[i - 1]
        curr_edge = edge_metrics[i]
        turn_angle = calculate_turn_angle(prev_edge["bearing"], curr_edge["bearing"])
        maneuver = classify_maneuver(turn_angle, is_crossing=curr_edge["is_crossing"])

        # Decide whether to start a new step:
        # A new step is created if:
        # - The street name changes meaningfully
        # - A road crossing begins or ends
        # - A significant turn occurs (|turn_angle| > 35 degrees)
        street_changed = curr_edge["street_name"].lower() != current_street.lower()
        is_significant_turn = abs(turn_angle) > 35.0 or curr_edge["is_crossing"] or prev_edge["is_crossing"]

        if street_changed or is_significant_turn:
            # Emit completed step
            instruction = _format_instruction(current_maneuver, current_street, current_dist)
            steps.append(DirectionStep(
                step_index=len(steps) + 1,
                instruction=instruction,
                maneuver=current_maneuver,
                street_name=current_street,
                distance_m=round(current_dist, 1),
                cumulative_distance_m=round(cumulative_dist, 1),
                latitude=round(step_start_pt[0], 6),
                longitude=round(step_start_pt[1], 6),
                accessibility_cues=list(dict.fromkeys(step_cues))[:3],  # deduplicate preserving order
                barrier_warnings=list(dict.fromkeys(step_warnings))[:3],
            ))

            cumulative_dist += current_dist
            current_street = curr_edge["street_name"]
            current_maneuver = maneuver
            current_dist = curr_edge["length_m"]
            step_start_pt = curr_edge["start_pt"]
            step_cues = list(curr_edge["cues"])
            step_warnings = list(curr_edge["warnings"])
        else:
            # Continue along same path
            current_dist += curr_edge["length_m"]
            step_cues.extend(curr_edge["cues"])
            step_warnings.extend(curr_edge["warnings"])

    # Emit the last accumulated in-progress step
    instruction = _format_instruction(current_maneuver, current_street, current_dist)
    steps.append(DirectionStep(
        step_index=len(steps) + 1,
        instruction=instruction,
        maneuver=current_maneuver,
        street_name=current_street,
        distance_m=round(current_dist, 1),
        cumulative_distance_m=round(cumulative_dist, 1),
        latitude=round(step_start_pt[0], 6),
        longitude=round(step_start_pt[1], 6),
        accessibility_cues=list(dict.fromkeys(step_cues))[:3],
        barrier_warnings=list(dict.fromkeys(step_warnings))[:3],
    ))
    cumulative_dist += current_dist

    # Final Arrival Step
    last_pt = edge_metrics[-1]["end_pt"]
    steps.append(DirectionStep(
        step_index=len(steps) + 1,
        instruction="Arrive at destination",
        maneuver="arrive",
        street_name="Destination",
        distance_m=0.0,
        cumulative_distance_m=round(cumulative_dist, 1),
        latitude=round(last_pt[0], 6),
        longitude=round(last_pt[1], 6),
        accessibility_cues=["Route goal reached"],
        barrier_warnings=[],
    ))

    return steps


def _format_instruction(maneuver: str, street_name: str, distance_m: float) -> str:
    """Format an English navigation sentence for a maneuver and street name."""
    dist_str = f"{distance_m:.0f} m" if distance_m < 1000 else f"{distance_m / 1000.0:.2f} km"

    if maneuver == "depart":
        return f"Continue on {street_name} — {dist_str}"
    if maneuver == "cross":
        return f"Cross at pedestrian crossing — {dist_str}"
    if maneuver == "straight":
        return f"Continue straight onto {street_name} — {dist_str}"
    if maneuver == "slight_right":
        return f"Turn slightly right onto {street_name} — {dist_str}"
    if maneuver == "right":
        return f"Turn right onto {street_name} — {dist_str}"
    if maneuver == "sharp_right":
        return f"Turn sharply right onto {street_name} — {dist_str}"
    if maneuver == "slight_left":
        return f"Turn slightly left onto {street_name} — {dist_str}"
    if maneuver == "left":
        return f"Turn left onto {street_name} — {dist_str}"
    if maneuver == "sharp_left":
        return f"Turn sharply left onto {street_name} — {dist_str}"

    return f"Proceed along {street_name} — {dist_str}"
