"""Route.ev FastAPI Backend Server.

Provides RESTful endpoints for EV trip planning, vehicle selection,
corridor inspection, and Pareto multi-objective trade-off analysis.
Exposes metadata flags ('synthetic', 'is_reliability_simulated') so the UI
can render data badges.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    HealthResponse,
    ParetoRequest,
    ParetoResponse,
    PlanRequest,
    PlanResponse,
    SnapshotSummary,
    StationSummary,
)
from core.models import PRESET_CARS, Car, CorridorSnapshot, Trip
from core.planner import EVPlanner
from ingest.stations import compute_data_provenance


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_all_snapshots()
    yield


app = FastAPI(
    title="Route.ev API",
    description="Multi-objective, physics-informed EV trip planner for Indian highway corridors.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for local web development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Planner instance
planner = EVPlanner()

# Snapshot storage cache
_SNAPSHOT_CACHE: dict[str, CorridorSnapshot] = {}
SNAPSHOTS_DIR = Path("data/snapshots")


def load_all_snapshots() -> dict[str, CorridorSnapshot]:
    """Discover and parse all available snapshot JSON files into memory cache."""
    if not SNAPSHOTS_DIR.exists():
        return {}

    for file_path in SNAPSHOTS_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            snapshot = CorridorSnapshot(**data)
            _SNAPSHOT_CACHE[snapshot.id] = snapshot
            # Also key by file stem for convenient lookup
            _SNAPSHOT_CACHE[file_path.stem] = snapshot
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[!] Warning: failed to load snapshot {file_path}: {e}")

    return _SNAPSHOT_CACHE


def get_snapshot(snapshot_id: str) -> CorridorSnapshot:
    """Retrieve snapshot by ID or filename stem, reloading cache if missing."""
    if snapshot_id not in _SNAPSHOT_CACHE:
        load_all_snapshots()

    if snapshot_id not in _SNAPSHOT_CACHE:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot '{snapshot_id}' not found. Available: {list(_SNAPSHOT_CACHE.keys())}",
        )
    return _SNAPSHOT_CACHE[snapshot_id]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """System health check and snapshot readiness status."""
    if not _SNAPSHOT_CACHE:
        load_all_snapshots()

    unique_snapshots = sorted({s.id for s in _SNAPSHOT_CACHE.values()})
    return HealthResponse(
        status="ok",
        version="1.0.0",
        available_snapshots=unique_snapshots,
        timestamp=datetime.now(UTC).isoformat(),
    )


@app.get("/cars", response_model=dict[str, Car])
def list_preset_cars() -> dict[str, Car]:
    """Retrieve list of preconfigured EV vehicle models."""
    return PRESET_CARS


@app.get("/snapshots", response_model=list[SnapshotSummary])
def list_snapshots() -> list[SnapshotSummary]:
    """Retrieve summaries of all available corridors with metadata flags for UI badges."""
    if not _SNAPSHOT_CACHE:
        load_all_snapshots()

    seen_ids = set()
    summaries: list[SnapshotSummary] = []

    for snapshot in _SNAPSHOT_CACHE.values():
        if snapshot.id in seen_ids:
            continue
        seen_ids.add(snapshot.id)

        is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
        provenance = snapshot.metadata.get("data_provenance") or compute_data_provenance(snapshot.stations, snapshot.metadata)
        tot_dist = float(snapshot.metadata.get("total_distance_km", 0.0))
        if tot_dist <= 0.0 and snapshot.edges:
            tot_dist = sum(e.length_m for e in snapshot.edges) / 1000.0

        summaries.append(
            SnapshotSummary(
                id=snapshot.id,
                source_name=snapshot.source_name,
                destination_name=snapshot.destination_name,
                created_at=snapshot.created_at,
                num_nodes=len(snapshot.nodes),
                num_edges=len(snapshot.edges),
                num_stations=len(snapshot.stations),
                total_distance_km=round(tot_dist, 1),
                synthetic=is_synth,
                data_provenance=provenance,
                is_reliability_simulated=True,
                metadata=snapshot.metadata,
            )
        )

    return summaries


@app.get("/snapshots/{snapshot_id}", response_model=SnapshotSummary)
def get_snapshot_details(snapshot_id: str) -> SnapshotSummary:
    """Retrieve metadata and station counts for a specific corridor snapshot."""
    snapshot = get_snapshot(snapshot_id)
    is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
    provenance = snapshot.metadata.get("data_provenance") or compute_data_provenance(snapshot.stations, snapshot.metadata)
    tot_dist = float(snapshot.metadata.get("total_distance_km", 0.0))
    if tot_dist <= 0.0 and snapshot.edges:
        tot_dist = sum(e.length_m for e in snapshot.edges) / 1000.0

    return SnapshotSummary(
        id=snapshot.id,
        source_name=snapshot.source_name,
        destination_name=snapshot.destination_name,
        created_at=snapshot.created_at,
        num_nodes=len(snapshot.nodes),
        num_edges=len(snapshot.edges),
        num_stations=len(snapshot.stations),
        total_distance_km=round(tot_dist, 1),
        synthetic=is_synth,
        data_provenance=provenance,
        is_reliability_simulated=True,
        metadata=snapshot.metadata,
    )


@app.post("/plan", response_model=PlanResponse)
def plan_trip(req: PlanRequest) -> PlanResponse:
    """Plan an optimal EV itinerary with exact charging stops and SoC profile.

    Returns full route trajectory and metadata flags ('synthetic', 'is_reliability_simulated')
    for frontend rendering.
    """
    snapshot = get_snapshot(req.snapshot_id)

    # Resolve vehicle
    if req.custom_car is not None:
        car = req.custom_car
    elif req.car_id in PRESET_CARS:
        car = PRESET_CARS[req.car_id]
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Car '{req.car_id}' not found. Available presets: {list(PRESET_CARS.keys())}",
        )

    # Build Trip query
    try:
        trip = Trip(
            snapshot_id=snapshot.id,
            start_soc=req.start_soc,
            reserve_soc=req.reserve_soc,
            stop_threshold_soc=req.stop_threshold_soc,
            comfort_weight_lambda=req.comfort_weight_lambda,
            K=req.K,
        )
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid trip parameters: {e}")

    # Execute dynamic programming planner
    plan = planner.plan(
        snapshot=snapshot,
        car=car,
        trip=trip,
        lambda_val=req.comfort_weight_lambda,
        enable_filter=req.enable_filter,
    )

    is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
    provenance = snapshot.metadata.get("data_provenance") or compute_data_provenance(snapshot.stations, snapshot.metadata)

    return PlanResponse(
        feasible=plan.feasible,
        infeasibility_reason=plan.infeasibility_reason,
        total_time_min=plan.total_time_min,
        driving_time_min=plan.driving_time_min,
        charging_time_min=plan.charging_time_min,
        total_discomfort_min=plan.total_discomfort_min,
        cost_J=plan.cost_J,
        build_time_ms=plan.build_time_ms,
        search_time_ms=plan.search_time_ms,
        states_expanded=plan.states_expanded,
        edges_relaxed=plan.edges_relaxed,
        stops=plan.stops,
        arrival_soc_dest=plan.arrival_soc_dest,
        route_soc_profile=plan.route_soc_profile,
        pareto_frontier=plan.pareto_frontier,
        corridor_stations=[
            StationSummary(
                id=st.id,
                name=st.name,
                lat=st.lat,
                lon=st.lon,
                operator=st.operator,
                max_kw=st.max_kw,
                amenity_score=st.amenity_score,
                amenities=st.amenities,
                reliability=st.reliability,
                is_reliability_simulated=st.is_reliability_simulated,
                source=getattr(st, "source", "synthetic"),
            )
            for st in snapshot.stations
        ],
        synthetic=is_synth,
        data_provenance=provenance,
        is_reliability_simulated=True,
    )


@app.post("/pareto", response_model=ParetoResponse)
def compute_pareto_frontier(req: ParetoRequest) -> ParetoResponse:
    """Compute supported Pareto frontier points (time vs comfort) via lambda parameter sweep."""
    snapshot = get_snapshot(req.snapshot_id)

    if req.car_id in PRESET_CARS:
        car = PRESET_CARS[req.car_id]
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Car '{req.car_id}' not found. Available presets: {list(PRESET_CARS.keys())}",
        )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=req.start_soc,
        reserve_soc=req.reserve_soc,
        stop_threshold_soc=req.stop_threshold_soc,
        K=req.K,
    )

    points = planner.sweep_pareto(
        snapshot=snapshot,
        car=car,
        trip=trip,
        lambdas=req.lambdas,
    )

    is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
    provenance = snapshot.metadata.get("data_provenance") or compute_data_provenance(snapshot.stations, snapshot.metadata)

    return ParetoResponse(
        points=points,
        synthetic=is_synth,
        data_provenance=provenance,
        is_reliability_simulated=True,
    )


@app.get("/benchmarks")
def get_benchmarks() -> dict[str, Any]:
    """Retrieve precomputed algorithmic benchmark results and measured speedups."""
    bench_path = Path("analysis/benchmark_results.json")
    if bench_path.exists():
        with open(bench_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
