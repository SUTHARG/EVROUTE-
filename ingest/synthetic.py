"""High-fidelity synthetic corridor and random geometric graph generator for offline testing."""

from __future__ import annotations

import math
import random
from typing import Any

from core.energy import edge_energy_kwh
from core.models import PRESET_CARS, Car, CorridorSnapshot, RoadEdge, RoadNode, Station
from ingest.elevation import smooth_elevation_profile


def generate_synthetic_corridor(
    source_name: str = "Mumbai",
    destination_name: str = "Pune",
    source_coord: tuple[float, float] = (18.9388, 72.8354),
    destination_coord: tuple[float, float] = (18.5204, 73.8567),
    total_distance_km: float = 150.0,
    num_road_segments: int = 50,
    num_stations: int = 15,
    seed: int = 42,
    car: Car | None = None,
) -> CorridorSnapshot:
    """Generate a realistic synthetic highway corridor with mountain ghats and charging stations.

    Runs completely offline with zero network calls. Modeled on terrain transitions
    such as the Mumbai-Pune Expressway (coastal plain -> Western Ghats climb to ~650m
    -> Deccan plateau descent to ~560m).

    Complexity:
        Time: O(num_road_segments + num_stations)
        Space: O(num_road_segments + num_stations)

    Args:
        source_name: Starting city label.
        destination_name: Destination city label.
        source_coord: (lat, lon) start point.
        destination_coord: (lat, lon) end point.
        total_distance_km: Length of corridor in kilometers.
        num_road_segments: Granularity of road network vertices.
        num_stations: Number of candidate charging stations along the route.
        seed: Deterministic PRNG seed.
        car: Reference vehicle for computing nominal edge energy.

    Returns:
        Fully populated CorridorSnapshot ready for the planner.
    """
    rng = random.Random(seed)
    eval_car = car or PRESET_CARS["tata_nexon_ev_lr"]

    s_lat, s_lon = source_coord
    d_lat, d_lon = destination_coord

    # 1. Generate road nodes along corridor with realistic elevation profile
    raw_elevations: list[float] = []
    nodes: dict[int, RoadNode] = {}
    node_coords: list[tuple[float, float]] = []

    for i in range(num_road_segments + 1):
        frac = i / num_road_segments
        # Linear interpolation with slight highway curvature
        curvature = 0.04 * math.sin(frac * math.pi)
        lat = s_lat + frac * (d_lat - s_lat) + curvature
        lon = s_lon + frac * (d_lon - s_lon) - curvature

        # Elevation profile: Coastal (15m) -> Ghats climb (650m around 55-65% dist) -> Pune (560m)
        if frac < 0.35:
            # Coastal plain
            elev = 15.0 + 40.0 * frac + rng.uniform(-3.0, 3.0)
        elif frac < 0.65:
            # Steep climb up the Western Ghats (Khandala / Lonavala)
            ghat_progress = (frac - 0.35) / 0.30
            elev = 30.0 + 620.0 * (1.0 / (1.0 + math.exp(-10.0 * (ghat_progress - 0.5)))) + rng.uniform(-5.0, 5.0)
        else:
            # Plateau with rolling hills descending slightly to Pune
            plateau_progress = (frac - 0.65) / 0.35
            elev = 650.0 - 90.0 * plateau_progress + rng.uniform(-4.0, 4.0)

        raw_elevations.append(elev)
        node_coords.append((lat, lon))

    # Apply 3-point moving average smoothing
    smoothed_elev, ascent_before, ascent_after = smooth_elevation_profile(raw_elevations, window_size=3)

    for i, (lat, lon) in enumerate(node_coords):
        nodes[i] = RoadNode(id=i, lat=round(lat, 5), lon=round(lon, 5), elevation_m=smoothed_elev[i])

    # 2. Generate road edges with derived delta_h and physical energy
    edges: list[RoadEdge] = []
    seg_length_m = (total_distance_km * 1000.0) / num_road_segments

    for i in range(num_road_segments):
        u, v = i, i + 1
        delta_h = nodes[v].elevation_m - nodes[u].elevation_m

        # Highway speeds: 70-90 km/h on flats, 50-60 km/h on steep ghat climbs
        base_speed_kmh = 80.0 if abs(delta_h) < 15.0 else (55.0 if delta_h > 0 else 65.0)
        time_s = seg_length_m / (base_speed_kmh / 3.6)

        e_kwh = edge_energy_kwh(
            car=eval_car,
            length_m=seg_length_m,
            time_s=time_s,
            elevation_gain_m=delta_h,
        )

        edge = RoadEdge(
            u=u,
            v=v,
            length_m=round(seg_length_m, 1),
            time_s=round(time_s, 1),
            elevation_gain_m=round(delta_h, 2),
            energy_kwh=round(e_kwh, 4),
        )
        edges.append(edge)

    # 3. Generate charging stations along corridor
    operators = [
        "Tata Power",
        "Jio-bp pulse",
        "Statiq",
        "Zeon Charging",
        "ChargeZone",
        "Fortum Charge & Drive",
    ]
    power_ratings = [30.0, 50.0, 60.0, 120.0, 150.0]

    stations: list[Station] = []
    # Distribute stations along route
    step_frac = 1.0 / (num_stations + 1)

    for s_idx in range(num_stations):
        target_frac = (s_idx + 1) * step_frac + rng.uniform(-0.015, 0.015)
        target_frac = max(0.05, min(0.95, target_frac))

        node_idx = int(target_frac * num_road_segments)
        base_node = nodes[node_idx]

        # Station placed with a small detour (0.2 to 1.5 km off main highway)
        detour_dist_km = rng.uniform(0.1, 1.2)
        detour_angle = rng.uniform(0, 2 * math.pi)
        detour_lat = base_node.lat + (detour_dist_km / 111.0) * math.sin(detour_angle)
        detour_lon = base_node.lon + (detour_dist_km / 111.0) * math.cos(detour_angle)

        op = rng.choice(operators)
        kw = rng.choice(power_ratings)

        # Realistic amenity distributions (restaurants, cafes, restrooms near highway food malls)
        has_food_mall = rng.random() > 0.35
        amenities: dict[str, int] = {}
        if has_food_mall:
            amenities["restaurant"] = rng.randint(1, 3)
            amenities["cafe"] = rng.randint(0, 2)
            amenities["toilets"] = rng.randint(1, 2)
            amenities["fuel"] = 1
        else:
            amenities["restaurant"] = rng.choice([0, 1])
            amenities["toilets"] = 1
            amenities["fuel"] = 1

        # Calculate amenity score
        from ingest.amenities import compute_amenity_score
        amenity_sc = compute_amenity_score(amenities)

        # Seeded simulated reliability score
        from ingest.stations import simulate_station_reliability
        rel = simulate_station_reliability(op, f"synth_{s_idx}_{op}")

        station = Station(
            id=f"synth_stat_{s_idx + 1:02d}",
            name=f"{op} - Highway Stop {s_idx + 1}",
            lat=round(detour_lat, 5),
            lon=round(detour_lon, 5),
            operator=op,
            max_kw=kw,
            connector_types=["CCS2"],
            reliability=rel,
            is_reliability_simulated=True,
            amenities=amenities,
            amenity_score=amenity_sc,
        )
        stations.append(station)

    metadata: dict[str, Any] = {
        "synthetic": True,
        "ascent_before_smoothing_m": ascent_before,
        "ascent_after_smoothing_m": ascent_after,
        "total_distance_km": total_distance_km,
        "num_road_segments": num_road_segments,
        "num_stations": len(stations),
        "kept_stations": len(stations),
        "dropped_connector": 0,
        "dropped_power": 0,
        "assumed_defaults": 0,
    }

    return CorridorSnapshot(
        id=f"synthetic_{source_name.lower()}_{destination_name.lower()}_v1",
        source_name=source_name,
        destination_name=destination_name,
        created_at="2026-10-17T20:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=stations,
        metadata=metadata,
    )


def generate_random_geometric_graph(
    num_nodes: int = 50,
    edge_probability: float = 0.15,
    seed: int = 42,
    allow_negative_edges: bool = True,
) -> tuple[dict[int, RoadNode], list[RoadEdge]]:
    """Generate a random geometric graph with negative edges (downhill regen) for algorithm testing.

    Complexity:
        Time: O(num_nodes^2)
        Space: O(num_nodes + num_edges)

    Args:
        num_nodes: Number of vertices.
        edge_probability: Connection probability between node pairs.
        seed: Random seed.
        allow_negative_edges: Include negative edge weights.

    Returns:
        Tuple of (nodes_dict, list_of_edges).
    """
    rng = random.Random(seed)
    nodes: dict[int, RoadNode] = {}
    car = PRESET_CARS["tata_nexon_ev_lr"]

    for i in range(num_nodes):
        lat = 18.0 + rng.uniform(0.0, 1.0)
        lon = 72.0 + rng.uniform(0.0, 1.0)
        elev = rng.uniform(50.0, 500.0)
        nodes[i] = RoadNode(id=i, lat=lat, lon=lon, elevation_m=elev)

    edges: list[RoadEdge] = []
    for u in range(num_nodes):
        for v in range(num_nodes):
            if u != v and rng.random() < edge_probability:
                dist_m = rng.uniform(2000.0, 15000.0)
                time_s = dist_m / rng.uniform(15.0, 25.0)
                delta_h = nodes[v].elevation_m - nodes[u].elevation_m

                e_kwh = edge_energy_kwh(
                    car=car,
                    length_m=dist_m,
                    time_s=time_s,
                    elevation_gain_m=delta_h,
                )
                if not allow_negative_edges and e_kwh < 0.0:
                    e_kwh = 0.1

                edges.append(
                    RoadEdge(
                        u=u,
                        v=v,
                        length_m=round(dist_m, 1),
                        time_s=round(time_s, 1),
                        elevation_gain_m=round(delta_h, 2),
                        energy_kwh=round(e_kwh, 4),
                    )
                )

    return nodes, edges
