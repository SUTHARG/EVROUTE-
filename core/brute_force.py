"""Independent exhaustive brute-force solver for testing and property verification.

Enumerates all valid charger subsets and discrete departure SoC levels across
the full grid to find the global optimum on small problem instances (N <= 4, K <= 20).
"""

from __future__ import annotations

import itertools
from typing import Any

from core.bellman_ford import dijkstra, reconstruct_path
from core.charging import charge_time_min
from core.comfort import compute_dwell_discomfort
from core.energy import discretize_soc_level, level_to_soc, simulate_path_soc
from core.models import Car, CorridorSnapshot, RoadEdge, Station, Trip
from core.road_graph import RoadGraph
from ingest.route import haversine_distance_m


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

    # Map each station to its attachment road node
    st_nodes: list[int] = []
    for st in stations:
        if st.road_node_id is not None and st.road_node_id in snapshot.nodes:
            st_nodes.append(st.road_node_id)
        else:
            closest_id = min(
                snapshot.nodes.keys(),
                key=lambda nid: haversine_distance_m(
                    st.lat, st.lon, snapshot.nodes[nid].lat, snapshot.nodes[nid].lon
                ),
            )
            st_nodes.append(closest_id)

    # Edge lookup map
    edge_map = {(e.u, e.v): e for e in road_graph.get_edges()}

    def get_highway_path_edges(u: int, v: int) -> list[RoadEdge]:
        """Compute shortest driving path edges between road nodes u and v."""
        if u == v:
            return []
        _, preds = dijkstra(road_graph, source=u, weight_attr="time_s")
        node_seq = reconstruct_path(preds, target=v)
        edges: list[RoadEdge] = []
        for i in range(len(node_seq) - 1):
            pair = (node_seq[i], node_seq[i + 1])
            if pair in edge_map:
                edges.append(edge_map[pair])
        return edges

    best_J = float("inf")
    best_result: dict[str, Any] = {"feasible": False, "cost_J": float("inf")}

    start_s_lvl = discretize_soc_level(trip.start_soc, K)

    # Enumerate all 2^N subsets of stations to stop and recharge at
    for subset_len in range(n_stations + 1):
        for chosen_indices in itertools.combinations(range(n_stations), subset_len):
            # Milestones sequence: source -> st_i1 -> ... -> st_im -> dest
            # Milestone descriptors: ('source', source_node, None) or ('st', st_node, st_obj) or ('dest', dest_node, None)
            milestones: list[tuple[str, int, Station | None]] = [("source", source_node, None)]
            for idx in chosen_indices:
                milestones.append(("st", st_nodes[idx], stations[idx]))
            milestones.append(("dest", dest_node, None))

            # Build road segments between consecutive milestones including spur detours
            road_segments: list[list[RoadEdge]] = []
            for m in range(len(milestones) - 1):
                m_curr_type, m_curr_node, m_curr_st = milestones[m]
                m_next_type, m_next_node, m_next_st = milestones[m + 1]

                seg_edges: list[RoadEdge] = []

                # 1. Outbound spur from current milestone (if it's a station)
                if (
                    m_curr_type == "st"
                    and m_curr_st is not None
                    and (
                        m_curr_st.detour_time_s > 0
                        or m_curr_st.detour_energy_kwh > 0
                        or m_curr_st.detour_distance_m > 0
                    )
                ):
                    out_d = m_curr_st.detour_distance_m / 2.0
                    out_t = m_curr_st.detour_time_s / 2.0
                    out_e = (
                        m_curr_st.detour_energy_kwh / 2.0
                        if m_curr_st.detour_energy_kwh > 0
                        else (car.consumption_kwh_per_km * (out_d / 1000.0))
                    )
                    seg_edges.append(
                        RoadEdge(
                            u=m_curr_node,
                            v=m_curr_node,
                            length_m=out_d,
                            time_s=max(0.1, out_t),
                            elevation_gain_m=0.0,
                            energy_kwh=out_e,
                        )
                    )

                # 2. Highway edges from m_curr_node to m_next_node
                seg_edges.extend(get_highway_path_edges(m_curr_node, m_next_node))

                # 3. Inbound spur into next milestone (if it's a station)
                if (
                    m_next_type == "st"
                    and m_next_st is not None
                    and (
                        m_next_st.detour_time_s > 0
                        or m_next_st.detour_energy_kwh > 0
                        or m_next_st.detour_distance_m > 0
                    )
                ):
                    in_d = m_next_st.detour_distance_m / 2.0
                    in_t = m_next_st.detour_time_s / 2.0
                    in_e = (
                        m_next_st.detour_energy_kwh / 2.0
                        if m_next_st.detour_energy_kwh > 0
                        else (car.consumption_kwh_per_km * (in_d / 1000.0))
                    )
                    seg_edges.append(
                        RoadEdge(
                            u=m_next_node,
                            v=m_next_node,
                            length_m=in_d,
                            time_s=max(0.1, in_t),
                            elevation_gain_m=0.0,
                            energy_kwh=in_e,
                        )
                    )

                road_segments.append(seg_edges)

            # Driving times
            seg_drive_times_min = [
                sum(e.time_s for e in seg) / 60.0 for seg in road_segments
            ]
            total_drive_time_min = sum(seg_drive_times_min)

            if not chosen_indices:
                # Direct travel without any charging stops
                arr_soc = simulate_path_soc(
                    car, road_segments[0], level_to_soc(start_s_lvl, K), reserve_soc
                )
                if arr_soc is not None:
                    cost_J = total_drive_time_min
                    if cost_J < best_J:
                        best_J = cost_J
                        best_result = {
                            "feasible": True,
                            "cost_J": cost_J,
                            "total_time_min": total_drive_time_min,
                            "total_discomfort_min": 0.0,
                            "stops": [],
                        }
                continue

            # If there are stops, search all discrete departure levels
            def search_charge_levels(
                stop_idx: int,
                curr_dep_lvl: int,
                accum_chg_time: float,
                accum_discomfort: float,
                current_stops: list[dict[str, Any]],
                indices: tuple[int, ...] = chosen_indices,
                segments: list[list[RoadEdge]] = road_segments,
                drive_time: float = total_drive_time_min,
            ) -> None:
                nonlocal best_J, best_result

                # Drive along segment stop_idx to reach the stop (or destination)
                next_seg = segments[stop_idx]
                arr_soc = simulate_path_soc(
                    car, next_seg, level_to_soc(curr_dep_lvl, K), reserve_soc
                )
                if arr_soc is None:
                    return

                arr_lvl = discretize_soc_level(arr_soc, K)

                if stop_idx == len(indices):
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
                            "stops": list(current_stops),
                        }
                    return

                # At stop_idx (0-indexed into indices)
                st_real_idx = indices[stop_idx]
                station = stations[st_real_idx]
                s_in = level_to_soc(arr_lvl, K)

                # Enumerate all discrete departure levels s_dep_lvl > arr_lvl (real charging stops only)
                for s_dep_lvl in range(arr_lvl + 1, K + 1):
                    s_out = level_to_soc(s_dep_lvl, K)
                    t_chg = charge_time_min(s_in, s_out, station.max_kw, car)
                    d_chg = compute_dwell_discomfort(
                        dwell_min=t_chg,
                        amenity_score=station.amenity_score,
                        is_real_charge=True,
                        arrival_soc=s_in,
                        stop_threshold_soc=trip.stop_threshold_soc,
                        gamma=trip.gamma,
                    )

                    stop_record = {
                        "station_id": station.id,
                        "arrival_soc": s_in,
                        "departure_soc": s_out,
                        "charge_time_min": t_chg,
                    }

                    search_charge_levels(
                        stop_idx + 1,
                        s_dep_lvl,
                        accum_chg_time + t_chg,
                        accum_discomfort + d_chg,
                        current_stops + [stop_record],
                        indices=indices,
                        segments=segments,
                        drive_time=drive_time,
                    )

            search_charge_levels(0, start_s_lvl, 0.0, 0.0, [])

    return best_result
