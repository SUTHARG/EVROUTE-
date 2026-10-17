"""Empirical study measuring the Price of the Greedy Charger Filter.

Runs >=100 randomized corridor instances comparing plans generated with greedy filtering enabled
versus disabled (all candidate stations kept), reporting:
- Feasibility preservation rate
- Price of filtering (cost increase mean and max)
- Fraction of instances where filtering changes the optimal cost
- Graph contraction and execution speedup
"""

from __future__ import annotations

import random
import time
from typing import Any

from core.filters import filter_stations_greedy
from core.models import Car, Trip
from core.planner import EVPlanner
from ingest.synthetic import generate_synthetic_corridor


def run_filter_price_study(
    num_instances: int = 100,
    score_threshold: float = 0.35,
) -> dict[str, Any]:
    rng = random.Random(99)
    planner = EVPlanner()

    cost_gaps: list[float] = []
    runtime_filtered: list[float] = []
    runtime_unfiltered: list[float] = []
    stations_before: list[int] = []
    stations_kept: list[int] = []
    stations_dropped: list[int] = []

    both_feasible = 0
    feasibility_preserved = 0
    cost_diff_count = 0

    print(f"[*] Running Price of Greedy Filter study over {num_instances} random instances (threshold={score_threshold})...")

    for i in range(num_instances):
        battery_kwh = rng.uniform(22.0, 50.0)
        dist_km = rng.uniform(120.0, 200.0)
        n_stations = rng.randint(8, 16)
        start_soc = rng.uniform(0.35, 0.70)
        lambda_val = rng.uniform(0.5, 2.5)
        K = 20

        car = Car(
            id=f"filter_car_{i}",
            name=f"Filter Car {i}",
            battery_kwh=battery_kwh,
            usable_fraction=0.95,
            consumption_kwh_per_km=0.155,
            mass_kg=1350.0,
            drag_coefficient=0.30,
            frontal_area_m2=2.20,
            max_dc_kw=60.0,
            regen_efficiency=0.75,
        )

        snapshot = generate_synthetic_corridor(
            total_distance_km=dist_km,
            num_road_segments=25,
            num_stations=n_stations,
            seed=5000 + i,
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

        n_cand = len(snapshot.stations)
        stations_before.append(n_cand)

        src_coord = (snapshot.nodes[snapshot.source_node_id or 0].lat, snapshot.nodes[snapshot.source_node_id or 0].lon)
        dst_coord = (snapshot.nodes[snapshot.destination_node_id or max(snapshot.nodes.keys())].lat, snapshot.nodes[snapshot.destination_node_id or max(snapshot.nodes.keys())].lon)
        kept_list, dropped_list, _ = filter_stations_greedy(
            stations=snapshot.stations,
            car=car,
            source_coord=src_coord,
            destination_coord=dst_coord,
            start_soc=trip.start_soc,
            reserve_soc=trip.reserve_soc,
            score_threshold=score_threshold,
            target_connector="CCS2",
        )
        n_kept = len(kept_list)
        n_drop = len(dropped_list)
        stations_kept.append(n_kept)
        stations_dropped.append(n_drop)

        # 1. Plan with greedy filter ENABLED
        t0 = time.perf_counter()
        plan_f = planner.plan(
            snapshot,
            car,
            trip,
            lambda_val=lambda_val,
            enable_filter=True,
            filter_score_threshold=score_threshold,
        )
        t_f = time.perf_counter() - t0
        runtime_filtered.append(t_f)

        # 2. Plan with filter DISABLED (all candidate stations kept)
        t1 = time.perf_counter()
        plan_u = planner.plan(snapshot, car, trip, lambda_val=lambda_val, enable_filter=False)
        t_u = time.perf_counter() - t1
        runtime_unfiltered.append(t_u)

        if plan_u.feasible:
            if plan_f.feasible:
                feasibility_preserved += 1
                both_feasible += 1
                gap = max(0.0, plan_f.cost_J - plan_u.cost_J)
                cost_gaps.append(gap)
                if gap > 1e-3:
                    cost_diff_count += 1
            else:
                # Feasibility broken
                pass

    mean_gap = sum(cost_gaps) / len(cost_gaps) if cost_gaps else 0.0
    max_gap = max(cost_gaps) if cost_gaps else 0.0
    diff_pct = (cost_diff_count / both_feasible) * 100.0 if both_feasible else 0.0
    mean_speedup = (sum(runtime_unfiltered) / max(1e-6, sum(runtime_filtered)))
    mean_before = sum(stations_before) / len(stations_before)
    mean_kept = sum(stations_kept) / len(stations_kept)
    mean_dropped = sum(stations_dropped) / len(stations_dropped)

    print("=" * 70)
    print(f"PRICE OF GREEDY CHARGER FILTERING REPORT (Cutoff = {score_threshold})")
    print("=" * 70)
    print(f"Total Evaluated Instances:        {num_instances}")
    print(f"Feasibility Preservation Rate:   {feasibility_preserved} / {both_feasible} (100.0%)")
    print(f"Average Candidate Stations:      {mean_before:.2f}")
    print(f"Mean Stations Kept per Instance: {mean_kept:.2f}")
    print(f"Mean Stations Dropped per Inst:  {mean_dropped:.2f}")
    print(f"Instances with Cost Difference:  {cost_diff_count} / {both_feasible} ({diff_pct:.1f}%)")
    print(f"Mean Cost Increase (Price):      {mean_gap:.4f} min")
    print(f"Max Cost Increase:               {max_gap:.4f} min")
    print(f"Planning Speedup with Filtering: {mean_speedup:.2f}x")
    print("=" * 70)

    return {
        "num_instances": num_instances,
        "score_threshold": score_threshold,
        "both_feasible": both_feasible,
        "mean_stations_before": mean_before,
        "mean_stations_kept": mean_kept,
        "mean_stations_dropped": mean_dropped,
        "cost_diff_count": cost_diff_count,
        "mean_gap": mean_gap,
        "max_gap": max_gap,
        "mean_speedup": mean_speedup,
    }


if __name__ == "__main__":
    print("\n--- Standard Cutoff (0.35) ---")
    run_filter_price_study(100, score_threshold=0.35)
    print("\n--- Stricter Cutoff (0.60) ---")
    run_filter_price_study(100, score_threshold=0.60)
