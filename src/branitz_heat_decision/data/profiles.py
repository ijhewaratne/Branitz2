import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def generate_hourly_profiles(
    buildings: gpd.GeoDataFrame,
    weather_df: pd.DataFrame,
    t_base: float = 15.0,
    space_share: float = 0.85,
    dhw_share: float = 0.15,
    blend_alpha: float = 0.7,
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate 8760 hourly heat demand profiles for all buildings.
    
    Args:
        buildings: GeoDataFrame with columns:
            - building_id (required)
            - use_type (required)
            - annual_heat_demand_kwh_a (required)
        weather_df: DataFrame with columns:
            - hour (0-8759) or index
            - temperature_c (required)
        t_base: Base temperature for heating degree days
        space_share: Share of annual heat for space heating
        dhw_share: Share for domestic hot water
        blend_alpha: Weight for weather-driven vs use-type shape
        
    Returns:
        DataFrame: index=hour (0-8759), columns=building_id, values=kW_th
    """
    logger.info("Generating hourly heat profiles")
    
    # Validate weather data
    if len(weather_df) != 8760:
        raise ValueError(f"Weather data must have 8760 rows, got {len(weather_df)}")
    
    # Get temperature series
    if 'temperature_c' in weather_df.columns:
        temp_c = weather_df['temperature_c'].values
    elif 'temp_C' in weather_df.columns:
        temp_c = weather_df['temp_C'].values
    else:
        raise ValueError("No temperature column found in weather_df")
    
    # Validate buildings
    required_cols = ['building_id', 'use_type', 'annual_heat_demand_kwh_a']
    for col in required_cols:
        if col not in buildings.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Initialize output DataFrame
    profile_data = {}
    np.random.seed(seed)
    
    for _, building in buildings.iterrows():
        building_id = building['building_id']
        annual_demand = building['annual_heat_demand_kwh_a']
        use_type = building['use_type']
        
        # Split space heating and DHW
        annual_space = annual_demand * space_share
        annual_dhw = annual_demand * dhw_share
        
        # 1. Weather-driven shape (heating degree days)
        hdd = np.maximum(0, t_base - temp_c)
        weather_shape = hdd / hdd.sum() if hdd.sum() > 0 else np.ones(8760) / 8760
        
        # 2. Use-type shape (standardized patterns)
        type_shape = get_use_type_profile(use_type)
        
        # 3. Blended shape
        blended_shape = blend_alpha * weather_shape + (1 - blend_alpha) * type_shape
        blended_shape = blended_shape / blended_shape.sum()  # Normalize
        
        # 4. Space heating profile
        space_profile = annual_space * blended_shape
        
        # 5. DHW profile (flat)
        dhw_profile = np.full(8760, annual_dhw / 8760)
        
        # 6. Total profile
        total_profile = space_profile + dhw_profile
        
        # Convert to kW (kWh/h)
        profile_data[building_id] = total_profile / 1.0
    
    profiles_df = pd.DataFrame(profile_data)
    profiles_df.index.name = 'hour'
    
    # Validate sum equals annual demand
    for building_id in buildings['building_id']:
        annual_sum = profiles_df[building_id].sum()
        expected = buildings.loc[buildings['building_id'] == building_id, 'annual_heat_demand_kwh_a'].iloc[0]
        if abs(annual_sum - expected) > expected * 0.01:  # 1% tolerance
            logger.warning(
                f"Building {building_id}: sum={annual_sum:.0f}, expected={expected:.0f}, "
                f"diff={abs(annual_sum - expected):.0f}"
            )
    
    logger.info(f"Generated profiles for {len(profiles_df.columns)} buildings")
    return profiles_df


def get_use_type_profile(use_type: str) -> np.ndarray:
    """
    Get standardized daily profile shape for use type.
    
    Returns:
        Array of length 8760, normalized to sum to 1
    """
    # Base pattern: higher in winter, lower in summer
    # This is a simplified version - in practice, you'd load from TABULA or similar
    
    use_type = str(use_type).lower()
    
    # For now, return a flat profile as fallback
    # In real implementation, load from TABULA/VDI profiles
    return np.ones(8760) / 8760