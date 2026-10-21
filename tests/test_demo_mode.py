"""Unit tests for Route.ev Demo build: 250 km default range, live station providers, and demo mode flags."""

import pytest

from core.config import (
    DEFAULT_RANGE_KM,
    EXCLUDED_2W_3W_CONNECTORS,
    USE_CAR_SPECIFIC_RANGE,
)
from core.energy import REFERENCE_SPEED_KMH, calibrate_crr, edge_energy_kwh
from core.filters import filter_stations_greedy
from core.models import PRESET_CARS, Station, StationAvailability
from ingest.station_providers import (
    ManualVerifiedCSVProvider,
    merge_and_deduplicate_stations,
    normalize_connector_type,
)


def test_default_range_250km_for_all_preset_cars():
    """Verify that for every car preset, full usable battery gives 250 km on flat road within 0.5%."""
    assert DEFAULT_RANGE_KM == 250.0
    assert USE_CAR_SPECIFIC_RANGE is False

    for car_id, car in PRESET_CARS.items():
        # Manufacturer rated real range is preserved
        assert hasattr(car, "real_range_km")
        assert car.real_range_km > 0.0

        # Rated flat-road consumption equals usable / 250 km
        expected_consumption = car.usable_battery_kwh / DEFAULT_RANGE_KM
        assert car.consumption_kwh_per_km == pytest.approx(expected_consumption, rel=1e-5)

        # Calibrate Crr and simulate 250 km driving at reference speed (70 km/h) on flat road (delta_h = 0)
        crr = calibrate_crr(car)
        distance_m = 250_000.0  # 250 km
        speed_mps = REFERENCE_SPEED_KMH / 3.6
        time_s = distance_m / speed_mps

        energy_consumed_kwh = edge_energy_kwh(
            car=car,
            length_m=distance_m,
            time_s=time_s,
            elevation_gain_m=0.0,
            crr=crr,
        )

        # Total energy consumed over 250 km must equal 100% of usable battery within 0.5%
        assert energy_consumed_kwh == pytest.approx(car.usable_battery_kwh, rel=0.005), (
            f"Failed for {car_id}: energy={energy_consumed_kwh}, usable={car.usable_battery_kwh}"
        )


def test_reserve_reduces_plannable_range_accordingly():
    """Verify safety reserve buffer reduces effective plannable range proportionally."""
    for car in PRESET_CARS.values():
        reserve_soc = 0.10  # 10% reserve buffer
        plannable_energy_kwh = car.effective_energy_kwh(reserve_soc=reserve_soc)

        # Plannable energy is (1 - 0.10) = 90% of usable battery
        expected_kwh = 0.90 * car.usable_battery_kwh
        assert plannable_energy_kwh == pytest.approx(expected_kwh, rel=1e-5)

        # Plannable distance is exactly (1 - reserve) * 250 km = 225 km
        km_per_kwh = 1.0 / car.consumption_kwh_per_km
        plannable_distance_km = plannable_energy_kwh * km_per_kwh
        assert plannable_distance_km == pytest.approx(225.0, rel=0.005)


def test_connector_normalization_and_4w_filter():
    """Verify 4-wheeler connector filtering and 2W/3W exclusion rules."""
    # 4-Wheeler standards
    norm, excluded = normalize_connector_type("CCS2")
    assert norm == "CCS2" and not excluded

    norm, excluded = normalize_connector_type("Type 2 Combo")
    assert norm == "CCS2" and not excluded

    norm, excluded = normalize_connector_type("Type 2 (AC)")
    assert norm == "Type 2 (AC)" and not excluded

    norm, excluded = normalize_connector_type("CHAdeMO")
    assert norm == "CHAdeMO" and not excluded

    # 2W/3W standards must be excluded
    for ex in EXCLUDED_2W_3W_CONNECTORS:
        norm, excluded = normalize_connector_type(ex)
        assert excluded is True


def test_unknown_connector_handling_in_routing():
    """Verify unknown connectors are marked connector_unknown and excluded from planning."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    station_unknown = Station(
        id="stat_unknown",
        name="Mystery Charger",
        lat=18.75,
        lon=73.40,
        operator="Independent",
        max_kw=50.0,
        connector_types=["Unknown Connector"],
        connector_unknown=True,
        source="osm",
        reliability=0.85,
    )
    station_ccs2 = Station(
        id="stat_ccs2",
        name="Verified Hub",
        lat=18.75,
        lon=73.40,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        connector_unknown=False,
        source="verified_manual",
        reliability=0.90,
    )

    kept, _dropped, _ = filter_stations_greedy(
        stations=[station_unknown, station_ccs2],
        car=car,
        source_coord=(18.93, 72.83),
        destination_coord=(18.52, 73.85),
    )

    # Station with unknown connector MUST be dropped from planner graph
    kept_ids = {s.id for s in kept}
    assert "stat_ccs2" in kept_ids
    assert "stat_unknown" not in kept_ids


def test_station_deduplication_priority():
    """Verify 100m spatial deduplication prefers verified_manual > google_places > ocm > osm."""
    lat, lon = 18.7525, 73.4089

    st_osm = Station(
        id="osm_1",
        name="OSM Station",
        lat=lat,
        lon=lon,
        operator="OSM Op",
        max_kw=30.0,
        source="osm",
        reliability=0.70,
    )
    st_ocm = Station(
        id="ocm_1",
        name="OCM Station",
        lat=lat + 0.0002,  # ~22m away
        lon=lon,
        operator="OCM Op",
        max_kw=50.0,
        source="ocm",
        reliability=0.80,
    )
    st_google = Station(
        id="gp_1",
        name="Google Places Station",
        lat=lat + 0.0003,  # ~33m away
        lon=lon,
        operator="Google Op",
        max_kw=60.0,
        source="google_places",
        availability=StationAvailability(available=2, total=2, out_of_service=0),
        reliability=0.88,
    )
    st_verified = Station(
        id="verified_1",
        name="Verified Station",
        lat=lat,
        lon=lon,
        operator="Tata Power",
        max_kw=60.0,
        source="verified_manual",
        verified=True,
        reliability=0.92,
    )

    # All 4 stations within 100m: deduplication must keep verified_manual as base
    # and merge live availability from google_places
    deduped = merge_and_deduplicate_stations([st_osm, st_ocm, st_google, st_verified])
    assert len(deduped) == 1
    chosen = deduped[0]
    assert chosen.id == "verified_1"
    assert chosen.source == "verified_manual"
    assert chosen.verified is True
    assert chosen.availability is not None
    assert chosen.availability.available == 2


def test_verified_manual_csv_provider(tmp_path):
    """Verify ManualVerifiedCSVProvider validates source_url and checked_on, rejecting invalid rows."""
    test_csv = tmp_path / "test_stations.csv"
    test_csv.write_text(
        "name,lat,lon,operator,max_kw,connectors,source_url,checked_on\n"
        "Valid Hub,18.80,73.30,Tata,60.0,CCS2,https://example.com/st1,2026-03-01\n"
        "Missing URL Hub,18.81,73.31,Statiq,60.0,CCS2,,2026-03-01\n"
        "Missing Date Hub,18.82,73.32,Zeon,60.0,CCS2,https://example.com/st3,\n",
        encoding="utf-8",
    )

    provider = ManualVerifiedCSVProvider(csv_path=test_csv)
    assert provider.is_available()

    api_tracker = {}
    failed_tracker = []
    bbox = (18.4, 72.7, 19.1, 74.0)
    stations = provider.fetch_stations([], bbox, api_tracker, failed_tracker)

    # Only the row with both non-empty source_url and checked_on is accepted
    assert len(stations) == 1
    st = stations[0]
    assert st.name == "Valid Hub"
    assert st.source == "verified_manual"
    assert st.verified is True
    assert st.source_url == "https://example.com/st1"
    assert st.checked_on == "2026-03-01"
