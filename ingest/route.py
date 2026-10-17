"""OSRM routing client with configurable base URL, disk caching, and spur detour calculations."""

from __future__ import annotations

import math
import os
from typing import Any

import requests

from ingest.cache import DiskCache

DEFAULT_OSRM_URL: str = "http://router.project-osrm.org"


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two coordinates in meters.

    Complexity: O(1).
    """
    R = 6_371_000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


class OSRMClient:
    """Client for OSRM routing service supporting live API and local self-hosted instances."""

    def __init__(
        self,
        base_url: str | None = None,
        cache: DiskCache | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("OSRM_BASE_URL", DEFAULT_OSRM_URL)
        ).rstrip("/")
        self.cache = cache or DiskCache("osrm")

    def get_route(
        self,
        start_coord: tuple[float, float],  # (lat, lon)
        end_coord: tuple[float, float],    # (lat, lon)
        alternatives: bool = True,
        allow_network: bool = True,
    ) -> dict[str, Any]:
        """Fetch primary driving route and alternatives from OSRM.

        Args:
            start_coord: (lat, lon) of source.
            end_coord: (lat, lon) of destination.
            alternatives: Request alternative paths.
            allow_network: Allow live HTTP request if not cached.

        Returns:
            Dictionary with distance_m, duration_s, and coordinates [(lat, lon), ...].
        """
        lat1, lon1 = start_coord
        lat2, lon2 = end_coord
        cache_key = f"{lat1:.5f},{lon1:.5f}_{lat2:.5f},{lon2:.5f}_alt={alternatives}"

        cached = self.cache.get(cache_key)
        if cached:
            return cached

        if not allow_network:
            raise ValueError(f"OSRM route for {cache_key} not in cache and network is disabled.")

        url = (
            f"{self.base_url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
            f"?overview=full&geometries=geojson&alternatives={'true' if alternatives else 'false'}"
        )

        headers = {"User-Agent": "RouteEV-TripPlanner/1.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError(f"OSRM returned error code: {data.get('code')}")

        primary_route = data["routes"][0]
        # OSRM geojson coordinates are [lon, lat]
        coords = [(pt[1], pt[0]) for pt in primary_route["geometry"]["coordinates"]]

        result = {
            "distance_m": primary_route["distance"],
            "duration_s": primary_route["duration"],
            "coordinates": coords,
            "alternatives_count": len(data["routes"]) - 1,
        }

        self.cache.set(cache_key, result)
        return result


def compute_spur_detour(
    main_coords: list[tuple[float, float]],
    station_lat: float,
    station_lon: float,
    assumed_spur_speed_kmh: float = 35.0,
) -> tuple[float, float, int]:
    """Compute spur detour distance and duration from corridor polyline to a station.

    Finds the closest node on the main highway polyline, computes spur round-trip
    distance (2 * straight-line * tortuosity 1.25), and converts to seconds.

    Complexity:
        Time: O(|main_coords|)
        Space: O(1)

    Args:
        main_coords: Polyline points along the main route [(lat, lon), ...].
        station_lat: Latitude of charging station.
        station_lon: Longitude of charging station.
        assumed_spur_speed_kmh: Speed for local access roads (default 35 km/h).

    Returns:
        Tuple of (detour_distance_m, detour_time_s, closest_node_idx).
    """
    min_dist = float("inf")
    closest_idx = 0

    for idx, (lat, lon) in enumerate(main_coords):
        dist = haversine_distance_m(lat, lon, station_lat, station_lon)
        if dist < min_dist:
            min_dist = dist
            closest_idx = idx

    # Apply 1.25 road tortuosity factor for urban/local spur access road
    detour_dist_one_way_m = min_dist * 1.25
    detour_dist_round_trip_m = 2.0 * detour_dist_one_way_m

    speed_mps = (assumed_spur_speed_kmh * 1000.0) / 3600.0
    detour_time_s = detour_dist_round_trip_m / speed_mps

    return detour_dist_round_trip_m, detour_time_s, closest_idx
