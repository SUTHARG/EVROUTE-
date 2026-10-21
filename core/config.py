"""Central configuration for Route.ev EV trip planning system.

Loads environment variables via python-dotenv without ever exposing API keys in logs or UI.
Controls demo-mode parameters, default vehicle ranges, connector filtering, and caching TTLs.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load root .env file if present
_env_path = Path(__file__).resolve().parents[1] / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

# ==============================================================================
# 1. VEHICLE RANGE CONFIGURATION (DEMO BUILD)
# ==============================================================================
# Default flat-road plannable range in kilometers for all vehicle profiles in demo mode.
DEFAULT_RANGE_KM: float = 250.0

# When False (default for demo), each vehicle's consumption is calibrated so a full usable
# battery delivers exactly DEFAULT_RANGE_KM (250 km) on flat highway cruise.
# When True, each car uses its manufacturer specific consumption / real_range_km.
USE_CAR_SPECIFIC_RANGE: bool = os.getenv("USE_CAR_SPECIFIC_RANGE", "false").lower() in ("true", "1", "yes")

# ==============================================================================
# 2. STATION PROVIDER API KEYS & LIMITS
# ==============================================================================
def get_google_maps_api_key() -> str | None:
    load_dotenv(dotenv_path=_env_path, override=True)
    return os.getenv("GOOGLE_MAPS_API_KEY")


def get_ocm_api_key() -> str | None:
    load_dotenv(dotenv_path=_env_path, override=True)
    return os.getenv("OCM_API_KEY")


# Google Maps / Places API (New) key
GOOGLE_MAPS_API_KEY: str | None = get_google_maps_api_key()

# Open Charge Map API v3 key
OCM_API_KEY: str | None = get_ocm_api_key()


def __getattr__(name: str):
    if name == "OCM_API_KEY":
        return get_ocm_api_key()
    if name == "GOOGLE_MAPS_API_KEY":
        return get_google_maps_api_key()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Maximum number of Google Places Text Search requests along any single route
# (protects quotas and controls API cost while sampling every ~20 km)
MAX_GOOGLE_PLACES_PER_ROUTE: int = 15

# Radius in meters for Google Places search along route sample points
GOOGLE_PLACES_SAMPLE_RADIUS_M: float = 9000.0

# Sample interval along route in meters (~20 km)
GOOGLE_PLACES_SAMPLE_INTERVAL_M: float = 20000.0

# Maximum number of Open Charge Map API requests along any single route
MAX_OCM_CALLS_PER_ROUTE: int = 10

# Radius in kilometers for Open Charge Map search along route sample points
OCM_SAMPLE_RADIUS_KM: float = 15.0

# Caching TTLs
CACHE_TTL_STATIC_HOURS: int = 24
CACHE_TTL_AVAILABILITY_MINUTES: int = 5


# ==============================================================================
# 3. 4-WHEELER CONNECTOR FILTERING STANDARDS
# ==============================================================================
# Supported DC and AC standards for passenger 4-wheeler EVs in India
SUPPORTED_4W_CONNECTORS: list[str] = [
    "CCS2",
    "Type 2 (AC)",
    "CHAdeMO",
]

# Excluded connector standards primarily used for electric 2-wheelers and 3-wheelers
EXCLUDED_2W_3W_CONNECTORS: list[str] = [
    "Bharat AC-001",
    "Bharat DC-001",
    "15A 3-Pin",
    "Wall BS 546",
    "IEC 60309",
    "GB/T",
]

# When False, stations with unknown connector types are displayed on map as
# "connector unknown" but excluded from planner routing graph.
ALLOW_UNKNOWN_CONNECTORS: bool = os.getenv("ALLOW_UNKNOWN_CONNECTORS", "false").lower() in ("true", "1", "yes")

# Deduplication radius between station providers in meters
STATION_DEDUPLICATION_RADIUS_M: float = 100.0

# Verified stations CSV dataset path
VERIFIED_STATIONS_CSV_PATH: Path = Path("data/stations/verified_stations.csv")
