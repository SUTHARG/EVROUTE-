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
from core.charging import charge_time_min
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
    RoutePoint,
    Trip,
)
from core.road_graph import RoadGraph


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
                target_connector=car.supported_connectors[0] if car.supported_connectors else "CCS2",
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
        t_search_start = time.perf_counter()
        # States are strings: "u_layer:s" where u_layer in {"source_dep", "dest_arr", f"{st_id}_arr", f"{st_id}_dep"}
        # and s in {0, ..., K}
        start_s = discretize_soc_level(trip.start_soc, K)
        start_state = ("source_dep", start_s)

        dist_J: dict[tuple[str, int], float] = {start_state: 0.0}
        pred: dict[tuple[str, int], tuple[tuple[str, int], Any] | None] = {start_state: None}
        state_metrics: dict[tuple[str, int], tuple[float, float]] = {start_state: (0.0, 0.0)}

        # Min-heap stores (cost_J, node_layer, s)
        pq: list[tuple[float, str, int]] = [(0.0, "source_dep", start_s)]
        states_expanded = 0
        edges_relaxed = 0

        while pq:
            curr_J, u_layer, s = heapq.heappop(pq)

            if curr_J > dist_J.get((u_layer, s), float("inf")):
                continue

            states_expanded += 1

            # Case A: At a departed state (e.g. "source_dep" or f"{st_id}_dep") -> DRIVE
            if u_layer.endswith("_dep"):
                outgoing_edges = reduced_graph.get_driving_edges(u_layer)
                for red_edge in outgoing_edges:
                    edges_relaxed += 1
                    arr_soc = red_edge.arrival_soc_table[s]
                    if arr_soc is None:
                        # Infeasible: battery drops below reserve along this edge
                        continue

                    s_arr_idx = discretize_soc_level(arr_soc, K)
                    v_arr_layer = f"{red_edge.v}_arr"
                    next_state = (v_arr_layer, s_arr_idx)

                    drive_time_min = red_edge.time_s / 60.0
                    delta_J = drive_time_min  # zero discomfort while driving

                    new_J = curr_J + delta_J
                    if new_J < dist_J.get(next_state, float("inf")) - 1e-9:
                        dist_J[next_state] = new_J
                        prev_time, prev_disc = state_metrics[(u_layer, s)]
                        state_metrics[next_state] = (prev_time + drive_time_min, prev_disc)
                        pred[next_state] = ((u_layer, s), ("drive", red_edge))
                        heapq.heappush(pq, (new_J, v_arr_layer, s_arr_idx))

            # Case B: At an arrived charger state (e.g. f"{st_id}_arr") -> PASS-THROUGH OR CHARGE
            elif u_layer.endswith("_arr") and not u_layer.startswith("dest"):
                st_id = u_layer[:-4]
                station = reduced_graph.stations.get(st_id)
                if not station:
                    continue

                dep_layer = f"{st_id}_dep"

                # Real charge transitions: (st_arr, s) -> (st_dep, s_dep) for s_dep > s
                # Uncharged visits are disallowed because entering a station incurs a physical spur detour.
                # If a station is not used for charging, the vehicle stays on the highway via direct reduced edges.
                if use_all_departure_levels:
                    candidate_departure_levels = list(range(s + 1, K + 1))
                else:
                    from core.charging import compute_dwell_window_soc_targets
                    targets_set = {round(0.80 * K), K}
                    dwell_targets = compute_dwell_window_soc_targets(
                        level_to_soc(s, K), station.max_kw, car, K=K
                    )
                    targets_set.update(dwell_targets)
                    candidate_departure_levels = [lvl for lvl in sorted(targets_set) if lvl > s]

                s_in_soc = level_to_soc(s, K)
                for s_dep_idx in candidate_departure_levels:
                    edges_relaxed += 1
                    s_out_soc = level_to_soc(s_dep_idx, K)
                    t_chg = charge_time_min(s_in_soc, s_out_soc, station.max_kw, car)
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

                    if new_J < dist_J.get(charge_state, float("inf")) - 1e-9:
                        dist_J[charge_state] = new_J
                        prev_time, prev_disc = state_metrics[(u_layer, s)]
                        state_metrics[charge_state] = (prev_time + t_chg, prev_disc + d_chg)
                        charge_info = {
                            "station": station,
                            "arrival_soc": s_in_soc,
                            "departure_soc": s_out_soc,
                            "charge_time_min": t_chg,
                            "discomfort_min": d_chg,
                        }
                        pred[charge_state] = ((u_layer, s), ("charge", charge_info))
                        heapq.heappush(pq, (new_J, dep_layer, s_dep_idx))

        # Step 4: Extract best arrival at destination over all arrival levels
        best_dest_state = None
        min_dest_J = float("inf")

        for s_idx in range(K + 1):
            target_key = ("dest_arr", s_idx)
            cost = dist_J.get(target_key, float("inf"))
            if cost < min_dest_J:
                min_dest_J = cost
                best_dest_state = target_key

        if best_dest_state is None or min_dest_J == float("inf"):
            # Diagnostic infeasibility analysis with bridging gap reporting
            unbridgeable = filter_audit.get("unbridgeable_gap")
            if unbridgeable:
                reason = (
                    f"Trip from {snapshot.source_name} to {snapshot.destination_name} is physically infeasible: "
                    f"unbridgeable gap between {unbridgeable['from_point']} and {unbridgeable['to_point']} "
                    f"({unbridgeable['gap_dist_km']} km, exceeding vehicle range {unbridgeable['allowed_dist_km']} km "
                    f"by {unbridgeable['deficit_km']} km / {unbridgeable['deficit_kwh']} kWh with reserve {trip.reserve_soc:.0%})."
                )
            else:
                reason = (
                    f"Trip from {snapshot.source_name} to {snapshot.destination_name} is physically infeasible: "
                    f"vehicle range with reserve {trip.reserve_soc:.0%} is insufficient to bridge charging gaps."
                )

            search_time_ms = (time.perf_counter() - t_search_start) * 1000.0
            return Plan(
                trip=trip,
                car=car,
                feasible=False,
                infeasibility_reason=reason,
                build_time_ms=round(build_time_ms, 2),
                search_time_ms=round(search_time_ms, 2),
                states_expanded=states_expanded,
                edges_relaxed=edges_relaxed,
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

        stops: list[ChargingStop] = []
        driving_edges_traversed: list[ReducedEdge] = []
        charging_time_total = 0.0

        for action, data in action_sequence:
            if action == "charge":
                st = data["station"]
                charging_time_total += data["charge_time_min"]
                stops.append(
                    ChargingStop(
                        station_id=st.id,
                        station_name=st.name,
                        operator=st.operator,
                        lat=st.lat,
                        lon=st.lon,
                        arrival_soc=data["arrival_soc"],
                        departure_soc=data["departure_soc"],
                        charge_time_min=data["charge_time_min"],
                        dwell_time_min=data["charge_time_min"],
                        discomfort_min=data["discomfort_min"],
                        amenities=st.amenities,
                        amenity_score=st.amenity_score,
                        reliability=st.reliability,
                        is_reliability_simulated=st.is_reliability_simulated,
                        max_kw=st.max_kw,
                    )
                )
            elif action == "drive":
                driving_edges_traversed.append(data)

        driving_time_total = sum(e.time_s for e in driving_edges_traversed) / 60.0

        # Step 6: Construct authentic continuous distance-elevation-SoC trajectory
        # Pre-build physical road edge lookup
        road_edge_map = {(e.u, e.v): e for e in snapshot.edges}
        profile: list[RoutePoint] = []
        cum_dist_km = 0.0

        # Start point at origin node
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
                )
            )

        # Walk through actions in forward chronological order
        for action, data in action_sequence:
            if action == "drive":
                r_edge: ReducedEdge = data
                for u_id, v_id in r_edge.road_edge_ids:
                    if (u_id, v_id) in road_edge_map:
                        phys_edge = road_edge_map[(u_id, v_id)]
                        cum_dist_km += phys_edge.length_m / 1000.0
                        current_battery_kwh -= phys_edge.energy_kwh
                        current_battery_kwh = min(car.usable_battery_kwh, current_battery_kwh)
                        current_soc = current_battery_kwh / car.usable_battery_kwh
                        head_node = snapshot.nodes.get(v_id)
                        if head_node:
                            profile.append(
                                RoutePoint(
                                    distance_km=round(cum_dist_km, 3),
                                    elevation_m=round(head_node.elevation_m, 1),
                                    soc=round(current_soc, 4),
                                    lat=head_node.lat,
                                    lon=head_node.lon,
                                )
                            )
            elif action == "charge":
                # Discontinuity at charging stop: step increase in SoC
                chg_st = data["station"]
                dep_soc = data["departure_soc"]
                current_soc = dep_soc
                current_battery_kwh = current_soc * car.usable_battery_kwh
                last_elev = profile[-1].elevation_m if profile else 0.0
                profile.append(
                    RoutePoint(
                        distance_km=round(cum_dist_km, 3),
                        elevation_m=last_elev,
                        soc=round(current_soc, 4),
                        lat=chg_st.lat,
                        lon=chg_st.lon,
                    )
                )

        dest_arrival_soc = profile[-1].soc if profile else level_to_soc(best_dest_state[1], K)
        search_time_ms = (time.perf_counter() - t_search_start) * 1000.0

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
