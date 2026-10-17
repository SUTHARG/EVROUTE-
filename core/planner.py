"""Multi-objective EV route planner using Dijkstra over an explicit 2-layer state graph.

Implements exact scalar DP over state space (node_layer, SoC) with objective
J = time_min + lambda * discomfort_min, generating optimal itineraries and supported
Pareto trade-off frontiers via lambda sweeps.
"""

from __future__ import annotations

import heapq
from typing import Any

from core.charger_graph import build_reduced_charger_graph
from core.charging import charge_time_min
from core.comfort import compute_dwell_discomfort
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
        pass

    def plan(
        self,
        snapshot: CorridorSnapshot,
        car: Car,
        trip: Trip,
        lambda_val: float | None = None,
        use_all_departure_levels: bool = True,
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

        Returns:
            Fully populated Plan with feasibility status, stops, and SoC trajectory.
        """
        active_lambda = lambda_val if lambda_val is not None else trip.comfort_weight_lambda
        K = trip.K

        # Step 1: Greedy station filtering with connectivity guarantee
        source_node_id = 0
        dest_node_id = max(snapshot.nodes.keys())
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

        # Step 2: Build reduced 2-layer charger transition graph
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

        # Step 3: Dijkstra search over explicit state space (node_layer, s)
        # States are strings: "u_layer:s" where u_layer in {"source_dep", "dest_arr", f"{st_id}_arr", f"{st_id}_dep"}
        # and s in {0, ..., K}
        start_s = min(K, max(0, round(trip.start_soc * K)))
        start_state = ("source_dep", start_s)

        dist_J: dict[tuple[str, int], float] = {start_state: 0.0}
        pred: dict[tuple[str, int], tuple[tuple[str, int], Any] | None] = {start_state: None}
        state_metrics: dict[tuple[str, int], tuple[float, float]] = {start_state: (0.0, 0.0)}  # (time_min, discomfort_min)

        # Min-heap stores (cost_J, node_layer, s)
        pq: list[tuple[float, str, int]] = [(0.0, "source_dep", start_s)]

        while pq:
            curr_J, u_layer, s = heapq.heappop(pq)

            if curr_J > dist_J.get((u_layer, s), float("inf")):
                continue

            # Case A: At a departed state (e.g. "source_dep" or f"{st_id}_dep") -> DRIVE
            if u_layer.endswith("_dep"):
                outgoing_edges = reduced_graph.get_driving_edges(u_layer)
                for red_edge in outgoing_edges:
                    arr_soc = red_edge.arrival_soc_table[s]
                    if arr_soc is None:
                        # Infeasible: battery drops below reserve along this edge
                        continue

                    s_arr_idx = min(K, max(0, round(arr_soc * K)))
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

                # 1. Zero-cost pass-through (no charging): (st_arr, s) -> (st_dep, s)
                pass_state = (dep_layer, s)
                if curr_J < dist_J.get(pass_state, float("inf")) - 1e-9:
                    dist_J[pass_state] = curr_J
                    state_metrics[pass_state] = state_metrics[(u_layer, s)]
                    pred[pass_state] = ((u_layer, s), ("pass", None))
                    heapq.heappush(pq, (curr_J, dep_layer, s))

                # 2. Real charge transitions: (st_arr, s) -> (st_dep, s_dep) for s_dep > s
                if use_all_departure_levels:
                    candidate_departure_levels = list(range(s + 1, K + 1))
                else:
                    from core.charging import compute_dwell_window_soc_targets
                    # Optional heuristic subset: 80%, 100%, and 20/40m dwell targets
                    targets_set = {round(0.80 * K), K}
                    dwell_targets = compute_dwell_window_soc_targets(s / K, station.max_kw, car, K=K)
                    targets_set.update(dwell_targets)
                    candidate_departure_levels = [lvl for lvl in sorted(targets_set) if lvl > s]

                s_in_soc = s / K
                for s_dep_idx in candidate_departure_levels:
                    s_out_soc = s_dep_idx / K
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
            # Diagnostic infeasibility analysis
            return Plan(
                trip=trip,
                car=car,
                feasible=False,
                infeasibility_reason=(
                    f"Trip from {snapshot.source_name} to {snapshot.destination_name} is physically infeasible: "
                    f"vehicle range with reserve {trip.reserve_soc:.0%} is insufficient to bridge charging gaps."
                ),
            )

        # Step 5: Backtrack optimal itinerary
        final_time_min, final_disc_min = state_metrics[best_dest_state]
        curr_state = best_dest_state
        stops: list[ChargingStop] = []
        reversed_edges: list[ReducedEdge] = []
        charging_time_total = 0.0

        while curr_state is not None:
            prev_info = pred[curr_state]
            if prev_info is None:
                break
            prev_state, (action, data) = prev_info
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
                reversed_edges.append(data)
            curr_state = prev_state

        stops.reverse()
        reversed_edges.reverse()

        driving_time_total = sum(e.time_s for e in reversed_edges) / 60.0

        # Construct continuous RoutePoint trajectory
        profile: list[RoutePoint] = []
        cum_dist_km = 0.0
        running_soc = trip.start_soc

        for e in reversed_edges:
            for lat, lon in e.geometry:
                profile.append(
                    RoutePoint(
                        distance_km=round(cum_dist_km, 2),
                        elevation_m=0.0,
                        soc=round(running_soc, 3),
                        lat=lat,
                        lon=lon,
                    )
                )
                cum_dist_km += 1.5  # average step

        return Plan(
            trip=trip,
            car=car,
            feasible=True,
            total_time_min=round(final_time_min, 2),
            driving_time_min=round(driving_time_total, 2),
            charging_time_min=round(charging_time_total, 2),
            total_discomfort_min=round(final_disc_min, 2),
            cost_J=round(min_dest_J, 3),
            stops=stops,
            arrival_soc_dest=round(best_dest_state[1] / K, 3),
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

        Complexity:
            Time: O(|lambdas| * Planner_Complexity)
        """
        sweep_lambdas = lambdas or [0.01, 0.10, 0.30, 0.60, 1.00, 2.00, 5.00, 10.00]
        points: list[ParetoPoint] = []
        seen_tradeoffs: set[tuple[float, float]] = set()

        for l_val in sweep_lambdas:
            res_plan = self.plan(snapshot, car, trip, lambda_val=l_val)
            if not res_plan.feasible:
                continue

            t_round = round(res_plan.total_time_min, 1)
            d_round = round(res_plan.total_discomfort_min, 1)
            pair = (t_round, d_round)

            if pair not in seen_tradeoffs:
                seen_tradeoffs.add(pair)
                points.append(
                    ParetoPoint(
                        lambda_val=l_val,
                        total_time_min=res_plan.total_time_min,
                        total_discomfort_min=res_plan.total_discomfort_min,
                        cost_J=res_plan.cost_J,
                        stops_count=len(res_plan.stops),
                        stop_station_ids=[s.station_id for s in res_plan.stops],
                    )
                )

        # Sort Pareto points by increasing travel time
        points.sort(key=lambda p: (p.total_time_min, p.total_discomfort_min))
        return points
