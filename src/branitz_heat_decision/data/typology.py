import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

# TABULA-based U-value lookup table
# Format: (use_type, construction_band, renovation_state) -> U-values
U_TABLE: Dict[tuple, Dict[str, float]] = {
    ('residential_sfh', 'pre_1978', 'unrenovated'): {'wall': 1.2, 'roof': 1.0, 'window': 2.7},
    ('residential_sfh', 'pre_1978', 'partial'): {'wall': 0.6, 'roof': 0.5, 'window': 1.8},
    ('residential_sfh', 'pre_1978', 'full'): {'wall': 0.2, 'roof': 0.18, 'window': 1.1},
    ('residential_sfh', '1979_1994', 'unrenovated'): {'wall': 0.8, 'roof': 0.7, 'window': 2.5},
    ('residential_sfh', '1979_1994', 'partial'): {'wall': 0.4, 'roof': 0.35, 'window': 1.6},
    ('residential_sfh', '1979_1994', 'full'): {'wall': 0.15, 'roof': 0.13, 'window': 0.9},
    ('residential_sfh', '1995_2009', 'unrenovated'): {'wall': 0.5, 'roof': 0.4, 'window': 1.8},
    ('residential_sfh', '1995_2009', 'partial'): {'wall': 0.3, 'roof': 0.25, 'window': 1.3},
    ('residential_sfh', '1995_2009', 'full'): {'wall': 0.13, 'roof': 0.10, 'window': 0.7},
    ('residential_sfh', 'post_2010', 'unrenovated'): {'wall': 0.3, 'roof': 0.25, 'window': 1.4},
    ('residential_sfh', 'post_2010', 'full'): {'wall': 0.13, 'roof': 0.10, 'window': 0.7},
    
    ('residential_mfh', 'pre_1978', 'unrenovated'): {'wall': 1.4, 'roof': 1.2, 'window': 2.8},
    # ... add all combinations
}

# Specific heat demand [kWh/(m²·a)]
SPEC_DEMAND_TABLE: Dict[tuple, float] = {
    ('residential_sfh', 'pre_1978', 'unrenovated'): 250,
    ('residential_sfh', 'pre_1978', 'full'): 60,
    ('residential_sfh', 'post_2010', 'full'): 40,
    # ... add all combinations
}

def classify_construction_band(year: int) -> str:
    """Map year to TABULA construction band."""
    if year <= 1978:
        return 'pre_1978'
    elif 1979 <= year <= 1994:
        return '1979_1994'
    elif 1995 <= year <= 2009:
        return '1995_2009'
    else:
        return 'post_2010'

def classify_use_type(building_function: str) -> str:
    """Map German building function to standard use_type."""
    function = str(building_function).lower()
    if 'wohn' in function or 'residential' in function:
        return 'residential_sfh'  # Default to SFH, will adjust if floor_area > 400m²
    elif 'mfh' in function or 'mehrfam' in function:
        return 'residential_mfh'
    elif 'office' in function or 'büro' in function:
        return 'office'
    elif 'school' in function or 'schule' in function:
        return 'school'
    elif 'retail' in function or 'handel' in function:
        return 'retail'
    else:
        return 'unknown'

def estimate_envelope(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Estimate building envelope parameters using TABULA typology.
    
    Args:
        buildings: GeoDataFrame with columns:
            - building_id (required)
            - year_of_construction (optional)
            - floor_area_m2 (optional)
            - building_function (optional)
            - annual_heat_demand_kwh_a (optional)
            
    Returns:
        GeoDataFrame with added columns:
            - use_type
            - construction_band
            - renovation_state
            - u_wall, u_roof, u_window
            - specific_heat_demand_kwh_m2a
            - annual_heat_demand_kwh_a (if missing)
    """
    logger.info(f"Estimating envelope for {len(buildings)} buildings")
    
    # Work on copy
    df = buildings.copy()
    
    # Classify use_type
    if 'use_type' not in df.columns:
        if 'building_function' in df.columns:
            df['use_type'] = df['building_function'].apply(classify_use_type)
        else:
            df['use_type'] = 'unknown'
            logger.warning("No building_function column, setting use_type='unknown'")
    
    # Classify construction band
    if 'year_of_construction' in df.columns:
        df['construction_band'] = df['year_of_construction'].apply(classify_construction_band)
    else:
        df['construction_band'] = 'unknown'
        logger.warning("No year_of_construction, setting construction_band='unknown'")
    
    # Default renovation state (to be updated later)
    if 'renovation_state' not in df.columns:
        df['renovation_state'] = 'unrenovated'
    
    # Estimate U-values and specific heat demand
    u_wall_values = []
    u_roof_values = []
    u_window_values = []
    specific_demand_values = []
    
    for idx, row in df.iterrows():
        key = (
            row.get('use_type', 'residential_sfh'),
            row.get('construction_band', 'unknown'),
            row.get('renovation_state', 'unrenovated')
        )
        
        if key in U_TABLE:
            u_vals = U_TABLE[key]
            u_wall_values.append(u_vals['wall'])
            u_roof_values.append(u_vals['roof'])
            u_window_values.append(u_vals['window'])
        else:
            # Fallback values
            u_wall_values.append(0.5)
            u_roof_values.append(0.4)
            u_window_values.append(1.5)
            if idx < 5:
                logger.warning(f"No U-value match for {key}, using defaults")
        
        if key in SPEC_DEMAND_TABLE:
            specific_demand_values.append(SPEC_DEMAND_TABLE[key])
        else:
            specific_demand_values.append(100)
    
    df['u_wall'] = u_wall_values
    df['u_roof'] = u_roof_values
    df['u_window'] = u_window_values
    df['specific_heat_demand_kwh_m2a'] = specific_demand_values
    
    # Estimate annual heat demand if missing
    if 'annual_heat_demand_kwh_a' not in df.columns:
        if 'floor_area_m2' in df.columns:
            df['annual_heat_demand_kwh_a'] = df['specific_heat_demand_kwh_m2a'] * df['floor_area_m2']
            logger.info("Estimated annual_heat_demand_kwh_a from floor_area_m2")
        else:
            df['annual_heat_demand_kwh_a'] = 25000  # Default 25 MWh
            logger.warning("No floor_area_m2, using default annual_heat_demand_kwh_a=25000")
    
    logger.info(f"Envelope estimation complete")
    return df