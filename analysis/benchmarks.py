"""Comprehensive algorithmic benchmarks for Route.ev:
1. Runtime vs |V_c| (charger count)
2. Runtime vs K (discretization resolution)
3. Brute Force vs DP runtime comparison
4. K-convergence of plan cost J(K)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from core.brute_force import solve_brute_force
from core.models import PRESET_CARS, Trip
from core.planner import EVPlanner
from ingest.synthetic import generate_synthetic_corridor


def benchmark_runtime_vs_vc() -> list[dict[str, Any]]:
    """Benchmark DP planner runtime as a function of candidate charger count |V_c|."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    K = 50
    vc_counts = [2, 4, 6, 8, 10, 12, 16, 20]
    results = []

    print("\n--- Benchmark 1: Runtime vs |V_c| (K = 50, Distance = 180 km) ---")
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
        t0 = time.perf_counter()
        for _ in range(trials):
            _ = planner.plan(snapshot, car, trip, enable_filter=False)
        avg_ms = ((time.perf_counter() - t0) / trials) * 1000.0

        results.append({"V_c": n_stat, "runtime_ms": round(avg_ms, 2)})
        print(f"|V_c| = {n_stat:>2} chargers | Runtime: {avg_ms:>6.2f} ms")

    return results


def benchmark_runtime_vs_k() -> list[dict[str, Any]]:
    """Benchmark DP planner runtime as a function of SoC resolution K."""
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
        t0 = time.perf_counter()
        for _ in range(trials):
            _ = planner.plan(snapshot, car, trip, enable_filter=False)
        avg_ms = ((time.perf_counter() - t0) / trials) * 1000.0

        results.append({"K": k, "runtime_ms": round(avg_ms, 2)})
        print(f"K = {k:>3} intervals | Runtime: {avg_ms:>6.2f} ms")

    return results


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

        # DP runtime
        trials_dp = 10
        t0 = time.perf_counter()
        for _ in range(trials_dp):
            p_plan = planner.plan(snapshot, car, trip, enable_filter=False)
        dp_ms = ((time.perf_counter() - t0) / trials_dp) * 1000.0

        # BF runtime
        t1 = time.perf_counter()
        bf_res = solve_brute_force(snapshot, car, trip)
        bf_ms = (time.perf_counter() - t1) * 1000.0

        speedup = bf_ms / max(0.01, dp_ms)
        cost_match = abs(p_plan.cost_J - bf_res["cost_J"]) < 1e-4 if p_plan.feasible and bf_res["feasible"] else True

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
    """Benchmark K-convergence of plan cost J(K)."""
    car = PRESET_CARS["tata_nexon_ev_lr"]
    planner = EVPlanner()
    k_values = [10, 15, 20, 30, 50, 75, 100, 150, 200, 300]
    results = []

    snapshot = generate_synthetic_corridor(
        total_distance_km=145.0,
        num_road_segments=25,
        num_stations=4,
        seed=333,
        car=car,
    )

    print("\n--- Benchmark 4: K-Convergence of Plan Cost J(K) (lambda = 0.0) ---")
    costs = {}
    for k in k_values:
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

    j_ref = costs[300]
    for k in k_values:
        diff = abs(costs[k] - j_ref)
        results.append({
            "K": k,
            "cost_J": round(costs[k], 4),
            "abs_error_vs_K300": round(diff, 4),
        })
        print(f"K = {k:>3} | Cost J = {costs[k]:>8.4f} min | |J(K) - J(300)| = {diff:>6.4f} min")

    return results


def plot_all_benchmarks(
    res_vc: list[dict[str, Any]],
    res_k: list[dict[str, Any]],
    res_bf: list[dict[str, Any]],
    res_conv: list[dict[str, Any]],
) -> None:
    """Generate high-resolution benchmark plots."""
    out_dir = Path("analysis/plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Runtime vs |V_c|
    plt.figure(figsize=(7, 4.5), dpi=150)
    vcs = [r["V_c"] for r in res_vc]
    times_vc = [r["runtime_ms"] for r in res_vc]
    plt.plot(vcs, times_vc, marker="o", color="#2563eb", linewidth=2.0)
    plt.title("DP Planner Runtime vs Candidate Charger Count |V_c| (K = 50)")
    plt.xlabel("Number of Candidate Chargers |V_c|")
    plt.ylabel("Execution Time (ms)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_runtime_vc.png")
    plt.close()

    # 2. Runtime vs K
    plt.figure(figsize=(7, 4.5), dpi=150)
    ks = [r["K"] for r in res_k]
    times_k = [r["runtime_ms"] for r in res_k]
    plt.plot(ks, times_k, marker="s", color="#059669", linewidth=2.0)
    plt.title("DP Planner Runtime vs SoC Discretization Resolution K (|V_c| = 5)")
    plt.xlabel("SoC Discretization Intervals K")
    plt.ylabel("Execution Time (ms)")
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

    # 4. K-Convergence
    plt.figure(figsize=(7, 4.5), dpi=150)
    ks_c = [r["K"] for r in res_conv]
    costs_c = [r["cost_J"] for r in res_conv]
    plt.plot(ks_c, costs_c, marker="d", color="#7c3aed", linewidth=2.0)
    plt.axhline(res_conv[-1]["cost_J"], color="#94a3b8", linestyle="--", label=f"J(K=300) = {res_conv[-1]['cost_J']:.2f} min")
    plt.title("K-Convergence of Optimal Plan Cost J(K)")
    plt.xlabel("SoC Discretization Intervals K")
    plt.ylabel("Optimal Itinerary Cost J (min)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_dir / "benchmark_k_convergence.png")
    plt.close()

    print(f"\n[+] All 4 benchmark plots successfully generated in: {out_dir}")


def main():
    res_vc = benchmark_runtime_vs_vc()
    res_k = benchmark_runtime_vs_k()
    res_bf = benchmark_bf_vs_dp()
    res_conv = benchmark_k_convergence()

    # Save benchmark data as JSON
    bench_data = {
        "runtime_vs_vc": res_vc,
        "runtime_vs_k": res_k,
        "bf_vs_dp": res_bf,
        "k_convergence": res_conv,
    }
    with open("analysis/benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(bench_data, f, indent=2)

    plot_all_benchmarks(res_vc, res_k, res_bf, res_conv)


if __name__ == "__main__":
    main()
