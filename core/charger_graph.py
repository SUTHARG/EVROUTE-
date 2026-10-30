"""Reduced charger graph construction module.

Contracts the physical road graph (|V| ~ 10^3 - 10^4) into a reduced transition
graph between candidate stops (|V_c| ~ 10 - 25).
For each pair (u, v), computes two candidate paths:
1. Fastest path (via Dijkstra on traversal time)
2. Eco / Min-energy path (via Bellman-Ford / Johnson on net energy with regen)
Both paths are pre-simulated across discrete departure levels 0..K with 100% capacity
clamping and prefix safety checks.
"""

from __future__ import annotations

from typing import Any

from core.bellman_ford import bellman_ford, dijkstra, reconstruct_path
from core.energy import build_arrival_soc_table, compute_path_energy_summary
from core.models import Car, ReducedEdge, RoadEdge, Station
from core.road_graph import RoadGraph
from ingest.route import haversine_distance_m


class ReducedChargerGraph:
    """Reduced transition graph between journey terminals and candidate chargers.

    Nodes:
        - 'source_dep': Starting terminal in departed state.
        - 'dest_arr': Ending terminal in arrived state.
        - For each charger station st: 'st.id_arr' and 'st.id_dep'.

    Edges:
        - Driving transitions: u_dep -> v_arr (with pre-tabulated arrival SoC).
        - No-charge zero-cost transitions: st_arr -> st_dep (same SoC, 0 time/cost).
        - Real charging transitions: st_arr -> st_dep (positive charging time & discomfort).
    """

    def __init__(self) -> None:
        self.stations: dict[str, Station] = {}
        # Driving edges: u_dep -> list of ReducedEdge directed to v_arr
        self.driving_edges: dict[str, list[ReducedEdge]] = {}
        self.terminals: list[str] = ["source", "dest"]

    def add_driving_edge(self, edge: ReducedEdge) -> None:
        """Register a reduced driving transition."""
        src_key = f"{edge.u}_dep"
        if src_key not in self.driving_edges:
            self.driving_edges[src_key] = []
        self.driving_edges[src_key].append(edge)

    def get_driving_edges(self, u_dep: str) -> list[ReducedEdge]:
        """Return all reduced driving edges departing from u_dep."""
        return self.driving_edges.get(u_dep, [])


def map_stations_to_road_nodes(
    stations: list[Station],
    road_graph: RoadGraph,
) -> dict[str, int]:
    """Map each station to its nearest physical road network node ID.

    Complexity:
        Time: O(|stations| * |V_road|)
        Space: O(|stations|)
    """
    station_node_map: dict[str, int] = {}
    nodes = road_graph.nodes

    for st in stations:
        if st.road_node_id is not None and st.road_node_id in nodes:
            station_node_map[st.id] = st.road_node_id
            continue

        min_dist = float("inf")
        closest_id = 0
        for node_id, node in nodes.items():
            dist = haversine_distance_m(st.lat, st.lon, node.lat, node.lon)
            if dist < min_dist:
                min_dist = dist
                closest_id = node_id
        station_node_map[st.id] = closest_id

    return station_node_map


def build_reduced_charger_graph(
    road_graph: RoadGraph,
    kept_stations: list[Station],
    source_node_id: int,
    dest_node_id: int,
    car: Car,
    K: int = 100,
    reserve_soc: float = 0.10,
) -> tuple[ReducedChargerGraph, dict[str, Any]]:
    """Construct the contracted charger transition graph with fastest and eco paths.

    For every ordered pair of stops (u, v) where v is reachable from u:
        1. Fastest candidate: Shortest path by time (Dijkstra on time_s).
        2. Eco candidate: Shortest path by net energy (Bellman-Ford on energy_kwh).
        3. Pre-tabulate exact arrival_soc[s] for s in 0..K using step-by-step
           edge simulation with 100% clamping and reserve verification.
        4. Prune candidate edges if completely infeasible across all departure levels.

    Two-Candidate-Path Limitation:
        For each pair of stops (u, v), the reduced graph computes exactly two candidate
        paths: the time-optimal path (Dijkstra on time_s) and the net-energy-optimal path
        (Bellman-Ford on energy_kwh). In general networks, intermediate Pareto-optimal paths
        (e.g., paths with moderate time and energy, or paths avoiding steep crests that clamp
        at 100% battery) could exist that dominate both candidates under specific battery states.
        Limiting the candidate set to {fastest, eco} is an efficient corridor heuristic that
        guarantees polynomial precomputation O(|V_c| * |E_road| log |V_road|) while capturing
        the primary time-vs-energy trade-off.

    Complexity:
        Time: O(|V_c| * (|E_road| log |V_road| + |V_road| |E_road|) + |V_c|^2 * K * |path|)
        Space: O(|V_c|^2 * K)

    Returns:
        Tuple of (ReducedChargerGraph, audit_benchmark_stats).
    """
    reduced_graph = ReducedChargerGraph()
    for st in kept_stations:
        reduced_graph.stations[st.id] = st

    # Map terminals
    st_node_map = map_stations_to_road_nodes(kept_stations, road_graph)
    terminal_node_map: dict[str, int] = {
        "source": source_node_id,
        "dest": dest_node_id,
        **st_node_map,
    }

    # Ordered list of terminal IDs
    all_terminals = ["source"] + [st.id for st in kept_stations] + ["dest"]
    num_terminals = len(all_terminals)

    eco_better_count = 0
    total_pairs_evaluated = 0

    # Cache road edge lookup for fast reconstruction
    edge_map: dict[tuple[int, int], RoadEdge] = {}
    for edge in road_graph.get_edges():
        edge_map[(edge.u, edge.v)] = edge

    for i in range(num_terminals):
        u_id = all_terminals[i]
        u_node = terminal_node_map[u_id]

        # Compute shortest path trees from u_node on road graph
        # 1. Fastest tree via Dijkstra on time_s
        time_dists, time_preds = dijkstra(road_graph, source=u_node, weight_attr="time_s")

        # 2. Eco tree via Bellman-Ford on energy_kwh
        energy_dists, energy_preds = bellman_ford(road_graph, source=u_node, weight_attr="energy_kwh")

        # Evaluate transitions to all downstream terminals v
        for j in range(i + 1, num_terminals):
            v_id = all_terminals[j]
            v_node = terminal_node_map[v_id]
            total_pairs_evaluated += 1

            # Extract candidate paths
            candidate_paths: list[tuple[str, list[int]]] = []
            if u_node == v_node:
                candidate_paths.append(("fastest", [u_node]))
            else:
                if time_dists.get(v_node, float("inf")) < float("inf"):
                    fastest_v_path = reconstruct_path(time_preds, target=v_node)
                    if fastest_v_path:
                        candidate_paths.append(("fastest", fastest_v_path))

                if energy_dists.get(v_node, float("inf")) < float("inf"):
                    eco_v_path = reconstruct_path(energy_preds, target=v_node)
                    if eco_v_path and (not candidate_paths or eco_v_path != candidate_paths[0][1]):
                        candidate_paths.append(("eco", eco_v_path))

            for path_type, v_path in candidate_paths:
                # Resolve sequence of RoadEdges
                path_edges: list[RoadEdge] = []
                coords: list[tuple[float, float]] = []

                # 1. Outbound spur from u (if u is a station)
                if u_id in reduced_graph.stations:
                    u_st = reduced_graph.stations[u_id]
                    if u_st.detour_time_s > 0 or u_st.detour_energy_kwh > 0 or u_st.detour_distance_m > 0:
                        out_d = u_st.detour_distance_m / 2.0
                        out_t = u_st.detour_time_s / 2.0
                        out_e = (
                            u_st.detour_energy_kwh / 2.0
                            if u_st.detour_energy_kwh > 0
                            else (car.consumption_kwh_per_km * (out_d / 1000.0))
                        )
                        path_edges.append(
                            RoadEdge(
                                u=u_node,
                                v=u_node,
                                length_m=out_d,
                                time_s=max(0.1, out_t),
                                elevation_gain_m=0.0,
                                energy_kwh=out_e,
                            )
                        )
                        coords.append((u_st.lat, u_st.lon))

                # 2. Highway road edges along v_path
                for k in range(len(v_path) - 1):
                    pair = (v_path[k], v_path[k + 1])
                    if pair in edge_map:
                        path_edges.append(edge_map[pair])
                        node_u = road_graph.nodes.get(v_path[k])
                        if node_u:
                            coords.append((node_u.lat, node_u.lon))

                if v_path:
                    last_node = road_graph.nodes.get(v_path[-1])
                    if last_node:
                        coords.append((last_node.lat, last_node.lon))

                # 3. Inbound spur into v (if v is a station)
                if v_id in reduced_graph.stations:
                    v_st = reduced_graph.stations[v_id]
                    if v_st.detour_time_s > 0 or v_st.detour_energy_kwh > 0 or v_st.detour_distance_m > 0:
                        in_d = v_st.detour_distance_m / 2.0
                        in_t = v_st.detour_time_s / 2.0
                        in_e = (
                            v_st.detour_energy_kwh / 2.0
                            if v_st.detour_energy_kwh > 0
                            else (car.consumption_kwh_per_km * (in_d / 1000.0))
                        )
                        path_edges.append(
                            RoadEdge(
                                u=v_node,
                                v=v_node,
                                length_m=in_d,
                                time_s=max(0.1, in_t),
                                elevation_gain_m=0.0,
                                energy_kwh=in_e,
                            )
                        )
                        coords.append((v_st.lat, v_st.lon))

                if not path_edges:
                    continue

                # Tabulate arrival SoC across discrete departure levels 0..K
                arr_table = build_arrival_soc_table(
                    car=car,
                    edges=path_edges,
                    K=K,
                    reserve_soc=reserve_soc,
                )

                # Check if this edge is feasible for at least one departure level
                has_feasible_level = any(val is not None for val in arr_table)
                if not has_feasible_level:
                    # Pruned: unreachable on single charge even from 100% SoC
                    continue

                time_s, net_kwh, peak_need_kwh = compute_path_energy_summary(path_edges)

                reduced_edge = ReducedEdge(
                    u=u_id,
                    v=v_id,
                    path_type=path_type,
                    time_s=time_s,
                    net_energy_kwh=net_kwh,
                    peak_need_kwh=peak_need_kwh,
                    road_edge_ids=[(e.u, e.v) for e in path_edges],
                    arrival_soc_table=arr_table,
                    geometry=coords,
                )
                reduced_graph.add_driving_edge(reduced_edge)

            # Check if eco path beat fastest path in energy
            if len(candidate_paths) >= 2:
                # Candidate 0 is fastest, Candidate 1 is eco
                eco_better_count += 1

    stats = {
        "total_terminal_pairs": total_pairs_evaluated,
        "reduced_nodes_count": len(all_terminals),
        "eco_candidates_evaluated": eco_better_count,
        "total_reduced_edges": sum(len(el) for el in reduced_graph.driving_edges.values()),
    }
    return reduced_graph, stats
