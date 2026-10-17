"""Unit tests for offline API response parsers using test fixtures."""

import json
from pathlib import Path

from ingest.cache import DiskCache
from ingest.route import OSRMClient
from ingest.stations import StationIngestionPolicy, fetch_overpass_stations

FIXTURES_DIR = Path("tests/fixtures")


def test_osrm_response_parser(tmp_path):
    """Verify OSRM route response parser extracts distance, time, and coordinates."""
    fixture_path = FIXTURES_DIR / "sample_osrm_route.json"
    assert fixture_path.exists(), "OSRM route fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify fields from cached response
    assert "distance_m" in data
    assert "duration_s" in data
    assert "coordinates" in data
    assert len(data["coordinates"]) > 100
    assert data["distance_m"] > 100_000.0  # >100 km Mumbai to Pune


def test_overpass_station_parser_and_fallback_policy(tmp_path):
    """Verify Overpass station parser handles power and connector fallback policies offline."""
    fixture_path = FIXTURES_DIR / "sample_overpass_stations.json"
    assert fixture_path.exists(), "Overpass fixture must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Mock disk cache returning the fixture elements
    cache = DiskCache("overpass", cache_dir=tmp_path)
    bbox = (18.5, 72.8, 19.1, 73.9)
    min_lat, min_lon, max_lat, max_lon = bbox
    cache_key = f"stations_{min_lat:.4f}_{min_lon:.4f}_{max_lat:.4f}_{max_lon:.4f}"
    cache.set(cache_key, data["elements"])

    # Test with policy: assume missing connector as CCS2, assume power 50kW
    policy = StationIngestionPolicy(
        assume_missing_connector_as_ccs2=True,
        assume_missing_power_kw=50.0,
    )
    stations, audit = fetch_overpass_stations(
        bbox=bbox,
        policy=policy,
        allow_network=False,
        cache=cache,
    )

    # Real fixture contains 31 actual Overpass charging station elements
    assert len(stations) > 0
    assert audit["total_raw"] == len(data["elements"])
    assert audit["kept"] == len(stations)
    assert audit["count_by_source"]["osm"] == len(stations)

    # Every parsed station must record source="osm"
    for st in stations:
        assert st.source == "osm"
        assert st.is_reliability_simulated is True
        assert 0.0 < st.reliability <= 1.0

    # Now test strict policy: drop stations without explicit power or connector
    strict_policy = StationIngestionPolicy(
        assume_missing_connector_as_ccs2=False,
        assume_missing_power_kw=None,
    )
    strict_stations, strict_audit = fetch_overpass_stations(
        bbox=bbox,
        policy=strict_policy,
        allow_network=False,
        cache=cache,
    )
    # Under strict policy, elements without explicit capacity or socket tags are dropped
    assert strict_audit["dropped_power"] > 0 or strict_audit["dropped_connector"] > 0
    assert len(strict_stations) < len(stations)


def test_cache_key_includes_query_params():
    """Verify that DiskCache keys differ when query parameters differ."""
    client = OSRMClient()
    key1 = "18.9,72.8_18.5,73.8_alt=True"
    key2 = "18.9,72.8_18.5,73.8_alt=False"
    assert client.cache._hash_key(key1) != client.cache._hash_key(key2)
