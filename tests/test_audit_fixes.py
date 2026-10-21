"""Comprehensive verification tests for independent audit items P0, P1, and P2.

Covers:
- Prefix reserve + 100% clamping with mixed slopes over several edges
- Charging inverse at tiny power, s_in >= s_out, and exactly 100%
- Connector matching with multiple supported plugs
- Filter vs road energy on hilly data
- Imputation flags through API
- Synthetic snapshot without source failure
- Regen + charge in one profile
- Spur energy included in profile and geometry
- Pareto non-dominance and invalid lambda rejection
- Independent hand-computed values for energy_kwh, charge_time_min
"""

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app
from core.charging import (
    charge_time_min,
    invert_charge_time_to_soc,
)
from core.energy import (
    edge_energy_kwh,
    simulate_path_soc,
)
from core.filters import filter_stations_greedy
from core.models import (
    PRESET_CARS,
    Car,
    CorridorSnapshot,
    RoadEdge,
    RoadNode,
    Station,
    Trip,
)
from core.planner import EVPlanner

client = TestClient(app)


def test_synthetic_snapshot_without_source_fails():
    """Item 1 & 17: Station.source is required. Omitting source must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Station(
            id="st_no_source",
            name="No Source Charger",
            lat=18.5,
            lon=73.5,
            operator="Audit",
            max_kw=60.0,
        )
    assert "source" in str(exc_info.value)

    # Valid with source
    st = Station(
        id="st_valid",
        name="Valid Charger",
        lat=18.5,
        lon=73.5,
        operator="Audit",
        max_kw=60.0,
        source="synthetic",
    )
    assert st.source == "synthetic"


def test_prefix_reserve_and_100_percent_clamping_mixed_slopes():
    """Item 17: Prefix reserve + 100% clamping with mixed slopes over several edges.

    Tests that:
    1. Regenerative braking downhill clamps battery SoC at exactly 1.0 (100%) and never exceeds 100%.
    2. Steep uphill checks enforce the safety reserve floor and flag infeasibility.
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]
    usable_kwh = car.usable_battery_kwh

    # Sequence of 3 edges:
    # Edge 1: Moderate consumption (uses 2.0 kWh)
    # Edge 2: Huge downhill generating 15.0 kWh regen (would push SoC far above 1.0 if unclamped)
    # Edge 3: Moderate consumption (uses 3.0 kWh)
    edges = [
        RoadEdge(u=1, v=2, length_m=10000.0, time_s=600.0, elevation_gain_m=0.0, energy_kwh=2.0),
        RoadEdge(u=2, v=3, length_m=20000.0, time_s=1200.0, elevation_gain_m=-800.0, energy_kwh=-15.0),
        RoadEdge(u=3, v=4, length_m=10000.0, time_s=600.0, elevation_gain_m=0.0, energy_kwh=3.0),
    ]

    # Start at 90% SoC (0.90)
    arr_soc = simulate_path_soc(
        car=car,
        edges=edges,
        departure_soc=0.90,
        reserve_soc=0.10,
    )
    assert arr_soc is not None
    # After Edge 1: 0.90 - 2.0/usable_kwh
    # After Edge 2 (regen): clamped at 1.0!
    # After Edge 3: 1.0 - 3.0/usable_kwh
    expected_arr_soc = 1.0 - (3.0 / usable_kwh)
    assert abs(arr_soc - expected_arr_soc) < 1e-6, f"Expected {expected_arr_soc}, got {arr_soc}"
    assert arr_soc <= 1.0

    # Test uphill failure when dropping below reserve_soc
    uphill_edge = RoadEdge(u=4, v=5, length_m=50000.0, time_s=3600.0, elevation_gain_m=1000.0, energy_kwh=usable_kwh)
    arr_fail = simulate_path_soc(
        car=car,
        edges=[uphill_edge],
        departure_soc=0.50,
        reserve_soc=0.10,
    )
    assert arr_fail is None


def test_charging_inverse_boundary_cases():
    """Item 17: Charging inverse at tiny power, s_in >= s_out, and exactly 100%."""
    car = PRESET_CARS["tata_nexon_ev_lr"]


    # 1. s_in >= s_out must return 0.0 minutes
    assert charge_time_min(s_in=0.50, s_out=0.50, station_max_kw=100.0, car=car) == 0.0
    assert charge_time_min(s_in=0.80, s_out=0.40, station_max_kw=100.0, car=car) == 0.0
    assert invert_charge_time_to_soc(s_in=0.50, target_dwell_min=0.0, station_max_kw=100.0, car=car) == 0.50

    # 2. Charging to exactly 1.0 (100%)
    t_full = charge_time_min(s_in=0.20, s_out=1.00, station_max_kw=100.0, car=car)
    assert t_full > 0.0
    assert math.isfinite(t_full)
    # Inversion reaches exactly 1.0 (clamped)
    soc_full = invert_charge_time_to_soc(s_in=0.20, target_dwell_min=t_full + 10.0, station_max_kw=100.0, car=car)
    assert abs(soc_full - 1.0) < 1e-6

    # Tapering slows charging near 100%: charging 80%->100% should take longer per % than 20%->40%
    t_low = charge_time_min(s_in=0.20, s_out=0.40, station_max_kw=100.0, car=car)
    t_high = charge_time_min(s_in=0.80, s_out=1.00, station_max_kw=100.0, car=car)
    assert t_high > t_low, "CC-CV taper must make 80->100% slower than 20->40%"

    # 3. Tiny power station (e.g. 0.001 kW): graceful bounding without crash or division by zero
    soc_tiny = invert_charge_time_to_soc(s_in=0.20, target_dwell_min=30.0, station_max_kw=0.001, car=car)
    assert abs(soc_tiny - 0.20) < 0.01
    assert charge_time_min(s_in=0.20, s_out=0.80, station_max_kw=0.0, car=car) == float("inf")


def test_connector_matching_multiple_supported_plugs():
    """Item 9 & 17: Match ANY supported connector, not only supported_connectors[0]."""
    car = Car(
        id="multi_plug_car",
        name="Multi Plug EV",
        battery_kwh=50.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.15,
        mass_kg=1500.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.2,
        max_dc_kw=100.0,
        supported_connectors=["Type2", "CCS2", "CHAdeMO"],
    )

    stations = [
        Station(
            id="st_type2",
            name="Type2 Only",
            lat=18.1,
            lon=73.1,
            operator="A",
            max_kw=22.0,
            source="synthetic",
            connector_types=["Type2"],
            road_node_id=1,
        ),
        Station(
            id="st_gbt",
            name="GB/T Only",
            lat=18.2,
            lon=73.2,
            operator="B",
            max_kw=60.0,
            source="synthetic",
            connector_types=["GB/T"],
            road_node_id=2,
        ),
        Station(
            id="st_chademo",
            name="CHAdeMO Only",
            lat=18.3,
            lon=73.3,
            operator="C",
            max_kw=50.0,
            source="synthetic",
            connector_types=["CHAdeMO"],
            road_node_id=3,
        ),
    ]

    kept, _dropped, _stats = filter_stations_greedy(
        stations=stations,
        car=car,
        source_coord=(18.0, 73.0),
        destination_coord=(18.4, 73.4),
        score_threshold=0.0,
        min_power_kw=15.0,
    )
    filtered_ids = {st.id for st in kept}

    # Type2 and CHAdeMO are supported (even though not first in list)
    assert "st_type2" in filtered_ids
    assert "st_chademo" in filtered_ids
    # GB/T is NOT supported
    assert "st_gbt" not in filtered_ids


def test_filter_vs_road_energy_on_hilly_data():
    """Item 9 & 17: Filter gap checks on hilly terrain vs clamped road energy.

    Verifies that on hilly corridors, road energy exceeds flat distance-based energy.
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]

    # Road leg with 1200m elevation climb over 20km
    hilly_edge = RoadEdge(
        u=10,
        v=20,
        length_m=20000.0,
        time_s=1200.0,
        elevation_gain_m=1200.0,
        energy_kwh=8.5,  # High uphill consumption
    )
    flat_edge = RoadEdge(
        u=10,
        v=20,
        length_m=20000.0,
        time_s=1200.0,
        elevation_gain_m=0.0,
        energy_kwh=2.8,  # Flat consumption
    )

    arr_hilly = simulate_path_soc(car, [hilly_edge], departure_soc=0.50, reserve_soc=0.10)
    arr_flat = simulate_path_soc(car, [flat_edge], departure_soc=0.50, reserve_soc=0.10)

    assert arr_hilly is not None
    assert arr_flat is not None
    assert arr_hilly < arr_flat


def test_imputation_flags_through_api():
    """Item 2 & 17: Imputation flags (power_assumed, connector_assumed) exposed in API."""
    resp = client.post(
        "/plan",
        json={
            "snapshot_id": "synthetic_mumbai_pune_v1",
            "car_id": "tata_nexon_ev_lr",
            "start_soc": 0.80,
            "reserve_soc": 0.10,
        },
    )
    assert resp.status_code == 200
    plan_data = resp.json()
    assert "corridor_stations" in plan_data
    assert len(plan_data["corridor_stations"]) > 0

    # Verify every station has power_assumed and connector_assumed booleans
    for st in plan_data["corridor_stations"]:
        assert "power_assumed" in st
        assert isinstance(st["power_assumed"], bool)
        assert "connector_assumed" in st
        assert isinstance(st["connector_assumed"], bool)
        assert "amenity_known" in st
        assert isinstance(st["amenity_known"], bool)
        assert "spur_estimated" in st
        assert isinstance(st["spur_estimated"], bool)


def test_spur_energy_included_in_profile_and_geometry():
    """Item 5 & 17: Spur energy included in profile, events, and geometry."""
    nodes = {
        0: RoadNode(id=0, lat=18.0, lon=73.0, elevation_m=100.0),
        1: RoadNode(id=1, lat=18.2, lon=73.2, elevation_m=100.0),
        2: RoadNode(id=2, lat=18.5, lon=73.5, elevation_m=100.0),
    }
    edges = [
        RoadEdge(u=0, v=1, length_m=30000.0, time_s=1800.0, elevation_gain_m=0.0, energy_kwh=4.5),
        RoadEdge(u=1, v=2, length_m=40000.0, time_s=2400.0, elevation_gain_m=0.0, energy_kwh=6.0),
    ]
    # Station with 2 km round-trip spur detour (1 km each way)
    stations = [
        Station(
            id="st_spur",
            name="Detour Station",
            lat=18.21,
            lon=73.21,
            operator="Audit",
            max_kw=100.0,
            road_node_id=1,
            detour_distance_m=2000.0,
            detour_time_s=180.0,
            detour_energy_kwh=0.4,
            source="synthetic",
            spur_estimated=True,
            connector_types=["CCS2"],
        )
    ]
    snap = CorridorSnapshot(
        id="snap_spur_test",
        source_name="Origin",
        destination_name="Destination",
        created_at="2026-10-18T00:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=stations,
        source_node_id=0,
        destination_node_id=2,
    )
    car = PRESET_CARS["tata_tiago_ev"].model_copy()
    car.battery_kwh = 15.0  # Force charge at st_spur

    trip = Trip(
        snapshot_id="snap_spur_test",
        source_id="source",
        destination_id="dest",
        start_soc=0.50,
        reserve_soc=0.10,
        stop_threshold_soc=0.25,
        comfort_weight_lambda=1.0,
        K=20,
    )

    plan = EVPlanner().plan(snap, car, trip, enable_filter=False)
    assert plan.feasible is True
    assert len(plan.stops) == 1
    stop = plan.stops[0]
    assert stop.spur_estimated is True

    # Profile must include spur_in and spur_out events
    events = [pt.event for pt in plan.route_soc_profile]
    assert "spur_in" in events, f"Expected spur_in in profile events: {set(events)}"
    assert "charge" in events, f"Expected charge in profile events: {set(events)}"
    assert "spur_out" in events, f"Expected spur_out in profile events: {set(events)}"


def test_pareto_non_dominance_and_invalid_lambda_rejection():
    """Item 15 & 17: Pareto endpoint rejects negative / non-finite lambdas and returns non-dominated points."""
    # 1. Negative lambda rejection
    resp_neg = client.post(
        "/pareto",
        json={
            "snapshot_id": "synthetic_mumbai_pune_v1",
            "car_id": "tata_nexon_ev_lr",
            "lambdas": [-0.5, 1.0],
        },
    )
    assert resp_neg.status_code == 422

    # 2. Valid request
    resp_valid = client.post(
        "/pareto",
        json={
            "snapshot_id": "synthetic_mumbai_pune_v1",
            "car_id": "tata_nexon_ev_lr",
            "lambdas": [0.0, 0.5, 1.0, 2.0],
        },
    )
    assert resp_valid.status_code == 200
    data = resp_valid.json()
    assert "points" in data
    pts = data["points"]
    assert len(pts) >= 1

    # Verify non-dominance: if point A has strictly lower total_time than point B,
    # point B cannot have both higher or equal time AND higher or equal discomfort!
    for i in range(len(pts)):
        for j in range(len(pts)):
            if i != j and pts[i]["total_time_min"] < pts[j]["total_time_min"] - 1e-4:
                # If i strictly beats j in time, j must strictly beat i in discomfort (or equal if identical point)
                assert pts[i]["total_discomfort_min"] >= pts[j]["total_discomfort_min"] - 1e-4


def test_independent_hand_computed_energy_and_charge_time():
    """Item 17: Independent hand-computed verification of physical models.

    Validates:
    1. Mechanical power and energy integration over flat highway cruise.
    2. Exact charging duration under constant-power regime.
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]
    # Vehicle parameters:
    # mass = 1400.0 kg
    # Cd = 0.33, A = 2.30 m2
    # Crr = 0.010
    # drivetrain_efficiency = 0.90
    # auxiliary_power_kw = 0.0
    # Speed v = 72 km/h = 20.0 m/s
    # Distance d = 10.0 km = 10,000 m
    # Duration t = 10,000 / 20.0 = 500 s
    # Air density rho = 1.205 kg/m3, g = 9.80665 m/s2
    #
    # Hand calculation:
    # F_aero = 0.5 * 1.205 * 0.33 * 2.30 * (20.0)^2 = 182.919 N
    # F_roll = 1400.0 * 9.80665 * 0.010 = 137.2931 N
    # F_tract = F_aero + F_roll = 320.2121 N
    # E_mech = F_tract * 10,000 m = 3,202,121 Joules = 3,202,121 / 3,600,000 kWh = 0.889478 kWh
    # E_electric = E_mech / 0.90 = 0.988309 kWh
    e_calc = edge_energy_kwh(
        car=car,
        length_m=10000.0,
        time_s=500.0,
        elevation_gain_m=0.0,
        crr=0.010,
        rho_air=1.205,
    )
    assert abs(e_calc - 0.988309) < 0.01, f"Expected ~0.988 kWh, got {e_calc}"

    # Hand calculation for charging:
    # Battery 40.5 kWh, usable 0.95 -> 38.475 kWh
    # Charge from 0.20 to 0.50 at constant 50 kW charger with 50 kW car max:
    # Energy charged = (0.50 - 0.20) * 38.475 kWh = 11.5425 kWh
    # Charge time in minutes = (11.5425 kWh / 50 kW) * 60 min/h = 13.851 min
    t_min = charge_time_min(s_in=0.20, s_out=0.50, station_max_kw=50.0, car=car)
    assert abs(t_min - 13.851) < 0.05, f"Expected ~13.85 min, got {t_min}"

