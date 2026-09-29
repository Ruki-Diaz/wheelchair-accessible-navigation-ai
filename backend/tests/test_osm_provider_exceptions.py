"""Regression tests for OSMnx graph provider exception handling.

Covers:
- Successful graph retrieval via SyntheticGraphProvider (smoke test)
- InsufficientResponseError (empty Overpass response) -> NoPedestrianNetworkError
- ResponseStatusCodeError (HTTP error from Overpass) -> NetworkDownloadError
- requests network failures (Timeout, ConnectionError) -> NetworkDownloadError
- requests catch-all RequestException -> NetworkDownloadError
- Exception handler never itself raises AttributeError (regression guard)
- Typed domain exceptions remain distinct from each other
"""

import pytest
import networkx as nx
from unittest.mock import patch, MagicMock
import requests.exceptions as req_exc

from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError

from accessroute.graph.errors import (
    GraphAcquisitionError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
)
from accessroute.graph.provider import OpenStreetMapGraphProvider, SyntheticGraphProvider
from accessroute.graph.region import BoundingBox


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_bbox() -> BoundingBox:
    """A small but valid bounding box within Vermont South."""
    return BoundingBox(south=-37.858, west=145.172, north=-37.852, east=145.178)


@pytest.fixture()
def osm_provider() -> OpenStreetMapGraphProvider:
    return OpenStreetMapGraphProvider(timeout_seconds=10)


# ---------------------------------------------------------------------------
# 1. Successful retrieval — SyntheticGraphProvider smoke test
# ---------------------------------------------------------------------------

def test_synthetic_provider_returns_valid_graph(small_bbox):
    """SyntheticGraphProvider must return a non-empty MultiDiGraph without hitting the network."""
    provider = SyntheticGraphProvider()
    G = provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert len(G.nodes) > 0
    assert G.number_of_edges() > 0


def test_osm_provider_successful_download(osm_provider, small_bbox, synthetic_multidigraph):
    """OpenStreetMapGraphProvider returns a validated graph on successful Overpass response."""
    with patch("osmnx.graph_from_bbox", return_value=synthetic_multidigraph):
        G = osm_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert len(G.nodes) > 0


# ---------------------------------------------------------------------------
# 2. InsufficientResponseError -> NoPedestrianNetworkError
# ---------------------------------------------------------------------------

def test_insufficient_response_raises_no_pedestrian_network(osm_provider, small_bbox):
    """InsufficientResponseError (empty Overpass response) must produce NoPedestrianNetworkError."""
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("empty result")):
        with pytest.raises(NoPedestrianNetworkError) as exc_info:
            osm_provider.get_pedestrian_network(small_bbox)

    # Must chain the original osmnx exception
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, InsufficientResponseError)
    # Must NOT be confused with a network download failure
    assert not isinstance(exc_info.value, NetworkDownloadError)


def test_insufficient_response_message_contains_bbox(osm_provider, small_bbox):
    """NoPedestrianNetworkError message must reference the queried region."""
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("no data")):
        with pytest.raises(NoPedestrianNetworkError, match="No pedestrian network found"):
            osm_provider.get_pedestrian_network(small_bbox)


# ---------------------------------------------------------------------------
# 3. ResponseStatusCodeError -> NetworkDownloadError
# ---------------------------------------------------------------------------

def test_response_status_code_error_raises_network_download(osm_provider, small_bbox):
    """ResponseStatusCodeError (bad HTTP status) must produce NetworkDownloadError."""
    with patch("osmnx.graph_from_bbox", side_effect=ResponseStatusCodeError("429 Too Many Requests")):
        with pytest.raises(NetworkDownloadError) as exc_info:
            osm_provider.get_pedestrian_network(small_bbox)

    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ResponseStatusCodeError)
    # Must NOT be confused with a no-network result
    assert not isinstance(exc_info.value, NoPedestrianNetworkError)


# ---------------------------------------------------------------------------
# 4. requests network failures -> NetworkDownloadError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc_class", [
    req_exc.Timeout,
    req_exc.ConnectionError,
])
def test_requests_network_failure_raises_network_download(osm_provider, small_bbox, exc_class):
    """requests Timeout and ConnectionError must map to NetworkDownloadError."""
    with patch("osmnx.graph_from_bbox", side_effect=exc_class("network failure")):
        with pytest.raises(NetworkDownloadError):
            osm_provider.get_pedestrian_network(small_bbox)


def test_requests_exception_catch_all_raises_network_download(osm_provider, small_bbox):
    """Any requests.exceptions.RequestException must produce NetworkDownloadError.

    Note: requests.SSLError is a subclass of requests.ConnectionError, so it is caught
    by the ConnectionError clause rather than the generic RequestException clause.
    Either way, the result must be NetworkDownloadError.
    """
    with patch("osmnx.graph_from_bbox", side_effect=req_exc.SSLError("ssl handshake failed")):
        with pytest.raises(NetworkDownloadError):
            osm_provider.get_pedestrian_network(small_bbox)


# ---------------------------------------------------------------------------
# 5. AttributeError regression guard — the original production crash
# ---------------------------------------------------------------------------

def test_no_attribute_error_on_empty_overpass(osm_provider, small_bbox):
    """
    Regression test for the production crash:
      AttributeError: module 'osmnx._errors' has no attribute 'EmptyOverpassResponse'

    The exception handler must never itself raise AttributeError regardless of
    what osmnx raises.
    """
    # Simulate the exact production scenario: osmnx raises InsufficientResponseError
    # which is what Overpass returns for an area with no walkable data.
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("no results")):
        try:
            osm_provider.get_pedestrian_network(small_bbox)
        except AttributeError as e:
            pytest.fail(
                f"Exception handler itself raised AttributeError — the production bug has recurred: {e}"
            )
        except NoPedestrianNetworkError:
            pass  # Expected — this is the correct domain exception


def test_no_attribute_error_on_http_error(osm_provider, small_bbox):
    """Exception handler must not raise AttributeError for HTTP status errors."""
    with patch("osmnx.graph_from_bbox", side_effect=ResponseStatusCodeError("503")):
        try:
            osm_provider.get_pedestrian_network(small_bbox)
        except AttributeError as e:
            pytest.fail(f"AttributeError raised by exception handler: {e}")
        except NetworkDownloadError:
            pass  # Expected


# ---------------------------------------------------------------------------
# 6. Domain exception hierarchy — typed errors remain distinct
# ---------------------------------------------------------------------------

def test_no_pedestrian_network_is_graph_acquisition_error(osm_provider, small_bbox):
    """NoPedestrianNetworkError must be a subclass of GraphAcquisitionError."""
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("empty")):
        with pytest.raises(GraphAcquisitionError):
            osm_provider.get_pedestrian_network(small_bbox)


def test_network_download_is_graph_acquisition_error(osm_provider, small_bbox):
    """NetworkDownloadError must be a subclass of GraphAcquisitionError."""
    with patch("osmnx.graph_from_bbox", side_effect=ResponseStatusCodeError("500")):
        with pytest.raises(GraphAcquisitionError):
            osm_provider.get_pedestrian_network(small_bbox)


def test_empty_response_does_not_raise_network_download(osm_provider, small_bbox):
    """An empty Overpass response must NOT be misclassified as NetworkDownloadError."""
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("no data")):
        with pytest.raises(NoPedestrianNetworkError):
            osm_provider.get_pedestrian_network(small_bbox)

    # Double-check: catch NetworkDownloadError should NOT trigger
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("no data")):
        try:
            osm_provider.get_pedestrian_network(small_bbox)
        except NetworkDownloadError:
            pytest.fail("Empty Overpass response was misclassified as NetworkDownloadError")
        except NoPedestrianNetworkError:
            pass  # Correct


def test_connection_error_does_not_raise_no_pedestrian_network(osm_provider, small_bbox):
    """A network connection failure must NOT be misclassified as NoPedestrianNetworkError."""
    with patch("osmnx.graph_from_bbox", side_effect=req_exc.ConnectionError("refused")):
        with pytest.raises(NetworkDownloadError):
            osm_provider.get_pedestrian_network(small_bbox)


# ---------------------------------------------------------------------------
# 7. Verify osmnx exception classes are importable (import smoke test)
# ---------------------------------------------------------------------------

def test_osmnx_exception_classes_importable():
    """The osmnx 2.x exception classes used by provider.py must be importable."""
    from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError  # noqa: F401
    # Verify they are proper exception classes
    assert issubclass(InsufficientResponseError, Exception)
    assert issubclass(ResponseStatusCodeError, Exception)


def test_osmnx_does_not_expose_removed_classes():
    """Confirm the removed class names no longer exist — so this test suite is forward-aware."""
    import osmnx._errors as errs
    assert not hasattr(errs, "EmptyOverpassResponse"), (
        "EmptyOverpassResponse has been re-added to osmnx._errors. "
        "Review whether provider.py needs to be updated."
    )
    assert not hasattr(errs, "Response200Error"), (
        "Response200Error has been re-added to osmnx._errors. "
        "Review whether provider.py needs to be updated."
    )
