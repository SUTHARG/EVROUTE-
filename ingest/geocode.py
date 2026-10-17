"""Geocoding module using OpenStreetMap Nominatim with rate-limiting, disk cache, and offline fallback."""

from __future__ import annotations

import time
from typing import Any

import requests

from ingest.cache import DiskCache

NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
USER_AGENT: str = "RouteEV-TripPlanner/1.0 (academic-dsa-project)"
RATE_LIMIT_DELAY_S: float = 1.0

# Offline fallback coordinates for standard Indian cities to support hermetic execution
FALLBACK_COORDINATES: dict[str, tuple[float, float]] = {
    "mumbai": (18.9388, 72.8354),
    "pune": (18.5204, 73.8567),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867),
    "chennai": (13.0827, 80.2707),
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "lonavala": (18.7546, 73.4062),
    "khandala": (18.7618, 73.3752),
    "panvel": (18.9894, 73.1175),
    "thane": (19.2183, 72.9781),
}

_last_request_time: float = 0.0


def geocode(
    place_name: str,
    allow_network: bool = True,
    cache: DiskCache | None = None,
) -> tuple[float, float, str]:
    """Geocode a place name into (lat, lon, display_name).

    Checks disk cache first, then falls back to offline dictionary if network
    is disabled or if Nominatim fails/rate limits.

    Complexity:
        O(1) with cache/offline dictionary, or network round-trip.

    Args:
        place_name: Location query string (e.g. "Mumbai", "Pune").
        allow_network: Whether network requests to Nominatim are permitted.
        cache: Optional DiskCache instance.

    Returns:
        Tuple of (latitude, longitude, display_name).

    Raises:
        ValueError: If location cannot be geocoded.
    """
    global _last_request_time
    clean_query = place_name.strip()
    cache_key = clean_query.lower()
    disk_cache = cache or DiskCache("geocode")

    # 1. Check disk cache
    cached: dict[str, Any] | None = disk_cache.get(cache_key)
    if cached:
        return cached["lat"], cached["lon"], cached["display_name"]

    # 2. Check offline dictionary
    if cache_key in FALLBACK_COORDINATES:
        lat, lon = FALLBACK_COORDINATES[cache_key]
        display_name = f"{clean_query.title()}, India (Offline Fallback)"
        disk_cache.set(cache_key, {"lat": lat, "lon": lon, "display_name": display_name})
        return lat, lon, display_name

    if not allow_network:
        raise ValueError(
            f"Location '{place_name}' not found in offline dictionary and network is disabled."
        )

    # 3. Rate-limited Nominatim query
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_DELAY_S:
        time.sleep(RATE_LIMIT_DELAY_S - elapsed)

    headers = {"User-Agent": USER_AGENT}
    params = {"q": clean_query, "format": "json", "limit": 1}

    try:
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        _last_request_time = time.time()
        response.raise_for_status()
        data = response.json()
        if not data:
            raise ValueError(f"Nominatim could not find location: '{place_name}'")

        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])
        display_name = str(data[0].get("display_name", clean_query))

        disk_cache.set(cache_key, {"lat": lat, "lon": lon, "display_name": display_name})
        return lat, lon, display_name
    except Exception as exc:
        # If network failed, check if we have a substring match in offline coordinates
        for known_city, (c_lat, c_lon) in FALLBACK_COORDINATES.items():
            if known_city in cache_key:
                display = f"{known_city.title()}, India (Offline Fallback)"
                return c_lat, c_lon, display
        raise ValueError(f"Geocoding failed for '{place_name}': {exc}") from exc
