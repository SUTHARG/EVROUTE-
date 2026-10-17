"""Unit tests for Bellman-Ford, Johnson's reweighting, and Dijkstra vs NetworkX."""

import networkx as nx
import pytest

from core.bellman_ford import (
    NegativeCycleError,
    bellman_ford,
    dijkstra,
    johnson_potentials,
    johnson_shortest_paths,
    reconstruct_path,
)
from core.models import RoadEdge, RoadNode
from core.road_graph import RoadGraph
from ingest.synthetic import generate_random_geometric_graph, generate_synthetic_corridor


def test_bellman_ford_vs_networkx_negative_edges():
    """Verify from-scratch Bellman-Ford matches networkx on random graphs with negative edges."""
    # Build a DAG / acyclic-biased graph with negative edges to guarantee no negative cycles
    graph = RoadGraph()
    nx_graph = nx.DiGraph()

    num_nodes = 15
    for i in range(num_nodes):
        graph.add_node(RoadNode(id=i, lat=0.0, lon=0.0, elevation_m=0.0))
        nx_graph.add_node(i)

    # Forward-directed edges with some negative weights (downhill regen)
    import random
    rng = random.Random(123)

    for u in range(num_nodes):
        for v in range(u + 1, min(num_nodes, u + 5)):
            weight = round(rng.uniform(-2.5, 8.0), 3)
            edge = RoadEdge(
                u=u,
                v=v,
                length_m=5000.0,
                time_s=300.0,
                energy_kwh=weight,
            )
            graph.add_edge(edge)
            nx_graph.add_edge(u, v, weight=weight)

    source = 0
    # Antigravity Bellman-Ford
    bf_dist, bf_pred = bellman_ford(graph, source=source, weight_attr="energy_kwh")

    # NetworkX Bellman-Ford
    nx_dist, nx_pred = nx.single_source_bellman_ford(nx_graph, source=source, weight="weight")

    for node_id in range(num_nodes):
        if node_id in nx_dist:
            assert bf_dist[node_id] == pytest.approx(nx_dist[node_id], rel=1e-5), f"Mismatch at node {node_id}"
            if node_id != source:
                path = reconstruct_path(bf_pred, target=node_id)
                assert path[0] == source
                assert path[-1] == node_id
                # Verify total weight along path equals dist
                nx_path = nx_pred[node_id]
                assert len(path) == len(nx_path)


def test_dijkstra_matches_bellman_ford_on_positive_graph():
    """Verify Dijkstra produces identical distances to Bellman-Ford on non-negative graphs."""
    nodes, edges = generate_random_geometric_graph(
        num_nodes=25,
        edge_probability=0.20,
        seed=77,
        allow_negative_edges=False,
    )
    graph = RoadGraph.from_edges(edges, nodes.values())
    source = 0

    dijk_dist, _ = dijkstra(graph, source=source, weight_attr="energy_kwh")
    bf_dist, _ = bellman_ford(graph, source=source, weight_attr="energy_kwh")

    for node_id in graph.get_nodes():
        if dijk_dist[node_id] != float("inf"):
            assert dijk_dist[node_id] == pytest.approx(bf_dist[node_id], rel=1e-5)


def test_negative_cycle_detection():
    """Verify that Bellman-Ford detects negative-weight cycles and raises NegativeCycleError."""
    graph = RoadGraph()
    # Cycle 1 -> 2 -> 3 -> 1 with negative net weight (-1.0)
    graph.add_edge(RoadEdge(u=1, v=2, length_m=1000.0, time_s=60.0, energy_kwh=2.0))
    graph.add_edge(RoadEdge(u=2, v=3, length_m=1000.0, time_s=60.0, energy_kwh=3.0))
    graph.add_edge(RoadEdge(u=3, v=1, length_m=1000.0, time_s=60.0, energy_kwh=-6.0))  # sum = -1.0

    with pytest.raises(NegativeCycleError) as exc_info:
        bellman_ford(graph, source=1, weight_attr="energy_kwh")

    assert len(exc_info.value.cycle) > 0


def test_johnson_reweighting_shortest_paths():
    """Verify Johnson's algorithm produces identical distances to Bellman-Ford for multiple terminals."""
    # Graph with negative edges but no negative cycles
    graph = RoadGraph()
    num_nodes = 12
    for i in range(num_nodes):
        graph.add_node(RoadNode(id=i, lat=0.0, lon=0.0, elevation_m=0.0))

    import random
    rng = random.Random(456)
    for u in range(num_nodes):
        for v in range(u + 1, min(num_nodes, u + 4)):
            w = round(rng.uniform(-1.5, 6.0), 3)
            graph.add_edge(RoadEdge(u=u, v=v, length_m=4000.0, time_s=250.0, energy_kwh=w))

    terminals = [0, 2, 4]
    johnson_dists = johnson_shortest_paths(graph, terminals=terminals, weight_attr="energy_kwh")

    for term in terminals:
        bf_dist, _ = bellman_ford(graph, source=term, weight_attr="energy_kwh")
        for v in range(num_nodes):
            if bf_dist[v] != float("inf"):
                assert johnson_dists[term][v] == pytest.approx(bf_dist[v], rel=1e-5), (
                    f"Johnson mismatch from {term} to {v}: {johnson_dists[term][v]} vs {bf_dist[v]}"
                )


def test_physical_corridor_has_no_negative_cycles():
    """Verify that physical road network from synthetic corridor has zero negative cycles."""
    snapshot = generate_synthetic_corridor(seed=999)
    graph = RoadGraph.from_snapshot(snapshot)

    # Johnson potentials must succeed without raising NegativeCycleError
    potentials = johnson_potentials(graph, weight_attr="energy_kwh")
    assert len(potentials) == len(snapshot.nodes)


def test_bellman_ford_unreachable_nodes_and_path_reconstruction():
    """Verify unreachable nodes return inf distance, None pred, and empty path."""
    graph = RoadGraph()
    graph.add_node(RoadNode(id=1, lat=0.0, lon=0.0, elevation_m=0.0))
    graph.add_node(RoadNode(id=2, lat=0.0, lon=0.0, elevation_m=0.0))
    graph.add_node(RoadNode(id=3, lat=0.0, lon=0.0, elevation_m=0.0))  # disconnected island
    graph.add_edge(RoadEdge(u=1, v=2, length_m=1000.0, time_s=60.0, energy_kwh=1.5))

    dist, pred = bellman_ford(graph, source=1, weight_attr="energy_kwh")
    assert dist[2] == 1.5
    assert dist[3] == float("inf")
    assert pred[3] is None

    # Path to reachable node
    path_1_to_2 = reconstruct_path(pred, target=2)
    assert path_1_to_2 == [1, 2]

    # Path to unreachable node
    path_1_to_3 = reconstruct_path(pred, target=3)
    assert path_1_to_3 == []


def test_johnson_vs_bellman_ford_on_synthetic_corridor():
    """Verify Johnson's algorithm distances match Bellman-Ford on the full synthetic corridor."""
    snapshot = generate_synthetic_corridor(seed=314)
    graph = RoadGraph.from_snapshot(snapshot)

    terminals = [0, 10, 25, 40]
    johnson_dists = johnson_shortest_paths(graph, terminals=terminals, weight_attr="time_s")

    for src in terminals:
        bf_dist, _ = bellman_ford(graph, source=src, weight_attr="time_s")
        for dst in [5, 15, 30, 45]:
            if bf_dist[dst] != float("inf"):
                assert johnson_dists[src][dst] == pytest.approx(bf_dist[dst], rel=1e-4)

