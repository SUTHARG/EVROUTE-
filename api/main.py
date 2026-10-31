"""Route.ev FastAPI Backend Server.

Provides RESTful endpoints for EV trip planning, vehicle selection,
corridor inspection, and Pareto multi-objective trade-off analysis.
Exposes metadata flags ('synthetic', 'is_reliability_simulated') so the UI
can render data badges.
"""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    GeocodeCandidate,
    HealthResponse,
    JobStatusResponse,
    BuiltRouteOption,
    ParetoRequest,
    ParetoResponse,
    PlanRequest,
    PlanResponse,
    RouteBuildRequest,
    SnapshotSummary,
    StationRefreshRequest,
    StationSummary,
)
from api.snapshot_store import SNAPSHOT_CACHE as _SNAPSHOT_CACHE
from api.snapshot_store import SNAPSHOTS_DIR, get_snapshot, load_all_snapshots
from core.models import PRESET_CARS, Car, Trip
from core.planner import EVPlanner
from ingest.build_snapshot import build_corridor_from_coords
from ingest.geocode import search_geocode
from ingest.stations import compute_data_provenance

_executor = ThreadPoolExecutor(max_workers=4)
_JOBS: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.config import GOOGLE_MAPS_API_KEY, OCM_API_KEY
    from ingest.ocm_snapshot import get_ocm_snapshot_file

    if not OCM_API_KEY:
        print("INFO:     Startup check: OCM_API_KEY not set (Open Charge Map API will be bypassed)")
    else:
        print("INFO:     Startup check: OCM_API_KEY configured")

    if not GOOGLE_MAPS_API_KEY:
        print("INFO:     Startup check: GOOGLE_MAPS_API_KEY not set (Google Places API will be bypassed)")
    else:
        print("INFO:     Startup check: GOOGLE_MAPS_API_KEY configured")

    ocm_file = get_ocm_snapshot_file()
    if ocm_file:
        print(f"INFO:     Startup check: Local OCM snapshot found at {ocm_file}")
    else:
        print("INFO:     Startup check: No local OCM snapshot file in data/ocm_snapshot/")

    from ingest.station_providers import ManualVerifiedCSVProvider

    valid_csv, rejected_csv = ManualVerifiedCSVProvider.inspect_verified_csv_at_startup()
    print(
        f"INFO:     Startup check: verified_stations.csv has {valid_csv} valid rows "
        f"({rejected_csv} rows rejected for missing source_url or checked_on)"
    )

    load_all_snapshots()
    yield


app = FastAPI(
    title="Route.ev API",
    description="Multi-objective, physics-informed EV trip planner for Indian highway corridors.",
    version="1.0.0",
    lifespan=lifespan,
)

# Explicit CORS for local web development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Planner instance
planner = EVPlanner()

# Snapshot storage cache
_LIVE_BUILT_SNAPSHOTS: set[str] = set()


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


@app.get("/health/sources")
def health_sources() -> dict[str, Any]:
    """List data providers and operational availability without exposing secrets."""
    from core.config import get_google_maps_api_key, get_ocm_api_key
    from ingest.ocm_snapshot import get_ocm_snapshot_file
    from ingest.station_providers import ManualVerifiedCSVProvider

    valid_csv, rejected_csv = ManualVerifiedCSVProvider.inspect_verified_csv_at_startup()

    return {
        "providers": {
            "verified_manual": bool(Path("data/stations/verified_stations.csv").exists()),
            "google_places": bool(get_google_maps_api_key()),
            "ocm_api": bool(get_ocm_api_key()),
            "ocm_snapshot": bool(get_ocm_snapshot_file() is not None),
            "osm_overpass": True,
        },
        "verified_manual_stats": {
            "valid_rows": valid_csv,
            "rejected_rows": rejected_csv,
        },
    }


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
        provenance = compute_data_provenance(snapshot.stations, snapshot.metadata)
        is_live = bool(snapshot.metadata.get("is_live_build", False) or snapshot.id in _LIVE_BUILT_SNAPSHOTS)
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
                is_live_build=is_live,
                metadata=snapshot.metadata,
            )
        )

    return summaries


@app.get("/snapshots/{snapshot_id}", response_model=SnapshotSummary)
def get_snapshot_details(snapshot_id: str) -> SnapshotSummary:
    """Retrieve metadata and station counts for a specific corridor snapshot."""
    snapshot = get_snapshot(snapshot_id)
    is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
    provenance = compute_data_provenance(snapshot.stations, snapshot.metadata)
    is_live = bool(snapshot.metadata.get("is_live_build", False) or snapshot.id in _LIVE_BUILT_SNAPSHOTS)
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
        is_live_build=is_live,
        metadata=snapshot.metadata,
    )


@app.get("/geocode", response_model=list[GeocodeCandidate])
def geocode_location(q: str, limit: int = 5, countrycodes: str = "in") -> list[GeocodeCandidate]:
    """Proxy geocoding query to Nominatim with rate-limiting, disk cache, and offline fallback."""
    candidates = search_geocode(query=q, limit=limit, countrycodes=countrycodes)
    return [GeocodeCandidate(**c) for c in candidates]


@app.post("/routes/build", response_model=JobStatusResponse)
def build_route_job(req: RouteBuildRequest) -> JobStatusResponse:
    """Start an asynchronous job to construct a road-following corridor snapshot."""
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress_step": "Initializing corridor builder...",
        "percent": 0,
        "error_message": None,
        "snapshot_id": None,
        "route_options": [],
    }

    def _worker():
        try:
            if req.use_synthetic:
                route_data_options = [None]
            else:
                from ingest.route import OSRMClient

                route_data_options = OSRMClient().get_routes(
                    (req.origin.lat, req.origin.lon),
                    (req.destination.lat, req.destination.lon),
                    max_routes=req.max_routes,
                )
            if not route_data_options:
                raise ValueError("The routing provider returned no route alternatives.")

            built_options: list[BuiltRouteOption] = []
            total_options = len(route_data_options)
            for route_index, route_data in enumerate(route_data_options):
                def _update(step: str, pct: int, index: int = route_index):
                    overall_pct = int(((index + pct / 100.0) / total_options) * 100)
                    _JOBS[job_id]["progress_step"] = (
                        f"Building route {index + 1} of {total_options}: {step}"
                    )
                    _JOBS[job_id]["percent"] = overall_pct

                try:
                    snapshot = build_corridor_from_coords(
                        origin_lat=req.origin.lat,
                        origin_lon=req.origin.lon,
                        origin_label=req.origin.label,
                        dest_lat=req.destination.lat,
                        dest_lon=req.destination.lon,
                        dest_label=req.destination.label,
                        use_synthetic=req.use_synthetic,
                        progress_callback=_update,
                        force_refresh=req.force_refresh,
                        route_data_override=route_data,
                        route_variant_index=route_index,
                    )
                except Exception as route_exc:  # noqa: BLE001
                    _JOBS[job_id]["progress_step"] = (
                        f"Skipping route {route_index + 1}: {route_exc}"
                    )
                    continue
                _SNAPSHOT_CACHE[snapshot.id] = snapshot
                if not req.use_synthetic:
                    _LIVE_BUILT_SNAPSHOTS.add(snapshot.id)
                distance_km = float(snapshot.metadata.get("total_distance_km", 0.0))
                driving_time_min = sum(edge.time_s for edge in snapshot.edges) / 60.0
                built_options.append(
                    BuiltRouteOption(
                        route_number=route_index + 1,
                        snapshot_id=snapshot.id,
                        distance_km=round(distance_km, 1),
                        driving_time_min=round(driving_time_min, 1),
                        station_count=len(snapshot.stations),
                    )
                )
                _JOBS[job_id]["route_options"] = [
                    option.model_dump() for option in built_options
                ]
                if _JOBS[job_id]["snapshot_id"] is None:
                    _JOBS[job_id]["snapshot_id"] = snapshot.id

            if not built_options:
                raise ValueError("Unable to build a charging corridor for any returned road route.")
            _JOBS[job_id]["status"] = "completed"
            _JOBS[job_id]["percent"] = 100
            _JOBS[job_id]["progress_step"] = (
                f"{len(built_options)} route option(s) ready for EV feasibility comparison"
            )
        except Exception as exc:  # noqa: BLE001
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error_message"] = str(exc)
            _JOBS[job_id]["progress_step"] = f"Failed: {exc}"

    _executor.submit(_worker)
    return JobStatusResponse(**_JOBS[job_id])


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Poll status of an asynchronous corridor building job."""
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JobStatusResponse(**_JOBS[job_id])


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

    # Strict road geometry validation
    if not snapshot.nodes or len(snapshot.nodes) < 2 or not snapshot.edges:
        raise HTTPException(
            status_code=422,
            detail="Corridor snapshot does not contain valid road-following geometry: straight line routes are strictly disallowed.",
        )

    # Execute dynamic programming planner
    plan = planner.plan(
        snapshot=snapshot,
        car=car,
        trip=trip,
        lambda_val=req.comfort_weight_lambda,
        enable_filter=req.enable_filter,
    )

    if not plan.route_geometry or len(plan.route_geometry) < 2:
        raise HTTPException(
            status_code=422,
            detail="Corridor snapshot does not contain valid road-following geometry: straight line routes are strictly disallowed.",
        )

    is_synth = bool(snapshot.metadata.get("synthetic", False) or "synthetic" in snapshot.id)
    provenance = compute_data_provenance(snapshot.stations, snapshot.metadata)

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
                max_ac_kw=getattr(st, "max_ac_kw", None),
                max_dc_kw=getattr(st, "max_dc_kw", None),
                charger_count=getattr(st, "charger_count", 1),
                connector_types=getattr(st, "connector_types", ["CCS2"]),
                availability=getattr(st, "availability", None),
                amenity_score=st.amenity_score,
                amenities=st.amenities,
                reliability=st.reliability,
                is_reliability_simulated=st.is_reliability_simulated,
                source=getattr(st, "source", "synthetic"),
                source_url=getattr(st, "source_url", None),
                fetched_at=getattr(st, "fetched_at", None),
                verified=getattr(st, "verified", False),
                connector_unknown=getattr(st, "connector_unknown", False),
                power_assumed=getattr(st, "power_assumed", False),
                connector_assumed=getattr(st, "connector_assumed", False),
                amenity_known=getattr(st, "amenity_known", False),
                spur_estimated=getattr(st, "spur_estimated", False),
                route_distance_km=getattr(st, "route_distance_km", 0.0),
                data_provider_name=getattr(st, "data_provider_name", None),
                data_provider_license=getattr(st, "data_provider_license", None),
            )
            for st in snapshot.stations
        ],
        source_name=snapshot.source_name,
        destination_name=snapshot.destination_name,
        snapshot_id=snapshot.id,
        sources_used=snapshot.metadata.get("sources_used") or sorted({getattr(st, "source", "") for st in snapshot.stations if getattr(st, "source", None)}),
        route_geometry=plan.route_geometry,
        route_distance_km=plan.route_distance_km,
        synthetic=is_synth,
        data_provenance=provenance,
        is_reliability_simulated=True,
        is_live_build=False if req.from_saved_snapshot else bool(snapshot.metadata.get("is_live_build", False) or snapshot.id in _LIVE_BUILT_SNAPSHOTS),
        elevation_available=getattr(plan, "elevation_available", True),
        is_demo_mode=(
            provenance == "manual_unverified"
            or any(getattr(s, "source", "") == "unverified_illustrative" for s in snapshot.stations)
        ),
        api_calls=snapshot.metadata.get("provider_stats", {}).get("api_calls_made", {}),
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
    provenance = compute_data_provenance(snapshot.stations, snapshot.metadata)

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


@app.post("/stations/refresh")
def refresh_stations(req: StationRefreshRequest | None = None) -> dict[str, Any]:
    """Manually clear OCM cache and invalidate cached corridor snapshot."""
    from ingest.cache import DiskCache

    ocm_cache = DiskCache("ocm")
    cleared = ocm_cache.clear()

    snapshot_cleared = False
    snap_id = req.snapshot_id if req else None
    if snap_id and snap_id in _SNAPSHOT_CACHE:
        snap_file = SNAPSHOTS_DIR / f"{snap_id}.json"
        if snap_file.exists():
            try:
                snap_file.unlink()
                snapshot_cleared = True
            except OSError:
                pass
        _SNAPSHOT_CACHE.pop(snap_id, None)

    return {
        "status": "ok",
        "cleared_cache_entries": cleared,
        "snapshot_cleared": snapshot_cleared,
        "message": f"Cleared {cleared} cached OCM entries and invalidated corridor cache.",
    }

