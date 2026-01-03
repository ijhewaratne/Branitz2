"""
Tests for data preparation pipeline.
"""
import pytest
import pandas as pd
import geopandas as gpd
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from branitz_heat_decision.config import (
    BUILDINGS_PATH,
    WEATHER_PATH,
    HOURLY_PROFILES_PATH,
    BUILDING_CLUSTER_MAP_PATH,
    DESIGN_TOPN_PATH,
)
from branitz_heat_decision.data.loader import load_buildings_geojson, DataValidationError


@pytest.mark.data
def test_buildings_file_exists():
    """Test that buildings.parquet file exists and can be loaded."""
    assert BUILDINGS_PATH.exists(), f"Buildings file not found: {BUILDINGS_PATH}"
    buildings = gpd.read_parquet(BUILDINGS_PATH)
    assert len(buildings) > 0, "Buildings file is empty"
    assert 'building_id' in buildings.columns, "Missing building_id column"
    assert buildings.crs is not None, "Missing CRS"


@pytest.mark.data
def test_weather_file_exists():
    """Test that weather.parquet file exists and has correct structure."""
    assert WEATHER_PATH.exists(), f"Weather file not found: {WEATHER_PATH}"
    weather = pd.read_parquet(WEATHER_PATH)
    assert len(weather) == 8760, f"Weather data should have 8760 hours, got {len(weather)}"
    assert 'temperature_c' in weather.columns, "Missing temperature_c column"


@pytest.mark.data
def test_hourly_profiles_file_exists():
    """Test that hourly profiles file exists and has correct structure."""
    assert HOURLY_PROFILES_PATH.exists(), f"Hourly profiles file not found: {HOURLY_PROFILES_PATH}"
    profiles = pd.read_parquet(HOURLY_PROFILES_PATH)
    assert len(profiles) == 8760, f"Profiles should have 8760 hours, got {len(profiles)}"
    assert len(profiles.columns) > 0, "Profiles should have at least one building"


@pytest.mark.data
def test_building_cluster_map_exists():
    """Test that building-cluster map file exists."""
    assert BUILDING_CLUSTER_MAP_PATH.exists(), f"Building-cluster map file not found: {BUILDING_CLUSTER_MAP_PATH}"
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    assert 'building_id' in cluster_map.columns, "Missing building_id column"
    assert 'cluster_id' in cluster_map.columns, "Missing cluster_id column"


@pytest.mark.data
def test_design_topn_file_exists():
    """Test that design topn JSON file exists."""
    assert DESIGN_TOPN_PATH.exists(), f"Design topn file not found: {DESIGN_TOPN_PATH}"
    import json
    with open(DESIGN_TOPN_PATH, 'r') as f:
        design_topn = json.load(f)
    assert isinstance(design_topn, dict), "Design topn should be a dictionary"
    assert len(design_topn) > 0, "Design topn should contain at least one cluster"

