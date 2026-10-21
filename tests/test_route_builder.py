"""Tests for asynchronous route building pipeline and job status polling."""

import time

from fastapi.testclient import TestClient

from api.main import app
from ingest.build_snapshot import build_corridor_from_coords

client = TestClient(app)


def test_build_corridor_from_coords_synthetic(tmp_path):
    """Test build_corridor_from_coords in synthetic mode creates valid snapshot."""
    progress_updates = []

    def on_progress(step: str, pct: int):
        progress_updates.append((step, pct))

    snap = build_corridor_from_coords(
        origin_lat=28.6139,
        origin_lon=77.2090,
        origin_label="Delhi",
        dest_lat=27.1767,
        dest_lon=78.0081,
        dest_label="Agra",
        use_synthetic=True,
        progress_callback=on_progress,
        output_dir=tmp_path,
    )

    assert snap.id.startswith(("corridor_", "synthetic_"))
    assert len(snap.nodes) > 0
    assert len(snap.edges) > 0
    assert len(progress_updates) >= 2
    assert progress_updates[-1][1] == 100


def test_routes_build_job_api(monkeypatch, tmp_path):
    """Test POST /routes/build returns job_id and GET /jobs/{job_id} tracks completion."""
    import api.main as api_main

    real_builder = api_main.build_corridor_from_coords

    def deterministic_builder(**kwargs):
        kwargs["use_synthetic"] = True
        kwargs["output_dir"] = tmp_path
        return real_builder(**kwargs)

    monkeypatch.setattr(api_main, "build_corridor_from_coords", deterministic_builder)
    build_payload = {
        "origin": {"lat": 18.9388, "lon": 72.8354, "label": "Mumbai"},
        "destination": {"lat": 18.5204, "lon": 73.8567, "label": "Pune"},
        "use_synthetic": False,
    }

    resp = client.post("/routes/build", json=build_payload)
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]
    assert job_id is not None
    assert data["status"] in ("pending", "running", "completed")

    # Poll status
    completed = False
    for _ in range(120):
        time.sleep(0.3)
        poll_resp = client.get(f"/jobs/{job_id}")
        assert poll_resp.status_code == 200
        job_data = poll_resp.json()
        if job_data["status"] == "completed":
            completed = True
            assert job_data["snapshot_id"] is not None
            assert job_data["percent"] == 100
            break
        elif job_data["status"] == "failed":
            raise AssertionError(f"Job failed unexpectedly: {job_data.get('error_message')}")

    assert completed, "Expected route building job to complete"
