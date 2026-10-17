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

        results.append({
            "V_c": n_stat,
            "build_ms": round(avg_build_ms, 2),
            "search_ms": round(avg_search_ms, 2),
            "total_ms": round(avg_total_ms, 2),
        })
        vcs.append(float(n_stat))
        search_times.append(avg_search_ms)
        print(
            f"|V_c| = {n_stat:>2} chargers | Build: {avg_build_ms:>5.2f} ms | "
            f"Search: {avg_search_ms:>5.2f} ms | Total: {avg_total_ms:>6.2f} ms"
        )

    slope_vc = fit_log_log_slope(vcs, search_times)
    print(f"[+] Fitted log-log slope for search time vs |V_c|: {slope_vc:.2f} (theoretical O(|V_c|^2) = 2.0)")

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
) -> tuple[float, float]:
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
    station_at_node = {st.road_node_id: st for st in snapshot.stations}

    t0 = time.perf_counter()
    dist: dict[tuple[int, int], float] = {(source_node, start_s): 0.0}
    pq: list[tuple[float, int, int]] = [(0.0, source_node, start_s)]

    best_dest_cost = float("inf")

    while pq:
        curr_d, u, s = heapq.heappop(pq)
        if curr_d > dist.get((u, s), float("inf")):
            continue

        if u == dest_node:
            best_dest_cost = min(best_dest_cost, curr_d)

        # 1. Drive along outgoing road edges
        for edge in road_graph.get_outgoing_edges(u):
            v = edge.v
            # Energy consumption along edge
            edge_soc_delta = edge.energy_kwh / car.usable_battery_kwh
            s_frac = level_to_soc(s, K) - edge_soc_delta
            s_frac = min(1.0, s_frac)

            if s_frac + 1e-9 < trip.reserve_soc:
                continue

            s_next = discretize_soc_level(s_frac, K)
            drive_time_min = edge.time_s / 60.0
            new_cost = curr_d + drive_time_min

            if new_cost < dist.get((v, s_next), float("inf")) - 1e-9:
                dist[(v, s_next)] = new_cost
                heapq.heappush(pq, (new_cost, v, s_next))

        # 2. Charge at station if present at node u
        if u in station_at_node:
            station = station_at_node[u]
            s_arr_soc = level_to_soc(s, K)

            for s_dep in range(s + 1, K + 1):
                s_dep_soc = level_to_soc(s_dep, K)
                t_chg = charge_time_min(
                    s_in=s_arr_soc,
                    s_out=s_dep_soc,
                    station_max_kw=station.max_kw,
                    car=car,
                )
                d_chg = compute_dwell_discomfort(
                    dwell_min=t_chg,
                    amenity_score=station.amenity_score,
                    is_real_charge=True,
                    arrival_soc=s_arr_soc,
                    stop_threshold_soc=trip.stop_threshold_soc,
                    gamma=trip.gamma,
                )
                chg_cost = t_chg + lambda_val * d_chg
                new_cost = curr_d + chg_cost

                if new_cost < dist.get((u, s_dep), float("inf")) - 1e-9:
                    dist[(u, s_dep)] = new_cost
                    heapq.heappush(pq, (new_cost, u, s_dep))

    runtime_ms = (time.perf_counter() - t0) * 1000.0
    return best_dest_cost, runtime_ms


def benchmark_full_road_graph_vs_reduced() -> dict[str, Any]:
    """Benchmark DP on uncontracted full road graph vs contracted 2-layer charger graph."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    K = 30

    snapshot = generate_synthetic_corridor(
        total_distance_km=160.0,
        num_road_segments=60,
        num_stations=6,
        seed=777,
        car=car,
    )
    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.45,
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        comfort_weight_lambda=0.0,
        K=K,
    )

    print("\n--- Benchmark 5: Full Road Graph DP vs Contracted Charger Graph DP ---")
    print(f"Graph size: |V_road| = {len(snapshot.nodes)} nodes, |V_c| = {len(snapshot.stations)} stations, K = {K}")

    # 1. Contracted 2-layer charger graph DP
    trials = 5
    t_search_sum = 0.0
    plan = None
    for _ in range(trials):
        plan = planner.plan(snapshot, car, trip, lambda_val=0.0, enable_filter=False)
        t_search_sum += plan.search_time_ms
    contracted_search_ms = t_search_sum / trials
    contracted_cost = plan.cost_J if plan else float("inf")

    # 2. Uncontracted full road graph DP
    trials_full = 3
    t_full_sum = 0.0
    full_cost = 0.0
    for _ in range(trials_full):
        full_cost, r_ms = solve_full_road_graph_dp(snapshot, car, trip, lambda_val=0.0)
        t_full_sum += r_ms
    full_road_ms = t_full_sum / trials_full

    speedup = full_road_ms / max(0.01, contracted_search_ms)

    print(f"Contracted Charger Graph DP Search: {contracted_search_ms:>6.2f} ms | Cost: {contracted_cost:.2f} min")
    print(f"Uncontracted Full Road Graph DP:     {full_road_ms:>6.2f} ms | Cost: {full_cost:.2f} min")
    print(f"[+] Empirical Search Speedup via Contraction: {speedup:.1f}x")

    return {
        "V_road": len(snapshot.nodes),
        "V_c": len(snapshot.stations),
        "K": K,
        "contracted_search_ms": round(contracted_search_ms, 2),
        "full_road_ms": round(full_road_ms, 2),
        "speedup": round(speedup, 1),
        "costs_consistent": abs(contracted_cost - full_cost) < 5.0,
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

    plot_all_benchmarks(res_vc, res_k, res_bf, res_conv, res_baseline)


if __name__ == "__main__":
    main()
