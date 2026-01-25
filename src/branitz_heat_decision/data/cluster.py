import geopandas as gpd
import pandas as pd
import numpy as np
import json
import warnings
from typing import Dict, List, Any, Optional, Tuple, Union
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

def aggregate_cluster_profiles(
    hourly_profiles: pd.DataFrame,
    cluster_map: pd.DataFrame
) -> Dict[str, pd.Series]:
    """
    Aggregate building-level hourly profiles to cluster-level.
    
    For each cluster:
    - Extract building IDs belonging to that cluster
    - Sum hourly profiles across all buildings in the cluster
    - Return aggregated profile as Series
    
    Args:
        hourly_profiles: DataFrame with shape [8760 × n_buildings]
            Index: 0-8759 (hour of year)
            Columns: building_id (one per building)
            Values: Heat demand in kW_th
        cluster_map: DataFrame with columns ['building_id', 'cluster_id']
            Maps each building to exactly one cluster
            Accepts aliases: 'street_id' or 'street_cluster' as cluster_id
        
    Returns:
        Dictionary: {cluster_id: Series(length 8760)}
        Each Series contains aggregated hourly heat demand for the cluster (kW_th)
    
    Raises:
        ValueError: If required columns are missing
    """
    # Validate inputs
    if len(hourly_profiles) != 8760:
        raise ValueError(
            f"hourly_profiles must have 8760 rows, got {len(hourly_profiles)}"
        )
    
    if "building_id" not in cluster_map.columns:
        raise ValueError("cluster_map must contain 'building_id' column")
    
    # Resolve cluster_id column (handle aliases)
    cluster_id_col = None
    for col_name in ['cluster_id', 'street_id', 'street_cluster']:
        if col_name in cluster_map.columns:
            cluster_id_col = col_name
            break
    
    if cluster_id_col is None:
        raise ValueError(
            "cluster_map must contain one of: 'cluster_id', 'street_id', 'street_cluster'"
        )
    
    # Create mapping: building_id -> cluster_id
    building_to_cluster = dict(
        zip(cluster_map['building_id'], cluster_map[cluster_id_col])
    )
    
    # Get unique clusters
    unique_clusters = cluster_map[cluster_id_col].unique()
    
    # Initialize result dictionary
    cluster_profiles = {}
    
    # Aggregate for each cluster
    for cluster_id in unique_clusters:
        # Find buildings in this cluster
        cluster_buildings = cluster_map[
            cluster_map[cluster_id_col] == cluster_id
        ]['building_id'].tolist()
        
        # Filter to buildings that exist in hourly_profiles
        available_buildings = [
            b for b in cluster_buildings if b in hourly_profiles.columns
        ]
        
        if len(available_buildings) == 0:
            warnings.warn(
                f"Cluster {cluster_id} has no buildings in hourly_profiles. "
                f"Skipping or filling with zeros.",
                UserWarning
            )
            # Create zero series
            cluster_profiles[cluster_id] = pd.Series(
                0.0,
                index=hourly_profiles.index,
                name=cluster_id
            )
            continue
        
        # Sum profiles across buildings in cluster
        cluster_profile = hourly_profiles[available_buildings].sum(axis=1)
        cluster_profiles[cluster_id] = cluster_profile
    
    logger.info(f"Aggregated profiles for {len(cluster_profiles)} clusters")
    return cluster_profiles


def compute_design_and_topn(
    cluster_profiles: Dict[str, pd.Series],
    N: int = 10,
    source_profiles: str = "hourly_heat_profiles.parquet",
    version: str = "v1"
) -> Dict:
    """
    Compute design hour and top-N hours for each cluster.
    
    For each cluster:
    - Design hour: hour with maximum load
    - Top-N hours: N hours with highest loads (sorted descending)
    
    Args:
        cluster_profiles: Dictionary {cluster_id: Series(8760)}
            Each Series contains hourly aggregated heat demand
        N: Number of top hours to extract (default: 10)
        source_profiles: Source file name for metadata (default: "hourly_heat_profiles.parquet")
        version: Version string for metadata (default: "v1")
        
    Returns:
        Dictionary ready for JSON serialization:
        {
            "clusters": {
                "cluster_id": {
                    "design_hour": int,
                    "design_load_kw": float,
                    "topn_hours": [int, ...],
                    "topn_loads_kw": [float, ...]
                },
                ...
            },
            "meta": {
                "N": int,
                "source_profiles": str,
                "version": str
            }
        }
    """
    result = {
        "clusters": {},
        "meta": {
            "N": N,
            "source_profiles": source_profiles,
            "version": version
        }
    }
    
    for cluster_id, series in cluster_profiles.items():
        if len(series) != 8760:
            warnings.warn(
                f"Cluster {cluster_id} profile has {len(series)} hours, expected 8760. "
                f"Skipping.",
                UserWarning
            )
            continue
        
        # Design hour: hour with maximum load
        design_hour = int(series.idxmax())
        design_load_kw = float(series.max())
        
        # Top-N hours: sort descending by load
        top_n = series.sort_values(ascending=False).head(N)
        topn_hours = [int(i) for i in top_n.index]
        topn_loads_kw = [float(v) for v in top_n.values]
        
        result["clusters"][cluster_id] = {
            "design_hour": design_hour,
            "design_load_kw": design_load_kw,
            "topn_hours": topn_hours,
            "topn_loads_kw": topn_loads_kw
        }
    
    logger.info(f"Computed design/topn for {len(result['clusters'])} clusters")
    return result


def create_cluster_summary(
    cluster_profiles: Dict[str, pd.Series],
    cluster_map: pd.DataFrame,
    buildings_df: pd.DataFrame,
    design_topn_dict: Dict
) -> pd.DataFrame:
    """
    Create summary table with one row per cluster.
    
    Args:
        cluster_profiles: Dictionary {cluster_id: Series(8760)} from aggregate_cluster_profiles
        cluster_map: DataFrame with building_id and cluster_id columns
        buildings_df: DataFrame with building_id and annual_heat_demand_kwh_a
        design_topn_dict: Dictionary from compute_design_and_topn
        
    Returns:
        DataFrame with columns:
        - cluster_id
        - n_buildings
        - annual_heat_kwh_a (sum of building annual)
        - design_hour
        - design_load_kw
        - topn_mean_kw
        - topn_min_kw
        - topn_max_kw
    """
    # Resolve cluster_id column
    cluster_id_col = None
    for col_name in ['cluster_id', 'street_id', 'street_cluster']:
        if col_name in cluster_map.columns:
            cluster_id_col = col_name
            break
    
    if cluster_id_col is None:
        raise ValueError(
            "cluster_map must contain one of: 'cluster_id', 'street_id', 'street_cluster'"
        )
    
    # Initialize result list
    summary_rows = []
    
    # Process each cluster
    for cluster_id in cluster_profiles.keys():
        # Count buildings
        cluster_buildings = cluster_map[
            cluster_map[cluster_id_col] == cluster_id
        ]['building_id'].tolist()
        n_buildings = len(cluster_buildings)
        
        # Sum annual heat from buildings
        if 'annual_heat_demand_kwh_a' in buildings_df.columns:
            cluster_buildings_df = buildings_df[
                buildings_df['building_id'].isin(cluster_buildings)
            ]
            annual_heat_kwh_a = cluster_buildings_df['annual_heat_demand_kwh_a'].sum()
        else:
            # Fallback: sum from hourly profile
            annual_heat_kwh_a = cluster_profiles[cluster_id].sum()
        
        # Get design and top-N from design_topn_dict
        if cluster_id in design_topn_dict.get("clusters", {}):
            cluster_info = design_topn_dict["clusters"][cluster_id]
            design_hour = cluster_info["design_hour"]
            design_load_kw = cluster_info["design_load_kw"]
            topn_loads_kw = cluster_info["topn_loads_kw"]
            
            topn_mean_kw = sum(topn_loads_kw) / len(topn_loads_kw) if topn_loads_kw else 0.0
            topn_min_kw = min(topn_loads_kw) if topn_loads_kw else 0.0
            topn_max_kw = max(topn_loads_kw) if topn_loads_kw else 0.0
        else:
            # Fallback: compute from profile
            series = cluster_profiles[cluster_id]
            design_hour = int(series.idxmax())
            design_load_kw = float(series.max())
            top_n = series.sort_values(ascending=False).head(10)
            topn_loads_kw = [float(v) for v in top_n.values]
            topn_mean_kw = sum(topn_loads_kw) / len(topn_loads_kw) if topn_loads_kw else 0.0
            topn_min_kw = min(topn_loads_kw) if topn_loads_kw else 0.0
            topn_max_kw = max(topn_loads_kw) if topn_loads_kw else 0.0
        
        summary_rows.append({
            "cluster_id": cluster_id,
            "n_buildings": n_buildings,
            "annual_heat_kwh_a": float(annual_heat_kwh_a),
            "design_hour": design_hour,
            "design_load_kw": design_load_kw,
            "topn_mean_kw": topn_mean_kw,
            "topn_min_kw": topn_min_kw,
            "topn_max_kw": topn_max_kw
        })
    
    summary_df = pd.DataFrame(summary_rows)
    logger.info(f"Created summary for {len(summary_df)} clusters")
    return summary_df


def extract_street_from_address(address_data) -> Optional[str]:
    """
    Extract street name from building address data.
    
    Args:
        address_data: Address data from buildings (can be list of dicts, dict, or string)
        
    Returns:
        Street name string, or None if not found
    """
    if address_data is None:
        return None
    
    # Handle list of addresses (take first one)
    if isinstance(address_data, list):
        if len(address_data) == 0:
            return None
        address_data = address_data[0]
    
    # Handle dict format: {'str': 'Parkstraße', 'hnr': 6, ...}
    if isinstance(address_data, dict):
        if 'str' in address_data:
            return address_data['str']
        elif 'street' in address_data:
            return address_data['street']
        elif 'strasse' in address_data:
            return address_data['strasse']
    
    # Handle string format (full address)
    if isinstance(address_data, str):
        # Try to extract street name (simple parsing)
        # Format might be "Parkstraße 6" or "Parkstraße 6, 03042 Cottbus"
        parts = address_data.split(',')[0].strip()  # Take part before comma
        # Remove house number (last word if it's numeric)
        words = parts.split()
        if len(words) > 1 and words[-1].isdigit():
            return ' '.join(words[:-1])
        return parts
    
    return None


def normalize_street_name(name: str) -> str:
    """
    Normalize street name for matching.
    
    Handles:
    - Case normalization (uppercase)
    - German character variations (ß -> SS, umlauts)
    - Remove special characters
    - Handle abbreviations (Str. -> Strasse, St. -> Strasse)
    
    Args:
        name: Street name string
        
    Returns:
        Normalized street name
    """
    if not name or not isinstance(name, str):
        return ""
    
    # Convert to uppercase
    normalized = name.upper().strip()
    
    # Replace German characters
    replacements = {
        'Ä': 'AE',
        'Ö': 'OE',
        'Ü': 'UE',
        'ß': 'SS',
        'ẞ': 'SS',
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    
    # Handle common abbreviations
    # Remove trailing dots and normalize
    normalized = normalized.rstrip('.')
    abbreviations = {
        'STR.': 'STRASSE',
        'STR': 'STRASSE',
        'ST.': 'STRASSE',
    }
    for abbrev, full in abbreviations.items():
        # Replace at end of string
        if normalized.endswith(' ' + abbrev):
            normalized = normalized[:-len(abbrev)-1] + ' ' + full
        elif normalized.endswith(abbrev):
            normalized = normalized[:-len(abbrev)] + full
        # Replace in middle (with spaces)
        normalized = normalized.replace(' ' + abbrev + ' ', ' ' + full + ' ')
    
    # Remove extra whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized


def match_buildings_to_streets(
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    max_distance_m: float = 500.0
) -> pd.DataFrame:
    """
    Match buildings to streets based on address data and spatial proximity.
    
    Args:
        buildings: GeoDataFrame with building data (must have 'adressen' column)
        streets: GeoDataFrame with street data (must have 'street_name' or similar)
        max_distance_m: Maximum distance for spatial fallback matching
        
    Returns:
        DataFrame with columns: ['building_id', 'street_name', 'street_normalized', 'matched_method']
    """
    matches = []
    
    # Get street name column from streets
    street_name_col = None
    for col in ['street_name', 'name', 'strasse', 'str']:
        if col in streets.columns:
            street_name_col = col
            break
    
    if street_name_col is None:
        raise ValueError("Streets GeoDataFrame must have a street name column")
    
    # Create normalized street names lookup
    street_normalized_map = {}
    street_name_map = {}
    for idx, row in streets.iterrows():
        street_name = str(row[street_name_col])
        normalized = normalize_street_name(street_name)
        street_normalized_map[normalized] = street_name
        street_name_map[street_name] = idx
    
    # Ensure buildings are in same CRS as streets for spatial operations
    if buildings.crs != streets.crs:
        buildings_for_spatial = buildings.to_crs(streets.crs)
    else:
        buildings_for_spatial = buildings
    
    matched_count = 0
    unmatched_count = 0
    
    for idx, (building_idx, building) in enumerate(buildings.iterrows()):
        building_id = building.get('building_id', building_idx)
        
        # Extract street name from address
        address_data = building.get('adressen', None)
        street_name_from_address = extract_street_from_address(address_data)
        
        matched_street = None
        match_method = None
        
        if street_name_from_address:
            normalized_address_street = normalize_street_name(street_name_from_address)
            
            # Try exact normalized match
            if normalized_address_street in street_normalized_map:
                matched_street = street_normalized_map[normalized_address_street]
                match_method = 'address_exact'
            else:
                # Try fuzzy match (check if normalized name is contained in street names)
                for norm_street, orig_street in street_normalized_map.items():
                    if normalized_address_street in norm_street or norm_street in normalized_address_street:
                        matched_street = orig_street
                        match_method = 'address_fuzzy'
                        break
        
        # Spatial fallback if address matching failed
        if matched_street is None:
            building_point = buildings_for_spatial.geometry.iloc[idx].centroid
            
            # Find nearest street
            min_dist = float('inf')
            nearest_street_idx = None
            
            for street_idx, street_row in streets.iterrows():
                street_geom = street_row.geometry
                dist = building_point.distance(street_geom)
                if dist < min_dist:
                    min_dist = dist
                    nearest_street_idx = street_idx
            
            if nearest_street_idx is not None and min_dist <= max_distance_m:
                matched_street = streets.loc[nearest_street_idx, street_name_col]
                match_method = 'spatial'
                matched_count += 1
            else:
                unmatched_count += 1
                logger.warning(f"Building {building_id}: No street match found (distance={min_dist:.1f}m)")
        else:
            matched_count += 1
        
        matches.append({
            'building_id': building_id,
            'street_name': matched_street,
            'street_normalized': normalize_street_name(matched_street) if matched_street else None,
            'matched_method': match_method
        })
    
    result_df = pd.DataFrame(matches)
    logger.info(f"Matched {matched_count} buildings to streets ({unmatched_count} unmatched)")
    logger.info(f"Match methods: {result_df['matched_method'].value_counts().to_dict()}")
    
    return result_df


def create_street_clusters(
    buildings: gpd.GeoDataFrame,
    building_street_map: pd.DataFrame,
    streets: gpd.GeoDataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Create street-based clusters from building-to-street mappings.
    
    Args:
        buildings: GeoDataFrame with building data
        building_street_map: DataFrame from match_buildings_to_streets() with columns:
            ['building_id', 'street_name', 'street_normalized', 'matched_method']
        streets: GeoDataFrame with street data
        
    Returns:
        Tuple of (building_cluster_map, street_clusters)
        - building_cluster_map: DataFrame with ['building_id', 'cluster_id']
        - street_clusters: DataFrame with cluster metadata
    """
    # Get street name column from streets
    street_name_col = None
    for col in ['street_name', 'name', 'strasse', 'str']:
        if col in streets.columns:
            street_name_col = col
            break
    
    if street_name_col is None:
        raise ValueError("Streets GeoDataFrame must have a street name column")
    
    # Group buildings by street
    street_groups = building_street_map.groupby('street_name')
    
    building_cluster_records = []
    street_cluster_records = []
    cluster_number = 1
    
    for street_name, group in street_groups:
        if pd.isna(street_name) or street_name is None:
            continue
        
        # Create cluster ID: ST{number}_{STREET_NAME}
        # Normalize street name for cluster ID (uppercase, replace spaces/special chars with underscores)
        cluster_name = normalize_street_name(street_name)
        cluster_name_clean = re.sub(r'[^A-Z0-9]', '_', cluster_name)
        cluster_name_clean = re.sub(r'_+', '_', cluster_name_clean).strip('_')
        cluster_id = f"ST{cluster_number:03d}_{cluster_name_clean}"
        
        building_ids_in_cluster = group['building_id'].tolist()
        
        # Add to building_cluster_map
        for building_id in building_ids_in_cluster:
            building_cluster_records.append({
                'building_id': building_id,
                'cluster_id': cluster_id
            })
        
        # Get buildings for this cluster
        cluster_buildings = buildings[buildings['building_id'].isin(building_ids_in_cluster)]
        
        # Calculate plant location (centroid of cluster buildings)
        if len(cluster_buildings) > 0:
            plant_centroid = cluster_buildings.geometry.union_all().centroid
            plant_x = float(plant_centroid.x)
            plant_y = float(plant_centroid.y)

        # Get street geometry (union of all segments with this name)
        street_rows = streets[streets[street_name_col] == street_name]
        if len(street_rows) > 0:
            # Safe union for modern Geopandas (union_all) or fallback
            try:
                if hasattr(street_rows.geometry, "union_all"):
                    cluster_geom = street_rows.geometry.union_all()
                else:
                    cluster_geom = street_rows.geometry.unary_union
            except Exception:
                 cluster_geom = street_rows.geometry.iloc[0]
            
            # Calculate plant location if not set from buildings
            if len(cluster_buildings) == 0:
                 midpoint = cluster_geom.interpolate(0.5, normalized=True)
                 plant_x = float(midpoint.x)
                 plant_y = float(midpoint.y)
        else:
            cluster_geom = None
            if len(cluster_buildings) == 0:
                plant_x = 0.0
                plant_y = 0.0

        # Add to street_clusters
        street_cluster_records.append({
            'cluster_id': cluster_id,
            'cluster_name': cluster_name,
            'plant_node_id': None,  # Will be set during network building
            'plant_x': plant_x,
            'plant_y': plant_y,
            'building_count': len(building_ids_in_cluster),
            'geometry': cluster_geom
        })
        
        cluster_number += 1
    
    building_cluster_map = pd.DataFrame(building_cluster_records)
    street_clusters_df = pd.DataFrame(street_cluster_records)
    
    # Convert to GeoDataFrame
    if not street_clusters_df.empty and 'geometry' in street_clusters_df.columns:
        street_clusters = gpd.GeoDataFrame(
            street_clusters_df, 
            geometry='geometry',
            crs=streets.crs
        )
    else:
        street_clusters = gpd.GeoDataFrame(
            street_clusters_df, 
            geometry=gpd.GeoSeries([], crs=streets.crs),
            crs=streets.crs
        )

    logger.info(f"Created {len(street_clusters)} street-based clusters")
    logger.info(f"Mapped {len(building_cluster_map)} buildings to clusters")
    
    return building_cluster_map, street_clusters


# ============================================================================
# Writer Functions
# ============================================================================

def save_design_topn_json(
    design_topn_dict: Dict,
    path: Union[str, Path],
    indent: int = 2
) -> None:
    """
    Save design hour and top-N hours dictionary to JSON file.
    
    Ensures:
    - Directory is created if needed
    - JSON is properly formatted with indentation
    - Schema matches what loaders expect
    
    Args:
        design_topn_dict: Dictionary from compute_design_and_topn()
            Expected structure:
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
        path: Path to output JSON file
        indent: JSON indentation (default: 2)
        
    Raises:
        ValueError: If design_topn_dict doesn't have expected structure
        IOError: If file cannot be written
    """
    path = Path(path)
    
    # Validate structure
    if not isinstance(design_topn_dict, dict):
        raise ValueError("design_topn_dict must be a dictionary")
    
    if "clusters" not in design_topn_dict:
        raise ValueError("design_topn_dict must contain 'clusters' key")
    
    if "meta" not in design_topn_dict:
        raise ValueError("design_topn_dict must contain 'meta' key")
    
    # Create directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write JSON file
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(design_topn_dict, f, indent=indent, ensure_ascii=False)
    
    logger.info(f"Saved design_topn JSON to {path}")


def save_cluster_summary_parquet(
    summary_df: pd.DataFrame,
    path: Union[str, Path],
    compression: str = 'snappy',
    index: bool = False
) -> None:
    """
    Save cluster summary DataFrame to parquet file.
    
    Ensures:
    - Directory is created if needed
    - Compression is applied (default: snappy)
    - Column order is preserved
    - Schema matches what loaders expect
    
    Args:
        summary_df: DataFrame from create_cluster_summary()
            Expected columns:
            - cluster_id
            - n_buildings
            - annual_heat_kwh_a
            - design_hour
            - design_load_kw
            - topn_mean_kw
            - topn_min_kw
            - topn_max_kw
        path: Path to output parquet file
        compression: Compression algorithm (default: 'snappy')
        index: Whether to write index (default: False)
        
    Raises:
        ValueError: If summary_df doesn't have required columns
        IOError: If file cannot be written
    """
    path = Path(path)
    
    # Validate required columns
    required_cols = [
        'cluster_id',
        'n_buildings',
        'annual_heat_kwh_a',
        'design_hour',
        'design_load_kw'
    ]
    
    missing_cols = [col for col in required_cols if col not in summary_df.columns]
    if missing_cols:
        raise ValueError(
            f"summary_df missing required columns: {missing_cols}. "
            f"Found columns: {list(summary_df.columns)}"
        )
    
    # Create directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write parquet file
    summary_df.to_parquet(
        path,
        engine='pyarrow',
        compression=compression,
        index=index,
        write_statistics=True
    )
    
    logger.info(f"Saved cluster summary to {path}")
