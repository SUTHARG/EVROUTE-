"""Multi-objective EV route planner using Dijkstra over an explicit 2-layer state graph.

Implements exact scalar DP over state space (node_layer, SoC) with objective
J = time_min + lambda * discomfort_min, generating optimal itineraries and supported
Pareto trade-off frontiers via lambda sweeps.
"""

from __future__ import annotations

import heapq
import time
from typing import Any

from core.charger_graph import ReducedChargerGraph, build_reduced_charger_graph
from core.charging import (
    charge_time_min,
    compute_dwell_window_soc_targets,
    station_charging_options,
)
from core.comfort import compute_dwell_discomfort
from core.energy import discretize_soc_level, level_to_soc
from core.filters import filter_stations_greedy
from core.models import (
    Car,
    ChargingStop,
    CorridorSnapshot,
    ParetoPoint,
    Plan,
    ReducedEdge,
    RoadEdge,
    RoutePoint,
    Trip,
)
from core.road_graph import RoadGraph


def compute_shortest_road_path(
    snapshot: CorridorSnapshot, source_node_id: int, dest_node_id: int
) -> tuple[list[list[float]], list[float]]:
    """Compute physical shortest road path geometry and cumulative distance via Dijkstra.

    Returns (geometry, distances_km). If no path exists, returns empty lists (never sorted node IDs).
    """
    road_graph = RoadGraph.from_snapshot(snapshot)
    if source_node_id not in road_graph.nodes or dest_node_id not in road_graph.nodes:
        return [], []

    dist: dict[int, float] = {source_node_id: 0.0}
    prev: dict[int, tuple[int, RoadEdge]] = {}
    pq: list[tuple[float, int]] = [(0.0, source_node_id)]

    while pq:
        curr_d, u = heapq.heappop(pq)
        if curr_d > dist.get(u, float("inf")):
            continue
        if u == dest_node_id:
            break
        for edge in road_graph.get_outgoing_edges(u):
            new_d = curr_d + edge.length_m
            if new_d < dist.get(edge.v, float("inf")):
                dist[edge.v] = new_d
                prev[edge.v] = (u, edge)
                heapq.heappush(pq, (new_d, edge.v))

    if dest_node_id not in dist and source_node_id != dest_node_id:
        return [], []

    # Reconstruct path
    curr = dest_node_id
    path_edges: list[RoadEdge] = []
    while curr != source_node_id:
        if curr not in prev:
            break
        u, edge = prev[curr]
        path_edges.append(edge)
        curr = u
    path_edges.reverse()

    if not path_edges and source_node_id != dest_node_id:
        return [], []

    geometry: list[list[float]] = []
    distances_km: list[float] = [0.0]
    cum_m = 0.0

    src_node = snapshot.nodes[source_node_id]
    geometry.append([src_node.lat, src_node.lon])

    for edge in path_edges:
        cum_m += edge.length_m
        v_node = snapshot.nodes.get(edge.v)
        if v_node:
            geometry.append([v_node.lat, v_node.lon])
            distances_km.append(round(cum_m / 1000.0, 4))

    return geometry, distances_km


class EVPlanner:
    """Exact scalar DP EV trip planner over explicit 2-layer state graph."""

    def __init__(self) -> None:
        self.last_reduced_graph: ReducedChargerGraph | None = None

    def plan(
        self,
        snapshot: CorridorSnapshot,
        car: Car,
        trip: Trip,
        lambda_val: float | None = None,
        use_all_departure_levels: bool = True,
        enable_filter: bool = True,
        filter_score_threshold: float = 0.35,
        precomputed_reduced_graph: ReducedChargerGraph | None = None,
    ) -> Plan:
        """Compute the optimal EV trip itinerary minimizing J = time + lambda * discomfort.

        Complexity:
            Time: O((|E_c| * K + |V_c| * K^2) * log(|V_c| * K))
            Space: O(|V_c| * K)

        Args:
            snapshot: Offline corridor snapshot holding physical road graph and stations.
            car: Vehicle specifications and charging curve.
            trip: Trip parameters (start_soc, reserve_soc, stop_threshold_soc, gamma).
            lambda_val: Trade-off parameter lambda (defaults to trip.comfort_weight_lambda).
            use_all_departure_levels: If True, evaluates all discrete s_dep > s_arr (exact).
            enable_filter: If True, runs range-preserving greedy charger filtering.
            filter_score_threshold: Quality cutoff threshold for greedy charger filtering.
            precomputed_reduced_graph: Optional pre-built ReducedChargerGraph to avoid recomputation.

        Returns:
            Fully populated Plan with feasibility status, stops, and SoC trajectory.
        """
        active_lambda = lambda_val if lambda_val is not None else trip.comfort_weight_lambda
        K = trip.K

        # Step 1: Identify terminal road nodes
        source_node_id = (
            snapshot.source_node_id
            if snapshot.source_node_id is not None
            else min(snapshot.nodes.keys())
        )
        dest_node_id = (
            snapshot.destination_node_id
            if snapshot.destination_node_id is not None
            else max(snapshot.nodes.keys())
        )

        filter_audit: dict[str, Any] = {}
        if enable_filter:
            src_coord = (snapshot.nodes[source_node_id].lat, snapshot.nodes[source_node_id].lon)
            dst_coord = (snapshot.nodes[dest_node_id].lat, snapshot.nodes[dest_node_id].lon)

            kept_stations, _, filter_audit = filter_stations_greedy(
                stations=snapshot.stations,
                car=car,
                source_coord=src_coord,
                destination_coord=dst_coord,
                start_soc=trip.start_soc,
                reserve_soc=trip.reserve_soc,
                score_threshold=filter_score_threshold,
                supported_connectors=car.supported_connectors,
                road_tortuosity=1.15,
            )
        else:
            kept_stations = list(snapshot.stations)

        # Step 2: Build or reuse reduced 2-layer charger transition graph
        t_build_start = time.perf_counter()
        if precomputed_reduced_graph is not None:
            reduced_graph = precomputed_reduced_graph
            build_time_ms = 0.0
        else:
            road_graph = RoadGraph.from_snapshot(snapshot)
            reduced_graph, _ = build_reduced_charger_graph(
                road_graph=road_graph,
                kept_stations=kept_stations,
                source_node_id=source_node_id,
                dest_node_id=dest_node_id,
                car=car,
                K=K,
                reserve_soc=trip.reserve_soc,
            )
            build_time_ms = (time.perf_counter() - t_build_start) * 1000.0
        self.last_reduced_graph = reduced_graph

        # Step 3: Dijkstra search over explicit state space (node_layer, s)
        start_s = discretize_soc_level(trip.start_soc, K)

        def _run_dijkstra(target_graph: ReducedChargerGraph) -> tuple[
            tuple[str, int] | None,
            float,
            dict[tuple[str, int], float],
            dict[tuple[str, int], tuple[tuple[str, int], Any] | None],
            dict[tuple[str, int], tuple[float, float]],
            int,
            int,
        ]:
            start_state = ("source_dep", start_s)
            d_dist_J: dict[tuple[str, int], float] = {start_state: 0.0}
            d_pred: dict[tuple[str, int], tuple[tuple[str, int], Any] | None] = {start_state: None}
            d_metrics: dict[tuple[str, int], tuple[float, float]] = {start_state: (0.0, 0.0)}

            pq: list[tuple[float, str, int]] = [(0.0, "source_dep", start_s)]
            st_expanded = 0
            ed_relaxed = 0

            while pq:
                curr_J, u_layer, s = heapq.heappop(pq)
                if curr_J > d_dist_J.get((u_layer, s), float("inf")):
                    continue
                st_expanded += 1

                # Case A: At a departed state (e.g. "source_dep" or f"{st_id}_dep") -> DRIVE
                if u_layer.endswith("_dep"):
                    outgoing_edges = target_graph.get_driving_edges(u_layer)
                    for red_edge in outgoing_edges:
                        ed_relaxed += 1
                        arr_soc = red_edge.arrival_soc_table[s]
                        if arr_soc is None:
                            continue

                        s_arr_idx = discretize_soc_level(arr_soc, K)
                        v_arr_layer = f"{red_edge.v}_arr"
                        next_state = (v_arr_layer, s_arr_idx)

                        drive_time_min = red_edge.time_s / 60.0
                        delta_J = drive_time_min
                        new_J = curr_J + delta_J

                        if new_J < d_dist_J.get(next_state, float("inf")) - 1e-9:
                            d_dist_J[next_state] = new_J
                            prev_time, prev_disc = d_metrics[(u_layer, s)]
                            d_metrics[next_state] = (prev_time + drive_time_min, prev_disc)
                            d_pred[next_state] = ((u_layer, s), ("drive", red_edge))
                            heapq.heappush(pq, (new_J, v_arr_layer, s_arr_idx))

                # Case B: At an arrived charger state (e.g. f"{st_id}_arr") -> CHARGE
                elif u_layer.endswith("_arr") and not u_layer.startswith("dest"):
                    st_id = u_layer[:-4]
                    station = target_graph.stations.get(st_id)
                    if not station:
                        continue
                    dep_layer = f"{st_id}_dep"

                    charging_options = station_charging_options(station, car)
                    if not charging_options:
                        continue

                    if use_all_departure_levels:
                        candidate_departure_levels = list(range(s + 1, K + 1))
                    else:
                        targets_set = {round(0.80 * K), K}
                        for mode, power_kw in charging_options:
                            targets_set.update(
                                compute_dwell_window_soc_targets(
                                    level_to_soc(s, K), power_kw, car, K=K, mode=mode
                                )
                            )
                        candidate_departure_levels = [lvl for lvl in sorted(targets_set) if lvl > s]

                    s_in_soc = level_to_soc(s, K)
                    for s_dep_idx in candidate_departure_levels:
                        ed_relaxed += 1
                        s_out_soc = level_to_soc(s_dep_idx, K)
                        for mode, power_kw in charging_options:
                            t_chg = charge_time_min(s_in_soc, s_out_soc, power_kw, car, mode=mode)
                            d_chg = compute_dwell_discomfort(
                                dwell_min=t_chg,
                                amenity_score=station.amenity_score,
                                is_real_charge=True,
                                arrival_soc=s_in_soc,
                                stop_threshold_soc=trip.stop_threshold_soc,
                                gamma=trip.gamma,
                            )

                            delta_J = t_chg + active_lambda * d_chg
                            charge_state = (dep_layer, s_dep_idx)
                            new_J = curr_J + delta_J

                            if new_J < d_dist_J.get(charge_state, float("inf")) - 1e-9:
                                d_dist_J[charge_state] = new_J
                                prev_time, prev_disc = d_metrics[(u_layer, s)]
                                d_metrics[charge_state] = (prev_time + t_chg, prev_disc + d_chg)
                                charge_info = {
                                    "station": station,
                                    "arrival_soc": s_in_soc,
                                    "departure_soc": s_out_soc,
                                    "charge_time_min": t_chg,
                                    "discomfort_min": d_chg,
                                    "charging_mode": mode,
                                    "charging_power_kw": min(power_kw, car.max_ac_kw if mode == "ac" else car.max_dc_kw),
                                }
                                d_pred[charge_state] = ((u_layer, s), ("charge", charge_info))
                                heapq.heappush(pq, (new_J, dep_layer, s_dep_idx))

            d_best_dest_state = None
            d_min_dest_J = float("inf")
            for s_idx in range(K + 1):
                target_key = ("dest_arr", s_idx)
                cost = d_dist_J.get(target_key, float("inf"))
                if cost < d_min_dest_J:
                    d_min_dest_J = cost
                    d_best_dest_state = target_key

            return d_best_dest_state, d_min_dest_J, d_dist_J, d_pred, d_metrics, st_expanded, ed_relaxed

        t_search_start = time.perf_counter()
        best_dest_state, min_dest_J, _dist_J, pred, state_metrics, states_expanded, edges_relaxed = (
            _run_dijkstra(reduced_graph)
        )

        # Candidate Restoration: If filtering was enabled and the trip could not reach destination,
        # verify whether dropped candidate stations would make the road route feasible.
        if (
            (best_dest_state is None or min_dest_J == float("inf"))
            and enable_filter
            and precomputed_reduced_graph is None
        ):
            supported = set(car.supported_connectors) if car.supported_connectors else {"CCS2"}
            restorable_candidates = [
                st
                for st in snapshot.stations
                if any(c in supported for c in st.connector_types) and st.max_kw > 0
            ]
            if len(restorable_candidates) > len(kept_stations):
                t_rebuild_start = time.perf_counter()
                road_graph = RoadGraph.from_snapshot(snapshot)
                restored_reduced_graph, _ = build_reduced_charger_graph(
                    road_graph=road_graph,
                    kept_stations=restorable_candidates,
                    source_node_id=source_node_id,
                    dest_node_id=dest_node_id,
                    car=car,
                    K=K,
                    reserve_soc=trip.reserve_soc,
                )
                build_time_ms += (time.perf_counter() - t_rebuild_start) * 1000.0

                (
                    r_dest_state,
                    r_min_dest_J,
                    _r_dist_J,
                    r_pred,
                    r_metrics,
                    r_expanded,
                    r_relaxed,
                ) = _run_dijkstra(restored_reduced_graph)

                states_expanded += r_expanded
                edges_relaxed += r_relaxed

                if r_dest_state is not None and r_min_dest_J < float("inf"):
                    # Feasible road-route found by restoring candidates!
                    kept_stations = restorable_candidates
                    reduced_graph = restored_reduced_graph
                    self.last_reduced_graph = reduced_graph
                    best_dest_state = r_dest_state
                    min_dest_J = r_min_dest_J
                    pred = r_pred
                    state_metrics = r_metrics
                    filter_audit["candidates_restored"] = True
                    filter_audit["restored_candidate_count"] = len(restorable_candidates)

        if best_dest_state is None or min_dest_J == float("inf"):
            # Diagnostic infeasibility analysis with bridging gap reporting
            if not snapshot.stations:
                reason = "No verified charging stations found for this route"
            else:
                unbridgeable = filter_audit.get("unbridgeable_gap")
                if unbridgeable and not filter_audit.get("candidates_restored"):
                    reason = (
                        f"Trip from {snapshot.source_name} to {snapshot.destination_name} is physically infeasible: "
                        f"unbridgeable gap between {unbridgeable['from_point']} and {unbridgeable['to_point']} "
                        f"({unbridgeable['gap_dist_km']} km, exceeding vehicle range {unbridgeable['allowed_dist_km']} km "
                        f"by {unbridgeable['deficit_km']} km / {unbridgeable['deficit_kwh']} kWh with reserve {trip.reserve_soc:.0%})."
                    )
                else:
                    reason = (
                        f"Trip from {snapshot.source_name} to {snapshot.destination_name} is physically infeasible: "
                        f"vehicle range with reserve {trip.reserve_soc:.0%} is insufficient to bridge charging gaps on the road network."
                    )

            search_time_ms = (time.perf_counter() - t_search_start) * 1000.0
            infeas_geom, infeas_dists = compute_shortest_road_path(snapshot, source_node_id, dest_node_id)

            elevations = [n.elevation_m for n in snapshot.nodes.values()] if snapshot.nodes else []
            elev_avail = bool(elevations and (max(elevations) - min(elevations) > 1.0 or any(e != 0.0 for e in elevations)))

            return Plan(
                trip=trip,
                car=car,
                feasible=False,
                infeasibility_reason=reason,
                build_time_ms=round(build_time_ms, 2),
                search_time_ms=round(search_time_ms, 2),
                states_expanded=states_expanded,
                edges_relaxed=edges_relaxed,
                route_geometry=infeas_geom,
                route_distance_km=infeas_dists,
                elevation_available=elev_avail,
            )

        # Step 5: Backtrack optimal itinerary
        final_time_min, final_disc_min = state_metrics[best_dest_state]
        curr_state = best_dest_state
        action_sequence: list[tuple[str, Any]] = []

        while curr_state is not None:
            prev_info = pred[curr_state]
            if prev_info is None:
                break
            prev_state, action_data = prev_info
            action_sequence.append(action_data)
            curr_state = prev_state

        action_sequence.reverse()

        # Step 6: Construct authentic continuous distance-elevation-SoC trajectory with explicit events
        road_edge_map = {(e.u, e.v): e for e in snapshot.edges}
        profile: list[RoutePoint] = []
        cum_dist_km = 0.0

        src_node = snapshot.nodes.get(source_node_id)
        current_soc = level_to_soc(start_s, K)
        current_battery_kwh = current_soc * car.usable_battery_kwh

        if src_node:
            profile.append(
                RoutePoint(
                    distance_km=0.0,
                    elevation_m=round(src_node.elevation_m, 1),
                    soc=round(current_soc, 4),
                    lat=src_node.lat,
                    lon=src_node.lon,
                    event="drive",
                )
            )

        stops: list[ChargingStop] = []
        driving_edges_traversed: list[ReducedEdge] = []
        charging_time_total = 0.0

        for action, data in action_sequence:
            if action == "drive":
                r_edge: ReducedEdge = data
                driving_edges_traversed.append(r_edge)
                for u_id, v_id in r_edge.road_edge_ids:
                    if (u_id, v_id) in road_edge_map:
                        phys_edge = road_edge_map[(u_id, v_id)]
                        cum_dist_km += phys_edge.length_m / 1000.0
                        current_battery_kwh -= phys_edge.energy_kwh
                        current_battery_kwh = min(car.usable_battery_kwh, current_battery_kwh)
                        current_soc = current_battery_kwh / car.usable_battery_kwh
                        event_name = "regen" if phys_edge.energy_kwh < 0 else "drive"
                        head_node = snapshot.nodes.get(v_id)
                        if head_node:
                            profile.append(
                                RoutePoint(
                                    distance_km=round(cum_dist_km, 3),
                                    elevation_m=round(head_node.elevation_m, 1),
                                    soc=round(current_soc, 4),
                                    lat=head_node.lat,
                                    lon=head_node.lon,
                                    event=event_name,
                                )
                            )
            elif action == "charge":
                chg_st = data["station"]
                charging_time_total += data["charge_time_min"]
                station_highway_km = cum_dist_km

                stops.append(
                    ChargingStop(
                        station_id=chg_st.id,
                        station_name=chg_st.name,
                        operator=chg_st.operator,
                        lat=chg_st.lat,
                        lon=chg_st.lon,
                        arrival_soc=data["arrival_soc"],
                        departure_soc=data["departure_soc"],
                        charge_time_min=data["charge_time_min"],
                        dwell_time_min=data["charge_time_min"],
                        discomfort_min=data["discomfort_min"],
                        amenities=chg_st.amenities,
                        amenity_score=chg_st.amenity_score,
                        reliability=chg_st.reliability,
                        is_reliability_simulated=chg_st.is_reliability_simulated,
                        max_kw=chg_st.max_kw,
                        max_ac_kw=chg_st.max_ac_kw,
                        max_dc_kw=chg_st.max_dc_kw,
                        charging_mode=data.get("charging_mode", "dc"),
                        charging_power_kw=data.get("charging_power_kw", chg_st.max_kw),
                        route_distance_km=round(station_highway_km, 3),
                        charger_count=getattr(chg_st, "charger_count", 1),
                        connector_types=getattr(chg_st, "connector_types", ["CCS2"]),
                        availability=getattr(chg_st, "availability", None),
                        source=getattr(chg_st, "source", "verified_manual"),
                        source_url=getattr(chg_st, "source_url", None),
                        fetched_at=getattr(chg_st, "fetched_at", None),
                        verified=getattr(chg_st, "verified", False),
                        connector_unknown=getattr(chg_st, "connector_unknown", False),
                        power_assumed=getattr(chg_st, "power_assumed", False),
                        connector_assumed=getattr(chg_st, "connector_assumed", False),
                        amenity_known=getattr(chg_st, "amenity_known", False),
                        spur_estimated=getattr(chg_st, "spur_estimated", False),
                    )
                )

                last_elev = profile[-1].elevation_m if profile else 0.0
                spur_half_dist_km = (chg_st.detour_distance_m / 2.0) / 1000.0
                spur_half_energy_kwh = chg_st.detour_energy_kwh / 2.0

                # Spur-in segment to station
                current_battery_kwh -= spur_half_energy_kwh
                current_soc = max(0.0, current_battery_kwh / car.usable_battery_kwh)
                profile.append(
                    RoutePoint(
                        distance_km=round(cum_dist_km + spur_half_dist_km, 3),
                        elevation_m=last_elev,
                        soc=round(current_soc, 4),
                        lat=chg_st.lat,
                        lon=chg_st.lon,
                        event="spur_in",
                    )
                )

                # Charge event: step increase in battery SoC
                dep_soc = data["departure_soc"]
                current_soc = dep_soc
                current_battery_kwh = current_soc * car.usable_battery_kwh
                profile.append(
                    RoutePoint(
                        distance_km=round(cum_dist_km + spur_half_dist_km, 3),
                        elevation_m=last_elev,
                        soc=round(current_soc, 4),
                        lat=chg_st.lat,
                        lon=chg_st.lon,
                        event="charge",
                    )
                )

                # Spur-out segment returning to highway attachment node
                current_battery_kwh -= spur_half_energy_kwh
                current_soc = max(0.0, current_battery_kwh / car.usable_battery_kwh)
                attach_node = snapshot.nodes.get(chg_st.road_node_id) or src_node
                profile.append(
                    RoutePoint(
                        distance_km=round(cum_dist_km + spur_half_dist_km * 2.0, 3),
                        elevation_m=last_elev,
                        soc=round(current_soc, 4),
                        lat=attach_node.lat if attach_node else chg_st.lat,
                        lon=attach_node.lon if attach_node else chg_st.lon,
                        event="spur_out",
                    )
                )
                cum_dist_km += spur_half_dist_km * 2.0

        driving_time_total = sum(e.time_s for e in driving_edges_traversed) / 60.0
        dest_arrival_soc = profile[-1].soc if profile else level_to_soc(best_dest_state[1], K)
        search_time_ms = (time.perf_counter() - t_search_start) * 1000.0

        route_geom = [[pt.lat, pt.lon] for pt in profile]
        route_dists = [pt.distance_km for pt in profile]

        elevations = [n.elevation_m for n in snapshot.nodes.values()] if snapshot.nodes else []
        elev_avail = bool(elevations and (max(elevations) - min(elevations) > 1.0 or any(e != 0.0 for e in elevations)))

        return Plan(
            trip=trip,
            car=car,
            feasible=True,
            total_time_min=final_time_min,
            driving_time_min=driving_time_total,
            charging_time_min=charging_time_total,
            total_discomfort_min=final_disc_min,
            cost_J=min_dest_J,
            build_time_ms=round(build_time_ms, 2),
            search_time_ms=round(search_time_ms, 2),
            states_expanded=states_expanded,
            edges_relaxed=edges_relaxed,
            stops=stops,
            arrival_soc_dest=dest_arrival_soc,
            route_soc_profile=profile,
            route_geometry=route_geom,
            route_distance_km=route_dists,
            elevation_available=elev_avail,
        )

    def sweep_pareto(
        self,
        snapshot: CorridorSnapshot,
        car: Car,
        trip: Trip,
        lambdas: list[float] | None = None,
    ) -> list[ParetoPoint]:
        """Compute the supported Pareto frontier of (time vs comfort) via lambda parameter sweep.

        Builds the reduced charger graph ONCE and reuses it across all lambdas, returning
        only strictly non-dominated trade-off points.

        Complexity:
            Time: O(|lambdas| * Planner_Search_Complexity)
        """
        sweep_lambdas = lambdas or [0.001, 0.05, 0.15, 0.40, 0.80, 1.50, 3.00, 8.00]

        source_node_id = (
            snapshot.source_node_id
            if snapshot.source_node_id is not None
            else min(snapshot.nodes.keys())
        )
        dest_node_id = (
            snapshot.destination_node_id
            if snapshot.destination_node_id is not None
            else max(snapshot.nodes.keys())
        )
        src_coord = (snapshot.nodes[source_node_id].lat, snapshot.nodes[source_node_id].lon)
        dst_coord = (snapshot.nodes[dest_node_id].lat, snapshot.nodes[dest_node_id].lon)

        kept_stations, _, _ = filter_stations_greedy(
            stations=snapshot.stations,
            car=car,
            source_coord=src_coord,
            destination_coord=dst_coord,
            start_soc=trip.start_soc,
            reserve_soc=trip.reserve_soc,
            target_connector=car.supported_connectors[0] if car.supported_connectors else "CCS2",
        )

        # Build reduced charger graph ONCE
        road_graph = RoadGraph.from_snapshot(snapshot)
        reduced_graph, _ = build_reduced_charger_graph(
            road_graph=road_graph,
            kept_stations=kept_stations,
            source_node_id=source_node_id,
            dest_node_id=dest_node_id,
            car=car,
            K=trip.K,
            reserve_soc=trip.reserve_soc,
        )

        raw_points: list[ParetoPoint] = []
        for l_val in sweep_lambdas:
            res_plan = self.plan(
                snapshot=snapshot,
                car=car,
                trip=trip,
                lambda_val=l_val,
                enable_filter=False,
                precomputed_reduced_graph=reduced_graph,
            )
            if not res_plan.feasible:
                continue

            raw_points.append(
                ParetoPoint(
                    lambda_val=l_val,
                    total_time_min=res_plan.total_time_min,
                    total_discomfort_min=res_plan.total_discomfort_min,
                    cost_J=res_plan.cost_J,
                    stops_count=len(res_plan.stops),
                    stop_station_ids=[s.station_id for s in res_plan.stops],
                )
            )

        # Filter to strictly non-dominated Pareto points
        # Sort primarily by increasing total_time_min, secondarily by total_discomfort_min
        raw_points.sort(key=lambda p: (p.total_time_min, p.total_discomfort_min))

        non_dominated: list[ParetoPoint] = []
        min_discomfort = float("inf")

        for pt in raw_points:
            # As time increases, discomfort must strictly decrease to be non-dominated
            if pt.total_discomfort_min < min_discomfort - 1e-4:
                non_dominated.append(pt)
                min_discomfort = pt.total_discomfort_min

        return non_dominated
