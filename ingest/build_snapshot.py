"""CLI Pipeline to construct corridor snapshots from geocoding, routing, Overpass, and elevation.

Usage:
    python -m ingest.build_snapshot --from "Mumbai" --to "Pune"
    python -m ingest.build_snapshot --from "Mumbai" --to "Pune" --use-synthetic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.energy import edge_energy_kwh
from core.models import PRESET_CARS, CorridorSnapshot, RoadEdge, RoadNode
from ingest.amenities import populate_station_amenities
from ingest.elevation import sample_elevations, smooth_elevation_profile
from ingest.geocode import geocode
from ingest.route import OSRMClient
from ingest.stations import StationIngestionPolicy, fetch_overpass_stations
from ingest.synthetic import generate_synthetic_corridor


def build_corridor_snapshot(
    source_name: str,
    destination_name: str,
    use_synthetic: bool = False,
    output_path: Path | None = None,
    buffer_km: float = 5.0,
    allow_network: bool = True,
) -> CorridorSnapshot:
    """Build a complete CorridorSnapshot for any source and destination.

    Complexity:
        O(|V_road| + |Stations|)
    """
    clean_src = source_name.strip()
    clean_dst = destination_name.strip()
    snapshot_id = f"corridor_{clean_src.lower().replace(' ', '_')}_{clean_dst.lower().replace(' ', '_')}"

    if use_synthetic:
        print(f"[*] Generating synthetic corridor snapshot for '{clean_src}' -> '{clean_dst}'...")
        snapshot = generate_synthetic_corridor(
            source_name=clean_src,
            destination_name=clean_dst,
        )
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(snapshot.model_dump(), f, indent=2)
            print(f"[+] Snapshot saved to: {output_path}")
        return snapshot

    print(f"[*] Geocoding '{clean_src}' and '{clean_dst}'...")
    s_lat, s_lon, s_disp = geocode(clean_src, allow_network=allow_network)
    d_lat, d_lon, d_disp = geocode(clean_dst, allow_network=allow_network)
    print(f"    Source: {s_disp} ({s_lat:.4f}, {s_lon:.4f})")
    print(f"    Destination: {d_disp} ({d_lat:.4f}, {d_lon:.4f})")

    # 1. Fetch OSRM route
    print("[*] Querying OSRM driving route...")
    osrm = OSRMClient()
    route_data = osrm.get_route((s_lat, s_lon), (d_lat, d_lon), allow_network=allow_network)
    coords = route_data["coordinates"]
    print(f"    Found route with {len(coords)} points, distance: {route_data['distance_m']/1000.0:.1f} km")

    # 2. Sample and smooth elevations
    print("[*] Sampling route elevation profile...")
    raw_elevs = sample_elevations(coords, allow_network=allow_network)
    smoothed_elevs, ascent_before, ascent_after = smooth_elevation_profile(raw_elevs, window_size=3)
    print(f"    Total ascent: before smoothing = {ascent_before:.1f}m, after smoothing = {ascent_after:.1f}m")

    # 3. Build Road Nodes and Edges
    nodes: dict[int, RoadNode] = {}
    edges: list[RoadEdge] = []
    eval_car = PRESET_CARS["tata_nexon_ev_lr"]

    for i, (lat, lon) in enumerate(coords):
        nodes[i] = RoadNode(id=i, lat=lat, lon=lon, elevation_m=smoothed_elevs[i])

    # Construct sequential edges along highway
    from ingest.route import haversine_distance_m
    total_time_s = route_data["duration_s"]
    total_dist_m = route_data["distance_m"]
    avg_speed_mps = max(5.0, total_dist_m / max(1.0, total_time_s))

    for i in range(len(coords) - 1):
        u, v = i, i + 1
        d_m = haversine_distance_m(nodes[u].lat, nodes[u].lon, nodes[v].lat, nodes[v].lon)
        t_s = max(0.5, d_m / avg_speed_mps)
        dh = nodes[v].elevation_m - nodes[u].elevation_m

        e_kwh = edge_energy_kwh(
            car=eval_car,
            length_m=d_m,
            time_s=t_s,
            elevation_gain_m=dh,
        )
        edges.append(
            RoadEdge(
                u=u,
                v=v,
                length_m=round(d_m, 1),
                time_s=round(t_s, 1),
                elevation_gain_m=round(dh, 2),
                energy_kwh=round(e_kwh, 4),
            )
        )

    # 4. Fetch charging stations along bounding box + corridor buffer
    buffer_deg = buffer_km / 111.0
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    bbox = (
        min(lats) - buffer_deg,
        min(lons) - buffer_deg,
        max(lats) + buffer_deg,
        max(lons) + buffer_deg,
    )

    print("[*] Querying Overpass API for charging stations in corridor bbox...")
    stations, audit = fetch_overpass_stations(
        bbox=bbox,
        policy=StationIngestionPolicy(assume_missing_connector_as_ccs2=True, assume_missing_power_kw=50.0),
        allow_network=allow_network,
    )
    print(f"    Stations audit: {audit}")

    # 5. Populate station amenities
    print("[*] Populating station amenities (cafe, food, toilets)...")
    for st in stations:
        populate_station_amenities(st, allow_network=allow_network)

    metadata = {
        "synthetic": False,
        "ascent_before_smoothing_m": ascent_before,
        "ascent_after_smoothing_m": ascent_after,
        "total_distance_km": route_data["distance_m"] / 1000.0,
        "num_road_segments": len(edges),
        "num_stations": len(stations),
        **audit,
    }

    snapshot = CorridorSnapshot(
        id=snapshot_id,
        source_name=clean_src,
        destination_name=clean_dst,
        created_at="2026-10-17T20:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=stations,
        metadata=metadata,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot.model_dump(), f, indent=2)
        print(f"[+] Snapshot saved to: {output_path}")

    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Route.ev Corridor Snapshot Builder")
    parser.add_argument("--from", dest="source", required=True, help="Origin location query (e.g. 'Mumbai')")
    parser.add_argument("--to", dest="destination", required=True, help="Destination location query (e.g. 'Pune')")
    parser.add_argument("--output", dest="output", default=None, help="Output JSON snapshot file path")
    parser.add_argument("--use-synthetic", action="store_true", help="Force synthetic corridor generation offline")
    parser.add_argument("--buffer-km", type=float, default=5.0, help="Corridor query buffer in km")

    args = parser.parse_args()

    out_file = Path(args.output) if args.output else Path(f"data/snapshots/{args.source.lower()}_{args.destination.lower()}.json")

    try:
        build_corridor_snapshot(
            source_name=args.source,
            destination_name=args.destination,
            use_synthetic=args.use_synthetic,
            output_path=out_file,
            buffer_km=args.buffer_km,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Live build encountered error ({exc}); falling back to synthetic generator...", file=sys.stderr)
        build_corridor_snapshot(
            source_name=args.source,
            destination_name=args.destination,
            use_synthetic=True,
            output_path=out_file,
            buffer_km=args.buffer_km,
        )


if __name__ == "__main__":
    main()
