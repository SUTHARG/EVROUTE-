"""OSRM routing client with configurable base URL, disk caching, and spur detour calculations."""

from __future__ import annotations

import os
from typing import Any

import requests

from core.geo import haversine_distance_m
from ingest.cache import DiskCache

DEFAULT_OSRM_URL: str = "http://router.project-osrm.org"


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
        """Fetch the primary driving route, preserving the legacy single-route API."""
        routes = self.get_routes(
            start_coord,
            end_coord,
            max_routes=2 if alternatives else 1,
            allow_network=allow_network,
        )
        if not routes:
            raise ValueError("OSRM returned no routes.")
        result = dict(routes[0])
        result["alternatives_count"] = len(routes) - 1
        return result

    def get_routes(
        self,
        start_coord: tuple[float, float],
        end_coord: tuple[float, float],
        max_routes: int = 2,
        allow_network: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch up to ``max_routes`` distinct driving routes from OSRM.

        Args:
            start_coord: (lat, lon) of source.
            end_coord: (lat, lon) of destination.
            max_routes: Maximum route candidates to return (1-3).
            allow_network: Allow live HTTP request if not cached.

        Returns:
            Route dictionaries with distance_m, duration_s, and coordinates [(lat, lon), ...].
        """
        if not 1 <= max_routes <= 3:
            raise ValueError("max_routes must be between 1 and 3.")

        lat1, lon1 = start_coord
        lat2, lon2 = end_coord
        cache_key = f"{lat1:.5f},{lon1:.5f}_{lat2:.5f},{lon2:.5f}_routes={max_routes}_v2"

        cached = self.cache.get(cache_key)
        if cached:
            return cached[:max_routes]

        if not allow_network:
            raise ValueError(f"OSRM route for {cache_key} not in cache and network is disabled.")

        url = (
            f"{self.base_url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
            f"?overview=full&geometries=geojson&alternatives={'true' if max_routes > 1 else 'false'}"
        )

        headers = {"User-Agent": "RouteEV-TripPlanner/1.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError(f"OSRM returned error code: {data.get('code')}")

        results: list[dict[str, Any]] = []
        for route_index, route in enumerate(data["routes"][:max_routes]):
            # OSRM geojson coordinates are [lon, lat].
            coords = [(pt[1], pt[0]) for pt in route["geometry"]["coordinates"]]
            results.append({
                "distance_m": route["distance"],
                "duration_s": route["duration"],
                "coordinates": coords,
                "route_index": route_index,
            })

        self.cache.set(cache_key, results)
        return results


def compute_spur_detour(
    main_coords: list[tuple[float, float]],
    station_lat: float,
    station_lon: float,
    assumed_spur_speed_kmh: float = 35.0,
) -> tuple[float, float, int]:
    """Compute spur detour distance and duration from corridor polyline to a station.

    NOTE [APPROXIMATION]: This function is an offline geometric approximation that
    estimates spur detour using great-circle distance scaled by a 1.25 road tortuosity
    factor. For exact navigation in live routing, use compute_live_osrm_spur.

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


def compute_live_osrm_spur(
    client: OSRMClient,
    highway_coord: tuple[float, float],
    station_coord: tuple[float, float],
    allow_network: bool = True,
) -> tuple[float, float]:
    """Compute exact spur detour distance and duration via live cached OSRM route query.

    Queries OSRM for highway_node -> station -> highway_node round-trip path.

    Complexity:
        O(1) with cache, or 1 OSRM HTTP round-trip.

    Returns:
        Tuple of (round_trip_distance_m, round_trip_duration_s).
    """
    try:
        route_data = client.get_route(
            start_coord=highway_coord,
            end_coord=station_coord,
            alternatives=False,
            allow_network=allow_network,
        )
        # Round trip is approximately double the one-way spur
        return route_data["distance_m"] * 2.0, route_data["duration_s"] * 2.0
    except (requests.RequestException, ValueError, KeyError):
        # Fallback to geometric approximation if OSRM is unreachable
        dist_m = haversine_distance_m(
            highway_coord[0], highway_coord[1], station_coord[0], station_coord[1]
        ) * 2.5
        time_s = dist_m / (35.0 / 3.6)
        return dist_m, time_s
