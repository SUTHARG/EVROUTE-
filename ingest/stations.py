"""Overpass and OpenChargeMap station ingestion client with simulated reliability and audit logging."""

from __future__ import annotations

import os
import random
from typing import Any

import requests

from core.models import Station
from ingest.cache import DiskCache

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


def fetch_overpass_stations(
    bbox: tuple[float, float, float, float],  # (min_lat, min_lon, max_lat, max_lon)
    policy: StationIngestionPolicy | None = None,
    allow_network: bool = True,
    cache: DiskCache | None = None,
) -> tuple[list[Station], dict[str, Any]]:
    """Fetch charging stations within bounding box from Overpass API and optional OpenChargeMap.

    Queries Overpass with proper User-Agent headers, chunking large boxes to avoid 406/429
    rejection, and raises descriptive errors on network/timeout failures when configured.

    Complexity:
        O(N) where N is the number of stations returned.

    Returns:
        Tuple of (list of Station objects, audit_log_dict).
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
        "count_by_source": {"osm": 0, "ocm": 0},
    }

    elements: list[dict[str, Any]] = []
    cached = disk_cache.get(cache_key)

    if cached is not None:
        elements = cached
    elif allow_network:
        # Divide into 2x2 sub-bounding boxes if bounding area is large
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
                # Otherwise keep collected elements

        disk_cache.set(cache_key, elements)
    else:
        elements = []

    audit["total_raw"] = len(elements)
    stations: list[Station] = []

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
            lat=float(lat),
            lon=float(lon),
            operator=operator,
            max_kw=max_kw,
            connector_types=connectors,
            reliability=rel,
            is_reliability_simulated=True,
            amenities={},
            amenity_score=0.0,
            power_assumed=power_assumed,
            connector_assumed=connector_assumed,
            source="osm",
        )
        stations.append(station)
        audit["kept"] += 1
        audit["count_by_source"]["osm"] += 1

    # Optional Open Charge Map supplement reading OCM_API_KEY from environment or .env
    ocm_api_key = os.getenv("OCM_API_KEY")
    if not ocm_api_key and os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as env_f:
                for line in env_f:
                    if line.startswith("OCM_API_KEY="):
                        ocm_api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass

    if ocm_api_key and allow_network:
        ocm_cache_key = f"ocm_{min_lat:.3f}_{min_lon:.3f}_{max_lat:.3f}_{max_lon:.3f}"
        ocm_cached = disk_cache.get(ocm_cache_key)
        ocm_data: list[dict[str, Any]] = []
        if ocm_cached:
            ocm_data = ocm_cached
        else:
            try:
                headers = {"User-Agent": USER_AGENT}
                ocm_resp = requests.get(
                    OPENCHARGEMAP_API_URL,
                    params={
                        "output": "json",
                        "countrycode": "IN",
                        "boundingbox": f"({min_lat},{min_lon}),({max_lat},{max_lon})",
                        "maxresults": 100,
                        "key": ocm_api_key,
                    },
                    headers=headers,
                    timeout=20,
                )
                if ocm_resp.status_code == 200:
                    ocm_data = ocm_resp.json()
                    disk_cache.set(ocm_cache_key, ocm_data)
            except (requests.RequestException, ValueError) as exc:
                if policy.raise_on_network_error:
                    raise RuntimeError(f"OpenChargeMap query failed: {exc}") from exc
                ocm_data = []

        for ocm_item in ocm_data:
            poi_id = str(ocm_item.get("ID", f"ocm_{len(stations)}"))
            addr = ocm_item.get("AddressInfo", {})
            lat_f = addr.get("Latitude")
            lon_f = addr.get("Longitude")
            if lat_f is None or lon_f is None:
                continue

            op_info = ocm_item.get("OperatorInfo") or {}
            op_title = op_info.get("Title") or "OpenChargeMap Network"
            station = Station(
                id=f"ocm_{poi_id}",
                name=addr.get("Title", f"OCM Charger {poi_id}"),
                lat=float(lat_f),
                lon=float(lon_f),
                operator=op_title,
                max_kw=60.0,
                connector_types=["CCS2"],
                reliability=simulate_station_reliability(op_title, f"ocm_{poi_id}"),
                is_reliability_simulated=True,
                amenities={},
                amenity_score=0.0,
                source="ocm",
            )
            stations.append(station)
            audit["kept"] += 1
            audit["count_by_source"]["ocm"] += 1

    return stations, audit
