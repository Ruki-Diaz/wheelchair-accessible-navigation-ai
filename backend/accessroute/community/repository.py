"""Repository interface and SQLite persistence for Community Accessibility Observations.

Stage 9 Architecture:
Separates community observations completely from GraphML caching.
Provides an abstract repository interface that enables future migration to PostgreSQL/PostGIS.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from accessroute.community.models import (
    AccessibilityEvidenceSource,
    CommunityObservation,
    ObservationCategory,
    VerificationStatus,
)


class CommunityObservationRepository(ABC):
    """Abstract interface for persisting and querying community accessibility observations."""

    @abstractmethod
    def save(self, observation: CommunityObservation) -> CommunityObservation:
        """Persist a new community observation."""
        pass

    @abstractmethod
    def get_by_id(self, observation_id: str) -> Optional[CommunityObservation]:
        """Retrieve an observation by its unique identifier."""
        pass

    @abstractmethod
    def get_by_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Query observations within a geographic bounding box."""
        pass

    @abstractmethod
    def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Query observations within radius_m of a given point."""
        pass

    @abstractmethod
    def get_by_osm_element(
        self,
        osm_element_type: str,
        osm_element_id: int,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Query active observations attached to a specific OSM element."""
        pass

    @abstractmethod
    def update(self, observation: CommunityObservation) -> CommunityObservation:
        """Update an existing observation."""
        pass

    @abstractmethod
    def delete(self, observation_id: str) -> bool:
        """Delete an observation by ID."""
        pass

    @abstractmethod
    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        """Paginate observations."""
        pass

    @abstractmethod
    def record_interaction(
        self,
        observation_id: str,
        contributor_id: str,
        interaction_type: str,
    ) -> bool:
        """Record a confirmation or dispute. Returns False if duplicate contributor."""
        pass

    @abstractmethod
    def count(self, include_expired: bool = False) -> int:
        """Count total observations in the repository."""
        pass


class SQLiteCommunityObservationRepository(CommunityObservationRepository):
    """SQLite implementation of CommunityObservationRepository with spatial bounding queries."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize SQLite connection and schema.

        Args:
            db_path: Path to sqlite database file. If None or ':memory:', uses in-memory DB or default path.
        """
        if db_path is None:
            default_dir = Path(__file__).resolve().parent.parent / "data"
            default_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(default_dir / "community_observations.db")
        else:
            self.db_path = db_path
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # WAL mode for concurrent readers and fast writes
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS community_observations (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    osm_element_type TEXT,
                    osm_element_id INTEGER,
                    matched_distance_m REAL,
                    match_confidence REAL,
                    is_temporary INTEGER NOT NULL,
                    reported_at TEXT NOT NULL,
                    expected_end_at TEXT,
                    expires_at TEXT,
                    verification_status TEXT NOT NULL,
                    confirmations_count INTEGER NOT NULL DEFAULT 0,
                    disputes_count INTEGER NOT NULL DEFAULT 0,
                    contributor_id TEXT,
                    notes TEXT,
                    photo_url TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS community_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL,
                    contributor_id TEXT NOT NULL,
                    interaction_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(observation_id, contributor_id),
                    FOREIGN KEY(observation_id) REFERENCES community_observations(id) ON DELETE CASCADE
                );
                """
            )
            # Spatial and lookup indices
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_lat_lon ON community_observations(latitude, longitude);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_category ON community_observations(category);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_status ON community_observations(verification_status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_osm ON community_observations(osm_element_type, osm_element_id);")

    def _row_to_observation(self, row: sqlite3.Row) -> CommunityObservation:
        def parse_dt(val: Optional[str]) -> Optional[datetime]:
            if not val:
                return None
            try:
                dt = datetime.fromisoformat(val)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None

        reported = parse_dt(row["reported_at"]) or datetime.now(timezone.utc)
        expected = parse_dt(row["expected_end_at"])
        expires = parse_dt(row["expires_at"])

        return CommunityObservation(
            id=row["id"],
            source=AccessibilityEvidenceSource(row["source"]),
            category=ObservationCategory(row["category"]),
            value=row["value"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            osm_element_type=row["osm_element_type"],
            osm_element_id=int(row["osm_element_id"]) if row["osm_element_id"] is not None else None,
            matched_distance_m=float(row["matched_distance_m"]) if row["matched_distance_m"] is not None else None,
            match_confidence=float(row["match_confidence"]) if row["match_confidence"] is not None else None,
            is_temporary=bool(row["is_temporary"]),
            reported_at=reported,
            expected_end_at=expected,
            expires_at=expires,
            verification_status=VerificationStatus(row["verification_status"]),
            confirmations_count=int(row["confirmations_count"]),
            disputes_count=int(row["disputes_count"]),
            contributor_id=row["contributor_id"],
            notes=row["notes"],
            photo_url=row["photo_url"],
        )

    def save(self, observation: CommunityObservation) -> CommunityObservation:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO community_observations (
                    id, source, category, value, latitude, longitude,
                    osm_element_type, osm_element_id, matched_distance_m, match_confidence,
                    is_temporary, reported_at, expected_end_at, expires_at,
                    verification_status, confirmations_count, disputes_count,
                    contributor_id, notes, photo_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    category = excluded.category,
                    value = excluded.value,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    osm_element_type = excluded.osm_element_type,
                    osm_element_id = excluded.osm_element_id,
                    matched_distance_m = excluded.matched_distance_m,
                    match_confidence = excluded.match_confidence,
                    is_temporary = excluded.is_temporary,
                    reported_at = excluded.reported_at,
                    expected_end_at = excluded.expected_end_at,
                    expires_at = excluded.expires_at,
                    verification_status = excluded.verification_status,
                    confirmations_count = excluded.confirmations_count,
                    disputes_count = excluded.disputes_count,
                    contributor_id = excluded.contributor_id,
                    notes = excluded.notes,
                    photo_url = excluded.photo_url;
                """,
                (
                    observation.id,
                    observation.source.value,
                    observation.category.value,
                    observation.value,
                    observation.latitude,
                    observation.longitude,
                    observation.osm_element_type,
                    observation.osm_element_id,
                    observation.matched_distance_m,
                    observation.match_confidence,
                    1 if observation.is_temporary else 0,
                    observation.reported_at.isoformat(),
                    observation.expected_end_at.isoformat() if observation.expected_end_at else None,
                    observation.expires_at.isoformat() if observation.expires_at else None,
                    observation.verification_status.value,
                    observation.confirmations_count,
                    observation.disputes_count,
                    observation.contributor_id,
                    observation.notes,
                    observation.photo_url,
                ),
            )
        return observation

    def get_by_id(self, observation_id: str) -> Optional[CommunityObservation]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM community_observations WHERE id = ?;", (observation_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_observation(row)

    def get_by_bbox(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM community_observations
                WHERE latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?;
                """,
                (min_lat, max_lat, min_lon, max_lon),
            )
            rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        results: List[CommunityObservation] = []
        for r in rows:
            obs = self._row_to_observation(r)
            if not include_expired and not obs.is_active(now):
                continue
            results.append(obs)
        return results

    def get_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 200.0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        # Approximate 1 degree latitude ~ 111,320m
        delta_lat = radius_m / 111320.0
        cos_lat = math.cos(math.radians(latitude))
        delta_lon = radius_m / (111320.0 * max(cos_lat, 0.01))

        candidates = self.get_by_bbox(
            min_lat=latitude - delta_lat,
            min_lon=longitude - delta_lon,
            max_lat=latitude + delta_lat,
            max_lon=longitude + delta_lon,
            include_expired=include_expired,
        )

        # Exact Haversine filter
        nearby: List[CommunityObservation] = []
        for obs in candidates:
            dist = self._haversine(latitude, longitude, obs.latitude, obs.longitude)
            if dist <= radius_m:
                nearby.append(obs)

        return sorted(nearby, key=lambda o: self._haversine(latitude, longitude, o.latitude, o.longitude))

    def get_by_osm_element(
        self,
        osm_element_type: str,
        osm_element_id: int,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        with self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM community_observations
                WHERE osm_element_type = ? AND osm_element_id = ?;
                """,
                (osm_element_type, osm_element_id),
            )
            rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        results: List[CommunityObservation] = []
        for r in rows:
            obs = self._row_to_observation(r)
            if not include_expired and not obs.is_active(now):
                continue
            results.append(obs)
        return results

    def update(self, observation: CommunityObservation) -> CommunityObservation:
        return self.save(observation)

    def update_status(self, observation_id: str, new_status: Any) -> bool:
        status_val = new_status.value if hasattr(new_status, "value") else str(new_status)
        with self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE community_observations SET verification_status = ? WHERE id = ?;",
                (status_val, observation_id),
            )
            return cur.rowcount > 0

    def delete(self, observation_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM community_observations WHERE id = ?;", (observation_id,))
            return cur.rowcount > 0

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_expired: bool = False,
    ) -> List[CommunityObservation]:
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM community_observations ORDER BY reported_at DESC LIMIT ? OFFSET ?;",
                (limit, offset),
            )
            rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        results: List[CommunityObservation] = []
        for r in rows:
            obs = self._row_to_observation(r)
            if not include_expired and not obs.is_active(now):
                continue
            results.append(obs)
        return results

    get_all = list_all
    add = save

    def record_interaction(
        self,
        observation_id: str,
        contributor_id: str,
        interaction_type: str,
        increment_count: bool = True,
    ) -> bool:
        """Record an interaction (confirm/dispute). Returns False if duplicate contributor."""
        now_str = datetime.now(timezone.utc).isoformat()
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO community_interactions (
                        observation_id, contributor_id, interaction_type, created_at
                    ) VALUES (?, ?, ?, ?);
                    """,
                    (observation_id, contributor_id, interaction_type, now_str),
                )
                if increment_count:
                    if interaction_type == "confirm":
                        conn.execute(
                            "UPDATE community_observations SET confirmations_count = confirmations_count + 1 WHERE id = ?;",
                            (observation_id,),
                        )
                    elif interaction_type == "dispute":
                        conn.execute(
                            "UPDATE community_observations SET disputes_count = disputes_count + 1 WHERE id = ?;",
                            (observation_id,),
                        )
                return True
        except sqlite3.IntegrityError:
            # Contributor already confirmed or disputed this report
            return False

    def get_interactions(self, observation_id: str) -> List[Dict[str, Any]]:
        """Retrieve all recorded interactions for an observation."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM community_interactions WHERE observation_id = ? ORDER BY created_at ASC;",
                (observation_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def count(self, include_expired: bool = False) -> int:
        with self._get_connection() as conn:
            if include_expired:
                cur = conn.execute("SELECT COUNT(*) FROM community_observations;")
                return int(cur.fetchone()[0])
            else:
                cur = conn.execute("SELECT * FROM community_observations;")
                rows = cur.fetchall()
                now = datetime.now(timezone.utc)
                return sum(1 for r in rows if self._row_to_observation(r).is_active(now))

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great circle distance in meters between two lat/lon coordinates."""
        r = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
