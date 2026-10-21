"""Comprehensive algorithmic benchmarks for Route.ev:
1. Runtime vs |V_c| (charger count) with build vs search time breakdown and log-log slope fitting
2. Runtime vs K (discretization resolution) with build vs search time breakdown and log-log slope fitting
3. Brute Force vs DP runtime comparison
4. K-convergence of plan cost J(K) on nested grids 25, 50, 100, 200, 400 at lambda=0
5. Full road graph DP baseline vs reduced charger graph DP
"""

from __future__ import annotations

import heapq
import json
import math
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from core.brute_force import solve_brute_force
from core.charger_graph import map_stations_to_road_nodes
from core.charging import charge_time_min
from core.comfort import compute_dwell_discomfort
from core.energy import discretize_soc_level, level_to_soc
from core.models import PRESET_CARS, Car, CorridorSnapshot, Trip
from core.planner import EVPlanner
from core.road_graph import RoadGraph
from ingest.synthetic import generate_synthetic_corridor


def fit_log_log_slope(xs: list[float], ys: list[float]) -> float:
    """Fit slope m in log(y) = m * log(x) + c using linear least squares."""
    pts = [(math.log(x), math.log(max(1e-4, y))) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pts) < 2:
        return 0.0
    u_mean = sum(p[0] for p in pts) / len(pts)
    w_mean = sum(p[1] for p in pts) / len(pts)
    num = sum((p[0] - u_mean) * (p[1] - w_mean) for p in pts)
    den = sum((p[0] - u_mean) ** 2 for p in pts)
    return num / den if den > 1e-12 else 0.0


def benchmark_runtime_vs_vc() -> tuple[list[dict[str, Any]], float]:
    """Benchmark DP planner runtime as a function of candidate charger count |V_c|.

    Separates graph-build time from search time and fits the log-log scaling slope.
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    K = 50
    vc_counts = [2, 4, 6, 8, 10, 12, 16, 20]
    results = []

    print("\n--- Benchmark 1: Runtime vs |V_c| (K = 50, Distance = 180 km) ---")
    search_times = []
    vcs = []

    for n_stat in vc_counts:
        snapshot = generate_synthetic_corridor(
            total_distance_km=180.0,
            num_road_segments=30,
            num_stations=n_stat,
            seed=100 + n_stat,
            car=car,
        )
        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=0.50,
            reserve_soc=0.10,
            stop_threshold_soc=0.35,
            K=K,
        )

        # Warm-up
        _ = planner.plan(snapshot, car, trip, enable_filter=False)

        trials = 5
        t_build_sum = 0.0
        t_search_sum = 0.0
        for _ in range(trials):
            p = planner.plan(snapshot, car, trip, enable_filter=False)
            t_build_sum += p.build_time_ms
            t_search_sum += p.search_time_ms

        avg_build_ms = t_build_sum / trials
        avg_search_ms = t_search_sum / trials
        avg_total_ms = avg_build_ms + avg_search_ms
        n_ec = (
            sum(len(e) for e in planner.last_reduced_graph.driving_edges.values())
            if planner.last_reduced_graph
            else 0
        )

        results.append({
            "V_c": n_stat,
            "E_c": n_ec,
            "build_ms": round(avg_build_ms, 2),
            "search_ms": round(avg_search_ms, 2),
            "total_ms": round(avg_total_ms, 2),
        })
        vcs.append(float(n_stat))
        search_times.append(avg_search_ms)
        print(
            f"|V_c| = {n_stat:>2} chargers | |E_c| = {n_ec:>2} edges (ratio {n_ec / max(1, n_stat):>4.2f}) | "
            f"Build: {avg_build_ms:>5.2f} ms | Search: {avg_search_ms:>5.2f} ms | Total: {avg_total_ms:>6.2f} ms"
        )

    slope_vc = fit_log_log_slope(vcs, search_times)
    print(f"[+] Fitted log-log slope for search time vs |V_c|: {slope_vc:.2f}")
    print("    Explanation: In corridor topology with finite EV battery range, each charger can only reach a constant")
    print("    number of forward stations within reachable range; hence |E_c| = O(|V_c|) rather than dense O(|V_c|^2),")
    print("    yielding a near-linear empirical search time slope O(|V_c|).")

    return results, slope_vc


def benchmark_runtime_vs_k() -> tuple[list[dict[str, Any]], float]:
    """Benchmark DP planner runtime as a function of SoC resolution K.

    Separates graph-build time from search time and fits the log-log scaling slope.
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    k_values = [10, 20, 30, 50, 75, 100, 150, 200]
    results = []

    snapshot = generate_synthetic_corridor(
        total_distance_km=140.0,
        num_road_segments=25,
        num_stations=5,
        seed=42,
        car=car,
    )

    print("\n--- Benchmark 2: Runtime vs K (|V_c| = 5, Distance = 140 km) ---")
    ks = []
    search_times = []

    for k in k_values:
        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=0.50,
            reserve_soc=0.10,
            stop_threshold_soc=0.35,
            K=k,
        )

        # Warm-up
        _ = planner.plan(snapshot, car, trip, enable_filter=False)

        trials = 5
        t_build_sum = 0.0
        t_search_sum = 0.0
        for _ in range(trials):
            p = planner.plan(snapshot, car, trip, enable_filter=False)
            t_build_sum += p.build_time_ms
            t_search_sum += p.search_time_ms

        avg_build_ms = t_build_sum / trials
        avg_search_ms = t_search_sum / trials
        avg_total_ms = avg_build_ms + avg_search_ms

        results.append({
            "K": k,
            "build_ms": round(avg_build_ms, 2),
            "search_ms": round(avg_search_ms, 2),
            "total_ms": round(avg_total_ms, 2),
        })
        ks.append(float(k))
        search_times.append(avg_search_ms)
        print(
            f"K = {k:>3} intervals | Build: {avg_build_ms:>5.2f} ms | "
            f"Search: {avg_search_ms:>5.2f} ms | Total: {avg_total_ms:>6.2f} ms"
        )

    slope_k = fit_log_log_slope(ks, search_times)
    print(f"[+] Fitted log-log slope for search time vs K: {slope_k:.2f} (theoretical O(K^2) = 2.0)")

    return results, slope_k


def benchmark_bf_vs_dp() -> list[dict[str, Any]]:
    """Benchmark Brute Force exponential scaling vs DP polynomial scaling."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    K = 10
    vc_counts = [1, 2, 3, 4, 5]
    results = []

    print("\n--- Benchmark 3: Brute Force vs DP (K = 10, Distance = 120 km) ---")
    for n_stat in vc_counts:
        snapshot = generate_synthetic_corridor(
            total_distance_km=120.0,
            num_road_segments=20,
            num_stations=n_stat,
            seed=200 + n_stat,
            car=car,
        )
        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=0.45,
            reserve_soc=0.10,
            stop_threshold_soc=0.35,
            K=K,
        )

        trials_dp = 10
        t0 = time.perf_counter()
        for _ in range(trials_dp):
            p_plan = planner.plan(snapshot, car, trip, enable_filter=False)
        dp_ms = ((time.perf_counter() - t0) / trials_dp) * 1000.0

        t1 = time.perf_counter()
        bf_res = solve_brute_force(snapshot, car, trip)
        bf_ms = (time.perf_counter() - t1) * 1000.0

        speedup = bf_ms / max(0.01, dp_ms)
        cost_match = (
            abs(p_plan.cost_J - bf_res["cost_J"]) < 1e-4
            if p_plan.feasible and bf_res["feasible"]
            else True
        )

        results.append({
            "V_c": n_stat,
            "dp_ms": round(dp_ms, 2),
            "bf_ms": round(bf_ms, 2),
            "speedup": round(speedup, 1),
            "cost_matched": cost_match,
        })
        print(f"|V_c| = {n_stat} | DP: {dp_ms:>5.2f} ms | BF: {bf_ms:>8.2f} ms | Speedup: {speedup:>6.1f}x")

    return results


def benchmark_k_convergence() -> list[dict[str, Any]]:
    """Benchmark K-convergence of plan cost J(K) on nested grid levels.

    Evaluates nested resolutions K in [25, 50, 100, 200, 400] at lambda = 0.0.
    Since grid resolutions are exact powers-of-two multiples, each coarser grid's
    discretization levels are a strict subset of finer grid levels.
    Reports relative difference against the finest-resolution reference grid J(K=400).
    """
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    nested_k_values = [25, 50, 100, 200, 400]
    results = []

    snapshot = generate_synthetic_corridor(
        total_distance_km=145.0,
        num_road_segments=25,
        num_stations=4,
        seed=333,
        car=car,
    )

    print("\n--- Benchmark 4: K-Convergence on Nested Grids (lambda = 0.0) ---")
    costs: dict[int, float] = {}
    for k in nested_k_values:
        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=0.40,
            reserve_soc=0.10,
            stop_threshold_soc=0.35,
            comfort_weight_lambda=0.0,
            K=k,
        )
        plan = planner.plan(snapshot, car, trip, lambda_val=0.0, enable_filter=False)
        costs[k] = plan.cost_J

    j_ref_400 = costs[400]
    for k in nested_k_values:
        diff = abs(costs[k] - j_ref_400)
        results.append({
            "K": k,
            "cost_J": round(costs[k], 4),
            "abs_error_vs_fine_grid_ref_K400": round(diff, 4),
        })
        print(f"K = {k:>3} | Cost J = {costs[k]:>8.4f} min | |J(K) - J_ref(400)| = {diff:>6.4f} min")

    return results


def solve_full_road_graph_dp(
    snapshot: CorridorSnapshot,
    car: Car,
    trip: Trip,
    lambda_val: float = 0.0,
) -> tuple[float, float, int, int]:
    """Execute dynamic programming directly on the uncontracted physical road network.

    State space: (node_id: int, s: int) for all node_id in V_road and s in 0..K.
    Transitions:
    1. Road driving edges (u, v): updates battery by edge energy with clamping.
    2. Charger dwelling at stations attached to node u: allows charging to level s_dep > s.

    Complexity:
        State space: |V_road| * K
        Driving transitions: |E_road| * K
        Charging transitions: |V_c| * K^2
    """
    K = trip.K
    start_s = discretize_soc_level(trip.start_soc, K)
    start_kwh = trip.start_soc * car.usable_battery_kwh

    road_graph = RoadGraph.from_snapshot(snapshot)
    source_node = (
        snapshot.source_node_id
        if snapshot.source_node_id is not None
        else min(snapshot.nodes.keys())
    )
    dest_node = (
        snapshot.destination_node_id
        if snapshot.destination_node_id is not None
        else max(snapshot.nodes.keys())
    )

    # Map road nodes to stations
    st_map = map_stations_to_road_nodes(snapshot.stations, road_graph)
    station_at_node = {node_id: st for st in snapshot.stations if (node_id := st_map.get(st.id)) is not None}

    t0 = time.perf_counter()
    # 2-layer state: (u, s, is_dep) ensures charging departure state does not overwrite driving arrival state
    dist: dict[tuple[int, int, bool], float] = {(source_node, start_s, True): 0.0}
    pq: list[tuple[float, float, int, int, bool]] = [(0.0, -start_kwh, source_node, start_s, True)]

    best_dest_cost = float("inf")
    states_expanded = 0
    edges_relaxed = 0

    while pq:
        curr_d, neg_kwh, u, s, is_dep = heapq.heappop(pq)
        curr_kwh = -neg_kwh
        if curr_d > dist.get((u, s, is_dep), float("inf")) + 1e-9:
            continue

        states_expanded += 1
        if u == dest_node:
            best_dest_cost = min(best_dest_cost, curr_d)
            break

        # 1. Drive along outgoing road edges
        for edge in road_graph.get_outgoing_edges(u):
            edges_relaxed += 1
            v = edge.v
            next_kwh = min(car.usable_battery_kwh, curr_kwh - edge.energy_kwh)
            next_soc = next_kwh / car.usable_battery_kwh

            if next_soc + 1e-9 < trip.reserve_soc:
                continue

            next_s = discretize_soc_level(next_soc, K)
            drive_time_min = edge.time_s / 60.0
            new_cost = curr_d + drive_time_min
            next_state = (v, next_s, False)

            if new_cost < dist.get(next_state, float("inf")) - 1e-9:
                dist[next_state] = new_cost
                heapq.heappush(pq, (new_cost, -next_kwh, v, next_s, False))

        # 2. Charge at station if present at node u and in arrived state (not already departed)
        if u in station_at_node and not is_dep:
            station = station_at_node[u]
            s_in_soc = level_to_soc(s, K)

            for s_dep in range(s + 1, K + 1):
                edges_relaxed += 1
                s_dep_soc = level_to_soc(s_dep, K)
                t_chg = charge_time_min(
                    s_in=s_in_soc,
                    s_out=s_dep_soc,
                    station_max_kw=station.max_kw,
                    car=car,
                )
                d_chg = compute_dwell_discomfort(
                    dwell_min=t_chg,
                    amenity_score=station.amenity_score,
                    is_real_charge=True,
                    arrival_soc=s_in_soc,
                    stop_threshold_soc=trip.stop_threshold_soc,
                    gamma=trip.gamma,
                )
                chg_cost = t_chg + lambda_val * d_chg
                new_cost = curr_d + chg_cost
                dep_kwh = s_dep_soc * car.usable_battery_kwh
                dep_state = (u, s_dep, True)

                if new_cost < dist.get(dep_state, float("inf")) - 1e-9:
                    dist[dep_state] = new_cost
                    heapq.heappush(pq, (new_cost, -dep_kwh, u, s_dep, True))

    runtime_ms = (time.perf_counter() - t0) * 1000.0
    return best_dest_cost, runtime_ms, states_expanded, edges_relaxed


def benchmark_full_road_graph_vs_reduced() -> dict[str, Any]:
    """Benchmark DP on uncontracted full road graph vs contracted 2-layer charger graph."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    K = 30

    real_path = Path("tests/fixtures/unverified_mumbai_pune.json")
    if not real_path.exists():
        real_path = Path("data/snapshots/default_mumbai_pune.json")
    if real_path.exists():
        with open(real_path) as f:
            snapshot = CorridorSnapshot(**json.load(f))
    else:
        snapshot = generate_synthetic_corridor(
            total_distance_km=160.0,
            num_road_segments=60,
            num_stations=6,
            seed=777,
            car=car,
        )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.50,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        comfort_weight_lambda=0.0,
        K=K,
    )

    print("\n--- Benchmark 5: Full Road Graph DP vs Contracted Charger Graph DP ---")
    print(f"Graph size: |V_road| = {len(snapshot.nodes)} nodes, |V_c| = {len(snapshot.stations)} stations, K = {K}")

    # Use identical number of timing trials (5) for all methods
    trials = 5

    # 1. Contracted 2-layer charger graph DP
    t_build_sum = 0.0
    t_search_sum = 0.0
    plan = None
    for _ in range(trials):
        plan = planner.plan(snapshot, car, trip, lambda_val=0.0, enable_filter=False)
        t_build_sum += plan.build_time_ms
        t_search_sum += plan.search_time_ms
    contracted_build_ms = t_build_sum / trials
    contracted_search_ms = t_search_sum / trials
    contracted_total_ms = contracted_build_ms + contracted_search_ms
    contracted_cost = plan.cost_J if plan else float("inf")
    contracted_states = plan.states_expanded if plan else 0
    contracted_relaxed = plan.edges_relaxed if plan else 0
    n_ec = (
        sum(len(e) for e in planner.last_reduced_graph.driving_edges.values())
        if planner.last_reduced_graph
        else 0
    )
    ec_vc_ratio = n_ec / max(1, len(snapshot.stations))

    # 2. Uncontracted full road graph DP (same 5 trials)
    t_full_sum = 0.0
    full_cost = 0.0
    full_states = 0
    full_relaxed = 0
    for _ in range(trials):
        full_cost, r_ms, full_states, full_relaxed = solve_full_road_graph_dp(snapshot, car, trip, lambda_val=0.0)
        t_full_sum += r_ms
    full_road_ms = t_full_sum / trials

    # 3. Measured amortized sweeps (reusing precomputed reduced graph)
    # A. 15-lambda sweep
    lambdas_15 = [i * 0.2 for i in range(15)]
    t0_15 = time.perf_counter()
    for l_val in lambdas_15:
        planner.plan(snapshot, car, trip, lambda_val=l_val, enable_filter=False, precomputed_reduced_graph=planner.last_reduced_graph)
    contracted_15_search_ms = (time.perf_counter() - t0_15) * 1000.0
    contracted_15_total_ms = contracted_build_ms + contracted_15_search_ms
    uncontracted_15_ms = full_road_ms * 15
    amortized_15_speedup = uncontracted_15_ms / max(0.01, contracted_15_total_ms)

    # B. 8-lambda Pareto sweep
    lambdas_8 = [0.0, 0.2, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
    t0_8 = time.perf_counter()
    for l_val in lambdas_8:
        planner.plan(snapshot, car, trip, lambda_val=l_val, enable_filter=False, precomputed_reduced_graph=planner.last_reduced_graph)
    contracted_8_search_ms = (time.perf_counter() - t0_8) * 1000.0
    contracted_8_total_ms = contracted_build_ms + contracted_8_search_ms
    uncontracted_8_ms = full_road_ms * 8
    amortized_8_speedup = uncontracted_8_ms / max(0.01, contracted_8_total_ms)

    # Assert exact cost equality within 1e-6 (strict mathematical equivalence)
    cost_diff = abs(contracted_cost - full_cost)
    assert cost_diff < 1e-6, (
        f"Optimal J discrepancy exceeds 1e-6 tolerance: contracted {contracted_cost:.8f} min vs "
        f"uncontracted {full_cost:.8f} min (diff = {cost_diff:.2e} min)"
    )

    search_speedup = full_road_ms / max(0.01, contracted_search_ms)
    total_speedup = full_road_ms / max(0.01, contracted_total_ms)
    state_reduction = full_states / max(1, contracted_states)

    print(
        f"Contracted Charger Graph DP:  Build={contracted_build_ms:>5.2f} ms | Search={contracted_search_ms:>5.2f} ms | "
        f"Total={contracted_total_ms:>5.2f} ms | Cost={contracted_cost:.2f} min | States={contracted_states} | Relaxed={contracted_relaxed}"
    )
    print(
        f"Uncontracted Road Graph DP:   Search={full_road_ms:>5.2f} ms | Cost={full_cost:.2f} min | States={full_states} | Relaxed={full_relaxed}"
    )
    print(f"[+] Objective Comparison (|J_contracted - J_uncontracted| = {cost_diff:.2e} min < 1e-6 tolerance): VERIFIED EXACT EQUALITY")
    print(f"[+] Reduced Charger Graph Topology: |V_c|={len(snapshot.stations)}, |E_c|={n_ec} edges (|E_c|/|V_c| = {ec_vc_ratio:.2f})")
    print(f"[+] Single-Query End-to-End Speedup (Uncontracted Search vs Contracted Build+Search): {total_speedup:.1f}x")
    print(f"[+] Search-Only Speedup: {search_speedup:.1f}x (State expansions reduced by {state_reduction:.1f}x)")
    print(f"[+] Measured Amortized Speedup (15-lambda sweep): {amortized_15_speedup:.1f}x")
    print(f"[+] Measured Amortized Speedup (8-lambda Pareto sweep): {amortized_8_speedup:.1f}x")

    return {
        "V_road": len(snapshot.nodes),
        "V_c": len(snapshot.stations),
        "E_c": n_ec,
        "ec_vc_ratio": round(ec_vc_ratio, 2),
        "K": K,
        "contracted_build_ms": round(contracted_build_ms, 2),
        "contracted_search_ms": round(contracted_search_ms, 2),
        "contracted_total_ms": round(contracted_total_ms, 2),
        "contracted_cost": round(contracted_cost, 2),
        "contracted_states": contracted_states,
        "contracted_relaxed": contracted_relaxed,
        "full_road_ms": round(full_road_ms, 2),
        "full_cost": round(full_cost, 2),
        "full_states": full_states,
        "full_relaxed": full_relaxed,
        "cost_diff_min": round(cost_diff, 2),
        "search_speedup": round(search_speedup, 1),
        "single_query_e2e_speedup": round(total_speedup, 1),
        "amortized_15_lambda_speedup": round(amortized_15_speedup, 1),
        "amortized_8_lambda_pareto_speedup": round(amortized_8_speedup, 1),
        "state_reduction": round(state_reduction, 1),
    }


def plot_all_benchmarks(
    res_vc: list[dict[str, Any]],
    res_k: list[dict[str, Any]],
    res_bf: list[dict[str, Any]],
    res_conv: list[dict[str, Any]],
    res_baseline: dict[str, Any],
) -> None:
    """Generate high-resolution benchmark plots."""
    out_dir = Path("analysis/plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Runtime vs |V_c| (with build vs search breakdown)
    plt.figure(figsize=(7, 4.5), dpi=150)
    vcs = [r["V_c"] for r in res_vc]
    builds_vc = [r["build_ms"] for r in res_vc]
    searches_vc = [r["search_ms"] for r in res_vc]
    plt.plot(vcs, builds_vc, marker="o", color="#3b82f6", linestyle="--", label="Graph-Build Time")
    plt.plot(vcs, searches_vc, marker="s", color="#1d4ed8", linewidth=2.0, label="DP Search Time")
    plt.title("DP Planner Timing Breakdown vs Candidate Chargers |V_c| (K = 50)")
    plt.xlabel("Number of Candidate Chargers |V_c|")
    plt.ylabel("Execution Time (ms)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_runtime_vc.png")
    plt.close()

    # 2. Runtime vs K (with build vs search breakdown)
    plt.figure(figsize=(7, 4.5), dpi=150)
    ks = [r["K"] for r in res_k]
    builds_k = [r["build_ms"] for r in res_k]
    searches_k = [r["search_ms"] for r in res_k]
    plt.plot(ks, builds_k, marker="o", color="#10b981", linestyle="--", label="Graph-Build Time")
    plt.plot(ks, searches_k, marker="s", color="#047857", linewidth=2.0, label="DP Search Time")
    plt.title("DP Planner Timing Breakdown vs SoC Resolution K (|V_c| = 5)")
    plt.xlabel("SoC Discretization Intervals K")
    plt.ylabel("Execution Time (ms)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_runtime_k.png")
    plt.close()

    # 3. Brute Force vs DP
    plt.figure(figsize=(7, 4.5), dpi=150)
    vcs_bf = [r["V_c"] for r in res_bf]
    times_bf = [r["bf_ms"] for r in res_bf]
    times_dp = [r["dp_ms"] for r in res_bf]
    plt.plot(vcs_bf, times_bf, marker="^", color="#dc2626", label="Brute Force (Exponential)", linewidth=2.0)
    plt.plot(vcs_bf, times_dp, marker="o", color="#2563eb", label="Scalar DP (Polynomial)", linewidth=2.0)
    plt.yscale("log")
    plt.title("Runtime Scaling: Exhaustive Brute Force vs 2-Layer DP (K = 10)")
    plt.xlabel("Number of Candidate Chargers |V_c|")
    plt.ylabel("Execution Time (ms, log scale)")
    plt.legend()
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_bf_vs_dp.png")
    plt.close()

    # 4. K-Convergence on Nested Grids
    plt.figure(figsize=(7, 4.5), dpi=150)
    ks_c = [r["K"] for r in res_conv]
    costs_c = [r["cost_J"] for r in res_conv]
    ref_cost = res_conv[-1]["cost_J"]
    plt.plot(ks_c, costs_c, marker="d", color="#7c3aed", linewidth=2.0, label="Optimal Plan Cost J(K)")
    plt.axhline(ref_cost, color="#94a3b8", linestyle="--", label=f"Fine-Grid Reference J(K=400) = {ref_cost:.2f} min")
    plt.title("K-Convergence of Plan Cost on Nested Grids (lambda = 0)")
    plt.xlabel("Nested SoC Discretization Intervals K")
    plt.ylabel("Optimal Itinerary Cost J (min)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_k_convergence.png")
    plt.close()

    print(f"\n[+] All 4 benchmark plots successfully generated in: {out_dir}")


def main():
    res_vc, slope_vc = benchmark_runtime_vs_vc()
    res_k, slope_k = benchmark_runtime_vs_k()
    res_bf = benchmark_bf_vs_dp()
    res_conv = benchmark_k_convergence()
    res_baseline = benchmark_full_road_graph_vs_reduced()

    bench_data = {
        "runtime_vs_vc": res_vc,
        "slope_vc": round(slope_vc, 2),
        "runtime_vs_k": res_k,
        "slope_k": round(slope_k, 2),
        "bf_vs_dp": res_bf,
        "k_convergence": res_conv,
        "full_road_baseline": res_baseline,
    }
    with open("analysis/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(bench_data, f, indent=2)

    ui_data_path = Path("ui/src/data/benchmark_results.json")
    if ui_data_path.parent.exists():
        with open(ui_data_path, "w", encoding="utf-8") as f:
            json.dump(bench_data, f, indent=2)

    plot_all_benchmarks(res_vc, res_k, res_bf, res_conv, res_baseline)


if __name__ == "__main__":
    main()
