"""Non-chain corridor generators (Diamond and Ladder topologies) with parallel routing options."""

from __future__ import annotations

from core.models import Car, CorridorSnapshot, RoadEdge, RoadNode, Station


def generate_diamond_corridor(
    car: Car,
    hilly_hill_m: float = 250.0,
    regen_hill_m: float = -120.0,
) -> CorridorSnapshot:
    """Generate a Diamond network topology with two parallel branches:

    Topology:
              [Node 1: Fast-but-Hilly Branch] (Station 1)
             /                               \\
    [Node 0]                                  ===> [Node 3] (Dest)
             \\                               /
              [Node 2: Slow-but-Flat with Regen] (Station 2)

    Branch 1 (Upper: 0 -> 1 -> 3):
        - High speed limit (short driving time: 35 min total).
        - Steep uphill climb (+250m elevation), high mechanical energy consumption (11.5 kWh).
        - Charger 1 attached with spur detour.

    Branch 2 (Lower: 0 -> 2 -> 3):
        - Lower speed limit (longer driving time: 55 min total).
        - Downhill slope with regenerative braking (-120m elevation, negative energy edge).
        - Total energy consumption is minimal / negative (net 1.8 kWh).
        - Charger 2 attached with spur detour.
    """
    nodes = {
        0: RoadNode(id=0, lat=18.90, lon=72.85, elevation_m=10.0),
        1: RoadNode(id=1, lat=18.75, lon=73.30, elevation_m=10.0 + hilly_hill_m),
        2: RoadNode(id=2, lat=18.60, lon=73.30, elevation_m=10.0 + regen_hill_m),
        3: RoadNode(id=3, lat=18.52, lon=73.85, elevation_m=550.0),
    }

    # Branch 1 edges (Fast-but-Hilly)
    # 0 -> 1: 50 km, fast (100 km/h = 1800s), +250m climb -> high energy 7.5 kWh
    # 1 -> 3: 50 km, fast (100 km/h = 1800s), +290m climb -> high energy 7.0 kWh
    e_0_1 = RoadEdge(u=0, v=1, length_m=50000.0, time_s=1800.0, elevation_gain_m=hilly_hill_m, energy_kwh=7.5)
    e_1_3 = RoadEdge(u=1, v=3, length_m=50000.0, time_s=1800.0, elevation_gain_m=550.0 - (10.0 + hilly_hill_m), energy_kwh=7.0)

    # Branch 2 edges (Slow-but-Flat / Regen)
    # 0 -> 2: 60 km, slower (60 km/h = 3600s), downhill -120m -> regen energy -0.5 kWh
    # 2 -> 3: 60 km, slower (60 km/h = 3600s), moderate climb -> energy 3.0 kWh
    e_0_2 = RoadEdge(u=0, v=2, length_m=60000.0, time_s=3600.0, elevation_gain_m=regen_hill_m, energy_kwh=-0.5)
    e_2_3 = RoadEdge(u=2, v=3, length_m=60000.0, time_s=3600.0, elevation_gain_m=550.0 - (10.0 + regen_hill_m), energy_kwh=3.0)

    edges = [e_0_1, e_1_3, e_0_2, e_2_3]

    st1 = Station(
        id="diamond_st_1",
        name="Hilly Crest Supercharger",
        lat=18.751,
        lon=73.301,
        operator="Tata Power",
        max_kw=60.0,
        connector_types=["CCS2"],
        amenity_score=0.80,
        road_node_id=1,
        detour_distance_m=1200.0,
        detour_time_s=120.0,
        detour_energy_kwh=0.20,
        source="synthetic",
    )

    st2 = Station(
        id="diamond_st_2",
        name="Valley Green Eco Charger",
        lat=18.601,
        lon=73.301,
        operator="Zeon",
        max_kw=100.0,
        connector_types=["CCS2"],
        amenity_score=0.90,
        road_node_id=2,
        detour_distance_m=800.0,
        detour_time_s=80.0,
        detour_energy_kwh=0.12,
        source="synthetic",
    )

    return CorridorSnapshot(
        id="diamond_topology_corridor",
        source_name="Diamond Origin",
        destination_name="Diamond Destination",
        created_at="2026-10-17T21:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=[st1, st2],
        source_node_id=0,
        destination_node_id=3,
        metadata={"synthetic": True, "topology": "diamond"},
    )
