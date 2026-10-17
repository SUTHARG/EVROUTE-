"""Unit tests for synthetic corridor generation and snapshot format (Phase 3)."""

from core.models import CorridorSnapshot
from ingest.elevation import smooth_elevation_profile
from ingest.synthetic import generate_random_geometric_graph, generate_synthetic_corridor


def test_synthetic_corridor_generation_offline():
    """Verify synthetic corridor snapshot is generated completely offline with correct attributes."""
    snapshot = generate_synthetic_corridor(
        source_name="Mumbai",
        destination_name="Pune",
        total_distance_km=150.0,
        num_road_segments=40,
        num_stations=12,
        seed=101,
    )

    assert isinstance(snapshot, CorridorSnapshot)
    assert snapshot.source_name == "Mumbai"
    assert snapshot.destination_name == "Pune"
    assert len(snapshot.nodes) == 41
    assert len(snapshot.edges) == 40
    assert len(snapshot.stations) == 12

    # Check stations have simulated reliability and amenities
    for station in snapshot.stations:
        assert station.is_reliability_simulated is True
        assert 0.0 < station.reliability < 1.0
        assert station.max_kw >= 30.0
        assert "CCS2" in station.connector_types
        assert 0.0 <= station.amenity_score <= 1.0
        assert "toilets" in station.amenities or "fuel" in station.amenities or "restaurant" in station.amenities

    # Check elevation ascent metrics in metadata
    meta = snapshot.metadata
    assert "ascent_before_smoothing_m" in meta
    assert "ascent_after_smoothing_m" in meta
    assert meta["ascent_after_smoothing_m"] <= meta["ascent_before_smoothing_m"]


def test_elevation_smoothing_reduces_noise():
    """Verify that moving average smoothing strictly reduces spurious jitter."""
    # Signal with oscillating high-frequency noise
    raw = [100.0, 105.0, 98.0, 106.0, 97.0, 104.0, 99.0, 105.0]
    smoothed, ascent_before, ascent_after = smooth_elevation_profile(raw, window_size=3)

    assert len(smoothed) == len(raw)
    assert ascent_after < ascent_before


def test_synthetic_reproducibility():
    """Verify that identical seeds yield identical snapshots."""
    snap1 = generate_synthetic_corridor(seed=42)
    snap2 = generate_synthetic_corridor(seed=42)

    assert snap1.edges[0].energy_kwh == snap2.edges[0].energy_kwh
    assert snap1.stations[0].reliability == snap2.stations[0].reliability
    assert snap1.nodes[10].elevation_m == snap2.nodes[10].elevation_m


def test_random_geometric_graph_generation():
    """Verify random geometric graph generator creates valid test instances."""
    nodes, edges = generate_random_geometric_graph(
        num_nodes=20,
        edge_probability=0.25,
        seed=42,
        allow_negative_edges=True,
    )
    assert len(nodes) == 20
    assert len(edges) > 0
    has_negative = any(e.energy_kwh < 0.0 for e in edges)
    assert has_negative, "Graph should contain downhill negative edges"
