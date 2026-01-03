"""
Pytest configuration and fixtures for Branitz Heat Decision tests.
"""
import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path
from shapely.geometry import Polygon, Point, LineString
import json

from branitz_heat_decision.config import (
    DATA_RAW,
    DATA_PROCESSED,
    BUILDINGS_PATH,
    WEATHER_PATH,
    HOURLY_PROFILES_PATH,
    BUILDING_CLUSTER_MAP_PATH,
    DESIGN_TOPN_PATH,
    POWER_LINES_PATH,
    POWER_SUBSTATIONS_PATH,
)


def create_test_data():
    """
    Create minimal test data files for pipeline testing.
    Creates test data in data/processed/ directory.
    """
    print("Creating test data...")
    
    # Ensure directories exist
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    
    # 1. Create test buildings GeoDataFrame
    print("Creating test buildings data...")
    buildings_data = {
        'building_id': [f'B{i:04d}' for i in range(1, 11)],
        'use_type': ['residential'] * 7 + ['commercial'] * 2 + ['industrial'],
        'building_function': ['Wohngebäude'] * 7 + ['Bürogebäude'] * 2 + ['Industriegebäude'],
        'year_of_construction': [1980, 1990, 2000, 2010, 1985, 1995, 2005, 2015, 1990, 1980],
        'floor_area_m2': [100.0, 150.0, 200.0, 250.0, 120.0, 180.0, 220.0, 300.0, 400.0, 500.0],
        'annual_heat_demand_kwh_a': [15000, 18000, 12000, 10000, 16000, 14000, 11000, 25000, 35000, 40000],
    }
    
    # Create simple polygon geometries (squares)
    geometries = []
    for i in range(10):
        x = 390000 + i * 50  # UTM coordinates (EPSG:25833 approximate)
        y = 5810000 + i * 50
        geom = Polygon([
            (x, y),
            (x + 20, y),
            (x + 20, y + 20),
            (x, y + 20),
            (x, y)
        ])
        geometries.append(geom)
    
    buildings_gdf = gpd.GeoDataFrame(
        buildings_data,
        geometry=geometries,
        crs='EPSG:25833'
    )
    
    # Save buildings
    BUILDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    buildings_gdf.to_parquet(BUILDINGS_PATH, index=False)
    print(f"Created {BUILDINGS_PATH} with {len(buildings_gdf)} buildings")
    
    # 2. Create test weather data (8760 hours)
    print("Creating test weather data...")
    hours = pd.date_range('2023-01-01', periods=8760, freq='H')
    weather_data = {
        'hour': range(8760),
        'datetime': hours,
        'temperature_c': 15 + 10 * np.sin(2 * np.pi * np.arange(8760) / 8760) + np.random.normal(0, 2, 8760),
    }
    weather_df = pd.DataFrame(weather_data)
    weather_df.to_parquet(WEATHER_PATH, index=False)
    print(f"Created {WEATHER_PATH} with {len(weather_df)} hours")
    
    # 3. Create test hourly profiles (8760 hours x 10 buildings)
    print("Creating test hourly profiles...")
    profiles_data = {}
    for bid in buildings_data['building_id']:
        base_demand = buildings_data['annual_heat_demand_kwh_a'][buildings_data['building_id'].index(bid)] / 8760
        # Simple sinusoidal profile
        profiles_data[bid] = base_demand * (1 + 0.5 * np.sin(2 * np.pi * np.arange(8760) / 8760))
    
    profiles_df = pd.DataFrame(profiles_data, index=range(8760))
    profiles_df.index.name = 'hour'
    profiles_df.to_parquet(HOURLY_PROFILES_PATH)
    print(f"Created {HOURLY_PROFILES_PATH} with shape {profiles_df.shape}")
    
    # 4. Create test building-cluster map
    print("Creating test building-cluster map...")
    cluster_map_data = {
        'building_id': buildings_data['building_id'],
        'cluster_id': ['ST001_TEST_CLUSTER'] * 10,
    }
    cluster_map_df = pd.DataFrame(cluster_map_data)
    cluster_map_df.to_parquet(BUILDING_CLUSTER_MAP_PATH, index=False)
    print(f"Created {BUILDING_CLUSTER_MAP_PATH}")
    
    # 5. Create test design topn JSON
    print("Creating test design topn data...")
    design_topn = {
        'ST001_TEST_CLUSTER': {
            'design_kw': 150.0,
            'topn_hours': [0, 100, 200, 300, 400, 500, 600, 700, 800, 900]
        }
    }
    with open(DESIGN_TOPN_PATH, 'w') as f:
        json.dump(design_topn, f, indent=2)
    print(f"Created {DESIGN_TOPN_PATH}")
    
    # 6. Create test power grid data
    print("Creating test power grid data...")
    # Power lines
    line_geoms = []
    for i in range(5):
        x1 = 390000 + i * 100
        y1 = 5810000
        x2 = 390000 + (i + 1) * 100
        y2 = 5810000
        from shapely.geometry import LineString
        line_geoms.append(LineString([(x1, y1), (x2, y2)]))
    
    power_lines = gpd.GeoDataFrame(
        {
            'line_id': [f'L{i:03d}' for i in range(1, 6)],
            'voltage_kv': [0.4] * 5,
            'length_m': [100.0] * 5,
        },
        geometry=line_geoms,
        crs='EPSG:25833'
    )
    power_lines.to_file(POWER_LINES_PATH, driver='GeoJSON')
    print(f"Created {POWER_LINES_PATH}")
    
    # Power substations
    substation_geoms = [Point(390000, 5810000), Point(390400, 5810000)]
    power_substations = gpd.GeoDataFrame(
        {
            'substation_id': ['S001', 'S002'],
            'capacity_kva': [630.0, 630.0],
        },
        geometry=substation_geoms,
        crs='EPSG:25833'
    )
    power_substations.to_file(POWER_SUBSTATIONS_PATH, driver='GeoJSON')
    print(f"Created {POWER_SUBSTATIONS_PATH}")
    
    print("Test data creation complete!")


if __name__ == "__main__":
    create_test_data()

