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
    required_cols = ['building_id', 'use_type']
    for col in required_cols:
        if col not in buildings.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Initialize output DataFrame
    profile_data = {}
    np.random.seed(seed)
    
    for _, building in buildings.iterrows():
        building_id = building['building_id']
        use_type = building['use_type']

        annual_demand = building.get("annual_heat_demand_kwh_a", np.nan)
        try:
            annual_demand = float(annual_demand) if annual_demand is not None else np.nan
        except Exception:
            annual_demand = np.nan

        # Use TABULA/U-value derived heat-loss coefficient if present
        h_total = building.get("h_total_w_per_k", np.nan)
        t_indoor = building.get("t_indoor_c", 20.0)
        try:
            h_total = float(h_total) if h_total is not None else np.nan
        except Exception:
            h_total = np.nan
        try:
            t_indoor = float(t_indoor) if t_indoor is not None else 20.0
        except Exception:
            t_indoor = 20.0

        is_res = str(use_type).lower().startswith("residential")
        dhw_share_i = dhw_share if is_res else 0.0
        space_share_i = (1.0 - dhw_share_i) if is_res else 1.0
        
        # 1) Space heating shape
        if np.isfinite(h_total) and h_total > 0:
            # physics-based (legacy-inspired): Q_space(t) = H_total * max(0, T_in - T_out)
            dT = np.maximum(0.0, t_indoor - temp_c)
            raw_space_kw = (h_total * dT) / 1000.0  # kW
            raw_space_kwh = float(raw_space_kw.sum())
            space_shape = (raw_space_kw / raw_space_kwh) if raw_space_kwh > 0 else (np.ones(8760) / 8760)
        else:
            # Weather-driven shape (heating degree days)
            hdd = np.maximum(0, t_base - temp_c)
            weather_shape = hdd / hdd.sum() if hdd.sum() > 0 else np.ones(8760) / 8760

            # Use-type shape (currently placeholder; retained for continuity)
            type_shape = get_use_type_profile(use_type)

            blended_shape = blend_alpha * weather_shape + (1 - blend_alpha) * type_shape
            space_shape = blended_shape / blended_shape.sum()

        # 2) Annual total demand handling
        if not np.isfinite(annual_demand) or annual_demand <= 0:
            # Estimate annual demand from the space shape magnitude if we had physics-based raw kW;
            # otherwise assign a conservative default.
            if np.isfinite(h_total) and h_total > 0:
                dT = np.maximum(0.0, t_indoor - temp_c)
                annual_space_est_kwh = float(((h_total * dT) / 1000.0).sum())
                annual_demand = annual_space_est_kwh / max(1e-9, space_share_i)
            else:
                annual_demand = 25000.0

        annual_space = float(annual_demand) * float(space_share_i)
        annual_dhw = float(annual_demand) * float(dhw_share_i)
        
        # 3) Space heating profile
        space_profile = annual_space * space_shape
        
        # 4) DHW profile (flat; can be upgraded later)
        dhw_profile = np.full(8760, annual_dhw / 8760)
        
        # 5) Total profile
        total_profile = space_profile + dhw_profile
        
        # Convert to kW (kWh/h)
        profile_data[building_id] = total_profile / 1.0
    
    profiles_df = pd.DataFrame(profile_data)
    profiles_df.index.name = 'hour'
    
    # Validate sum equals annual demand when available
    if "annual_heat_demand_kwh_a" in buildings.columns:
        for building_id in buildings['building_id']:
            annual_sum = float(profiles_df[building_id].sum())
            expected = buildings.loc[buildings['building_id'] == building_id, 'annual_heat_demand_kwh_a'].iloc[0]
            try:
                expected_f = float(expected)
            except Exception:
                continue
            if expected_f > 0 and abs(annual_sum - expected_f) > expected_f * 0.01:  # 1% tolerance
                logger.warning(
                    f"Building {building_id}: sum={annual_sum:.0f}, expected={expected_f:.0f}, "
                    f"diff={abs(annual_sum - expected_f):.0f}"
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