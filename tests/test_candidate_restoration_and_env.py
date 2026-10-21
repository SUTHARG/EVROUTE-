"""Regression tests for candidate restoration upon filtering failure and configuration integrity."""

from pathlib import Path
from unittest.mock import MagicMock

import requests

from core.models import Car, CorridorSnapshot, RoadEdge, RoadNode, Station, Trip
from core.planner import EVPlanner
from ingest.station_providers import OpenChargeMapProvider


def test_candidate_restoration_prevents_false_infeasibility():
    """Verify that when greedy filtering drops a necessary charger due to score,
    the planner restores candidate stations and returns a feasible road plan.
    """
    # 3-node road corridor: Node 0 -> Node 1 (40 km) -> Node 2 (50 km). Total = 90 km.
    nodes = {
        0: RoadNode(id=0, lat=19.0, lon=73.0, elevation_m=10.0),
        1: RoadNode(id=1, lat=19.36, lon=73.0, elevation_m=10.0),
        2: RoadNode(id=2, lat=19.81, lon=73.0, elevation_m=10.0),
    }
    edges = [
        RoadEdge(u=0, v=1, length_m=40000.0, time_s=1600.0, energy_kwh=6.0),
        RoadEdge(u=1, v=2, length_m=50000.0, time_s=2000.0, energy_kwh=7.5),
    ]

    # Vehicle with 10 kWh battery:
    # effective range ~55 km (cannot bridge 90 km directly, but can do 40 km then 50 km).
    car = Car(
        id="test_car",
        name="Test EV",
        battery_kwh=10.0,
        usable_fraction=1.0,
        consumption_kwh_per_km=0.15,
        real_range_km=65.0,
        mass_kg=1200.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.0,
        max_dc_kw=50.0,
        supported_connectors=["CCS2"],
    )

    low_score_charger = Station(
        id="st_bridge",
        name="Essential Intermediate Charger",
        lat=19.36,
        lon=73.0,
        operator="Local",
        max_kw=30.0,
        connector_types=["CCS2"],
        reliability=0.50,
        amenities={},
        amenity_score=0.0,  # Score ~0.25 (below threshold 0.60)
        source="verified_manual",
        source_url="https://example.com/st",
        fetched_at="2026-10-21T00:00:00Z",
    )

    snapshot = CorridorSnapshot(
        id="snap_candidate_test",
        created_at="2026-10-21T00:00:00Z",
        source_name="Origin",
        destination_name="Destination",
        nodes=nodes,
        edges=edges,
        stations=[low_score_charger],
        source_node_id=0,
        destination_node_id=2,
    )

    trip = Trip(
        snapshot_id="snap_candidate_test",
        car_id="test_car",
        start_soc=1.0,
        reserve_soc=0.10,
        comfort_weight_lambda=1.0,
    )

    planner = EVPlanner()

    # Plan with enable_filter=True and high score threshold (0.60)
    # The filter will initially drop low_score_charger if evaluated strictly by score.
    # The reduced graph search with filtered chargers fails, triggering candidate restoration!
    plan = planner.plan(
        snapshot=snapshot,
        trip=trip,
        car=car,
        enable_filter=True,
        filter_score_threshold=0.60,
    )

    # Candidate restoration MUST make the trip feasible!
    assert plan.feasible is True
    assert len(plan.stops) == 1
    assert plan.stops[0].station_id == "st_bridge"


def test_requirements_and_pyproject_dependencies_match():
    """Ensure all core runtime dependencies in pyproject.toml are present in requirements.txt."""
    req_file = Path("requirements.txt")
    assert req_file.exists(), "requirements.txt manifest must exist"

    req_text = req_file.read_text(encoding="utf-8")
    assert "python-dotenv" in req_text
    assert "fastapi" in req_text
    assert "pydantic" in req_text
    assert "networkx" in req_text


def test_ocm_key_header_only_never_in_url():
    """Verify OpenChargeMapProvider sends API key strictly in the X-API-Key header, never in query string."""
    provider = OpenChargeMapProvider(api_key="test-secret-key-12345")
    assert provider.effective_api_key == "test-secret-key-12345"

    # Bypass cache for test
    provider.cache = MagicMock()
    provider.cache.get.return_value = None

    # Distinct route coords so it creates sample points
    route_coords = [(18.90 + i * 0.05, 72.80 + i * 0.05) for i in range(20)]
    bbox = (18.5, 72.8, 19.9, 73.8)

    captured_calls = []

    def mock_get(url, **kwargs):
        captured_calls.append({"url": url, "headers": kwargs.get("headers", {})})
        m = requests.models.Response()
        m.status_code = 200
        m._content = b"[]"
        return m

    orig_get = requests.get
    requests.get = mock_get
    try:
        api_tracker = {}
        failed_tracker = []
        provider.fetch_stations(route_coords, bbox, api_tracker, failed_tracker)

        assert len(captured_calls) > 0
        for call in captured_calls:
            # Key MUST NOT appear anywhere in the request URL!
            assert "test-secret-key-12345" not in call["url"]
            assert "key=" not in call["url"].lower()
            # Key MUST be present in X-API-Key header
            assert call["headers"].get("X-API-Key") == "test-secret-key-12345"
    finally:
        requests.get = orig_get
