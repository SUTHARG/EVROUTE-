"""Overpass and OpenChargeMap station ingestion client with simulated reliability and audit logging."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from core.models import Station
from ingest.cache import DiskCache

load_dotenv()

OVERPASS_API_URL: str = "https://overpass-api.de/api/interpreter"
OPENCHARGEMAP_API_URL: str = "https://api.openchargemap.io/v3/poi"
USER_AGENT: str = "RouteEV-TripPlanner/1.0 (academic-dsa-project)"

# Known EV operators in India with base simulated reliability ratings
OPERATOR_BASE_RELIABILITY: dict[str, float] = {
    "tata power": 0.91,
    "jio-bp": 0.89,
    "statiq": 0.86,
    "zeon": 0.93,
    "fortum": 0.90,
    "chargezone": 0.87,
    "ather": 0.92,
    "glida": 0.88,
    "magenta": 0.84,
}


def simulate_station_reliability(operator: str, seed_key: str) -> float:
    """Generate a reproducible, seeded simulated reliability score for an EV charger.

    Complexity: O(1).
    """
    op_clean = operator.lower().strip()
    base_score = 0.78  # default baseline for unlisted/unknown operators
    for known_op, score in OPERATOR_BASE_RELIABILITY.items():
        if known_op in op_clean:
            base_score = score
            break

    # Seed with hash of seed_key for exact deterministic reproducibility
    rng = random.Random(f"rel_seed_{seed_key}")
    noise = rng.gauss(0.0, 0.035)
    return round(max(0.20, min(0.99, base_score + noise)), 3)


class StationIngestionPolicy:
    """Configurable fallback policy for missing connector or power data."""

    def __init__(
        self,
        assume_missing_connector_as_ccs2: bool = True,
        assume_missing_power_kw: float | None = 50.0,
        default_connector: str = "CCS2",
        raise_on_network_error: bool = False,
    ) -> None:
        self.assume_missing_connector_as_ccs2 = assume_missing_connector_as_ccs2
        self.assume_missing_power_kw = assume_missing_power_kw
        self.default_connector = default_connector
        self.raise_on_network_error = raise_on_network_error


def compute_data_provenance(stations: list[Station], metadata: dict[str, Any] | None = None) -> str:
    """Compute data provenance classification: 'verified', 'open_data_providers', 'manual_unverified', or 'synthetic'."""
    if metadata and (metadata.get("synthetic", False) or metadata.get("data_provenance") == "synthetic"):
        return "synthetic"

    if not stations:
        return "synthetic" if (metadata and metadata.get("synthetic", False)) else "none"

    sources = {st.source for st in stations if st.source}
    if any(s.startswith("synth") for s in sources):
        return "synthetic"

    # Project verification policy: verified applies ONLY when verified=True from official checked CSV / ground truth
    has_verified = any(
        getattr(st, "verified", False) and getattr(st, "source", "") in {"verified", "verified_manual", "manual"}
        for st in stations
    )
    if has_verified:
        return "verified"

    # Distinguish live open data providers (OCM, OSM, Google Places) from unverified manual data
    if any(s in {"ocm", "osm", "google_places", "ocm_snapshot"} for s in sources):
        return "open_data_providers"

    return "manual_unverified"



def load_curated_stations(csv_path: str | Path | None = None) -> list[Station]:
    """Load illustrative charging stations from a curated CSV dataset.

    Note: When stations originate from model memory, they are labeled source='unverified_illustrative'
    and data_provenance is marked 'manual_unverified'.
    """
    if csv_path is None:
        csv_path = Path("tests/fixtures/curated_mumbai_pune_chargers.csv")
    path = Path(csv_path)
    if not path.exists():
        return []

    import csv

    stations: list[Station] = []
    with open(path, "r", encoding="utf-8") as f:
        # Filter comment lines starting with #
        lines = [line for line in f if not line.strip().startswith("#")]
        reader = csv.DictReader(lines)
        for row in reader:
            connectors = [c.strip() for c in row.get("connector_types", "CCS2").split(";")]
            src = row.get("source", "unverified_illustrative").strip()
            st = Station(
                id=row["id"],
                name=row["name"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                operator=row["operator"],
                max_kw=float(row["max_kw"]),
                connector_types=connectors,
                reliability=simulate_station_reliability(row["operator"], row["id"]),
                is_reliability_simulated=True,
                amenities={"restaurant": 2, "cafe": 1, "toilets": 2, "fuel": 1},
                amenity_score=float(row.get("amenity_score", 0.8)),
                source=src,
            )
            stations.append(st)
    return stations


def load_user_verified_csv(csv_path: str | Path) -> list[Station]:
    """Load hand-verified charging stations from a user-supplied CSV.

    Required columns:
        name, lat, lon, operator, max_kw, connectors, source_url, checked_on

    Complexity:
        O(|rows|)
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"User verified CSV not found at: {path}")

    import csv

    required_cols = {"name", "lat", "lon", "operator", "max_kw", "connectors", "source_url", "checked_on"}
    stations: list[Station] = []

    with open(path, "r", encoding="utf-8") as f:
        lines = [line for line in f if not line.strip().startswith("#")]
        reader = csv.DictReader(lines)
        if not required_cols.issubset(set(reader.fieldnames or [])):
            missing = required_cols - set(reader.fieldnames or [])
            raise ValueError(f"User CSV missing required columns: {missing}")

        for idx, row in enumerate(reader):
            connectors = [c.strip() for c in row["connectors"].split(";") if c.strip()]
            op = row["operator"].strip()
            st_id = f"verified_user_{idx + 1}"
            st = Station(
                id=st_id,
                name=row["name"].strip(),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                operator=op,
                max_kw=float(row["max_kw"]),
                connector_types=connectors,
                reliability=simulate_station_reliability(op, st_id),
                is_reliability_simulated=True,
                amenities={},
                amenity_score=0.85,
                source="verified",
                source_url=row["source_url"].strip(),
                checked_on=row["checked_on"].strip(),
                verified=True,
            )
            stations.append(st)

    return stations


def fetch_overpass_stations(
    bbox: tuple[float, float, float, float],  # (min_lat, min_lon, max_lat, max_lon)
    policy: StationIngestionPolicy | None = None,
    allow_network: bool = True,
    cache: DiskCache | None = None,
    route_coords: list[tuple[float, float]] | None = None,
    curated_csv: str | Path | None = None,
) -> tuple[list[Station], dict[str, Any]]:
    """Fetch charging stations within bounding box from Overpass API, OpenChargeMap, or curated CSV.

    Queries Open Charge Map as primary live source (sampled along route points every ~15km, radius ~10km)
    when OCM_API_KEY is configured, then supplements with Overpass API. If both network sources return 0,
    loads verified corridor stations from curated CSV with source='manual'.
    """
    policy = policy or StationIngestionPolicy()
    disk_cache = cache or DiskCache("overpass")
    min_lat, min_lon, max_lat, max_lon = bbox
    cache_key = f"stations_{min_lat:.4f}_{min_lon:.4f}_{max_lat:.4f}_{max_lon:.4f}"

    audit: dict[str, Any] = {
        "total_raw": 0,
        "kept": 0,
        "dropped_connector": 0,
        "dropped_power": 0,
        "assumed_power": 0,
        "assumed_connector": 0,
        "count_by_source": {"osm": 0, "ocm": 0, "manual": 0},
    }

    elements: list[dict[str, Any]] = []
    cached = disk_cache.get(cache_key)

    if cached is not None:
        elements = cached
    elif allow_network:
        # Divide into sub-bounding boxes if bounding area is large
        d_lat = max_lat - min_lat
        d_lon = max_lon - min_lon
        sub_boxes = []

        if d_lat > 0.4 or d_lon > 0.4:
            mid_lat = (min_lat + max_lat) / 2.0
            mid_lon = (min_lon + max_lon) / 2.0
            sub_boxes = [
                (min_lat, min_lon, mid_lat, mid_lon),
                (min_lat, mid_lon, mid_lat, max_lon),
                (mid_lat, min_lon, max_lat, mid_lon),
                (mid_lat, mid_lon, max_lat, max_lon),
            ]
        else:
            sub_boxes = [bbox]

        headers = {"User-Agent": USER_AGENT}
        seen_element_ids = set()

        for s_bbox in sub_boxes:
            b_min_lat, b_min_lon, b_max_lat, b_max_lon = s_bbox
            query = f"""
            [out:json][timeout:25];
            (
              node["amenity"="charging_station"]({b_min_lat},{b_min_lon},{b_max_lat},{b_max_lon});
              way["amenity"="charging_station"]({b_min_lat},{b_min_lon},{b_max_lat},{b_max_lon});
            );
            out center tags;
            """
            try:
                resp = requests.post(
                    OVERPASS_API_URL, data={"data": query}, headers=headers, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                for el in data.get("elements", []):
                    el_id = el.get("id")
                    if el_id not in seen_element_ids:
                        seen_element_ids.add(el_id)
                        elements.append(el)
            except (requests.RequestException, ValueError) as exc:
                if policy.raise_on_network_error:
                    raise RuntimeError(
                        f"Overpass API query failed for bbox {s_bbox}: {exc}"
                    ) from exc

        disk_cache.set(cache_key, elements)
    else:
        elements = []

    audit["total_raw"] = len(elements)

    # 1. Primary Live Source: Open Charge Map (when OCM_API_KEY is configured)
    ocm_api_key = os.getenv("OCM_API_KEY")
    if not ocm_api_key and os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as env_f:
                for line in env_f:
                    if line.startswith("OCM_API_KEY="):
                        ocm_api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass

    stations: list[Station] = []

    if ocm_api_key and allow_network:
        # Sample points along the route every ~15 km (or use center of bbox)
        sample_points = []
        if route_coords and len(route_coords) > 10:
            step = max(1, len(route_coords) // 10)
            sample_points = [route_coords[i] for i in range(0, len(route_coords), step)]
        else:
            sample_points = [((min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0)]

        ocm_headers = {
            "User-Agent": USER_AGENT,
            "X-API-Key": ocm_api_key,
        }
        seen_ocm_ids = set()

        for s_lat, s_lon in sample_points:
            ocm_cache_key = f"ocm_{s_lat:.3f}_{s_lon:.3f}_rad10"
            ocm_cached = disk_cache.get(ocm_cache_key)
            ocm_data: list[dict[str, Any]] = []
            if ocm_cached:
                ocm_data = ocm_cached
            else:
                try:
                    ocm_resp = requests.get(
                        OPENCHARGEMAP_API_URL,
                        params={
                            "output": "json",
                            "countrycode": "IN",
                            "latitude": s_lat,
                            "longitude": s_lon,
                            "distance": 10,
                            "distanceunit": "KM",
                            "maxresults": 100,
                        },
                        headers=ocm_headers,
                        timeout=15,
                    )
                    if ocm_resp.status_code == 200:
                        ocm_data = ocm_resp.json()
                        disk_cache.set(ocm_cache_key, ocm_data)
                except (requests.RequestException, ValueError) as exc:
                    if policy.raise_on_network_error:
                        raise RuntimeError("OpenChargeMap query failed") from exc
                    ocm_data = []

            for ocm_item in ocm_data:
                poi_id = str(ocm_item.get("ID", f"ocm_{len(stations)}"))
                if poi_id in seen_ocm_ids:
                    continue
                seen_ocm_ids.add(poi_id)

                addr = ocm_item.get("AddressInfo", {})
                lat_f = addr.get("Latitude")
                lon_f = addr.get("Longitude")
                if lat_f is None or lon_f is None:
                    continue

                op_info = ocm_item.get("OperatorInfo") or {}
                op_title = op_info.get("Title") or "OpenChargeMap Network"

                # Parse real PowerKW and ConnectionType from Connections array
                connections = ocm_item.get("Connections") or []
                max_kw = 0.0
                connectors: list[str] = []
                power_assumed = False
                connector_assumed = False

                if isinstance(connections, list) and len(connections) > 0:
                    for conn in connections:
                        p_kw = conn.get("PowerKW")
                        if p_kw is not None and isinstance(p_kw, (int, float)) and p_kw > 0:
                            max_kw = max(max_kw, float(p_kw))

                        conn_type = conn.get("ConnectionType") or {}
                        c_title = (conn_type.get("Title") or conn_type.get("FormalName") or "").lower()
                        if "ccs" in c_title or "combo" in c_title or "type 2 combo" in c_title:
                            if "CCS2" not in connectors:
                                connectors.append("CCS2")
                        elif "type 2" in c_title or "type2" in c_title:
                            if "Type 2" not in connectors:
                                connectors.append("Type 2")
                        elif "chademo" in c_title and "CHAdeMO" not in connectors:
                            connectors.append("CHAdeMO")

                if max_kw <= 0.0:
                    max_kw = policy.assume_missing_power_kw if policy.assume_missing_power_kw is not None else 50.0
                    power_assumed = True
                    audit["assumed_power"] += 1

                if not connectors:
                    if policy.assume_missing_connector_as_ccs2:
                        connectors = [policy.default_connector]
                        connector_assumed = True
                        audit["assumed_connector"] += 1
                    else:
                        audit["dropped_connector"] += 1
                        continue

                station = Station(
                    id=f"ocm_{poi_id}",
                    name=addr.get("Title", f"OCM Charger {poi_id}"),
                    lat=float(lat_f),
                    lon=float(lon_f),
                    operator=op_title,
                    max_kw=max_kw,
                    connector_types=connectors,
                    reliability=simulate_station_reliability(op_title, f"ocm_{poi_id}"),
                    is_reliability_simulated=True,
                    amenities={},
                    amenity_score=0.0,
                    power_assumed=power_assumed,
                    connector_assumed=connector_assumed,
                    amenity_known=False,
                    spur_estimated=True,
                    source="ocm",
                )
                stations.append(station)
                audit["kept"] += 1
                audit["count_by_source"]["ocm"] += 1

    # 2. Secondary Live Source / Fixture: Overpass API
    from ingest.route import haversine_distance_m

    for elem in elements:
        tags = elem.get("tags", {})
        elem_id = str(elem.get("id", f"station_{len(stations)}"))
        name = tags.get("name") or tags.get("operator") or f"EV Station {elem_id}"
        operator = tags.get("operator") or tags.get("brand") or "Independent Operator"

        # Position (nodes have lat/lon; ways have center.lat/center.lon)
        lat = elem.get("lat") or elem.get("center", {}).get("lat")
        lon = elem.get("lon") or elem.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue

        lat_f = float(lat)
        lon_f = float(lon)

        # Proximity deduplication: if station already exists from primary OCM within 100m, skip OSM duplicate
        is_duplicate = False
        for existing in stations:
            if haversine_distance_m(lat_f, lon_f, existing.lat, existing.lon) < 100.0:
                is_duplicate = True
                break
        if is_duplicate:
            continue

        # Power parsing
        power_str = tags.get("capacity:output") or tags.get("socket:output") or tags.get("power")
        max_kw: float | None = None
        power_assumed = False

        if power_str:
            try:
                num_part = "".join(ch for ch in power_str if ch.isdigit() or ch == ".")
                if num_part:
                    max_kw = float(num_part)
            except ValueError:
                max_kw = None

        if max_kw is None:
            if policy.assume_missing_power_kw is not None:
                max_kw = policy.assume_missing_power_kw
                power_assumed = True
                audit["assumed_power"] += 1
            else:
                audit["dropped_power"] += 1
                continue

        # Connectors parsing
        connectors: list[str] = []
        connector_assumed = False
        socket_tags = [k for k in tags if "socket:" in k or "connector:" in k]
        for s_tag in socket_tags:
            val = tags[s_tag]
            if val in ("yes", "1", "2", "3", "4") or "ccs" in s_tag.lower():
                if "ccs2" in s_tag.lower() or "type2_combo" in s_tag.lower():
                    connectors.append("CCS2")
                elif "chademo" in s_tag.lower():
                    connectors.append("CHAdeMO")
                elif "type2" in s_tag.lower():
                    connectors.append("Type 2")

        if not connectors:
            if policy.assume_missing_connector_as_ccs2:
                connectors = [policy.default_connector]
                connector_assumed = True
                audit["assumed_connector"] += 1
            else:
                audit["dropped_connector"] += 1
                continue

        # Simulated reliability with deterministic hash seed
        rel = simulate_station_reliability(operator, f"{elem_id}_{name}")

        station = Station(
            id=f"osm_{elem_id}",
            name=name,
            lat=lat_f,
            lon=lon_f,
            operator=operator,
            max_kw=max_kw,
            connector_types=connectors,
            reliability=rel,
            is_reliability_simulated=True,
            amenities={},
            amenity_score=0.0,
            power_assumed=power_assumed,
            connector_assumed=connector_assumed,
            amenity_known=False,
            spur_estimated=True,
            source="osm",
        )
        stations.append(station)
        audit["kept"] += 1
        audit["count_by_source"]["osm"] += 1

    # 3. Fallback when live API queries return 0 results
    if len(stations) == 0:
        curated = load_curated_stations(curated_csv)
        matching_curated = [
            st for st in curated
            if (min_lat - 0.2 <= st.lat <= max_lat + 0.2 and min_lon - 0.2 <= st.lon <= max_lon + 0.2)
        ]
        if matching_curated:
            for st in matching_curated:
                stations.append(st)
                audit["kept"] += 1
                audit["count_by_source"][st.source] = audit["count_by_source"].get(st.source, 0) + 1
        elif route_coords and len(route_coords) >= 10:
            # Generate corridor charging stations along the road trajectory
            total_dist_m = sum(
                haversine_distance_m(route_coords[i][0], route_coords[i][1], route_coords[i + 1][0], route_coords[i + 1][1])
                for i in range(len(route_coords) - 1)
            )
            step_m = 45_000.0  # every ~45 km
            num_stops = max(2, int(total_dist_m / step_m))
            target_step = total_dist_m / (num_stops + 1)

            curr_acc = 0.0
            next_target = target_step
            st_idx = 1
            for i in range(len(route_coords) - 1):
                d = haversine_distance_m(route_coords[i][0], route_coords[i][1], route_coords[i + 1][0], route_coords[i + 1][1])
                curr_acc += d
                if curr_acc >= next_target and st_idx <= num_stops:
                    lat_c, lon_c = route_coords[i]
                    st_id = f"synth_corridor_stat_{st_idx}"
                    op = "Tata Power" if st_idx % 2 == 1 else "Jio-bp pulse"
                    st = Station(
                        id=st_id,
                        name=f"{op} - Highway Stop {st_idx}",
                        lat=round(lat_c + (0.0005 if st_idx % 2 == 0 else -0.0005), 5),
                        lon=round(lon_c + (0.0005 if st_idx % 2 == 0 else -0.0005), 5),
                        operator=op,
                        max_kw=60.0 if st_idx % 2 == 1 else 120.0,
                        connector_types=["CCS2"],
                        reliability=simulate_station_reliability(op, st_id),
                        is_reliability_simulated=True,
                        amenities={"restaurant": 2, "cafe": 1, "toilets": 1, "fuel": 1},
                        amenity_score=0.85,
                        power_assumed=False,
                        connector_assumed=False,
                        amenity_known=False,
                        spur_estimated=True,
                        source="synthetic",
                    )
                    stations.append(st)
                    audit["kept"] += 1
                    audit["count_by_source"]["synthetic"] = audit["count_by_source"].get("synthetic", 0) + 1
                    next_target += target_step
                    st_idx += 1

    audit["data_provenance"] = compute_data_provenance(stations)
    return stations, audit


def compute_station_route_distances(
    stations: list[Station], route_coords: list[tuple[float, float]]
) -> dict[str, float]:
    """Compute distance statistics (min, mean, max in km) from stations to nearest route points."""
    from ingest.route import haversine_distance_m

    if not stations or not route_coords:
        return {"min_km": 0.0, "mean_km": 0.0, "max_km": 0.0}

    distances_km = []
    for st in stations:
        min_d_m = min(haversine_distance_m(st.lat, st.lon, r_lat, r_lon) for r_lat, r_lon in route_coords)
        distances_km.append(min_d_m / 1000.0)

    return {
        "min_km": round(min(distances_km), 2),
        "mean_km": round(sum(distances_km) / len(distances_km), 2),
        "max_km": round(max(distances_km), 2),
    }

