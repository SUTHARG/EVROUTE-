"""Unit tests for Route.ev domain models and physics-based energy simulation."""

import pytest

from core.charging import charge_time_min, invert_charge_time_to_soc, station_charging_options
from core.energy import (
    REFERENCE_SPEED_KMH,
    build_arrival_soc_table,
    calibrate_crr,
    compute_path_energy_summary,
    edge_energy_kwh,
    simulate_path_soc,
)
from core.models import PRESET_CARS, Car, RoadEdge, Station, Trip


def test_preset_cars_and_effective_range():
    """Verify placeholder vehicle profiles, usable battery, and effective range calculations."""
    assert len(PRESET_CARS) >= 3
    nexon = PRESET_CARS["tata_nexon_ev_lr"]
    assert nexon.is_placeholder_profile is True
    assert nexon.battery_kwh == 40.5
    assert nexon.usable_battery_kwh == pytest.approx(40.5 * 0.95)

    # Effective energy with 10% reserve: usable * (1 - 0.10)
    effective_kwh = nexon.effective_energy_kwh(reserve_soc=0.10)
    expected_kwh = (40.5 * 0.95) * 0.90
    assert effective_kwh == pytest.approx(expected_kwh)


def test_station_simulated_tag():
    """Verify that Station reliability is strictly flagged as simulated."""
    station = Station(
        id="stat_001",
        name="Navi Mumbai Supercharger",
        lat=19.0330,
        lon=73.0297,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        reliability=0.92,
        source="synthetic",
    )
    assert station.is_reliability_simulated is True
    assert station.reliability == 0.92


def test_type2_station_uses_conservative_ac_power_and_constant_power_model():
    """An assumed generic 50 kW rating must not turn a Type 2 plug into DC fast charging."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    station = Station(
        id="type2-only",
        name="AC charger",
        lat=28.6,
        lon=77.2,
        max_kw=50.0,
        connector_types=["Type 2 (AC)"],
        power_assumed=True,
        source="ocm",
    )

    options = station_charging_options(station, car)
    assert options == [("ac", 7.2)]
    expected_min = (car.usable_battery_kwh * 0.20 / (7.2 * car.ac_charging_efficiency)) * 60
    assert charge_time_min(0.2, 0.4, options[0][1], car, mode="ac") == pytest.approx(expected_min)

    reached_soc = invert_charge_time_to_soc(0.2, expected_min, options[0][1], car, mode="ac")
    assert reached_soc == pytest.approx(0.4)

    mixed_site = station.model_copy(
        update={"power_assumed": False, "connector_types": ["CCS2", "Type 2 (AC)"], "max_kw": 50.0}
    )
    assert station_charging_options(mixed_site, car) == [("dc", 50.0), ("ac", 7.2)]


def test_trip_validation():
    """Verify Trip schema enforces reserve_soc and stop_threshold_soc bounds."""
    # Valid trip
    trip = Trip(
        snapshot_id="mumbai_pune_v1",
        start_soc=1.0,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
    )
    assert trip.start_soc == 1.0

    # Infeasible: start_soc lower than reserve
    with pytest.raises(ValueError, match="cannot be lower than reserve_soc"):
        Trip(
            snapshot_id="mumbai_pune_v1",
            start_soc=0.05,
            reserve_soc=0.10,
        )


def test_calibrated_crr_flat_road_exact_match():
    """Verify that flat road consumption exactly matches rated consumption_kwh_per_km.

    At reference speed (70 km/h) over a flat road, electrical consumption
    must equal rated consumption * distance.
    """
    for car_id, car in PRESET_CARS.items():
        crr = calibrate_crr(car, v_ref_kmh=REFERENCE_SPEED_KMH)
        assert crr >= 0.005

        distance_km = 25.0
        distance_m = distance_km * 1000.0
        speed_mps = REFERENCE_SPEED_KMH / 3.6
        time_s = distance_m / speed_mps

        # Energy on flat road
        energy_kwh = edge_energy_kwh(
            car=car,
            length_m=distance_m,
            time_s=time_s,
            elevation_gain_m=0.0,
            crr=crr,
        )

        expected_kwh = car.consumption_kwh_per_km * distance_km
        assert energy_kwh == pytest.approx(expected_kwh, rel=1e-5), f"Failed for {car_id}"


def test_symmetric_hill_net_positive():
    """Verify that round-trip over a symmetric hill costs net positive energy.

    Because drivetrain propulsion efficiency < 1.0 and regenerative braking
    efficiency < 1.0, climbing up then descending down the same vertical height
    must consume net positive energy.
    """
    car = PRESET_CARS["mg_zs_ev"]
    crr = calibrate_crr(car)

    length_m = 10_000.0  # 10 km
    time_s = 600.0  # 60 km/h
    delta_h = 400.0  # 400m climb

    # Uphill edge
    e_uphill = edge_energy_kwh(
        car=car,
        length_m=length_m,
        time_s=time_s,
        elevation_gain_m=delta_h,
        crr=crr,
    )

    # Downhill edge (same distance and speed, negative delta_h)
    e_downhill = edge_energy_kwh(
        car=car,
        length_m=length_m,
        time_s=time_s,
        elevation_gain_m=-delta_h,
        crr=crr,
    )

    # Uphill must consume energy
    assert e_uphill > 0.0
    # Downhill must return negative energy (regen recovery)
    assert e_downhill < 0.0

    # Net energy over symmetric hill MUST be strictly positive!
    net_hill_energy = e_uphill + e_downhill
    assert net_hill_energy > 0.0

    # Furthermore, net hill energy must exceed flat road energy for the same 20 km
    e_flat_20km = (
        edge_energy_kwh(
            car=car,
            length_m=length_m,
            time_s=time_s,
            elevation_gain_m=0.0,
            crr=crr,
        )
        * 2.0
    )
    assert net_hill_energy > e_flat_20km


def test_steep_downhill_negative_edge():
    """Verify steep descent produces negative energy_kwh (regenerative charging)."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    # Drop 600 meters over 3 km at 40 km/h
    length_m = 3000.0
    time_s = 270.0  # 40 km/h
    delta_h = -600.0

    e_descent = edge_energy_kwh(
        car=car,
        length_m=length_m,
        time_s=time_s,
        elevation_gain_m=delta_h,
    )
    assert e_descent < -1.0  # Substantial regenerative recharge


def test_clamping_counterexample_user_scenario():
    """Verify exact 100% clamping counterexample from review item 1.

    Scenario:
      - Usable battery: 40.0 kWh
      - Reserve SoC: 0.10 (4.0 kWh)
      - Starting at 100% SoC (40.0 kWh)
      - Edge 1 (Descent): net energy -0.2 * 40 = -8.0 kWh
      - Edge 2 (Climb): net energy +0.95 * 40 = +38.0 kWh

    Naive math without clamping:
      arrival = 40.0 - (-8.0 + 38.0) = 10.0 kWh (25% SoC >= 10% reserve -> Falsely FEASIBLE).

    True physical reality with clamping:
      After edge 1: battery charges from 40.0, but clamps at 40.0 (100%).
      After edge 2: battery drops from 40.0 - 38.0 = 2.0 kWh (5% SoC < 10% reserve -> INFEASIBLE).

    simulate_path_soc must detect this and return None!
    """
    car = Car(
        id="test_car",
        name="Test 40kWh Car",
        battery_kwh=40.0,
        usable_fraction=1.0,
        consumption_kwh_per_km=0.150,
        mass_kg=1500.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.30,
        max_dc_kw=50.0,
        regen_efficiency=0.80,
    )

    edges = [
        RoadEdge(
            u=1,
            v=2,
            length_m=5000.0,
            time_s=300.0,
            elevation_gain_m=-500.0,
            energy_kwh=-8.0,  # -0.2 * usable
        ),
        RoadEdge(
            u=2,
            v=3,
            length_m=15000.0,
            time_s=900.0,
            elevation_gain_m=800.0,
            energy_kwh=38.0,  # +0.95 * usable
        ),
    ]

    arrival_soc = simulate_path_soc(
        car=car,
        edges=edges,
        departure_soc=1.0,
        reserve_soc=0.10,
    )

    # Must be INFEASIBLE because true remaining energy is 2.0 kWh (0.05 SoC) < 0.10 reserve!
    assert arrival_soc is None

    # Summary metrics should show net energy 30.0 kWh, peak need 30.0 kWh
    time_s, net_kwh, peak_need_kwh = compute_path_energy_summary(edges)
    assert net_kwh == 30.0
    assert peak_need_kwh == 30.0
    assert time_s == 1200.0


def test_arrival_soc_table_monotonicity():
    """Verify that build_arrival_soc_table produces non-strict monotonic arrival SoC.

    Due to 100% battery capacity clamping, the arrival SoC plateau is non-decreasing:
    s_a <= s_b implies arrival_soc(s_a) <= arrival_soc(s_b) for all valid levels.
    """
    car = PRESET_CARS["hyundai_ioniq_5"]
    edges = [
        RoadEdge(
            u=1,
            v=2,
            length_m=8000.0,
            time_s=400.0,
            elevation_gain_m=-150.0,
            energy_kwh=-1.5,
        ),
        RoadEdge(
            u=2,
            v=3,
            length_m=12000.0,
            time_s=600.0,
            elevation_gain_m=100.0,
            energy_kwh=2.8,
        ),
        RoadEdge(
            u=3,
            v=4,
            length_m=15000.0,
            time_s=800.0,
            elevation_gain_m=-80.0,
            energy_kwh=-0.5,
        ),
        RoadEdge(
            u=4,
            v=5,
            length_m=20000.0,
            time_s=1000.0,
            elevation_gain_m=250.0,
            energy_kwh=5.0,
        ),
    ]

    K = 50
    reserve_soc = 0.10
    table = build_arrival_soc_table(car, edges, K=K, reserve_soc=reserve_soc)

    assert len(table) == K + 1

    # Check monotonicity across valid departure levels
    prev_valid_soc = -1.0
    for s_idx in range(K + 1):
        arr_soc = table[s_idx]
        if arr_soc is not None:
            assert arr_soc >= reserve_soc
            assert arr_soc <= 1.0
            assert (
                arr_soc >= prev_valid_soc - 1e-9
            ), f"Monotonicity violation at s_idx={s_idx}: {arr_soc} < {prev_valid_soc}"
            prev_valid_soc = arr_soc
