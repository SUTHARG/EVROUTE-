"""Domain models for Route.ev EV trip planning system.

Defines Pydantic models for vehicles, charging stations, road network
elements, reduced charger-graph transitions, trips, and planning results.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class Car(BaseModel):
    """Electric Vehicle specification profile.

    Attributes:
        id: Unique identifier for vehicle profile.
        name: Commercial or descriptive name.
        battery_kwh: Total battery pack capacity in kilowatt-hours.
        usable_fraction: Fraction of battery capacity accessible for driving (e.g. 0.95).
        consumption_kwh_per_km: Rated energy consumption at reference speed (70 km/h).
        mass_kg: Vehicle curb mass plus driver/passenger payload in kilograms.
        drag_coefficient: Aerodynamic drag coefficient (Cd, dimensionless).
        frontal_area_m2: Vehicle frontal area in square meters (A).
        max_dc_kw: Maximum supported DC fast-charging intake power in kW.
        regen_efficiency: Regenerative braking recovery efficiency (strictly < 1.0).
        drivetrain_efficiency: Efficiency of motor and inverter under traction (default 0.90).
        auxiliary_power_kw: Base electric power load for HVAC and electronics in kW.
        supported_connectors: List of compatible charging connector standards.
        is_placeholder_profile: Flag indicating whether values are approximate placeholders.
        description: Informational profile notes.
    """

    id: str
    name: str
    battery_kwh: float = Field(..., gt=0.0, description="Gross battery capacity in kWh")
    usable_fraction: float = Field(0.95, gt=0.5, le=1.0, description="Usable battery fraction")
    consumption_kwh_per_km: float = Field(
        ..., gt=0.0, description="Rated consumption at v_ref (70 km/h) in kWh/km"
    )
    mass_kg: float = Field(..., gt=0.0, description="Total vehicle mass in kg")
    drag_coefficient: float = Field(0.30, gt=0.1, le=0.6, description="Aerodynamic Cd")
    frontal_area_m2: float = Field(2.30, gt=1.0, le=5.0, description="Frontal area in m^2")
    max_dc_kw: float = Field(..., gt=0.0, description="Max DC fast charging rate in kW")
    regen_efficiency: float = Field(
        0.75, gt=0.0, lt=1.0, description="Regen recovery efficiency (strictly < 1.0)"
    )
    drivetrain_efficiency: float = Field(
        0.90, gt=0.5, lt=1.0, description="Drivetrain motor/inverter efficiency"
    )
    auxiliary_power_kw: float = Field(
        0.0, ge=0.0, description="Auxiliary electric load (HVAC, computer) in kW"
    )
    supported_connectors: list[str] = Field(
        default_factory=lambda: ["CCS2"], description="Supported DC charging plugs"
    )
    is_placeholder_profile: bool = Field(
        True, description="Indicates approximate placeholder profile, user-editable"
    )
    description: str = Field(
        "Approximate placeholder profile, user-editable",
        description="Profile metadata notes",
    )

    @property
    def usable_battery_kwh(self) -> float:
        """Usable battery energy capacity in kWh."""
        return self.battery_kwh * self.usable_fraction

    def effective_energy_kwh(self, reserve_soc: float) -> float:
        """Effective energy available above safety reserve buffer in kWh.

        Complexity: O(1).
        """
        return self.usable_battery_kwh * max(0.0, 1.0 - reserve_soc)


# Example preset vehicle profiles (clearly marked as approximate placeholder values)
PRESET_CARS: dict[str, Car] = {
    "tata_nexon_ev_lr": Car(
        id="tata_nexon_ev_lr",
        name="Tata Nexon EV Long Range (Placeholder)",
        battery_kwh=40.5,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.140,  # 140 Wh/km
        mass_kg=1400.0,
        drag_coefficient=0.33,
        frontal_area_m2=2.30,
        max_dc_kw=50.0,
        regen_efficiency=0.75,
        drivetrain_efficiency=0.90,
        auxiliary_power_kw=0.0,
        supported_connectors=["CCS2"],
        is_placeholder_profile=True,
        description="Approximate placeholder profile for Tata Nexon EV LR, user-editable.",
    ),
    "mg_zs_ev": Car(
        id="mg_zs_ev",
        name="MG ZS EV (Placeholder)",
        battery_kwh=50.3,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.155,  # 155 Wh/km
        mass_kg=1620.0,
        drag_coefficient=0.32,
        frontal_area_m2=2.40,
        max_dc_kw=75.0,
        regen_efficiency=0.75,
        drivetrain_efficiency=0.90,
        auxiliary_power_kw=0.0,
        supported_connectors=["CCS2"],
        is_placeholder_profile=True,
        description="Approximate placeholder profile for MG ZS EV, user-editable.",
    ),
    "hyundai_ioniq_5": Car(
        id="hyundai_ioniq_5",
        name="Hyundai Ioniq 5 (Placeholder)",
        battery_kwh=72.6,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.160,  # 160 Wh/km
        mass_kg=1910.0,
        drag_coefficient=0.288,
        frontal_area_m2=2.50,
        max_dc_kw=220.0,
        regen_efficiency=0.82,
        drivetrain_efficiency=0.92,
        auxiliary_power_kw=0.0,
        supported_connectors=["CCS2"],
        is_placeholder_profile=True,
        description="Approximate placeholder profile for Hyundai Ioniq 5, user-editable.",
    ),
    "tata_tiago_ev": Car(
        id="tata_tiago_ev",
        name="Tata Tiago EV (Placeholder)",
        battery_kwh=24.0,
        usable_fraction=0.95,
        consumption_kwh_per_km=0.120,  # 120 Wh/km
        mass_kg=1150.0,
        drag_coefficient=0.33,
        frontal_area_m2=2.10,
        max_dc_kw=25.0,
        regen_efficiency=0.70,
        drivetrain_efficiency=0.88,
        auxiliary_power_kw=0.0,
        supported_connectors=["CCS2"],
        is_placeholder_profile=True,
        description="Approximate placeholder profile for Tata Tiago EV, user-editable.",
    ),
}


class Station(BaseModel):
    """EV Charging station with amenities and simulated reliability.

    Attributes:
        id: Unique identifier from OSM or synthetic generator.
        name: Station name or operator location description.
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        operator: Charging network operator (e.g. 'Tata Power', 'Jio-bp', 'Static').
        max_kw: Peak DC charging power in kW.
        connector_types: List of available connector standards (e.g. ['CCS2']).
        reliability: Estimated reliability/uptime in [0, 1] (EXPLICITLY SIMULATED).
        is_reliability_simulated: Always True to prevent silent data invention.
        amenities: Dictionary mapping amenity category to count within ~200m.
        amenity_score: Normalized amenity comfort score in [0.0, 1.0].
        power_assumed: Whether power was assumed due to missing data in source.
        connector_assumed: Whether connector was assumed due to missing data in source.
    """

    id: str
    name: str
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    operator: str = "Unknown Operator"
    max_kw: float = Field(50.0, gt=0.0, description="Maximum DC charging power in kW")
    connector_types: list[str] = Field(
        default_factory=lambda: ["CCS2"], description="Connector standards available"
    )
    reliability: float = Field(
        0.85,
        ge=0.0,
        le=1.0,
        description="[SIMULATED] Estimated operational reliability in [0, 1]",
    )
    is_reliability_simulated: bool = Field(
        True,
        description="Flag explicitly verifying that station reliability is simulated",
    )
    amenities: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of amenities within ~200m buffer: cafe, restaurant, toilets, fuel",
    )
    amenity_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate amenity comfort score in range [0, 1]",
    )
    power_assumed: bool = Field(
        False, description="Whether max_kw was imputed via fallback policy"
    )
    connector_assumed: bool = Field(
        False, description="Whether connector_types were imputed via fallback policy"
    )
    source: str = Field(
        "osm", description="Provenance source of charger data: 'osm', 'ocm', or 'synthetic'"
    )
    road_node_id: int | None = Field(
        None, description="Physical road network attachment node ID"
    )
    detour_distance_m: float = Field(
        0.0, description="Round-trip spur detour distance in meters"
    )
    detour_time_s: float = Field(
        0.0, description="Round-trip spur detour duration in seconds"
    )
    detour_energy_kwh: float = Field(
        0.0, description="Round-trip spur detour energy in kWh"
    )
    source_url: str | None = Field(
        None, description="Verification source URL for hand-verified chargers"
    )
    checked_on: str | None = Field(
        None, description="Date or timestamp when charger data was verified"
    )


class RoadNode(BaseModel):
    """Vertex in the physical road network.

    Attributes:
        id: Integer node identifier.
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        elevation_m: Smoothed elevation in meters above sea level.
    """

    id: int
    lat: float
    lon: float
    elevation_m: float = 0.0


class RoadEdge(BaseModel):
    """Directed edge in the physical road network.

    Attributes:
        u: Tail node ID.
        v: Head node ID.
        length_m: Traversal length in meters.
        time_s: Traversal time in seconds (based on speed limit or traffic).
        elevation_gain_m: Altitude change h(v) - h(u) in meters.
        energy_kwh: Mechanical energy consumed (can be negative due to regen!).
    """

    u: int
    v: int
    length_m: float = Field(..., ge=0.0)
    time_s: float = Field(..., gt=0.0)
    elevation_gain_m: float = 0.0
    energy_kwh: float = 0.0


class ReducedEdge(BaseModel):
    """High-level transition between candidate stops (source, chargers, destination).

    Attributes:
        u: Origin station ID or 'source'.
        v: Destination station ID or 'dest'.
        path_type: Routing objective used ('fastest' via Dijkstra or 'eco' via Bellman-Ford).
        time_s: Driving duration in seconds.
        net_energy_kwh: Net energy consumed along path (may be negative).
        peak_need_kwh: Maximum cumulative energy deficit at any intermediate prefix.
        road_edge_ids: Sequence of physical road edges (u_i, v_i) traversed.
        arrival_soc_table: Pre-tabulated arrival SoC for discrete departure levels 0..K.
            None indicates that the departure level is infeasible (drops below reserve).
        geometry: Sequence of (lat, lon) coordinates along the physical route.
    """

    u: str
    v: str
    path_type: str = "fastest"
    time_s: float = Field(..., ge=0.0)
    net_energy_kwh: float
    peak_need_kwh: float
    road_edge_ids: list[tuple[int, int]] = Field(default_factory=list)
    arrival_soc_table: list[float | None] = Field(default_factory=list)
    geometry: list[tuple[float, float]] = Field(default_factory=list)


class Trip(BaseModel):
    """EV Trip planning query definition.

    Attributes:
        snapshot_id: Identifier of the pre-ingested corridor snapshot.
        source_id: Node ID for journey start (default 'source').
        destination_id: Node ID for journey destination (default 'dest').
        start_soc: Initial battery SoC as fraction of usable capacity in [0, 1].
        reserve_soc: Minimum allowable safety reserve SoC in [0, 1].
        stop_threshold_soc: Arrival SoC threshold above which a premature-stop penalty applies.
        gamma: Discomfort-minutes penalty per unit SoC for charging with arrival SoC > stop_threshold.
        comfort_weight_lambda: Trade-off parameter in scalar cost J = time_min + lambda * discomfort_min.
        K: Number of discrete battery SoC intervals (e.g. 100 for 1% increments).
    """

    snapshot_id: str
    source_id: str = "source"
    destination_id: str = "dest"
    start_soc: float = Field(1.0, ge=0.0, le=1.0, description="Initial battery SoC in [0, 1]")
    reserve_soc: float = Field(
        0.10, ge=0.0, le=0.5, description="Safety reserve battery SoC in [0, 1]"
    )
    stop_threshold_soc: float = Field(
        0.35, ge=0.0, le=1.0, description="Max preferred arrival SoC to trigger a charge stop (~0.35)"
    )
    gamma: float = Field(
        80.0,
        ge=0.0,
        description="Soft premature stop penalty factor in discomfort-minutes per unit SoC above stop_threshold_soc (gamma=80.0 corresponds to an 8-minute discomfort penalty for stopping prematurely at 45% SoC instead of 35%)",
    )
    comfort_weight_lambda: float = Field(
        1.0, ge=0.0, description="Weight lambda in objective J = time_min + lambda * discomfort_min"
    )
    K: int = Field(100, ge=5, le=500, description="Battery SoC discretization resolution")

    @model_validator(mode="after")
    def validate_soc_bounds(self) -> Trip:
        if self.start_soc < self.reserve_soc:
            raise ValueError(
                f"start_soc ({self.start_soc}) cannot be lower than reserve_soc ({self.reserve_soc})"
            )
        if self.stop_threshold_soc < self.reserve_soc:
            raise ValueError(
                f"stop_threshold_soc ({self.stop_threshold_soc}) cannot be lower than reserve_soc ({self.reserve_soc})"
            )
        return self


class ChargingStop(BaseModel):
    """Realized charging stop in a planned itinerary.

    Attributes:
        station_id: Station identifier.
        station_name: Station human-readable name.
        operator: Network operator.
        lat: Station latitude.
        lon: Station longitude.
        arrival_soc: Battery SoC upon arrival as fraction of usable capacity.
        departure_soc: Battery SoC upon departure as fraction of usable capacity.
        charge_time_min: Exact duration spent charging in minutes.
        dwell_time_min: Total dwell duration at station (equals charge_time_min).
        discomfort_min: Computed discomfort penalty in equivalent minutes.
        amenities: Dictionary of amenity counts.
        amenity_score: Amenity score in [0, 1].
        reliability: Estimated station reliability.
        is_reliability_simulated: Always True.
        max_kw: Station charging power rating.
    """

    station_id: str
    station_name: str
    operator: str
    lat: float
    lon: float
    arrival_soc: float = Field(..., ge=0.0, le=1.0)
    departure_soc: float = Field(..., ge=0.0, le=1.0)
    charge_time_min: float = Field(..., ge=0.0)
    dwell_time_min: float = Field(..., ge=0.0)
    discomfort_min: float = Field(..., ge=0.0)
    amenities: dict[str, int] = Field(default_factory=dict)
    amenity_score: float = Field(0.0, ge=0.0, le=1.0)
    reliability: float = Field(0.85, ge=0.0, le=1.0)
    is_reliability_simulated: bool = True
    max_kw: float = 50.0


class RoutePoint(BaseModel):
    """Point along the continuous journey trajectory for UI plotting.

    Attributes:
        distance_km: Cumulative distance traversed from source in km.
        elevation_m: Elevation at this point in meters.
        soc: Battery SoC fraction at this point.
        lat: Latitude coordinate.
        lon: Longitude coordinate.
    """

    distance_km: float
    elevation_m: float
    soc: float
    lat: float
    lon: float


class ParetoPoint(BaseModel):
    """A supported Pareto point on the Time vs Comfort frontier.

    Attributes:
        lambda_val: Sensitivity parameter lambda yielding this trade-off point.
        total_time_min: Total itinerary time in minutes.
        total_discomfort_min: Total accumulated discomfort in minutes.
        cost_J: Scalarized objective J = total_time_min + lambda * total_discomfort_min.
        stops_count: Number of charging stops.
        stop_station_ids: IDs of the stations selected for charging.
    """

    lambda_val: float
    total_time_min: float
    total_discomfort_min: float
    cost_J: float
    stops_count: int
    stop_station_ids: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Complete planned EV itinerary result.

    Attributes:
        trip: Original trip parameters.
        car: Vehicle profile used for physical simulation.
        feasible: Whether the trip is physically and mathematically possible.
        infeasibility_reason: Explicit diagnostic message if trip is infeasible.
        total_time_min: Total travel time (driving + charging) in minutes.
        driving_time_min: Total driving time in minutes.
        charging_time_min: Total charging duration in minutes.
        total_discomfort_min: Total discomfort in minutes.
        cost_J: Scalar cost J = total_time_min + lambda * total_discomfort_min.
        stops: Ordered list of chosen charging stops.
        arrival_soc_dest: Battery SoC upon arrival at final destination.
        route_soc_profile: Continuous distance-elevation-SoC trajectory.
        pareto_frontier: Set of supported Pareto points computed via lambda-sweep.
    """

    trip: Trip
    car: Car
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


class CorridorSnapshot(BaseModel):
    """Self-contained offline snapshot of a geographical corridor.

    The routing planner reads exclusively from snapshots, maintaining
    pure algorithmic decoupling from live network APIs.
    """

    id: str
    source_name: str
    destination_name: str
    created_at: str
    nodes: dict[int, RoadNode]
    edges: list[RoadEdge]
    stations: list[Station]
    source_node_id: int | None = Field(None, description="Starting road network node ID")
    destination_node_id: int | None = Field(None, description="Destination road network node ID")
    metadata: dict[str, Any] = Field(default_factory=dict)
