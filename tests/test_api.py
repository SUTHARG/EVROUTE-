"""Unit and integration tests for Route.ev FastAPI endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_endpoint():
    """Verify system health endpoint and snapshot availability."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert "synthetic_mumbai_pune_v1" in data["available_snapshots"]


def test_cars_endpoint():
    """Verify preset vehicle catalog retrieval."""
    resp = client.get("/cars")
    assert resp.status_code == 200
    cars = resp.json()
    assert "tata_nexon_ev_lr" in cars
    assert cars["tata_nexon_ev_lr"]["battery_kwh"] > 35.0


def test_snapshots_endpoint():
    """Verify corridor summaries and metadata flags (synthetic, reliability simulated)."""
    resp = client.get("/snapshots")
    assert resp.status_code == 200
    snapshots = resp.json()
    assert len(snapshots) >= 1

    synthetic_snap = next(
        (s for s in snapshots if s["id"] == "synthetic_mumbai_pune_v1"),
        None,
    )
    assert synthetic_snap is not None
    assert synthetic_snap["synthetic"] is True
    assert synthetic_snap["data_provenance"] == "synthetic"
    assert synthetic_snap["is_reliability_simulated"] is True
    assert synthetic_snap["num_stations"] > 0


def test_snapshot_details_endpoint():
    """Verify single snapshot inspection endpoint."""
    resp = client.get("/snapshots/synthetic_mumbai_pune_v1")
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["id"] == "synthetic_mumbai_pune_v1"
    assert snap["synthetic"] is True

    # 404 for unknown snapshot
    resp_404 = client.get("/snapshots/non_existent_corridor_xyz")
    assert resp_404.status_code == 404


def test_plan_trip_synthetic():
    """Verify trip planning on the synthetic snapshot with metadata flags."""
    payload = {
        "snapshot_id": "synthetic_mumbai_pune_v1",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 40,
        "enable_filter": True,
    }
    resp = client.post("/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()

    assert plan["feasible"] is True
    assert plan["total_time_min"] > 0.0
    assert plan["driving_time_min"] > 0.0
    assert plan["cost_J"] > 0.0
    assert plan["arrival_soc_dest"] >= 0.10
    assert len(plan["route_soc_profile"]) > 10

    # Assert required metadata flags for frontend badges
    assert plan["synthetic"] is True
    assert plan["data_provenance"] == "synthetic"
    assert plan["is_reliability_simulated"] is True


def test_plan_trip_infeasible():
    """Verify proper diagnostic reporting when vehicle battery cannot bridge route gaps."""
    payload = {
        "snapshot_id": "synthetic_mumbai_pune_v1",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.11,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "comfort_weight_lambda": 1.0,
        "K": 30,
        "enable_filter": True,
    }
    resp = client.post("/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()

    assert plan["feasible"] is False
    assert plan["infeasibility_reason"] is not None
    assert "infeasible" in plan["infeasibility_reason"].lower()
    assert plan["synthetic"] is True


def test_pareto_endpoint():
    """Verify Pareto frontier lambda sweep endpoint."""
    payload = {
        "snapshot_id": "synthetic_mumbai_pune_v1",
        "car_id": "tata_nexon_ev_lr",
        "start_soc": 0.80,
        "reserve_soc": 0.10,
        "stop_threshold_soc": 0.35,
        "K": 20,
        "lambdas": [0.01, 1.0, 5.0],
    }
    resp = client.post("/pareto", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert "points" in data
    assert len(data["points"]) >= 1
    assert data["synthetic"] is True
    assert data["data_provenance"] == "synthetic"
    assert data["is_reliability_simulated"] is True


def test_invalid_requests():
    """Verify validation error handling for invalid payloads and parameters."""
    # Unknown car
    resp_bad_car = client.post(
        "/plan",
        json={"snapshot_id": "synthetic_mumbai_pune_v1", "car_id": "unknown_car_xyz"},
    )
    assert resp_bad_car.status_code == 404

    # Invalid SoC (start_soc < reserve_soc)
    resp_bad_soc = client.post(
        "/plan",
        json={
            "snapshot_id": "synthetic_mumbai_pune_v1",
            "car_id": "tata_nexon_ev_lr",
            "start_soc": 0.05,
            "reserve_soc": 0.15,
        },
    )
    assert resp_bad_soc.status_code == 422


def test_downhill_regen_before_stop_explicit_distance():
    """Verify that a route with downhill regen before a charging stop does not confuse regen with charging.

    The planner must return explicit stop['route_distance_km'] matching the known station km,
    and profile points must distinguish 'regen' events from 'charge' events without inferring stops
    from SoC jumps (since downhill regen also increases SoC).
    """
    from core.models import PRESET_CARS, CorridorSnapshot, RoadEdge, RoadNode, Station, Trip
    from core.planner import EVPlanner

    # Create a corridor:
    # Node 0 (km 0, elev 800m) -> Node 1 (km 20, elev 100m, steep downhill, regen increases SoC)
    # Station S1 located exactly at Node 1 (km 20.0)
    # Node 1 -> Node 2 (km 60, elev 700m, steep uphill requiring charge at S1)
    nodes = {
        0: RoadNode(id=0, lat=18.0, lon=73.0, elevation_m=800.0),
        1: RoadNode(id=1, lat=18.1, lon=73.1, elevation_m=100.0),
        2: RoadNode(id=2, lat=18.3, lon=73.3, elevation_m=700.0),
    }
    edges = [
        RoadEdge(u=0, v=1, length_m=20000.0, time_s=1200.0, elevation_gain_m=-700.0, energy_kwh=-2.5),
        RoadEdge(u=1, v=2, length_m=40000.0, time_s=2400.0, elevation_gain_m=600.0, energy_kwh=10.0),
    ]
    stations = [
        Station(
            id="st_downhill_20km",
            name="Known Km 20 Charger",
            operator="AuditCharger",
            lat=18.1,
            lon=73.1,
            max_kw=120.0,
            road_node_id=1,
            detour_distance_m=0.0,
            detour_time_s=0.0,
            detour_energy_kwh=0.0,
            source="synthetic",
            connector_types=["CCS2"],
        )
    ]
    snap = CorridorSnapshot(
        id="regen_downhill_audit",
        source_name="Origin",
        destination_name="Destination",
        created_at="2026-10-18T00:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=stations,
        source_node_id=0,
        destination_node_id=2,
    )
    car = PRESET_CARS["tata_tiago_ev"].model_copy()
    car.battery_kwh = 20.0

    trip = Trip(
        snapshot_id="regen_downhill_audit",
        source_id="source",
        destination_id="dest",
        start_soc=0.20,
        reserve_soc=0.10,
        stop_threshold_soc=0.25,
        comfort_weight_lambda=1.0,
        K=20,
    )

    planner = EVPlanner()
    plan = planner.plan(
        snapshot=snap,
        car=car,
        trip=trip,
        enable_filter=False,
    )

    assert plan.feasible is True
    assert len(plan.stops) == 1
    stop = plan.stops[0]

    # Explicit stop distance must equal exactly 20.0 km
    assert abs(stop.route_distance_km - 20.0) < 1e-3, (
        f"Expected stop.route_distance_km to be exactly 20.0 km, got {stop.route_distance_km}"
    )

    # In the profile, verify that downhill segment produced regen points AND a separate charge point
    events = [pt.event for pt in plan.route_soc_profile if pt.event is not None]
    assert "regen" in events, f"Expected downhill segment to have 'regen' event, got events: {set(events)}"
    assert "charge" in events, f"Expected charging stop to have 'charge' event, got events: {set(events)}"

    # Crucial assertion: A naive detector counting ANY SoC jump > 0.005 would see at least 2 increases
    # (downhill regen + charging stop), which fails if stops are inferred from SoC jumps alone!
    soc_increases = [
        (curr.distance_km, prev.soc, curr.soc)
        for prev, curr in zip(plan.route_soc_profile[:-1], plan.route_soc_profile[1:])
        if curr.soc > prev.soc + 0.001
    ]
    assert len(soc_increases) >= 2, (
        "Downhill regen plus charging must produce >= 2 upward SoC increases, proving naive jump detection is ambiguous"
    )



