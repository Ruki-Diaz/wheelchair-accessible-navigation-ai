"""Deterministic conflict detection between OpenStreetMap evidence and Community observations.

Stage 9 Architecture:
Maintains explicit provenance without silently overwriting either source.
When OpenStreetMap and Community observations disagree, the system surfaces both:
'OpenStreetMap reports X. Community observation reports Y. These sources disagree.'
"""

from typing import Any, Dict, List, Optional
from accessroute.community.models import CommunityObservation, EvidenceConflict, ObservationCategory, VerificationStatus
from accessroute.scoring.models import EdgeAccessibilityEvidence, FindingType, KerbType, NodeAccessibilityEvidence, SurfaceType


class EvidenceConflictDetector:
    """Detects factual disagreements between OpenStreetMap normalized tags and community observations."""

    @staticmethod
    def detect_conflicts(
        osm_edge_evidence: Optional[EdgeAccessibilityEvidence],
        osm_node_evidence: Optional[NodeAccessibilityEvidence],
        community_observations: List[CommunityObservation],
    ) -> List[EvidenceConflict]:
        """Compare OSM evidence with active community observations on the same element.

        Args:
            osm_edge_evidence: Normalized evidence for the traversing way.
            osm_node_evidence: Optional normalized evidence for the node.
            community_observations: Active community observations matched to this way/node.

        Returns:
            List of detected EvidenceConflict instances.
        """
        conflicts: List[EvidenceConflict] = []
        if not community_observations:
            return conflicts

        for obs in community_observations:
            if not obs.is_active():
                continue

            # 1. Kerb Conflicts
            if obs.category == ObservationCategory.KERB:
                osm_kerb = KerbType.UNKNOWN
                if osm_edge_evidence and osm_edge_evidence.kerb != KerbType.UNKNOWN:
                    osm_kerb = osm_edge_evidence.kerb
                elif osm_node_evidence and osm_node_evidence.kerb != KerbType.UNKNOWN:
                    osm_kerb = osm_node_evidence.kerb

                if osm_kerb != KerbType.UNKNOWN:
                    # Check for direct contradiction
                    osm_is_accessible = osm_kerb in (KerbType.LOWERED, KerbType.FLUSH)
                    comm_is_raised = obs.value in ("raised", "no_kerb")
                    osm_is_raised = osm_kerb == KerbType.RAISED
                    comm_is_lowered = obs.value in ("lowered", "flush")

                    if osm_is_accessible and comm_is_raised:
                        conflicts.append(
                            EvidenceConflict(
                                osm_element_type=obs.osm_element_type or "crossing",
                                osm_element_id=obs.osm_element_id or 0,
                                latitude=obs.latitude,
                                longitude=obs.longitude,
                                attribute_name="kerb",
                                osm_claim=f"OpenStreetMap records kerb={osm_kerb.value}",
                                community_claim=f"Community reports kerb={obs.value}",
                                conflict_summary=f"OSM records a {osm_kerb.value} kerb, but community report indicates a {obs.value} kerb.",
                                community_observation_id=obs.id,
                                verification_status=obs.verification_status,
                            )
                        )
                    elif osm_is_raised and comm_is_lowered:
                        conflicts.append(
                            EvidenceConflict(
                                osm_element_type=obs.osm_element_type or "crossing",
                                osm_element_id=obs.osm_element_id or 0,
                                latitude=obs.latitude,
                                longitude=obs.longitude,
                                attribute_name="kerb",
                                osm_claim="OpenStreetMap records kerb=raised",
                                community_claim=f"Community reports kerb={obs.value}",
                                conflict_summary=f"OSM records a raised kerb, but community report indicates a {obs.value} transition.",
                                community_observation_id=obs.id,
                                verification_status=obs.verification_status,
                            )
                        )

            # 2. Surface Conflicts
            elif obs.category == ObservationCategory.SURFACE and osm_edge_evidence:
                osm_surf = osm_edge_evidence.surface
                if osm_surf != SurfaceType.UNKNOWN:
                    osm_is_paved = osm_surf in (
                        SurfaceType.ASPHALT,
                        SurfaceType.PAVED,
                        SurfaceType.CONCRETE,
                        SurfaceType.CONCRETE_PLATES,
                        SurfaceType.PAVING_STONES,
                    )
                    comm_is_unpaved = obs.value in ("gravel", "dirt", "ground", "grass", "cobblestone")

                    osm_is_unpaved = osm_surf in (
                        SurfaceType.GRAVEL,
                        SurfaceType.FINE_GRAVEL,
                        SurfaceType.DIRT,
                        SurfaceType.GROUND,
                        SurfaceType.GRASS,
                    )
                    comm_is_paved = obs.value in ("asphalt", "concrete", "paved")

                    if osm_is_paved and comm_is_unpaved:
                        conflicts.append(
                            EvidenceConflict(
                                osm_element_type=obs.osm_element_type or "way",
                                osm_element_id=obs.osm_element_id or 0,
                                latitude=obs.latitude,
                                longitude=obs.longitude,
                                attribute_name="surface",
                                osm_claim=f"OpenStreetMap records surface={osm_surf.value}",
                                community_claim=f"Community reports surface={obs.value}",
                                conflict_summary=f"OSM records paved ({osm_surf.value}), but community report indicates unpaved ({obs.value}).",
                                community_observation_id=obs.id,
                                verification_status=obs.verification_status,
                            )
                        )
                    elif osm_is_unpaved and comm_is_paved:
                        conflicts.append(
                            EvidenceConflict(
                                osm_element_type=obs.osm_element_type or "way",
                                osm_element_id=obs.osm_element_id or 0,
                                latitude=obs.latitude,
                                longitude=obs.longitude,
                                attribute_name="surface",
                                osm_claim=f"OpenStreetMap records surface={osm_surf.value}",
                                community_claim=f"Community reports surface={obs.value}",
                                conflict_summary=f"OSM records unpaved ({osm_surf.value}), but community report indicates paved ({obs.value}).",
                                community_observation_id=obs.id,
                                verification_status=obs.verification_status,
                            )
                        )

            # 3. Stairs Conflicts
            elif obs.category == ObservationCategory.STAIRS and osm_edge_evidence:
                osm_has_steps = osm_edge_evidence.is_steps
                comm_has_steps = obs.value in ("present", "steep_flight")
                comm_no_steps = obs.value == "absent"

                if not osm_has_steps and comm_has_steps:
                    conflicts.append(
                        EvidenceConflict(
                            osm_element_type=obs.osm_element_type or "way",
                            osm_element_id=obs.osm_element_id or 0,
                            latitude=obs.latitude,
                            longitude=obs.longitude,
                            attribute_name="stairs",
                            osm_claim="OpenStreetMap shows step-free pathway",
                            community_claim="Community reports stairs present",
                            conflict_summary="OSM shows standard footpath without steps, but community reports mapped stairs.",
                            community_observation_id=obs.id,
                            verification_status=obs.verification_status,
                        )
                    )
                elif osm_has_steps and comm_no_steps:
                    conflicts.append(
                        EvidenceConflict(
                            osm_element_type=obs.osm_element_type or "way",
                            osm_element_id=obs.osm_element_id or 0,
                            latitude=obs.latitude,
                            longitude=obs.longitude,
                            attribute_name="stairs",
                            osm_claim="OpenStreetMap records highway=steps",
                            community_claim="Community reports no stairs (ramp or level path)",
                            conflict_summary="OSM records stairs, but community report indicates no stairs.",
                            community_observation_id=obs.id,
                            verification_status=obs.verification_status,
                        )
                    )

            # 4. Path Blocked / Obstruction vs Walkable Highway
            elif obs.category in (ObservationCategory.PATH_BLOCKED, ObservationCategory.CONSTRUCTION) and osm_edge_evidence:
                conflicts.append(
                    EvidenceConflict(
                        osm_element_type=obs.osm_element_type or "way",
                        osm_element_id=obs.osm_element_id or 0,
                        latitude=obs.latitude,
                        longitude=obs.longitude,
                        attribute_name="passability",
                        osm_claim=f"OpenStreetMap records walkable highway={getattr(osm_edge_evidence, 'highway_type', getattr(osm_edge_evidence, 'highway', 'path'))}",
                        community_claim=f"Community reports path blocked ({obs.value})",
                        conflict_summary=f"OSM records walkable path, but community report flags obstruction ({obs.value}).",
                        community_observation_id=obs.id,
                        verification_status=obs.verification_status,
                    )
                )

        return conflicts
