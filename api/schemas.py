"""Pydantic API request and response schemas for Route.ev."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from core.models import Car, ChargingStop, ParetoPoint, RoutePoint, StationAvailability


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
    data_provenance: str = Field("open_data_providers", description="Provenance status: 'verified', 'open_data_providers', 'manual_unverified', or 'synthetic'")
    is_reliability_simulated: bool = Field(True, description="Always True: charger reliability is simulated")
    is_live_build: bool = Field(False, description="Flag for UI: whether corridor was built live from API providers")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanRequest(BaseModel):
    """Trip planning query payload."""

    snapshot_id: str = Field("corridor_18.939_72.835_18.52_73.857", description="Corridor snapshot identifier")
    car_id: str = Field("tata_nexon_ev_lr", description="Preset EV vehicle ID (e.g. tata_nexon_ev_lr, mg_zs_ev)")
    custom_car: Car | None = Field(None, description="Optional custom vehicle specifications")
    start_soc: float = Field(0.80, ge=0.0, le=1.0, description="Initial battery SoC fraction in [0, 1]")
    reserve_soc: float = Field(0.10, ge=0.0, le=0.5, description="Safety reserve battery SoC in [0, 1]")
    stop_threshold_soc: float = Field(0.35, ge=0.0, le=1.0, description="Preferred arrival SoC threshold to charge")
    comfort_weight_lambda: float = Field(1.0, ge=0.0, description="Objective weight lambda in J = time + lambda * discomfort")
    K: int = Field(50, ge=5, le=500, description="SoC discretization resolution")
    enable_filter: bool = Field(True, description="Enable greedy range-preserving candidate charger filter")
    from_saved_snapshot: bool = Field(False, description="Explicitly plan against saved disk snapshot")


class StationSummary(BaseModel):
    """Charging station summary for map rendering and provenance auditing."""

    id: str
    name: str
    lat: float
    lon: float
    operator: str
    max_kw: float
    max_ac_kw: float | None = None
    max_dc_kw: float | None = None
    charger_count: int = 1
    connector_types: list[str] = Field(default_factory=lambda: ["CCS2"])
    availability: StationAvailability | None = None
    amenity_score: float = 0.0
    amenities: dict[str, int] = Field(default_factory=dict)
    reliability: float = 0.85
    is_reliability_simulated: bool = True
    source: str = "synthetic"
    source_url: str | None = None
    fetched_at: str | None = None
    verified: bool = False
    connector_unknown: bool = False
    power_assumed: bool = False
    connector_assumed: bool = False
    amenity_known: bool = False
    spur_estimated: bool = False
    route_distance_km: float = Field(0.0, description="Projected distance along highway route in km")
    data_provider_name: str | None = None
    data_provider_license: str | None = None


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
    route_geometry: list[list[float]] = Field(default_factory=list, description="[[lat, lon], ...] along the road")
    route_distance_km: list[float] = Field(default_factory=list, description="Cumulative distance in km per point")
    pareto_frontier: list[ParetoPoint] = Field(default_factory=list)
    corridor_stations: list[StationSummary] = Field(default_factory=list)

    # Corridor metadata
    source_name: str = Field("Origin", description="True starting city / place name of the corridor")
    destination_name: str = Field("Destination", description="True ending city / place name of the corridor")
    snapshot_id: str = Field("", description="Snapshot ID of the loaded corridor")
    sources_used: list[str] = Field(default_factory=list, description="Station provider sources contributing to corridor")

    # Metadata flags for UI badges
    synthetic: bool = Field(..., description="Flag for UI: whether corridor is synthetic")
    data_provenance: str = Field("open_data_providers", description="Provenance status: 'verified', 'open_data_providers', 'manual_unverified', or 'synthetic'")
    is_reliability_simulated: bool = Field(True, description="Flag for UI: charger reliability is simulated")
    is_live_build: bool = Field(False, description="Flag for UI: whether plan was built fresh from live providers vs loaded from saved snapshot")
    elevation_available: bool = Field(True, description="Flag for UI: whether elevation data was available")
    is_demo_mode: bool = Field(False, description="Flag for UI: whether demo mode is active with illustrative data")
    api_calls: dict[str, int] = Field(default_factory=dict, description="API calls made per station provider")



class GeocodeCandidate(BaseModel):
    """Geocode autocomplete search suggestion."""

    label: str = Field(..., description="Formatted display name / address")
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


class LocationSpec(BaseModel):
    """Waypoint location specification with strict coordinate range bounds."""

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in range [-90, 90]")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in range [-180, 180]")
    label: str = ""


class RouteBuildRequest(BaseModel):
    """Request payload to asynchronously build a real corridor snapshot."""

    origin: LocationSpec
    destination: LocationSpec
    use_synthetic: bool = False
    force_refresh: bool = False
    max_routes: int = Field(2, ge=1, le=3, description="Maximum road alternatives to build and compare")


class BuiltRouteOption(BaseModel):
    """Summary of one built road-route candidate."""

    route_number: int
    snapshot_id: str
    distance_km: float
    driving_time_min: float
    station_count: int


class JobStatusResponse(BaseModel):
    """Status update for an asynchronous pipeline job."""

    job_id: str
    status: str = Field(..., description="'pending' | 'running' | 'completed' | 'failed'")
    progress_step: str = ""
    percent: int = 0
    error_message: str | None = None
    snapshot_id: str | None = None
    route_options: list[BuiltRouteOption] = Field(default_factory=list)



class ParetoRequest(BaseModel):
    """Pareto frontier sweep request payload."""

    snapshot_id: str = Field("corridor_28.614_77.209_27.177_78.008", description="Corridor snapshot identifier")
    car_id: str = Field("tata_nexon_ev_lr", description="Preset EV vehicle ID")
    start_soc: float = Field(0.80, ge=0.0, le=1.0)
    reserve_soc: float = Field(0.10, ge=0.0, le=0.5)
    stop_threshold_soc: float = Field(0.35, ge=0.0, le=1.0)
    K: int = Field(30, ge=5, le=500)
    lambdas: list[float] | None = Field(None, description="Optional custom list of lambda parameters")

    @field_validator("lambdas")
    @classmethod
    def validate_lambdas(cls, v: list[float] | None) -> list[float] | None:
        if v is not None:
            import math
            for lam in v:
                if not math.isfinite(lam) or lam < 0.0:
                    raise ValueError(f"Each lambda must be a finite non-negative number, got {lam}")
        return v


class ParetoResponse(BaseModel):
    """Pareto frontier sweep response."""

    points: list[ParetoPoint]
    synthetic: bool
    data_provenance: str = "open_data_providers"
    is_reliability_simulated: bool = True


class StationRefreshRequest(BaseModel):
    """Payload to trigger manual stations cache invalidation and snapshot rebuild."""

    snapshot_id: str | None = None

