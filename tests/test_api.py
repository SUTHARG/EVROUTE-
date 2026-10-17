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
