"""Graph provider abstraction for pedestrian network acquisition.

Failover Strategy
-----------------
OpenStreetMapGraphProvider accepts a list of Overpass API endpoints.
On each call to get_pedestrian_network(), it attempts endpoints in order,
moving to the next on any infrastructure failure (connection refused, timeout,
HTTP error status).  Only after all endpoints are exhausted is a
NetworkDownloadError raised to the caller.

Environment variable:
    ACCESSROUTE_OVERPASS_ENDPOINTS
        Comma-separated list of Overpass base URLs in priority order.
        Example:
            https://overpass-api.de/api,https://overpass.kumi.systems/api
        When not set, a built-in ordered list of three public mirrors is used.

OSMnx 2.1.1 endpoint mechanism (confirmed by source inspection):
    ox.settings.overpass_url is read by _overpass._overpass_request() at
    every call.  Setting it immediately before ox.graph_from_bbox() is the
    supported, non-invasive way to direct requests to a specific server.
"""

from abc import ABC, abstractmethod
import logging
import os
from typing import List, Optional
import networkx as nx
import osmnx as ox
import requests.exceptions as _req_exc

from accessroute.config import (
    ACCESSIBILITY_NODE_TAGS,
    ACCESSIBILITY_WAY_TAGS,
    DEFAULT_OVERPASS_ENDPOINTS,
)
from accessroute.graph.errors import (
    GraphAcquisitionError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
)
from accessroute.graph.loader import validate_graph
from accessroute.graph.region import BoundingBox

# osmnx 2.x exception classes (osmnx._errors is private but stable since 2.0.0).
# InsufficientResponseError  — Overpass returned empty / too-few results.
# ResponseStatusCodeError    — Overpass returned a non-2xx HTTP status.
from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError

logger = logging.getLogger(__name__)

# ── Overpass endpoint defaults ────────────────────────────────────────────────
# Three geographically distributed public mirrors. Primary is the canonical
# overpass-api.de; the others are community-run mirrors with good uptime.
# Render's network should be able to reach all three; the order defines
# preference, not requirement.
_DEFAULT_OVERPASS_ENDPOINTS: List[str] = list(DEFAULT_OVERPASS_ENDPOINTS)

# Infrastructure exception types that warrant trying the next endpoint.
# InsufficientResponseError is NOT included — an empty result from one
# endpoint will be empty from all of them; it is not an infrastructure failure.
_INFRASTRUCTURE_EXCEPTIONS = (
    _req_exc.ConnectionError,   # connection refused, NewConnectionError, DNS failure
    _req_exc.Timeout,           # read/connect timeout
    _req_exc.SSLError,          # TLS handshake failure
    ResponseStatusCodeError,    # 429, 5xx from this endpoint
)


def _parse_overpass_endpoints() -> List[str]:
    """Return the ordered list of Overpass endpoints to try.

    Reads ACCESSROUTE_OVERPASS_ENDPOINTS env var; falls back to built-in defaults.
    Strips whitespace, filters empty tokens, removes redundant '/interpreter' suffixes,
    and removes duplicates while preserving order.
    """
    raw = os.environ.get("ACCESSROUTE_OVERPASS_ENDPOINTS", "")
    if raw.strip():
        seen: set = set()
        endpoints: List[str] = []
        for part in raw.split(","):
            ep = part.strip().rstrip("/")
            if ep.endswith("/interpreter"):
                ep = ep[:-len("/interpreter")].rstrip("/")
            if ep and ep not in seen:
                endpoints.append(ep)
                seen.add(ep)
        if endpoints:
            return endpoints
    return list(_DEFAULT_OVERPASS_ENDPOINTS)


class GraphProvider(ABC):
    """Abstract interface for acquiring pedestrian graphs across geographic regions."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifying name of the network source."""
        pass

    @abstractmethod
    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        """Download or construct a pedestrian MultiDiGraph for the specified bounding box.

        Args:
            bbox: Geographic bounding box to query.

        Returns:
            Validated networkx.MultiDiGraph with pedestrian nodes and ways.

        Raises:
            NetworkDownloadError: If external network request fails or times out.
            NoPedestrianNetworkError: If the region contains no walkable edges.
            GraphAcquisitionError: On other unexpected acquisition failures.
        """
        pass


class OpenStreetMapGraphProvider(GraphProvider):
    """Acquires pedestrian networks from OpenStreetMap via OSMnx with endpoint failover.

    Attempts each configured Overpass endpoint in order.  Infrastructure
    failures (connection refused, timeout, HTTP errors) trigger failover to the
    next endpoint.  An empty-network result (InsufficientResponseError) is
    treated as a definitive answer and immediately raises NoPedestrianNetworkError
    — it is not retried, because a different server will return the same empty data.

    Configuration
    -------------
    Set ACCESSROUTE_OVERPASS_ENDPOINTS env var to override the default endpoints.
    Set ACCESSROUTE_OVERPASS_TIMEOUT env var to override the per-request timeout
    (default: 60 s; the instance constructor value takes precedence).
    """

    def __init__(
        self,
        timeout_seconds: int = 60,
        endpoints: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            timeout_seconds: Per-request HTTP timeout for each Overpass attempt.
            endpoints: Explicit endpoint list (overrides env var and defaults).
                       Useful for testing.  Pass an empty list to use defaults.
        """
        self._timeout_seconds = timeout_seconds
        self._endpoints: List[str] = (
            endpoints if endpoints is not None else _parse_overpass_endpoints()
        )
        if not self._endpoints:
            self._endpoints = list(_DEFAULT_OVERPASS_ENDPOINTS)

    @property
    def provider_name(self) -> str:
        return "openstreetmap:walk"

    @property
    def endpoints(self) -> List[str]:
        """Read-only view of the configured endpoint list."""
        return list(self._endpoints)

    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        """Download a pedestrian graph with automatic endpoint failover.

        Iterates through configured Overpass endpoints.  Infrastructure failures
        advance to the next endpoint.  All-endpoints-exhausted raises
        NetworkDownloadError.
        """
        logger.info(
            "Querying pedestrian network: S=%.4f W=%.4f N=%.4f E=%.4f "
            "(area=%.2f km²) via %d endpoint(s).",
            bbox.south,
            bbox.west,
            bbox.north,
            bbox.east,
            bbox.area_km2,
            len(self._endpoints),
        )

        # Configure OSMnx to preserve all accessibility tags.
        # These are set once before the failover loop; they are global settings
        # that do not change between endpoint attempts.
        ox.settings.useful_tags_way = list(
            set(ox.settings.useful_tags_way + ACCESSIBILITY_WAY_TAGS)
        )
        ox.settings.useful_tags_node = list(
            set(ox.settings.useful_tags_node + ACCESSIBILITY_NODE_TAGS)
        )
        ox.settings.requests_timeout = self._timeout_seconds
        ox.settings.overpass_rate_limit = False

        osmnx_bbox = bbox.as_osmnx_bbox()
        endpoint_errors: List[str] = []
        n = len(self._endpoints)

        for attempt_idx, endpoint in enumerate(self._endpoints, start=1):
            # ── Point OSMnx at this endpoint ──────────────────────────────────
            # ox.settings.overpass_url is read fresh by _overpass._overpass_request()
            # at every call, so assigning here before graph_from_bbox() is safe.
            ox.settings.overpass_url = endpoint

            logger.info(
                "Overpass attempt %d/%d: %s",
                attempt_idx,
                n,
                endpoint,
            )

            try:
                G = ox.graph_from_bbox(
                    bbox=osmnx_bbox,
                    network_type="walk",
                    simplify=True,
                    retain_all=False,
                )

            except InsufficientResponseError as exc:
                # An empty result is a data fact, not an infrastructure failure.
                # A different endpoint will return the same empty response for
                # the same geographic area — do not retry.
                raise NoPedestrianNetworkError(
                    f"No pedestrian network found within requested region: {bbox.to_dict()}."
                ) from exc

            except _INFRASTRUCTURE_EXCEPTIONS as exc:
                # Infrastructure failure on this endpoint: log and try the next one.
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Overpass endpoint failed: %s (attempt %d/%d: %s)",
                    reason,
                    attempt_idx,
                    n,
                    endpoint,
                )
                endpoint_errors.append(f"[{attempt_idx}/{n}] {endpoint}: {reason}")
                continue  # next endpoint

            except _req_exc.RequestException as exc:
                # Any other requests-layer failure (redirect loop, chunked encoding, etc.)
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Overpass endpoint failed: %s (attempt %d/%d: %s)",
                    reason,
                    attempt_idx,
                    n,
                    endpoint,
                )
                endpoint_errors.append(f"[{attempt_idx}/{n}] {endpoint}: {reason}")
                continue  # next endpoint

            except Exception as exc:
                # Last-resort: inspect message for known patterns before bubbling up.
                msg = str(exc).lower()
                if "empty" in msg or "no data" in msg or "insufficient" in msg:
                    raise NoPedestrianNetworkError(
                        f"No walkable paths found in region: {bbox.to_dict()}."
                    ) from exc
                if "timeout" in msg or "connection" in msg or "status code" in msg:
                    # Treat as infrastructure failure and try next endpoint.
                    reason = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Overpass endpoint failed: %s (attempt %d/%d: %s)",
                        reason,
                        attempt_idx,
                        n,
                        endpoint,
                    )
                    endpoint_errors.append(f"[{attempt_idx}/{n}] {endpoint}: {reason}")
                    continue
                # Unexpected programming error — do not retry, raise immediately.
                raise GraphAcquisitionError(
                    f"Unexpected OSM graph acquisition failure: {exc}"
                ) from exc

            else:
                # ── Success ────────────────────────────────────────────────────
                logger.info(
                    "Overpass acquisition succeeded using: %s (attempt %d/%d).",
                    endpoint,
                    attempt_idx,
                    n,
                )
                try:
                    validate_graph(G)
                except Exception as exc:
                    raise GraphAcquisitionError(
                        f"Downloaded graph failed validation: {exc}"
                    ) from exc
                return G

        # All endpoints exhausted without a successful response.
        summary = "; ".join(endpoint_errors)
        raise NetworkDownloadError(
            f"All {n} Overpass endpoint(s) failed for region {bbox.to_dict()}. "
            f"Errors: {summary}"
        )


class SyntheticGraphProvider(GraphProvider):
    """Deterministic offline graph provider for testing without external network calls."""

    def __init__(self, template_graph: Optional[nx.MultiDiGraph] = None) -> None:
        self._template = template_graph

    @property
    def provider_name(self) -> str:
        return "synthetic:offline_test"

    def get_pedestrian_network(self, bbox: BoundingBox) -> nx.MultiDiGraph:
        if self._template is not None:
            return self._template.copy()

        # Build a minimal synthetic 4-node grid centered within the bbox
        G = nx.MultiDiGraph()
        G.graph["crs"] = "EPSG:4326"
        c_lat, c_lon = bbox.center
        d_lat = 0.001
        d_lon = 0.001

        nodes = {
            1: {"y": c_lat - d_lat, "x": c_lon - d_lon},
            2: {"y": c_lat - d_lat, "x": c_lon + d_lon},
            3: {"y": c_lat + d_lat, "x": c_lon + d_lon},
            4: {"y": c_lat + d_lat, "x": c_lon - d_lon},
        }
        for n_id, data in nodes.items():
            G.add_node(n_id, **data)

        edges = [
            (1, 2, 100.0, "paved"),
            (2, 1, 100.0, "paved"),
            (2, 3, 100.0, "paved"),
            (3, 2, 100.0, "paved"),
            (3, 4, 100.0, "paved"),
            (4, 3, 100.0, "paved"),
            (4, 1, 100.0, "paved"),
            (1, 4, 100.0, "paved"),
            (1, 3, 141.4, "gravel"),
            (3, 1, 141.4, "gravel"),
        ]
        for u, v, length, surface in edges:
            G.add_edge(u, v, key=0, length=length, surface=surface, highway="footway")

        validate_graph(G)
        return G
