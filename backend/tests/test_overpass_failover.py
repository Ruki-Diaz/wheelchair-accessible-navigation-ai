"""Regression tests for Overpass endpoint failover in OpenStreetMapGraphProvider.

Tests cover:
- Primary endpoint succeeds → no failover attempted
- Primary fails, secondary succeeds → correct failover
- Connection refused → failover
- Timeout → failover
- All endpoints fail → NetworkDownloadError
- Empty network result → NoPedestrianNetworkError (no retry on different endpoint)
- Unexpected error → GraphAcquisitionError
- Endpoint parsing (env var, deduplication, whitespace)
- No infinite retry (bounded by endpoint count)
- Structured logging (attempt N/M, success, failure messages)
- Existing OSMnx exception regression tests still pass
"""

import os
import pytest
import networkx as nx
from unittest.mock import patch, call, MagicMock
import requests.exceptions as req_exc
import logging

from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError

from accessroute.graph.errors import (
    GraphAcquisitionError,
    NetworkDownloadError,
    NoPedestrianNetworkError,
)
from accessroute.graph.provider import (
    OpenStreetMapGraphProvider,
    SyntheticGraphProvider,
    _parse_overpass_endpoints,
    _DEFAULT_OVERPASS_ENDPOINTS,
)
from accessroute.graph.region import BoundingBox


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_bbox() -> BoundingBox:
    return BoundingBox(south=-37.858, west=145.172, north=-37.852, east=145.178)


@pytest.fixture()
def two_endpoint_provider() -> OpenStreetMapGraphProvider:
    """Provider configured with exactly two test endpoints."""
    return OpenStreetMapGraphProvider(
        endpoints=["https://primary.example.com/api", "https://secondary.example.com/api"],
        timeout_seconds=10,
    )


@pytest.fixture()
def three_endpoint_provider() -> OpenStreetMapGraphProvider:
    """Provider configured with three test endpoints."""
    return OpenStreetMapGraphProvider(
        endpoints=[
            "https://ep1.example.com/api",
            "https://ep2.example.com/api",
            "https://ep3.example.com/api",
        ],
        timeout_seconds=10,
    )


# ---------------------------------------------------------------------------
# 1. Primary endpoint succeeds — no failover
# ---------------------------------------------------------------------------

def test_primary_endpoint_succeeds_no_failover(
    two_endpoint_provider, small_bbox, synthetic_multidigraph
):
    """When the primary endpoint works, graph_from_bbox is called exactly once."""
    with patch("osmnx.graph_from_bbox", return_value=synthetic_multidigraph) as mock_gbbox:
        G = two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert mock_gbbox.call_count == 1


def test_primary_endpoint_sets_overpass_url(
    two_endpoint_provider, small_bbox, synthetic_multidigraph
):
    """ox.settings.overpass_url must be set to the primary endpoint before the request."""
    captured_urls = []

    def capture_url(**kwargs):
        import osmnx as ox
        captured_urls.append(ox.settings.overpass_url)
        return synthetic_multidigraph

    with patch("osmnx.graph_from_bbox", side_effect=capture_url):
        two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert captured_urls[0] == "https://primary.example.com/api"


# ---------------------------------------------------------------------------
# 2. Primary fails, secondary succeeds
# ---------------------------------------------------------------------------

def test_primary_connection_refused_secondary_succeeds(
    two_endpoint_provider, small_bbox, synthetic_multidigraph
):
    """Connection refused on primary must trigger failover to secondary."""
    side_effects = [
        req_exc.ConnectionError("Connection refused"),
        synthetic_multidigraph,
    ]
    with patch("osmnx.graph_from_bbox", side_effect=side_effects) as mock_gbbox:
        G = two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert mock_gbbox.call_count == 2


def test_secondary_endpoint_url_set_on_failover(
    two_endpoint_provider, small_bbox, synthetic_multidigraph
):
    """ox.settings.overpass_url must be updated to the secondary endpoint on failover."""
    captured_urls = []

    call_count = [0]

    def side_effect(**kwargs):
        import osmnx as ox
        captured_urls.append(ox.settings.overpass_url)
        call_count[0] += 1
        if call_count[0] == 1:
            raise req_exc.ConnectionError("refused")
        return synthetic_multidigraph

    with patch("osmnx.graph_from_bbox", side_effect=side_effect):
        two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert captured_urls[0] == "https://primary.example.com/api"
    assert captured_urls[1] == "https://secondary.example.com/api"


# ---------------------------------------------------------------------------
# 3. Connection refused failover
# ---------------------------------------------------------------------------

def test_connection_refused_triggers_failover(
    two_endpoint_provider, small_bbox, synthetic_multidigraph
):
    """NewConnectionError (subclass of ConnectionError) triggers failover."""
    # NewConnectionError is a subclass of requests.ConnectionError
    new_conn_err = req_exc.ConnectionError(
        "HTTPSConnectionPool: Max retries exceeded (Caused by NewConnectionError: "
        "Failed to establish a new connection: [Errno 111] Connection refused)"
    )
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=[new_conn_err, synthetic_multidigraph],
    ) as mock_gbbox:
        G = two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert mock_gbbox.call_count == 2


# ---------------------------------------------------------------------------
# 4. Timeout failover
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc_class", [req_exc.Timeout, req_exc.ReadTimeout, req_exc.ConnectTimeout])
def test_timeout_triggers_failover(exc_class, two_endpoint_provider, small_bbox, synthetic_multidigraph):
    """All timeout variants must trigger failover."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=[exc_class("timed out"), synthetic_multidigraph],
    ) as mock_gbbox:
        G = two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert mock_gbbox.call_count == 2


# ---------------------------------------------------------------------------
# 5. All endpoints fail → NetworkDownloadError
# ---------------------------------------------------------------------------

def test_all_endpoints_fail_raises_network_download_error(
    three_endpoint_provider, small_bbox
):
    """When every endpoint fails with a connection error, raise NetworkDownloadError."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.ConnectionError("refused"),
    ) as mock_gbbox:
        with pytest.raises(NetworkDownloadError, match="All 3 Overpass endpoint"):
            three_endpoint_provider.get_pedestrian_network(small_bbox)

    # Exactly 3 attempts — no more, no fewer.
    assert mock_gbbox.call_count == 3


def test_all_endpoints_timeout_raises_network_download_error(
    three_endpoint_provider, small_bbox
):
    """When every endpoint times out, raise NetworkDownloadError."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.Timeout("timed out"),
    ) as mock_gbbox:
        with pytest.raises(NetworkDownloadError):
            three_endpoint_provider.get_pedestrian_network(small_bbox)

    assert mock_gbbox.call_count == 3


def test_http_error_on_all_endpoints_raises_network_download(
    three_endpoint_provider, small_bbox
):
    """ResponseStatusCodeError on all endpoints → NetworkDownloadError."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=ResponseStatusCodeError("503 Service Unavailable"),
    ) as mock_gbbox:
        with pytest.raises(NetworkDownloadError):
            three_endpoint_provider.get_pedestrian_network(small_bbox)

    assert mock_gbbox.call_count == 3


# ---------------------------------------------------------------------------
# 6. Empty network → NoPedestrianNetworkError (no retry on different endpoint)
# ---------------------------------------------------------------------------

def test_insufficient_response_does_not_failover(two_endpoint_provider, small_bbox):
    """InsufficientResponseError must raise immediately — no retry on secondary endpoint."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=InsufficientResponseError("no results"),
    ) as mock_gbbox:
        with pytest.raises(NoPedestrianNetworkError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)

    # Must stop after the first attempt — empty is empty everywhere.
    assert mock_gbbox.call_count == 1


def test_insufficient_response_message_references_region(two_endpoint_provider, small_bbox):
    """NoPedestrianNetworkError message must include the bounding box region."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=InsufficientResponseError("empty"),
    ):
        with pytest.raises(NoPedestrianNetworkError, match="No pedestrian network found"):
            two_endpoint_provider.get_pedestrian_network(small_bbox)


def test_insufficient_response_is_not_network_download_error(two_endpoint_provider, small_bbox):
    """An empty Overpass response must NOT be misclassified as NetworkDownloadError."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=InsufficientResponseError("no data"),
    ):
        try:
            two_endpoint_provider.get_pedestrian_network(small_bbox)
        except NetworkDownloadError:
            pytest.fail("Empty Overpass response was misclassified as NetworkDownloadError")
        except NoPedestrianNetworkError:
            pass  # Correct


# ---------------------------------------------------------------------------
# 7. Unexpected error → GraphAcquisitionError
# ---------------------------------------------------------------------------

def test_unexpected_exception_raises_graph_acquisition_error(
    two_endpoint_provider, small_bbox
):
    """An unexpected programming exception must raise GraphAcquisitionError immediately."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=RuntimeError("unexpected internal osmnx error"),
    ) as mock_gbbox:
        with pytest.raises(GraphAcquisitionError, match="Unexpected OSM graph acquisition"):
            two_endpoint_provider.get_pedestrian_network(small_bbox)

    # Must stop at first endpoint — unexpected errors are not retried.
    assert mock_gbbox.call_count == 1


def test_unexpected_error_is_not_network_download_error(two_endpoint_provider, small_bbox):
    """GraphAcquisitionError must not be caught by NetworkDownloadError handler."""
    with patch("osmnx.graph_from_bbox", side_effect=RuntimeError("unexpected")):
        with pytest.raises(GraphAcquisitionError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)


# ---------------------------------------------------------------------------
# 8. Endpoint parsing — env var, deduplication, whitespace
# ---------------------------------------------------------------------------

def test_parse_endpoints_returns_defaults_when_env_not_set():
    """_parse_overpass_endpoints() returns built-in defaults when env var absent."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ACCESSROUTE_OVERPASS_ENDPOINTS", None)
        result = _parse_overpass_endpoints()
    assert result == _DEFAULT_OVERPASS_ENDPOINTS


def test_parse_endpoints_reads_env_var():
    """_parse_overpass_endpoints() parses a custom comma-separated env var."""
    custom = "https://a.example.com/api,https://b.example.com/api"
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": custom}):
        result = _parse_overpass_endpoints()
    assert result == ["https://a.example.com/api", "https://b.example.com/api"]


def test_parse_endpoints_strips_whitespace():
    """Whitespace around comma-separated entries must be stripped."""
    raw = "  https://a.example.com/api ,  https://b.example.com/api  "
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": raw}):
        result = _parse_overpass_endpoints()
    assert result == ["https://a.example.com/api", "https://b.example.com/api"]


def test_parse_endpoints_deduplicates():
    """Duplicate endpoints must be removed while preserving order."""
    raw = "https://a.example.com/api,https://b.example.com/api,https://a.example.com/api"
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": raw}):
        result = _parse_overpass_endpoints()
    assert result == ["https://a.example.com/api", "https://b.example.com/api"]


def test_parse_endpoints_trailing_slashes_stripped():
    """Trailing slashes on endpoint URLs must be removed."""
    raw = "https://a.example.com/api/"
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": raw}):
        result = _parse_overpass_endpoints()
    assert result == ["https://a.example.com/api"]


def test_parse_endpoints_interpreter_suffix_stripped():
    """Redundant /interpreter suffix must be stripped so OSMnx doesn't append it twice."""
    raw = "https://a.example.com/api/interpreter, https://b.example.com/api/interpreter/"
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": raw}):
        result = _parse_overpass_endpoints()
    assert result == ["https://a.example.com/api", "https://b.example.com/api"]


def test_parse_endpoints_empty_env_var_returns_defaults():
    """An empty ACCESSROUTE_OVERPASS_ENDPOINTS falls back to built-in defaults."""
    with patch.dict(os.environ, {"ACCESSROUTE_OVERPASS_ENDPOINTS": ""}):
        result = _parse_overpass_endpoints()
    assert result == _DEFAULT_OVERPASS_ENDPOINTS


def test_provider_endpoint_list_accessible():
    """OpenStreetMapGraphProvider.endpoints must expose the configured list."""
    ep = ["https://a.example.com/api", "https://b.example.com/api"]
    provider = OpenStreetMapGraphProvider(endpoints=ep)
    assert provider.endpoints == ep


# ---------------------------------------------------------------------------
# 9. No infinite retry (bounded by endpoint count)
# ---------------------------------------------------------------------------

def test_no_infinite_retry_single_endpoint(small_bbox):
    """A single-endpoint provider must make exactly 1 attempt."""
    provider = OpenStreetMapGraphProvider(
        endpoints=["https://only.example.com/api"], timeout_seconds=5
    )
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.ConnectionError("refused"),
    ) as mock_gbbox:
        with pytest.raises(NetworkDownloadError):
            provider.get_pedestrian_network(small_bbox)

    assert mock_gbbox.call_count == 1


def test_no_infinite_retry_two_endpoints(two_endpoint_provider, small_bbox):
    """With two endpoints, exactly 2 attempts must be made before giving up."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.ConnectionError("refused"),
    ) as mock_gbbox:
        with pytest.raises(NetworkDownloadError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert mock_gbbox.call_count == 2


def test_no_retry_after_insufficient_response(two_endpoint_provider, small_bbox):
    """InsufficientResponseError must short-circuit — exactly 1 attempt total."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=InsufficientResponseError("no data"),
    ) as mock_gbbox:
        with pytest.raises(NoPedestrianNetworkError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert mock_gbbox.call_count == 1


# ---------------------------------------------------------------------------
# 10. Structured logging verification
# ---------------------------------------------------------------------------

def test_logs_attempt_number_on_each_try(
    two_endpoint_provider, small_bbox, caplog
):
    """Provider must log 'Overpass attempt N/M' for each endpoint tried."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.ConnectionError("refused"),
    ):
        with pytest.raises(NetworkDownloadError):
            with caplog.at_level(logging.INFO, logger="accessroute.graph.provider"):
                two_endpoint_provider.get_pedestrian_network(small_bbox)

    log_text = caplog.text
    assert "Overpass attempt 1/2" in log_text
    assert "Overpass attempt 2/2" in log_text


def test_logs_endpoint_failure_reason(two_endpoint_provider, small_bbox, caplog):
    """Provider must log the failure reason for each failed endpoint."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=req_exc.ConnectionError("refused"),
    ):
        with pytest.raises(NetworkDownloadError):
            with caplog.at_level(logging.WARNING, logger="accessroute.graph.provider"):
                two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert "Overpass endpoint failed" in caplog.text


def test_logs_success_endpoint(
    two_endpoint_provider, small_bbox, synthetic_multidigraph, caplog
):
    """Provider must log which endpoint succeeded."""
    with patch(
        "osmnx.graph_from_bbox",
        side_effect=[req_exc.ConnectionError("refused"), synthetic_multidigraph],
    ):
        with caplog.at_level(logging.INFO, logger="accessroute.graph.provider"):
            two_endpoint_provider.get_pedestrian_network(small_bbox)

    assert "Overpass acquisition succeeded" in caplog.text
    assert "secondary.example.com" in caplog.text


# ---------------------------------------------------------------------------
# 11. Domain exception hierarchy preserved (regression from previous fix)
# ---------------------------------------------------------------------------

def test_no_pedestrian_network_is_graph_acquisition_error(two_endpoint_provider, small_bbox):
    with patch("osmnx.graph_from_bbox", side_effect=InsufficientResponseError("empty")):
        with pytest.raises(GraphAcquisitionError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)


def test_network_download_is_graph_acquisition_error(two_endpoint_provider, small_bbox):
    with patch("osmnx.graph_from_bbox", side_effect=req_exc.ConnectionError("refused")):
        with pytest.raises(GraphAcquisitionError):
            two_endpoint_provider.get_pedestrian_network(small_bbox)


# ---------------------------------------------------------------------------
# 12. Synthetic provider still works (no external calls)
# ---------------------------------------------------------------------------

def test_synthetic_provider_unaffected_by_failover_logic(small_bbox):
    """SyntheticGraphProvider must continue to work without any Overpass calls."""
    provider = SyntheticGraphProvider()
    G = provider.get_pedestrian_network(small_bbox)
    assert isinstance(G, nx.MultiDiGraph)
    assert len(G.nodes) > 0


# ---------------------------------------------------------------------------
# 13. Mixed failure modes — first two infra failures, third succeeds
# ---------------------------------------------------------------------------

def test_two_infra_failures_then_success(three_endpoint_provider, small_bbox, synthetic_multidigraph):
    """Two infrastructure failures then a successful third endpoint."""
    side_effects = [
        req_exc.ConnectionError("refused"),
        req_exc.Timeout("timed out"),
        synthetic_multidigraph,
    ]
    with patch("osmnx.graph_from_bbox", side_effect=side_effects) as mock_gbbox:
        G = three_endpoint_provider.get_pedestrian_network(small_bbox)

    assert isinstance(G, nx.MultiDiGraph)
    assert mock_gbbox.call_count == 3
