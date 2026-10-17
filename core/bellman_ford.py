"""Bellman-Ford, Johnson's potential reweighting, and Dijkstra shortest path algorithms.

Handles negative edge weights from downhill regenerative braking, negative cycle
detection, early termination, and multi-terminal shortest path reweighting.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable

from core.models import RoadEdge
from core.road_graph import RoadGraph


class NegativeCycleError(Exception):
    """Raised when a negative-weight cycle is detected in the graph."""

    def __init__(self, message: str, cycle: list[int] | None = None) -> None:
        super().__init__(message)
        self.cycle = cycle or []


def get_edge_weight(edge: RoadEdge, weight_attr: str = "energy_kwh") -> float:
    """Extract requested numerical weight metric from an edge.

    Complexity: O(1).
    """
    if weight_attr == "energy_kwh":
        return edge.energy_kwh
    elif weight_attr == "time_s":
        return edge.time_s
    elif weight_attr == "length_m":
        return edge.length_m
    else:
        return getattr(edge, weight_attr)


def bellman_ford(
    graph: RoadGraph,
    source: int,
    weight_attr: str = "energy_kwh",
) -> tuple[dict[int, float], dict[int, int | None]]:
    """Compute single-source shortest paths on graphs with potentially negative edges.

    Implements Bellman-Ford with early termination if no edge relaxes in round k < |V| - 1,
    and reports negative cycles if relaxation occurs on round |V|.

    Complexity:
        Time: O(|V| * |E|) worst case, O(k * |E|) with early termination where k <= |V|.
        Space: O(|V|) to store distances and predecessor pointers.

    Args:
        graph: Directed RoadGraph.
        source: Starting vertex ID.
        weight_attr: Edge attribute to use as weight (default 'energy_kwh').

    Returns:
        Tuple of (distances_dict, predecessors_dict).

    Raises:
        NegativeCycleError: If a reachable negative-weight cycle exists.
    """
    nodes = graph.get_nodes()
    all_edges = graph.get_edges()
    num_v = len(nodes)

    dist: dict[int, float] = {node_id: float("inf") for node_id in nodes}
    pred: dict[int, int | None] = {node_id: None for node_id in nodes}

    if source not in dist:
        dist[source] = 0.0
        pred[source] = None
    else:
        dist[source] = 0.0

    # Relax edges repeatedly up to |V| - 1 times
    for iteration in range(num_v - 1):
        relaxed_any = False
        for edge in all_edges:
            u, v = edge.u, edge.v
            if dist[u] != float("inf"):
                w = get_edge_weight(edge, weight_attr)
                if dist[u] + w < dist[v] - 1e-9:
                    dist[v] = dist[u] + w
                    pred[v] = u
                    relaxed_any = True

        # Early termination: if no edge was relaxed in this round, shortest paths are found!
        if not relaxed_any:
            break

    # |V|-th iteration: Check for negative-weight cycles
    for edge in all_edges:
        u, v = edge.u, edge.v
        if dist[u] != float("inf"):
            w = get_edge_weight(edge, weight_attr)
            if dist[u] + w < dist[v] - 1e-9:
                # Trace cycle back to extract vertices
                visited = set()
                curr = v
                for _ in range(num_v):
                    curr = pred[curr] or curr
                cycle_start = curr
                cycle = [cycle_start]
                step = pred[cycle_start]
                while step is not None and step != cycle_start and step not in visited:
                    visited.add(step)
                    cycle.append(step)
                    step = pred[step]
                cycle.append(cycle_start)
                cycle.reverse()
                raise NegativeCycleError(
                    f"Negative cycle detected reachable from source {source}: {cycle}",
                    cycle=cycle,
                )

    return dist, pred


def dijkstra(
    graph: RoadGraph,
    source: int,
    weight_attr: str = "time_s",
    custom_weight_fn: Callable[[RoadEdge], float] | None = None,
) -> tuple[dict[int, float], dict[int, int | None]]:
    """Compute single-source shortest paths on graphs with non-negative edge weights.

    Uses a binary min-heap priority queue.

    Complexity:
        Time: O((|V| + |E|) log |V|)
        Space: O(|V|)

    Args:
        graph: Directed RoadGraph.
        source: Starting vertex ID.
        weight_attr: Edge attribute to use as weight (default 'time_s').
        custom_weight_fn: Optional custom weighting function (e.g. for reweighted edges).

    Returns:
        Tuple of (distances_dict, predecessors_dict).

    Raises:
        ValueError: If a negative edge weight is encountered.
    """
    nodes = graph.get_nodes()
    dist: dict[int, float] = {node_id: float("inf") for node_id in nodes}
    pred: dict[int, int | None] = {node_id: None for node_id in nodes}

    if source not in dist:
        dist[source] = 0.0
    else:
        dist[source] = 0.0

    # Priority queue stores tuples of (distance, node_id)
    pq: list[tuple[float, int]] = [(0.0, source)]

    while pq:
        d_curr, u = heapq.heappop(pq)

        if d_curr > dist[u]:
            continue

        for edge in graph.get_outgoing_edges(u):
            v = edge.v
            if custom_weight_fn is not None:
                w = custom_weight_fn(edge)
            else:
                w = get_edge_weight(edge, weight_attr)

            if w < -1e-9:
                raise ValueError(
                    f"Dijkstra encountered negative edge weight ({w}) on edge {u}->{v}. "
                    "Use Bellman-Ford or Johnson's algorithm instead."
                )

            if dist[u] + w < dist[v] - 1e-9:
                dist[v] = dist[u] + w
                pred[v] = u
                heapq.heappush(pq, (dist[v], v))

    return dist, pred


def johnson_potentials(
    graph: RoadGraph,
    weight_attr: str = "energy_kwh",
) -> dict[int, float]:
    """Compute node potentials h(u) using Bellman-Ford from a virtual source node s0.

    Adds virtual source s0 connected to every node in V with weight 0, then runs
    Bellman-Ford. If a negative cycle exists, raises NegativeCycleError.

    Complexity:
        Time: O(|V| * |E|)
        Space: O(|V|)

    Args:
        graph: Directed RoadGraph.
        weight_attr: Edge attribute (default 'energy_kwh').

    Returns:
        Dictionary mapping node_id -> potential h(u).
    """
    nodes = graph.get_nodes()
    all_edges = graph.get_edges()
    s0 = -999999  # Virtual source node ID not present in graph

    dist: dict[int, float] = {node_id: 0.0 for node_id in nodes}
    dist[s0] = 0.0

    # Relaxation rounds
    num_v = len(nodes) + 1
    for iteration in range(num_v - 1):
        relaxed_any = False
        for edge in all_edges:
            u, v = edge.u, edge.v
            w = get_edge_weight(edge, weight_attr)
            if dist[u] + w < dist[v] - 1e-9:
                dist[v] = dist[u] + w
                relaxed_any = True

        if not relaxed_any:
            break

    # Negative cycle check
    for edge in all_edges:
        u, v = edge.u, edge.v
        w = get_edge_weight(edge, weight_attr)
        if dist[u] + w < dist[v] - 1e-9:
            raise NegativeCycleError(
                "Negative cycle detected in graph during Johnson potential calculation."
            )

    dist.pop(s0, None)
    return dist


def johnson_shortest_paths(
    graph: RoadGraph,
    terminals: list[int],
    weight_attr: str = "energy_kwh",
) -> dict[int, dict[int, float]]:
    """Compute shortest path distances between terminals using Johnson's reweighting.

    1. Computes potentials h(u) via Bellman-Ford from virtual source in O(|V| * |E|).
    2. Reweights edges: w_hat(u, v) = w(u, v) + h(u) - h(v) >= 0.
    3. Runs Dijkstra from each terminal in O(|terminals| * |E| log |V|).
    4. Reverses reweighting: d(u, v) = d_hat(u, v) - h(u) + h(v).

    Complexity:
        Time: O(|V_road| * |E_road| + |V_c| * |E_road| * log |V_road|)
        Space: O(|V_road| + |V_c| * |V_road|)

    Args:
        graph: Physical road network.
        terminals: List of origin terminal vertices (source, chargers, dest).
        weight_attr: Edge attribute to minimize (e.g. 'energy_kwh').

    Returns:
        Nested dict: distances[u][v] = shortest path distance from u to v.
    """
    # Step 1: Compute potentials h
    h = johnson_potentials(graph, weight_attr=weight_attr)

    # Step 2 & 3: Run Dijkstra with reweighted edges from each terminal
    result: dict[int, dict[int, float]] = {}

    for src in terminals:
        def reweighted_fn(edge: RoadEdge, _h: dict[int, float] = h) -> float:
            raw_w = get_edge_weight(edge, weight_attr)
            # w_hat = w + h(u) - h(v)
            return max(0.0, raw_w + _h[edge.u] - _h[edge.v])

        dist_hat, _ = dijkstra(
            graph,
            source=src,
            custom_weight_fn=reweighted_fn,
        )

        # Step 4: Undo reweighting to recover exact original distance
        orig_dist: dict[int, float] = {}
        for target, d_hat in dist_hat.items():
            if d_hat == float("inf"):
                orig_dist[target] = float("inf")
            else:
                orig_dist[target] = round(d_hat - h[src] + h[target], 6)

        result[src] = orig_dist

    return result


def reconstruct_path(
    predecessors: dict[int, int | None],
    target: int,
) -> list[int]:
    """Reconstruct vertex sequence from source to target using predecessor map.

    Complexity:
        Time: O(|path|)
        Space: O(|path|)

    Args:
        predecessors: Predecessor map from shortest path search.
        target: Target destination vertex ID.

    Returns:
        List of vertex IDs from source to target, or empty list if target unreachable.
    """
    if target not in predecessors:
        return []

    path: list[int] = []
    curr: int | None = target
    visited = set()

    while curr is not None:
        if curr in visited:
            # Cycle safety
            return []
        visited.add(curr)
        path.append(curr)
        curr = predecessors[curr]

    path.reverse()
    return path
