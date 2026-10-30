"""CLI Pipeline to construct corridor snapshots from geocoding, routing, Overpass, and elevation.

Usage:
    python -m ingest.build_snapshot --from "Mumbai" --to "Pune"
    python -m ingest.build_snapshot --from "Mumbai" --to "Pune" --use-synthetic
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from core.energy import edge_energy_kwh
from core.models import PRESET_CARS, CorridorSnapshot, RoadEdge, RoadNode
from ingest.amenities import populate_station_amenities
from ingest.elevation import sample_elevations, smooth_elevation_profile
from ingest.geocode import geocode
from ingest.route import OSRMClient, haversine_distance_m
from ingest.synthetic import generate_synthetic_corridor


def build_corridor_from_coords(
    origin_lat: float,
    origin_lon: float,
    origin_label: str,
    dest_lat: float,
    dest_lon: float,
    dest_label: str,
    use_synthetic: bool = False,
    progress_callback: Any = None,
    allow_network: bool = True,
    output_dir: Path | None = None,
    buffer_km: float = 8.0,
    force_refresh: bool = False,
) -> CorridorSnapshot:
    """Build a complete CorridorSnapshot for coordinate waypoints with progress reporting.

    Pipeline stages:
        (a) OSRM driving route with full geometry & alternatives
        (b) Corridor stations (OCM & Overpass, deduped <=100m, provenance labeled)
        (c) OpenTopoData elevation profile (sampled & smoothed; elevation_available flag)
        (d) Station amenities (toilets, cafe, food)
        (e) Assembly of road nodes & edges with real geometry
        (f) Save snapshot and cache by rounded coordinates

    Complexity:
        O(|V_road| + |Stations|)
    """
    clean_src = origin_label.strip() or f"{origin_lat:.2f},{origin_lon:.2f}"
    clean_dst = dest_label.strip() or f"{dest_lat:.2f},{dest_lon:.2f}"
    coord_key = f"corridor_{round(origin_lat, 3)}_{round(origin_lon, 3)}_{round(dest_lat, 3)}_{round(dest_lon, 3)}"
    snapshots_dir = output_dir or Path("data/snapshots")

    # Fast-path 0: Check disk cache only if not forcing fresh live build
    if not force_refresh:
        if progress_callback:
            progress_callback("Checking cached corridor...", 5)

        cached_file = snapshots_dir / f"{coord_key}.json"
        if cached_file.exists():
            try:
                with open(cached_file, "r", encoding="utf-8") as f:
                    snap_data = json.load(f)
                if progress_callback:
                    progress_callback("Found existing corridor in cache", 100)
                if "metadata" in snap_data:
                    snap_data["metadata"]["is_live_build"] = False
                return CorridorSnapshot(**snap_data)
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                snap_data = None

    if use_synthetic:
        if progress_callback:
            progress_callback("Generating synthetic corridor...", 50)
        snapshot = generate_synthetic_corridor(
            source_name=clean_src,
            destination_name=clean_dst,
        )
        out_file = snapshots_dir / f"{coord_key}.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(snapshot.model_dump(), f, indent=2)
        if progress_callback:
            progress_callback("Completed synthetic corridor", 100)
        return snapshot

    # Stage (a): Query OSRM driving route
    if progress_callback:
        progress_callback("Fetching OSRM road geometry...", 20)

    osrm = OSRMClient()
    route_data = osrm.get_route((origin_lat, origin_lon), (dest_lat, dest_lon), alternatives=True, allow_network=allow_network)
    coords = route_data["coordinates"]
    if len(coords) < 2:
        raise ValueError("OSRM did not return valid driving route coordinates.")

    # Stage (b): Query corridor stations from live providers
    if progress_callback:
        progress_callback("Querying live station providers (Google Places, OCM, Verified, OSM)...", 45)

    buffer_deg = buffer_km / 111.0
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    bbox = (
        min(lats) - buffer_deg,
        min(lons) - buffer_deg,
        max(lats) + buffer_deg,
        max(lons) + buffer_deg,
    )

    from ingest.station_providers import query_all_providers

    stations, provider_stats = query_all_providers(
        route_coords=coords,
        bbox=bbox,
        allow_network=allow_network,
    )

    # Stage (c): Sample & smooth elevations. Keep long corridors to about 900
    # samples so they do not require dozens of sequential calls to the public API.
    if progress_callback:
        progress_callback("Sampling and smoothing route elevations...", 70)

    elevation_available = True
    try:
        sample_spacing_m = max(250.0, route_data["distance_m"] / 900.0)
        subsampled_indices = [0]
        cum_d = 0.0
        for i in range(len(coords) - 1):
            cum_d += haversine_distance_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
            if cum_d >= sample_spacing_m:
                subsampled_indices.append(i + 1)
                cum_d = 0.0
        if subsampled_indices[-1] != len(coords) - 1:
            subsampled_indices.append(len(coords) - 1)

        subsampled_coords = [coords[idx] for idx in subsampled_indices]

        def report_elevation_progress(completed: int, total: int) -> None:
            if progress_callback:
                percent = 70 + int(15 * completed / max(1, total))
                progress_callback(
                    f"Sampling route elevations (batch {completed} of {total})...",
                    percent,
                )

        sub_elevs = sample_elevations(
            subsampled_coords,
            allow_network=allow_network,
            progress_callback=report_elevation_progress,
        )
        smoothed_sub, ascent_before, ascent_after = smooth_elevation_profile(sub_elevs, window_size=3)

        if all(e == 0.0 for e in sub_elevs):
            elevation_available = False

        smoothed_elevs = [0.0] * len(coords)
        for seg_i in range(len(subsampled_indices) - 1):
            idx_a = subsampled_indices[seg_i]
            idx_b = subsampled_indices[seg_i + 1]
            h_a = smoothed_sub[seg_i]
            h_b = smoothed_sub[seg_i + 1]
            span = max(1, idx_b - idx_a)
            for j in range(idx_a, idx_b):
                frac = (j - idx_a) / span
                smoothed_elevs[j] = round(h_a + frac * (h_b - h_a), 2)
        smoothed_elevs[-1] = smoothed_sub[-1]
    except (requests.RequestException, OSError, ValueError, KeyError):
        smoothed_elevs = [0.0] * len(coords)
        ascent_before, ascent_after = 0.0, 0.0
        elevation_available = False

    # Stage (d): Populate station amenities
    if progress_callback:
        progress_callback("Populating station amenities...", 85)

    for st in stations:
        populate_station_amenities(st, allow_network=allow_network)

    # Stage (e): Build road network nodes & edges
    if progress_callback:
        progress_callback("Building road network graph and snapshot...", 95)

    nodes: dict[int, RoadNode] = {}
    for i, (lat, lon) in enumerate(coords):
        nodes[i] = RoadNode(id=i, lat=lat, lon=lon, elevation_m=smoothed_elevs[i])

    edges: list[RoadEdge] = []
    eval_car = PRESET_CARS["tata_nexon_ev_lr"]
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

    # Precompute cumulative distance along road nodes
    cum_dist_km: dict[int, float] = {0: 0.0}
    c_km = 0.0
    for edge in edges:
        c_km += edge.length_m / 1000.0
        cum_dist_km[edge.v] = c_km

    # Attach stations to nearest road nodes and calculate detours & route distance
    for st in stations:
        min_dist = float("inf")
        best_nid = 0
        for nid, node in nodes.items():
            dist = haversine_distance_m(st.lat, st.lon, node.lat, node.lon)
            if dist < min_dist:
                min_dist = dist
                best_nid = nid
        st.road_node_id = best_nid
        st.route_distance_km = round(cum_dist_km.get(best_nid, 0.0), 3)
        st.detour_distance_m = round(2.0 * min_dist, 1)
        st.detour_time_s = round(st.detour_distance_m / 11.1, 1)
        st.detour_energy_kwh = round(edge_energy_kwh(eval_car, st.detour_distance_m, st.detour_time_s, 0.0), 4)

    # Stage (f): Finalize metadata and cache
    from ingest.stations import compute_data_provenance

    is_synthetic = bool(use_synthetic) or any(getattr(st, "source", "") == "synthetic" for st in stations)
    provenance = compute_data_provenance(stations, {"synthetic": is_synthetic})

    metadata = {
        "synthetic": is_synthetic,
        "energy_vehicle_id": eval_car.id,
        "data_provenance": provenance,
        "is_live_build": not is_synthetic,
        "built_at": datetime.now(UTC).isoformat(),
        "elevation_available": elevation_available,
        "ascent_before_smoothing_m": ascent_before,
        "ascent_after_smoothing_m": ascent_after,
        "total_distance_km": route_data["distance_m"] / 1000.0,
        "num_road_segments": len(edges),
        "num_stations": len(stations),
        "provider_stats": provider_stats,
    }

    snapshot = CorridorSnapshot(
        id=coord_key,
        source_name=clean_src,
        destination_name=clean_dst,
        created_at="2026-10-18T00:00:00Z",
        nodes=nodes,
        edges=edges,
        stations=stations,
        source_node_id=0,
        destination_node_id=len(nodes) - 1,
        metadata=metadata,
    )

    out_file = snapshots_dir / f"{coord_key}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(snapshot.model_dump(), f, indent=2)

    if progress_callback:
        progress_callback("Corridor snapshot ready", 100)

    return snapshot


def build_corridor_snapshot(
    source_name: str,
    destination_name: str,
    use_synthetic: bool = False,
    output_path: Path | None = None,
    buffer_km: float = 5.0,
    allow_network: bool = True,
) -> CorridorSnapshot:
    """Build a complete CorridorSnapshot for any source and destination by geocoding."""
    s_lat, s_lon, s_disp = geocode(source_name, allow_network=allow_network)
    d_lat, d_lon, d_disp = geocode(destination_name, allow_network=allow_network)
    out_dir = output_path.parent if output_path else None
    return build_corridor_from_coords(
        origin_lat=s_lat,
        origin_lon=s_lon,
        origin_label=s_disp,
        dest_lat=d_lat,
        dest_lon=d_lon,
        dest_label=d_disp,
        use_synthetic=use_synthetic,
        allow_network=allow_network,
        output_dir=out_dir,
        buffer_km=buffer_km,
    )



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
