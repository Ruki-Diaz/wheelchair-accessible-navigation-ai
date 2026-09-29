"""Unit tests for Geocoding abstractions, providers, and caching."""

from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

from accessroute.geocoding.base import GeocodeCandidate, GeocoderProvider
from accessroute.geocoding.cache import GeocodingCache
from accessroute.geocoding.photon import PhotonGeocoderProvider
from accessroute.geocoding.nominatim import NominatimGeocoderProvider


def test_geocode_candidate_serialization():
    cand = GeocodeCandidate(
        display_name="Flinders Street Station, Melbourne",
        latitude=-37.8183,
        longitude=144.9671,
        place_type="station",
        street="Flinders Street",
        city="Melbourne",
        state="Victoria",
        country="Australia",
        postcode="3000",
        extent=(-37.819, 144.965, -37.817, 144.969),
    )
    d = cand.to_dict()
    assert d["display_name"] == "Flinders Street Station, Melbourne"
    assert d["latitude"] == -37.8183
    assert d["extent"] == (-37.819, 144.965, -37.817, 144.969)

    cand_back = GeocodeCandidate.from_dict(d)
    assert cand_back.display_name == cand.display_name
    assert cand_back.latitude == cand.latitude
    assert cand_back.extent == cand.extent


def test_geocoding_cache_memory():
    cache = GeocodingCache(db_path=":memory:")
    cands = [
        GeocodeCandidate(display_name="Site A", latitude=10.0, longitude=20.0),
        GeocodeCandidate(display_name="Site B", latitude=10.1, longitude=20.1),
    ]

    # Cache miss initially
    assert cache.get("test query") is None

    # Cache set and retrieve
    cache.set("test query", cands)
    cached = cache.get("test query")
    assert cached is not None
    assert len(cached) == 2
    assert cached[0].display_name == "Site A"
    assert cached[1].display_name == "Site B"


def test_photon_geocoder_mocked():
    cache = GeocodingCache(db_path=":memory:")
    provider = PhotonGeocoderProvider(cache=cache)

    mock_response = {
        "features": [
            {
                "geometry": {"coordinates": [144.9671, -37.8183]},
                "properties": {
                    "name": "Flinders Street Station",
                    "city": "Melbourne",
                    "state": "Victoria",
                    "country": "Australia",
                    "osm_value": "station",
                },
            }
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.read.return_value = json_str = str(mock_response).replace("'", '"').encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_ctx

        results = provider.search("Flinders Street")
        assert len(results) == 1
        assert "Flinders Street Station" in results[0].display_name
        assert results[0].latitude == -37.8183
        assert results[0].longitude == 144.9671

        # Second query should hit cache (urlopen not called again)
        mock_urlopen.reset_mock()
        cached_results = provider.search("Flinders Street")
        assert len(cached_results) == 1
        mock_urlopen.assert_not_called()


def test_geocoder_empty_query():
    provider = PhotonGeocoderProvider(cache=GeocodingCache(db_path=":memory:"))
    assert provider.search("") == []
    assert provider.search("   ") == []
