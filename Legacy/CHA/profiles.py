"""
Load and generation profile module.
Handles creation and manipulation of energy profiles.
"""

import warnings
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd

# Constants
T_BASE = 17.0  # Base temperature for heating degree calculation (°C)
SPACE_SHARE = 0.85  # Share of annual heat for space heating
DHW_SHARE = 0.15  # Share of annual heat for domestic hot water
DEFAULT_BLEND_ALPHA = 0.7  # Default blending factor: α * weather_shape + (1-α) * type_shape


# ============================================================================
# Standardized Profile Shapes by Use Type
# ============================================================================

def _get_standardized_profile_shape(use_type: str) -> np.ndarray:
    """
    Generate standardized hourly profile shape (8760 hours) for a given use type.
    
    These shapes represent typical usage patterns independent of weather:
    - Residential: Morning and evening peaks
    - Office: Weekday 8-18h pattern
    - School: Weekday 6-16h pattern
    - Retail: Weekday 9-20h pattern, higher on weekends
    - Default: Flat profile (weather-driven only)
    
    Args:
        use_type: Building use type (residential_sfh, residential_mfh, office, school, retail, unknown)
        
    Returns:
        Normalized array of shape (8760,) representing hourly pattern (sums to 1.0)
    """
    shape = np.zeros(8760)
    
    # Create day-of-week and hour-of-day indices
    # Hour 0 = Jan 1, 00:00 (assuming non-leap year)
    # We'll create patterns based on day of week and hour of day
    
    for hour in range(8760):
        day_of_week = (hour // 24) % 7  # 0=Monday, 6=Sunday
        hour_of_day = hour % 24
        
        is_weekday = day_of_week < 5
        is_weekend = day_of_week >= 5
        
        if use_type in ["residential_sfh", "residential_mfh"]:
            # Residential: Morning peak (6-9h) and evening peak (17-22h)
            if 6 <= hour_of_day <= 9:
                shape[hour] = 1.5  # Morning peak
            elif 17 <= hour_of_day <= 22:
                shape[hour] = 1.8  # Evening peak (higher)
            elif 10 <= hour_of_day <= 16:
                shape[hour] = 0.6  # Daytime (lower)
            elif 23 <= hour_of_day or hour_of_day <= 5:
                shape[hour] = 0.8  # Night (moderate)
            else:
                shape[hour] = 1.0  # Base
                
        elif use_type == "office":
            # Office: Weekday 8-18h pattern, very low on weekends
            if is_weekday and 8 <= hour_of_day <= 18:
                shape[hour] = 2.0  # Work hours
            elif is_weekday:
                shape[hour] = 0.3  # Off-hours on weekdays
            else:
                shape[hour] = 0.2  # Weekends (very low)
                
        elif use_type == "school":
            # School: Weekday 6-16h pattern, very low on weekends/holidays
            if is_weekday and 6 <= hour_of_day <= 16:
                shape[hour] = 2.2  # School hours
            elif is_weekday:
                shape[hour] = 0.4  # Off-hours on weekdays
            else:
                shape[hour] = 0.15  # Weekends/holidays (very low)
                
        elif use_type == "retail":
            # Retail: Weekday 9-20h, higher on weekends
            if is_weekday and 9 <= hour_of_day <= 20:
                shape[hour] = 1.8  # Business hours
            elif is_weekday:
                shape[hour] = 0.4  # Off-hours on weekdays
            elif is_weekend and 9 <= hour_of_day <= 20:
                shape[hour] = 2.2  # Weekend business hours (higher)
            else:
                shape[hour] = 0.3  # Weekend off-hours
                
        else:
            # Unknown/default: Flat profile (will be blended with weather)
            shape[hour] = 1.0
    
    # Normalize to sum to 1.0
    shape_sum = np.sum(shape)
    if shape_sum > 0:
        shape = shape / shape_sum
    else:
        # Fallback: flat profile
        shape = np.ones(8760) / 8760.0
    
    return shape


def _resolve_use_type_for_profile(row: pd.Series) -> str:
    """
    Resolve use type from building row for profile selection.
    
    Args:
        row: Building row with use_type, building_type, or profile_code
        
    Returns:
        Use type string for profile selection
    """
    # Try profile_code first (if available)
    profile_code = row.get("profile_code")
    if profile_code is not None and not pd.isna(profile_code):
        profile_str = str(profile_code).upper()
        # Map common profile codes to use types
        if profile_str in ["H0", "H1", "H2"]:
            return "residential_sfh"
        elif profile_str in ["G1"]:
            return "office"
        elif profile_str in ["G2"]:
            return "retail"
        elif profile_str in ["G0"]:
            return "residential_mfh"  # General commercial/residential mix
    
    # Fall back to use_type
    use_type = (
        row.get("use_type") or
        row.get("building_type") or
        row.get("building_function") or
        None
    )
    
    if use_type is not None and not pd.isna(use_type):
        use_type_str = str(use_type).lower()
        if "sfh" in use_type_str or "single" in use_type_str or "einfamilien" in use_type_str:
            return "residential_sfh"
        elif "mfh" in use_type_str or "multi" in use_type_str or "wohn" in use_type_str:
            return "residential_mfh"
        elif "office" in use_type_str or "büro" in use_type_str:
            return "office"
        elif "school" in use_type_str or "schule" in use_type_str:
            return "school"
        elif "retail" in use_type_str or "handel" in use_type_str or "shop" in use_type_str:
            return "retail"
    
    return "unknown"


# ============================================================================
# Weather Standardization
# ============================================================================

def _standardize_weather(weather_df: pd.DataFrame) -> pd.Series:
    """
    Standardize weather DataFrame to extract temperature series.
    
    Args:
        weather_df: DataFrame with weather data
            Expected columns: 'temp_C' or 'temperature_c' or first numeric column
        
    Returns:
        Series with temperature in °C, index 0-8759
        
    Raises:
        ValueError: If weather data doesn't have 8760 rows
        ValueError: If no temperature column found
    """
    # Check length
    if len(weather_df) != 8760:
        raise ValueError(
            f"Weather data must have exactly 8760 rows (full year), "
            f"got {len(weather_df)} rows"
        )
    
    # Try to find temperature column
    temp_col = None
    
    # Try explicit column names
    for col_name in ['temp_C', 'temperature_c', 'temperature', 'T_out', 'T_ambient']:
        if col_name in weather_df.columns:
            temp_col = col_name
            break
    
    # If not found, try first numeric column
    if temp_col is None:
        numeric_cols = weather_df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            temp_col = numeric_cols[0]
            warnings.warn(
                f"No explicit temperature column found, using first numeric column: {temp_col}",
                UserWarning
            )
        else:
            raise ValueError(
                f"No temperature column found in weather data. "
                f"Expected one of: temp_C, temperature_c, temperature, T_out, T_ambient, "
                f"or a numeric column. Available columns: {list(weather_df.columns)}"
            )
    
    # Extract temperature series
    temp_series = weather_df[temp_col].copy()
    
    # Reset index to 0-8759 if needed
    if not isinstance(temp_series.index, pd.RangeIndex) or temp_series.index[0] != 0:
        temp_series.index = pd.RangeIndex(0, 8760)
    
    return temp_series


# ============================================================================
# Profile Generation
# ============================================================================

def generate_hourly_profiles(
    buildings_with_env: pd.DataFrame,
    weather_df: pd.DataFrame,
    t_base: float = T_BASE,
    space_share: float = SPACE_SHARE,
    dhw_share: float = DHW_SHARE,
    use_profile_code: bool = True,
    blend_alpha: float = DEFAULT_BLEND_ALPHA
) -> pd.DataFrame:
    """
    Generate hourly heat demand profiles for all buildings.
    
    Model:
    - Space heating: Blended weather-driven + use-type-specific pattern
    - DHW: Flat profile (constant throughout year)
    - Total: Space + DHW
    
    Formula:
    - Heating intensity: h = max(0, T_base - temp_C)
    - Weather shape: normalized heating degree hours
    - Type shape: standardized pattern by use_type (residential, office, school, etc.)
    - Blended shape: α * weather_shape + (1-α) * type_shape
    - Space profile: annual_space * blended_shape
    - DHW profile: annual_dhw * (1/8760) [flat]
    - Hourly demand: space_profile + dhw_profile (in kWh/h = kW for hourly steps)
    
    Args:
        buildings_with_env: DataFrame with building data including:
            - building_id (required)
            - annual_heat_demand_kwh_a (required, can be NaN)
            - use_type or building_type (optional): For type-specific patterns
            - profile_code (optional): Alternative to use_type for pattern selection
        weather_df: DataFrame with weather data (8760 rows)
            Must contain temperature column (temp_C, temperature_c, or first numeric)
        t_base: Base temperature for heating degree calculation (°C, default: 17.0)
        space_share: Share of annual heat for space heating (default: 0.85)
        dhw_share: Share of annual heat for DHW (default: 0.15)
        use_profile_code: If True, blend weather-based shape with type-specific patterns (default: True)
        blend_alpha: Blending factor α for shape = α * weather_shape + (1-α) * type_shape (default: 0.7)
            α = 1.0: Pure weather-driven (original behavior)
            α = 0.0: Pure type-specific pattern
            α = 0.7: 70% weather, 30% type pattern (recommended)
        
    Returns:
        DataFrame with:
        - Index: 0-8759 (hour of year)
        - Columns: building_id (one per building)
        - Values: Heat demand in kW_th (kWh/h, numerically equal to kW for hourly steps)
        
    Raises:
        ValueError: If weather data doesn't have 8760 rows
        ValueError: If building_id column missing
    """
    # Sanity checks
    if "building_id" not in buildings_with_env.columns:
        raise ValueError("buildings_with_env must contain 'building_id' column")
    
    if "annual_heat_demand_kwh_a" not in buildings_with_env.columns:
        raise ValueError(
            "buildings_with_env must contain 'annual_heat_demand_kwh_a' column. "
            "Run estimate_envelope() first."
        )
    
    # Standardize weather
    temp_C = _standardize_weather(weather_df)
    
    # Get building IDs
    building_ids = buildings_with_env['building_id'].tolist()
    n_buildings = len(building_ids)
    
    # Initialize output DataFrame
    profiles_df = pd.DataFrame(
        index=pd.RangeIndex(0, 8760),
        columns=building_ids,
        dtype=float
    )
    
    # Step A: Compute base weather-driven heating shape
    # Heating intensity: h = max(0, T_base - temp_C)
    h = np.maximum(0, t_base - temp_C.values)
    
    # Check if all zeros (strange weather)
    if np.sum(h) == 0:
        warnings.warn(
            "All heating intensities are zero (weather always above base temperature). "
            "Using flat profile as fallback.",
            UserWarning
        )
        weather_shape = np.ones(8760) / 8760.0  # Flat profile
    else:
        # Normalize weather shape
        weather_shape = h / np.sum(h)
    
    # Step B: Generate profiles for each building
    for idx, building_id in enumerate(building_ids):
        row = buildings_with_env.iloc[idx]
        annual_demand = row.get('annual_heat_demand_kwh_a')
        
        # Handle missing annual demand
        if pd.isna(annual_demand) or annual_demand is None:
            warnings.warn(
                f"Building {building_id} has missing annual_heat_demand_kwh_a. "
                f"Filling with zeros.",
                UserWarning
            )
            profiles_df[building_id] = 0.0
            continue
        
        # Ensure non-negative
        if annual_demand < 0:
            warnings.warn(
                f"Building {building_id} has negative annual_heat_demand_kwh_a: {annual_demand}. "
                f"Filling with zeros.",
                UserWarning
            )
            profiles_df[building_id] = 0.0
            continue
        
        # Split annual demand
        annual_space = annual_demand * space_share
        annual_dhw = annual_demand * dhw_share
        
        # Step C: Compute blended shape (weather + type-specific pattern)
        if use_profile_code:
            # Resolve use type for this building
            use_type = _resolve_use_type_for_profile(row)
            
            # Get type-specific standardized shape
            type_shape = _get_standardized_profile_shape(use_type)
            
            # Blend: α * weather_shape + (1-α) * type_shape
            blended_shape = blend_alpha * weather_shape + (1 - blend_alpha) * type_shape
            
            # Renormalize to ensure sum = 1.0
            shape_sum = np.sum(blended_shape)
            if shape_sum > 0:
                blended_shape = blended_shape / shape_sum
            else:
                # Fallback to weather shape
                blended_shape = weather_shape
        else:
            # Pure weather-driven (original behavior)
            blended_shape = weather_shape
        
        # Space heating profile: blended shape
        space_profile = annual_space * blended_shape
        
        # DHW profile: flat (constant throughout year)
        dhw_profile = np.full(8760, annual_dhw / 8760.0)
        
        # Total hourly profile (kWh/h = kW for hourly steps)
        hourly_kwh = space_profile + dhw_profile
        
        profiles_df[building_id] = hourly_kwh
    
    # Ensure column order matches building_ids
    profiles_df = profiles_df[building_ids]
    
    return profiles_df


def save_hourly_profiles_parquet(
    df: pd.DataFrame,
    path: Union[str, Path],
    compression: str = 'snappy'
) -> None:
    """
    Save hourly heat profiles to parquet file.
    
    Ensures:
    - Index is stored
    - Compression is applied (default: snappy)
    - Column order is preserved
    - Stable dtypes
    
    Args:
        df: DataFrame with hourly profiles (8760 rows, columns=building_id)
        path: Path to output parquet file
        compression: Compression algorithm (default: 'snappy')
        
    Raises:
        ValueError: If DataFrame doesn't have 8760 rows
    """
    if len(df) != 8760:
        raise ValueError(
            f"Profiles DataFrame must have exactly 8760 rows, got {len(df)}"
        )
    
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save with index, compression, and preserve column order
    df.to_parquet(
        path,
        engine='pyarrow',
        compression=compression,
        index=True,
        write_statistics=True
    )


# ============================================================================
# Legacy Functions (kept for backward compatibility)
# ============================================================================

def create_load_profile(data, parameters):
    """
    Create load profile from data.
    
    Args:
        data: Input data
        parameters: Profile generation parameters
        
    Returns:
        Load profile time series
    """
    # TODO: Implement load profile creation
    pass


def create_generation_profile(data, parameters):
    """
    Create generation profile from data.
    
    Args:
        data: Input data
        parameters: Profile generation parameters
        
    Returns:
        Generation profile time series
    """
    # TODO: Implement generation profile creation
    pass


def normalize_profile(profile):
    """
    Normalize profile to standard format.
    
    Args:
        profile: Profile to normalize
        
    Returns:
        Normalized profile
    """
    # TODO: Implement profile normalization
    pass

