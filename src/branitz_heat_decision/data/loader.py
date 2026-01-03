import geopandas as gpd
import pandas as pd
from pathlib import Path
from typing import Union, Dict, Any
import logging

logger = logging.getLogger(__name__)

class DataValidationError(Exception):
    """Custom exception for data validation failures."""
    pass

def load_buildings_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """
    Load buildings from GeoJSON with comprehensive validation.
    
    Args:
        path: Path to buildings.geojson
        
    Returns:
        GeoDataFrame with validated and standardized columns
        
    Raises:
        DataValidationError: If validation fails
        FileNotFoundError: If file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Buildings file not found: {path}")
    
    logger.info(f"Loading buildings from {path}")
    gdf = gpd.read_file(path)
    
    # --- VALIDATION RULES ---
    
    # 1. Must have building_id column
    if 'building_id' not in gdf.columns:
        # Try to infer from other common names
        id_candidates = ['id', 'gid', 'objectid', 'building_id']
        found = False
        for candidate in id_candidates:
            if candidate in gdf.columns:
                gdf = gdf.rename(columns={candidate: 'building_id'})
                found = True
                logger.warning(f"Renamed '{candidate}' to 'building_id'")
                break
        
        if not found:
            raise DataValidationError(
                f"No building ID column found. Tried: {id_candidates}. "
                f"Available columns: {list(gdf.columns)}"
            )
    
    # 2. building_id must be unique
    if gdf['building_id'].duplicated().any():
        dups = gdf['building_id'][gdf['building_id'].duplicated()].unique()
        raise DataValidationError(
            f"Duplicate building_id found: {dups[:5]}"
        )
    
    # 3. Must have geometry column
    if gdf.geometry is None:
        raise DataValidationError("No geometry column found")
    
    # 4. Geometry must be Polygon or MultiPolygon (not points)
    invalid_geom_types = gdf.geometry.type[~gdf.geometry.type.isin(['Polygon', 'MultiPolygon'])]
    if not invalid_geom_types.empty:
        raise DataValidationError(
            f"Invalid geometry types found: {invalid_geom_types.unique()}. "
            "Expected only Polygon or MultiPolygon for building footprints."
        )
    
    # 5. CRS must be projected (not geographic)
    if gdf.crs is None:
        raise DataValidationError("No CRS defined. Must be a projected CRS (e.g., EPSG:25833)")
    
    if gdf.crs.is_geographic:
        raise DataValidationError(
            f"Geographic CRS detected ({gdf.crs}). "
            "Must use projected CRS for distance calculations."
        )
    
    # 6. Standardize column names
    column_mapping = {
        'floor_area': 'floor_area_m2',
        'area': 'floor_area_m2',
        'heated_area': 'floor_area_m2',
        'year_built': 'year_of_construction',
        'baujahr': 'year_of_construction',
        'construction_year': 'year_of_construction',
        'heat_demand': 'annual_heat_demand_kwh_a',
        'wärmebedarf': 'annual_heat_demand_kwh_a',
    }
    
    gdf = gdf.rename(columns={k: v for k, v in column_mapping.items() if k in gdf.columns})
    
    # 7. Ensure required numeric columns exist and are valid
    required_numerics = ['floor_area_m2', 'year_of_construction', 'annual_heat_demand_kwh_a']
    for col in required_numerics:
        if col in gdf.columns:
            # Check for NaN/inf
            if gdf[col].isna().any() or np.isinf(gdf[col]).any():
                raise DataValidationError(f"Invalid values (NaN/inf) in {col}")
            
            # Check for negative values
            if (gdf[col] < 0).any():
                raise DataValidationError(f"Negative values found in {col}")
    
    # 8. Add metadata
    gdf.attrs['source_file'] = str(path)
    gdf.attrs['validated_at'] = pd.Timestamp.now().isoformat()
    gdf.attrs['validation_rules'] = 'phase1_buildings_v1'
    
    logger.info(f"Successfully loaded {len(gdf)} buildings")
    return gdf


def load_streets_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """
    Load streets from GeoJSON with validation.
    
    Args:
        path: Path to streets.geojson
        
    Returns:
        GeoDataFrame with validated LineString geometries
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Streets file not found: {path}")
    
    logger.info(f"Loading streets from {path}")
    gdf = gpd.read_file(path)
    
    # --- VALIDATION RULES ---
    
    # 1. Standardize column names
    if 'name' in gdf.columns:
        gdf = gdf.rename(columns={'name': 'street_name'})
    
    if 'id' in gdf.columns:
        gdf = gdf.rename(columns={'id': 'street_id'})
    
    # 2. Must have either street_name or street_id
    if not ('street_name' in gdf.columns or 'street_id' in gdf.columns):
        raise DataValidationError(
            "No street identifier found. Need 'street_name' or 'street_id' column."
        )
    
    # 3. All geometries must be LineString (not Polygon, not Point)
    if not gdf.geometry.type.isin(['LineString', 'MultiLineString']).all():
        invalid = gdf.geometry.type[~gdf.geometry.type.isin(['LineString', 'MultiLineString'])].unique()
        raise DataValidationError(
            f"Invalid street geometry types: {invalid}. Expected LineString or MultiLineString."
        )
    
    # 4. Explode MultiLineString to LineString
    if (gdf.geometry.type == 'MultiLineString').any():
        logger.info("Exploding MultiLineString geometries to LineString")
        gdf = gdf.explode(index_parts=True).reset_index(drop=True)
    
    # 5. CRS must be projected and match buildings
    if gdf.crs is None:
        raise DataValidationError("No CRS defined for streets")
    
    if gdf.crs.is_geographic:
        raise DataValidationError(f"Geographic CRS detected for streets: {gdf.crs}")
    
    # 6. Compute and validate length
    gdf['length_m'] = gdf.geometry.length
    if (gdf['length_m'] <= 0).any():
        raise DataValidationError("Streets with zero or negative length found")
    
    # 7. Add unique street_id if missing
    if 'street_id' not in gdf.columns:
        gdf['street_id'] = [f"street_{i:06d}" for i in range(len(gdf))]
        logger.warning("Generated synthetic street_id")
    
    # 8. Add metadata
    gdf.attrs['source_file'] = str(path)
    gdf.attrs['validated_at'] = pd.Timestamp.now().isoformat()
    gdf.attrs['validation_rules'] = 'phase1_streets_v1'
    
    logger.info(f"Successfully loaded {len(gdf)} street segments")
    return gdf


def load_power_grid(
    lines_path: Union[str, Path],
    substations_path: Union[str, Path]
) -> Dict[str, gpd.GeoDataFrame]:
    """
    Load LV power grid from GeoJSON files.
    
    Args:
        lines_path: Path to power_lines.geojson
        substations_path: Path to power_substations.geojson
        
    Returns:
        Dict with 'lines' and 'substations' GeoDataFrames
    """
    lines_path = Path(lines_path)
    substations_path = Path(substations_path)
    
    if not lines_path.exists():
        raise FileNotFoundError(f"Power lines file not found: {lines_path}")
    if not substations_path.exists():
        raise FileNotFoundError(f"Substations file not found: {substations_path}")
    
    logger.info(f"Loading power grid from {lines_path} and {substations_path}")
    
    # Load lines
    lines = gpd.read_file(lines_path)
    if 'voltage_kv' not in lines.columns:
        lines['voltage_kv'] = 0.4  # Default LV
        logger.warning("No voltage_kv column, defaulting to 0.4 kV")
    
    # Load substations
    substations = gpd.read_file(substations_path)
    if 'capacity_kva' not in substations.columns:
        substations['capacity_kva'] = 630  # Default
        logger.warning("No capacity_kva column, defaulting to 630 kVA")
    
    # Validate CRS
    if lines.crs != substations.crs:
        logger.warning(f"CRS mismatch: lines={lines.crs}, substations={substations.crs}")
        # Reproject substations to match lines
        substations = substations.to_crs(lines.crs)
    
    # Add metadata
    lines.attrs['source_file'] = str(lines_path)
    substations.attrs['source_file'] = str(substations_path)
    
    return {
        'lines': lines,
        'substations': substations
    }