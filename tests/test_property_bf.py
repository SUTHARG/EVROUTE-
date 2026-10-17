"""Hypothesis property-based tests: Planner optimality vs Brute Force, and feasibility preservation."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.brute_force import solve_brute_force
from core.filters import filter_stations_greedy
from core.models import PRESET_CARS, Car, RoadEdge, RoadNode, Trip
from core.planner import EVPlanner
from core.road_graph import RoadGraph
from ingest.synthetic import generate_synthetic_corridor


@settings(max_examples=30, deadline=None)
@given(
    start_soc=st.floats(min_value=0.50, max_value=1.0),
    lambda_val=st.floats(min_value=0.1, max_value=3.0),
    car_battery=st.floats(min_value=30.0, max_value=60.0),
)
def test_planner_matches_brute_force_on_random_instances(start_soc, lambda_val, car_battery):
    """Property test: EVPlanner optimal cost J equals Brute-Force global optimum on small instances."""
    # Build small instance: 15 km corridor with 2 stations, K=10
    car = Car(
        id="test_prop_car",
        name="Property Test Car",
        battery_kwh=car_battery,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.150,
        mass_kg=1400.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.30,
        max_dc_kw=50.0,
        regen_efficiency=0.75,
    )

    snapshot = generate_synthetic_corridor(
        total_distance_km=40.0,
        num_road_segments=10,
        num_stations=2,
        seed=100,
        car=car,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=start_soc,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        comfort_weight_lambda=lambda_val,
        K=10,  # Coarse K for fast, exact combinatorial verification
    )

    # 1. Independent Brute Force Global Optimum
    bf_res = solve_brute_force(snapshot, car, trip, lambda_val=lambda_val)

    # 2. Main Planner Optimum
    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, lambda_val=lambda_val, use_all_departure_levels=True)

    if bf_res["feasible"]:
        assert plan.feasible is True
        # Cost J must match within floating-point tolerance (0.1 min)
        assert plan.cost_J == pytest.approx(bf_res["cost_J"], abs=0.15), (
            f"Planner J ({plan.cost_J}) != Brute Force J ({bf_res['cost_J']})"
        )


def test_lambda_zero_minimizes_travel_time():
    """Verify that as lambda -> 0, planner strictly minimizes total travel time."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    snapshot = generate_synthetic_corridor(
        total_distance_km=140.0,
        num_road_segments=25,
        num_stations=4,
        seed=55,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.60,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=20,
    )

    planner = EVPlanner()
    # Plan with lambda -> 0 (pure time priority)
    plan_speed = planner.plan(snapshot, car, trip, lambda_val=0.001)

    # Plan with high lambda (comfort priority: prefers better amenities, ideal dwell)
    plan_comfort = planner.plan(snapshot, car, trip, lambda_val=5.0)

    assert plan_speed.feasible is True
    assert plan_comfort.feasible is True

    # Speed plan total time must be <= comfort plan total time
    assert plan_speed.total_time_min <= plan_comfort.total_time_min + 1e-4

    # Comfort plan total discomfort must be <= speed plan total discomfort
    assert plan_comfort.total_discomfort_min <= plan_speed.total_discomfort_min + 1e-4


def test_filtering_preserves_feasibility_property():
    """Property test: If a trip is feasible with all stations, it is STILL feasible after filtering."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    snapshot = generate_synthetic_corridor(
        total_distance_km=150.0,
        num_road_segments=30,
        num_stations=10,
        seed=42,
    )
    src_coord = (snapshot.nodes[0].lat, snapshot.nodes[0].lon)
    dst_coord = (snapshot.nodes[30].lat, snapshot.nodes[30].lon)

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.70,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=20,
    )

    # 1. Filter stations
    kept, _, _audit = filter_stations_greedy(
        stations=snapshot.stations,
        car=car,
        source_coord=src_coord,
        destination_coord=dst_coord,
        start_soc=trip.start_soc,
        reserve_soc=trip.reserve_soc,
        score_threshold=0.65,  # High threshold triggers loop reinstatement
    )

    # Plan with kept stations
    snapshot_kept = snapshot.model_copy()
    snapshot_kept.stations = kept

    planner = EVPlanner()
    plan_kept = planner.plan(snapshot_kept, car, trip)

    # Plan with all stations
    plan_all = planner.plan(snapshot, car, trip)

    # If all-stations was feasible, kept-stations must remain feasible!
    if plan_all.feasible:
        assert plan_kept.feasible is True, "Greedy filtering broke feasibility!"


def test_eco_path_beats_fastest_path_in_energy():
    """Verify scenario where eco path consumes less net energy than fastest path."""
    PRESET_CARS["tata_nexon_ev_lr"]
    graph = RoadGraph()

    # Node 0 to 2
    # Path 1 (Fast Highway): 0 -> 1 -> 2: 120 km/h, flat
    # Path 2 (Eco Scenic / Descent): 0 -> 3 -> 2: 60 km/h with descent
    graph.add_node(RoadNode(id=0, lat=18.0, lon=72.0, elevation_m=200.0))
    graph.add_node(RoadNode(id=1, lat=18.05, lon=72.05, elevation_m=200.0))
    graph.add_node(RoadNode(id=2, lat=18.10, lon=72.10, elevation_m=100.0))
    graph.add_node(RoadNode(id=3, lat=18.02, lon=72.08, elevation_m=100.0))

    # Fast path: High speed (time = 200s, energy = 4.0 kWh)
    graph.add_edge(RoadEdge(u=0, v=1, length_m=5000.0, time_s=150.0, energy_kwh=2.2))
    graph.add_edge(RoadEdge(u=1, v=2, length_m=5000.0, time_s=150.0, energy_kwh=2.2))

    # Eco path: Lower speed + downhill regen (time = 500s, energy = 0.8 kWh)
    graph.add_edge(RoadEdge(u=0, v=3, length_m=5000.0, time_s=300.0, energy_kwh=0.8))
    graph.add_edge(RoadEdge(u=3, v=2, length_m=5000.0, time_s=300.0, energy_kwh=0.2))

    from core.bellman_ford import bellman_ford, dijkstra, reconstruct_path
    fast_dist, fast_pred = dijkstra(graph, source=0, weight_attr="time_s")
    eco_dist, eco_pred = bellman_ford(graph, source=0, weight_attr="energy_kwh")

    fast_path = reconstruct_path(fast_pred, target=2)
    eco_path = reconstruct_path(eco_pred, target=2)

    assert fast_path == [0, 1, 2]
    assert eco_path == [0, 3, 2]
    assert fast_dist[2] < (300.0 + 300.0)  # Fast path is faster in time
    assert eco_dist[2] < (2.2 + 2.2)        # Eco path consumes less energy


def test_reduced_edge_only_high_departure_levels_feasible():
    """Verify path requiring significant climb is feasible only from high departure levels."""
    car = Car(
        id="prop_car",
        name="Prop Car",
        battery_kwh=40.0,
        usable_fraction=1.0,
        consumption_kwh_per_km=0.15,
        mass_kg=1500.0,
        drag_coefficient=0.3,
        frontal_area_m2=2.3,
        max_dc_kw=50.0,
        regen_efficiency=0.8,
    )

    # Edge consuming 28 kWh out of 40 kWh (70% of battery!), reserve is 10% (4 kWh)
    # Need departure energy >= 28 + 4 = 32 kWh (80% SoC)
    edges = [
        RoadEdge(
            u=1,
            v=2,
            length_m=20000.0,
            time_s=1200.0,
            elevation_gain_m=800.0,
            energy_kwh=28.0,
        )
    ]

    from core.energy import build_arrival_soc_table
    K = 20
    table = build_arrival_soc_table(car, edges, K=K, reserve_soc=0.10)

    # Departure levels < 80% (idx < 16) must be None
    for s_idx in range(16):
        assert table[s_idx] is None, f"Level {s_idx} should be infeasible"

    # Departure levels >= 80% (idx >= 16) must be feasible
    for s_idx in range(16, 21):
        assert table[s_idx] is not None, f"Level {s_idx} should be feasible"
        assert table[s_idx] >= 0.10
