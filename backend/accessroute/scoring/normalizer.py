"""Normalization engine for raw OpenStreetMap accessibility attributes.

Safely parses, normalizes, and validates messy, sparse, and ambiguous real-world
OpenStreetMap tags into typed domain models and deterministic findings.

Critical Principles:
1. Unknown/missing data remains UNKNOWN. Missing is never defaulted to accessible or inaccessible.
2. surface=asphalt/paved/concrete NEVER implies wheelchair-accessible.
3. No arbitrary numerical scores or routing penalties are produced here.
4. Parsing failures never crash the system; unfamiliar values are categorized as OTHER while preserving raw input.
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from accessroute.scoring.models import (
    BarrierType,
    EdgeAccessibilityEvidence,
    FindingType,
    InclineMeasurement,
    KerbType,
    NodeAccessibilityEvidence,
    SmoothnessType,
    SurfaceType,
    TactilePaving,
    WheelchairAccess,
    WidthMeasurement,
)


def _extract_scalar_string(value: Any) -> Optional[str]:
    """Extract a cleaned, lowercase scalar string from messy OSM values.

    Handles:
    - None / NaN / Empty
    - Lists e.g. ['footway', 'path'] -> picks first non-empty element
    - Semicolon-delimited values e.g. 'asphalt;concrete' -> picks primary value
    - Stringified python lists e.g. "['footway', 'crossing']" (from GraphML exports)
    - Numbers, booleans
    """
    if value is None:
        return None

    # Handle native Python lists or tuples
    if isinstance(value, (list, tuple)):
        for item in value:
            clean = _extract_scalar_string(item)
            if clean:
                return clean
        return None

    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "null", ""):
        return None

    # Handle stringified list representation from GraphML
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, (list, tuple)):
                return _extract_scalar_string(parsed)
        except Exception:
            pass  # Fall back to stripping brackets
        text = text.strip("[]'\" ")

    # Handle semicolon-delimited values: 'flush;lowered' -> 'flush'
    if ";" in text:
        text = text.split(";")[0].strip()

    return text.lower() if text else None


def normalize_wheelchair(raw_value: Any) -> WheelchairAccess:
    """Normalize raw 'wheelchair' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return WheelchairAccess.UNKNOWN

    mapping = {
        "yes": WheelchairAccess.YES,
        "designated": WheelchairAccess.DESIGNATED,
        "limited": WheelchairAccess.LIMITED,
        "no": WheelchairAccess.NO,
        "unknown": WheelchairAccess.UNKNOWN,
    }
    return mapping.get(val, WheelchairAccess.OTHER)


def normalize_surface(raw_value: Any) -> SurfaceType:
    """Normalize raw 'surface' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return SurfaceType.UNKNOWN

    mapping = {
        "asphalt": SurfaceType.ASPHALT,
        "paved": SurfaceType.PAVED,
        "concrete": SurfaceType.CONCRETE,
        "concrete:plates": SurfaceType.CONCRETE_PLATES,
        "concrete_plates": SurfaceType.CONCRETE_PLATES,
        "paving_stones": SurfaceType.PAVING_STONES,
        "compacted": SurfaceType.COMPACTED,
        "fine_gravel": SurfaceType.FINE_GRAVEL,
        "gravel": SurfaceType.GRAVEL,
        "ground": SurfaceType.GROUND,
        "dirt": SurfaceType.DIRT,
        "grass": SurfaceType.GRASS,
        "cobblestone": SurfaceType.COBBLESTONE,
        "sett": SurfaceType.COBBLESTONE,
        "unpaved": SurfaceType.GROUND,
    }
    return mapping.get(val, SurfaceType.OTHER)


def normalize_kerb(raw_value: Any) -> KerbType:
    """Normalize raw 'kerb' or 'curb' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return KerbType.UNKNOWN

    mapping = {
        "flush": KerbType.FLUSH,
        "lowered": KerbType.LOWERED,
        "rolled": KerbType.ROLLED,
        "raised": KerbType.RAISED,
        "no": KerbType.NO,
        "none": KerbType.NO,
        "unknown": KerbType.UNKNOWN,
    }
    return mapping.get(val, KerbType.OTHER)


def normalize_smoothness(raw_value: Any) -> SmoothnessType:
    """Normalize raw 'smoothness' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return SmoothnessType.UNKNOWN

    mapping = {
        "excellent": SmoothnessType.EXCELLENT,
        "good": SmoothnessType.GOOD,
        "intermediate": SmoothnessType.INTERMEDIATE,
        "bad": SmoothnessType.BAD,
        "very_bad": SmoothnessType.VERY_BAD,
        "horrible": SmoothnessType.HORRIBLE,
        "very_horrible": SmoothnessType.VERY_HORRIBLE,
        "impassable": SmoothnessType.IMPASSABLE,
        "unknown": SmoothnessType.UNKNOWN,
    }
    return mapping.get(val, SmoothnessType.OTHER)


def normalize_tactile_paving(raw_value: Any) -> TactilePaving:
    """Normalize raw 'tactile_paving' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return TactilePaving.UNKNOWN

    mapping = {
        "yes": TactilePaving.YES,
        "no": TactilePaving.NO,
        "incorrect": TactilePaving.INCORRECT,
        "primitive": TactilePaving.PRIMITIVE,
        "unknown": TactilePaving.UNKNOWN,
    }
    return mapping.get(val, TactilePaving.OTHER)


def normalize_barrier(raw_value: Any) -> BarrierType:
    """Normalize raw 'barrier' OSM tag."""
    val = _extract_scalar_string(raw_value)
    if val is None:
        return BarrierType.NONE

    mapping = {
        "none": BarrierType.NONE,
        "no": BarrierType.NONE,
        "bollard": BarrierType.BOLLARD,
        "gate": BarrierType.GATE,
        "cycle_barrier": BarrierType.CYCLE_BARRIER,
        "turnstile": BarrierType.TURNSTILE,
        "block": BarrierType.BLOCK,
        "debris": BarrierType.DEBRIS,
        "kerb": BarrierType.KERB,
        "lift_gate": BarrierType.LIFT_GATE,
        "swing_gate": BarrierType.SWING_GATE,
        "unknown": BarrierType.UNKNOWN,
    }
    return mapping.get(val, BarrierType.OTHER)


def normalize_incline(raw_value: Any) -> InclineMeasurement:
    """Parse raw 'incline' or 'incline:direction' tags into an InclineMeasurement.

    Supports:
    - '5%' -> percentage=5.0
    - '-8%' -> percentage=-8.0
    - '12' -> percentage=12.0
    - 'up' / 'down' -> direction='up' / 'down'
    - '1:12' -> percentage=8.33
    - Ambiguous or malformed -> raw preserved, percentage=None, is_parsed=False
    """
    if raw_value is None:
        return InclineMeasurement(raw="", is_parsed=False)

    raw_str = str(raw_value).strip()
    val = _extract_scalar_string(raw_value)
    if val is None:
        return InclineMeasurement(raw=raw_str, is_parsed=False)

    # Directional semantics
    if val in ("up", "down", "steep", "gentle"):
        return InclineMeasurement(
            raw=raw_str,
            direction=val,
            is_parsed=True,
        )

    # Percentage parsing: e.g. "5%", "-8.5%", "12 %"
    pct_match = re.match(r"^([+-]?\d+(?:\.\d+)?)\s*%$", val)
    if pct_match:
        try:
            return InclineMeasurement(
                raw=raw_str,
                percentage=float(pct_match.group(1)),
                is_parsed=True,
            )
        except ValueError:
            pass

    # Ratio slope parsing: e.g. "1:12", "1/10"
    ratio_match = re.match(r"^1\s*[:/]\s*(\d+(?:\.\d+)?)$", val)
    if ratio_match:
        try:
            run = float(ratio_match.group(1))
            if run > 0:
                pct = (1.0 / run) * 100.0
                return InclineMeasurement(
                    raw=raw_str,
                    percentage=round(pct, 2),
                    is_parsed=True,
                )
        except ValueError:
            pass

    # Pure numeric representation (some mappers omit % symbol): e.g. "5", "-8"
    num_match = re.match(r"^([+-]?\d+(?:\.\d+)?)$", val)
    if num_match:
        try:
            num = float(num_match.group(1))
            # Sensible pedestrian slope guard: -50% to +50%
            if -50.0 <= num <= 50.0:
                return InclineMeasurement(
                    raw=raw_str,
                    percentage=num,
                    is_parsed=True,
                )
        except ValueError:
            pass

    # Unrecognized format: preserve raw without guessing
    return InclineMeasurement(raw=raw_str, is_parsed=False)


def normalize_width(raw_value: Any) -> WidthMeasurement:
    """Parse raw 'width' or 'est_width' tags into meters.

    Supports:
    - '1.5' -> 1.5m
    - '1.5 m' / '1.5m' / '1.5 metres' -> 1.5m
    - '150 cm' / '150cm' -> 1.5m
    - Ambiguous ranges or malformed -> raw preserved, width_meters=None, is_parsed=False
    """
    if raw_value is None:
        return WidthMeasurement(raw="", is_parsed=False)

    raw_str = str(raw_value).strip()
    val = _extract_scalar_string(raw_value)
    if val is None:
        return WidthMeasurement(raw=raw_str, is_parsed=False)

    # 1. Direct meters with optional unit
    m_match = re.match(r"^(\d+(?:\.\d+)?)\s*(?:m|meter|meters|metres)?$", val)
    if m_match:
        try:
            w = float(m_match.group(1))
            if 0.1 <= w <= 50.0:
                return WidthMeasurement(raw=raw_str, width_meters=w, is_parsed=True)
        except ValueError:
            pass

    # 2. Centimeters: e.g. '150 cm', '90cm'
    cm_match = re.match(r"^(\d+(?:\.\d+)?)\s*cm$", val)
    if cm_match:
        try:
            cm = float(cm_match.group(1))
            w = cm / 100.0
            if 0.1 <= w <= 50.0:
                return WidthMeasurement(raw=raw_str, width_meters=round(w, 3), is_parsed=True)
        except ValueError:
            pass

    # Unrecognized or ambiguous width
    return WidthMeasurement(raw=raw_str, is_parsed=False)


def extract_edge_evidence(raw_edge_data: Dict[str, Any]) -> EdgeAccessibilityEvidence:
    """Extract, normalize, and deduce deterministic findings for a network edge.

    Does NOT create arbitrary scores or routing penalties.
    Missing fields are explicitly cataloged in missing_fields.
    """
    raw_tags = dict(raw_edge_data)

    # 1. Primary categorical normalization
    wheelchair = normalize_wheelchair(raw_tags.get("wheelchair"))
    surface = normalize_surface(raw_tags.get("surface"))
    kerb = normalize_kerb(raw_tags.get("kerb") or raw_tags.get("curb"))
    smoothness = normalize_smoothness(raw_tags.get("smoothness"))
    tactile_paving = normalize_tactile_paving(raw_tags.get("tactile_paving"))
    incline = normalize_incline(raw_tags.get("incline") or raw_tags.get("incline:direction"))
    width = normalize_width(raw_tags.get("width") or raw_tags.get("est_width"))

    # 2. Infrastructure type extraction
    highway_raw = _extract_scalar_string(raw_tags.get("highway")) or "unknown"
    footway_raw = _extract_scalar_string(raw_tags.get("footway"))

    # Robust detection for list or composite tags (e.g. ['footway', 'steps'])
    hw_val = raw_tags.get("highway")
    hw_tokens = set()
    if isinstance(hw_val, (list, tuple, set)):
        hw_tokens = {str(x).strip().lower() for x in hw_val if x}
    elif hw_val is not None:
        hw_str = str(hw_val).strip().lower()
        if hw_str.startswith("[") and hw_str.endswith("]"):
            import ast
            try:
                parsed = ast.literal_eval(hw_str)
                if isinstance(parsed, (list, tuple)):
                    hw_tokens = {str(x).strip().lower() for x in parsed if x}
            except Exception:
                hw_tokens = {hw_str}
        else:
            hw_tokens = {hw_str}

    is_steps = ("steps" in hw_tokens) or (highway_raw == "steps") or ("step_count" in raw_tags)
    step_count = None
    if "step_count" in raw_tags:
        try:
            step_count = int(float(str(raw_tags["step_count"])))
        except (ValueError, TypeError):
            pass

    is_crossing = (
        ("crossing" in hw_tokens)
        or (highway_raw == "crossing")
        or (footway_raw == "crossing")
        or ("crossing" in raw_tags)
    )
    crossing_signals = (
        _extract_scalar_string(raw_tags.get("crossing:signals")) == "yes"
        or _extract_scalar_string(raw_tags.get("traffic_signals")) == "yes"
    )
    crossing_markings = _extract_scalar_string(raw_tags.get("crossing:markings"))

    ramp_val = _extract_scalar_string(raw_tags.get("ramp"))
    has_ramp = ramp_val in ("yes", "separate")
    ramp_wheelchair_val = _extract_scalar_string(raw_tags.get("ramp:wheelchair"))
    has_wheelchair_ramp = ramp_wheelchair_val in ("yes", "designated")
    if has_wheelchair_ramp:
        has_ramp = True

    lit_val = _extract_scalar_string(raw_tags.get("lit"))
    is_lit = True if lit_val == "yes" else (False if lit_val == "no" else None)

    access_val = _extract_scalar_string(raw_tags.get("access")) or "yes"

    # 3. Deduce Deterministic Findings (Strictly Evidence-Backed)
    findings: Set[FindingType] = set()

    # Wheelchair findings
    if wheelchair == WheelchairAccess.NO:
        findings.add(FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED)
    elif wheelchair in (WheelchairAccess.YES, WheelchairAccess.DESIGNATED):
        findings.add(FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED)
    elif wheelchair == WheelchairAccess.LIMITED:
        findings.add(FindingType.WHEELCHAIR_ACCESS_LIMITED)

    # Steps and ramp findings
    if is_steps:
        findings.add(FindingType.STEPS_PRESENT)
    if has_ramp:
        findings.add(FindingType.RAMP_PRESENT)
    if has_wheelchair_ramp:
        findings.add(FindingType.RAMP_WHEELCHAIR_DESIGNATED)

    handrail_val = _extract_scalar_string(raw_tags.get("handrail"))
    if handrail_val in ("yes", "left", "right", "both"):
        findings.add(FindingType.HANDRAIL_PRESENT)

    # Kerb findings
    if kerb == KerbType.FLUSH:
        findings.add(FindingType.FLUSH_KERB_RECORDED)
    elif kerb == KerbType.LOWERED:
        findings.add(FindingType.LOWERED_KERB_RECORDED)
    elif kerb == KerbType.RAISED:
        findings.add(FindingType.RAISED_KERB_RECORDED)
    elif kerb == KerbType.ROLLED:
        findings.add(FindingType.ROLLED_KERB_RECORDED)

    # Surface findings (CRITICAL: Paved does NOT imply wheelchair accessible)
    if surface in (
        SurfaceType.ASPHALT,
        SurfaceType.PAVED,
        SurfaceType.CONCRETE,
        SurfaceType.CONCRETE_PLATES,
        SurfaceType.PAVING_STONES,
    ):
        findings.add(FindingType.PAVED_SURFACE_RECORDED)
    elif surface in (
        SurfaceType.GRAVEL,
        SurfaceType.FINE_GRAVEL,
        SurfaceType.GROUND,
        SurfaceType.DIRT,
        SurfaceType.GRASS,
        SurfaceType.COMPACTED,
    ):
        findings.add(FindingType.UNPAVED_SURFACE_RECORDED)

    if surface == SurfaceType.COBBLESTONE or smoothness in (
        SmoothnessType.BAD,
        SmoothnessType.VERY_BAD,
        SmoothnessType.HORRIBLE,
        SmoothnessType.VERY_HORRIBLE,
        SmoothnessType.IMPASSABLE,
    ):
        findings.add(FindingType.ROUGH_SURFACE_RECORDED)

    # Crossing findings
    if is_crossing:
        findings.add(FindingType.PEDESTRIAN_CROSSING_RECORDED)
    if crossing_signals:
        findings.add(FindingType.SIGNALIZED_CROSSING_RECORDED)
    if crossing_markings and crossing_markings != "no":
        findings.add(FindingType.MARKED_CROSSING_RECORDED)

    # Tactile paving & lighting
    if tactile_paving == TactilePaving.YES:
        findings.add(FindingType.TACTILE_PAVING_RECORDED)
    if is_lit is True:
        findings.add(FindingType.LIT_AT_NIGHT)

    # Incline steepness
    if (incline.percentage is not None and abs(incline.percentage) >= 8.0) or incline.direction == "steep":
        findings.add(FindingType.STEEP_INCLINE_RECORDED)

    # Access constraints
    if access_val in ("private", "no"):
        findings.add(FindingType.RESTRICTED_ACCESS_RECORDED)

    # 4. Catalog Missing Fields Explicitly
    missing: List[str] = []
    if wheelchair == WheelchairAccess.UNKNOWN:
        missing.append("wheelchair")
    if surface == SurfaceType.UNKNOWN:
        missing.append("surface")
    if kerb == KerbType.UNKNOWN:
        missing.append("kerb")
    if smoothness == SmoothnessType.UNKNOWN:
        missing.append("smoothness")
    if tactile_paving == TactilePaving.UNKNOWN:
        missing.append("tactile_paving")
    if not incline.is_known:
        missing.append("incline")
    if not width.is_known:
        missing.append("width")
    if is_lit is None:
        missing.append("lit")

    return EdgeAccessibilityEvidence(
        wheelchair=wheelchair,
        surface=surface,
        kerb=kerb,
        smoothness=smoothness,
        tactile_paving=tactile_paving,
        incline=incline,
        width=width,
        highway_type=highway_raw,
        footway_type=footway_raw,
        is_crossing=is_crossing,
        crossing_signals=crossing_signals,
        crossing_markings=crossing_markings,
        is_steps=is_steps,
        step_count=step_count,
        has_ramp=has_ramp,
        has_wheelchair_ramp=has_wheelchair_ramp,
        is_lit=is_lit,
        access=access_val,
        findings=findings,
        missing_fields=missing,
        raw_tags=raw_tags,
    )


def extract_node_evidence(node_id: int, raw_node_data: Dict[str, Any]) -> NodeAccessibilityEvidence:
    """Extract, normalize, and deduce deterministic findings for a network node (point).

    Nodes often host kerb ramps, tactile paving, crossing points, or physical barriers.
    """
    raw_tags = dict(raw_node_data)
    lat = float(raw_tags.get("y", 0.0))
    lon = float(raw_tags.get("x", 0.0))

    kerb = normalize_kerb(raw_tags.get("kerb") or raw_tags.get("curb"))
    tactile_paving = normalize_tactile_paving(raw_tags.get("tactile_paving"))
    barrier = normalize_barrier(raw_tags.get("barrier"))
    wheelchair = normalize_wheelchair(raw_tags.get("wheelchair"))

    highway_val = _extract_scalar_string(raw_tags.get("highway"))
    crossing_val = _extract_scalar_string(raw_tags.get("crossing"))
    is_crossing = highway_val == "crossing" or crossing_val is not None
    has_traffic_signals = highway_val == "traffic_signals" or _extract_scalar_string(raw_tags.get("traffic_signals")) == "yes"

    findings: Set[FindingType] = set()

    # Wheelchair findings
    if wheelchair == WheelchairAccess.NO:
        findings.add(FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_PROHIBITED)
    elif wheelchair in (WheelchairAccess.YES, WheelchairAccess.DESIGNATED):
        findings.add(FindingType.WHEELCHAIR_ACCESS_EXPLICITLY_ALLOWED)

    # Kerb findings on node
    if kerb == KerbType.FLUSH:
        findings.add(FindingType.FLUSH_KERB_RECORDED)
    elif kerb == KerbType.LOWERED:
        findings.add(FindingType.LOWERED_KERB_RECORDED)
    elif kerb == KerbType.RAISED:
        findings.add(FindingType.RAISED_KERB_RECORDED)
    elif kerb == KerbType.ROLLED:
        findings.add(FindingType.ROLLED_KERB_RECORDED)

    # Tactile paving
    if tactile_paving == TactilePaving.YES:
        findings.add(FindingType.TACTILE_PAVING_RECORDED)

    # Crossing findings
    if is_crossing:
        findings.add(FindingType.PEDESTRIAN_CROSSING_RECORDED)
    if has_traffic_signals:
        findings.add(FindingType.SIGNALIZED_CROSSING_RECORDED)

    # Barrier findings
    if barrier in (BarrierType.TURNSTILE, BarrierType.CYCLE_BARRIER):
        findings.add(FindingType.RESTRICTIVE_BARRIER_RECORDED)
    elif barrier in (BarrierType.BOLLARD, BarrierType.GATE, BarrierType.LIFT_GATE, BarrierType.SWING_GATE):
        findings.add(FindingType.PASSABLE_BARRIER_RECORDED)

    # Missing fields catalog
    missing: List[str] = []
    if kerb == KerbType.UNKNOWN:
        missing.append("kerb")
    if tactile_paving == TactilePaving.UNKNOWN:
        missing.append("tactile_paving")
    if wheelchair == WheelchairAccess.UNKNOWN:
        missing.append("wheelchair")

    return NodeAccessibilityEvidence(
        node_id=node_id,
        latitude=lat,
        longitude=lon,
        kerb=kerb,
        tactile_paving=tactile_paving,
        barrier=barrier,
        wheelchair=wheelchair,
        is_crossing=is_crossing,
        has_traffic_signals=has_traffic_signals,
        findings=findings,
        missing_fields=missing,
        raw_tags=raw_tags,
    )
