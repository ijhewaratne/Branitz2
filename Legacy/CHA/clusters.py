"""
Clustering module for data segmentation.
Handles clustering of similar energy systems or profiles.
"""

import json
import warnings
from pathlib import Path
from typing import Dict, Union

import pandas as pd


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
    return summary_df


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


# ============================================================================
# Legacy Functions (kept for backward compatibility)
# ============================================================================

def perform_clustering(data, n_clusters=None):
    """
    Perform clustering on data.
    
    Args:
        data: Data to cluster
        n_clusters: Number of clusters (optional, auto-detect if None)
        
    Returns:
        Cluster labels and centroids
    """
    # TODO: Implement clustering algorithm
    pass


def get_cluster_characteristics(cluster_data):
    """
    Extract characteristics of each cluster.
    
    Args:
        cluster_data: Clustered data
        
    Returns:
        Dictionary of cluster characteristics
    """
    # TODO: Implement cluster characterization
    pass


def assign_to_cluster(data_point, clusters):
    """
    Assign a data point to the nearest cluster.
    
    Args:
        data_point: Data point to assign
        clusters: Cluster model/centroids
        
    Returns:
        Cluster assignment
    """
    # TODO: Implement cluster assignment
    pass

