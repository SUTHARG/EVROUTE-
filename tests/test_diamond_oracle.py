"""Unit tests for non-chain diamond corridor generator and multi-route oracle solver."""

from core.models import Car, Trip
from core.oracle import solve_multi_route_oracle
from core.planner import EVPlanner
from ingest.topologies import generate_diamond_corridor


def test_diamond_topology_planner_matches_oracle_and_chooses_eco_path():
    """Verify that on a diamond network, planner matches multi-route oracle and chooses the eco path when battery is low."""
    car = Car(
        id="test_diamond_car",
        name="Diamond Car",
        battery_kwh=20.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.150,
        mass_kg=1200.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.10,
        max_dc_kw=60.0,
        regen_efficiency=0.80,
    )
    snapshot = generate_diamond_corridor(car)

    # 1. Low battery test: Fast-but-hilly branch causes depletion/infeasibility,
    # so the eco branch (with regenerative braking descent) is strictly better and feasible.
    trip_eco = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.45,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        K=10,
    )
    planner = EVPlanner()
    plan_eco = planner.plan(snapshot, car, trip_eco, enable_filter=False)
    oracle_eco = solve_multi_route_oracle(snapshot, car, trip_eco)

    assert plan_eco.feasible is True
    assert oracle_eco["feasible"] is True
    assert abs(plan_eco.cost_J - oracle_eco["cost_J"]) < 1e-5
    # Confirm the eco route (via node 2) was chosen by the oracle
    assert oracle_eco["route_nodes"] == [0, 2, 3]

    # 2. High battery test: With ample SoC, the faster hilly branch (node 1) is chosen
    trip_fast = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.90,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        K=10,
    )
    plan_fast = planner.plan(snapshot, car, trip_fast, enable_filter=False)
    oracle_fast = solve_multi_route_oracle(snapshot, car, trip_fast)

    assert plan_fast.feasible is True
    assert oracle_fast["feasible"] is True
    assert abs(plan_fast.cost_J - oracle_fast["cost_J"]) < 1e-5
    assert oracle_fast["route_nodes"] == [0, 1, 3]
    assert plan_fast.cost_J < plan_eco.cost_J

    # 3. Forced stop test: Low start SoC forces a charging stop at station 2 along the eco branch
    trip_chg = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.25,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        K=10,
    )
    plan_chg = planner.plan(snapshot, car, trip_chg, enable_filter=False)
    oracle_chg = solve_multi_route_oracle(snapshot, car, trip_chg)

    assert plan_chg.feasible is True
    assert oracle_chg["feasible"] is True
    assert abs(plan_chg.cost_J - oracle_chg["cost_J"]) < 1e-5
    assert len(plan_chg.stops) == 1
    assert plan_chg.stops[0].station_id == "diamond_st_2"
    assert oracle_chg["stops"][0]["station_id"] == "diamond_st_2"


def test_diamond_both_routes_feasible_eco_wins_because_fast_route_needs_stop():
    """Verify scenario where BOTH the fast route and the eco route are feasible, but the

    eco route strictly wins because the fast route is forced to make an expensive charging stop.

    Setup:
    - Fast route (Branch 1: 0 -> 1 -> 3): high speed (60 min drive), high energy (14.5 kWh).
      At start_soc = 0.65 (9.88 kWh), it cannot bridge both legs without charging at station 1.
      Charging at 30 kW adds ~15.7 min, total time ~75.7 min. Feasible = True.
    - Eco route (Branch 2: 0 -> 2 -> 3): moderate speed (68 min drive), very low energy (2.5 kWh).
      At start_soc = 0.65, it needs ZERO stops, total time = 68.0 min. Feasible = True.
    - Result:
      Both routes are physically feasible.
      Eco route strictly wins (68.0 min < 75.7 min).
      Planner chooses the Eco route and matches the exhaustive multi-route Oracle.
    """
    car = Car(
        id="test_diamond_car_dual",
        name="Diamond Dual Feasible Car",
        battery_kwh=16.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.150,
        mass_kg=1200.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.10,
        max_dc_kw=30.0,
        regen_efficiency=0.80,
    )
    snapshot = generate_diamond_corridor(car)
    # Configure Branch 2 drive time to 68 min (2040s per segment)
    for e in snapshot.edges:
        if e.u == 0 and e.v == 2 or e.u == 2 and e.v == 3:
            e.time_s = 2040.0

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.65,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        comfort_weight_lambda=0.0,  # Pure time
        K=20,
    )

    # 1. Verify standalone feasibility of Branch 1 (Fast path with stop)
    snap_branch1 = snapshot.model_copy(deep=True)
    snap_branch1.nodes = {k: v for k, v in snapshot.nodes.items() if k != 2}
    snap_branch1.edges = [e for e in snapshot.edges if e.u != 2 and e.v != 2]
    snap_branch1.stations = [st for st in snapshot.stations if st.id == "diamond_st_1"]
    o1 = solve_multi_route_oracle(snap_branch1, car, trip, lambda_val=0.0)
    assert o1["feasible"] is True
    assert len(o1["stops"]) == 1
    assert o1["cost_J"] > 74.0

    # 2. Verify standalone feasibility of Branch 2 (Eco path with zero stops)
    snap_branch2 = snapshot.model_copy(deep=True)
    snap_branch2.nodes = {k: v for k, v in snapshot.nodes.items() if k != 1}
    snap_branch2.edges = [e for e in snapshot.edges if e.u != 1 and e.v != 1]
    snap_branch2.stations = [st for st in snapshot.stations if st.id == "diamond_st_2"]
    o2 = solve_multi_route_oracle(snap_branch2, car, trip, lambda_val=0.0)
    assert o2["feasible"] is True
    assert len(o2["stops"]) == 0
    assert abs(o2["cost_J"] - 68.0) < 1e-3

    # 3. Verify Planner on complete network picks Eco route and matches Oracle
    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, lambda_val=0.0, enable_filter=False)
    oracle = solve_multi_route_oracle(snapshot, car, trip, lambda_val=0.0)

    assert plan.feasible is True
    assert oracle["feasible"] is True
    assert abs(plan.cost_J - oracle["cost_J"]) < 1e-4
    assert plan.cost_J < o1["cost_J"]  # Eco strictly beats Fast
    assert len(plan.stops) == 0  # No stops needed on eco route
    assert oracle["route_nodes"] == [0, 2, 3]


def test_randomized_diamond_property_planner_matches_oracle():
    """Randomized property test verifying EVPlanner == Multi-Route Oracle across diverse parameters."""
    import random

    rng = random.Random(42)
    car = Car(
        id="test_diamond_car_random",
        name="Diamond Random Car",
        battery_kwh=18.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.145,
        mass_kg=1250.0,
        drag_coefficient=0.29,
        frontal_area_m2=2.15,
        max_dc_kw=45.0,
        regen_efficiency=0.80,
    )
    snapshot = generate_diamond_corridor(car)
    planner = EVPlanner()

    for i in range(25):
        # Sample randomized inputs
        start_soc = rng.choice([0.30, 0.40, 0.50, 0.65, 0.85, 0.95])
        reserve_soc = rng.choice([0.08, 0.10, 0.12])
        stop_thresh = rng.choice([0.30, 0.35, 0.40])
        lambda_val = rng.choice([0.0, 0.5, 1.0, 2.0])
        K = rng.choice([10, 15, 20])

        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=start_soc,
            reserve_soc=reserve_soc,
            stop_threshold_soc=stop_thresh,
            comfort_weight_lambda=lambda_val,
            K=K,
        )

        plan = planner.plan(snapshot, car, trip, lambda_val=lambda_val, enable_filter=False)
        oracle = solve_multi_route_oracle(snapshot, car, trip, lambda_val=lambda_val)

        assert plan.feasible == oracle["feasible"], f"Feasibility mismatch at trial {i}"
        if plan.feasible:
            assert abs(plan.cost_J - oracle["cost_J"]) < 1e-4, (
                f"Cost mismatch at trial {i}: Planner={plan.cost_J:.4f} vs Oracle={oracle['cost_J']:.4f}"
            )
