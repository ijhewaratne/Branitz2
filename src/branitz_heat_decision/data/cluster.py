import geopandas as gpd
import pandas as pd
import numpy as np
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)

def aggregate_cluster_profiles(
    hourly_profiles: pd.DataFrame,
    cluster_map: pd.DataFrame,
    cluster_id_col: str = 'cluster_id'
) -> Dict[str, pd.Series]:
    """
    Aggregate building-level profiles to cluster level.
    
    Args:
        hourly_profiles: DataFrame (8760, n_buildings)
        cluster_map: DataFrame with ['building_id', cluster_id_col]
        cluster_id_col: Name of cluster ID column
        
    Returns:
        Dict: {cluster_id: pd.Series(8760)} with aggregated heat demand (kW_th)
    """
    # Validate cluster_map
    if 'building_id' not in cluster_map.columns:
        raise ValueError("cluster_map must have 'building_id' column")
    
    if cluster_id_col not in cluster_map.columns:
        raise ValueError(f"cluster_map must have '{cluster_id_col}' column")
    
    # Find cluster IDs
    cluster_ids = cluster_map[cluster_id_col].unique()
    
    aggregated = {}
    for cluster_id in cluster_ids:
        building_ids_in_cluster = cluster_map.loc[
            cluster_map[cluster_id_col] == cluster_id,
            'building_id'
        ].values
        
        # Filter to buildings that exist in hourly_profiles
        building_ids_in_cluster = [
            bid for bid in building_ids_in_cluster 
            if bid in hourly_profiles.columns
        ]
        
        if not building_ids_in_cluster:
            logger.warning(f"No buildings found for cluster {cluster_id}")
            continue
        
        # Sum profiles
        cluster_profile = hourly_profiles[building_ids_in_cluster].sum(axis=1)
        cluster_profile.name = cluster_id
        aggregated[cluster_id] = cluster_profile
    
    logger.info(f"Aggregated profiles for {len(aggregated)} clusters")
    return aggregated


def compute_design_and_topn(
    cluster_profiles: Dict[str, pd.Series],
    topn: int = 10
) -> Dict[str, Any]:
    """
    Compute design hour and top-N hours for each cluster.
    
    Args:
        cluster_profiles: Dict from aggregate_cluster_profiles()
        topn: Number of top hours to extract
        
    Returns:
        Dict: {
            "clusters": {
                "cluster_id": {
                    "design_hour": int,
                    "design_load_kw": float,
                    "topn_hours": List[int],
                    "topn_loads_kw": List[float]
                }
            },
            "meta": {...}
        }
    """
    result = {
        "clusters": {},
        "meta": {
            "topn": topn,
            "created_at": pd.Timestamp.now().isoformat(),
            "version": "1.0"
        }
    }
    
    for cluster_id, profile in cluster_profiles.items():
        if len(profile) != 8760:
            raise ValueError(f"Profile for {cluster_id} must have 8760 rows, got {len(profile)}")
        
        # Sort by load (descending)
        sorted_hours = profile.sort_values(ascending=False)
        
        # Design hour is the maximum
        design_hour = sorted_hours.index[0]
        design_load_kw = sorted_hours.iloc[0]
        
        # Top-N hours
        topn_hours = sorted_hours.index[:topn].tolist()
        topn_loads_kw = sorted_hours.iloc[:topn].values.tolist()
        
        result["clusters"][cluster_id] = {
            "design_hour": int(design_hour),
            "design_load_kw": float(design_load_kw),
            "topn_hours": [int(h) for h in topn_hours],
            "topn_loads_kw": [float(l) for l in topn_loads_kw]
        }
    
    logger.info(f"Computed design/topn for {len(result['clusters'])} clusters")
    return result


def create_cluster_summary(
    cluster_profiles: Dict[str, pd.Series],
    cluster_map: pd.DataFrame,
    buildings: gpd.GeoDataFrame,
    design_topn: Dict[str, Any]
) -> pd.DataFrame:
    """
    Create summary table with one row per cluster.
    
    Args:
        cluster_profiles: From aggregate_cluster_profiles()
        cluster_map: From load_building_cluster_map()
        buildings: From load_buildings_geojson()
        design_topn: From compute_design_and_topn()
        
    Returns:
        DataFrame: one row per cluster with aggregated metrics
    """
    summaries = []
    
    for cluster_id in cluster_profiles.keys():
        # Get buildings in cluster
        building_ids = cluster_map.loc[
            cluster_map['cluster_id'] == cluster_id,
            'building_id'
        ].values
        
        cluster_buildings = buildings[buildings['building_id'].isin(building_ids)]
        
        # Sum annual heat demand
        annual_heat_kwh_a = cluster_buildings['annual_heat_demand_kwh_a'].sum()
        
        # Get design info
        design_info = design_topn["clusters"][cluster_id]
        
        # Get topn loads
        topn_loads = np.array(design_info['topn_loads_kw'])
        
        summaries.append({
            'cluster_id': cluster_id,
            'n_buildings': len(cluster_buildings),
            'annual_heat_kwh_a': annual_heat_kwh_a,
            'design_hour': design_info['design_hour'],
            'design_load_kw': design_info['design_load_kw'],
            'topn_mean_kw': topn_loads.mean(),
            'topn_min_kw': topn_loads.min(),
            'topn_max_kw': topn_loads.max(),
        })
    
    summary_df = pd.DataFrame(summaries)
    summary_df = summary_df.set_index('cluster_id')
    
    logger.info(f"Created summary for {len(summary_df)} clusters")
    return summary_df