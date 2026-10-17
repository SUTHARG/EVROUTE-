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
        kept_stations=snapshot.stations[:3],
        source_node_id=0,
        dest_node_id=30,
        car=car,
        K=20,
        reserve_soc=0.10,
    )

    assert stats["total_reduced_edges"] > 0
    assert stats["reduced_nodes_count"] == 5  # source, 3 stations, dest

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
