"""Elevation provider using the Open-Meteo Elevation API (Copernicus DEM 30m / 90m).

Open-Meteo provides free, open-access, keyless elevation queries backed by Copernicus GLO-30
globally and high-resolution national elevation models where available.
"""

import json
import logging
import time
from typing import List, Optional, Sequence, Tuple
import urllib.error
import urllib.parse
import urllib.request

from accessroute.elevation.base import ElevationProvider

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.open-meteo.com/v1/elevation"
MAX_BATCH_SIZE = 100  # API comfortably handles 100 coordinates
DEFAULT_TIMEOUT_SECONDS = 15.0
INTER_BATCH_DELAY_SECONDS = 0.1  # Low-latency delay between batches to respect burst limits


class OpenMeteoElevationProvider(ElevationProvider):
    """Elevation provider backed by Open-Meteo's Copernicus GLO-30 DEM service."""

    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        delay_seconds: float = INTER_BATCH_DELAY_SECONDS,
    ):
        self._api_url = api_url
        self._timeout = timeout_seconds
        self._delay = delay_seconds
        self._rate_limited_until = 0.0

    @property
    def source_name(self) -> str:
        return "open-meteo:copernicus_dem_30m"

    @property
    def resolution_meters(self) -> float:
        return 30.0

    @property
    def vertical_accuracy_meters(self) -> float:
        return 1.5

    def get_elevation(self, latitude: float, longitude: float) -> Optional[float]:
        results = self.get_elevations([(latitude, longitude)])
        return results[0] if results else None

    def get_elevations(
        self, coordinates: Sequence[Tuple[float, float]]
    ) -> List[Optional[float]]:
        if not coordinates:
            return []

        if time.time() < self._rate_limited_until:
            logger.info("Open-Meteo elevation provider in rate-limit backoff; skipping network query.")
            return [None] * len(coordinates)

        results: List[Optional[float]] = []

        # Process in batches of MAX_BATCH_SIZE
        for i in range(0, len(coordinates), MAX_BATCH_SIZE):
            if time.time() < self._rate_limited_until:
                results.extend([None] * (len(coordinates) - len(results)))
                break

            batch = coordinates[i : i + MAX_BATCH_SIZE]
            batch_elevations = self._fetch_batch(batch)
            results.extend(batch_elevations)
            if i + MAX_BATCH_SIZE < len(coordinates) and self._delay > 0:
                time.sleep(self._delay)

        return results

    def _fetch_batch(
        self, batch: Sequence[Tuple[float, float]]
    ) -> List[Optional[float]]:
        payload = json.dumps({
            "latitude": [round(float(lat), 6) for lat, _ in batch],
            "longitude": [round(float(lon), 6) for _, lon in batch],
        }).encode("utf-8")

        req = urllib.request.Request(
            self._api_url,
            data=payload,
            headers={
                "User-Agent": "AccessRouteAI/1.0 (Accessibility Navigation System)",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    elevations = data.get("elevation", [])
                    if isinstance(elevations, list) and len(elevations) == len(batch):
                        return [float(e) if e is not None else None for e in elevations]
                    elif isinstance(elevations, (int, float)) and len(batch) == 1:
                        return [float(elevations)]
                    else:
                        logger.warning(
                            "Open-Meteo elevation length mismatch: expected %d, got %s",
                            len(batch),
                            len(elevations) if isinstance(elevations, list) else "scalar",
                        )
                        return [None] * len(batch)

            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    err_body = ""
                    try:
                        err_body = exc.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                    if "hourly" in err_body.lower() or "daily" in err_body.lower():
                        logger.warning("Open-Meteo quota exceeded (%s). Engaging circuit breaker.", err_body.strip())
                        self._rate_limited_until = time.time() + 600.0  # Back off 10 minutes
                        return [None] * len(batch)
                    elif attempt < max_retries - 1:
                        wait_time = 5.0 * (attempt + 1)
                        logger.info("Open-Meteo burst limit hit (429), backing off for %.1fs...", wait_time)
                        time.sleep(wait_time)
                        continue
                    else:
                        self._rate_limited_until = time.time() + 120.0
                        logger.warning("Open-Meteo 429 limit persistent. Engaging circuit breaker for 2m.")
                        return [None] * len(batch)
                logger.warning("Open-Meteo HTTP error: %s", exc)
                return [None] * len(batch)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                logger.warning("Open-Meteo network query failed: %s", exc)
                return [None] * len(batch)
            except Exception as exc:
                logger.error("Unexpected error querying Open-Meteo elevation: %s", exc)
                return [None] * len(batch)

        return [None] * len(batch)

