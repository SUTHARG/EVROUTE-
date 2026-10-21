"""Multi-route exhaustive oracle solver for non-chain and general DAG topologies.

Enumerates all acyclic routes from origin to destination, all charger subsets along
each route, and all discrete departure SoC levels, simulating continuous SoC propagation
with capacity clamping and spur detours to find the true global optimum.
"""

from __future__ import annotations

import itertools
from typing import Any

from core.charging import charge_time_min, station_charging_options
from core.comfort import compute_dwell_discomfort
from core.energy import discretize_soc_level, level_to_soc, simulate_path_soc
from core.models import Car, CorridorSnapshot, RoadEdge, Station, Trip
from core.road_graph import RoadGraph


def find_all_acyclic_paths(
    road_graph: RoadGraph, source: int, target: int, visited: set[int] | None = None
) -> list[list[int]]:
    """Enumerate all simple acyclic paths from source to target."""
    if visited is None:
        visited = set()
    if source == target:
        return [[target]]

    visited.add(source)
    paths: list[list[int]] = []

    for edge in road_graph.get_outgoing_edges(source):
        nxt = edge.v
        if nxt not in visited:
            sub_paths = find_all_acyclic_paths(road_graph, nxt, target, visited)
            for sp in sub_paths:
                paths.append([source] + sp)

    visited.remove(source)
    return paths


def solve_multi_route_oracle(
    snapshot: CorridorSnapshot,
    car: Car,
    trip: Trip,
    lambda_val: float = 1.0,
) -> dict[str, Any]:
    """Exhaustive oracle for general / non-chain road graphs."""
    road_graph = RoadGraph.from_snapshot(snapshot)
    source_node = snapshot.source_node_id if snapshot.source_node_id is not None else min(snapshot.nodes.keys())
    dest_node = snapshot.destination_node_id if snapshot.destination_node_id is not None else max(snapshot.nodes.keys())
    K = trip.K
    reserve_soc = trip.reserve_soc

    all_routes = find_all_acyclic_paths(road_graph, source_node, dest_node)

    best_J = float("inf")
    best_result: dict[str, Any] = {"feasible": False, "cost_J": float("inf")}

    start_s_lvl = discretize_soc_level(trip.start_soc, K)
    edge_map = {(e.u, e.v): e for e in road_graph.get_edges()}

    for route_nodes in all_routes:
        # Identify stations attached to nodes along this physical route
        stations_on_route: list[Station] = []
        for st in snapshot.stations:
            if st.road_node_id in route_nodes and st.road_node_id not in (source_node, dest_node):
                stations_on_route.append(st)

        # Sort stations in order of appearance along the route
        node_order = {nid: idx for idx, nid in enumerate(route_nodes)}
        stations_on_route.sort(key=lambda s: node_order.get(s.road_node_id, -1))
        n_st = len(stations_on_route)

        # Enumerate all charger subsets along this route
        for subset_len in range(n_st + 1):
            for chosen_indices in itertools.combinations(range(n_st), subset_len):
                chosen_stations = [stations_on_route[idx] for idx in chosen_indices]

                # Milestones: ('source', source_node, None) -> ('st', st_node, st) -> ('dest', dest_node, None)
                milestones = [("source", source_node, None)]
                for st in chosen_stations:
                    milestones.append(("st", st.road_node_id, st))
                milestones.append(("dest", dest_node, None))

                # Build road segments between consecutive milestones
                road_segments: list[list[RoadEdge]] = []
                for m in range(len(milestones) - 1):
                    m_curr_type, m_curr_node, m_curr_st = milestones[m]
                    m_next_type, m_next_node, m_next_st = milestones[m + 1]

                    seg: list[RoadEdge] = []
                    # 1. Outbound spur from current station
                    if m_curr_type == "st" and m_curr_st is not None:
                        out_d = m_curr_st.detour_distance_m / 2.0
                        out_t = m_curr_st.detour_time_s / 2.0
                        out_e = m_curr_st.detour_energy_kwh / 2.0 if m_curr_st.detour_energy_kwh > 0 else (car.consumption_kwh_per_km * (out_d / 1000.0))
                        seg.append(RoadEdge(u=m_curr_node, v=m_curr_node, length_m=out_d, time_s=max(0.1, out_t), energy_kwh=out_e))

                    # 2. Highway edges along the chosen route between m_curr_node and m_next_node
                    idx_start = route_nodes.index(m_curr_node)
                    idx_end = route_nodes.index(m_next_node)
                    for i in range(idx_start, idx_end):
                        u, v = route_nodes[i], route_nodes[i + 1]
                        if (u, v) in edge_map:
                            seg.append(edge_map[(u, v)])

                    # 3. Inbound spur into next station
                    if m_next_type == "st" and m_next_st is not None:
                        in_d = m_next_st.detour_distance_m / 2.0
                        in_t = m_next_st.detour_time_s / 2.0
                        in_e = m_next_st.detour_energy_kwh / 2.0 if m_next_st.detour_energy_kwh > 0 else (car.consumption_kwh_per_km * (in_d / 1000.0))
                        seg.append(RoadEdge(u=m_next_node, v=m_next_node, length_m=in_d, time_s=max(0.1, in_t), energy_kwh=in_e))

                    road_segments.append(seg)

                seg_drive_times_min = [sum(e.time_s for e in s) / 60.0 for s in road_segments]
                total_drive_time_min = sum(seg_drive_times_min)

                if not chosen_stations:
                    # Direct driving without charging
                    arr_soc = simulate_path_soc(car, road_segments[0], level_to_soc(start_s_lvl, K), reserve_soc)
                    if arr_soc is not None:
                        cost_J = total_drive_time_min
                        if cost_J < best_J:
                            best_J = cost_J
                            best_result = {
                                "feasible": True,
                                "cost_J": cost_J,
                                "total_time_min": total_drive_time_min,
                                "total_discomfort_min": 0.0,
                                "route_nodes": route_nodes,
                                "stops": [],
                            }
                    continue

                def search_levels(
                    stop_idx: int,
                    curr_dep_lvl: int,
                    accum_chg_time: float,
                    accum_discomfort: float,
                    current_stops: list[dict[str, Any]],
                    route: list[int] = route_nodes,
                    segments: list[list[RoadEdge]] = road_segments,
                    drive_time: float = total_drive_time_min,
                    stops_list: list[Station] = chosen_stations,
                ) -> None:
                    nonlocal best_J, best_result

                    next_seg = segments[stop_idx]
                    arr_soc = simulate_path_soc(car, next_seg, level_to_soc(curr_dep_lvl, K), reserve_soc)
                    if arr_soc is None:
                        return

                    arr_lvl = discretize_soc_level(arr_soc, K)

                    if stop_idx == len(stops_list):
                        # Reached destination
                        total_time = drive_time + accum_chg_time
                        cost_J = total_time + lambda_val * accum_discomfort
                        if cost_J < best_J:
                            best_J = cost_J
                            best_result = {
                                "feasible": True,
                                "cost_J": cost_J,
                                "total_time_min": total_time,
                                "total_discomfort_min": accum_discomfort,
                                "route_nodes": route,
                                "stops": list(current_stops),
                            }
                        return

                    st = stops_list[stop_idx]
                    s_in = level_to_soc(arr_lvl, K)

                    for s_dep_lvl in range(arr_lvl + 1, K + 1):
                        s_out = level_to_soc(s_dep_lvl, K)
                        for mode, power_kw in station_charging_options(st, car):
                            t_chg = charge_time_min(s_in, s_out, power_kw, car, mode=mode)
                            d_chg = compute_dwell_discomfort(
                                dwell_min=t_chg,
                                amenity_score=st.amenity_score,
                                is_real_charge=True,
                                arrival_soc=s_in,
                                stop_threshold_soc=trip.stop_threshold_soc,
                                gamma=trip.gamma,
                            )

                            stop_record = {
                                "station_id": st.id,
                                "arrival_soc": s_in,
                                "departure_soc": s_out,
                                "charge_time_min": t_chg,
                                "charging_mode": mode,
                            }

                            search_levels(
                                stop_idx + 1,
                                s_dep_lvl,
                                accum_chg_time + t_chg,
                                accum_discomfort + d_chg,
                                current_stops + [stop_record],
                                route=route,
                                segments=segments,
                                drive_time=drive_time,
                                stops_list=stops_list,
                            )

                search_levels(0, start_s_lvl, 0.0, 0.0, [])

    return best_result
