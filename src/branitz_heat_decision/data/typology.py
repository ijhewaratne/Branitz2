import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
import logging
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Legacy TABULA-like U-values table (derived from `Legacy/fromDifferentThesis/gebaeudedaten/uwerte_berechnungV2.py`)
# Stored as JSON list of dicts in `uwerte3.json`.
def _default_uwerte3_path() -> Optional[Path]:
    """
    Locate `uwerte3.json` deterministically.

    Search order:
      1) data/raw/uwerte3.json (preferred for pipeline reproducibility)
      2) Legacy/fromDifferentThesis/gebaeudedaten/uwerte3.json (repo-shipped legacy)
    """
    try:
        repo_root = Path(__file__).resolve().parents[3]
    except Exception:
        repo_root = Path(".").resolve()

    candidates = [
        repo_root / "data" / "raw" / "uwerte3.json",
        repo_root / "Legacy" / "fromDifferentThesis" / "gebaeudedaten" / "uwerte3.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_uwerte3_table(path: Path) -> Dict[int, Dict[str, float]]:
    """
    Load legacy U-values table keyed by integer building_code.

    Output keys (when present):
      u_ausenwand, u_fenster, u_dach, u_bodenplatte,
      innentemperatur, luftwechselrate, fensterflaechenanteil
    """
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, list):
        raise ValueError("uwerte3.json must be a list of dicts")
    out: Dict[int, Dict[str, float]] = {}
    for rec in obj:
        if not isinstance(rec, dict):
            continue
        try:
            code = int(rec.get("code"))
        except Exception:
            continue
        # store only numeric keys we use
        out[code] = {
            "fensterflaechenanteil": float(rec.get("fensterflaechenanteil", 0.2)),
            "u_ausenwand": float(rec.get("u_ausenwand", np.nan)),
            "u_fenster": float(rec.get("u_fenster", np.nan)),
            "u_dach": float(rec.get("u_dach", np.nan)),
            "u_bodenplatte": float(rec.get("u_bodenplatte", np.nan)),
            "innentemperatur": float(rec.get("innentemperatur", 20.0)),
            "luftwechselrate": float(rec.get("luftwechselrate", 0.5)),
        }
    return out


def _map_sanierungszustand_to_renovation_state(z: object) -> str:
    """Map legacy gebaeudeanalyse states to our normalized labels."""
    s = str(z).strip().lower()
    if s in {"vollsaniert", "voll saniert", "fully_renovated", "full"}:
        return "full"
    if s in {"teilsaniert", "teil saniert", "partial"}:
        return "partial"
    if s in {"unsaniert", "unrenovated"}:
        return "unrenovated"
    return "unrenovated"

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


def _classify_use_type_from_code(building_code: object, building_function: object) -> str:
    """
    Prefer deterministic mapping from numeric building_code when available.
    Falls back to building_function heuristics.
    """
    try:
        code = int(str(building_code).strip())
        # residential buckets (Wohngebäude + mixed residential)
        if 1000 <= code < 1200:
            return "residential_sfh"
        # pure commercial / services
        if 2000 <= code < 2400:
            return "retail"
        if 3000 <= code < 3300:
            return "office"
    except Exception:
        pass
    return classify_use_type(str(building_function))

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
        if 'building_code' in df.columns or 'building_function' in df.columns:
            df['use_type'] = df.apply(
                lambda r: _classify_use_type_from_code(r.get("building_code"), r.get("building_function")),
                axis=1,
            )
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
        if "sanierungszustand" in df.columns:
            df["renovation_state"] = df["sanierungszustand"].apply(_map_sanierungszustand_to_renovation_state)
        else:
            df['renovation_state'] = 'unrenovated'

    # Load legacy U-values table if available
    uwerte3_path = _default_uwerte3_path()
    uwerte3: Optional[Dict[int, Dict[str, float]]] = None
    if uwerte3_path is not None:
        try:
            uwerte3 = _load_uwerte3_table(uwerte3_path)
            logger.info(f"Loaded uwerte3.json for U-values: {uwerte3_path}")
        except Exception as e:
            logger.warning(f"Failed to load uwerte3.json ({uwerte3_path}): {e}")
            uwerte3 = None
    
    # Estimate U-values and specific heat demand
    u_wall_values = []
    u_roof_values = []
    u_window_values = []
    specific_demand_values = []
    t_indoor_values = []
    air_change_values = []
    window_share_values = []
    h_trans_values = []
    h_vent_values = []
    h_total_values = []
    
    for idx, row in df.iterrows():
        key = (
            row.get('use_type', 'residential_sfh'),
            row.get('construction_band', 'unknown'),
            row.get('renovation_state', 'unrenovated')
        )

        # Prefer uwerte3 mapping by building_code if available
        uvals3 = None
        if uwerte3 is not None:
            try:
                code = int(str(row.get("building_code")).strip())
                uvals3 = uwerte3.get(code)
            except Exception:
                uvals3 = None

        if uvals3 is not None and np.isfinite(uvals3.get("u_ausenwand", np.nan)):
            u_wall_values.append(float(uvals3.get("u_ausenwand", 0.5)))
            u_roof_values.append(float(uvals3.get("u_dach", 0.4)))
            u_window_values.append(float(uvals3.get("u_fenster", 1.5)))
            t_indoor_values.append(float(uvals3.get("innentemperatur", 20.0)))
            air_change_values.append(float(uvals3.get("luftwechselrate", 0.5)))
            window_share_values.append(float(uvals3.get("fensterflaechenanteil", 0.2)))
        else:
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
            t_indoor_values.append(20.0)
            air_change_values.append(0.5)
            window_share_values.append(0.2)
        
        if key in SPEC_DEMAND_TABLE:
            specific_demand_values.append(SPEC_DEMAND_TABLE[key])
        else:
            specific_demand_values.append(100)

        # Precompute heat-loss coefficient if we have geometry-related fields
        try:
            wall_area = float(row.get("wall_area_m2")) if row.get("wall_area_m2") is not None else np.nan
            footprint = float(row.get("footprint_m2")) if row.get("footprint_m2") is not None else np.nan
            volume = float(row.get("volume_m3")) if row.get("volume_m3") is not None else np.nan
        except Exception:
            wall_area, footprint, volume = np.nan, np.nan, np.nan

        u_wall = float(u_wall_values[-1])
        u_roof = float(u_roof_values[-1])
        # u_bodenplatte from uwerte3 when available; else approximate with roof U
        u_floor = float(uvals3.get("u_bodenplatte", u_roof)) if uvals3 is not None else float(u_roof)

        if np.isfinite(wall_area) and np.isfinite(footprint) and wall_area > 0 and footprint > 0:
            roof_area = footprint
            floor_area = footprint
            h_trans = (u_wall * wall_area) + (u_roof * roof_area) + (u_floor * floor_area)  # W/K
        else:
            h_trans = np.nan

        ach = float(air_change_values[-1])
        if np.isfinite(volume) and volume > 0 and np.isfinite(ach) and ach >= 0:
            h_vent = 0.33 * ach * volume  # W/K (approx.)
        else:
            h_vent = np.nan

        h_trans_values.append(float(h_trans) if np.isfinite(h_trans) else np.nan)
        h_vent_values.append(float(h_vent) if np.isfinite(h_vent) else np.nan)
        if np.isfinite(h_trans) or np.isfinite(h_vent):
            ht = (0.0 if not np.isfinite(h_trans) else h_trans) + (0.0 if not np.isfinite(h_vent) else h_vent)
            h_total_values.append(float(ht))
        else:
            h_total_values.append(np.nan)
    
    df['u_wall'] = u_wall_values
    df['u_roof'] = u_roof_values
    df['u_window'] = u_window_values
    df['specific_heat_demand_kwh_m2a'] = specific_demand_values
    df["t_indoor_c"] = t_indoor_values
    df["air_change_1_h"] = air_change_values
    df["window_area_share"] = window_share_values
    df["h_trans_w_per_k"] = h_trans_values
    df["h_vent_w_per_k"] = h_vent_values
    df["h_total_w_per_k"] = h_total_values
    
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