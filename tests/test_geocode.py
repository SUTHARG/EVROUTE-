"""Tests for geocode search proxy, rate limiting, and candidate response formatting."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from ingest.cache import DiskCache
from ingest.geocode import search_geocode

client = TestClient(app)

SAMPLE_NOMINATIM_FIXTURE = [
    {
        "place_id": 12345,
        "licence": "Data © OpenStreetMap contributors",
        "osm_type": "relation",
        "osm_id": 78910,
        "lat": "28.6138954",
        "lon": "77.2090057",
        "display_name": "New Delhi, Delhi, India",
        "class": "boundary",
        "type": "administrative",
        "importance": 0.85,
    },
    {
        "place_id": 54321,
        "licence": "Data © OpenStreetMap contributors",
        "osm_type": "node",
        "osm_id": 11223,
        "lat": "28.6500",
        "lon": "77.2300",
        "display_name": "Delhi, North Delhi, Delhi, India",
        "class": "place",
        "type": "city",
        "importance": 0.75,
    },
]


def test_nominatim_search_parsing(tmp_path):
    """Test that search_geocode correctly parses Nominatim JSON into candidate dicts."""
    test_cache = DiskCache("test_geocode", cache_dir=tmp_path)

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_NOMINATIM_FIXTURE
        mock_get.return_value = mock_resp

        candidates = search_geocode("Delhi", limit=5, allow_network=True, cache=test_cache)

        assert len(candidates) == 2
        assert candidates[0]["label"] == "New Delhi, Delhi, India"
        assert abs(candidates[0]["lat"] - 28.61389) < 1e-4
        assert abs(candidates[0]["lon"] - 77.20900) < 1e-4

        # Verify caching
        cached_candidates = search_geocode("Delhi", limit=5, allow_network=False, cache=test_cache)
        assert len(cached_candidates) == 2


def test_geocode_offline_fallback(tmp_path):
    """Test that search_geocode falls back to offline dictionary when network is disabled."""
    test_cache = DiskCache("test_geocode_offline", cache_dir=tmp_path)
    candidates = search_geocode("Mumbai", limit=5, allow_network=False, cache=test_cache)

    assert len(candidates) >= 1
    assert "Mumbai" in candidates[0]["label"]
    assert abs(candidates[0]["lat"] - 18.9388) < 1e-3


def test_geocode_api_endpoint():
    """Test GET /geocode endpoint returns up to limit candidates."""
    resp = client.get("/geocode", params={"q": "Pune", "limit": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "lat" in data[0]
    assert "lon" in data[0]
    assert "label" in data[0]
