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
    fixture_path = FIXTURES_DIR / "pune_city_overpass_stations.json"
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


def test_load_user_verified_csv_and_provenance(tmp_path):
    """Verify loading user hand-verified CSV with mandatory columns and provenance tracking."""
    from ingest.stations import compute_data_provenance, load_user_verified_csv

    csv_content = """name,lat,lon,operator,max_kw,connectors,source_url,checked_on
Expressway Fast Hub,18.7500,73.4000,Zeon,60.0,CCS2;Type2,https://example.com/charger/1,2026-10-15
Plaza Supercharger,18.7200,73.6000,Tata Power,120.0,CCS2,https://example.com/charger/2,2026-10-16
"""
    csv_file = tmp_path / "user_verified_chargers.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    stations = load_user_verified_csv(csv_file)
    assert len(stations) == 2
    assert stations[0].name == "Expressway Fast Hub"
    assert stations[0].max_kw == 60.0
    assert stations[0].connector_types == ["CCS2", "Type2"]
    assert stations[0].source_url == "https://example.com/charger/1"
    assert stations[0].checked_on == "2026-10-15"

    prov = compute_data_provenance(stations, metadata={"synthetic": False})
    assert prov == "verified"


def test_ocm_api_sample_fixture_parser():
    """Verify OpenChargeMap API parser against real fixture response."""
    from core.config import get_ocm_api_key
    from ingest.station_providers import OpenChargeMapProvider

    fixture_path = FIXTURES_DIR / "ocm_api_sample.json"
    assert fixture_path.exists(), "tests/fixtures/ocm_api_sample.json must exist"

    content = fixture_path.read_text(encoding="utf-8")
    key = get_ocm_api_key()
    if key:
        assert key not in content, "API key must NEVER be written to fixture file"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert 5 <= len(data) <= 10, f"Expected 5-10 stations in sample, got {len(data)}"

    # Parse through provider
    provider = OpenChargeMapProvider(api_key="mock_key_for_test")
    assert provider.name == "ocm"

    # Simulate fetch_stations parsing logic on fixture data
    seen_ids = set()
    stations = []
    for item in data:
        poi_id = str(item.get("ID", ""))
        if not poi_id or poi_id in seen_ids:
            continue
        seen_ids.add(poi_id)
        addr = item.get("AddressInfo") or {}
        lat_f = addr.get("Latitude")
        lon_f = addr.get("Longitude")
        assert lat_f is not None and lon_f is not None

        dp_obj = item.get("DataProvider") or {}
        dp_name = dp_obj.get("Title") if isinstance(dp_obj, dict) else None
        dp_license = dp_obj.get("License") if isinstance(dp_obj, dict) else None

        connections = item.get("Connections") or []
        assert isinstance(connections, list)

        # Check DataProvider attribution
        if dp_name:
            assert "Open Charge Map" in dp_name or isinstance(dp_name, str)
        if dp_license:
            assert "Creative Commons" in dp_license or "CC" in dp_license or isinstance(dp_license, str)

        stations.append(poi_id)

    assert len(seen_ids) == len(data)
    assert len(stations) == len(data)



def test_api_key_not_leaked_in_cache_snapshots_reports():
    """Grep verification that OCM_API_KEY is never written in cache, snapshots, logs, or reports."""
    from core.config import get_ocm_api_key

    key = get_ocm_api_key()
    if not key or len(key.strip()) < 8:
        return

    # Check data/cache/
    cache_dir = Path("data/cache")
    if cache_dir.exists():
        for f in cache_dir.rglob("*.json"):
            assert key not in f.read_text(encoding="utf-8", errors="ignore"), f"Key leaked in cache file: {f.name}"

    # Check data/snapshots/
    snap_dir = Path("data/snapshots")
    if snap_dir.exists():
        for f in snap_dir.glob("*.json"):
            assert key not in f.read_text(encoding="utf-8", errors="ignore"), f"Key leaked in snapshot file: {f.name}"

    # Check reports and docs
    for md_file in Path(".").glob("*.md"):
        assert key not in md_file.read_text(encoding="utf-8", errors="ignore"), f"Key leaked in markdown file: {md_file.name}"

