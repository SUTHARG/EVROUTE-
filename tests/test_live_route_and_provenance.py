"""Focused regression tests for live route planning, provenance classification,
Open Charge Map search coverage, and returning all corridor stations.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from core.models import Station
from ingest.station_providers import OpenChargeMapProvider
from ingest.stations import compute_data_provenance

client = TestClient(app)


# ==============================================================================
# 1. Provenance Classification Tests
# ==============================================================================

def test_provenance_open_data_providers_for_ocm_and_osm():
    """Live OCM and OSM stations must be labeled 'open_data_providers', never 'manual_unverified' or 'synthetic'."""
    ocm_station = Station(
        id="ocm_12345",
        name="Highway Fast Charger",
        lat=18.75,
        lon=73.40,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        source="ocm",
        verified=False,
    )
    osm_station = Station(
        id="osm_67890",
        name="Plaza EV Station",
        lat=18.70,
        lon=73.50,
        operator="Zeon",
        max_kw=50.0,
        connector_types=["CCS2"],
        source="osm",
        verified=False,
    )

    prov_ocm = compute_data_provenance([ocm_station], metadata={"synthetic": False})
    assert prov_ocm == "open_data_providers", f"Expected 'open_data_providers', got '{prov_ocm}'"

    prov_mixed = compute_data_provenance([ocm_station, osm_station], metadata={"synthetic": False})
    assert prov_mixed == "open_data_providers"


def test_provenance_verified_only_for_policy_compliant_stations():
    """Do not call a source verified unless it satisfies the project's verification policy."""
    # OCM station with verified=False is NOT verified
    ocm_station = Station(
        id="ocm_1",
        name="OCM Charger",
        lat=18.75,
        lon=73.40,
        operator="Tata Power",
        max_kw=50.0,
        connector_types=["CCS2"],
        source="ocm",
        verified=False,
    )
    assert compute_data_provenance([ocm_station]) == "open_data_providers"

    # User-verified CSV station with source='verified' and verified=True
    verified_st = Station(
        id="verified_1",
        name="Verified Hub",
        lat=18.75,
        lon=73.40,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        source="verified",
        verified=True,
        source_url="https://example.com/proof",
        checked_on="2026-10-18",
    )
    assert compute_data_provenance([verified_st]) == "verified"


def test_provenance_synthetic_not_applied_to_api_data():
    """Live API data must never be labeled synthetic."""
    st = Station(
        id="ocm_2",
        name="Live Charger",
        lat=18.8,
        lon=73.3,
        operator="Statiq",
        max_kw=120.0,
        connector_types=["CCS2"],
        source="ocm",
        verified=False,
    )
    assert compute_data_provenance([st], metadata={"synthetic": False}) == "open_data_providers"

    # Truly synthetic station
    synth_st = Station(
        id="synth_1",
        name="Synthetic Charger",
        lat=18.8,
        lon=73.3,
        operator="Synthetic Network",
        max_kw=50.0,
        connector_types=["CCS2"],
        source="synthetic",
        verified=False,
    )
    assert compute_data_provenance([synth_st]) == "synthetic"
    assert compute_data_provenance([], metadata={"synthetic": True}) == "synthetic"


# ==============================================================================
# 2. OCM Provider Coverage & Limits Tests
# ==============================================================================

def test_ocm_sampling_covers_origin_to_destination():
    """OCM sample points must span the route from origin to destination without skipping."""
    provider = OpenChargeMapProvider(api_key="test_dummy_key_12345")

    # Mock route coordinates along Mumbai -> Pune
    route_coords = [(18.9388 + i * 0.001, 72.8354 + i * 0.001) for i in range(100)]
    api_tracker: dict[str, int] = {}
    failed_tracker: list[str] = []

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        # Bypass disk cache
        provider.cache.get = MagicMock(return_value=None)
        provider.cache.set = MagicMock()

        provider.fetch_stations(
            route_coords=route_coords,
            bbox=(18.5, 72.8, 19.0, 73.9),
            api_tracker=api_tracker,
            failed_tracker=failed_tracker,
        )

        assert mock_get.called
        calls = mock_get.call_args_list

        # First call should be at origin
        first_lat = calls[0].kwargs["params"]["latitude"]
        first_lon = calls[0].kwargs["params"]["longitude"]
        assert round(first_lat, 4) == round(route_coords[0][0], 4)
        assert round(first_lon, 4) == round(route_coords[0][1], 4)

        # Last call should be at destination
        last_lat = calls[-1].kwargs["params"]["latitude"]
        last_lon = calls[-1].kwargs["params"]["longitude"]
        assert round(last_lat, 4) == round(route_coords[-1][0], 4)
        assert round(last_lon, 4) == round(route_coords[-1][1], 4)

        # Maxresults must be 100 for maximum API coverage
        for c in calls:
            assert c.kwargs["params"]["maxresults"] == 100
            # Header must have X-API-Key and params must NOT have key
            assert "X-API-Key" in c.kwargs["headers"]
            assert "key" not in c.kwargs["params"]


def test_ocm_result_cap_tracking_and_reporting():
    """When OCM returns 100 stations for a sample, report the result cap in stats without hiding it."""
    provider = OpenChargeMapProvider(api_key="test_dummy_key_12345")
    route_coords = [(18.9, 72.8), (18.5, 73.8)]
    api_tracker: dict[str, int] = {}
    failed_tracker: list[str] = []

    # Fake 100 items returned
    fake_100 = [{"ID": i, "AddressInfo": {"Latitude": 18.9, "Longitude": 72.8, "Title": f"St {i}"}} for i in range(100)]

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_100
        mock_get.return_value = mock_resp

        provider.cache.get = MagicMock(return_value=None)
        provider.cache.set = MagicMock()

        stations = provider.fetch_stations(
            route_coords=route_coords,
            bbox=(18.5, 72.8, 19.0, 73.9),
            api_tracker=api_tracker,
            failed_tracker=failed_tracker,
        )

        assert len(stations) == 100
        assert api_tracker.get("ocm_cap_reached_samples", 0) > 0
        assert any("result cap (100) reached" in msg for msg in failed_tracker)


# ==============================================================================
# 3. Live Route Planning vs Synthetic Isolation
# ==============================================================================

def test_live_mumbai_pune_planning():
    """Planning the live Mumbai->Pune corridor uses live provider data with open_data_providers provenance."""
    payload = {
        "snapshot_id": "corridor_18.939_72.835_18.52_73.857",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp = client.post("/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()

    assert plan["feasible"] is True
    assert plan["synthetic"] is False
    assert plan["data_provenance"] == "open_data_providers"
    assert len(plan["corridor_stations"]) > 0

    # Every station in the corridor is returned
    for st in plan["corridor_stations"]:
        assert st["source"] in ("ocm", "osm", "google_places", "verified_manual")


def test_live_delhi_agra_planning():
    """Planning the live Delhi->Agra corridor uses live provider data with open_data_providers provenance."""
    # Test with Hyundai Ioniq 5 (capable of bridging 178km corridor without CCS2 stops)
    payload_feasible = {
        "snapshot_id": "corridor_28.614_77.209_27.177_78.008",
        "car_id": "hyundai_ioniq_5",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp = client.post("/plan", json=payload_feasible)
    assert resp.status_code == 200
    plan = resp.json()

    assert plan["feasible"] is True
    assert plan["synthetic"] is False
    assert plan["data_provenance"] == "open_data_providers"
    assert len(plan["corridor_stations"]) == 54

    # Type 2 stations on the corridor can support the Nexon at a realistic AC rate.
    payload_ac_route = {
        "snapshot_id": "corridor_28.614_77.209_27.177_78.008",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp_ac = client.post("/plan", json=payload_ac_route)
    assert resp_ac.status_code == 200
    plan_ac = resp_ac.json()
    assert plan_ac["feasible"] is True
    assert plan_ac["synthetic"] is False
    assert plan_ac["data_provenance"] == "open_data_providers"
    assert plan_ac["stops"]
    assert all(stop["charging_mode"] == "ac" for stop in plan_ac["stops"])
    assert all(stop["charging_power_kw"] == 7.2 for stop in plan_ac["stops"])


def test_corridor_stations_distinguished_from_chosen_stops():
    """Every corridor station is returned in corridor_stations, even if not chosen as a charging stop."""
    payload = {
        "snapshot_id": "corridor_18.939_72.835_18.52_73.857",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp = client.post("/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()

    corridor_stations = plan["corridor_stations"]
    stops = plan["stops"]

    # There should be more corridor stations than chosen stops
    assert len(corridor_stations) >= len(stops)

    chosen_ids = {s["station_id"] for s in stops}
    corridor_ids = {s["id"] for s in corridor_stations}
    assert chosen_ids.issubset(corridor_ids)


def test_saved_snapshot_provenance_flag():
    """Saved disk snapshots must return is_live_build=False, clearly distinguishing them from live builds."""
    # 1. Saved real snapshot on disk
    payload_saved = {
        "snapshot_id": "corridor_18.939_72.835_18.52_73.857",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp_saved = client.post("/plan", json=payload_saved)
    assert resp_saved.status_code == 200
    plan_saved = resp_saved.json()
    assert plan_saved["is_live_build"] is False
    assert plan_saved["synthetic"] is False

    # 2. Synthetic demo snapshot
    payload_synth = {
        "snapshot_id": "default_mumbai_pune",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp_synth = client.post("/plan", json=payload_synth)
    assert resp_synth.status_code == 200
    plan_synth = resp_synth.json()
    assert plan_synth["is_live_build"] is False
    assert plan_synth["synthetic"] is True


def test_live_build_provenance_flag():
    """Corridors built via live route building must be recorded and returned with is_live_build=True."""
    from api.main import _LIVE_BUILT_SNAPSHOTS

    test_live_snap_id = "test_live_snapshot_123"
    _LIVE_BUILT_SNAPSHOTS.add(test_live_snap_id)

    # Check snapshot summary details endpoint
    with patch("api.main.get_snapshot") as mock_get_snap:
        mock_snap = MagicMock()
        mock_snap.id = test_live_snap_id
        mock_snap.source_name = "Origin City"
        mock_snap.destination_name = "Dest City"
        mock_snap.created_at = "2026-10-21T00:00:00Z"
        mock_snap.nodes = []
        mock_snap.edges = []
        mock_snap.stations = []
        mock_snap.metadata = {"is_live_build": True}
        mock_get_snap.return_value = mock_snap

        resp = client.get(f"/snapshots/{test_live_snap_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_live_build"] is True

