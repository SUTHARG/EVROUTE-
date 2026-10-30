"""Unit tests for Phase 5 (Greedy Station Filter) and Phase 6 (Reduced Charger Graph)."""

from core.charger_graph import build_reduced_charger_graph
from core.filters import compute_station_score, filter_stations_greedy
from core.models import PRESET_CARS, Car, Station
from core.road_graph import RoadGraph
from ingest.synthetic import generate_synthetic_corridor


def test_station_scoring_and_connector_filtering():
    """Verify station scoring formula and connector standard compatibility filtering."""
    st_ccs2 = Station(
        id="st_1",
        name="Tata Power Fast CCS2",
        lat=19.0,
        lon=73.0,
        operator="Tata Power",
        max_kw=120.0,
        connector_types=["CCS2"],
        reliability=0.92,
        amenities={"restaurant": 2, "toilets": 1},
        amenity_score=0.70,
        source="synthetic",
    )
    st_chademo = Station(
        id="st_2",
        name="Old CHAdeMO Hub",
        lat=19.1,
        lon=73.1,
        operator="Legacy",
        max_kw=50.0,
        connector_types=["CHAdeMO"],
        reliability=0.80,
        amenities={},
        amenity_score=0.10,
        source="synthetic",
    )

    score_1 = compute_station_score(st_ccs2, detour_km=0.5)
    score_2 = compute_station_score(st_chademo, detour_km=0.5)
    assert score_1 > score_2
    assert score_1 > 0.50

    car = PRESET_CARS["tata_nexon_ev_lr"]
    source = (18.9388, 72.8354)
    dest = (18.5204, 73.8567)

    kept, dropped, audit = filter_stations_greedy(
        stations=[st_ccs2, st_chademo],
        car=car,
        source_coord=source,
        destination_coord=dest,
        target_connector="CCS2",
    )

    # CHAdeMO must be in dropped, CCS2 in kept
    assert any(s.id == "st_2" for s in dropped)
    assert any(s.id == "st_1" for s in kept)
    assert audit["kept_count"] >= 1


def test_greedy_loop_reinstatement_bridges_gaps():
    """Verify loop reinstatement restores dropped candidates to bridge gaps exceeding vehicle range."""
    source = (18.9388, 72.8354)  # Mumbai
    dest = (18.5204, 73.8567)    # Pune (~150 km)

    # Place stations: St1 at 40 km, St2 at 80 km, St3 at 120 km
    # Give St2 a low score so initial threshold drops it
    st1 = Station(
        id="st_panvel",
        name="Panvel High Quality Hub",
        lat=18.80,
        lon=73.10,
        operator="Zeon",
        max_kw=150.0,
        connector_types=["CCS2"],
        reliability=0.95,
        amenities={"restaurant": 2, "cafe": 1, "toilets": 1},
        amenity_score=0.90,
        source="synthetic",
    )
    st2 = Station(
        id="st_lonavala_low_score",
        name="Lonavala Low Score Charger",
        lat=18.70,
        lon=73.40,
        operator="Local",
        max_kw=30.0,
        connector_types=["CCS2"],
        reliability=0.40,
        amenities={},
        amenity_score=0.0,  # low score will be dropped initially
        source="synthetic",
    )
    st3 = Station(
        id="st_talegaon",
        name="Talegaon Superhub",
        lat=18.60,
        lon=73.65,
        operator="Tata Power",
        max_kw=120.0,
        connector_types=["CCS2"],
        reliability=0.92,
        amenities={"restaurant": 1, "toilets": 1},
        amenity_score=0.70,
        source="synthetic",
    )

    # Constrain car to a small range (e.g. 50 km) so gap between St1 (40km) and St3 (120km) is 80km > 50km
    limited_car = Car(
        id="small_ev",
        name="Small City EV",
        battery_kwh=10.0,
        usable_fraction=1.0,
        consumption_kwh_per_km=0.15,  # Range = 10 / 0.15 = 66 km
        mass_kg=1200.0,
        drag_coefficient=0.32,
        frontal_area_m2=2.2,
        max_dc_kw=30.0,
        regen_efficiency=0.75,
    )

    kept, dropped, audit = filter_stations_greedy(
        stations=[st1, st2, st3],
        car=limited_car,
        source_coord=source,
        destination_coord=dest,
        score_threshold=0.50,  # st2 score is ~0.20, below threshold
        reserve_soc=0.10,
    )

    # Because gap between St1 and St3 exceeds vehicle range, loop reinstatement MUST re-add st2!
    assert any(s.id == "st_lonavala_low_score" for s in kept)
    assert audit["reinstated_count"] >= 1
    assert isinstance(dropped, list)


def test_first_gap_start_soc_sensitivity():
    """Verify low start_soc shrinks first gap allowance and reinstates early chargers."""
    source = (18.9388, 72.8354)
    dest = (18.5204, 73.8567)

    st_early = Station(
        id="st_early",
        name="Early Low Score Charger (15 km)",
        lat=18.90,
        lon=72.95,
        operator="Local",
        max_kw=25.0,
        connector_types=["CCS2"],
        reliability=0.35,
        amenities={},
        amenity_score=0.0,
        source="synthetic",
    )
    st_mid = Station(
        id="st_mid",
        name="Mid High Quality Charger (70 km)",
        lat=18.72,
        lon=73.35,
        operator="Tata Power",
        max_kw=100.0,
        connector_types=["CCS2"],
        reliability=0.95,
        amenities={"restaurant": 2, "toilets": 1},
        amenity_score=0.85,
        source="synthetic",
    )

    car = PRESET_CARS["tata_nexon_ev_lr"]

    # Case A: Starting with 100% SoC -> can reach st_mid directly, st_early dropped
    kept_full, _, _ = filter_stations_greedy(
        stations=[st_early, st_mid],
        car=car,
        source_coord=source,
        destination_coord=dest,
        start_soc=1.0,
        reserve_soc=0.10,
        score_threshold=0.45,
    )
    assert not any(s.id == "st_early" for s in kept_full)

    # Case B: Starting with 15% SoC (near 10% reserve) -> cannot reach 70km! Reinstates st_early!
    kept_low, _, audit_low = filter_stations_greedy(
        stations=[st_early, st_mid],
        car=car,
        source_coord=source,
        destination_coord=dest,
        start_soc=0.16,
        reserve_soc=0.10,
        score_threshold=0.45,
    )
    assert any(s.id == "st_early" for s in kept_low)
    assert audit_low["reinstated_count"] >= 1


def test_reduced_charger_graph_fastest_and_eco_paths():
    """Verify ReducedChargerGraph builds 2-layer topology with fastest and eco candidate edges."""
    snapshot = generate_synthetic_corridor(
        total_distance_km=120.0,
        num_road_segments=30,
        num_stations=5,
        seed=42,
    )
    road_graph = RoadGraph.from_snapshot(snapshot)
    car = PRESET_CARS["tata_nexon_ev_lr"]

    reduced_graph, stats = build_reduced_charger_graph(
        road_graph=road_graph,
        # Provider order is arbitrary; the graph builder must use each station's
        # projected corridor position when deciding which transitions are forward.
        kept_stations=list(reversed(snapshot.stations[:3])),
        source_node_id=0,
        dest_node_id=30,
        car=car,
        K=20,
        reserve_soc=0.10,
    )

    assert stats["total_reduced_edges"] > 0
    assert stats["reduced_nodes_count"] == 5  # source, 3 stations, dest

    corridor_order = sorted(snapshot.stations[:3], key=lambda station: station.route_distance_km)
    first_station_edges = reduced_graph.get_driving_edges(f"{corridor_order[0].id}_dep")
    assert any(edge.v == corridor_order[1].id for edge in first_station_edges)

    # Check outgoing transitions from source_dep
    source_edges = reduced_graph.get_driving_edges("source_dep")
    assert len(source_edges) > 0

    edge = source_edges[0]
    assert edge.time_s > 0.0
    assert len(edge.arrival_soc_table) == 21  # K=20 -> length 21

    # Check 100% clamping and reserve check in arrival table
    # Departure below reserve (0.10 -> idx 0 and 1) must be None
    assert edge.arrival_soc_table[0] is None
    assert edge.arrival_soc_table[1] is None

    # High departure levels must be feasible (float)
    assert edge.arrival_soc_table[20] is not None
    assert 0.10 <= edge.arrival_soc_table[20] <= 1.0


def test_counterexample_greedy_filter_drops_optimal_station():
    """Hand-built counterexample proving that greedy multi-attribute filtering can drop

    the globally optimal station for time-minimizing trips (lambda=0).

    Setup:
    - st_fast: 150 kW DC fast charger, zero amenities (score = 0.565).
    - st_slow_lounge: 25 kW DC charger, luxury amenities (score = 0.688).
    - At score_threshold = 0.60, st_fast is dropped and st_slow_lounge is kept.
    - Since st_slow_lounge bridges the corridor, st_fast is never reinstated.
    - At lambda = 0 (pure time), the optimal plan uses st_fast (charging takes ~8 min).
    - With filtering enabled, the planner is forced to use st_slow_lounge (charging takes ~48 min).
    - Result: Filtered plan is strictly suboptimal (costs ~40 min more).
    """
    from core.models import CorridorSnapshot, RoadEdge, RoadNode, Trip
    from core.planner import EVPlanner

    car = PRESET_CARS["tata_nexon_ev_lr"]  # 40.5 kWh, usable 38.47 kWh

    # Build simple 3-node road corridor: node 0 (0 km) -> node 1 (50 km) -> node 2 (100 km)
    nodes = {
        0: RoadNode(id=0, lat=19.00, lon=73.00, elevation_m=20.0),
        1: RoadNode(id=1, lat=18.75, lon=73.30, elevation_m=20.0),
        2: RoadNode(id=2, lat=18.52, lon=73.85, elevation_m=20.0),
    }
    # 50 km leg at 80 km/h takes 37.5 min = 2250 s, consumes ~7.5 kWh
    edges = [
        RoadEdge(u=0, v=1, length_m=50000.0, time_s=2250.0, energy_kwh=7.5),
        RoadEdge(u=1, v=2, length_m=50000.0, time_s=2250.0, energy_kwh=7.5),
    ]

    st_fast = Station(
        id="st_fast",
        name="Ultra-Fast 150kW Depot",
        lat=18.75,
        lon=73.30,
        road_node_id=1,
        operator="FastPower",
        max_kw=150.0,
        connector_types=["CCS2"],
        reliability=0.90,
        amenity_score=0.0,
        detour_time_s=0.0,
        detour_distance_m=0.0,
        source="synthetic",
    )
    st_slow_lounge = Station(
        id="st_slow_lounge",
        name="Slow 25kW Luxury Lounge",
        lat=18.7501,
        lon=73.3001,
        road_node_id=1,
        operator="LoungeCharge",
        max_kw=25.0,
        connector_types=["CCS2"],
        reliability=0.99,
        amenity_score=1.0,
        detour_time_s=0.0,
        detour_distance_m=0.0,
        source="synthetic",
    )

    snapshot = CorridorSnapshot(
        id="counterexample_corridor",
        name="Filter Counterexample Corridor",
        created_at="2026-10-17T00:00:00Z",
        source_name="Origin",
        destination_name="Destination",
        source_node_id=0,
        destination_node_id=2,
        total_distance_km=100.0,
        nodes=nodes,
        edges=edges,
        stations=[st_fast, st_slow_lounge],
    )

    trip = Trip(
        snapshot_id=snapshot.id,
        start_soc=0.35,  # 13.5 kWh: reaches station at km 50 (needs 7.5 kWh) but cannot reach destination without charging
        reserve_soc=0.10,
        stop_threshold_soc=0.35,
        comfort_weight_lambda=0.0,  # Pure time objective
        K=20,
    )

    planner = EVPlanner()

    # 1. Unfiltered: planner considers both stations and chooses st_fast (150 kW)
    plan_unfiltered = planner.plan(snapshot, car, trip, lambda_val=0.0, enable_filter=False)
    assert plan_unfiltered.feasible is True
    assert len(plan_unfiltered.stops) == 1
    assert plan_unfiltered.stops[0].station_id == "st_fast"

    # 2. Filtered with threshold=0.60: st_fast is dropped, st_slow_lounge is kept
    plan_filtered = planner.plan(
        snapshot,
        car,
        trip,
        lambda_val=0.0,
        enable_filter=True,
        filter_score_threshold=0.60,
    )
    assert plan_filtered.feasible is True
    assert len(plan_filtered.stops) == 1
    assert plan_filtered.stops[0].station_id == "st_slow_lounge"

    # Strict suboptimality gap: unfiltered plan finishes significantly faster!
    cost_gap = plan_filtered.cost_J - plan_unfiltered.cost_J
    assert cost_gap > 5.0  # Slow charger takes significantly longer to charge
    print(f"Counterexample verified: Unfiltered={plan_unfiltered.cost_J:.2f} min vs Filtered={plan_filtered.cost_J:.2f} min (Gap={cost_gap:.2f} min)")

