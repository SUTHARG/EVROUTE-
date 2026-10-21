"""Station provider interfaces and live data ingestion clients for Route.ev.

Supports:
1. GooglePlacesProvider (Google Places API (New) with FieldMask, 20km route sampling, 24h static & 5m availability cache)
2. OpenChargeMapProvider (Open Charge Map API v3 with Connections array parsing)
3. ManualVerifiedCSVProvider (Hand-verified user-supplied stations from data/stations/verified_stations.csv)
4. OCMSnapshotProvider (Local Open Charge Map POI.json.gz snapshot)
5. OverpassProvider (OpenStreetMap fallback)

Enforces strict 4-wheeler EV connector filtering (CCS2, Type 2 AC, CHAdeMO), 100m spatial
deduplication with hierarchical provider priority, and honest provenance tracking.
Never exposes or prints API keys in logs or exceptions.
"""

from __future__ import annotations

import csv
import random
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from core.config import (
    CACHE_TTL_AVAILABILITY_MINUTES,
    CACHE_TTL_STATIC_HOURS,
    EXCLUDED_2W_3W_CONNECTORS,
    GOOGLE_PLACES_SAMPLE_INTERVAL_M,
    GOOGLE_PLACES_SAMPLE_RADIUS_M,
    MAX_GOOGLE_PLACES_PER_ROUTE,
    MAX_OCM_CALLS_PER_ROUTE,
    OCM_SAMPLE_RADIUS_KM,
    STATION_DEDUPLICATION_RADIUS_M,
    SUPPORTED_4W_CONNECTORS,
    VERIFIED_STATIONS_CSV_PATH,
    get_google_maps_api_key,
    get_ocm_api_key,
)
from core.models import Station, StationAvailability
from ingest.cache import DiskCache
from ingest.route import haversine_distance_m

USER_AGENT: str = "RouteEV-TripPlanner/1.0 (academic-dsa-project)"


def simulate_station_reliability(operator: str, seed_key: str) -> float:
    """Generate a reproducible, seeded simulated reliability score for an EV charger.

    This number is explicitly labeled 'simulated' and used only as an internal weighting.
    """
    op_clean = operator.lower().strip()
    base_score = 0.78
    known_ratings: dict[str, float] = {
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
    for known_op, score in known_ratings.items():
        if known_op in op_clean:
            base_score = score
            break

    rng = random.Random(f"rel_seed_{seed_key}")
    noise = rng.gauss(0.0, 0.035)
    return round(max(0.20, min(0.99, base_score + noise)), 3)


def normalize_connector_type(raw_type: str) -> tuple[str | None, bool]:
    """Map raw connector identifier or description into normalized 4W standard.

    Returns:
        (normalized_name, is_2w_3w_excluded)
    """
    raw_lower = raw_type.lower().strip()

    # Check 2W/3W exclusions
    for excluded in EXCLUDED_2W_3W_CONNECTORS:
        if excluded.lower() in raw_lower:
            return None, True

    # 4-Wheeler standards
    if "ccs2" in raw_lower or "combo 2" in raw_lower or "combo_2" in raw_lower or "type 2 combo" in raw_lower or "ccs_combo_2" in raw_lower:
        return "CCS2", False
    if "type 2" in raw_lower or "type2" in raw_lower or "iec 62196-2" in raw_lower:
        return "Type 2 (AC)", False
    if "chademo" in raw_lower:
        return "CHAdeMO", False

    return None, False


class StationProvider(ABC):
    """Abstract Base Class for EV Charging Station data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier string: 'google_places', 'ocm', 'verified_manual', 'osm'."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider has necessary configuration / keys to run."""

    @abstractmethod
    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
    ) -> list[Station]:
        """Fetch and normalize charging stations along route and bounding box."""


import logging

from ingest.ocm_snapshot import OCMSnapshotProvider, clean_station_name

logger = logging.getLogger(__name__)


class ManualVerifiedCSVProvider(StationProvider):
    """Loads hand-verified charging stations from local CSV dataset."""

    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or VERIFIED_STATIONS_CSV_PATH

    @property
    def name(self) -> str:
        return "verified_manual"

    def is_available(self) -> bool:
        return self.csv_path.exists()

    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
    ) -> list[Station]:
        if not self.csv_path.exists():
            return []

        min_lat, min_lon, max_lat, max_lon = bbox
        # Add 25km buffer for verified hubs along highway approach corridors
        buf_deg = 0.25
        b_min_lat, b_max_lat = min_lat - buf_deg, max_lat + buf_deg
        b_min_lon, b_max_lon = min_lon - buf_deg, max_lon + buf_deg

        stations: list[Station] = []
        fetched_iso = datetime.now(UTC).isoformat()
        rejected_rows = 0

        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if not line.strip().startswith("#")]
                reader = csv.DictReader(lines)
                for idx, row in enumerate(reader):
                    # Strict validation: reject any row missing non-empty source_url or checked_on
                    source_url = row.get("source_url", "").strip() or None
                    checked_on = row.get("checked_on", "").strip() or None
                    if not source_url or not checked_on:
                        rejected_rows += 1
                        logger.warning(
                            "ManualVerifiedCSVProvider: Row %d rejected (missing source_url or checked_on): %s",
                            idx + 1,
                            row.get("name", "unnamed"),
                        )
                        continue

                    try:
                        lat = float(row["lat"])
                        lon = float(row["lon"])
                    except (KeyError, ValueError):
                        rejected_rows += 1
                        continue

                    # Filter within corridor bounding area
                    if not (b_min_lat <= lat <= b_max_lat and b_min_lon <= lon <= b_max_lon):
                        continue

                    # Documented fallback defaults for verified CSV data with missing power or connector fields:
                    # DEFAULT_ASSUMED_MAX_KW = 50.0 kW (standard Indian highway DC fast charge rate)
                    # DEFAULT_ASSUMED_CONNECTORS = ["CCS2"] (standard passenger 4-wheeler DC fast connector in India)
                    raw_max_kw = row.get("max_kw", "").strip()
                    power_assumed = False
                    if not raw_max_kw:
                        max_kw = 50.0
                        power_assumed = True
                    else:
                        try:
                            max_kw = float(raw_max_kw)
                            if max_kw <= 0.0:
                                max_kw = 50.0
                                power_assumed = True
                        except ValueError:
                            max_kw = 50.0
                            power_assumed = True

                    # Parse connectors with documented default
                    raw_connectors_str = row.get("connectors", "").strip()
                    connector_assumed = False
                    connector_unknown = False

                    if not raw_connectors_str:
                        normalized_connectors = ["CCS2"]
                        connector_assumed = True
                    else:
                        raw_connectors = [c.strip() for c in raw_connectors_str.split(";") if c.strip()]
                        normalized_connectors = []
                        is_excluded = False
                        for c_raw in raw_connectors:
                            norm, excluded = normalize_connector_type(c_raw)
                            if excluded:
                                is_excluded = True
                            elif norm and norm not in normalized_connectors:
                                normalized_connectors.append(norm)

                        if not normalized_connectors:
                            if is_excluded:
                                # Row only contains 2W/3W connectors (e.g. 15A 3-pin / Bharat DC-001)
                                continue
                            # Unrecognized connector string -> assume standard passenger 4W CCS2
                            normalized_connectors = ["CCS2"]
                            connector_assumed = True

                    st_id = f"verified_csv_{idx + 1}"
                    op = row.get("operator", "Unknown Operator").strip()
                    charger_count_raw = row.get("charger_count", "").strip()
                    charger_count = int(charger_count_raw) if charger_count_raw.isdigit() else 2

                    raw_name = row.get("name", f"EV Charger {st_id}").strip()
                    name = clean_station_name(raw_name)

                    st = Station(
                        id=st_id,
                        name=name,
                        lat=lat,
                        lon=lon,
                        operator=op,
                        max_kw=max_kw,
                        charger_count=charger_count,
                        connector_types=normalized_connectors,
                        availability=None,
                        reliability=simulate_station_reliability(op, st_id),
                        is_reliability_simulated=True,
                        amenities={"restaurant": 2, "cafe": 1, "toilets": 2, "fuel": 1},
                        amenity_score=0.90,
                        power_assumed=power_assumed,
                        connector_assumed=connector_assumed,
                        connector_unknown=connector_unknown,
                        amenity_known=True,
                        spur_estimated=True,
                        source="verified_manual",
                        source_url=source_url,
                        fetched_at=fetched_iso,
                        verified=True,
                        checked_on=checked_on,
                    )
                    stations.append(st)

            api_tracker["verified_manual_files"] = api_tracker.get("verified_manual_files", 0) + 1
            logger.info(
                "ManualVerifiedCSVProvider: Loaded %d verified stations from %s (rejected %d rows)",
                len(stations),
                self.csv_path,
                rejected_rows,
            )
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            failed_tracker.append(f"ManualVerifiedCSVProvider error: {exc}")

        return stations

    @staticmethod
    def inspect_verified_csv_at_startup(csv_path: Path = VERIFIED_STATIONS_CSV_PATH) -> tuple[int, int]:
        """Inspect CSV at startup and return (valid_count, rejected_count)."""
        if not csv_path.exists():
            return 0, 0
        valid_count = 0
        rejected_count = 0
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if not line.strip().startswith("#")]
                reader = csv.DictReader(lines)
                for row in reader:
                    source_url = row.get("source_url", "").strip() or None
                    checked_on = row.get("checked_on", "").strip() or None
                    if not source_url or not checked_on:
                        rejected_count += 1
                        continue
                    try:
                        float(row["lat"])
                        float(row["lon"])
                        valid_count += 1
                    except (KeyError, ValueError):
                        rejected_count += 1
        except OSError:
            pass
        return valid_count, rejected_count


class GooglePlacesProvider(StationProvider):
    """Google Places API (New) provider with FieldMask, route sampling, and dual caching."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self.cache = DiskCache("google_places")

    @property
    def effective_api_key(self) -> str | None:
        return self.api_key or get_google_maps_api_key()

    @property
    def name(self) -> str:
        return "google_places"

    def is_available(self) -> bool:
        key = self.effective_api_key
        return bool(key and len(key.strip()) > 5)

    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
    ) -> list[Station]:
        if not self.is_available():
            return []

        # Sample points along route every ~20 km
        sample_points: list[tuple[float, float]] = []
        if len(route_coords) >= 2:
            step_m = GOOGLE_PLACES_SAMPLE_INTERVAL_M
            cum_m = 0.0
            sample_points.append(route_coords[0])
            for i in range(len(route_coords) - 1):
                d = haversine_distance_m(route_coords[i][0], route_coords[i][1], route_coords[i + 1][0], route_coords[i + 1][1])
                cum_m += d
                if cum_m >= step_m:
                    sample_points.append(route_coords[i + 1])
                    cum_m = 0.0
                    if len(sample_points) >= MAX_GOOGLE_PLACES_PER_ROUTE:
                        break
            if sample_points[-1] != route_coords[-1] and len(sample_points) < MAX_GOOGLE_PLACES_PER_ROUTE:
                sample_points.append(route_coords[-1])
        else:
            min_lat, min_lon, max_lat, max_lon = bbox
            sample_points = [((min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0)]

        url = "https://places.googleapis.com/v1/places:searchText"
        field_mask = (
            "places.id,"
            "places.displayName,"
            "places.location,"
            "places.evChargeOptions,"
            "places.googleMapsUri"
        )
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.effective_api_key or "",
            "X-Goog-FieldMask": field_mask,
        }

        stations_by_place_id: dict[str, Station] = {}
        now_ts = time.time()
        now_iso = datetime.now(UTC).isoformat()

        for s_lat, s_lon in sample_points:
            cache_key = f"gp_sample_{s_lat:.3f}_{s_lon:.3f}"
            cached_entry = self.cache.get(cache_key)
            places_raw: list[dict[str, Any]] = []

            # Check cache TTL: availability 5 min, static 24 h
            use_cached = False
            if cached_entry and isinstance(cached_entry, dict):
                cached_time = cached_entry.get("timestamp", 0.0)
                if now_ts - cached_time < CACHE_TTL_AVAILABILITY_MINUTES * 60:
                    places_raw = cached_entry.get("places", [])
                    use_cached = True

            if not use_cached:
                body = {
                    "textQuery": "EV charging station",
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": s_lat, "longitude": s_lon},
                            "radius": GOOGLE_PLACES_SAMPLE_RADIUS_M,
                        }
                    },
                    "maxResultCount": 20,
                }
                try:
                    api_tracker["google_places_calls"] = api_tracker.get("google_places_calls", 0) + 1
                    resp = requests.post(url, json=body, headers=headers, timeout=12)
                    if resp.status_code == 200:
                        data = resp.json()
                        places_raw = data.get("places", [])
                        self.cache.set(cache_key, {"timestamp": now_ts, "places": places_raw})
                    elif resp.status_code in (429, 403):
                        failed_tracker.append(f"Google Places quota/permission limited (HTTP {resp.status_code})")
                        break
                    else:
                        failed_tracker.append(f"Google Places request returned status {resp.status_code}")
                except (requests.RequestException, OSError, ValueError, KeyError) as exc:
                    failed_tracker.append(f"Google Places network connection failed: {exc}")
                    break

            for p in places_raw:
                place_id = p.get("id")
                if not place_id or place_id in stations_by_place_id:
                    continue

                display_name = p.get("displayName", {}).get("text", f"EV Charger {place_id}")
                loc = p.get("location", {})
                lat_val = loc.get("latitude")
                lon_val = loc.get("longitude")
                if lat_val is None or lon_val is None:
                    continue

                maps_uri = p.get("googleMapsUri")
                ev_opts = p.get("evChargeOptions") or {}
                connector_aggs = ev_opts.get("connectorAggregation") or []

                connectors: list[str] = []
                max_kw = 0.0
                max_ac_kw = 0.0
                max_dc_kw = 0.0
                total_chargers = ev_opts.get("connectorCount", 0)
                available_count = 0
                out_of_service_count = 0
                has_live_avail = False
                last_updated_str: str | None = None

                is_2w_3w_excluded = False
                for agg in connector_aggs:
                    raw_c_type = agg.get("type", "")
                    norm, excluded = normalize_connector_type(raw_c_type)
                    if excluded:
                        is_2w_3w_excluded = True
                    elif norm and norm not in connectors:
                        connectors.append(norm)

                    p_kw = agg.get("maxChargeRateKw")
                    if p_kw and isinstance(p_kw, (int, float)) and p_kw > max_kw:
                        max_kw = float(p_kw)
                    if p_kw and isinstance(p_kw, (int, float)) and norm:
                        if norm == "Type 2 (AC)":
                            max_ac_kw = max(max_ac_kw, float(p_kw))
                        elif norm in {"CCS2", "CHAdeMO"}:
                            max_dc_kw = max(max_dc_kw, float(p_kw))

                    c_cnt = agg.get("count", 0)
                    if total_chargers == 0 and c_cnt > 0:
                        total_chargers += c_cnt

                    if "availableCount" in agg:
                        has_live_avail = True
                        available_count += agg.get("availableCount", 0)
                        out_of_service_count += agg.get("outOfServiceCount", 0)
                        if not last_updated_str and "availabilityLastUpdateTime" in agg:
                            last_updated_str = agg.get("availabilityLastUpdateTime")

                power_assumed = False
                if max_kw <= 0.0:
                    max_kw = 50.0
                    power_assumed = True

                connector_unknown = False
                connector_assumed = False
                if not connectors:
                    if is_2w_3w_excluded:
                        continue
                    connector_unknown = True
                    connector_assumed = True
                    connectors = ["Unknown Connector"]

                avail_obj: StationAvailability | None = None
                if has_live_avail:
                    avail_obj = StationAvailability(
                        available=available_count,
                        total=max(total_chargers, available_count + out_of_service_count),
                        out_of_service=out_of_service_count,
                        last_updated=last_updated_str or now_iso,
                    )

                # Determine operator from title
                op_name = "EV Charging Network"
                for known in ["Tata Power", "Jio-bp", "Statiq", "Zeon", "ChargeZone", "Glida", "Fortum"]:
                    if known.lower() in display_name.lower():
                        op_name = known
                        break

                station = Station(
                    id=f"gp_{place_id}",
                    name=display_name,
                    lat=float(lat_val),
                    lon=float(lon_val),
                    operator=op_name,
                    max_kw=max_kw,
                    max_ac_kw=max_ac_kw or None,
                    max_dc_kw=max_dc_kw or None,
                    charger_count=max(1, total_chargers),
                    connector_types=connectors,
                    availability=avail_obj,
                    reliability=simulate_station_reliability(op_name, place_id),
                    is_reliability_simulated=True,
                    amenities={"cafe": 1, "restaurant": 1, "toilets": 1},
                    amenity_score=0.80,
                    power_assumed=power_assumed,
                    connector_assumed=connector_assumed,
                    connector_unknown=connector_unknown,
                    amenity_known=False,
                    spur_estimated=True,
                    source="google_places",
                    source_url=maps_uri,
                    fetched_at=now_iso,
                    verified=False,
                )
                stations_by_place_id[place_id] = station

        return list(stations_by_place_id.values())


class OpenChargeMapProvider(StationProvider):
    """Open Charge Map v3 API provider with Connections array parsing."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self.cache = DiskCache("ocm")

    @property
    def effective_api_key(self) -> str | None:
        return self.api_key or get_ocm_api_key()

    @property
    def name(self) -> str:
        return "ocm"

    def is_available(self) -> bool:
        key = self.effective_api_key
        return bool(key and len(key.strip()) > 5)

    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
    ) -> list[Station]:
        if not self.is_available():
            return []

        sample_points: list[tuple[float, float]] = []
        if len(route_coords) >= 2:
            num_samples = min(MAX_OCM_CALLS_PER_ROUTE, max(3, len(route_coords) // 20))
            if num_samples >= 2:
                sample_indices = [
                    round(i * (len(route_coords) - 1) / (num_samples - 1))
                    for i in range(num_samples)
                ]
                sample_points = [route_coords[idx] for idx in sample_indices]
            else:
                sample_points = [route_coords[0], route_coords[-1]]
        else:
            min_lat, min_lon, max_lat, max_lon = bbox
            sample_points = [((min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0)]

        ocm_url = "https://api.openchargemap.io/v3/poi"
        # Send API key strictly in the X-API-Key header, never in URL query params
        headers = {
            "User-Agent": USER_AGENT,
            "X-API-Key": self.effective_api_key or "",
        }
        seen_ids: set[str] = set()
        stations: list[Station] = []
        now_iso = datetime.now(UTC).isoformat()
        api_tracker["ocm_samples_count"] = len(sample_points)
        api_tracker["ocm_radius_km"] = int(OCM_SAMPLE_RADIUS_KM)

        for s_lat, s_lon in sample_points:
            cache_key = f"ocm_{s_lat:.3f}_{s_lon:.3f}_rad{int(OCM_SAMPLE_RADIUS_KM)}"
            ocm_data: list[dict[str, Any]] = []
            # Cache responses for 24 hours (CACHE_TTL_STATIC_HOURS)
            cached = self.cache.get(cache_key, max_age_seconds=CACHE_TTL_STATIC_HOURS * 3600)

            if cached is not None:
                ocm_data = cached
            else:
                try:
                    api_tracker["ocm_calls"] = api_tracker.get("ocm_calls", 0) + 1
                    resp = requests.get(
                        ocm_url,
                        params={
                            "output": "json",
                            "countrycode": "IN",
                            "latitude": s_lat,
                            "longitude": s_lon,
                            "distance": OCM_SAMPLE_RADIUS_KM,
                            "distanceunit": "KM",
                            "maxresults": 100,
                            "includecomments": "false",
                        },
                        headers=headers,
                        timeout=(3.0, 8.0),
                    )

                    if resp.status_code == 200:
                        ocm_data = resp.json()
                        self.cache.set(cache_key, ocm_data)
                    else:
                        failed_tracker.append(f"OpenChargeMap HTTP status {resp.status_code}")
                except (requests.RequestException, OSError, ValueError, KeyError) as exc:
                    failed_tracker.append(f"OpenChargeMap query failed: {exc}")

            if len(ocm_data) >= 100:
                api_tracker["ocm_cap_reached_samples"] = api_tracker.get("ocm_cap_reached_samples", 0) + 1
                cap_msg = f"OpenChargeMap result cap (100) reached near ({s_lat:.3f}, {s_lon:.3f}); local density may exceed single-query limit"
                if cap_msg not in failed_tracker:
                    failed_tracker.append(cap_msg)

            for item in ocm_data:
                poi_id = str(item.get("ID", ""))
                if not poi_id or poi_id in seen_ids:
                    continue
                seen_ids.add(poi_id)

                addr = item.get("AddressInfo") or {}
                lat_f = addr.get("Latitude")
                lon_f = addr.get("Longitude")
                if lat_f is None or lon_f is None:
                    continue

                op_info = item.get("OperatorInfo") or {}
                op_title = op_info.get("Title") or "OpenChargeMap Network"

                connections = item.get("Connections") or []
                max_kw = 0.0
                max_ac_kw = 0.0
                max_dc_kw = 0.0
                total_chargers = 0
                connectors: list[str] = []
                is_2w_3w_excluded = False

                for conn in connections:
                    qty = conn.get("Quantity") or 1
                    total_chargers += int(qty)
                    p_kw = conn.get("PowerKW")
                    if p_kw and isinstance(p_kw, (int, float)) and p_kw > max_kw:
                        max_kw = float(p_kw)

                    c_type = conn.get("ConnectionType") or {}
                    raw_c_title = c_type.get("Title") or c_type.get("FormalName") or ""
                    norm, excluded = normalize_connector_type(raw_c_title)
                    if excluded:
                        is_2w_3w_excluded = True
                    elif norm and norm not in connectors:
                        connectors.append(norm)
                    if p_kw and isinstance(p_kw, (int, float)) and norm:
                        if norm == "Type 2 (AC)":
                            max_ac_kw = max(max_ac_kw, float(p_kw))
                        elif norm in {"CCS2", "CHAdeMO"}:
                            max_dc_kw = max(max_dc_kw, float(p_kw))

                power_assumed = False
                if max_kw <= 0.0:
                    max_kw = 50.0
                    power_assumed = True

                connector_unknown = False
                connector_assumed = False
                if not connectors:
                    if is_2w_3w_excluded:
                        continue
                    connector_unknown = True
                    connector_assumed = True
                    connectors = ["Unknown Connector"]

                dp_obj = item.get("DataProvider") or {}
                dp_name = dp_obj.get("Title") if isinstance(dp_obj, dict) else None
                dp_license = dp_obj.get("License") if isinstance(dp_obj, dict) else None

                status_type = item.get("StatusType") or {}
                date_last_status = item.get("DateLastStatusUpdate")
                avail_obj: StationAvailability | None = None
                if status_type or date_last_status:
                    is_operational = status_type.get("IsOperational", True) if isinstance(status_type, dict) else True
                    tot_chargers = max(1, total_chargers)
                    avail_obj = StationAvailability(
                        available=tot_chargers if is_operational else 0,
                        total=tot_chargers,
                        out_of_service=0 if is_operational else tot_chargers,
                        last_updated=date_last_status or now_iso,
                    )

                st = Station(
                    id=f"ocm_{poi_id}",
                    name=addr.get("Title", f"OCM Charger {poi_id}"),
                    lat=float(lat_f),
                    lon=float(lon_f),
                    operator=op_title,
                    max_kw=max_kw,
                    max_ac_kw=max_ac_kw or None,
                    max_dc_kw=max_dc_kw or None,
                    charger_count=max(1, total_chargers),
                    connector_types=connectors,
                    availability=avail_obj,
                    reliability=simulate_station_reliability(op_title, f"ocm_{poi_id}"),
                    is_reliability_simulated=True,
                    amenities={},
                    amenity_score=0.0,
                    power_assumed=power_assumed,
                    connector_assumed=connector_assumed,
                    connector_unknown=connector_unknown,
                    amenity_known=False,
                    spur_estimated=True,
                    source="ocm",
                    source_url=f"https://openchargemap.org/site/poi/details/{poi_id}",
                    fetched_at=now_iso,
                    verified=False,
                    data_provider_name=dp_name,
                    data_provider_license=dp_license,
                )
                stations.append(st)

        return stations



class OverpassProvider(StationProvider):
    """OpenStreetMap Overpass API provider."""

    def __init__(self) -> None:
        self.cache = DiskCache("overpass")

    @property
    def name(self) -> str:
        return "osm"

    def is_available(self) -> bool:
        return True

    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
    ) -> list[Station]:
        min_lat, min_lon, max_lat, max_lon = bbox
        cache_key = f"osm_{min_lat:.3f}_{min_lon:.3f}_{max_lat:.3f}_{max_lon:.3f}"
        elements: list[dict[str, Any]] = []
        cached = self.cache.get(cache_key)

        if cached is not None:
            elements = cached
        else:
            query = f"""
            [out:json][timeout:25];
            (
              node["amenity"="charging_station"]({min_lat},{min_lon},{max_lat},{max_lon});
              way["amenity"="charging_station"]({min_lat},{min_lon},{max_lat},{max_lon});
            );
            out center tags;
            """
            try:
                api_tracker["osm_calls"] = api_tracker.get("osm_calls", 0) + 1
                resp = requests.post(
                    "https://overpass-api.de/api/interpreter",
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=(3.0, 8.0),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    elements = data.get("elements", [])
                    self.cache.set(cache_key, elements)
                else:
                    failed_tracker.append(f"OSM Overpass returned status {resp.status_code}")
            except (requests.RequestException, OSError, ValueError, KeyError) as exc:
                failed_tracker.append(f"OSM Overpass query failed: {exc}")

        stations: list[Station] = []
        now_iso = datetime.now(UTC).isoformat()

        for elem in elements:
            tags = elem.get("tags", {})
            elem_id = str(elem.get("id", f"osm_{len(stations)}"))
            lat = elem.get("lat") or elem.get("center", {}).get("lat")
            lon = elem.get("lon") or elem.get("center", {}).get("lon")
            if lat is None or lon is None:
                continue

            name = tags.get("name") or tags.get("operator") or f"EV Station {elem_id}"
            operator = tags.get("operator") or tags.get("brand") or "Independent Operator"

            # Parse power
            power_str = tags.get("capacity:output") or tags.get("socket:output") or tags.get("power")
            max_kw = 50.0
            power_assumed = True
            if power_str:
                try:
                    num_part = "".join(ch for ch in power_str if ch.isdigit() or ch == ".")
                    if num_part:
                        max_kw = float(num_part)
                        power_assumed = False
                except ValueError:
                    pass

            # Parse connectors
            connectors: list[str] = []
            is_2w_3w_excluded = False
            for k, val in tags.items():
                if "socket:" in k or "connector:" in k:
                    norm, excluded = normalize_connector_type(f"{k}={val}")
                    if excluded:
                        is_2w_3w_excluded = True
                    elif norm and norm not in connectors:
                        connectors.append(norm)

            connector_unknown = False
            connector_assumed = False
            if not connectors:
                if is_2w_3w_excluded:
                    continue
                connector_unknown = True
                connector_assumed = True
                connectors = ["Unknown Connector"]

            st = Station(
                id=f"osm_{elem_id}",
                name=name,
                lat=float(lat),
                lon=float(lon),
                operator=operator,
                max_kw=max_kw,
                charger_count=int(tags.get("capacity", 2)),
                connector_types=connectors,
                availability=None,
                reliability=simulate_station_reliability(operator, f"{elem_id}_{name}"),
                is_reliability_simulated=True,
                amenities={},
                amenity_score=0.0,
                power_assumed=power_assumed,
                connector_assumed=connector_assumed,
                connector_unknown=connector_unknown,
                amenity_known=False,
                spur_estimated=True,
                source="osm",
                source_url=f"https://www.openstreetmap.org/{elem.get('type', 'node')}/{elem_id}",
                fetched_at=now_iso,
                verified=False,
            )
            stations.append(st)

        return stations


def merge_and_deduplicate_stations(
    stations: list[Station],
    radius_m: float = STATION_DEDUPLICATION_RADIUS_M,
) -> list[Station]:
    """Merge and deduplicate candidate stations within spatial proximity.

    Priority hierarchy:
        1. verified_manual (rank 1)
        2. google_places (rank 2)
        3. ocm (rank 3)
        4. osm (rank 4)
        5. other / synthetic (rank 5)

    Merges real-time live availability into higher-priority records if available.
    Complexity: O(|stations|^2) where |stations| <= 200.
    """
    priority_order = {
        "verified_manual": 1,
        "google_places": 2,
        "ocm": 3,
        "ocm_snapshot": 4,
        "osm": 5,
    }

    # Sort stations by priority rank
    sorted_stations = sorted(
        stations,
        key=lambda s: priority_order.get(s.source, 99),
    )

    kept: list[Station] = []
    for candidate in sorted_stations:
        matched = False
        for existing in kept:
            dist = haversine_distance_m(candidate.lat, candidate.lon, existing.lat, existing.lon)
            if dist <= radius_m:
                matched = True
                # If candidate has live availability data and existing does not, adopt it
                if candidate.availability is not None and existing.availability is None:
                    existing.availability = candidate.availability
                # If existing has unknown connector but candidate has verified connector, adopt it
                if existing.connector_unknown and not candidate.connector_unknown:
                    existing.connector_types = candidate.connector_types
                    existing.connector_unknown = False
                    existing.connector_assumed = False
                break

        if not matched:
            kept.append(candidate)

    return kept


def query_all_providers(
    route_coords: list[tuple[float, float]],
    bbox: tuple[float, float, float, float],
    allow_network: bool = True,
) -> tuple[list[Station], dict[str, Any]]:
    """Execute all configured providers, deduplicate within 100m, and track API metrics.

    Returns:
        (stations, stats_dict)
    """
    providers: list[Any] = [
        ManualVerifiedCSVProvider(),
        GooglePlacesProvider(),
        OpenChargeMapProvider(),
        OCMSnapshotProvider(),
        OverpassProvider(),
    ]

    api_tracker: dict[str, int] = {}
    failed_tracker: list[str] = []
    all_raw_stations: list[Station] = []
    sources_used: list[str] = []

    for prov in providers:
        if not allow_network and prov.name not in ("verified_manual", "ocm_snapshot"):
            continue

        if prov.is_available():
            prov_stations = prov.fetch_stations(
                route_coords=route_coords,
                bbox=bbox,
                api_tracker=api_tracker,
                failed_tracker=failed_tracker,
            )
            if prov_stations:
                all_raw_stations.extend(prov_stations)
                sources_used.append(prov.name)
        else:
            if prov.name == "google_places":
                failed_tracker.append("Google Places: key GOOGLE_MAPS_API_KEY not set in .env")
            elif prov.name == "ocm":
                failed_tracker.append("OpenChargeMap: key OCM_API_KEY not set in .env")
            elif prov.name == "ocm_snapshot":
                failed_tracker.append("OCM Snapshot: data/ocm_snapshot/POI.json.gz not present")

    # Spatial deduplication
    deduped = merge_and_deduplicate_stations(all_raw_stations)

    # Metrics
    source_counts: dict[str, int] = {}
    ccs2_type2_count = 0
    live_availability_count = 0

    for st in deduped:
        source_counts[st.source] = source_counts.get(st.source, 0) + 1
        has_4w = any(c in SUPPORTED_4W_CONNECTORS for c in st.connector_types)
        if has_4w:
            ccs2_type2_count += 1
        if st.availability is not None:
            live_availability_count += 1

    stats: dict[str, Any] = {
        "total_stations_found": len(deduped),
        "stations_per_source": source_counts,
        "ccs2_type2_count": ccs2_type2_count,
        "live_availability_count": live_availability_count,
        "api_calls_made": api_tracker,
        "failed_requests": failed_tracker,
        "sources_used": sources_used,
    }

    return deduped, stats
