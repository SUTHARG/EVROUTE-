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
