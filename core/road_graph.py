"""Road graph data structure storing physical nodes and directed edges."""

from __future__ import annotations

from collections.abc import Iterable

from core.models import CorridorSnapshot, RoadEdge, RoadNode


class RoadGraph:
    """Directed graph representation of the physical road infrastructure.

    Stores adjacency lists for fast forward edge traversal and node attribute lookup.

    Complexity:
        Space: O(|V| + |E|)
        Node/Edge insertion: O(1) amortized
        Degree lookup: O(1)
    """

    def __init__(self) -> None:
        self.nodes: dict[int, RoadNode] = {}
        self.adj: dict[int, list[RoadEdge]] = {}
        self._num_edges: int = 0

    def add_node(self, node: RoadNode) -> None:
        """Register a road network vertex.

        Complexity: O(1).
        """
        self.nodes[node.id] = node
        if node.id not in self.adj:
            self.adj[node.id] = []

    def add_edge(self, edge: RoadEdge) -> None:
        """Insert a directed road edge.

        Complexity: O(1).
        """
        if edge.u not in self.nodes:
            self.nodes[edge.u] = RoadNode(id=edge.u, lat=0.0, lon=0.0, elevation_m=0.0)
        if edge.v not in self.nodes:
            self.nodes[edge.v] = RoadNode(id=edge.v, lat=0.0, lon=0.0, elevation_m=0.0)

        if edge.u not in self.adj:
            self.adj[edge.u] = []
        if edge.v not in self.adj:
            self.adj[edge.v] = []

        self.adj[edge.u].append(edge)
        self._num_edges += 1

    def get_nodes(self) -> list[int]:
        """Return list of all vertex IDs."""
        return list(self.nodes.keys())

    def get_edges(self) -> list[RoadEdge]:
        """Return flat list of all edges in graph."""
        edges: list[RoadEdge] = []
        for edge_list in self.adj.values():
            edges.extend(edge_list)
        return edges

    def get_outgoing_edges(self, u: int) -> list[RoadEdge]:
        """Return all edges directed outward from vertex u.

        Complexity: O(1).
        """
        return self.adj.get(u, [])

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    @property
    def num_edges(self) -> int:
        return self._num_edges

    @classmethod
    def from_snapshot(cls, snapshot: CorridorSnapshot) -> RoadGraph:
        """Construct RoadGraph from a CorridorSnapshot.

        Complexity: O(|V| + |E|).
        """
        graph = cls()
        for node in snapshot.nodes.values():
            graph.add_node(node)
        for edge in snapshot.edges:
            graph.add_edge(edge)
        return graph

    @classmethod
    def from_edges(
        cls,
        edges: Iterable[RoadEdge],
        nodes: Iterable[RoadNode] | None = None,
    ) -> RoadGraph:
        """Construct RoadGraph from edge and node iterables.

        Complexity: O(|V| + |E|).
        """
        graph = cls()
        if nodes:
            for node in nodes:
                graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)
        return graph
