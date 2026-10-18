"""Pydantic API request and response schemas for Route.ev."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.models import Car, ChargingStop, ParetoPoint, RoutePoint


class HealthResponse(BaseModel):
    """Health check endpoint response."""

    status: str = "ok"
    version: str = "1.0.0"
    available_snapshots: list[str]
    timestamp: str


class SnapshotSummary(BaseModel):
    """Corridor snapshot summary including metadata flags for UI badges."""

    id: str
    source_name: str
    destination_name: str
    created_at: str
    num_nodes: int
    num_edges: int
    num_stations: int
    total_distance_km: float
    synthetic: bool = Field(..., description="Flag indicating if corridor topography/stations are synthetic")
    data_provenance: str = Field("synthetic", description="Provenance status: 'verified', 'manual_unverified', or 'synthetic'")
    is_reliability_simulated: bool = Field(True, description="Always True: charger reliability is simulated")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(BaseModel):
    """Trip planning query payload."""

    snapshot_id: str = Field("synthetic_mumbai_pune_v1", description="Corridor snapshot identifier")
    car_id: str = Field("tata_nexon_ev_lr", description="Preset EV vehicle ID (e.g. tata_nexon_ev_lr, mg_zs_ev)")
    custom_car: Car | None = Field(None, description="Optional custom vehicle specifications")
    start_soc: float = Field(0.80, ge=0.0, le=1.0, description="Initial battery SoC fraction in [0, 1]")
    reserve_soc: float = Field(0.10, ge=0.0, le=0.5, description="Safety reserve battery SoC in [0, 1]")
    stop_threshold_soc: float = Field(0.35, ge=0.0, le=1.0, description="Preferred arrival SoC threshold to charge")
    comfort_weight_lambda: float = Field(1.0, ge=0.0, description="Objective weight lambda in J = time + lambda * discomfort")
    K: int = Field(50, ge=5, le=500, description="SoC discretization resolution")
    enable_filter: bool = Field(True, description="Enable greedy range-preserving candidate charger filter")


class StationSummary(BaseModel):
    """Charging station summary for map rendering and provenance auditing."""

    id: str
    name: str
    lat: float
    lon: float
    operator: str
    max_kw: float
    amenity_score: float = 0.0
    amenities: dict[str, int] = Field(default_factory=dict)
    reliability: float = 0.85
    is_reliability_simulated: bool = True
    source: str = "synthetic"


class PlanResponse(BaseModel):
    """Planned EV trip response with metadata flags for frontend badges."""

    feasible: bool
    infeasibility_reason: str | None = None
    total_time_min: float = 0.0
    driving_time_min: float = 0.0
    charging_time_min: float = 0.0
    total_discomfort_min: float = 0.0
    cost_J: float = 0.0
    build_time_ms: float = 0.0
    search_time_ms: float = 0.0
    states_expanded: int = 0
    edges_relaxed: int = 0
    stops: list[ChargingStop] = Field(default_factory=list)
    arrival_soc_dest: float = 0.0
    route_soc_profile: list[RoutePoint] = Field(default_factory=list)
    pareto_frontier: list[ParetoPoint] = Field(default_factory=list)
    corridor_stations: list[StationSummary] = Field(default_factory=list)

    # Metadata flags for UI badges
    synthetic: bool = Field(..., description="Flag for UI: whether corridor is synthetic")
    data_provenance: str = Field("synthetic", description="Provenance status: 'verified', 'manual_unverified', or 'synthetic'")
    is_reliability_simulated: bool = Field(True, description="Flag for UI: charger reliability is simulated")


class ParetoRequest(BaseModel):
    """Pareto frontier sweep request payload."""

    snapshot_id: str = Field("synthetic_mumbai_pune_v1", description="Corridor snapshot identifier")
    car_id: str = Field("tata_nexon_ev_lr", description="Preset EV vehicle ID")
    start_soc: float = Field(0.80, ge=0.0, le=1.0)
    reserve_soc: float = Field(0.10, ge=0.0, le=0.5)
    stop_threshold_soc: float = Field(0.35, ge=0.0, le=1.0)
    K: int = Field(30, ge=5, le=500)
    lambdas: list[float] | None = Field(None, description="Optional custom list of lambda parameters")


class ParetoResponse(BaseModel):
    """Pareto frontier sweep response."""

    points: list[ParetoPoint]
    synthetic: bool
    data_provenance: str = "synthetic"
    is_reliability_simulated: bool = True
