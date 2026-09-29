"""Persistent local SQLite cache for elevation lookups.

Prevents redundant external API calls, supports fast batch retrieval, stores source metadata,
and operates completely offline once populated.
"""

from pathlib import Path
import sqlite3
import threading
from typing import Dict, List, Optional, Sequence, Tuple

from accessroute.elevation.base import ElevationProvider, ElevationResult

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"
DEFAULT_DB_PATH = DEFAULT_CACHE_DIR / "elevation_cache.sqlite"
COORDINATE_DECIMALS = 6  # 6 decimal places corresponds to ~0.11m spatial precision


class CachedElevationProvider(ElevationProvider):
    """Wraps an underlying ElevationProvider with persistent SQLite caching."""

    def __init__(
        self,
        backend: ElevationProvider,
        db_path: Path = DEFAULT_DB_PATH,
    ):
        self._backend = backend
        self._db_path = db_path
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
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
                CREATE TABLE IF NOT EXISTS elevation_cache (
                    lat_round REAL NOT NULL,
                    lon_round REAL NOT NULL,
                    elevation_m REAL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (lat_round, lon_round)
                )
                """
            )
            conn.commit()

    @property
    def source_name(self) -> str:
        return f"cached:{self._backend.source_name}"

    @property
    def resolution_meters(self) -> float:
        return self._backend.resolution_meters

    @property
    def vertical_accuracy_meters(self) -> float:
        return self._backend.vertical_accuracy_meters

    @property
    def cache_stats(self) -> Dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": self._hits + self._misses,
        }

    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]:
        results = self.get_elevations([(latitude, longitude)])
        return results[0] if results else None

    def get_elevations(
        self, coordinates: Sequence[Tuple[float, float]]
    ) -> List[Optional[float]]:
        if not coordinates:
            return []

        rounded_coords = [
            (round(float(lat), COORDINATE_DECIMALS), round(float(lon), COORDINATE_DECIMALS))
            for lat, lon in coordinates
        ]

        # 1. Query cached coordinates
        cached_results: Dict[Tuple[float, float], Optional[float]] = {}
        unique_rounded = list(dict.fromkeys(rounded_coords))

        with self._lock, self._get_connection() as conn:
            # Query in chunks of 500 to avoid SQLite variable limits
            chunk_size = 500
            for i in range(0, len(unique_rounded), chunk_size):
                chunk = unique_rounded[i : i + chunk_size]
                placeholders = ",".join(["(?, ?)"] * len(chunk))
                flat_params = [val for pt in chunk for val in pt]
                cursor = conn.execute(
                    f"SELECT lat_round, lon_round, elevation_m, status FROM elevation_cache WHERE (lat_round, lon_round) IN (VALUES {placeholders})",
                    flat_params,
                )
                for row in cursor.fetchall():
                    lat_r = row["lat_round"]
                    lon_r = row["lon_round"]
                    status = row["status"]
                    elev = row["elevation_m"] if status != "MISSING" else None
                    cached_results[(lat_r, lon_r)] = elev

        # 2. Determine uncached coordinates
        missing_coords = [
            pt for pt in unique_rounded if pt not in cached_results
        ]

        # Update hit/miss statistics
        self._hits += len(unique_rounded) - len(missing_coords)
        self._misses += len(missing_coords)

        # 3. Query backend for missing entries and save to cache incrementally
        if missing_coords:
            sub_batch_size = 100
            for i in range(0, len(missing_coords), sub_batch_size):
                sub_missing = missing_coords[i : i + sub_batch_size]
                backend_elevations = self._backend.get_elevations(sub_missing)
                insert_rows = []
                for (lat_r, lon_r), elev in zip(sub_missing, backend_elevations):
                    cached_results[(lat_r, lon_r)] = elev
                    if elev is not None:
                        insert_rows.append(
                            (lat_r, lon_r, elev, self._backend.source_name, "MEASURED")
                        )

                if insert_rows:
                    with self._lock, self._get_connection() as conn:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO elevation_cache 
                            (lat_round, lon_round, elevation_m, source, status)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            insert_rows,
                        )
                        conn.commit()

        # 4. Return results matching input coordinate order
        return [cached_results.get(pt) for pt in rounded_coords]
