"""
Centralized configuration for Branitz Heat Decision System.
All paths are resolved relative to BRANITZ_DATA_ROOT environment variable.
"""
import os
from pathlib import Path

# Project root is 2 levels up from this file
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Data root can be overridden by environment variable
DATA_ROOT = Path(os.getenv("BRANITZ_DATA_ROOT", PROJECT_ROOT / "data"))

# Path constants
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"
RESULTS_ROOT = PROJECT_ROOT / "results"

# Individual file paths
BUILDINGS_PATH = DATA_PROCESSED / "buildings.parquet"
BUILDING_CLUSTER_MAP_PATH = DATA_PROCESSED / "building_cluster_map.parquet"
HOURLY_PROFILES_PATH = DATA_PROCESSED / "hourly_heat_profiles.parquet"
WEATHER_PATH = DATA_PROCESSED / "weather.parquet"
DESIGN_TOPN_PATH = DATA_PROCESSED / "cluster_design_topn.json"

POWER_LINES_PATH = DATA_PROCESSED / "power_lines.geojson"
POWER_SUBSTATIONS_PATH = DATA_PROCESSED / "power_substations.geojson"

def resolve_cluster_path(cluster_id: str, phase: str) -> Path:
    """Get result directory for a cluster and phase."""
    return RESULTS_ROOT / phase / cluster_id

