"""Unit tests for stop position projection consistency, row rejection, name cleaning, and sources health."""

from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from core.models import CorridorSnapshot, RoadEdge, RoadNode, Station, Trip
from core.planner import EVPlanner
from ingest.ocm_snapshot import clean_station_name
from ingest.station_providers import ManualVerifiedCSVProvider

client = TestClient(app)


def test_station_name_cleaning():
    """Verify that (KM 98), (km 36), etc. are stripped from station names."""
    raw1 = "Tata Power - Khalapur Food Plaza (KM 36)"
    raw2 = "Statiq - Talegaon Expressway Fuel Stop (KM 98)"
    raw3 = "ChargeZone - Mathura Toll Food Plaza (km 115)"
    raw4 = "Normal Charger"

    assert clean_station_name(raw1) == "Tata Power - Khalapur Food Plaza"
    assert clean_station_name(raw2) == "Statiq - Talegaon Expressway Fuel Stop"
    assert clean_station_name(raw3) == "ChargeZone - Mathura Toll Food Plaza"
    assert clean_station_name(raw4) == "Normal Charger"


def test_verified_manual_csv_provider_rejects_missing_fields(tmp_path: Path):
    """Verify loader rejects rows without non-empty source_url and checked_on."""
    csv_file = tmp_path / "stations.csv"
    csv_file.write_text(
        "name,lat,lon,operator,max_kw,connectors,source_url,checked_on\n"
        "Valid Hub,18.79,73.29,Tata,60,CCS2,https://example.com/valid,2026-03-01\n"
        "No URL,18.78,73.28,Jio,60,CCS2,,2026-03-01\n"
        "No Date,18.77,73.27,Statiq,60,CCS2,https://example.com/nodate,\n"
        "Both Empty,18.76,73.26,Zeon,60,CCS2,,\n",
        encoding="utf-8",
    )

    provider = ManualVerifiedCSVProvider(csv_path=csv_file)
    api_tracker: dict[str, int] = {}
    failed: list[str] = []
    bbox = (18.0, 72.0, 19.5, 74.5)
    stations = provider.fetch_stations([], bbox, api_tracker, failed)

    assert len(stations) == 1
    assert stations[0].name == "Valid Hub"
    assert stations[0].source_url == "https://example.com/valid"
    assert stations[0].checked_on == "2026-03-01"


def test_health_sources_endpoint():
    """Verify /health/sources returns provider dictionary without secrets."""
    response = client.get("/health/sources")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    providers = data["providers"]
    assert "verified_manual" in providers
    assert "google_places" in providers
    assert "ocm_api" in providers
    assert "ocm_snapshot" in providers
    assert "osm_overpass" in providers
    # Providers must be boolean statuses, never secrets
    for status in providers.values():
        assert isinstance(status, bool)


def test_no_stations_infeasibility_message():
    """When no stations exist along corridor, planner must return explicit infeasibility message."""
    planner = EVPlanner()
    empty_snap = CorridorSnapshot(
        id="empty_corridor",
        created_at="2026-03-01T00:00:00Z",
        source_name="Delhi",
        destination_name="Agra",
        nodes={
            0: RoadNode(id=0, lat=28.61, lon=77.20, elevation_m=200.0),
            1: RoadNode(id=1, lat=27.17, lon=78.00, elevation_m=170.0),
        },
        edges=[
            RoadEdge(u=0, v=1, length_m=200000.0, time_s=7200.0, elevation_gain_m=-30.0, energy_kwh=30.0),
        ],
        stations=[],
        metadata={"synthetic": False, "data_provenance": "none"},
    )
    from core.models import PRESET_CARS

    car = PRESET_CARS["tata_nexon_ev_lr"]
    trip = Trip(
        snapshot_id=empty_snap.id,
        start_soc=0.45,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
    )
    plan = planner.plan(empty_snap, car, trip)

    assert plan.feasible is False
    assert len(plan.stops) == 0
    assert plan.infeasibility_reason == "No verified charging stations found for this route"


def test_stop_projected_route_distance_consistency():
    """Verify that stop.route_distance_km matches the station's projected distance along route."""
    planner = EVPlanner()
    # 3 nodes: 0 -> 1 (50 km) -> 2 (50 km). Station attaches to node 1 at 50 km.
    snap = CorridorSnapshot(
        id="test_projection_snap",
        created_at="2026-03-01T00:00:00Z",
        source_name="Origin",
        destination_name="Destination",
        nodes={
            0: RoadNode(id=0, lat=18.0, lon=72.0, elevation_m=0.0),
            1: RoadNode(id=1, lat=18.4, lon=72.4, elevation_m=0.0),
            2: RoadNode(id=2, lat=18.8, lon=72.8, elevation_m=0.0),
        },
        edges=[
            RoadEdge(u=0, v=1, length_m=50000.0, time_s=1800.0, elevation_gain_m=0.0, energy_kwh=6.0),
            RoadEdge(u=1, v=2, length_m=50000.0, time_s=1800.0, elevation_gain_m=0.0, energy_kwh=6.0),
        ],
        stations=[
            Station(
                id="st_1",
                name="Midpoint Hub",
                lat=18.401,
                lon=72.401,
                operator="FastCharge",
                max_kw=60.0,
                charger_count=2,
                connector_types=["CCS2"],
                source="verified_manual",
                verified=True,
                road_node_id=1,
                route_distance_km=50.0,
                detour_distance_m=200.0,
                detour_time_s=30.0,
                detour_energy_kwh=0.04,
            )
        ],
        metadata={"synthetic": False, "data_provenance": "verified"},
    )
    from core.models import PRESET_CARS

    car = PRESET_CARS["tata_tiago_ev"]
    trip = Trip(
        snapshot_id=snap.id,
        start_soc=0.45,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
    )
    plan = planner.plan(snap, car, trip)

    assert plan.feasible is True
    assert len(plan.stops) == 1
    stop = plan.stops[0]
    # Stop route_distance_km must match the station's projected route distance
    assert abs(stop.route_distance_km - 50.0) < 0.1
    # Verify the station in snapshot matches
    assert abs(snap.stations[0].route_distance_km - 50.0) < 0.1


def test_verified_manual_csv_empty_fields_use_documented_defaults(tmp_path: Path):
    """When max_kw or connectors are empty in CSV, loader must use documented defaults and flag assumed."""
    csv_file = tmp_path / "stations_empty_fields.csv"
    csv_file.write_text(
        "name,lat,lon,operator,max_kw,connectors,source_url,checked_on\n"
        "Empty Power,18.79,73.29,Tata,,CCS2,https://example.com/p1,2026-03-01\n"
        "Empty Connector,18.78,73.28,Jio,60,,https://example.com/p2,2026-03-01\n"
        "Both Empty,18.77,73.27,Statiq,,,https://example.com/p3,2026-03-01\n"
        "Fully Specified,18.76,73.26,Zeon,120,CCS2,https://example.com/p4,2026-03-01\n",
        encoding="utf-8",
    )

    provider = ManualVerifiedCSVProvider(csv_path=csv_file)
    api_tracker: dict[str, int] = {}
    failed: list[str] = []
    bbox = (18.0, 72.0, 19.5, 74.5)
    stations = provider.fetch_stations([], bbox, api_tracker, failed)

    assert len(stations) == 4

    # Empty Power: max_kw assumed 50.0, power_assumed=True, connector_assumed=False
    st1 = next(s for s in stations if s.name == "Empty Power")
    assert st1.max_kw == 50.0
    assert st1.power_assumed is True
    assert st1.connector_assumed is False

    # Empty Connector: connectors assumed ["CCS2"], power_assumed=False, connector_assumed=True
    st2 = next(s for s in stations if s.name == "Empty Connector")
    assert st2.max_kw == 60.0
    assert st2.connector_types == ["CCS2"]
    assert st2.power_assumed is False
    assert st2.connector_assumed is True

    # Both Empty: both assumed True
    st3 = next(s for s in stations if s.name == "Both Empty")
    assert st3.max_kw == 50.0
    assert st3.connector_types == ["CCS2"]
    assert st3.power_assumed is True
    assert st3.connector_assumed is True

    # Fully Specified: both assumed False
    st4 = next(s for s in stations if s.name == "Fully Specified")
    assert st4.max_kw == 120.0
    assert st4.connector_types == ["CCS2"]
    assert st4.power_assumed is False
    assert st4.connector_assumed is False


def test_startup_csv_inspection(tmp_path: Path):
    """Verify inspect_verified_csv_at_startup reports valid vs rejected rows count."""
    csv_file = tmp_path / "test_startup.csv"
    csv_file.write_text(
        "name,lat,lon,operator,max_kw,connectors,source_url,checked_on\n"
        "Valid 1,18.79,73.29,Tata,50,CCS2,https://example.com/1,2026-03-01\n"
        "Missing URL,18.78,73.28,Jio,50,CCS2,,2026-03-01\n"
        "Missing Date,18.77,73.27,Statiq,50,CCS2,https://example.com/2,\n"
        "Valid 2,18.76,73.26,Zeon,50,CCS2,https://example.com/3,2026-03-01\n",
        encoding="utf-8",
    )

    valid_count, rejected_count = ManualVerifiedCSVProvider.inspect_verified_csv_at_startup(csv_file)
    assert valid_count == 2
    assert rejected_count == 2


def test_ocm_data_provider_and_license_extraction(tmp_path: Path):
    """Verify OCMSnapshotProvider extracts DataProvider title and license per POI under CC BY 4.0."""
    import json

    from ingest.ocm_snapshot import OCMSnapshotProvider

    sample_poi = [
        {
            "ID": 101,
            "AddressInfo": {
                "Title": "Test India Charger",
                "Latitude": 18.52,
                "Longitude": 73.85,
                "ISOCode": "IN",
            },
            "DataProvider": {
                "Title": "Open Charge Map Contributors",
                "License": "CC BY 4.0",
                "WebsiteURL": "https://openchargemap.org",
            },
            "Connections": [
                {
                    "ConnectionType": {"Title": "CCS (Type 2)"},
                    "PowerKW": 60.0,
                    "Quantity": 2,
                }
            ],
            "StatusType": {"IsOperational": True},
        }
    ]
    sample_file = tmp_path / "sample_poi.json"
    sample_file.write_text(json.dumps(sample_poi), encoding="utf-8")

    provider = OCMSnapshotProvider(snapshot_path=sample_file)
    # Clear class cache
    OCMSnapshotProvider._cached_india_records = None
    OCMSnapshotProvider._spatial_grid = None

    bbox = (18.0, 73.0, 19.0, 74.0)
    route = [(18.52, 73.85)]
    api_tracker: dict[str, int] = {}
    failed: list[str] = []
    stations = provider.fetch_stations(route, bbox, api_tracker, failed)

    assert len(stations) == 1
    st = stations[0]
    assert st.data_provider_name == "Open Charge Map Contributors"
    assert st.data_provider_license == "CC BY 4.0"
    assert st.source == "ocm_snapshot"


