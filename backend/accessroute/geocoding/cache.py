"""Persistent local caching for geocoder queries.

Prevents redundant external geocoding requests, respects provider rate limits,
and enables offline reproducibility for common benchmark queries.
"""

import json
from pathlib import Path
import sqlite3
import threading
from typing import List, Optional, Tuple

from accessroute.geocoding.base import GeocodeCandidate

DEFAULT_GEOCODE_CACHE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "cache"
)
DEFAULT_GEOCODE_DB_PATH = DEFAULT_GEOCODE_CACHE_DIR / "geocoding_cache.sqlite"


class GeocodingCache:
    """Thread-safe SQLite-backed geocoding query cache."""

    def __init__(self, db_path: Path = DEFAULT_GEOCODE_DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None

        if str(db_path) == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    cache_key TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    proximity TEXT,
                    results_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    @staticmethod
    def _make_key(
        query: str,
        proximity: Optional[Tuple[float, float]],
        country_code: Optional[str],
    ) -> str:
        q_norm = query.strip().lower()
        prox_str = f"{round(proximity[0], 4)}_{round(proximity[1], 4)}" if proximity else "none"
        cc_str = (country_code or "all").lower()
        return f"{q_norm}|{prox_str}|{cc_str}"

    def get(
        self,
        query: str,
        proximity: Optional[Tuple[float, float]] = None,
        country_code: Optional[str] = None,
    ) -> Optional[List[GeocodeCandidate]]:
        """Retrieve cached candidates if available."""
        key = self._make_key(query, proximity, country_code)
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT results_json FROM geocode_cache WHERE cache_key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row["results_json"])
                    return [GeocodeCandidate.from_dict(d) for d in data]
                except Exception:
                    return None
        return None

    def set(
        self,
        query: str,
        candidates: List[GeocodeCandidate],
        proximity: Optional[Tuple[float, float]] = None,
        country_code: Optional[str] = None,
    ) -> None:
        """Store candidate results in cache."""
        key = self._make_key(query, proximity, country_code)
        data = json.dumps([c.to_dict() for c in candidates])
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO geocode_cache (cache_key, query, proximity, results_json)
                VALUES (?, ?, ?, ?)
                """,
                (key, query, str(proximity), data),
            )
            conn.commit()
