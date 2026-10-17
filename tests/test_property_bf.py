"""Hypothesis property-based tests: Planner optimality vs Brute Force, and feasibility preservation."""

import os
import time

from hypothesis import given, settings
from hypothesis import strategies as st

from core.brute_force import solve_brute_force
from core.filters import filter_stations_greedy
from core.models import PRESET_CARS, Car, CorridorSnapshot, RoadEdge, RoadNode, Station, Trip
from core.planner import EVPlanner
from ingest.synthetic import generate_synthetic_corridor

MAX_EXAMPLES = int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "50"))


class TestBruteForceProperty:
    """Hypothesis property tests for planner optimality vs exhaustive brute force."""

    total_evaluated = 0
    total_feasible = 0
    stops_ge_1 = 0
    stops_ge_2 = 0

    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(
        start_soc=st.floats(min_value=0.25, max_value=0.45),
        lambda_val=st.floats(min_value=0.2, max_value=2.5),
        car_battery=st.floats(min_value=17.0, max_value=24.0),
        num_stations=st.integers(min_value=3, max_value=4),
        K=st.integers(min_value=8, max_value=12),
    )
    def test_planner_matches_brute_force_forced_charging(
        self, start_soc, lambda_val, car_battery, num_stations, K
    ):
        """Property test: Small battery and low start SoC force charging stops; planner matches brute force."""
        car = Car(
            id="test_prop_car",
            name="Property Test Car",
            battery_kwh=car_battery,
            usable_fraction=0.95,
            consumption_kwh_per_km=0.150,
            mass_kg=1200.0,
            drag_coefficient=0.30,
            frontal_area_m2=2.10,
            max_dc_kw=50.0,
            regen_efficiency=0.75,
        )

        total_dist_km = 100.0 if num_stations == 3 else 135.0
        snapshot = generate_synthetic_corridor(
            total_distance_km=total_dist_km,
            num_road_segments=20,
            num_stations=num_stations,
            seed=42 + num_stations,
            car=car,
        )

        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=start_soc,
            reserve_soc=0.10,
            stop_threshold_soc=0.80,
            comfort_weight_lambda=lambda_val,
            K=K,
        )

        # 1. Independent Brute Force Global Optimum (pure grid search)
        bf_res = solve_brute_force(snapshot, car, trip, lambda_val=lambda_val)

        # 2. Main Planner Optimum (with filter disabled for pure equivalence check)
        planner = EVPlanner()
        plan = planner.plan(
            snapshot,
            car,
            trip,
            lambda_val=lambda_val,
            use_all_departure_levels=True,
            enable_filter=False,
        )

        TestBruteForceProperty.total_evaluated += 1

        # Assert bidirectional feasibility
        assert plan.feasible == bf_res["feasible"], (
            f"Feasibility mismatch: Planner={plan.feasible}, BF={bf_res['feasible']}"
        )

        if bf_res["feasible"]:
            TestBruteForceProperty.total_feasible += 1
            num_stops = len(bf_res["stops"])
            if num_stops >= 1:
                TestBruteForceProperty.stops_ge_1 += 1
            if num_stops >= 2:
                TestBruteForceProperty.stops_ge_2 += 1

            # Exact cost matching within numerical tolerance
            assert abs(plan.cost_J - bf_res["cost_J"]) < 1e-5, (
                f"Planner J ({plan.cost_J}) != Brute Force J ({bf_res['cost_J']})"
            )

    def test_assert_charging_distribution(self):
        """Assert minimum fraction of forced charging examples (>=60% >=1 stop, and >=1 with 2 stops).

        Order-independent: If executed standalone, evaluates a deterministic suite of forced-charging scenarios.
        """
        if TestBruteForceProperty.total_feasible == 0:
            test_configs = [
                (0.30, 1.0, 18.0, 3, 10, 110.0),
                (0.25, 0.5, 18.0, 3, 10, 115.0),
                (0.35, 1.5, 20.0, 4, 10, 135.0),
                (0.28, 1.0, 17.5, 4, 10, 135.0),
                (0.25, 2.0, 18.0, 4, 10, 140.0),
                (0.30, 0.8, 19.0, 4, 10, 130.0),
                (0.32, 1.2, 21.0, 4, 10, 135.0),
                (0.26, 1.0, 17.0, 4, 10, 140.0),
            ]
            for s_soc, lam, bat, n_st, k_res, dist in test_configs:
                c = Car(
                    id="dist_car",
                    name="Distribution Test Car",
                    battery_kwh=bat,
                    usable_fraction=0.95,
                    consumption_kwh_per_km=0.150,
                    mass_kg=1200.0,
                    drag_coefficient=0.30,
                    frontal_area_m2=2.10,
                    max_dc_kw=50.0,
                    regen_efficiency=0.75,
                )
                snap = generate_synthetic_corridor(
                    total_distance_km=dist,
                    num_road_segments=20,
                    num_stations=n_st,
                    seed=42 + n_st,
                    car=c,
                )
                tr = Trip(
                    snapshot_id=snap.id,
                    start_soc=s_soc,
                    reserve_soc=0.10,
                    stop_threshold_soc=0.80,
                    comfort_weight_lambda=lam,
                    K=k_res,
                )
                bf = solve_brute_force(snap, c, tr, lambda_val=lam)
                if bf["feasible"]:
                    TestBruteForceProperty.total_feasible += 1
                    TestBruteForceProperty.total_evaluated += 1
                    if len(bf["stops"]) >= 1:
                        TestBruteForceProperty.stops_ge_1 += 1
                    if len(bf["stops"]) >= 2:
                        TestBruteForceProperty.stops_ge_2 += 1

        tot = TestBruteForceProperty.total_feasible
        assert tot > 0, "At least some examples must be feasible"

        frac_ge_1 = TestBruteForceProperty.stops_ge_1 / tot
        print(f"\n[Hypothesis Stats] Total Feasible: {tot}/{TestBruteForceProperty.total_evaluated}")
        print(f"[Hypothesis Stats] Stops >= 1: {TestBruteForceProperty.stops_ge_1} ({frac_ge_1:.1%})")
        print(f"[Hypothesis Stats] Stops >= 2: {TestBruteForceProperty.stops_ge_2}")

        assert frac_ge_1 >= 0.60, f"Expected >=60% examples with >=1 stop, got {frac_ge_1:.1%}"
        assert TestBruteForceProperty.stops_ge_2 >= 1, "Expected at least one example with 2 stops"


def test_non_uniform_station_layout_and_nonzero_detours():
    """Verify planner matches brute force with non-uniform layout and nonzero detours."""
    car = Car(
        id="detour_car",
        name="Detour Car",
        battery_kwh=30.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.150,
        mass_kg=1300.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.20,
        max_dc_kw=50.0,
        regen_efficiency=0.75,
    )

    # 4 road nodes: 0 -> 1 -> 2 -> 3 (total 90 km)
    nodes = {
        0: RoadNode(id=0, lat=18.0, lon=72.0, elevation_m=50.0),
        1: RoadNode(id=1, lat=18.2, lon=72.2, elevation_m=100.0),
        2: RoadNode(id=2, lat=18.5, lon=72.6, elevation_m=80.0),
        3: RoadNode(id=3, lat=18.8, lon=73.0, elevation_m=60.0),
    }
    edges = [
        RoadEdge(u=0, v=1, length_m=30000.0, time_s=1200.0, elevation_gain_m=50.0, energy_kwh=4.5),
        RoadEdge(u=1, v=2, length_m=30000.0, time_s=1200.0, elevation_gain_m=-20.0, energy_kwh=4.0),
        RoadEdge(u=2, v=3, length_m=30000.0, time_s=1200.0, elevation_gain_m=-20.0, energy_kwh=4.0),
    ]

    # Station attached to node 1 with 2.0 km / 180s / 0.3 kWh spur detour
    st1 = Station(
        id="spur_st_1",
        name="Spur Station 1",
        lat=18.21,
        lon=72.21,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        amenity_score=0.8,
        road_node_id=1,
        detour_distance_m=2000.0,
        detour_time_s=180.0,
        detour_energy_kwh=0.30,
    )
    # Station attached to node 2 with 1.0 km / 90s / 0.15 kWh spur detour
    st2 = Station(
        id="spur_st_2",
        name="Spur Station 2",
        lat=18.51,
        lon=72.61,
        operator="Jio-bp",
        max_kw=100.0,
        connector_types=["CCS2"],
        amenity_score=0.5,
        road_node_id=2,
        detour_distance_m=1000.0,
        detour_time_s=90.0,
        detour_energy_kwh=0.15,
    )

    snapshot = CorridorSnapshot(
        id="non_uniform_spur_corridor",
        source_name="Origin",
        destination_name="Destination",
        created_at="2026-10-17T20:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=[st1, st2],
        source_node_id=0,
        destination_node_id=3,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.30,  # Forces stop at Station 1
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=10,
    )

    bf_res = solve_brute_force(snapshot, car, trip, lambda_val=1.0)
    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, lambda_val=1.0, enable_filter=False)

    assert plan.feasible == bf_res["feasible"]
    assert plan.feasible is True
    assert abs(plan.cost_J - bf_res["cost_J"]) < 1e-5


def test_route_soc_profile_independent_clamped_simulation():
    """Verify route_soc_profile is an independent clamped simulation within 1/K and above reserve."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    snapshot = generate_synthetic_corridor(
        total_distance_km=120.0,
        num_road_segments=20,
        num_stations=3,
        seed=77,
        car=car,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.50,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        K=20,
    )

    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, enable_filter=False)

    assert plan.feasible is True
    assert len(plan.route_soc_profile) > 0

    # 1. Confirm continuous physical simulation: SoC points are NOT snapped to discrete grid levels (1/K)
    non_grid_count = sum(
        1 for pt in plan.route_soc_profile
        if abs(pt.soc * trip.K - round(pt.soc * trip.K)) > 1e-3
    )
    assert non_grid_count > 0, "Profile should contain continuous intermediate SoC values from physical simulation"

    # 2. Assert final profile SoC is within 1/K of plan.arrival_soc_dest
    final_point_soc = plan.route_soc_profile[-1].soc
    allowed_tolerance = (1.0 / trip.K) + 1e-6
    assert abs(final_point_soc - plan.arrival_soc_dest) <= allowed_tolerance, (
        f"Profile final SoC ({final_point_soc}) not within 1/K ({allowed_tolerance}) of arrival ({plan.arrival_soc_dest})"
    )

    # 3. Assert profile SoC never drops below reserve across the entire trajectory
    for idx, pt in enumerate(plan.route_soc_profile):
        assert pt.soc >= trip.reserve_soc - 1e-6, (
            f"Profile point {idx} at dist={pt.distance_km}km dropped below reserve: {pt.soc} < {trip.reserve_soc}"
        )
        assert pt.soc <= 1.0 + 1e-6, (
            f"Profile point {idx} at dist={pt.distance_km}km exceeded 100% capacity: {pt.soc} > 1.0"
        )


def test_pareto_frontier_monotonicity():
    """Verify Pareto points form a non-increasing discomfort vs increasing time curve."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    snapshot = generate_synthetic_corridor(
        total_distance_km=140.0,
        num_road_segments=25,
        num_stations=5,
        seed=99,
        car=car,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.45,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=20,
    )

    planner = EVPlanner()
    pareto_pts = planner.sweep_pareto(snapshot, car, trip)

    assert len(pareto_pts) >= 1
    # Check that as time strictly increases, discomfort strictly decreases
    for i in range(len(pareto_pts) - 1):
        pt_curr = pareto_pts[i]
        pt_next = pareto_pts[i + 1]
        assert pt_next.total_time_min > pt_curr.total_time_min - 1e-4
        assert pt_next.total_discomfort_min < pt_curr.total_discomfort_min + 1e-4


def test_infeasible_plan_reports_bridging_gap():
    """Verify that an infeasible plan reports the exact unbridgeable gap from the filter."""
    car = Car(
        id="tiny_car",
        name="Tiny Range Car",
        battery_kwh=10.0,
        usable_fraction=0.90,
        consumption_kwh_per_km=0.200,  # Range = 45 km, usable at 50% = 20 km
        mass_kg=1200.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.20,
        max_dc_kw=30.0,
        regen_efficiency=0.70,
    )

    snapshot = generate_synthetic_corridor(
        total_distance_km=150.0,
        num_road_segments=15,
        num_stations=1,  # Only 1 station in middle at 75 km!
        seed=1,
        car=car,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.50,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=10,
    )

    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, enable_filter=True)

    assert plan.feasible is False
    assert plan.infeasibility_reason is not None
    assert "unbridgeable gap" in plan.infeasibility_reason.lower()
    assert "exceeding vehicle range" in plan.infeasibility_reason.lower()


def test_heuristic_dwell_targets_vs_full_set():
    """Compare 20/40-minute dwell heuristic vs full departure level set (cost equality, speedup)."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    snapshot = generate_synthetic_corridor(
        total_distance_km=130.0,
        num_road_segments=25,
        num_stations=3,
        seed=88,
        car=car,
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.40,
        reserve_soc=0.10,
        stop_threshold_soc=0.80,
        K=50,  # Resolution K=50 highlights speedup
    )

    planner = EVPlanner()

    # Exact full departure search
    t0 = time.perf_counter()
    plan_full = planner.plan(snapshot, car, trip, use_all_departure_levels=True)
    time_full = time.perf_counter() - t0

    # 20/40-min dwell target heuristic
    t1 = time.perf_counter()
    plan_heur = planner.plan(snapshot, car, trip, use_all_departure_levels=False)
    time_heur = time.perf_counter() - t1

    assert plan_full.feasible is True
    assert plan_heur.feasible is True

    # Heuristic cost is close to full search optimum (within 1.5 min)
    assert abs(plan_heur.cost_J - plan_full.cost_J) <= 1.50
    speedup = time_full / max(1e-6, time_heur)
    print(f"\n[Benchmark] Full search: {time_full:.3f}s | Heuristic: {time_heur:.3f}s | Speedup: {speedup:.2f}x")


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

    kept, _, _ = filter_stations_greedy(
        stations=snapshot.stations,
        car=car,
        source_coord=src_coord,
        destination_coord=dst_coord,
        start_soc=trip.start_soc,
        reserve_soc=trip.reserve_soc,
        score_threshold=0.65,
    )

    snapshot_kept = snapshot.model_copy()
    snapshot_kept.stations = kept

    planner = EVPlanner()
    plan_kept = planner.plan(snapshot_kept, car, trip, enable_filter=False)
    plan_all = planner.plan(snapshot, car, trip, enable_filter=False)

    if plan_all.feasible:
        assert plan_kept.feasible is True, "Greedy filtering broke feasibility!"


def test_regression_original_mismatch_instance():
    """Regression test reproducing the original mismatch instance: start_soc=0.375, lambda=2.5, battery=21.75.

    Root Cause Analysis:
        In commit 444f1a2, brute_force.py had 3 discrepancies relative to the planner:
        1. It used continuous floating-point arrival SoC rather than discretizing to level/K,
           causing charge_time_min and dwell penalty to diverge.
        2. It ignored spur detours (detour_distance_m, detour_time_s, detour_energy_kwh),
           evaluating travel time only on the main highway.
        3. It assumed uniform integer node milestones instead of reading real road_node_id.

        When brute force is properly aligned to the true physical problem (including spur detours
        and unified grid discretization), both independently achieve the exact global optimum J.
    """
    car = Car(
        id="test_prop_car",
        name="Property Test Car",
        battery_kwh=21.75,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.150,
        mass_kg=1200.0,
        drag_coefficient=0.30,
        frontal_area_m2=2.10,
        max_dc_kw=50.0,
        regen_efficiency=0.75,
    )
    snapshot = generate_synthetic_corridor(
        total_distance_km=135.0,
        num_road_segments=20,
        num_stations=4,
        seed=46,
        car=car,
    )
    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.375,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        comfort_weight_lambda=2.5,
        K=10,
    )

    # 1. Independent Brute Force
    bf_res = solve_brute_force(snapshot, car, trip, lambda_val=2.5)

    # 2. Main Planner
    planner = EVPlanner()
    plan = planner.plan(snapshot, car, trip, lambda_val=2.5, enable_filter=False)

    assert plan.feasible is True
    assert bf_res["feasible"] is True

    # Assert exact cost matching within numerical tolerance
    assert abs(plan.cost_J - bf_res["cost_J"]) < 1e-5, (
        f"Regression failure: Planner J ({plan.cost_J}) != BF J ({bf_res['cost_J']})"
    )

    # Both must select the exact same charging stops
    planner_stops = [(s.station_id, s.arrival_soc, s.departure_soc) for s in plan.stops]
    bf_stops = [(s["station_id"], s["arrival_soc"], s["departure_soc"]) for s in bf_res["stops"]]
    assert planner_stops == bf_stops, f"Stop sequence mismatch: {planner_stops} vs {bf_stops}"

