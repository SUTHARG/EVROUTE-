"""Empirical study evaluating the 20/40-minute dwell heuristic targets against the full departure set.

Runs >=100 random synthetic instances with varying parameters and records:
- Cost gap (mean, max)
- Speedup factor (mean, median)
- Feasibility preservation
"""

from __future__ import annotations

import random
import time
from typing import Any

from core.models import Car, Trip
from core.planner import EVPlanner
from ingest.synthetic import generate_synthetic_corridor


def run_heuristic_dwell_study(num_instances: int = 100) -> dict[str, Any]:
    rng = random.Random(42)
    planner = EVPlanner()

    cost_gaps: list[float] = []
    speedups: list[float] = []
    time_full_list: list[float] = []
    time_heur_list: list[float] = []

    print(f"[*] Running heuristic dwell target study over {num_instances} random instances...")

    evaluated = 0
    both_feasible = 0

    for i in range(num_instances):
        battery_kwh = rng.uniform(20.0, 45.0)
        usable_frac = 0.95
        consumption = rng.uniform(0.14, 0.17)
        dist_km = rng.uniform(90.0, 160.0)
        n_stations = rng.randint(3, 5)
        start_soc = rng.uniform(0.25, 0.60)
        lambda_val = rng.uniform(0.5, 3.0)
        K = rng.choice([20, 25, 30, 40])  # Discretization resolution

        car = Car(
            id=f"test_car_{i}",
            name=f"Study Car {i}",
            battery_kwh=battery_kwh,
            usable_fraction=usable_frac,
            consumption_kwh_per_km=consumption,
            mass_kg=1300.0,
            drag_coefficient=0.30,
            frontal_area_m2=2.20,
            max_dc_kw=60.0,
            regen_efficiency=0.75,
        )

        snapshot = generate_synthetic_corridor(
            total_distance_km=dist_km,
            num_road_segments=20,
            num_stations=n_stations,
            seed=1000 + i,
            car=car,
        )

        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=start_soc,
            reserve_soc=0.10,
            stop_threshold_soc=0.35,
            comfort_weight_lambda=lambda_val,
            K=K,
        )

        # 1. Exact full departure search
        t0 = time.perf_counter()
        plan_full = planner.plan(snapshot, car, trip, lambda_val=lambda_val, use_all_departure_levels=True, enable_filter=False)
        t_full = time.perf_counter() - t0

        # 2. Heuristic 20/40-min dwell targets
        t1 = time.perf_counter()
        plan_heur = planner.plan(snapshot, car, trip, lambda_val=lambda_val, use_all_departure_levels=False, enable_filter=False)
        t_heur = time.perf_counter() - t1

        evaluated += 1

        if plan_full.feasible and plan_heur.feasible:
            both_feasible += 1
            gap = max(0.0, plan_heur.cost_J - plan_full.cost_J)
            speedup = t_full / max(1e-6, t_heur)

            cost_gaps.append(gap)
            speedups.append(speedup)
            time_full_list.append(t_full)
            time_heur_list.append(t_heur)

    mean_gap = sum(cost_gaps) / len(cost_gaps) if cost_gaps else 0.0
    max_gap = max(cost_gaps) if cost_gaps else 0.0
    mean_speedup = sum(speedups) / len(speedups) if speedups else 1.0
    sorted_speedups = sorted(speedups)
    median_speedup = sorted_speedups[len(sorted_speedups) // 2] if sorted_speedups else 1.0

    print("=" * 70)
    print("HEURISTIC DWELL TARGETS BENCHMARK REPORT")
    print("=" * 70)
    print(f"Total Evaluated Instances: {evaluated}")
    print(f"Feasible Instances:        {both_feasible} / {evaluated}")
    print(f"Mean Cost Gap:             {mean_gap:.4f} min")
    print(f"Max Cost Gap:              {max_gap:.4f} min")
    print(f"Mean Speedup Factor:       {mean_speedup:.2f}x")
    print(f"Median Speedup Factor:     {median_speedup:.2f}x")
    print("=" * 70)
    print("Classification: Documented as an optional heuristic speedup optimization.")
    print("When exact optimality is required, the full departure search must be used.")
    print("=" * 70)

    return {
        "evaluated": evaluated,
        "both_feasible": both_feasible,
        "mean_gap": mean_gap,
        "max_gap": max_gap,
        "mean_speedup": mean_speedup,
        "median_speedup": median_speedup,
    }


if __name__ == "__main__":
    run_heuristic_dwell_study(100)
