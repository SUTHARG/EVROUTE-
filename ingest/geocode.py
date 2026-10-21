"""Geocoding module using OpenStreetMap Nominatim with rate-limiting, disk cache, and offline fallback."""

from __future__ import annotations

import time
from typing import Any

import requests

from ingest.cache import DiskCache

NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
USER_AGENT: str = "RouteEV-TripPlanner/1.0 (academic-dsa-project)"
RATE_LIMIT_DELAY_S: float = 1.0

# Offline fallback coordinates for standard Indian cities to support hermetic execution and tests
FALLBACK_COORDINATES: dict[str, tuple[float, float, str]] = {
    "mumbai": (18.9388, 72.8354, "Mumbai, Maharashtra, India"),
    "pune": (18.5204, 73.8567, "Pune, Maharashtra, India"),
    "delhi": (28.6139, 77.2090, "Delhi, National Capital Territory of Delhi, India"),
    "new delhi": (28.6139, 77.2090, "New Delhi, Delhi, India"),
    "agra": (27.1767, 78.0081, "Agra, Uttar Pradesh, India"),
    "bengaluru": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "bangalore": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "hyderabad": (17.3850, 78.4867, "Hyderabad, Telangana, India"),
    "chennai": (13.0827, 80.2707, "Chennai, Tamil Nadu, India"),
    "jaipur": (26.9124, 75.7873, "Jaipur, Rajasthan, India"),
    "ahmedabad": (23.0225, 72.5714, "Ahmedabad, Gujarat, India"),
    "chandigarh": (30.7333, 76.7794, "Chandigarh, India"),
    "lucknow": (26.8467, 80.9462, "Lucknow, Uttar Pradesh, India"),
    "lonavala": (18.7546, 73.4062, "Lonavala, Pune, Maharashtra, India"),
    "khandala": (18.7618, 73.3752, "Khandala, Pune, Maharashtra, India"),
    "panvel": (18.9894, 73.1175, "Panvel, Raigad, Maharashtra, India"),
    "thane": (19.2183, 72.9781, "Thane, Maharashtra, India"),
    "navi mumbai": (19.0330, 73.0297, "Navi Mumbai, Maharashtra, India"),
}

_last_request_time: float = 0.0


def search_geocode(
    query: str,
    limit: int = 5,
    countrycodes: str = "in",
    allow_network: bool = True,
    cache: DiskCache | None = None,
) -> list[dict[str, Any]]:
    """Search for location candidates using OpenStreetMap Nominatim or offline fallbacks.

    Rate-limited to 1 request/second and cached to disk.

    Args:
        query: Search string entered by user.
        limit: Maximum number of candidates to return (up to 5).
        countrycodes: Country code filter (default 'in').
        allow_network: Allow live HTTP requests if not cached.
        cache: Optional DiskCache instance.

    Returns:
        List of candidate dictionaries: [{"label": ..., "lat": ..., "lon": ...}, ...]
    """
    global _last_request_time
    clean_query = query.strip()
    if not clean_query:
        return []

    cache_key = f"search_{clean_query.lower()}_lim={limit}_cc={countrycodes}"
    disk_cache = cache or DiskCache("geocode_search")

    # 1. Check disk cache
    cached = disk_cache.get(cache_key)
    if cached and isinstance(cached, list):
        return cached

    # 2. Check offline candidates if network is disabled
    offline_candidates: list[dict[str, Any]] = []
    q_lower = clean_query.lower()
    for name, (lat, lon, label) in FALLBACK_COORDINATES.items():
        if q_lower in name or name in q_lower:
            offline_candidates.append({"label": label, "lat": lat, "lon": lon})
            if len(offline_candidates) >= limit:
                break

    if not allow_network:
        return offline_candidates

    # 3. Rate-limited Nominatim query
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_DELAY_S:
        time.sleep(RATE_LIMIT_DELAY_S - elapsed)

    headers = {"User-Agent": USER_AGENT}
    params: dict[str, Any] = {
        "q": clean_query,
        "format": "json",
        "limit": limit,
    }
    if countrycodes:
        params["countrycodes"] = countrycodes

    try:
        response = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        _last_request_time = time.time()
        response.raise_for_status()
        data = response.json()
        results: list[dict[str, Any]] = []
        if isinstance(data, list):
            for item in data[:limit]:
                results.append({
                    "label": item.get("display_name", clean_query),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                })

        if results:
            disk_cache.set(cache_key, results)
            return results
        # If no results from Nominatim, fallback to offline candidates if any
        return offline_candidates
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Nominatim search failed ({exc}), using offline candidates.")
        return offline_candidates


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
    clean_query = place_name.strip()
    candidates = search_geocode(clean_query, limit=1, allow_network=allow_network, cache=cache)
    if candidates:
        first = candidates[0]
        return first["lat"], first["lon"], first["label"]

    raise ValueError(f"Geocoding failed for '{place_name}': location not found.")

