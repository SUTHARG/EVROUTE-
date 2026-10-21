"""Open Charge Map snapshot provider for offline/local POI.json.gz ingestion.

Reads local POI.json.gz (from https://github.com/openchargemap/ocm-data) in data/ocm_snapshot/,
filters to India, indexes spatially with a grid index for fast querying along highway corridors,
and normalizes records into the standard Route.ev Station model with 4-wheeler connector filtering.

Attribution: Data courtesy of Open Charge Map - https://openchargemap.org (CC BY 4.0).
Each POI may specify an individual DataProvider and specific license.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import EXCLUDED_2W_3W_CONNECTORS
from core.models import Station, StationAvailability

logger = logging.getLogger(__name__)

OCM_SNAPSHOT_DIR = Path("data/ocm_snapshot")


def get_ocm_snapshot_file() -> Path | None:
    """Find local OCM snapshot file in data/ocm_snapshot/ if available."""
    if not OCM_SNAPSHOT_DIR.exists():
        return None
    for candidate in [
        OCM_SNAPSHOT_DIR / "POI.json.gz",
        OCM_SNAPSHOT_DIR / "poi.json.gz",
        OCM_SNAPSHOT_DIR / "POI.json",
        OCM_SNAPSHOT_DIR / "poi.json",
    ]:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    # Check any .json.gz or .json in that dir
    for f in OCM_SNAPSHOT_DIR.glob("*.json.gz"):
        if f.stat().st_size > 0:
            return f
    for f in OCM_SNAPSHOT_DIR.glob("*.json"):
        if f.stat().st_size > 0:
            return f
    return None


def clean_station_name(raw_name: str | None) -> str:
    """Strip highway milestone tags such as '(KM 98)' or '(KM 36)' from station names."""
    if not raw_name:
        return "EV Charging Station"
    return re.sub(r"\s*\((?:KM|km)\s*\d+\)", "", raw_name, flags=re.IGNORECASE).strip()


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
    if any(k in raw_lower for k in ["ccs2", "combo 2", "combo_2", "type 2 combo", "ccs_combo_2"]):
        return "CCS2", False
    if any(k in raw_lower for k in ["type 2", "type2", "iec 62196-2"]):
        return "Type 2 (AC)", False
    if "chademo" in raw_lower:
        return "CHAdeMO", False

    return None, False


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two points in km."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def min_dist_to_route_km(lat: float, lon: float, route_coords: list[tuple[float, float]]) -> float:
    """Compute approximate minimum distance from point to sampled route points."""
    if not route_coords:
        return 0.0
    # Downsample if route_coords has thousands of points for speed
    step = max(1, len(route_coords) // 200)
    sampled = route_coords[::step]
    min_d = float("inf")
    for r_lat, r_lon in sampled:
        d = haversine_km(lat, lon, r_lat, r_lon)
        if d < min_d:
            min_d = d
            if min_d < 0.5:
                break
    return min_d


class OCMSnapshotProvider:
    """Loads Open Charge Map stations from local POI.json.gz data export."""

    _cached_file_path: Path | None = None
    _cached_file_mtime: float = 0.0
    _cached_india_records: list[dict[str, Any]] | None = None
    _spatial_grid: dict[tuple[int, int], list[dict[str, Any]]] | None = None

    def __init__(self, snapshot_path: Path | None = None, enabled: bool = False) -> None:
        self.snapshot_path = snapshot_path or get_ocm_snapshot_file()
        self.enabled = enabled

    @property
    def name(self) -> str:
        return "ocm_snapshot"

    def is_available(self) -> bool:
        """Check if provider is enabled and local snapshot file exists and is readable."""
        if not self.enabled:
            return False
        f = self.snapshot_path or get_ocm_snapshot_file()
        return bool(f and f.exists() and f.stat().st_size > 0)


    def _ensure_loaded(self) -> None:
        """Load and index India records from snapshot file once."""
        target_file = self.snapshot_path or get_ocm_snapshot_file()
        if not target_file or not target_file.exists():
            OCMSnapshotProvider._cached_india_records = []
            OCMSnapshotProvider._spatial_grid = {}
            return

        mtime = target_file.stat().st_mtime
        if (
            OCMSnapshotProvider._cached_india_records is not None
            and OCMSnapshotProvider._cached_file_path == target_file
            and OCMSnapshotProvider._cached_file_mtime == mtime
        ):
            return

        logger.info("Loading OCM snapshot from %s...", target_file)
        records: list[dict[str, Any]] = []

        try:
            if target_file.name.endswith(".gz"):
                with gzip.open(target_file, "rt", encoding="utf-8") as f:
                    raw_data = json.load(f)
            else:
                with open(target_file, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)

            if isinstance(raw_data, list):
                poi_list = raw_data
            elif isinstance(raw_data, dict):
                poi_list = raw_data.get("POI", raw_data.get("data", []))
            else:
                poi_list = []

            grid: dict[tuple[int, int], list[dict[str, Any]]] = {}

            for poi in poi_list:
                addr = poi.get("AddressInfo", {})
                country_obj = addr.get("Country") or {}
                iso_code = (
                    addr.get("ISOCode")
                    or (country_obj.get("ISOCode") if isinstance(country_obj, dict) else "")
                    or ""
                ).strip().upper()
                lat = addr.get("Latitude")
                lon = addr.get("Longitude")

                if lat is None or lon is None:
                    continue
                try:
                    lat_f, lon_f = float(lat), float(lon)
                except (ValueError, TypeError):
                    continue

                # Filter strictly by ISO country code ("IN")
                if iso_code != "IN":
                    continue

                records.append(poi)

                # Spatial grid indexing: 0.1 degree resolution (~11 km grid cells)
                cell = (int(lat_f * 10), int(lon_f * 10))
                grid.setdefault(cell, []).append(poi)

            if records:
                first_poi = records[0]
                addr_keys = list(first_poi.get("AddressInfo", {}).keys()) if isinstance(first_poi.get("AddressInfo"), dict) else []
                dp_keys = list(first_poi.get("DataProvider", {}).keys()) if isinstance(first_poi.get("DataProvider"), dict) else []
                conns = first_poi.get("Connections")
                conn_keys = list(conns[0].keys()) if isinstance(conns, list) and conns and isinstance(conns[0], dict) else []
                print(
                    f"\n[OCM Snapshot] Actual keys of first India record:\n"
                    f"  - Top-level keys: {list(first_poi.keys())}\n"
                    f"  - AddressInfo keys: {addr_keys}\n"
                    f"  - DataProvider keys: {dp_keys}\n"
                    f"  - Connections[0] keys: {conn_keys}\n"
                )
                logger.info("OCM first India record keys: %s", list(first_poi.keys()))

                # If test fixture does not exist, save the first 5 real India records
                fixture_path = Path("tests/fixtures/ocm_india_sample.json")
                if not fixture_path.exists():
                    try:
                        fixture_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(fixture_path, "w", encoding="utf-8") as f_samp:
                            json.dump(records[:5], f_samp, indent=2)
                        print(f"INFO:     Saved 5 real India records to test fixture at {fixture_path}")
                    except OSError as e:
                        logger.warning("Could not write test fixture: %s", e)

            OCMSnapshotProvider._cached_india_records = records
            OCMSnapshotProvider._spatial_grid = grid
            OCMSnapshotProvider._cached_file_path = target_file
            OCMSnapshotProvider._cached_file_mtime = mtime
            logger.info("Loaded %d India stations from OCM snapshot into spatial grid", len(records))

        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.error("Failed to load OCM snapshot file %s: %s", target_file, exc)
            OCMSnapshotProvider._cached_india_records = []
            OCMSnapshotProvider._spatial_grid = {}

    def fetch_stations(
        self,
        route_coords: list[tuple[float, float]],
        bbox: tuple[float, float, float, float],
        api_tracker: dict[str, int],
        failed_tracker: list[str],
        max_corridor_dist_km: float = 5.0,
    ) -> list[Station]:
        """Fetch and normalize stations within max_corridor_dist_km of route geometry."""
        target_file = self.snapshot_path or get_ocm_snapshot_file()
        if not target_file or not target_file.exists():
            return []

        self._ensure_loaded()
        if not OCMSnapshotProvider._spatial_grid:
            return []

        # Determine snapshot date and ISO fetched_at from file mtime
        mtime = target_file.stat().st_mtime
        file_dt = datetime.fromtimestamp(mtime, tz=UTC)
        fetched_iso = file_dt.isoformat()
        checked_on = file_dt.strftime("%Y-%m-%d")

        # Collect grid cells along the route corridor
        cells_to_check: set[tuple[int, int]] = set()
        for r_lat, r_lon in route_coords:
            base_r = int(r_lat * 10)
            base_c = int(r_lon * 10)
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    cells_to_check.add((base_r + dr, base_c + dc))

        candidate_pois: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for cell in cells_to_check:
            for poi in OCMSnapshotProvider._spatial_grid.get(cell, []):
                pid = poi.get("ID")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    candidate_pois.append(poi)

        stations: list[Station] = []
        for poi in candidate_pois:
            addr = poi.get("AddressInfo", {})
            try:
                lat = float(addr["Latitude"])
                lon = float(addr["Longitude"])
            except (KeyError, ValueError, TypeError):
                continue

            # Verify corridor distance (within ~5 km)
            d_km = min_dist_to_route_km(lat, lon, route_coords)
            if d_km > max_corridor_dist_km:
                continue

            poi_id = poi.get("ID", 0)
            raw_title = addr.get("Title") or f"OCM Charger {poi_id}"
            clean_name = clean_station_name(raw_title)

            operator_info = poi.get("OperatorInfo") or {}
            operator_name = operator_info.get("Title") or "Unknown Operator"

            # Parse Connections
            connections = poi.get("Connections", []) or []
            max_kw = 0.0
            normalized_connectors: list[str] = []
            is_excluded = False
            power_assumed = False

            for conn in connections:
                if not isinstance(conn, dict):
                    continue
                p_kw = conn.get("PowerKW")
                if p_kw is not None:
                    try:
                        p_val = float(p_kw)
                        max_kw = max(max_kw, p_val)
                    except (ValueError, TypeError):
                        pass

                conn_type = conn.get("ConnectionType") or {}
                type_title = conn_type.get("Title") or ""
                norm, excl = normalize_connector_type(type_title)
                if excl:
                    is_excluded = True
                elif norm and norm not in normalized_connectors:
                    normalized_connectors.append(norm)

            if max_kw <= 0.0:
                max_kw = 50.0
                power_assumed = True

            connector_unknown = False
            if not normalized_connectors:
                if is_excluded:
                    continue
                connector_unknown = True
                normalized_connectors = ["Unknown Connector"]

            num_points = poi.get("NumberOfPoints")
            charger_count = int(num_points) if num_points and int(num_points) > 0 else None

            # Operational status
            status_type = poi.get("StatusType") or {}
            is_operational = status_type.get("IsOperational", True)
            availability = None
            if status_type:
                total_c = charger_count or 1
                avail_c = total_c if is_operational else 0
                availability = StationAvailability(
                    available=avail_c,
                    total=total_c,
                    out_of_service=0 if is_operational else total_c,
                    last_updated=poi.get("DateLastStatusUpdate"),
                )

            dp_obj = poi.get("DataProvider") or {}
            dp_name = dp_obj.get("Title") if isinstance(dp_obj, dict) else None
            dp_license = dp_obj.get("License") if isinstance(dp_obj, dict) else None

            st = Station(
                id=f"ocm_snap_{poi_id}",
                name=clean_name,
                lat=lat,
                lon=lon,
                operator=operator_name,
                max_kw=max_kw,
                charger_count=charger_count or 1,
                connector_types=normalized_connectors,
                availability=availability,
                reliability=0.85,
                is_reliability_simulated=True,
                amenities={"restaurant": 1, "cafe": 1, "toilets": 1, "fuel": 1},
                amenity_score=0.75,
                power_assumed=power_assumed,
                connector_assumed=False,
                connector_unknown=connector_unknown,
                amenity_known=False,
                spur_estimated=True,
                source="ocm_snapshot",
                source_url=f"https://openchargemap.org/site/poi/details/{poi_id}",
                fetched_at=fetched_iso,
                verified=False,
                checked_on=checked_on,
                data_provider_name=dp_name,
                data_provider_license=dp_license,
            )
            stations.append(st)

        api_tracker["ocm_snapshot_stations"] = len(stations)
        logger.info("OCMSnapshotProvider: Extracted %d stations along corridor", len(stations))
        return stations
