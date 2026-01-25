"""
Data preparation module.
Handles loading, cleaning, and preprocessing of raw data.
"""

from pathlib import Path
from typing import Dict, Any

import json
import pandas as pd
import geopandas as gpd

# Import centralized path configuration
from branitz_ai.config.paths import (
    get_data_processed,
    DATA_PROCESSED,
    BUILDINGS_PATH,
    BUILDING_CLUSTER_MAP_PATH,
    WEATHER_CSV_PATH,
    WEATHER_PARQUET_PATH,
    HOURLY_PROFILES_PATH,
    DESIGN_TOPN_PATH,
    POWER_LINES_PATH,
    POWER_SUBSTATIONS_PATH,
    POWER_GENERATORS_PATH,
    POWER_PLANTS_PATH
)

# Use centralized DATA_PROCESSED path
# This resolves to: repo-level data/processed/ (if exists) or package-local branitz_ai/data/processed/
# Can be overridden by BRANITZ_DATA_ROOT environment variable
DATA_PROCESSED = get_data_processed()


def load_buildings() -> gpd.GeoDataFrame:
    """
    Load canonical buildings table.
    
    Returns:
        GeoDataFrame with one row per building (1,880 buildings)
        Contains building_id, geometry, and all building attributes.
    
    Raises:
        FileNotFoundError: If buildings.parquet is not found
        AssertionError: If required columns are missing
    """
    path = DATA_PROCESSED / "buildings.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Buildings file not found: {path}")
    
    gdf = gpd.read_parquet(path)
    
    # Sanity checks
    assert "building_id" in gdf.columns, "buildings.parquet must contain 'building_id' column"
    assert "geometry" in gdf.columns, "buildings.parquet must contain 'geometry' column"
    assert len(gdf) > 0, "buildings.parquet is empty"
    
    return gdf


def filter_residential_buildings(buildings_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Filter buildings to only residential buildings.
    
    A building is considered residential if:
    - building_type == 'sfh' (single-family house), OR
    - building_function contains 'Wohn' (case-insensitive, German for residential)
    
    Args:
        buildings_df: GeoDataFrame with building data
        
    Returns:
        Filtered GeoDataFrame with only residential buildings
        
    Examples:
        >>> buildings = load_buildings()
        >>> residential = filter_residential_buildings(buildings)
        >>> print(f"Residential: {len(residential)}, Total: {len(buildings)}")
    """
    if len(buildings_df) == 0:
        return buildings_df.copy()
    
    # Build filter conditions
    conditions = []
    
    # Condition 1: building_type == 'sfh'
    if 'building_type' in buildings_df.columns:
        conditions.append(buildings_df['building_type'] == 'sfh')
    
    # Condition 2: building_function contains 'Wohn' (case-insensitive)
    if 'building_function' in buildings_df.columns:
        conditions.append(
            buildings_df['building_function'].astype(str).str.contains('Wohn', case=False, na=False)
        )
    
    # Combine conditions with OR
    if conditions:
        mask = conditions[0]
        for cond in conditions[1:]:
            mask = mask | cond
        filtered = buildings_df[mask].copy()
    else:
        # If no relevant columns, return empty (or warn and return all)
        import warnings
        warnings.warn(
            "No 'building_type' or 'building_function' columns found. "
            "Cannot filter residential buildings. Returning all buildings.",
            UserWarning
        )
        return buildings_df.copy()
    
    return filtered


def load_building_cluster_map() -> pd.DataFrame:
    """
    Load mapping from building_id to cluster_id (street_id).
    
    Returns:
        DataFrame with columns: building_id, street_id (or cluster_id)
        Maps each building to exactly one street/cluster (1,632 mappings)
    
    Raises:
        FileNotFoundError: If building_cluster_map.parquet is not found
        AssertionError: If required columns are missing
    """
    # Use centralized path
    path = BUILDING_CLUSTER_MAP_PATH if BUILDING_CLUSTER_MAP_PATH.exists() else (DATA_PROCESSED / "building_cluster_map.parquet")
    if not path.exists():
        raise FileNotFoundError(
            f"Building cluster map file not found: {path}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure building_cluster_map.parquet exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    df = pd.read_parquet(path)
    
    # Sanity checks
    required_cols = {"building_id", "street_id"}
    assert required_cols <= set(df.columns), (
        f"building_cluster_map.parquet must contain columns: {required_cols}. "
        f"Found: {set(df.columns)}"
    )
    assert len(df) > 0, "building_cluster_map.parquet is empty"
    
    return df


def load_weather() -> pd.DataFrame:
    """
    Load hourly weather data (8760 rows for full year).
    
    Returns:
        DataFrame with columns: hour, temperature_c
        Contains 8760 rows (one per hour of the year, no gaps)
    
    Raises:
        FileNotFoundError: If hourly_weather.csv is not found
        AssertionError: If data doesn't have 8760 rows
    """
    # Try centralized paths first, then fallback
    csv_path = WEATHER_CSV_PATH if WEATHER_CSV_PATH.exists() else (DATA_PROCESSED / "hourly_weather.csv")
    parquet_path = WEATHER_PARQUET_PATH if WEATHER_PARQUET_PATH.exists() else (DATA_PROCESSED / "weather.parquet")
    
    if csv_path.exists():
        df = pd.read_csv(csv_path)
    elif parquet_path.exists():
        df = pd.read_parquet(parquet_path)
    else:
        raise FileNotFoundError(
            f"Weather file not found. Expected: {csv_path} or {parquet_path}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure hourly_weather.csv or weather.parquet exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    # Sanity checks
    assert len(df) == 8760, (
        f"Expected 8760 rows (full year), got {len(df)} rows"
    )
    assert "temperature_c" in df.columns or "temperature" in df.columns, (
        "Weather data must contain temperature column"
    )
    
    return df


def load_lv_grid() -> Dict[str, gpd.GeoDataFrame]:
    """
    Load LV (Low Voltage) grid infrastructure from power_*.geojson files.
    
    Returns:
        Dictionary with keys: 'lines', 'substations', 'generators', 'plants'
        Each value is a GeoDataFrame with the respective infrastructure.
    
    Raises:
        FileNotFoundError: If any required power_*.geojson file is not found
    """
    result = {}
    
    # Load power lines (required)
    lines_path = POWER_LINES_PATH if POWER_LINES_PATH.exists() else (DATA_PROCESSED / "power_lines.geojson")
    if lines_path.exists():
        result["lines"] = gpd.read_file(lines_path)
    else:
        raise FileNotFoundError(
            f"Power lines file not found: {lines_path}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure power_lines.geojson exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    # Load substations (required)
    subs_path = POWER_SUBSTATIONS_PATH if POWER_SUBSTATIONS_PATH.exists() else (DATA_PROCESSED / "power_substations.geojson")
    if subs_path.exists():
        result["substations"] = gpd.read_file(subs_path)
    else:
        raise FileNotFoundError(
            f"Power substations file not found: {subs_path}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure power_substations.geojson exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    # Load generators (optional)
    gen_path = POWER_GENERATORS_PATH if POWER_GENERATORS_PATH.exists() else (DATA_PROCESSED / "power_generators.geojson")
    if gen_path.exists():
        result["generators"] = gpd.read_file(gen_path)
    
    # Load plants (optional)
    plants_path = POWER_PLANTS_PATH if POWER_PLANTS_PATH.exists() else (DATA_PROCESSED / "power_plants.geojson")
    if plants_path.exists():
        result["plants"] = gpd.read_file(plants_path)
    
    return result


def load_hourly_heat_profiles() -> pd.DataFrame:
    """
    Load hourly heat profiles for all buildings.
    
    Supports both formats:
    - Index-based: index is 0-8759 (hour), columns are building_id (preferred)
    - Column-based: "hour" column exists, will be set as index
    
    Returns:
        DataFrame with index=hour (0-8759) and columns=building_id
        Values are heat demand in kW_th (thermal power)
        Shape: (8760, n_buildings)
    
    Raises:
        FileNotFoundError: If hourly_heat_profiles.parquet is not found
        ValueError: If data doesn't have expected structure
    """
    # Use centralized path
    path = HOURLY_PROFILES_PATH if HOURLY_PROFILES_PATH.exists() else (DATA_PROCESSED / "hourly_heat_profiles.parquet")
    if not path.exists():
        raise FileNotFoundError(
            f"Hourly heat profiles file not found: {path}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure hourly_heat_profiles.parquet exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    df = pd.read_parquet(path)
    
    # Sanity check: must have 8760 rows
    if len(df) != 8760:
        raise ValueError(
            f"Expected 8760 rows (full year), got {len(df)} rows"
        )
    
    # Handle both formats: index-based (preferred) or column-based (legacy)
    if "hour" in df.columns:
        # Legacy format: hour is a column, set it as index
        df = df.set_index("hour")
    elif len(df.index) == 8760:
        # Preferred format: index is already 0-8759 (or similar)
        # Ensure index is integer range 0-8759
        if not isinstance(df.index, pd.RangeIndex) or df.index[0] != 0:
            df.index = pd.RangeIndex(0, 8760)
    else:
        raise ValueError(
            f"hourly_heat_profiles must have 8760 rows. "
            f"Found {len(df)} rows. "
            f"If 'hour' is a column, it will be set as index. "
            f"Otherwise, index must represent hours 0-8759."
        )
    
    return df


def load_design_topn() -> Dict[str, Any]:
    """
    Load design hour and top-N hours for each cluster.
    
    Supports both schema formats:
    
    1. New schema (preferred, from clusters.compute_design_and_topn()):
       {
         "clusters": {
           "cluster_id": {
             "design_hour": int,
             "design_load_kw": float,
             "topn_hours": [int, ...],
             "topn_loads_kw": [float, ...]
           }
         },
         "meta": {
           "N": int,
           "source_profiles": str,
           "version": str
         }
       }
    
    2. Legacy schema (flat dict keyed by cluster_id):
       {
         "cluster_id": {
           "design_hour": int,
           "top_n_hours": [int, ...],
           ...
         }
       }
    
    Returns:
        Dictionary in new schema format (normalized):
        {
          "clusters": {cluster_id: {...}},
          "meta": {...}
        }
        If legacy format is detected, it's converted to new format.
    
    Raises:
        FileNotFoundError: If design_topn.json or cluster_design_topn.json is not found
        json.JSONDecodeError: If file is not valid JSON
        ValueError: If schema is invalid
    """
    # Try cluster_design_topn.json first (preferred), then design_topn.json (legacy)
    path = DESIGN_TOPN_PATH if DESIGN_TOPN_PATH.exists() else (DATA_PROCESSED / "cluster_design_topn.json")
    if not path.exists():
        # Try legacy name
        path = DATA_PROCESSED / "design_topn.json"
    
    if not path.exists():
        raise FileNotFoundError(
            f"Design topn file not found. Tried: {DESIGN_TOPN_PATH}, {DATA_PROCESSED / 'cluster_design_topn.json'}, {DATA_PROCESSED / 'design_topn.json'}\n"
            f"  Searched in: {DATA_PROCESSED}\n"
            f"  Hint: Ensure cluster_design_topn.json or design_topn.json exists in data/processed/ or branitz_ai/data/processed/"
        )
    
    with open(path, 'r') as f:
        data = json.load(f)
    
    # Sanity checks
    if not isinstance(data, dict):
        raise ValueError("design_topn.json must be a dictionary")
    
    if len(data) == 0:
        raise ValueError("design_topn.json is empty")
    
    # Detect schema format and normalize to new format
    if "clusters" in data and "meta" in data:
        # New schema: already in correct format
        # Validate structure
        if not isinstance(data["clusters"], dict):
            raise ValueError("'clusters' must be a dictionary")
        
        # Validate at least one cluster entry
        if len(data["clusters"]) == 0:
            raise ValueError("'clusters' dictionary is empty")
        
        # Validate first cluster entry
        first_cluster_id = list(data["clusters"].keys())[0]
        first_entry = data["clusters"][first_cluster_id]
        
        if not isinstance(first_entry, dict):
            raise ValueError(f"Cluster entry for '{first_cluster_id}' must be a dictionary")
        
        required_fields = ["design_hour", "topn_hours"]
        missing_fields = [f for f in required_fields if f not in first_entry]
        if missing_fields:
            raise ValueError(
                f"Cluster entry for '{first_cluster_id}' missing required fields: {missing_fields}"
            )
        
        return data
    
    elif "clusters" not in data and "meta" not in data:
        # Legacy schema: flat dict keyed by cluster_id
        # Convert to new format
        clusters_dict = {}
        for cluster_id, cluster_data in data.items():
            if not isinstance(cluster_data, dict):
                continue  # Skip invalid entries
            
            # Normalize field names (handle both "top_n_hours" and "topn_hours")
            normalized = {}
            
            # Design hour
            if "design_hour" in cluster_data:
                normalized["design_hour"] = cluster_data["design_hour"]
            elif "design_hour_idx" in cluster_data:
                normalized["design_hour"] = cluster_data["design_hour_idx"]
            else:
                continue  # Skip if no design hour
            
            # Design load
            if "design_load_kw" in cluster_data:
                normalized["design_load_kw"] = cluster_data["design_load_kw"]
            elif "peak_heat_kw" in cluster_data:
                normalized["design_load_kw"] = cluster_data["peak_heat_kw"]
            else:
                # Estimate from design hour if not available
                normalized["design_load_kw"] = None
            
            # Top-N hours (handle both "top_n_hours" and "topn_hours")
            if "topn_hours" in cluster_data:
                normalized["topn_hours"] = cluster_data["topn_hours"]
            elif "top_n_hours" in cluster_data:
                normalized["topn_hours"] = cluster_data["top_n_hours"]
            else:
                continue  # Skip if no top-N hours
            
            # Top-N loads (optional)
            if "topn_loads_kw" in cluster_data:
                normalized["topn_loads_kw"] = cluster_data["topn_loads_kw"]
            elif "top_n_loads_kw" in cluster_data:
                normalized["topn_loads_kw"] = cluster_data["top_n_loads_kw"]
            else:
                normalized["topn_loads_kw"] = []
            
            clusters_dict[cluster_id] = normalized
        
        # Create new format with metadata
        return {
            "clusters": clusters_dict,
            "meta": {
                "N": len(clusters_dict.get(list(clusters_dict.keys())[0], {}).get("topn_hours", [])) if clusters_dict else 10,
                "source_profiles": "hourly_heat_profiles.parquet",
                "version": "v1_legacy_converted"
            }
        }
    
    else:
        # Mixed or invalid schema
        raise ValueError(
            "Invalid schema: design_topn.json must be either:\n"
            "  - New format: {'clusters': {...}, 'meta': {...}}\n"
            "  - Legacy format: {cluster_id: {...}, ...}"
        )


# Legacy functions (kept for backward compatibility)
def load_raw_data(file_path: str):
    """
    Load raw data from file.
    
    Args:
        file_path: Path to raw data file
        
    Returns:
        Raw data as pandas DataFrame or similar structure
    """
    # TODO: Implement data loading
    pass


def clean_data(data):
    """
    Clean and validate input data.
    
    Args:
        data: Raw data to clean
        
    Returns:
        Cleaned data
    """
    # TODO: Implement data cleaning
    pass


def preprocess_data(data):
    """
    Preprocess data for analysis.
    
    Args:
        data: Cleaned data
        
    Returns:
        Preprocessed data ready for analysis
    """
    # TODO: Implement preprocessing
    pass

