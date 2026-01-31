"""
Typology classification module.
Handles classification of energy system typologies and building envelope estimation.
"""

import warnings
from typing import Union

import pandas as pd
import geopandas as gpd

# ============================================================================
# Parameter Tables
# ============================================================================

# U-value table: (use_type, construction_band, renovation_state) -> U-values
# Units: W/(m²·K)
U_TABLE = {
    # Residential SFH
    ("residential_sfh", "pre_1978", "unrenovated"): dict(u_wall=1.2, u_roof=1.0, u_window=2.7),
    ("residential_sfh", "pre_1978", "partial"): dict(u_wall=0.6, u_roof=0.4, u_window=1.6),
    ("residential_sfh", "pre_1978", "full"): dict(u_wall=0.3, u_roof=0.2, u_window=1.2),
    ("residential_sfh", "1979_1994", "unrenovated"): dict(u_wall=0.8, u_roof=0.6, u_window=2.0),
    ("residential_sfh", "1979_1994", "partial"): dict(u_wall=0.4, u_roof=0.3, u_window=1.4),
    ("residential_sfh", "1979_1994", "full"): dict(u_wall=0.25, u_roof=0.2, u_window=1.1),
    ("residential_sfh", "1995_2009", "unrenovated"): dict(u_wall=0.5, u_roof=0.4, u_window=1.6),
    ("residential_sfh", "1995_2009", "partial"): dict(u_wall=0.3, u_roof=0.25, u_window=1.3),
    ("residential_sfh", "1995_2009", "full"): dict(u_wall=0.2, u_roof=0.15, u_window=1.0),
    ("residential_sfh", "post_2010", "unrenovated"): dict(u_wall=0.3, u_roof=0.25, u_window=1.2),
    ("residential_sfh", "post_2010", "partial"): dict(u_wall=0.2, u_roof=0.18, u_window=1.0),
    ("residential_sfh", "post_2010", "full"): dict(u_wall=0.15, u_roof=0.12, u_window=0.8),
    
    # Residential MFH
    ("residential_mfh", "pre_1978", "unrenovated"): dict(u_wall=1.1, u_roof=0.9, u_window=2.6),
    ("residential_mfh", "pre_1978", "partial"): dict(u_wall=0.55, u_roof=0.35, u_window=1.5),
    ("residential_mfh", "pre_1978", "full"): dict(u_wall=0.28, u_roof=0.18, u_window=1.1),
    ("residential_mfh", "1979_1994", "unrenovated"): dict(u_wall=0.75, u_roof=0.55, u_window=1.9),
    ("residential_mfh", "1979_1994", "partial"): dict(u_wall=0.38, u_roof=0.28, u_window=1.3),
    ("residential_mfh", "1979_1994", "full"): dict(u_wall=0.24, u_roof=0.19, u_window=1.0),
    ("residential_mfh", "1995_2009", "unrenovated"): dict(u_wall=0.48, u_roof=0.38, u_window=1.5),
    ("residential_mfh", "1995_2009", "partial"): dict(u_wall=0.28, u_roof=0.24, u_window=1.2),
    ("residential_mfh", "1995_2009", "full"): dict(u_wall=0.19, u_roof=0.14, u_window=0.95),
    ("residential_mfh", "post_2010", "unrenovated"): dict(u_wall=0.28, u_roof=0.24, u_window=1.1),
    ("residential_mfh", "post_2010", "partial"): dict(u_wall=0.19, u_roof=0.17, u_window=0.95),
    ("residential_mfh", "post_2010", "full"): dict(u_wall=0.14, u_roof=0.11, u_window=0.75),
    
    # Office
    ("office", "pre_1978", "unrenovated"): dict(u_wall=1.0, u_roof=0.8, u_window=2.5),
    ("office", "pre_1978", "partial"): dict(u_wall=0.5, u_roof=0.3, u_window=1.4),
    ("office", "pre_1978", "full"): dict(u_wall=0.25, u_roof=0.15, u_window=1.0),
    ("office", "1979_1994", "unrenovated"): dict(u_wall=0.7, u_roof=0.5, u_window=1.8),
    ("office", "1979_1994", "partial"): dict(u_wall=0.35, u_roof=0.25, u_window=1.2),
    ("office", "1979_1994", "full"): dict(u_wall=0.22, u_roof=0.17, u_window=0.9),
    ("office", "1995_2009", "unrenovated"): dict(u_wall=0.45, u_roof=0.35, u_window=1.4),
    ("office", "1995_2009", "partial"): dict(u_wall=0.27, u_roof=0.22, u_window=1.1),
    ("office", "1995_2009", "full"): dict(u_wall=0.18, u_roof=0.13, u_window=0.85),
    ("office", "post_2010", "unrenovated"): dict(u_wall=0.25, u_roof=0.22, u_window=1.0),
    ("office", "post_2010", "partial"): dict(u_wall=0.17, u_roof=0.15, u_window=0.85),
    ("office", "post_2010", "full"): dict(u_wall=0.13, u_roof=0.10, u_window=0.7),
    
    # School
    ("school", "pre_1978", "unrenovated"): dict(u_wall=1.1, u_roof=0.9, u_window=2.6),
    ("school", "pre_1978", "partial"): dict(u_wall=0.55, u_roof=0.35, u_window=1.5),
    ("school", "pre_1978", "full"): dict(u_wall=0.28, u_roof=0.18, u_window=1.1),
    ("school", "1979_1994", "unrenovated"): dict(u_wall=0.75, u_roof=0.55, u_window=1.9),
    ("school", "1979_1994", "partial"): dict(u_wall=0.38, u_roof=0.28, u_window=1.3),
    ("school", "1979_1994", "full"): dict(u_wall=0.24, u_roof=0.19, u_window=1.0),
    ("school", "1995_2009", "unrenovated"): dict(u_wall=0.48, u_roof=0.38, u_window=1.5),
    ("school", "1995_2009", "partial"): dict(u_wall=0.28, u_roof=0.24, u_window=1.2),
    ("school", "1995_2009", "full"): dict(u_wall=0.19, u_roof=0.14, u_window=0.95),
    ("school", "post_2010", "unrenovated"): dict(u_wall=0.28, u_roof=0.24, u_window=1.1),
    ("school", "post_2010", "partial"): dict(u_wall=0.19, u_roof=0.17, u_window=0.95),
    ("school", "post_2010", "full"): dict(u_wall=0.14, u_roof=0.11, u_window=0.75),
    
    # Retail
    ("retail", "pre_1978", "unrenovated"): dict(u_wall=1.0, u_roof=0.8, u_window=2.5),
    ("retail", "pre_1978", "partial"): dict(u_wall=0.5, u_roof=0.3, u_window=1.4),
    ("retail", "pre_1978", "full"): dict(u_wall=0.25, u_roof=0.15, u_window=1.0),
    ("retail", "1979_1994", "unrenovated"): dict(u_wall=0.7, u_roof=0.5, u_window=1.8),
    ("retail", "1979_1994", "partial"): dict(u_wall=0.35, u_roof=0.25, u_window=1.2),
    ("retail", "1979_1994", "full"): dict(u_wall=0.22, u_roof=0.17, u_window=0.9),
    ("retail", "1995_2009", "unrenovated"): dict(u_wall=0.45, u_roof=0.35, u_window=1.4),
    ("retail", "1995_2009", "partial"): dict(u_wall=0.27, u_roof=0.22, u_window=1.1),
    ("retail", "1995_2009", "full"): dict(u_wall=0.18, u_roof=0.13, u_window=0.85),
    ("retail", "post_2010", "unrenovated"): dict(u_wall=0.25, u_roof=0.22, u_window=1.0),
    ("retail", "post_2010", "partial"): dict(u_wall=0.17, u_roof=0.15, u_window=0.85),
    ("retail", "post_2010", "full"): dict(u_wall=0.13, u_roof=0.10, u_window=0.7),
    
    # Unknown (defaults)
    ("unknown", "pre_1978", "unrenovated"): dict(u_wall=1.0, u_roof=0.8, u_window=2.5),
    ("unknown", "pre_1978", "partial"): dict(u_wall=0.5, u_roof=0.3, u_window=1.4),
    ("unknown", "pre_1978", "full"): dict(u_wall=0.25, u_roof=0.15, u_window=1.0),
    ("unknown", "1979_1994", "unrenovated"): dict(u_wall=0.7, u_roof=0.5, u_window=1.8),
    ("unknown", "1979_1994", "partial"): dict(u_wall=0.35, u_roof=0.25, u_window=1.2),
    ("unknown", "1979_1994", "full"): dict(u_wall=0.22, u_roof=0.17, u_window=0.9),
    ("unknown", "1995_2009", "unrenovated"): dict(u_wall=0.45, u_roof=0.35, u_window=1.4),
    ("unknown", "1995_2009", "partial"): dict(u_wall=0.27, u_roof=0.22, u_window=1.1),
    ("unknown", "1995_2009", "full"): dict(u_wall=0.18, u_roof=0.13, u_window=0.85),
    ("unknown", "post_2010", "unrenovated"): dict(u_wall=0.25, u_roof=0.22, u_window=1.0),
    ("unknown", "post_2010", "partial"): dict(u_wall=0.17, u_roof=0.15, u_window=0.85),
    ("unknown", "post_2010", "full"): dict(u_wall=0.13, u_roof=0.10, u_window=0.7),
}

# Default U-values (W/(m²·K))
DEFAULT_U = dict(u_wall=0.8, u_roof=0.6, u_window=1.8)

# Internal gains table: use_type -> W/m²
GAINS_TABLE = {
    "residential_sfh": 3.0,
    "residential_mfh": 3.5,
    "office": 6.0,
    "school": 5.0,
    "retail": 7.0,
    "unknown": 3.0,
}

# Specific heat demand table: (use_type, construction_band, renovation_state) -> kWh/(m²·a)
SPEC_DEMAND_TABLE = {
    # Residential SFH
    ("residential_sfh", "pre_1978", "unrenovated"): 180,
    ("residential_sfh", "pre_1978", "partial"): 120,
    ("residential_sfh", "pre_1978", "full"): 70,
    ("residential_sfh", "1979_1994", "unrenovated"): 140,
    ("residential_sfh", "1979_1994", "partial"): 100,
    ("residential_sfh", "1979_1994", "full"): 60,
    ("residential_sfh", "1995_2009", "unrenovated"): 100,
    ("residential_sfh", "1995_2009", "partial"): 75,
    ("residential_sfh", "1995_2009", "full"): 50,
    ("residential_sfh", "post_2010", "unrenovated"): 60,
    ("residential_sfh", "post_2010", "partial"): 50,
    ("residential_sfh", "post_2010", "full"): 40,
    
    # Residential MFH
    ("residential_mfh", "pre_1978", "unrenovated"): 160,
    ("residential_mfh", "pre_1978", "partial"): 110,
    ("residential_mfh", "pre_1978", "full"): 65,
    ("residential_mfh", "1979_1994", "unrenovated"): 130,
    ("residential_mfh", "1979_1994", "partial"): 95,
    ("residential_mfh", "1979_1994", "full"): 55,
    ("residential_mfh", "1995_2009", "unrenovated"): 95,
    ("residential_mfh", "1995_2009", "partial"): 70,
    ("residential_mfh", "1995_2009", "full"): 45,
    ("residential_mfh", "post_2010", "unrenovated"): 55,
    ("residential_mfh", "post_2010", "partial"): 45,
    ("residential_mfh", "post_2010", "full"): 35,
    
    # Office
    ("office", "pre_1978", "unrenovated"): 120,
    ("office", "pre_1978", "partial"): 85,
    ("office", "pre_1978", "full"): 55,
    ("office", "1979_1994", "unrenovated"): 100,
    ("office", "1979_1994", "partial"): 75,
    ("office", "1979_1994", "full"): 50,
    ("office", "1995_2009", "unrenovated"): 75,
    ("office", "1995_2009", "partial"): 60,
    ("office", "1995_2009", "full"): 40,
    ("office", "post_2010", "unrenovated"): 50,
    ("office", "post_2010", "partial"): 40,
    ("office", "post_2010", "full"): 30,
    
    # School
    ("school", "pre_1978", "unrenovated"): 130,
    ("school", "pre_1978", "partial"): 90,
    ("school", "pre_1978", "full"): 60,
    ("school", "1979_1994", "unrenovated"): 110,
    ("school", "1979_1994", "partial"): 80,
    ("school", "1979_1994", "full"): 55,
    ("school", "1995_2009", "unrenovated"): 80,
    ("school", "1995_2009", "partial"): 65,
    ("school", "1995_2009", "full"): 45,
    ("school", "post_2010", "unrenovated"): 55,
    ("school", "post_2010", "partial"): 45,
    ("school", "post_2010", "full"): 35,
    
    # Retail
    ("retail", "pre_1978", "unrenovated"): 140,
    ("retail", "pre_1978", "partial"): 95,
    ("retail", "pre_1978", "full"): 60,
    ("retail", "1979_1994", "unrenovated"): 115,
    ("retail", "1979_1994", "partial"): 85,
    ("retail", "1979_1994", "full"): 55,
    ("retail", "1995_2009", "unrenovated"): 85,
    ("retail", "1995_2009", "partial"): 70,
    ("retail", "1995_2009", "full"): 45,
    ("retail", "post_2010", "unrenovated"): 60,
    ("retail", "post_2010", "partial"): 50,
    ("retail", "post_2010", "full"): 35,
    
    # Unknown (defaults)
    ("unknown", "pre_1978", "unrenovated"): 120,
    ("unknown", "pre_1978", "partial"): 85,
    ("unknown", "pre_1978", "full"): 55,
    ("unknown", "1979_1994", "unrenovated"): 100,
    ("unknown", "1979_1994", "partial"): 75,
    ("unknown", "1979_1994", "full"): 50,
    ("unknown", "1995_2009", "unrenovated"): 75,
    ("unknown", "1995_2009", "partial"): 60,
    ("unknown", "1995_2009", "full"): 40,
    ("unknown", "post_2010", "unrenovated"): 50,
    ("unknown", "post_2010", "partial"): 40,
    ("unknown", "post_2010", "full"): 30,
}

DEFAULT_SPEC_DEMAND = 120  # kWh/(m²·a)

# Default air changes per hour
DEFAULT_N_AIR_CHANGES_H = 0.5  # 1/h


# ============================================================================
# Helper Resolver Functions
# ============================================================================

def _resolve_use_type(row: pd.Series) -> str:
    """
    Resolve building use type from row data.
    
    Returns: "residential_sfh", "residential_mfh", "office", "school", "retail", "unknown"
    """
    # Try different column names and combine them for better detection
    use_type_fields = [
        row.get("use_type"),
        row.get("building_type"),
        row.get("building_function"),
        row.get("gebaeudefunktion"),
    ]
    
    # Combine all non-null values into a single string for matching
    use_type_strs = [str(f).lower() for f in use_type_fields if f is not None and not pd.isna(f)]
    
    if not use_type_strs:
        return "unknown"
    
    combined_str = " ".join(use_type_strs)
    
    # Check for SFH first (more specific)
    if any(term in combined_str for term in ["einfamilien", "single", "sfh", "detached", "single-family"]):
        return "residential_sfh"
    
    # Then check for general residential
    if any(term in combined_str for term in ["wohn", "residential", "housing"]):
        return "residential_mfh"
    
    # Other building types
    if any(term in combined_str for term in ["büro", "office", "commercial"]):
        return "office"
    elif any(term in combined_str for term in ["schule", "school", "education"]):
        return "school"
    elif any(term in combined_str for term in ["handel", "retail", "shop", "store", "verkauf"]):
        return "retail"
    else:
        return "unknown"


def _resolve_construction_band(row: pd.Series) -> str:
    """
    Resolve construction period band from row data.
    
    Returns: "pre_1978", "1979_1994", "1995_2009", "post_2010", "unknown"
    """
    # Try construction_period (textual)
    construction_period = row.get("construction_period") or row.get("construction_type")
    if construction_period is not None and not pd.isna(construction_period):
        period_str = str(construction_period).lower()
        if "pre" in period_str or "vor" in period_str or "before" in period_str:
            return "pre_1978"
        elif "1979" in period_str or "1980" in period_str or "1994" in period_str:
            return "1979_1994"
        elif "1995" in period_str or "2009" in period_str:
            return "1995_2009"
        elif "2010" in period_str or "post" in period_str or "nach" in period_str:
            return "post_2010"
    
    # Try year_built (numeric)
    year_built = (
        row.get("year_built") or
        row.get("year_of_construction") or
        row.get("baujahr") or
        row.get("construction_year")
    )
    
    if year_built is not None and not pd.isna(year_built):
        try:
            year = int(float(year_built))
            if year < 1978:
                return "pre_1978"
            elif 1979 <= year <= 1994:
                return "1979_1994"
            elif 1995 <= year <= 2009:
                return "1995_2009"
            elif year >= 2010:
                return "post_2010"
        except (ValueError, TypeError):
            pass
    
    return "unknown"


def _resolve_renovation_state(row: pd.Series) -> str:
    """
    Resolve renovation state from row data.
    
    Returns: "unrenovated", "partial", "full", "unknown"
    """
    renovation = (
        row.get("renovation_state") or
        row.get("renovation_status") or
        row.get("sanierungszustand") or
        row.get("sanierung")
    )
    
    if renovation is None or pd.isna(renovation):
        return "unknown"
    
    renovation_str = str(renovation).lower()
    
    if any(term in renovation_str for term in ["full", "voll", "complete", "deep", "tief"]):
        return "full"
    elif any(term in renovation_str for term in ["partial", "teil", "partly", "teilweise"]):
        return "partial"
    elif any(term in renovation_str for term in ["none", "keine", "unrenovated", "unsaniert"]):
        return "unrenovated"
    else:
        return "unknown"


# ============================================================================
# Main Function
# ============================================================================

def estimate_envelope(buildings_df: Union[pd.DataFrame, gpd.GeoDataFrame]) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Estimate building envelope parameters and annual heat demand.
    
    Input: buildings_df (pd.DataFrame or gpd.GeoDataFrame)
    Output: buildings_with_env_df (same rows, new columns added)
    
    Required input columns (minimum):
    - building_id (required)
    
    Optional input columns (used if present):
    - use_type or building_type or building_function
    - construction_period or year_built or year_of_construction
    - renovation_state
    - floor_area_m2 or floor_area or heated_area_m2
    
    Output columns added:
    - u_wall: Wall U-value (W/(m²·K))
    - u_roof: Roof U-value (W/(m²·K))
    - u_window: Window U-value (W/(m²·K))
    - n_air_changes_h: Air changes per hour (1/h)
    - internal_gains_w_m2: Internal gains (W/m²)
    - specific_heat_demand_kwh_m2a: Specific heat demand (kWh/(m²·a))
    - annual_heat_demand_kwh_a: Annual heat demand (kWh/a)
    
    Args:
        buildings_df: DataFrame or GeoDataFrame with building data
        
    Returns:
        Same type as input, with envelope parameters added as new columns
    """
    # Sanity check: building_id must exist
    if "building_id" not in buildings_df.columns:
        raise ValueError("buildings_df must contain 'building_id' column")
    
    # Create a copy to avoid modifying original
    result_df = buildings_df.copy()
    
    # Initialize output columns
    result_df["u_wall"] = None
    result_df["u_roof"] = None
    result_df["u_window"] = None
    result_df["n_air_changes_h"] = DEFAULT_N_AIR_CHANGES_H
    result_df["internal_gains_w_m2"] = None
    result_df["specific_heat_demand_kwh_m2a"] = None
    result_df["annual_heat_demand_kwh_a"] = None
    result_df["data_incomplete"] = False  # Flag for buildings with missing critical data
    
    # Process each row
    for idx, row in result_df.iterrows():
        # Resolve categories
        use_type = _resolve_use_type(row)
        construction_band = _resolve_construction_band(row)
        renovation_state = _resolve_renovation_state(row)
        
        # Get U-values
        u_key = (use_type, construction_band, renovation_state)
        if u_key in U_TABLE:
            u_values = U_TABLE[u_key]
            result_df.at[idx, "u_wall"] = u_values["u_wall"]
            result_df.at[idx, "u_roof"] = u_values["u_roof"]
            result_df.at[idx, "u_window"] = u_values["u_window"]
        else:
            # Use defaults
            result_df.at[idx, "u_wall"] = DEFAULT_U["u_wall"]
            result_df.at[idx, "u_roof"] = DEFAULT_U["u_roof"]
            result_df.at[idx, "u_window"] = DEFAULT_U["u_window"]
        
        # Get internal gains
        result_df.at[idx, "internal_gains_w_m2"] = GAINS_TABLE.get(use_type, GAINS_TABLE["unknown"])
        
        # Get specific heat demand
        spec_key = (use_type, construction_band, renovation_state)
        if spec_key in SPEC_DEMAND_TABLE:
            result_df.at[idx, "specific_heat_demand_kwh_m2a"] = SPEC_DEMAND_TABLE[spec_key]
        else:
            result_df.at[idx, "specific_heat_demand_kwh_m2a"] = DEFAULT_SPEC_DEMAND
        
        # Calculate annual heat demand
        # RISK MITIGATION: Preserve existing annual demand if present (e.g., from Wärmekataster)
        existing_annual = (
            row.get("annual_heat_demand_kwh_a") or
            row.get("baseline_heat_demand_kwh_a") or
            row.get("baseline_heat_kwh_a") or
            row.get("annual_heat_kwh_a") or
            None
        )
        
        # If existing annual demand is valid, preserve it (skip typology-based calculation)
        preserve_existing = False
        if existing_annual is not None and not pd.isna(existing_annual):
            try:
                existing_annual_float = float(existing_annual)
                if existing_annual_float > 0:
                    result_df.at[idx, "annual_heat_demand_kwh_a"] = existing_annual_float
                    preserve_existing = True
            except (ValueError, TypeError):
                # Invalid existing value, proceed with calculation
                pass
        
        # If we preserved existing annual demand, skip typology-based calculation
        if preserve_existing:
            continue
        
        # No valid existing annual demand → compute from typology
        # Try to get area
        area = (
            row.get("heated_area_m2") or
            row.get("floor_area_m2") or
            row.get("floor_area") or
            row.get("net_floor_area") or
            None
        )
        
        # RISK MITIGATION: If area missing, try fallback strategies
        if area is None or pd.isna(area):
            # Fallback 1: Try to infer area from volume/footprint
            volume = row.get("volume_m3") or row.get("building_volume")
            footprint_area = None
            
            # Try to compute footprint from geometry if available
            if hasattr(result_df, 'geometry') and idx in result_df.index:
                try:
                    geom = result_df.at[idx, 'geometry']
                    if geom is not None and not pd.isna(geom):
                        footprint_area = geom.area
                except (AttributeError, TypeError):
                    pass
            
            # Fallback 2: Use existing baseline annual demand to infer area
            if existing_annual is not None and not pd.isna(existing_annual):
                try:
                    existing_annual_float = float(existing_annual)
                    spec_demand = result_df.at[idx, "specific_heat_demand_kwh_m2a"]
                    if spec_demand > 0:
                        inferred_area = existing_annual_float / spec_demand
                        if inferred_area > 0:
                            area = inferred_area
                            warnings.warn(
                                f"Building {row.get('building_id', idx)} missing area, "
                                f"inferred from existing annual demand: {inferred_area:.1f} m²",
                                UserWarning
                            )
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
            
            # Fallback 3: Estimate from volume (if available)
            if area is None and volume is not None and not pd.isna(volume):
                try:
                    volume_float = float(volume)
                    # Rough estimate: area ≈ volume / 2.5 (typical ceiling height)
                    estimated_area = volume_float / 2.5
                    if estimated_area > 0:
                        area = estimated_area
                        warnings.warn(
                            f"Building {row.get('building_id', idx)} missing area, "
                            f"estimated from volume: {estimated_area:.1f} m²",
                            UserWarning
                        )
                except (ValueError, TypeError):
                    pass
            
            # Fallback 4: Use footprint area (if available)
            if area is None and footprint_area is not None and footprint_area > 0:
                # Rough estimate: floor area ≈ footprint * 1.5 (typical multi-story factor)
                estimated_area = footprint_area * 1.5
                area = estimated_area
                warnings.warn(
                    f"Building {row.get('building_id', idx)} missing area, "
                    f"estimated from footprint: {estimated_area:.1f} m²",
                    UserWarning
                )
        
        # Calculate annual demand from area (if available)
        if area is not None and not pd.isna(area):
            try:
                area_float = float(area)
                if area_float > 0:
                    spec_demand = result_df.at[idx, "specific_heat_demand_kwh_m2a"]
                    annual = spec_demand * area_float
                    result_df.at[idx, "annual_heat_demand_kwh_a"] = annual
                else:
                    warnings.warn(
                        f"Building {row.get('building_id', idx)} has non-positive area: {area_float}",
                        UserWarning
                    )
                    result_df.at[idx, "annual_heat_demand_kwh_a"] = pd.NA
                    result_df.at[idx, "data_incomplete"] = True
            except (ValueError, TypeError):
                warnings.warn(
                    f"Building {row.get('building_id', idx)} has invalid area value: {area}",
                    UserWarning
                )
                result_df.at[idx, "annual_heat_demand_kwh_a"] = pd.NA
                result_df.at[idx, "data_incomplete"] = True
        else:
            # Area missing and all fallbacks failed
            building_id = row.get('building_id', idx)
            warnings.warn(
                f"Building {building_id} missing area data and all fallbacks failed. "
                f"annual_heat_demand_kwh_a set to NaN. Building marked as data_incomplete.",
                UserWarning
            )
            result_df.at[idx, "annual_heat_demand_kwh_a"] = pd.NA
            result_df.at[idx, "data_incomplete"] = True
    
    # Sanity checks on output
    assert "u_wall" in result_df.columns, "Output must contain 'u_wall' column"
    assert "u_roof" in result_df.columns, "Output must contain 'u_roof' column"
    assert "u_window" in result_df.columns, "Output must contain 'u_window' column"
    assert "annual_heat_demand_kwh_a" in result_df.columns, "Output must contain 'annual_heat_demand_kwh_a' column"
    
    # Check that annual_heat_demand_kwh_a is non-negative where it exists
    annual_demand = result_df["annual_heat_demand_kwh_a"]
    if annual_demand.notna().any():
        negative_mask = annual_demand < 0
        if negative_mask.any():
            n_negative = negative_mask.sum()
            warnings.warn(
                f"Found {n_negative} buildings with negative annual_heat_demand_kwh_a. "
                f"This should not happen. Check area and specific_demand values.",
                UserWarning
            )
    
    return result_df


def classify_typology(data):
    """
    Classify energy system typology based on data characteristics.
    
    Args:
        data: Input data for classification
        
    Returns:
        Typology classification result
    """
    # TODO: Implement typology classification
    pass


def get_typology_features(data):
    """
    Extract features for typology classification.
    
    Args:
        data: Input data
        
    Returns:
        Feature vector for classification
    """
    # TODO: Implement feature extraction
    pass

