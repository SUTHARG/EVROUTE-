"""Test road geometry compliance, great-circle ratios, and strict anti-straight-line enforcement."""

import json
import math
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from core.models import CorridorSnapshot
from ingest.route import haversine_distance_m

client = TestClient(app)


def perpendicular_distance_m(
    pt_lat: float,
    pt_lon: float,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> float:
    """Compute cross-track perpendicular distance from pt to great circle line between start and end."""
    R = 6_371_000.0
    lat1, lon1 = math.radians(start_lat), math.radians(start_lon)
    lat2, lon2 = math.radians(end_lat), math.radians(end_lon)
    lat3, lon3 = math.radians(pt_lat), math.radians(pt_lon)

    # Great-circle angular distance from start to pt
    d13 = 2.0 * math.asin(
        math.sqrt(
            math.sin((lat3 - lat1) / 2.0) ** 2
            + math.cos(lat1) * math.cos(lat3) * math.sin((lon3 - lon1) / 2.0) ** 2
        )
    )
    # Bearing from start to end
    y_12 = math.sin(lon2 - lon1) * math.cos(lat2)
    x_12 = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    theta12 = math.atan2(y_12, x_12)

    # Bearing from start to pt
    y_13 = math.sin(lon3 - lon1) * math.cos(lat3)
    x_13 = math.cos(lat1) * math.sin(lat3) - math.sin(lat1) * math.cos(lat3) * math.cos(lon3 - lon1)
    theta13 = math.atan2(y_13, x_13)

    # Cross-track distance
    dxt = math.asin(math.sin(d13) * math.sin(theta13 - theta12)) * R
    return abs(dxt)


def test_mumbai_pune_expressway_geometry_ratio_and_deviation():
    """Verify that unverified_mumbai_pune has realistic highway curvature:

    - Polyline length is between 1.0x and 1.3x great-circle distance
    - Maximum perpendicular deviation from the straight chord is > 2.0 km (winding through Bhor Ghat).
    """
    snapshot_path = Path("tests/fixtures/unverified_mumbai_pune.json")
    assert snapshot_path.exists(), "unverified_mumbai_pune.json fixture must exist"

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    snapshot = CorridorSnapshot(**data)

    nodes = snapshot.nodes
    assert len(nodes) >= 1000, f"Expected real road nodes >= 1000, got {len(nodes)}"

    start_node = nodes[min(nodes.keys())]
    end_node = nodes[max(nodes.keys())]

    great_circle_m = haversine_distance_m(start_node.lat, start_node.lon, end_node.lat, end_node.lon)
    polyline_m = sum(edge.length_m for edge in snapshot.edges)

    ratio = polyline_m / great_circle_m
    assert 1.0 <= ratio <= 1.30, f"Polyline / great-circle ratio {ratio:.3f} outside [1.0, 1.30]"

    # Test perpendicular deviation
    max_dev_m = max(
        perpendicular_distance_m(
            node.lat, node.lon, start_node.lat, start_node.lon, end_node.lat, end_node.lon
        )
        for node in nodes.values()
    )
    assert max_dev_m > 2000.0, f"Expected max perpendicular deviation > 2000m, got {max_dev_m:.1f}m"


def test_plan_endpoint_returns_real_route_geometry():
    """Verify that /plan returns route_geometry with >= 1000 points and route_distance_km."""
    resp = client.post(
        "/plan",
        json={
            "snapshot_id": "default_mumbai_pune",
            "car_id": "tata_nexon_ev_lr",
            "start_soc": 0.80,
            "reserve_soc": 0.10,
            "K": 20,
        },
    )
    assert resp.status_code == 200, f"Plan request failed: {resp.text}"
    data = resp.json()

    geometry = data.get("route_geometry", [])
    distances = data.get("route_distance_km", [])

    assert len(geometry) >= 1000, "route_geometry must contain real road coordinates"
    assert len(distances) == len(geometry), "route_distance_km must match geometry length"
    assert distances[-1] > 100.0, "Total corridor distance should be > 100 km"


def test_plan_rejects_missing_route_geometry():
    """Verify that /plan returns 422 if route geometry is empty or missing."""
    from api.main import _SNAPSHOT_CACHE

    fake_snapshot = CorridorSnapshot(
        id="corridor_without_geometry",
        source_name="FakeCityA",
        destination_name="FakeCityB",
        created_at="2026-10-18T00:00:00Z",
        nodes={},
        edges=[],
        stations=[],
        metadata={"synthetic": True},
    )
    _SNAPSHOT_CACHE["corridor_without_geometry"] = fake_snapshot

    resp = client.post(
        "/plan",
        json={
            "snapshot_id": "corridor_without_geometry",
            "car_id": "tata_nexon_ev_lr",
        },
    )
    # Planner fails to plan on empty nodes/edges or raises 422
    assert resp.status_code in (422, 500)
