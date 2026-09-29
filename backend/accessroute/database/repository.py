"""PostgreSQL / PostGIS implementation of CommunityObservationRepository.

Provides full parity with SQLiteCommunityObservationRepository while leveraging
PostgreSQL ACID transactions and spatial indexing capabilities.
"""

from datetime import datetime, timezone
import json
import logging
import math
from typing import Any, Dict, List, Optional
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)
from accessroute.community.repository import CommunityObservationRepository
from accessroute.database.config import db_settings

logger = logging.getLogger(__name__)


class PostgresCommunityObservationRepository(CommunityObservationRepository):
    """PostgreSQL / PostGIS repository for community observations."""

    def __init__(self, connection_url_or_session: Any = None, connection_url: Optional[str] = None):
        target = connection_url if connection_url is not None else connection_url_or_session
        if isinstance(target, str):
            self.db_url = target
        elif target is not None and hasattr(target, "bind"):
            try:
                self.db_url = str(target.bind.url)
            except Exception:
                self.db_url = db_settings.database_url
        else:
            self.db_url = db_settings.database_url

        self._has_postgis: Optional[bool] = None
        self._init_db()

    def _get_connection(self):
        return psycopg2.connect(self.db_url)

    def _check_postgis(self, conn) -> bool:
        if self._has_postgis is not None:
            return self._has_postgis
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'postgis';")
                self._has_postgis = cur.fetchone() is not None
        except Exception:
            self._has_postgis = False
        return self._has_postgis

    def _init_db(self) -> None:
        """Create PostgreSQL tables and spatial indexes if they do not exist."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS community_observations (
                            id VARCHAR(64) PRIMARY KEY,
                            source VARCHAR(64) NOT NULL,
                            category VARCHAR(64) NOT NULL,
                            value VARCHAR(64) NOT NULL,
                            latitude DOUBLE PRECISION NOT NULL,
                            longitude DOUBLE PRECISION NOT NULL,
                            osm_element_type VARCHAR(16),
                            osm_element_id BIGINT,
                            matched_distance_m DOUBLE PRECISION,
                            match_confidence DOUBLE PRECISION,
                            is_temporary BOOLEAN NOT NULL,
                            reported_at TIMESTAMPTZ NOT NULL,
                            expected_end_at TIMESTAMPTZ,
                            expires_at TIMESTAMPTZ,
                            verification_status VARCHAR(32) NOT NULL,
                            confirmations_count INTEGER NOT NULL DEFAULT 0,
                            disputes_count INTEGER NOT NULL DEFAULT 0,
                            contributor_id VARCHAR(64),
                            notes TEXT,
                            photo_url TEXT
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS community_interactions (
                            id SERIAL PRIMARY KEY,
                            observation_id VARCHAR(64) NOT NULL REFERENCES community_observations(id) ON DELETE CASCADE,
                            contributor_id VARCHAR(64) NOT NULL,
                            interaction_type VARCHAR(16) NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL,
                            CONSTRAINT uq_pg_obs_contributor UNIQUE(observation_id, contributor_id)
                        );
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_obs_lat_lon ON community_observations(latitude, longitude);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_obs_category ON community_observations(category);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_obs_status ON community_observations(verification_status);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_obs_osm ON community_observations(osm_element_type, osm_element_id);")

                    # Check PostGIS and add geometry column/index if enabled
                    if self._check_postgis(conn):
                        cur.execute(
                            """
                            DO $$
                            BEGIN
                                IF NOT EXISTS (
                                    SELECT 1 FROM information_schema.columns 
                                    WHERE table_name = 'community_observations' AND column_name = 'geom'
                                ) THEN
                                    ALTER TABLE community_observations ADD COLUMN geom geometry(Point, 4326);
                                    UPDATE community_observations SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326);
                                    CREATE INDEX IF NOT EXISTS idx_pg_obs_gist_geom ON community_observations USING GIST(geom);
                                END IF;
                            END $$;
                            """
                        )
                conn.commit()
        except Exception as e:
            logger.warning("PostgresCommunityObservationRepository init error (continuing): %s", e)

    def _row_to_observation(self, row: Dict[str, Any]) -> CommunityObservation:
        def ensure_tz(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        source_val = row.get("source_type") or row.get("source") or "community_observation"
        try:
            source_enum = AccessibilityEvidenceSource(source_val)
        except ValueError:
            source_enum = AccessibilityEvidenceSource.COMMUNITY_OBSERVATION

        reported = ensure_tz(row.get("created_at") or row.get("reported_at")) or datetime.now(timezone.utc)
        return CommunityObservation(
            id=row["id"],
            source=source_enum,
            category=ObservationCategory(row["category"]),
            value=row["value"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            osm_element_type=row.get("osm_element_type"),
            osm_element_id=int(row["osm_element_id"]) if row.get("osm_element_id") is not None and str(row["osm_element_id"]).isdigit() else None,
            is_temporary=bool(row.get("is_temporary", False)),
            reported_at=reported,
            expires_at=ensure_tz(row.get("expires_at")),
            verification_status=VerificationStatus(row.get("verification_status", "unverified")),
            confirmations_count=int(row.get("confirmations_count", 1)),
            disputes_count=int(row.get("disputes_count", 0)),
            contributor_id=row.get("contributor_id") or "anon",
            notes=row.get("notes"),
        )

    def save(self, observation: CommunityObservation) -> CommunityObservation:
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                has_postgis = self._check_postgis(conn)
                source_val = observation.source.value if hasattr(observation.source, "value") else str(observation.source)
                cat_val = observation.category.value if hasattr(observation.category, "value") else str(observation.category)
                ver_val = observation.verification_status.value if hasattr(observation.verification_status, "value") else str(observation.verification_status)
                osm_id_str = str(observation.osm_element_id) if observation.osm_element_id is not None else None

                if has_postgis:
                    sql = """
                        INSERT INTO community_observations (
                            id, category, value, latitude, longitude,
                            osm_element_type, osm_element_id, contributor_id,
                            source_type, is_temporary, expires_at, verification_status,
                            confirmations_count, disputes_count, notes,
                            created_at, updated_at, geom
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                        )
                        ON CONFLICT(id) DO UPDATE SET
                            value = EXCLUDED.value,
                            verification_status = EXCLUDED.verification_status,
                            confirmations_count = EXCLUDED.confirmations_count,
                            disputes_count = EXCLUDED.disputes_count,
                            expires_at = EXCLUDED.expires_at,
                            notes = EXCLUDED.notes,
                            updated_at = EXCLUDED.updated_at;
                    """
                    params = (
                        observation.id,
                        cat_val,
                        observation.value,
                        observation.latitude,
                        observation.longitude,
                        observation.osm_element_type,
                        osm_id_str,
                        observation.contributor_id or "anon",
                        source_val,
                        observation.is_temporary,
                        observation.expires_at,
                        ver_val,
                        observation.confirmations_count,
                        observation.disputes_count,
                        observation.notes,
                        now,
                        now,
                        observation.longitude,
                        observation.latitude,
                    )
                else:
                    sql = """
                        INSERT INTO community_observations (
                            id, category, value, latitude, longitude,
                            osm_element_type, osm_element_id, contributor_id,
                            source_type, is_temporary, expires_at, verification_status,
                            confirmations_count, disputes_count, notes,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT(id) DO UPDATE SET
                            value = EXCLUDED.value,
                            verification_status = EXCLUDED.verification_status,
                            confirmations_count = EXCLUDED.confirmations_count,
                            disputes_count = EXCLUDED.disputes_count,
                            expires_at = EXCLUDED.expires_at,
                            notes = EXCLUDED.notes,
                            updated_at = EXCLUDED.updated_at;
                    """
                    params = (
                        observation.id,
                        cat_val,
                        observation.value,
                        observation.latitude,
                        observation.longitude,
                        observation.osm_element_type,
                        osm_id_str,
                        observation.contributor_id or "anon",
                        source_val,
                        observation.is_temporary,
                        observation.expires_at,
                        ver_val,
                        observation.confirmations_count,
                        observation.disputes_count,
                        observation.notes,
                        now,
                        now,
                    )

                cur.execute(sql, params)
            conn.commit()
        return observation

    def get_by_id(self, observation_id: str) -> Optional[CommunityObservation]:
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM community_observations WHERE id = %s;", (observation_id,))
                    row = cur.fetchone()
                    return self._row_to_observation(row) if row else None
        except Exception as e:
            logger.warning("Postgres get_by_id failed (database outage/unreachable): %s", e)
            return None

    def get_by_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        now = datetime.now(timezone.utc)
        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    has_postgis = self._check_postgis(conn)
                    if has_postgis:
                        sql = """
                            SELECT * FROM community_observations
                            WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                        """
                        params = [min_lon, min_lat, max_lon, max_lat]
                    else:
                        sql = """
                            SELECT * FROM community_observations
                            WHERE latitude BETWEEN %s AND %s
                              AND longitude BETWEEN %s AND %s
                        """
                        params = [min_lat, max_lat, min_lon, max_lon]

                    if not include_expired:
                        sql += " AND (expires_at IS NULL OR expires_at > %s)"
                        params.append(now)

                    cur.execute(sql, tuple(params))
                    return [self._row_to_observation(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("Postgres get_by_bbox failed (database outage/unreachable): %s", e)
            return []

    def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        try:
            with self._get_connection() as conn:
                has_postgis = self._check_postgis(conn)
                now = datetime.now(timezone.utc)

                if has_postgis:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        sql = """
                            SELECT * FROM community_observations
                            WHERE ST_DWithin(
                                geom::geography,
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                                %s
                            )
                        """
                        params = [longitude, latitude, radius_m]
                        if not include_expired:
                            sql += " AND (expires_at IS NULL OR expires_at > %s)"
                            params.append(now)

                        cur.execute(sql, tuple(params))
                        return [self._row_to_observation(r) for r in cur.fetchall()]
                else:
                    # Bounding box filter + haversine calculation
                    lat_deg = radius_m / 111139.0
                    lon_deg = radius_m / (111139.0 * math.cos(math.radians(latitude)))
                    min_lat = latitude - lat_deg
                    max_lat = latitude + lat_deg
                    min_lon = longitude - lon_deg
                    max_lon = longitude + lon_deg

                    candidates = self.get_by_bbox(min_lat, min_lon, max_lat, max_lon, include_expired=include_expired)
                    results = []
                    for obs in candidates:
                        dist = self._haversine(latitude, longitude, obs.latitude, obs.longitude)
                        if dist <= radius_m:
                            results.append(obs)
                    return results
        except Exception as e:
            logger.warning("Postgres get_nearby failed (database outage/unreachable): %s", e)
            return []

    def get_by_osm_element(
        self,
        osm_element_type: str,
        osm_element_id: int,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = """
                    SELECT * FROM community_observations
                    WHERE osm_element_type = %s AND osm_element_id = %s
                """
                params = [osm_element_type, osm_element_id]
                if not include_expired:
                    sql += " AND (expires_at IS NULL OR expires_at > %s)"
                    params.append(now)

                cur.execute(sql, tuple(params))
                return [self._row_to_observation(r) for r in cur.fetchall()]

    def update(self, observation: CommunityObservation) -> CommunityObservation:
        return self.save(observation)

    def update_status(self, observation_id: str, new_status: Any) -> None:
        status_val = new_status.value if hasattr(new_status, "value") else str(new_status)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE community_observations SET verification_status = %s WHERE id = %s;",
                    (status_val, observation_id),
                )
            conn.commit()

    def delete(self, observation_id: str) -> bool:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM community_observations WHERE id = %s;", (observation_id,))
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = "SELECT * FROM community_observations"
                params = []
                if not include_expired:
                    sql += " WHERE (expires_at IS NULL OR expires_at > %s)"
                    params.append(now)
                sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s;"
                params.extend([limit, offset])

                cur.execute(sql, tuple(params))
                return [self._row_to_observation(r) for r in cur.fetchall()]

    get_all = list_all
    add = save

    def count(self, include_expired: bool = False) -> int:
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                sql = "SELECT COUNT(*) FROM community_observations"
                params = []
                if not include_expired:
                    sql += " WHERE (expires_at IS NULL OR expires_at > %s)"
                    params.append(now)
                cur.execute(sql, tuple(params))
                return cur.fetchone()[0]

    def record_interaction(
        self,
        observation_id: str,
        contributor_id: str,
        interaction_type: str,
        increment_count: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc)
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Atomic check and insert with transaction
                    cur.execute(
                        """
                        INSERT INTO community_interactions (
                            id, observation_id, contributor_id, interaction_type, created_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (observation_id, contributor_id) DO NOTHING;
                        """,
                        (str(uuid.uuid4()), observation_id, contributor_id, interaction_type, now),
                    )
                    inserted = cur.rowcount > 0

                    if inserted and increment_count:
                        if interaction_type == "confirm":
                            cur.execute(
                                "UPDATE community_observations SET confirmations_count = confirmations_count + 1 WHERE id = %s;",
                                (observation_id,),
                            )
                        elif interaction_type == "dispute":
                            cur.execute(
                                "UPDATE community_observations SET disputes_count = disputes_count + 1 WHERE id = %s;",
                                (observation_id,),
                            )
                conn.commit()
                return inserted
        except Exception as e:
            logger.error("Error recording interaction in Postgres: %s", e)
            return False

    def get_interactions(self, observation_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM community_interactions WHERE observation_id = %s ORDER BY created_at ASC;",
                    (observation_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
        return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    # Convenience aliases for parity across test suites
    def add(self, observation: CommunityObservation) -> CommunityObservation:
        return self.save(observation)

    def find_within_radius(self, latitude: float, longitude: float, radius_meters: float = 200.0, include_expired: bool = False) -> List[CommunityObservation]:
        return self.get_nearby(latitude, longitude, radius_m=radius_meters, include_expired=include_expired)

    def find_in_bounding_box(self, bbox: Any, include_expired: bool = False) -> List[CommunityObservation]:
        return self.get_by_bbox(bbox.south, bbox.west, bbox.north, bbox.east, include_expired=include_expired)

    def find_in_bbox(self, south: float, west: float, north: float, east: float, include_expired: bool = False) -> List[CommunityObservation]:
        return self.get_by_bbox(south, west, north, east, include_expired=include_expired)

    def find_nearby(self, latitude: float, longitude: float, radius_m: float = 200.0, include_expired: bool = False) -> List[CommunityObservation]:
        return self.get_nearby(latitude, longitude, radius_m=radius_m, include_expired=include_expired)


