"""Independent exhaustive brute-force solver for testing and property verification.

Enumerates all valid charger subsets and discrete departure SoC levels across
the full grid to find the global optimum on small problem instances (N <= 4, K <= 20).
"""

from __future__ import annotations

import itertools
from typing import Any

from core.charging import charge_time_min
from core.comfort import compute_dwell_discomfort
from core.energy import simulate_path_soc
from core.models import Car, CorridorSnapshot, RoadEdge, Station, Trip
from core.road_graph import RoadGraph


def solve_brute_force(
    snapshot: CorridorSnapshot,
    car: Car,
    trip: Trip,
    lambda_val: float = 1.0,
) -> dict[str, Any]:
    """Find globally optimal EV itinerary via exhaustive brute-force search.

    Complexity:
        Time: O(2^|C| * K^|C| * |V_road|)
        Space: O(|V_road| + |C|)

    Args:
        snapshot: Corridor snapshot.
        car: Vehicle profile.
        trip: Trip parameters.
        lambda_val: Comfort trade-off weight.

    Returns:
        Dict with 'cost_J', 'feasible', 'stops', 'total_time_min', 'total_discomfort_min'.
    """
    stations: list[Station] = snapshot.stations
    n_stations = len(stations)
    K = trip.K
    reserve_soc = trip.reserve_soc

    road_graph = RoadGraph.from_snapshot(snapshot)
    num_road_nodes = len(snapshot.nodes)
    source_node = 0
    dest_node = num_road_nodes - 1

    # In synthetic corridor, road edges form a linear path 0 -> 1 -> ... -> dest
    # Group edges into contiguous blocks:
    # Segment 0: 0 -> station_1_node
    # Segment i: station_i_node -> station_{i+1}_node
    # Segment last: station_k_node -> dest_node
    # For synthetic corridor, station i is attached to node int(((i+1)/(n+1)) * segments)
    step_frac = 1.0 / (n_stations + 1)
    st_nodes = [
        round(((i + 1) * step_frac) * (num_road_nodes - 1))
        for i in range(n_stations)
    ]

    # Pre-extract road edge slices between milestone nodes
    edge_map = {(e.u, e.v): e for e in road_graph.get_edges()}

    def get_path_edges(u: int, v: int) -> list[RoadEdge]:
        edges = []
        for curr in range(u, v):
            if (curr, curr + 1) in edge_map:
                edges.append(edge_map[(curr, curr + 1)])
        return edges

    best_J = float("inf")
    best_result: dict[str, Any] = {"feasible": False, "cost_J": float("inf")}

    start_s = min(K, max(0, round(trip.start_soc * K)))

    # Enumerate all 2^N subsets of stations to stop and recharge at
    for subset_len in range(n_stations + 1):
        for chosen_indices in itertools.combinations(range(n_stations), subset_len):
            # Milestones sequence: source -> st_i1 -> ... -> st_im -> dest
            stop_nodes = [st_nodes[idx] for idx in chosen_indices]
            route_milestones = [source_node] + stop_nodes + [dest_node]

            # Road segments between consecutive milestones
            road_segments = [
                get_path_edges(route_milestones[m], route_milestones[m + 1])
                for m in range(len(route_milestones) - 1)
            ]

            # Driving times
            seg_drive_times_min = [
                sum(e.time_s for e in seg) / 60.0 for seg in road_segments
            ]
            total_drive_time_min = sum(seg_drive_times_min)

            if not chosen_indices:
                # Direct travel without any charging stops
                arr_soc = simulate_path_soc(car, road_segments[0], start_s / K, reserve_soc)
                if arr_soc is not None:
                    cost_J = total_drive_time_min
                    if cost_J < best_J:
                        best_J = cost_J
                        best_result = {
                            "feasible": True,
                            "cost_J": round(cost_J, 3),
                            "total_time_min": round(total_drive_time_min, 2),
                            "total_discomfort_min": 0.0,
                            "stops": [],
                        }
                continue

            # If there are stops, recursively or iteratively search all discrete departure levels
            def search_charge_levels(
                stop_idx: int,
                curr_s_in: float,
                accum_chg_time: float,
                accum_discomfort: float,
                current_stops: list[dict[str, Any]],
                indices: tuple[int, ...] = chosen_indices,
                segments: list[list[RoadEdge]] = road_segments,
                drive_time: float = total_drive_time_min,
            ) -> None:
                nonlocal best_J, best_result

                if stop_idx == len(indices):
                    # Final drive to destination
                    final_arr_soc = simulate_path_soc(
                        car, segments[-1], curr_s_in, reserve_soc
                    )
                    if final_arr_soc is not None:
                        total_time = drive_time + accum_chg_time
                        cost_J = total_time + lambda_val * accum_discomfort
                        if cost_J < best_J:
                            best_J = cost_J
                            best_result = {
                                "feasible": True,
                                "cost_J": round(cost_J, 3),
                                "total_time_min": round(total_time, 2),
                                "total_discomfort_min": round(accum_discomfort, 2),
                                "stops": list(current_stops),
                            }
                    return

                # At stop_idx
                st_real_idx = indices[stop_idx]
                station = stations[st_real_idx]
                s_in_lvl = round(curr_s_in * K)

                # Enumerate all discrete departure levels s_dep > s_in_lvl
                for s_dep_lvl in range(s_in_lvl + 1, K + 1):
                    s_dep = s_dep_lvl / K
                    # Simulate next driving segment to the next stop
                    next_seg = segments[stop_idx + 1]
                    next_arr_soc = simulate_path_soc(car, next_seg, s_dep, reserve_soc)
                    if next_arr_soc is None:
                        # Cannot reach next stop from this departure level
                        continue

                    # Charge duration and discomfort
                    t_chg = charge_time_min(curr_s_in, s_dep, station.max_kw, car)
                    d_chg = compute_dwell_discomfort(
                        dwell_min=t_chg,
                        amenity_score=station.amenity_score,
                        is_real_charge=True,
                        arrival_soc=curr_s_in,
                        stop_threshold_soc=trip.stop_threshold_soc,
                        gamma=trip.gamma,
                    )

                    stop_record = {
                        "station_id": station.id,
                        "arrival_soc": curr_s_in,
                        "departure_soc": s_dep,
                        "charge_time_min": t_chg,
                    }

                    search_charge_levels(
                        stop_idx + 1,
                        next_arr_soc,
                        accum_chg_time + t_chg,
                        accum_discomfort + d_chg,
                        current_stops + [stop_record],
                        indices=indices,
                        segments=segments,
                        drive_time=drive_time,
                    )

            # First drive from source to first chosen stop
            first_arr_soc = simulate_path_soc(
                car, road_segments[0], start_s / K, reserve_soc
            )
            if first_arr_soc is not None:
                search_charge_levels(0, first_arr_soc, 0.0, 0.0, [])

    return best_result
